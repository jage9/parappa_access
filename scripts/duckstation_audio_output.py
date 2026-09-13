"""One persistent, explicitly selected WASAPI cue stream; no playback queue."""
import array
import copy
import io
from pathlib import Path
import sys
import struct
import threading
import time
import wave

def render_pcm(wav_bytes, output_rate=44100):
    """Convert a prepared WAV to stereo PCM16 at ``output_rate``.

    Resampling is done before playback so the real-time callback only copies
    already prepared samples. Linear interpolation retains the cue's pitch
    and duration without an external audio dependency.
    """
    if not isinstance(output_rate, int) or output_rate <= 0:
        raise ValueError('output_rate must be a positive integer')
    with wave.open(io.BytesIO(wav_bytes),'rb') as wav:
        assert wav.getsampwidth()==2 and wav.getnchannels() in (1,2)
        rate=wav.getframerate();channels=wav.getnchannels()
        assert rate in (22050,44100),'Cue output supports prepared 22050/44100 Hz PCM'
        samples=array.array('h',wav.readframes(wav.getnframes()))
    frames=len(samples)//channels
    if not frames:return b''
    if channels==2 and output_rate==rate:
        return samples.tobytes()

    output_frames=round(frames*output_rate/rate)
    out=array.array('h')
    for i in range(output_frames):
        source_numerator=i*rate
        source_index,remainder=divmod(source_numerator,output_rate)
        if source_index>=frames-1:
            source_index=frames-1
            following_index=source_index
            remainder=0
        else:
            following_index=source_index+1
        for channel in range(2):
            source_channel=0 if channels==1 else channel
            first=samples[source_index*channels+source_channel]
            following=samples[following_index*channels+source_channel]
            weighted=first*(output_rate-remainder)+following*remainder
            # Truncate toward zero, matching the original 22.05-to-44.1
            # interpolation exactly, including negative PCM values.
            sample=(weighted//output_rate if weighted>=0
                    else -((-weighted)//output_rate))
            out.append(sample)
    return out.tobytes()


def mix_pcm16_stereo(base, overlay):
    """Sum two little-endian stereo PCM16 buffers and clip safely.

    Each buffer is at most the current callback's requested audio chunk. A
    shorter buffer is treated as silence after its end, allowing a brief
    handoff sound to overlay a longer teacher cue without replacing it.
    """
    if len(base) % 4 or len(overlay) % 4:
        raise ValueError('stereo PCM16 chunks must contain whole frames')
    if not base:return overlay
    if not overlay:return base
    size = max(len(base), len(overlay))
    if not size:
        return b''
    mixed = bytearray(size)
    for pos in range(0, size, 2):
        left = struct.unpack_from('<h', base, pos)[0] if pos < len(base) else 0
        right = struct.unpack_from('<h', overlay, pos)[0] if pos < len(overlay) else 0
        sample = max(-32768, min(32767, left + right))
        struct.pack_into('<h', mixed, pos, sample)
    return bytes(mixed)

class WasapiCueOutput:
    def __init__(self,output_name,prepared_wavs,handoff_wav=None):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/research/audio-python'))
        import pyaudiowpatch as audio
        self.audio=audio;self.pcm={};self.handoff_pcm=None
        self.lock=threading.Lock();self.active=None;self.offset=0;self.generation=0
        self.handoff_active=False;self.handoff_offset=0;self.handoff_generation=0
        self.callbacks=[];self.callback_count=0;self.dropped=0;self.statuses={}
        self.samples=0;self.closed=False;self.stream=None;self.device=None
        self.silence=bytes(65536)
        try:
            self.device=audio.PyAudio()
            matches=[]
            for i in range(self.device.get_device_count()):
                d=self.device.get_device_info_by_index(i)
                host=self.device.get_host_api_info_by_index(d['hostApi'])
                if d['name']==output_name and not d.get('isLoopbackDevice') and d['maxOutputChannels']>=2 and host['type']==audio.paWASAPI:
                    matches.append((d,host))
            if len(matches)!=1:raise RuntimeError('Expected one exact WASAPI cue output: '+output_name)
            info,host=matches[0]
            rates=[44100]
            try:
                default_rate=int(info['defaultSampleRate'])
            except (KeyError,TypeError,ValueError,OverflowError):
                default_rate=0
            if default_rate>0 and default_rate not in rates:rates.append(default_rate)
            sample_rate=None;rejected=[]
            for candidate in rates:
                try:
                    supported=self.device.is_format_supported(candidate,
                        output_device=info['index'],output_channels=2,
                        output_format=audio.paInt16)
                except ValueError as error:
                    rejected.append(str(error))
                    continue
                if supported:
                    sample_rate=candidate
                    break
                rejected.append('PortAudio reported the format unsupported')
            if sample_rate is None:
                candidates=' or '.join(str(rate) for rate in rates)+' Hz'
                detail=': '+'; '.join(rejected) if rejected else ''
                raise RuntimeError('Selected WASAPI cue output supports none of '+
                    candidates+' as PCM16 stereo'+detail)
            self.pcm={k:render_pcm(v,sample_rate) for k,v in prepared_wavs.items()}
            self.handoff_pcm=render_pcm(handoff_wav,sample_rate) if handoff_wav is not None else None
            self.metadata=dict(name='WASAPI persistent callback',device=info,host_api=host,
                rate=sample_rate,channels=2,requested_frames_per_buffer=256,
                policy='New teacher cue replaces its active cue; handoff overlays independently; no queue',
                handoff_enabled=self.handoff_pcm is not None,
                limitation='Callback and reported output latency are not physical speaker latency')
            self.stream=self.device.open(format=audio.paInt16,channels=2,rate=sample_rate,output=True,
                output_device_index=info['index'],frames_per_buffer=256,stream_callback=self._callback,start=False)
            self.metadata['reported_output_latency_seconds']=self.stream.get_output_latency()
            self.stream.start_stream()
        except BaseException:
            try:self.close()
            except BaseException:pass
            raise

    def _callback(self,data,frames,timing,status):
        stamp=time.perf_counter_ns();size=frames*4
        with self.lock:
            self.callback_count+=1
            self.statuses[status]=self.statuses.get(status,0)+1
            active=self.active;offset=self.offset
            handoff_active=self.handoff_active;handoff_offset=self.handoff_offset
            if active is not None:
                pcm=self.pcm[active];chunk=pcm[offset:offset+size];self.offset+=len(chunk)
                if self.offset>=len(pcm):self.active=None
            else:chunk=b''
            if handoff_active and self.handoff_pcm is not None:
                handoff_chunk=self.handoff_pcm[handoff_offset:handoff_offset+size]
                self.handoff_offset+=len(handoff_chunk)
                if self.handoff_offset>=len(self.handoff_pcm):self.handoff_active=False
            else:handoff_chunk=b''
            if (active is not None and offset==0) or (handoff_active and handoff_offset==0) or status:
                event=dict(perf_counter_ns=stamp,sample_index=self.samples,frames=frames,
                    button=active,generation=self.generation,
                    handoff=handoff_active,handoff_generation=self.handoff_generation,
                    status=status,time_info=dict(timing))
                if len(self.callbacks)<4096:self.callbacks.append(event)
                else:self.dropped+=1
            self.samples+=frames
        if handoff_chunk:chunk=mix_pcm16_stereo(chunk,handoff_chunk)
        return chunk+self.silence[:size-len(chunk)],self.audio.paContinue

    def play(self,button):
        before=time.perf_counter_ns()
        with self.lock:
            if self.closed:raise RuntimeError('Cue stream closed')
            if button not in self.pcm:raise ValueError('Unknown cue '+button)
            self.generation+=1;self.active=button;self.offset=0;generation=self.generation
        return dict(before_ns=before,after_ns=time.perf_counter_ns(),result=True,status='submitted',generation=generation)

    def play_handoff(self):
        before=time.perf_counter_ns()
        with self.lock:
            if self.closed:raise RuntimeError('Cue stream closed')
            if self.handoff_pcm is None:
                return dict(before_ns=before,after_ns=time.perf_counter_ns(),result=False,status='disabled')
            self.handoff_generation+=1;self.handoff_active=True;self.handoff_offset=0
            generation=self.handoff_generation
        return dict(before_ns=before,after_ns=time.perf_counter_ns(),result=True,status='submitted',generation=generation)

    def stop(self):
        before=time.perf_counter_ns()
        with self.lock:
            self.active=None;self.offset=0
            self.handoff_active=False;self.handoff_offset=0
        return dict(before_ns=before,after_ns=time.perf_counter_ns(),result=True,status='stopped')

    @property
    def manifest(self):
        with self.lock:
            return dict(copy.deepcopy(self.metadata),callbacks=copy.deepcopy(self.callbacks),
                        callback_count=self.callback_count,dropped_records=self.dropped,status_counts=dict(self.statuses),closed=self.closed)

    def close(self):
        if self.closed:return
        self.stop();self.closed=True
        try:
            if self.stream:
                try:self.stream.stop_stream()
                finally:self.stream.close()
        finally:
            if self.device is not None:self.device.terminate()
