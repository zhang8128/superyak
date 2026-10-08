"""superyak-agent: dock this machine's ship, serve its station tools, watch its mentions."""
import argparse
import sys
from pathlib import Path
from .station import CONFIG, HOME


def build_parser():
    parser = argparse.ArgumentParser(prog='superyak-agent')
    commands = parser.add_subparsers(dest='command', required=True)
    mcp = commands.add_parser('mcp', help='Station tools over stdio (MCP)')
    mcp.add_argument('--config', type=Path, default=CONFIG)
    watch = commands.add_parser('watch', help='Answer mentions (runs as a service)')
    watch.add_argument('--config', type=Path, default=CONFIG)
    watch.add_argument('--state', type=Path, default=HOME / 'ship-state.json')
    watch.add_argument('--mcp-config', type=Path)
    watch.add_argument('--notices-command', help='Trusted local command printing station notices as JSON (Odo only)')
    watch.add_argument('--resident', action='store_true', help='Station resident: always read-only; answers one-person rooms')
    watch.add_argument('--model')
    watch.add_argument('--once', action='store_true')
    hook = commands.add_parser('hook', help='Claude Code hook: session start and prompt')
    hook.add_argument('--config', type=Path, default=CONFIG)
    dock = commands.add_parser('dock', help='Request access if needed, dock this machine, install its tools')
    dock.add_argument('--station', required=True)
    dock.add_argument('--door')
    dock.add_argument('--ship')
    dock.add_argument('--workspace', default=str(Path(__file__).resolve().parents[2]))
    dock.add_argument('--request', action='store_true')
    dock.add_argument('--name')
    dock.add_argument('--contact')
    dock.add_argument('--note', default='')
    dock.add_argument('--wait', type=int, default=540)
    dock.add_argument('--hook', action='store_true', help='Show new room messages at each Claude Code turn')
    dock.add_argument('--no-adna', action='store_true')
    dock.add_argument('--no-service', action='store_true')
    run_mcp = commands.add_parser('run-mcp', help='Write the MCP config used by watcher runs')
    run_mcp.add_argument('--config', type=Path, required=True)
    run_mcp.add_argument('--out', type=Path, required=True)
    run_mcp.add_argument('--adna-dist', type=Path)
    for name in ('status', 'undock'):
        commands.add_parser(name).add_argument('--config', type=Path, default=CONFIG)
    worm = commands.add_parser('wormhole', help='Relay bridged rooms and the Station.aDNA vault (runs as a service)')
    worm.add_argument('--config', type=Path, required=True)
    worm.add_argument('--state', type=Path, required=True)
    worm.add_argument('--vault', type=Path, required=True, help='The bridge clone of Station.aDNA')
    worm.add_argument('--personas', type=Path, required=True)
    worm.add_argument('--owner', action='append', required=True, metavar='USERNAME',
                      help='Bridge only rooms this person owns (repeat for more people)')
    worm.add_argument('--once', action='store_true')
    init = commands.add_parser('wormhole-init', help='Create the Station.aDNA bare repository and the bridge clone')
    init.add_argument('--bare', type=Path, required=True)
    init.add_argument('--clone', type=Path, required=True)
    init.add_argument('--template', type=Path)
    personas = commands.add_parser('wormhole-personas', help='Write the persona map from the public aDNA registry')
    personas.add_argument('--out', type=Path, required=True)
    personas.add_argument('--registry', default=None)
    vg = commands.add_parser('vault-git', help='Forced command for the sync key (fetch/push one repository only)')
    vg.add_argument('--repo', type=Path, required=True)
    key = commands.add_parser('wormhole-key', help="Authorize Stanley's sync key for the station vault only")
    which = key.add_mutually_exclusive_group(required=True)
    which.add_argument('--key', help='The public key line (in a shell it may be mangled; prefer --key-file)')
    which.add_argument('--key-file', type=Path, help='A .pub file holding exactly one public key line')
    key.add_argument('--repo', type=Path, required=True)
    key.add_argument('--authorized-keys', type=Path, default=Path.home() / '.ssh' / 'authorized_keys')
    return parser


def _hook(parser, argv):
    """Claude Code hook: unknown flags are ignored and nothing may break the prompt, so it always exits 0."""
    try:
        import os
        from .hook import run, session_from_stdin
        args, _ = parser.parse_known_args(argv)
        session_id = None if sys.stdin.isatty() else session_from_stdin(sys.stdin)
        text = run(args.config, session_id=session_id,
                   event='session-start' if os.environ.get('SUPERYAK_HOOK_EVENT') == 'session-start' else 'prompt',
                   messages=os.environ.get('SUPERYAK_HOOK_MESSAGES') != '0')
        if text:
            print(text)
    except BaseException:  # noqa: BLE001
        pass
    return 0


