"""superyak-agent: dock this machine's ship, serve its station tools, watch its mentions."""
import argparse
from pathlib import Path
from .station import CONFIG


def build_parser():
    parser = argparse.ArgumentParser(prog='superyak-agent')
    commands = parser.add_subparsers(dest='command', required=True)
    mcp = commands.add_parser('mcp', help='Station tools over stdio (MCP)')
    mcp.add_argument('--config', type=Path, default=CONFIG)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == 'mcp':
        from .mcp import serve
        serve(args.config)
        return 0
    parser.error(f'unknown command {args.command}')
