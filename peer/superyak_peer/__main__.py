"""Explicit provisioning and loopback-first server commands."""
import argparse
import getpass
import hmac
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sqlite3
from .auth import password_hash
from .common import Problem, text
from .db import Store


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def validate_demo(data_dir):
    """Check completion read-only; never replace or repair retained demo state."""
    database = data_dir / 'peer.sqlite3'
    if not database.is_file():
        raise ValueError('Refusing incomplete demo state')
    try:
        marker = json.loads((data_dir / 'demo-marker.json').read_text())
        credentials = json.loads((data_dir / 'demo-credentials.json').read_text())
        if marker != {'application': 'superyak-demo', 'version': 1}:
            raise ValueError('Invalid marker')
        expected = {'patient', 'family', 'doctor', 'organizer'}
        if not isinstance(credentials, list) or len(credentials) != 4 or any(not isinstance(c, dict) for c in credentials):
            raise ValueError('Invalid credentials')
        if {c.get('username') for c in credentials} != expected:
            raise ValueError('Missing seeded identities')
        db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        try:
            if db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Incomplete identity references')
            for credential in credentials:
                row = db.execute('SELECT * FROM users WHERE username=?', (credential['username'],)).fetchone()
                password = text(credential.get('password'), 'password', 1024)
                if not row or ('id' in credential and credential['id'] != row['id']):
                    raise ValueError('Missing seeded identity')
                if not hmac.compare_digest(password_hash(password, row['salt']), row['password_hash']):
                    raise ValueError('Credentials do not match')
        finally:
            db.close()
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, Problem):
        raise ValueError('Refusing incomplete or mismatched demo state') from None
    return credentials


