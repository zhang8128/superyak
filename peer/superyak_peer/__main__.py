"""Explicit provisioning and loopback-first server commands."""
import argparse
import getpass
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sys
from .common import Problem
from .db import Store


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def seed_demo(data_dir):
    data_dir = Path(data_dir)
    marker = data_dir / 'demo-credentials.json'
    if data_dir.is_symlink() or marker.is_symlink():
        raise ValueError('Symlinked demo state is not allowed')
    if data_dir.exists() and any(data_dir.iterdir()):
        if marker.is_file() and (data_dir / 'demo-marker.json').is_file():
            if json.loads((data_dir / 'demo-marker.json').read_text()) == {'application': 'superyak-demo', 'version': 1}:
                Store(data_dir)
                return
        raise ValueError('Refusing to overwrite non-demo or incomplete state')
    store = Store(data_dir)
    credentials, people = [], {}
    for username, name in [('patient', 'Alex Patient'), ('family', 'Sam Family'), ('doctor', 'Dr. Morgan'), ('organizer', 'Taylor Organizer')]:
        password = secrets.token_urlsafe(18)
        people[username] = store.create_user(username, name, password, is_admin=username == 'organizer')
        credentials.append({'username': username, 'name': name, 'password': password})
    patient = people['patient']['id']
    store.create_space(patient, 'Alex’s care circle', 'care-circle', [people['family']['id'], people['doctor']['id']])
    store.create_space(people['organizer']['id'], 'Wilhelm Foundation demo project', 'organization', [patient, people['doctor']['id']])
    for username, person in people.items():
        store.create_layer(person['id'], {'title': 'My private notes', 'body': f'Fictional {username} notes. This draft is private.'})
    store.create_room(patient, 'Family conversation', [people['family']['id']])
    private_json(marker, credentials)
    private_json(data_dir / 'demo-marker.json', {'application': 'superyak-demo', 'version': 1})


def main(argv=None):
    parser = argparse.ArgumentParser(prog='superyak-peer')
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--data-dir', type=Path, default=Path('.engram/home'))
    init.add_argument('--username', required=True)
    init.add_argument('--name', required=True)
    init.add_argument('--password-file', type=Path)
    demo = commands.add_parser('demo')
    demo.add_argument('--data-dir', type=Path, default=Path('.engram/home-demo'))
    serve = commands.add_parser('serve')
    serve.add_argument('--data-dir', type=Path, default=Path('.engram/home'))
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=7435)
    serve.add_argument('--tls-cert', type=Path)
    serve.add_argument('--tls-key', type=Path)
    serve.add_argument('--origin', action='append', default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == 'demo':
            seed_demo(args.data_dir)
            print(f'Demo ready. Private credentials: {args.data_dir / "demo-credentials.json"}')
        elif args.command == 'init':
            store = Store(args.data_dir)
            with store.transaction() as db:
                if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                    raise ValueError('Peer already has accounts; use an owner invitation')
                password = args.password_file.read_text().rstrip('\r\n') if args.password_file else getpass.getpass('Owner password (12+ characters): ')
                store._create_user(db, args.username, args.name, password, True)
            print(f'Superyak owner created in {args.data_dir}')
        else:
            try:
                loopback = ipaddress.ip_address(args.host).is_loopback
            except ValueError:
                loopback = args.host == 'localhost'
            tls = bool(args.tls_cert and args.tls_key)
            if not loopback and not tls:
                raise ValueError('Remote binds require TLS certificate and key')
            if bool(args.tls_cert) != bool(args.tls_key):
                raise ValueError('TLS requires both certificate and key')
            from .app import create_app
            import uvicorn
            origins = args.origin or [f'{"https" if tls else "http"}://{args.host}:{args.port}']
            app = create_app(args.data_dir, allowed_origins=origins, secure_cookies=tls)
            uvicorn.run(app, host=args.host, port=args.port, ssl_certfile=str(args.tls_cert) if tls else None, ssl_keyfile=str(args.tls_key) if tls else None, proxy_headers=False)
    except (Problem, ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')

if __name__ == '__main__':
    main()
