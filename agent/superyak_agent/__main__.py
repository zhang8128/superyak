"""superyak-agent: dock this machine's ship, serve its station tools, watch its mentions."""
import argparse
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
    hook = commands.add_parser('hook', help='Claude Code UserPromptSubmit hook')
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
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == 'mcp':
        from .mcp import serve
        serve(args.config)
        return 0
    if args.command == 'hook':
        from .hook import run
        text = run(args.config)
        if text:
            print(text)
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
        from .station import client_for, load_config
        config = load_config(args.config)
        me = client_for(config).me()
        print(f'{me["name"]} (@{me["username"]}) is docked at {config["station"]}; workspace {config["workspace"]}.')
        return 0
    if args.command == 'undock':
        from .install import uninstall_all
        uninstall_all(args.config)
        return 0
    parser.error(f'unknown command {args.command}')