def main(argv=None):
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ['hook']:
        return _hook(parser, argv)
    args = parser.parse_args(argv)
    if args.command == 'mcp':
        from .mcp import serve
        serve(args.config)
        return 0
    if args.command == 'watch':
        import logging
        import shlex
        import time
        from .runs import ClaudeRunner
        from .station import client_for, load_config
        from .watch import POLL_SECONDS, Watcher
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
        config = load_config(args.config)
        mcp_config = args.mcp_config or args.config.parent / 'run-mcp.json'
        runner = ClaudeRunner(config, args.state.parent / 'runs', mcp_config=mcp_config if mcp_config.exists() else None, model=args.model)
        watcher = Watcher(client_for(config), config, args.state, runner, resident=args.resident,
                          notices_command=shlex.split(args.notices_command) if args.notices_command else None)
        while True:
            try:
                posted = watcher.cycle()
                if posted:
                    logging.info('posted %d message(s)', posted)
            except Exception:  # noqa: BLE001 - keep the service alive
                logging.exception('cycle failed')
                watcher.me = None
            if args.once:
                return 0
            time.sleep(POLL_SECONDS)
    if args.command == 'dock':
        from .dock import Dock
        from .install import install_all
        fields = None
        if args.request:
            if not (args.name and args.contact):
                parser.error('--request needs --name and --contact')
            fields = {'name': args.name, 'contact': args.contact, 'note': args.note}
        code = Dock(args.station, door=args.door, ship=args.ship, workspace=args.workspace).run(fields, wait=args.wait)
        if code == 0:
            install_all(CONFIG, hook=args.hook, adna=not args.no_adna, service=not args.no_service)
        return code
    if args.command == 'run-mcp':
        from .install import run_mcp_config
        from .station import write_private
        write_private(args.out, run_mcp_config(args.config, args.adna_dist))
        return 0
    if args.command == 'status':
        from .station import StationError, client_for, label, load_config
        config = load_config(args.config)
        client = client_for(config)
        me = client.me()
        print(f'{me["name"]} (@{me["username"]}) is docked at {config["station"]}; workspace {config["workspace"]}.')
        try:
            layers = client.instructions().get('layers') or []
            lines = ['Instructions:'] + [f'  {label(layer.get("title"))} · revision {layer.get("revision")} · signed by '
                                         f'{label(layer.get("signer_name"))}' for layer in layers] if layers else ['Instructions: none']
        except (StationError, OSError, ValueError, AttributeError, TypeError) as error:
            # an older station (403), a station gone mid-command or an odd answer; the key never goes into the reason
            lines = [f'Instructions: unavailable ({label(str(error).replace(config["key"], "[key]"))})']
        print('\n'.join(lines))
        return 0
    if args.command == 'undock':
        from .install import uninstall_all
        uninstall_all(args.config)
        return 0
    if args.command == 'wormhole':
        import logging
        import time
        from .memos import load_personas
        from .station import client_for, load_config
        from .vault import Vault
        from .wormhole import POLL_SECONDS, Wormhole
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
        bridge = Wormhole(client_for(load_config(args.config)), Vault(args.vault), load_personas(args.personas), args.state,
                          owners=args.owner)
        while True:
            try:
                posted = bridge.cycle()
                if posted:
                    logging.info('posted %d message(s)', posted)
            except Exception:  # noqa: BLE001 - keep the service alive
                logging.exception('cycle failed')
                bridge.me = None
            if args.once:
                return 0
            time.sleep(POLL_SECONDS)
    if args.command == 'wormhole-init':
        from .vault import Vault
        Vault.create(args.bare, args.clone, template=args.template)
        print(f'Station.aDNA created: {args.bare} (bridge clone {args.clone})')
        return 0
    if args.command == 'wormhole-personas':
        from .memos import REGISTRY, fetch_registry, personas_from_registry
        from .station import write_private
        found = personas_from_registry(fetch_registry(args.registry or REGISTRY))
        write_private(args.out, found)
        print(f'{len(found)} personas written to {args.out}. Add your own in {args.out.with_name("personas.local.json")}.')
        return 0
    if args.command == 'vault-git':
        from .vault_git import serve
        return serve(args.repo)
    if args.command == 'wormhole-key':
        from .vault_git import install_key
        run_agent = Path(__file__).resolve().parents[1] / 'run_agent.py'
        try:
            key = args.key
            if args.key_file:
                key = args.key_file.read_bytes().decode('utf-8')  # no newline translation: CRLF is refused too
                key = key[:-1] if key.endswith('\n') else key  # one trailing newline; install_key refuses any other
            added = install_key(key, args.repo, sys.executable, run_agent, args.authorized_keys)
        except (ValueError, OSError) as error:  # a bad key, an unreadable key file or authorized_keys
            print(f'wormhole-key: {error}', file=sys.stderr)
            return 2
        print('Key authorized: it can only fetch and push the station vault.' if added else
              'That key is already in authorized_keys; nothing changed. If it is an unrestricted key, ask for a dedicated one.')
        return 0
    parser.error(f'unknown command {args.command}')
