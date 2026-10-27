"""One bounded private index cache; immutable S3 receipts remain authoritative."""
import hashlib
import json
import os
import re
import shutil
import tarfile
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pipelines.query.engine import QueryError
from pipelines.query.source_reader import SourceIndexReader
from pipelines.query.source_recipe import RECIPE_SHA256, encoded

MAX_CACHE_BYTES = 12 * 1024**3
MAX_PACKAGE_BYTES = 4 * 1024**3


def _key(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise QueryError('INDEX_CACHE_ID_INVALID')
    return value


def _used(root):
    total = 0
    for path in root.rglob('*'):
        try:
            if path.is_symlink():
                raise QueryError('INDEX_CACHE_INVALID')
            if path.is_file():
                total += path.stat().st_size
        except FileNotFoundError:
            continue
    return total


@contextmanager
def _lock(root, tick):
    import fcntl  # Supported deployment is Linux; importing the module is portable.
    with (root / '.prepare.lock').open('a+b') as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                tick(force=True)
                time.sleep(.2)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def open_cached(cache_root, cache_key, expected_identity):
    """API-safe: no mkdir, lock creation, registry writes, download or CWB."""
    root = Path(cache_root).resolve()
    directory = root / _key(cache_key)
    try:
        if directory.is_symlink() or not directory.resolve().is_relative_to(root):
            raise QueryError('INDEX_CACHE_INVALID')
        marker = json.loads((directory / '.ready.json').read_text('utf-8'))
        raw = (directory / 'manifest.json').read_bytes()
        if marker['package_sha256'] != cache_key or marker['identity_sha256'] != expected_identity or marker['manifest_sha256'] != hashlib.sha256(raw).hexdigest():
            raise QueryError('INDEX_CACHE_INVALID')
        reader = SourceIndexReader(directory, verify=False)
        if reader.manifest['identity_sha256'] != expected_identity:
            reader.close()
            raise QueryError('INDEX_CACHE_INVALID')
        return reader
    except FileNotFoundError as exc:
        raise QueryError('CACHE_NOT_READY') from exc
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise QueryError('INDEX_CACHE_INVALID') from exc


def prepare_index(cache_root, manifest_bytes, expected_manifest_sha256, open_package,
                  progress_callback, *, max_cache_bytes=MAX_CACHE_BYTES, timeout=1800):
    """Install once by package SHA using a trusted, version-pinned stream factory.

    Global local flock serializes cache admission/install only, not query reads.
    Total limit includes existing entries and this request's tar+unpacked peak.
    Failed installs remove only their own staging directory; there is no eviction.
    """
    if len(manifest_bytes) > 2*1024**2 or hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
        raise QueryError('INDEX_MANIFEST_INVALID')
    manifest = json.loads(manifest_bytes)
    from pipelines.query.project_recipe import RECIPE_SHA256 as PROJECT_RECIPE_SHA256
    supported = {'source-index/v1':RECIPE_SHA256,'project-index/v1':PROJECT_RECIPE_SHA256}
    if supported.get(manifest['format']) != manifest['recipe_sha256']:
        raise QueryError('INDEX_RECIPE_MISMATCH')
    if hashlib.sha256(encoded(manifest['identity'])).hexdigest() != manifest['identity_sha256']:
        raise QueryError('INDEX_IDENTITY_MISMATCH')
    key = _key(manifest['package']['sha256'])
    package_bytes = manifest['package']['bytes']
    if type(package_bytes) is not int or not 0 < package_bytes <= MAX_PACKAGE_BYTES:
        raise QueryError('INDEX_CACHE_QUOTA_EXCEEDED')
    inner = {k: v for k, v in manifest.items() if k not in {'package', 'measurement'}}
    inner_bytes = encoded(inner)
    expected = {'manifest.json': {'bytes': len(inner_bytes), 'sha256': hashlib.sha256(inner_bytes).hexdigest()}}
    for entry in manifest['files']:
        name = entry['name']
        parts = PurePosixPath(name)
        if name in expected or parts.is_absolute() or '..' in parts.parts or '\\' in name or str(parts) != name or type(entry['bytes']) is not int or entry['bytes'] < 0:
            raise QueryError('INDEX_MEMBER_INVALID')
        _key(entry['sha256'])
        expected[name] = entry
    root = Path(cache_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / key
    started, last, downloaded = time.monotonic(), 0, 0
    stage = 'CACHE_ACQUIRING'

    def tick(*, force=False):
        nonlocal last
        now = time.monotonic()
        if now-started > timeout:
            raise QueryError('CACHE_PREPARE_TIMEOUT')
        if force or now-last >= 1:
            used = _used(root)
            if used > max_cache_bytes:
                raise QueryError('INDEX_CACHE_QUOTA_EXCEEDED')
            progress_callback({'stage': stage, 'processed_bytes': downloaded, 'total_bytes': package_bytes,
                               'processed_records': None, 'total_records': None, 'cache_bytes': used})
            last = now

    with _lock(root, tick):
        tick(force=True)
        if target.exists():
            try:
                with open_cached(root, key, manifest['identity_sha256']) as cached:
                    for entry in cached.manifest['files']:
                        h = hashlib.sha256()
                        with (target/entry['name']).open('rb') as stream:
                            while chunk := stream.read(1024**2):
                                h.update(chunk)
                                tick()
                        if h.hexdigest() != entry['sha256']:
                            raise QueryError('INDEX_CACHE_INVALID')
                return {'cache_key': key, 'directory': target, 'manifest': manifest, 'created': False, 'cache_bytes': _used(root)}
            except QueryError as exc:
                if str(exc) not in {'INDEX_CACHE_INVALID', 'CACHE_NOT_READY'}:
                    raise
                # Only this digest-named derived copy may be replaced. S3 is unchanged.
                if target.is_symlink() or not target.resolve().is_relative_to(root):
                    raise QueryError('INDEX_CACHE_INVALID') from None
                shutil.rmtree(target)
        required = package_bytes + sum(x['bytes'] for x in expected.values()) + 1024**2
        if _used(root) + required > max_cache_bytes:
            raise QueryError('INDEX_CACHE_QUOTA_EXCEEDED')
        temporary = root / ('.staging-' + uuid4().hex)
        temporary.mkdir()
        unpacked, package = temporary/'bundle', temporary/'index.tar'
        unpacked.mkdir()
        try:
            stream = open_package()
            try:
                h = hashlib.sha256()
                with package.open('xb') as output:
                    while chunk := stream.read(1024**2):
                        downloaded += len(chunk)
                        if downloaded > package_bytes:
                            raise QueryError('INDEX_PACKAGE_HASH_MISMATCH')
                        output.write(chunk)
                        h.update(chunk)
                        tick()
                if downloaded != package_bytes or h.hexdigest() != key:
                    raise QueryError('INDEX_PACKAGE_HASH_MISMATCH')
            finally:
                stream.close()
            stage = 'CACHE_VERIFYING'
            seen = set()
            with tarfile.open(package, 'r:') as archive:
                for member in archive:
                    if member.name not in expected or member.name in seen or not member.isfile() or member.size != expected[member.name]['bytes']:
                        raise QueryError('INDEX_MEMBER_INVALID')
                    seen.add(member.name)
                    path = unpacked/member.name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise QueryError('INDEX_MEMBER_INVALID')
                    h, size = hashlib.sha256(), 0
                    with source, path.open('xb') as output:
                        while chunk := source.read(1024**2):
                            output.write(chunk)
                            h.update(chunk)
                            size += len(chunk)
                            tick()
                    if size != member.size or h.hexdigest() != expected[member.name]['sha256']:
                        raise QueryError('INDEX_MEMBER_HASH_MISMATCH')
            if seen != set(expected):
                raise QueryError('INDEX_MEMBER_INVALID')
            with SourceIndexReader(unpacked, verify=False):
                pass
            marker = {'format': 'source-index-cache/v1', 'package_sha256': key,
                      'identity_sha256': manifest['identity_sha256'],
                      'manifest_sha256': expected['manifest.json']['sha256'],
                      'receipt_manifest_sha256': expected_manifest_sha256}
            (unpacked/'.ready.json').write_bytes(encoded(marker))
            tick(force=True)
            package.unlink()
            os.replace(unpacked, target)
            return {'cache_key': key, 'directory': target, 'manifest': manifest, 'created': True, 'cache_bytes': _used(root)}
        finally:
            if temporary.resolve().is_relative_to(root) and temporary.name.startswith('.staging-'):
                shutil.rmtree(temporary)
