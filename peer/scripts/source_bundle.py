"""Build a standalone source archive from explicit reviewed files only."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

# Updating this manifest is a release review decision. Never glob private state.
FILES = ('API.md', 'LICENSE', 'MODELS_AND_SOURCES.md', 'NOTICE', 'PROTOCOL.md', 'README.md', 'pyproject.toml', 'scripts/source_bundle.py', 'scripts/two_peer_check.py', 'superyak_peer/__init__.py', 'superyak_peer/__main__.py', 'superyak_peer/app.py', 'superyak_peer/auth.py', 'superyak_peer/chats.py', 'superyak_peer/common.py', 'superyak_peer/db.py', 'superyak_peer/dispatch.py', 'superyak_peer/federation.py', 'superyak_peer/files.py', 'superyak_peer/identity.py', 'superyak_peer/interchange.py', 'superyak_peer/layers.py', 'superyak_peer/models.py', 'superyak_peer/peer_routes.py', 'superyak_peer/peer_store.py', 'superyak_peer/source_routes.py', 'superyak_peer/spaces.py', 'superyak_peer/static/app.css', 'superyak_peer/static/app.js', 'superyak_peer/static/index.html', 'superyak_peer/transport.py', 'tests/conftest.py', 'tests/test_auth.py', 'tests/test_browser.py', 'tests/test_chats.py', 'tests/test_cli.py', 'tests/test_federation.py', 'tests/test_identity.py', 'tests/test_interchange.py', 'tests/test_layers.py', 'tests/test_models.py', 'tests/test_packaging.py', 'tests/test_transport.py', 'uv.lock')


def build(root, output):
    root, output = Path(root).resolve(), Path(output)
    contents = {}
    for name in FILES:
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
