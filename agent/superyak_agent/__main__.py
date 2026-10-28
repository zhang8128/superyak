"""superyak-agent: dock this machine's ship, serve its station tools, watch its mentions."""
import sys
from pathlib import Path


def build_parser():
    import argparse  # here, not at the top: the hold path never loads it (Ruling 44)
    from .station import CONFIG, HOME
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
    kick = commands.add_parser('kick', help='Print one line per mention of this ship or reply to its post (run under a Monitor)')
    kick.add_argument('--config', type=Path, default=CONFIG)
    route = commands.add_parser('route-watch', help="Check the station's public route once from here, read-only; post "
                                'to a room when a check changes (run by a timer)')
    route.add_argument('--config', type=Path, default=CONFIG)
    route.add_argument('--room', help='The room that gets the lines (not needed with --dry-run)')
    route.add_argument('--state', type=Path, default=HOME / 'route-watch.json')
    route.add_argument('--dry-run', action='store_true', help='Print each check; post nothing and write no state')
    hook = commands.add_parser('hook', help='Claude Code hook: session start and prompt')
    hook.add_argument('--config', type=Path, default=CONFIG)
    held = commands.add_parser('hold', help='Claude Code PreToolUse hook on Bash: checklists and lessons hold a '
                               'command once (dispatched before this parser, which only describes it)')
    held.add_argument('--config', type=Path, default=CONFIG)
    lists = commands.add_parser('checklists', help='Which checklists load from where; trust a directory of lists '
                                '(a person at a terminal); propose changes from the run logs')
    which = lists.add_subparsers(dest='checklists_command', required=True)
    shown = which.add_parser('list', help='Show what loads from where, and when each list last fired')
    shown.add_argument('--cwd')
    shown.add_argument('--home', type=Path, help="The ship's home (default: the ship that acts at the cwd)")
    trust = which.add_parser('trust', help='Trust a checklists directory (needs a terminal)')
    trust.add_argument('path')
    trust.add_argument('--home', type=Path, help="The ship's home (default: the ship that acts where the lists are)")
    proposed = which.add_parser('report', help='Propose changes to lists from the run and firing logs; changes nothing')
    proposed.add_argument('--home', type=Path, help="The ship's home (default: the ship that acts at the cwd)")
    dock = commands.add_parser('dock', help='Request access if needed, dock this machine, install its tools')
    dock.add_argument('--station', required=True)
    dock.add_argument('--door')
    dock.add_argument('--ship')
    dock.add_argument('--workspace', default=None, help='Where watcher runs work (default: this checkout for the machine '
                      'ship, the project for a project ship)')
    dock.add_argument('--home', type=Path, help='~/.superyak (the machine ship, the default) or ~/.superyak/ships/<ship>')
    dock.add_argument('--project', type=Path, help='Dock a project ship that claims this repository (D7)')
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
        sub = commands.add_parser(name)
        sub.add_argument('--config', type=Path, default=CONFIG)
        sub.add_argument('--home', type=Path, help="The ship's home, instead of --config")
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
        from . import hook
        args, _ = parser.parse_known_args(argv)
        got = hook.HookInput(None, None, None, None, None) if sys.stdin.isatty() else hook.read_hook_input(sys.stdin)
        if got.event:  # Ruling 6: Claude Code's own name for the event decides; any other value prints nothing
            if got.event not in hook.EVENTS:
                return 0
            event = hook.EVENTS[got.event]
        else:
            event = {'session-start': 'session-start', 'session-end': 'session-end'}.get(os.environ.get('SUPERYAK_HOOK_EVENT'), 'prompt')
        text = hook.run(args.config, session_id=got.session, cwd=got.cwd, mode=got.mode, event=event, source=got.source,
                        messages=os.environ.get('SUPERYAK_HOOK_MESSAGES') != '0')
        if text:
            print(text)
    except BaseException:  # noqa: BLE001
        pass
    return 0