def seed_demo(data_dir):
    data_dir = Path(data_dir)
    marker = data_dir / 'demo-credentials.json'
    entries = ['demo-credentials.json', 'demo-marker.json', 'peer.sqlite3', 'peer.sqlite3-wal', 'peer.sqlite3-shm', 'peer.sqlite3-journal']
    if data_dir.is_symlink() or any((data_dir / name).is_symlink() for name in entries):
        raise ValueError('Symlinked demo state is not allowed')
    if data_dir.exists() and any(data_dir.iterdir()):
        validate_demo(data_dir)
        return
    store = Store(data_dir)
    credentials, people = [], {}
    for username, name in [('patient', 'Alex Patient'), ('family', 'Sam Family'), ('doctor', 'Dr. Morgan'), ('organizer', 'Taylor Organizer')]:
        password = secrets.token_urlsafe(18)
        people[username] = store.create_user(username, name, password, is_admin=username == 'organizer')
        credentials.append({'id': people[username]['id'], 'username': username, 'name': name, 'password': password})
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
    bootstrap = commands.add_parser('bootstrap-super-admin', help='Reserve the first super admin with a private one-use activation')
    bootstrap.add_argument('--data-dir', type=Path, default=Path('.engram/home'))
    bootstrap.add_argument('--username', required=True)
    bootstrap.add_argument('--name', required=True)
    bootstrap.add_argument('--activation-file', type=Path, required=True)
    bootstrap.add_argument('--renew-activation', action='store_true', help='Replace a lost or expired activation for the same pending first super admin')
    demo = commands.add_parser('demo')
    demo.add_argument('--data-dir', type=Path, default=Path('.engram/home-demo'))
    card = commands.add_parser('card')
    card.add_argument('--data-dir', type=Path, default=Path('.engram/home'))
    card.add_argument('--username', required=True)
    card.add_argument('--endpoint', required=True)
    notices = commands.add_parser('station-notices', help='Trusted local listing of what Odo announces in Ops')
    notices.add_argument('--data-dir', type=Path, default=Path('.engram/home'))
    door = commands.add_parser('door', help='Public access-request door for tailscale funnel (two routes, loopback only)')
    door.add_argument('--data-dir', type=Path, default=Path('.engram/home'))
    door.add_argument('--host', default='127.0.0.1')
    door.add_argument('--port', type=int, default=7436)
    ship = commands.add_parser('create-ship', help='Trusted local: create the station ship (no owner) and write its private agent config')
    ship.add_argument('--data-dir', type=Path, default=Path('.engram/home'))
    ship.add_argument('--username', required=True)
    ship.add_argument('--name', required=True)
    ship.add_argument('--station', required=True, help='URL the ship uses, e.g. http://127.0.0.1:7435')
    ship.add_argument('--origin', help='Public origin when --station is a loopback proxy target')
    ship.add_argument('--workspace', type=Path, required=True)
    ship.add_argument('--config', type=Path, required=True)
    serve = commands.add_parser('serve')
    serve.add_argument('--data-dir', type=Path, default=Path('.engram/home'))
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=7435)
    serve.add_argument('--local-demo', action='store_true', help='Open seeded test accounts without passwords, on loopback only')
    serve.add_argument('--tls-cert', type=Path)
    serve.add_argument('--tls-key', type=Path)
    serve.add_argument('--origin', action='append', default=[])
    serve.add_argument('--peer-tls', action='store_true')
    serve.add_argument('--federation-endpoint')
    serve.add_argument('--sync', action='store_true')
    serve.add_argument('--proxy-headers', action='store_true', help='Trust X-Forwarded-Proto/For from a loopback reverse proxy such as tailscale serve')
    serve.add_argument('--model-config', type=Path, help='Operator-owned approved local Gemma JSON configuration')
    serve.add_argument('--share-link-file', type=Path, help='Reusable Tailscale share link released once to approved requesters')
    args = parser.parse_args(argv)
    try:
        if args.command == 'bootstrap-super-admin':
            user = Store(args.data_dir).bootstrap_super_admin(args.username, args.name, args.activation_file, renew_activation=args.renew_activation)
            print(f'Super admin reserved for {user["username"]}. Private activation: {args.activation_file}')
        elif args.command == 'create-ship':
            import platform
            import time
            store = Store(args.data_dir)
            args.config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Claim the private config first; the ship and its key commit only once the file holds them.
            fd = os.open(args.config, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, 'w') as stream, store.transaction() as db:
                    ship = store._new_ship(db, args.username, args.name, None)
                    json.dump({'station': args.station, 'origin': args.origin, 'ship': ship['username'], 'ship_id': ship['id'],
                               'ship_name': ship['name'], 'owner_id': None, 'key': store._new_ship_key(db, ship['id']),
                               'workspace': str(args.workspace), 'machine': platform.node(), 'created': time.time()}, stream, indent=2)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                args.config.unlink(missing_ok=True)
                raise
            print(f'Station ship {ship["username"]} created. Private config: {args.config}')
        elif args.command == 'station-notices':
            print(json.dumps(Store(args.data_dir).station_notices(), indent=2))
        elif args.command == 'card':
            from .identity import PeerIdentity
            from .federation import Federation
            from urllib.parse import urlsplit
            store = Store(args.data_dir)
            with store.transaction() as db:
                user = db.execute('SELECT id FROM users WHERE username=?', (args.username,)).fetchone()
                if not user:
                    raise ValueError('Unknown local account')
            host = urlsplit(args.endpoint).hostname
            identity = PeerIdentity.load_or_create(store.data_dir, hosts=tuple(dict.fromkeys(['localhost','127.0.0.1',host])))
            print(json.dumps(Federation(store, endpoint=args.endpoint, identity=identity).card(user[0]), indent=2))
        elif args.command == 'demo':
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
        elif args.command == 'door':
            try:
                loopback = ipaddress.ip_address(args.host).is_loopback
            except ValueError:
                loopback = False
            if not loopback:
                raise ValueError('The door binds to loopback; tailscale funnel publishes it')
            from .door import create_door
            import uvicorn
            uvicorn.run(create_door(args.data_dir), host=args.host, port=args.port, access_log=False)  # status polls carry ?secret=
        else:
            try:
                loopback = ipaddress.ip_address(args.host).is_loopback
            except ValueError:
                loopback = args.host == 'localhost'
            if args.local_demo and not loopback:
                raise ValueError('Local demo requires a loopback bind')
            if args.proxy_headers and (not loopback or args.local_demo or not args.origin or any(not o.startswith('https://') for o in args.origin)):
                raise ValueError('Proxy headers require a loopback bind, explicit HTTPS origins, and no local demo')
            if args.peer_tls:
                from .identity import PeerIdentity
                from urllib.parse import urlsplit
                if args.tls_cert or args.tls_key:
                    raise ValueError('Choose generated peer TLS or explicit TLS files')
                host = urlsplit(args.federation_endpoint).hostname if args.federation_endpoint else args.host
                identity = PeerIdentity.load_or_create(args.data_dir, hosts=tuple(dict.fromkeys(['localhost','127.0.0.1',host])))
                args.tls_cert, args.tls_key = identity.cert_path, identity.key_path
            if args.federation_endpoint and not args.peer_tls:
                raise ValueError('Federation serving requires --peer-tls to match its exported certificate')
            tls = bool(args.tls_cert and args.tls_key)
            if not loopback and not tls:
                raise ValueError('Remote binds require TLS certificate and key')
            if bool(args.tls_cert) != bool(args.tls_key):
                raise ValueError('TLS requires both certificate and key')
            from .app import create_app
            import uvicorn
            origins = args.origin or [f'{"https" if tls else "http"}://{args.host}:{args.port}']
            from .models import load_config
            model_config = load_config(args.model_config)
            app = create_app(args.data_dir, local_demo=args.local_demo, model_config=model_config, allowed_origins=origins, secure_cookies=tls or args.proxy_headers, federation_endpoint=args.federation_endpoint, sync_enabled=args.sync, share_link_file=args.share_link_file)
            uvicorn.run(app, host=args.host, port=args.port, ssl_certfile=str(args.tls_cert) if tls else None, ssl_keyfile=str(args.tls_key) if tls else None, proxy_headers=args.proxy_headers, forwarded_allow_ips='127.0.0.1' if args.proxy_headers else None)
    except (Problem, ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')

if __name__ == '__main__':
    main()
