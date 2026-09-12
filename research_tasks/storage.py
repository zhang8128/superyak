"""Small immutable, checksummed task artifacts."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


class IntegrityError(ValueError):
    """A saved artifact is no longer a reliable checkpoint."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise IntegrityError('Duplicate artifact JSON key')
        result[key] = value
    return result


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError(f'Expected a bounded regular artifact: {path}')
    with path.open('rb') as stream:
        data = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ValueError('Artifact exceeds its byte limit')
    value = json.loads(data, object_pairs_hook=_unique_object)
    canonical(value)  # Reject non-finite JSON numbers too.
    return value


def write_once(path, value):
    path = Path(path)
    encoded = canonical(value) + b'\n'
    if len(encoded) > MAX_ARTIFACT_BYTES:
        raise ValueError('Artifact exceeds its byte limit')
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('Artifact paths cannot contain symlinks')
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except FileExistsError:
        if read(path) != value:
            raise IntegrityError(f'Existing immutable artifact differs: {path}') from None
    finally:
        temporary.unlink(missing_ok=True)
    return value


def save_checked(path, payload):
    write_once(path, {'payload': payload, 'sha256': digest(payload)})
    return payload


def read_checked(path):
    try:
        value = read(path)
    except (ValueError, OSError) as error:
        raise IntegrityError(f'Unreadable checkpoint: {path}: {error}') from error
    if (not isinstance(value, dict) or set(value) != {'payload', 'sha256'}
            or digest(value['payload']) != value['sha256']):
        raise IntegrityError(f'Artifact hash mismatch: {path}')
    return value['payload']
