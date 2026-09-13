"""Download a verified, unmodified DuckStation archive from upstream only.

No game, BIOS, card or existing emulator installation is modified here.
The pinned archive must be revalidated before updating either URL or digest.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request
import zipfile
from duckstation_paths import EXECUTABLE_NAME

# Official 0.1.11894 asset, validated against our Stage 1 runtime workflow.
# Asset IDs do not follow the moving "latest" tag. Upstream can still remove it.
DOWNLOAD_URL = 'https://api.github.com/repos/stenzek/duckstation/releases/assets/559221312'
ARCHIVE_SHA256 = '5ba3b9624b3073d3398c2cb8185ba3a014ff9e84f9c486627e0e8aa56371d352'
MAX_DOWNLOAD = 150 * 1024 * 1024
MAX_EXTRACTED = 500 * 1024 * 1024


def install_archive(archive, destination):
    """Install only our verified archive into a previously absent directory."""
    archive, destination = Path(archive), Path(destination)
    if destination.exists():
        raise FileExistsError('DuckStation folder already exists; it was not changed.')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('This DuckStation download differs from the tested release. '
                         'Nothing was installed. The downloader needs a newly verified release.')
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        if sum(m.file_size for m in members) > MAX_EXTRACTED:
            raise ValueError('DuckStation archive exceeds the extraction limit.')
        base = destination.resolve()
        for member in members:
            target = (base / member.filename).resolve()
            if not target.is_relative_to(base) or (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe DuckStation archive path.')
        if EXECUTABLE_NAME not in zipped.namelist():
            raise ValueError('DuckStation executable missing from archive.')
        if zipped.testzip() is not None:
            raise ValueError('Damaged DuckStation archive.')
        destination.mkdir(parents=True, exist_ok=False)
        zipped.extractall(destination)


def download_duckstation(root, progress=None, cancelled=None):
    root = Path(root)
    destination = root / 'tools/duckstation'
    if destination.exists():
        raise FileExistsError('DuckStation folder already exists; it was not changed.')
    metadata_request = urllib.request.Request(
        DOWNLOAD_URL,
        headers={'User-Agent': 'ParappaAccess/0.1', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(metadata_request, timeout=15) as response:
        metadata = json.loads(response.read(2 * 1024 * 1024))
    if metadata.get('digest') != 'sha256:' + ARCHIVE_SHA256:
        raise ValueError('The tested DuckStation download is no longer available upstream. '
                         'This build needs an updated, verified download before first-time setup can continue. '
                         'Your existing installation was not changed.')
    cache = root / 'logs/downloads'
    cache.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(DOWNLOAD_URL, headers={
        'User-Agent': 'ParappaAccess/0.1', 'Accept': 'application/octet-stream'})
    with tempfile.TemporaryDirectory(prefix='duck-', dir=cache) as temporary:
        archive = Path(temporary) / 'duckstation.zip'
        with urllib.request.urlopen(request, timeout=30) as response, archive.open('xb') as stream:
            count = 0
            while True:
                if cancelled is not None and cancelled.is_set():
                    raise InterruptedError('Download cancelled.')
                block = response.read(256 * 1024)
                if not block:
                    break
                count += len(block)
                if count > MAX_DOWNLOAD:
                    raise ValueError('DuckStation download exceeds the size limit.')
                stream.write(block)
                if progress:
                    progress(count)
        if cancelled is not None and cancelled.is_set():
            raise InterruptedError('Download cancelled.')
        install_archive(archive, destination)
    return destination
