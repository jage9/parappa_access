"""Match Windows playback endpoints across Cubeb, WASAPI cues and loopback."""
from dataclasses import dataclass
from pathlib import Path
import configparser
import sys
from duckstation_paths import duckstation_directory, SETTINGS_NAME


def _endpoints():
    import winreg
    path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render'
    result = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as render:
        for index in range(winreg.QueryInfoKey(render)[0]):
            identifier = winreg.EnumKey(render, index)
            with winreg.OpenKey(render, identifier) as device:
                if winreg.QueryValueEx(device, 'DeviceState')[0] != 1:
                    continue
                with winreg.OpenKey(device, 'Properties') as properties:
                    try:
                        name = winreg.QueryValueEx(properties, '{a45c254e-df1c-4efd-8020-67d146a850e0},14')[0]
                    except FileNotFoundError:
                        try:
                            description = winreg.QueryValueEx(properties, '{a45c254e-df1c-4efd-8020-67d146a850e0},2')[0]
                            interface = winreg.QueryValueEx(properties, '{b3f8fa53-0004-438e-9003-51a46e139bfc},6')[0]
                            name = f'{description} ({interface})'
                        except FileNotFoundError:
                            continue
                result.append((name, '{0.0.0.00000000}.' + identifier))
    return result

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AudioOutput:
    name: str
    endpoint_id: str
    loopback_name: str


def list_outputs():
    sys.path.insert(0, str(ROOT / 'tools/research/audio-python'))
    import pyaudiowpatch as audio
    endpoints = _endpoints()
    pa = audio.PyAudio()
    try:
        outputs = []
        loops = list(pa.get_loopback_device_info_generator())
        for name, endpoint_id in endpoints:
            matches = [pa.get_device_info_by_index(i) for i in range(pa.get_device_count())]
            matches = [d for d in matches if d['name'] == name
                       and not d.get('isLoopbackDevice') and d['maxOutputChannels'] >= 2
                       and pa.get_host_api_info_by_index(d['hostApi'])['type'] == audio.paWASAPI]
            loop = [d for d in loops if d['name'] == name + ' [Loopback]']
            # Exact names are required by the cue/recorder backends. Ambiguous
            # endpoints must not silently send the two streams to different cards.
            if len(matches) == len(loop) == 1 and sum(e[0] == name for e in endpoints) == 1:
                outputs.append(AudioOutput(name, endpoint_id, loop[0]['name']))
        return outputs
    finally:
        pa.terminate()


def current_device():
    config = configparser.ConfigParser(interpolation=None)
    config.read(duckstation_directory(ROOT) / SETTINGS_NAME)
    endpoint = config.get('Audio', 'OutputDevice', fallback='')
    devices = list_outputs()
    for device in devices:
        if device.endpoint_id == endpoint:
            return device.name
    if not endpoint:
        import pyaudiowpatch as audio
        pa = audio.PyAudio()
        try:
            host = pa.get_host_api_info_by_type(audio.paWASAPI)
            default = pa.get_device_info_by_index(host['defaultOutputDevice'])['name']
            return next((d.name for d in devices if d.name == default), None)
        finally:
            pa.terminate()
    return None


def system_default_device():
    """Return the exact supported output selected as the WASAPI system default."""
    sys.path.insert(0, str(ROOT / 'tools/research/audio-python'))
    import pyaudiowpatch as audio
    pa = audio.PyAudio()
    try:
        try:
            host = pa.get_host_api_info_by_type(audio.paWASAPI)
            index = host.get('defaultOutputDevice', -1)
            if index is None or int(index) < 0:
                return None
            name = pa.get_device_info_by_index(index).get('name')
        except (KeyError, OSError, ValueError):
            return None
    finally:
        pa.terminate()

    if not name:
        return None
    matches = [device for device in list_outputs() if device.name == name]
    return name if len(matches) == 1 else None


def resolve_preference(name):
    """Resolve an explicit saved output, or follow the Windows system default."""
    return name if isinstance(name, str) and name else system_default_device()


def resolve_output(name):
    matches = [d for d in list_outputs() if d.name == name]
    if len(matches) != 1:
        raise ValueError('Audio device unavailable. Choose an audio device in Settings.')
    return matches[0]
