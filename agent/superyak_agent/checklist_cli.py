"""Checklists: `superyak-agent checklists list | trust | report` (spec, Where checklists are found; Trust; Renegotiation)."""
import os
import sys
from pathlib import Path

from . import checklists as cl
from .acting import acting_home
from .checklist_report import read_lines, render_report, report
from .station import utc_time


def _when(checklist) -> str:
    parts = []
    for m in checklist.moments:
        if m.kind == 'every':
            parts.append(f'every {m.hours}h')
        elif m.kind == 'command':
            parts.append(f'command {m.words}')
        elif m.kind == 'enter' and m.path:
            parts.append(f'enter {m.path}')
        else:
            parts.append(m.kind)
    return '; '.join(parts)


def _count(directory) -> int:
    try:
        return sum(1 for n in os.listdir(directory) if n.endswith('.md') and cl.ID.fullmatch(n[:-3]))
    except OSError:
        return 0


def _list(args, out) -> int:
    cwd = os.path.realpath(args.cwd or os.getcwd())
    home = Path(args.home) if args.home else acting_home(cwd)
    own_dir = home / 'checklists'
    allowed = cl.trusted(own_dir)
    own_real = os.path.realpath(own_dir)
    found = cl.find(cwd, own_dir)
    fired = read_lines(own_dir / 'fired.jsonl')
    for directory, _ in cl.search_dirs(cwd, own_dir):
        shown = cl._clean(directory)
        if str(directory) == own_real:
            out(f"{shown}: the ship's own")
        elif str(directory) in allowed:
            out(f'{shown}: trusted')
        else:
            n = _count(directory)
            out(f'{shown}: not trusted ({n} list{"" if n == 1 else "s"})')
            continue
        for loaded in found.lists:
            if loaded.directory != directory:
                continue
            times = sorted((l['time'] for l in fired if l.get('key') == loaded.key and 'moment' in l
                            and isinstance(l.get('time'), (int, float))), reverse=True)[:3]
            last = 'last fired ' + ', '.join(utc_time(t) for t in times) if times else 'never fired'
            c = loaded.checklist
            out(f'  {loaded.key} v{c.version} "{cl._clean(c.title)}": {_when(c)}; {last}')
        for loaded in found.overridden:
            if loaded.directory == directory:
                out(f'  {loaded.key} overridden by a nearer {loaded.checklist.id}')
    for notice in found.notices:
        out(notice)
    return 0


def _trust(args, out, stdin, stdout) -> int:
    if not (stdin.isatty() and stdout.isatty()):
        out('checklists trust: only a person at a terminal can trust a directory (stdin and stdout must be a terminal).')
        return 2
    real = os.path.realpath(args.path)
    reason = cl.trust_refusal(Path(real))
    if reason:
        out(f'checklists trust: not trusting {cl._clean(real)}: {reason}.')
        return 2
    holder = os.path.dirname(os.path.dirname(real))
    home = Path(args.home) if args.home else acting_home(holder)
    out(f'Trusting means this ship runs what these lists say. Directory: {cl._clean(real)}')
    out(f'It will be trusted by: {home}')
    out('Type the directory path above exactly to confirm:')
    typed = stdin.readline().rstrip('\r\n')
    if typed != real:
        out('checklists trust: what you typed is not that path; nothing was trusted.')
        return 2
    from .install import add_trusted
    try:
        added = add_trusted(home / 'checklists', real)
    except OSError as error:
        out(f'checklists trust: could not write {home / "checklists"}: {error.strerror or error}.')
        return 2
    if added:
        out(f'Trusted: {cl._clean(real)}. Home changed: {home}')
    else:
        out(f'Already trusted: {cl._clean(real)}. Home: {home}')
    return 0


def _report(args, out) -> int:
    cwd = os.getcwd()
    home = Path(args.home) if args.home else acting_home(cwd)
    own_dir = home / 'checklists'
    fired = read_lines(own_dir / 'fired.jsonl')
    runs = read_lines(own_dir / 'runs.jsonl')
    texts = {(l.key, l.checklist.version): list(l.checklist.items) for l in cl.find(cwd, own_dir).lists}
    misses = sum(1 for line in fired if 'miss' in line)
    out(render_report(report(fired, runs, texts=texts), misses))
    return 0


def main(args, out=print, stdin=None, stdout=None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    if args.checklists_command == 'list':
        return _list(args, out)
    if args.checklists_command == 'trust':
        return _trust(args, out, stdin, stdout)
    return _report(args, out)
