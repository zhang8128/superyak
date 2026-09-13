"""Build a standalone source archive from explicit reviewed files only."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tomllib

# The standard sdist builder and this archive share one reviewed inventory.
# Wheel selection is an explicit runtime subset in the same pyproject file.
def release_files(root):
    config = tomllib.loads((root / 'pyproject.toml').read_text())
    return config['tool']['hatch']['build']['targets']['sdist']['only-include']


def build(root, output):
    root, output = Path(root).resolve(), Path(output)
    contents = {}
    for name in release_files(root):
        path = root / name
        if any((root / Path(*Path(name).parts[:i])).is_symlink() for i in range(1, len(Path(name).parts) + 1)):
            raise ValueError('Refusing symlink in release source: ' + name)
        if not path.is_file():
            raise ValueError('Missing release source: ' + name)
        contents[name] = path.read_bytes()
    contents['CHECKSUMS.json'] = (json.dumps({name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}, indent=2, sort_keys=True) + '\n').encode()
    # Exclusive creation also refuses output symlinks and accidental release reuse.
    with output.open('xb') as stream:
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for name, data in sorted(contents.items()):
                info = tarfile.TarInfo('superyak-peer/' + name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                archive.addfile(info, io.BytesIO(data))
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='New .tar.gz file; parent directory must exist')
    args = parser.parse_args()
    try:
        digest = build(Path(__file__).resolve().parents[1], args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps({'archive': str(args.output.resolve()), 'sha256': digest}))


if __name__ == '__main__':
    main()
