"""Build a portable Windows source/runtime bundle, without local game artifacts."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
VERSION = '3.13.13'
URL = f'https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip'
# Published on https://www.python.org/downloads/release/python-31313/
SHA256 = '8766a8775746235e23cf5aee5027ab1060bb981d93110577adcf3508aa0cbd55'


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build on Windows with Python and uv installed.')
    if not shutil.which('uv'):
        raise SystemExit('Install uv first: https://docs.astral.sh/uv/getting-started/installation/')
    subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                    '-File', str(ROOT / 'packaging/build-native-launcher.ps1')], check=True, cwd=ROOT)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    output = ROOT / 'dist' / stamp / 'Parappa Access'
    output.mkdir(parents=True, exist_ok=False)
    cache = ROOT / 'build' / 'downloads'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / URL.rsplit('/', 1)[1]
    if not archive.exists():
        print('Downloading the official Python embeddable runtime.', flush=True)
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise SystemExit('Python download checksum mismatch.')
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('Cached Python download checksum mismatch.')
    runtime = output / 'runtime'
    runtime.mkdir()
    with zipfile.ZipFile(archive) as zipped:
        for name in zipped.namelist():
            path = (runtime / name).resolve()
            if not path.is_relative_to(runtime.resolve()):
                raise SystemExit('Unsafe runtime archive path.')
        zipped.extractall(runtime)
    # The isolated runtime and its children share these explicit paths, even
    # when the recording child uses -I -S. No global Python installation needed.
    (runtime / 'python313._pth').write_text(
        'python313.zip\n.\nsite-packages\n../scripts\n', encoding='ascii')
    locked_requirements = output.parent / 'runtime-requirements.txt'
    subprocess.run(['uv', '--cache-dir', str(ROOT / 'build/uv-cache'),
                    'export', '--locked', '--no-dev', '--no-emit-project',
                    '--format', 'requirements-txt', '--output-file', str(locked_requirements)],
                   check=True, cwd=ROOT)
    subprocess.run([
        'uv', '--cache-dir', str(ROOT / 'build/uv-cache'),
        'pip', 'install', '--only-binary=:all:', '--require-hashes',
        '--python', str(runtime / 'python.exe'),
        '--target', str(runtime / 'site-packages'),
        '-r', str(locked_requirements),
    ], check=True)
    files = [line.strip() for line in (ROOT / 'release-files.txt').read_text().splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    for name in files:
        source = (ROOT / name).resolve()
        if not source.is_relative_to(ROOT) or name.startswith(('tools/', 'logs/', 'build/', 'dist/')):
            raise ValueError('Unsafe release file: ' + name)
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, destination)
    (output / 'public-build.json').write_text('{"developer_tools": false}\n')
    shutil.copy2(ROOT / 'build/native-launcher.exe', output / 'Parappa Access.exe')
    # Retain upstream package metadata, licenses and notices without pruning.
    manifest = {
        'python_version': VERSION, 'python_url': URL, 'python_sha256': SHA256,
        'requirements': locked_requirements.read_text(),
        'files': {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(output.rglob('*')) if p.is_file()},
    }
    (output / 'bundle-manifest.json').write_text(json.dumps(manifest, indent=2))
    subprocess.run([str(runtime / 'python.exe'), '-B', '-I', '-S', '-c',
                    'import prism, pyaudiowpatch, window_menu, duckstation_capture; '
                    'print("Portable runtime imports OK")'], check=True, cwd=output)
    subprocess.run([str(runtime / 'python.exe'), '-B', str(output / 'scripts/accessible-menu.py'),
                    '--help'], check=True, cwd=output)
    subprocess.run([str(runtime / 'python.exe'), '-B', '-I', '-S', '-c',
                    'import window_menu; m=window_menu.WindowMenu(); '
                    'm.show("Packaging check", [("0", "Exit")], 0, ""); '
                    'assert m._list_hwnd; m.shutdown(); '
                    'print("Portable native controls OK")'], check=True, cwd=output)
    total = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
    zipped = Path(shutil.make_archive(str(output), 'zip', output.parent, output.name))
    print(json.dumps({'folder': str(output), 'bytes': total,
                      'zip': str(zipped), 'zip_bytes': zipped.stat().st_size}, indent=2))


if __name__ == '__main__':
    main()
