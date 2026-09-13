"""Cached WinMM playback for the repository's six current button cues."""

from __future__ import annotations

import copy
import ctypes
import hashlib
import math
import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path


BUTTONS = ("CIRCLE", "X", "SQUARE", "TRIANGLE", "L1", "R1")
PAN_POSITIONS = {
    "TRIANGLE": -0.35,
    "L1": -0.6,
    "SQUARE": -0.8,
    "X": 0.35,
    "R1": 0.6,
    "CIRCLE": 0.8,
}

SND_ASYNC = 0x0001
SND_NODEFAULT = 0x0002
SND_MEMORY = 0x0004
PLAY_FLAGS = SND_ASYNC | SND_NODEFAULT | SND_MEMORY

MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 192_000
MAX_DURATION_MS = 250


class CuePreparationError(ValueError):
    """A source WAV is not in the supported earcon PCM format."""


@dataclass(frozen=True)
class WavInfo:
    sample_rate: int
    channels: int
    bits_per_sample: int
    frames: int
    block_align: int
    data_offset: int
    data_size: int

    @property
    def duration_ms(self) -> float:
        return self.frames * 1000.0 / self.sample_rate


@dataclass(frozen=True)
class PreparedWav:
    wav_bytes: bytes
    source_info: WavInfo
    output_info: WavInfo
    leading_silence_frames: int
    pan: float | None


