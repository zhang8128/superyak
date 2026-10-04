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
    parser.error(f'unknown command {args.command}')