def _dock_project(args, fields):
    """A project ship (D7, S9): the checks before the request; Dock runs them again before each poll; install runs them
    once more inside the lock hold that writes the claim. Any refusal after the station has the ship says how to clean
    up."""
    from .claims import Refused
    from .dock import Dock
    from .project_dock import ProjectDock
    project = ProjectDock(args.ship, args.project)
    try:
        repo = project.checks()
    except Refused as error:
        print(f'dock: {error}', file=sys.stderr)
        return 2
    workspace = args.workspace or str(repo.root)
    try:
        code = Dock(args.station, door=args.door, ship=args.ship, workspace=workspace, home=project.home,
                    check=project.checks).run(fields, wait=args.wait)
    except Refused as error:
        print(project.cleanup(error), file=sys.stderr)
        return 2
    if code != 0:
        return code
    try:
        project.install(hook=args.hook, service=not args.no_service)
    except Refused as error:
        print(project.cleanup(error, rolled_back=getattr(error, 'rolled_back', False)), file=sys.stderr)
        return 2
    return 0


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ['hold']:  # before any station import: the hold stays light (N8)
        from .hold import main as hold
        return hold(argv[1:])
    parser = build_parser()
    if argv[:1] == ['hook']:
        return _hook(parser, argv)
    args = parser.parse_args(argv)
    if args.command == 'checklists':
        from .checklist_cli import main as checklists
        return checklists(args)
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
    if args.command == 'kick':
        from .kick import Kick
        from .station import client_for, load_config
        config = load_config(args.config)
        try:
            Kick(client_for(config, timeout=40), config.get('ship') or '').run()
        except KeyboardInterrupt:
            return 0
        except ValueError as error:  # a config naming no ship
            print(f'superyak kick: {error}', file=sys.stderr)
            return 2
    if args.command == 'route-watch':
        from .route_watch import run_once
        from .station import client_for, load_config
        if not (args.room or args.dry_run):
            parser.error('route-watch needs --room, or --dry-run')
        config = load_config(args.config)
        run_once(config, args.room, args.state, None if args.dry_run else client_for(config), dry_run=args.dry_run)
        return 0
    if args.command == 'dock':
        from .claims import Refused, check_mode
        from .dock import Dock
        from .install import install_all
        fields = None
        if args.request:
            if not (args.name and args.contact):
                parser.error('--request needs --name and --contact')
            fields = {'name': args.name, 'contact': args.contact, 'note': args.note}
        try:
            home, kind = check_mode(args.ship, args.home, args.project)   # S2: before any network call or write
        except Refused as error:
            print(f'dock: {error}', file=sys.stderr)
            return 2
        if kind == 'project':
            return _dock_project(args, fields)
        workspace = args.workspace or str(Path(__file__).resolve().parents[2])
        code = Dock(args.station, door=args.door, ship=args.ship, workspace=workspace, home=home).run(fields, wait=args.wait)
        if code == 0:
            install_all(home / 'station.json', hook=args.hook, adna=not args.no_adna, service=not args.no_service)
        return code
    if args.command == 'run-mcp':
        from .install import run_mcp_config
        from .station import write_private
        write_private(args.out, run_mcp_config(args.config, args.adna_dist))
        return 0
    if args.command in ('status', 'undock') and args.home is not None:
        from .claims import kind_of
        if kind_of(args.home) is None:
            print(f'{args.command}: {args.home} is not a ship home: use ~/.superyak or ~/.superyak/ships/<ship>.',
                  file=sys.stderr)
            return 2
        args.config = args.home / 'station.json'
    if args.command == 'status':
        from .claims import Unreadable, read_json_quiet, read_registry, registry_line, stale_claims, wiring_gaps
        from . import station as station_module
        from .station import StationError, client_for, label
        try:
            entries = read_registry()           # R16: named before the config is read or the station is called
        except Unreadable as error:
            print(registry_line(error))
            entries = []
        stale = stale_claims(entries)
        for entry, why in stale:   # R15
            print(f"Superyak: {entry['ship']}'s claim on {entry['root']} is stale: {why}. Both ships stay quiet there; "
                  f"dock {entry['ship']} again (with --project at the repository's new place) to refresh it.")
        for entry in entries:
            own = read_json_quiet(Path(entry['home']) / 'claim.json')
            if own != entry:       # S6: a stop between the registry entry and claim.json
                print(f"Superyak: {entry['ship']}'s registry entry has no matching {entry['home']}/claim.json, so "
                      f"{entry['ship']} doesn't act anywhere and the machine ship stays quiet in {entry['root']}; "
                      f"dock {entry['ship']} again to rewrite both.")
                continue
            if any(entry is gone for gone, _ in stale):
                continue           # below: a full match whose wiring is gone (a re-clone where inodes are reused)
            gaps = wiring_gaps(entry)
            if gaps:
                print(f"Superyak: {entry['ship']}'s claim on {entry['root']} matches, but {'; and '.join(gaps)}. Only "
                      f"{entry['ship']}'s tools can act there and no hook speaks; dock {entry['ship']} again to rewire it.")
        config = station_module.load_config(args.config)
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