def parse_pcm_wav(data: bytes) -> WavInfo:
    """Validate the uncompressed mono/stereo PCM subset used by earcons.lua."""
    if not isinstance(data, bytes) or len(data) < 12:
        raise CuePreparationError("file is shorter than a RIFF/WAVE header")
    if data[:4] != b"RIFF":
        raise CuePreparationError("missing RIFF header")
    if data[8:12] != b"WAVE":
        raise CuePreparationError("RIFF file is not a WAVE file")

    riff_size = struct.unpack_from("<I", data, 4)[0]
    if riff_size < 4:
        raise CuePreparationError("invalid RIFF size")
    riff_end = 8 + riff_size
    if riff_end > len(data):
        raise CuePreparationError("RIFF data is truncated")

    fmt = None
    data_chunk = None
    cursor = 12
    while cursor < riff_end:
        if cursor + 8 > riff_end:
            raise CuePreparationError("truncated chunk header")
        chunk_id = data[cursor : cursor + 4]
        chunk_size = struct.unpack_from("<I", data, cursor + 4)[0]
        chunk_start = cursor + 8
        chunk_end = chunk_start + chunk_size
        if chunk_end > riff_end:
            raise CuePreparationError("chunk extends beyond RIFF data")

        if chunk_id == b"fmt " and fmt is None:
            if chunk_size < 16:
                raise CuePreparationError("fmt chunk is shorter than 16 bytes")
            fmt = struct.unpack_from("<HHIIHH", data, chunk_start)
        elif chunk_id == b"data" and data_chunk is None:
            data_chunk = (chunk_start, chunk_size)

        cursor = chunk_end + (chunk_size & 1)

    if cursor != riff_end:
        raise CuePreparationError("RIFF chunk layout is malformed")
    if fmt is None:
        raise CuePreparationError("missing fmt chunk")
    if data_chunk is None:
        raise CuePreparationError("missing data chunk")

    audio_format, channels, sample_rate, byte_rate, block_align, bits = fmt
    if audio_format != 1:
        raise CuePreparationError("audio format is not uncompressed PCM")
    if channels not in (1, 2):
        raise CuePreparationError("channels must be mono (1) or stereo (2)")
    if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
        raise CuePreparationError(
            f"sample rate must be between {MIN_SAMPLE_RATE} and {MAX_SAMPLE_RATE} Hz"
        )
    if bits not in (16, 24):
        raise CuePreparationError("bits per sample must be 16 or 24")

    expected_align = channels * (bits // 8)
    if block_align != expected_align:
        raise CuePreparationError("block alignment does not match PCM channels and bit depth")
    if byte_rate != sample_rate * block_align:
        raise CuePreparationError("byte rate does not match the PCM format")

    data_offset, data_size = data_chunk
    if data_size == 0 or data_size % block_align:
        raise CuePreparationError("data chunk does not contain whole PCM frames")
    frames = data_size // block_align
    if frames * 1000 > sample_rate * MAX_DURATION_MS:
        duration_ms = frames * 1000.0 / sample_rate
        raise CuePreparationError(
            f"duration is {duration_ms:.1f} ms; maximum is {MAX_DURATION_MS} ms"
        )

    return WavInfo(
        sample_rate=sample_rate,
        channels=channels,
        bits_per_sample=bits,
        frames=frames,
        block_align=block_align,
        data_offset=data_offset,
        data_size=data_size,
    )


def _canonical_pcm16_wav(sample_rate: int, channels: int, pcm_data: bytes) -> bytes:
    block_align = channels * 2
    riff_size = 36 + len(pcm_data)
    if riff_size > 0xFFFFFFFF:
        raise CuePreparationError("prepared WAV is too large for a RIFF file")
    fmt = struct.pack(
        "<HHIIHH",
        1,
        channels,
        sample_rate,
        sample_rate * block_align,
        block_align,
        16,
    )
    return b"".join(
        (
            b"RIFF",
            struct.pack("<I", riff_size),
            b"WAVEfmt ",
            struct.pack("<I", 16),
            fmt,
            b"data",
            struct.pack("<I", len(pcm_data)),
            pcm_data,
        )
    )


def _make_placeholder_handoff_wav() -> bytes:
    """Create a short centered placeholder chirp without a user sound file."""
    sample_rate = 44_100
    frames = round(sample_rate * 0.060)
    split = frames // 2
    fade_frames = round(sample_rate * 0.002)
    amplitude = 0.18 * 1.30 * 32767
    pcm = bytearray(frames * 4)

    for frame in range(frames):
        if frame < split:
            phase = 2.0 * math.pi * 660.0 * frame / sample_rate
        else:
            phase = (
                2.0 * math.pi * 660.0 * split / sample_rate
                + 2.0 * math.pi * 990.0 * (frame - split) / sample_rate
            )
        envelope = min(
            1.0,
            (frame + 1) / fade_frames,
            (frames - frame) / fade_frames,
        )
        sample = _clamp_pcm16(amplitude * envelope * math.sin(phase))
        struct.pack_into("<hh", pcm, frame * 4, sample, sample)

    return _canonical_pcm16_wav(sample_rate, 2, bytes(pcm))


def _round_half_away_from_zero(value: float) -> int:
    if value >= 0:
        return math.floor(value + 0.5)
    return math.ceil(value - 0.5)


def _clamp_pcm16(value: float) -> int:
    return max(-32768, min(32767, _round_half_away_from_zero(value)))


def _apply_pcm16_volume(data: bytes, info: WavInfo, volume_percent: int) -> bytes:
    """Scale already-prepared PCM16 samples with integer percent gain."""
    if volume_percent == 100:
        return data

    scaled = bytearray(data)
    start = info.data_offset
    end = start + info.data_size
    if volume_percent == 0:
        scaled[start:end] = b"\0" * info.data_size
        return bytes(scaled)

    for offset in range(start, end, 2):
        sample = struct.unpack_from("<h", data, offset)[0]
        product = sample * volume_percent
        if product >= 0:
            sample = (product + 50) // 100
        else:
            sample = -(((-product) + 50) // 100)
        struct.pack_into("<h", scaled, offset, max(-32768, min(32767, sample)))
    return bytes(scaled)


def _convert_24_to_16(data: bytes, info: WavInfo) -> bytes:
    pcm = bytearray(info.frames * info.channels * 2)
    src = info.data_offset
    dst = 0
    for _ in range(info.frames * info.channels):
        sample = data[src] | (data[src + 1] << 8) | (data[src + 2] << 16)
        if sample & 0x800000:
            sample -= 0x1000000
        # This is the signed divide-by-256 and half-away-from-zero rounding
        # used by earcons.lua when reducing 24-bit samples to PCM16.
        if sample >= 0:
            sample16 = (sample + 128) // 256
        else:
            sample16 = -(((-sample) + 128) // 256)
        sample16 = max(-32768, min(32767, sample16))
        struct.pack_into("<h", pcm, dst, sample16)
        src += 3
        dst += 2
    return _canonical_pcm16_wav(info.sample_rate, info.channels, bytes(pcm))


def _apply_equal_power_pan(data: bytes, info: WavInfo, pan: float) -> bytes:
    if not math.isfinite(pan) or not -1.0 <= pan <= 1.0:
        raise ValueError("pan must be a finite value from -1.0 to 1.0")
    angle = (pan + 1.0) * math.pi * 0.25
    left_gain = math.cos(angle)
    right_gain = math.sin(angle)
    pcm = bytearray(info.frames * 4)
    src = info.data_offset
    dst = 0

    for _ in range(info.frames):
        left = struct.unpack_from("<h", data, src)[0]
        if info.channels == 2:
            right = struct.unpack_from("<h", data, src + 2)[0]
            sample = (left + right) * 0.5
            src += 4
        else:
            sample = left
            src += 2
        struct.pack_into("<hh", pcm, dst, _clamp_pcm16(sample * left_gain),
                         _clamp_pcm16(sample * right_gain))
        dst += 4

    return _canonical_pcm16_wav(info.sample_rate, 2, bytes(pcm))


def leading_silence_frames(data: bytes, info: WavInfo | None = None) -> int:
    """Count initial frames whose PCM samples are all zero."""
    info = parse_pcm_wav(data) if info is None else info
    cursor = info.data_offset
    count = 0
    for _ in range(info.frames):
        frame_end = cursor + info.block_align
        if any(data[cursor:frame_end]):
            break
        count += 1
        cursor = frame_end
    return count


def preprocess_wav(data: bytes, pan: float | None = None) -> PreparedWav:
    """Validate and prepare a cue, matching the Lua 24-bit/panning pipeline."""
    source_info = parse_pcm_wav(data)
    prepared = data
    if source_info.bits_per_sample == 24:
        prepared = _convert_24_to_16(data, source_info)
    if pan is not None:
        pcm16_info = parse_pcm_wav(prepared)
        prepared = _apply_equal_power_pan(prepared, pcm16_info, pan)
    output_info = parse_pcm_wav(prepared)
    if output_info.bits_per_sample != 16:
        raise CuePreparationError("prepared cue is not PCM16")
    return PreparedWav(
        wav_bytes=prepared,
        source_info=source_info,
        output_info=output_info,
        leading_silence_frames=leading_silence_frames(prepared, output_info),
        pan=pan,
    )


def _apply_prepared_volume(prepared: PreparedWav, volume_percent: int) -> PreparedWav:
    """Apply volume after conversion and panning, then refresh output metadata."""
    if volume_percent == 100:
        return prepared
    wav_bytes = _apply_pcm16_volume(
        prepared.wav_bytes, prepared.output_info, volume_percent
    )
    output_info = parse_pcm_wav(wav_bytes)
    return PreparedWav(
        wav_bytes=wav_bytes,
        source_info=prepared.source_info,
        output_info=output_info,
        leading_silence_frames=leading_silence_frames(wav_bytes, output_info),
        pan=prepared.pan,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _load_pan_setting(root: Path) -> tuple[bool, str | None]:
    path = root / "logs" / "demo-panning.txt"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return False, None
    text = raw.decode("utf-8", errors="replace")
    return text.strip().lower() == "on", _sha256(raw)


class CueSounds:
    """Prepare session-local WAV copies and play them from cached memory.

    All source reads and conversions happen in ``__init__``.  With cues
    enabled, WinMM is primed with a retained silent WAV before this object is
    returned, so callers can construct it before resuming gameplay.  Each cue
    call goes directly to PlaySoundA with asynchronous in-memory flags; there
    is no Python playback queue.
    """

    def __init__(self, root, session_dir, enabled: bool = True, output_name='ProFX 1-2 (ProFX)',
                 handoff_enabled: bool = False, *, volume_percent: int = 100):
        if isinstance(volume_percent, bool) or not isinstance(volume_percent, int):
            raise TypeError("volume_percent must be an integer (not bool)")
        if not 0 <= volume_percent <= 200:
            raise ValueError("volume_percent must be from 0 to 200")

        self.root = Path(root).resolve()
        session = Path(session_dir)
        if not session.is_absolute():
            session = self.root / session
        logs_root = (self.root / "logs").resolve()
        self.session_dir = session.resolve()
        if self.session_dir == logs_root or not _inside(self.session_dir, logs_root):
            raise ValueError("Cue WAV exports must be inside a session under the ignored logs directory.")
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = self.session_dir.resolve()
        if self.session_dir == logs_root or not _inside(self.session_dir, logs_root):
            raise ValueError("Cue WAV exports must be inside a session under the ignored logs directory.")

        self.enabled = bool(enabled)
        self.handoff_enabled = bool(handoff_enabled)
        self.volume_percent = volume_percent
        self.pan_enabled, self._pan_setting_sha256 = _load_pan_setting(self.root)
        self.output_dir = self.session_dir / "cue-wavs"
        if self.output_dir.exists():
            resolved_output = self.output_dir.resolve()
            if not _inside(resolved_output, self.session_dir):
                raise ValueError("Cue WAV output directory resolves outside its session.")
            raise FileExistsError(f"Cue WAV output directory already exists: {self.output_dir}")

        sources = {}
        for button in BUTTONS:
            source_path = self.root / "sounds" / f"{button.lower()}.wav"
            resolved_source = source_path.resolve()
            if not _inside(resolved_source, self.root):
                raise ValueError(f"Cue source resolves outside the repository: {source_path}")
            try:
                source_bytes = source_path.read_bytes()
            except OSError as exc:
                raise CuePreparationError(f"Could not read cue source {source_path}: {exc}") from exc

            pan = PAN_POSITIONS[button] if self.pan_enabled else None
            try:
                prepared = preprocess_wav(source_bytes, pan=pan)
                prepared = _apply_prepared_volume(prepared, self.volume_percent)
            except (CuePreparationError, ValueError) as exc:
                raise CuePreparationError(f"Invalid cue source {source_path}: {exc}") from exc
            sources[button] = (source_path, source_bytes, prepared)

        handoff_source = _make_placeholder_handoff_wav() if self.handoff_enabled else None
        handoff_prepared = (
            _apply_prepared_volume(preprocess_wav(handoff_source), self.volume_percent)
            if handoff_source is not None
            else None
        )

        self.output_dir.mkdir(parents=False, exist_ok=False)
        if not _inside(self.output_dir.resolve(), self.session_dir):
            raise ValueError("Cue WAV output directory resolves outside its session.")

        self._buffers = {}
        self._silence_buffer = None
        self._winmm = None
        self._play_sound = None
        self._prime_result = {
            "before_ns": None,
            "after_ns": None,
            "result": False,
            "status": "disabled",
        }
        sound_manifest = {}

        for button in BUTTONS:
            source_path, source_bytes, prepared = sources[button]
            output_path = self.output_dir / f"{button.lower()}.wav"
            with output_path.open("xb") as stream:
                stream.write(prepared.wav_bytes)

            info = prepared.output_info
            source_info = prepared.source_info
            sound_manifest[button] = {
                "source_path": source_path.relative_to(self.root).as_posix(),
                "prepared_path": output_path.relative_to(self.session_dir).as_posix(),
                "source_sha256": _sha256(source_bytes),
                "output_sha256": _sha256(prepared.wav_bytes),
                "sample_rate_hz": info.sample_rate,
                "channels": info.channels,
                "bits_per_sample": info.bits_per_sample,
                "original_channels": source_info.channels,
                "original_bits_per_sample": source_info.bits_per_sample,
                "frames": info.frames,
                "duration_ms": info.duration_ms,
                "duration_seconds": info.frames / info.sample_rate,
                "leading_silence_frames": prepared.leading_silence_frames,
                "pan_position": PAN_POSITIONS[button],
                "pan_applied": self.pan_enabled,
            }
            if self.enabled:
                buffer = ctypes.create_string_buffer(prepared.wav_bytes)
                self._buffers[button] = (buffer, ctypes.cast(buffer, ctypes.c_void_p))

        if handoff_prepared is not None:
            handoff_path = self.output_dir / "handoff.wav"
            with handoff_path.open("xb") as stream:
                stream.write(handoff_prepared.wav_bytes)
            info = handoff_prepared.output_info
            handoff_manifest = {
                "enabled": True,
                "source": "generated_placeholder",
                "description": "60 ms centered two-tone chirp (660 Hz then 990 Hz)",
                "prepared_path": handoff_path.relative_to(self.session_dir).as_posix(),
                "source_sha256": _sha256(handoff_source),
                "output_sha256": _sha256(handoff_prepared.wav_bytes),
                "sample_rate_hz": info.sample_rate,
                "channels": info.channels,
                "bits_per_sample": info.bits_per_sample,
                "frames": info.frames,
                "duration_ms": info.duration_ms,
                "centered": True,
                "playback_policy": "Independent overlay on the shared WASAPI cue stream; no queue",
            }
        else:
            handoff_manifest = {
                "enabled": False,
                "source": None,
                "prepared_path": None,
                "playback_policy": "disabled",
            }

        self._manifest = {
            "schema_version": 1,
            "backend": {
                "name": "WinMM PlaySoundA",
                "enabled": self.enabled,
                "flags": PLAY_FLAGS,
                "flags_hex": f"0x{PLAY_FLAGS:02x}",
                "flags_names": ["SND_ASYNC", "SND_NODEFAULT", "SND_MEMORY"],
                "playback_policy": "direct asynchronous calls; no software queue",
                "prime": self._prime_result,
            },
            "pan": {
                "enabled": self.pan_enabled,
                "mapping": "equal-power",
                "settings_path": "logs/demo-panning.txt",
                "settings_sha256": self._pan_setting_sha256,
                "positions": dict(PAN_POSITIONS),
            },
            "settings": {
                "handoff_enabled": self.handoff_enabled,
                "volume_percent": self.volume_percent,
            },
            "handoff": handoff_manifest,
            "prepared_directory": self.output_dir.relative_to(self.session_dir).as_posix(),
            "sounds": sound_manifest,
        }

        self._output = None
        if self.enabled:
            from duckstation_audio_output import WasapiCueOutput
            self._output = WasapiCueOutput(output_name,
                {button: prepared.wav_bytes for button, (_, _, prepared) in sources.items()},
                handoff_wav=(handoff_prepared.wav_bytes if handoff_prepared is not None else None))

    @property
    def manifest(self) -> dict:
        result=copy.deepcopy(self._manifest)
        if self._output is not None:result['backend']=self._output.manifest
        return result

    def _initialize_winmm(self):
        if os.name != "nt":
            raise OSError("WinMM PlaySoundA is only available on Windows.")
        try:
            self._winmm = ctypes.WinDLL("winmm", use_last_error=True)
            self._play_sound = self._winmm.PlaySoundA
            self._play_sound.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32)
            self._play_sound.restype = ctypes.c_int
        except (AttributeError, OSError) as exc:
            raise OSError(f"Could not load WinMM PlaySoundA: {exc}") from exc

    def _call_play_sound(self, pointer, flags: int) -> dict:
        ctypes.set_last_error(0)
        before_ns = time.perf_counter_ns()
        try:
            winmm_return = int(self._play_sound(pointer, None, flags))
            after_ns = time.perf_counter_ns()
            last_error = ctypes.get_last_error()
        except Exception as exc:  # Keep a native playback failure out of cue callbacks.
            after_ns = time.perf_counter_ns()
            return {
                "before_ns": before_ns,
                "after_ns": after_ns,
                "result": False,
                "status": "error",
                "error": str(exc),
            }
        result = winmm_return != 0
        return {
            "before_ns": before_ns,
            "after_ns": after_ns,
            "result": result,
            "status": "started" if result else "error",
            "winmm_return": winmm_return,
            "last_error": last_error if not result else 0,
            **({} if result else {"error": "PlaySoundA returned FALSE"}),
        }

    def _prime_silence(self):
        triangle = self.output_dir / "triangle.wav"
        prepared = triangle.read_bytes()
        info = parse_pcm_wav(prepared)
        start = info.data_offset
        end = start + info.data_size
        silence = prepared[:start] + (b"\0" * info.data_size) + prepared[end:]
        self._silence_buffer = ctypes.create_string_buffer(silence)
        result = self._call_play_sound(ctypes.cast(self._silence_buffer, ctypes.c_void_p), PLAY_FLAGS)
        result["status"] = "primed" if result["result"] else "error"
        self._prime_result = result
        self._manifest["backend"]["prime"] = result
        if not result["result"]:
            raise OSError(f"Could not prime WinMM with silence: {result.get('error', 'unknown error')}")

    def play(self, button: str) -> dict:
        if self._output is not None:return self._output.play(button)
        name = button.strip().upper() if isinstance(button, str) else ""
        if name not in BUTTONS:
            before_ns = time.perf_counter_ns()
            after_ns = time.perf_counter_ns()
            return {
                "before_ns": before_ns,
                "after_ns": after_ns,
                "result": False,
                "status": "unknown_button",
                "error": f"Unknown button: {button!r}",
            }
        if not self.enabled:
            before_ns = time.perf_counter_ns()
            after_ns = time.perf_counter_ns()
            return {
                "before_ns": before_ns,
                "after_ns": after_ns,
                "result": False,
                "status": "disabled",
            }
        buffer = self._buffers.get(name)
        if buffer is None or self._play_sound is None:
            before_ns = time.perf_counter_ns()
            after_ns = time.perf_counter_ns()
            return {
                "before_ns": before_ns,
                "after_ns": after_ns,
                "result": False,
                "status": "unavailable",
                "error": "Cue audio was not initialized",
            }
        return self._call_play_sound(buffer[1], PLAY_FLAGS)

    def play_handoff(self) -> dict:
        if not self.handoff_enabled or not self.enabled:
            before_ns = time.perf_counter_ns()
            after_ns = time.perf_counter_ns()
            return {
                "before_ns": before_ns,
                "after_ns": after_ns,
                "result": False,
                "status": "disabled",
            }
        if self._output is None:
            before_ns = time.perf_counter_ns()
            after_ns = time.perf_counter_ns()
            return {
                "before_ns": before_ns,
                "after_ns": after_ns,
                "result": False,
                "status": "unavailable",
                "error": "Handoff cue audio was not initialized",
            }
        return self._output.play_handoff()

    def stop(self) -> dict:
        if getattr(self,'_output',None) is not None:return self._output.stop()
        if not self.enabled or self._play_sound is None:
            before_ns = time.perf_counter_ns()
            after_ns = time.perf_counter_ns()
            return {
                "before_ns": before_ns,
                "after_ns": after_ns,
                "result": False,
                "status": "disabled",
            }
        result = self._call_play_sound(None, 0)
        result["status"] = "stopped" if result["result"] else "error"
        return result

    def close(self):
        if self._output is not None:self._output.close()
        else:self.stop()
