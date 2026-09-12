"""Terminal presentation and configuration for durable coding tasks."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import sys
import unicodedata
import uuid

from context_coding import CodingRuntime
from context_compile import Budget
from context_sources import EngramSource


def add_code_parser(sub):
    parser = sub.add_parser('code', help='Code in a repository with durable, resumable context episodes')
    parser.add_argument('task', nargs='?')
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--max-episodes', type=int, default=20)
    parser.add_argument('--episode-seconds', type=float, default=900)
    parser.add_argument('--soft-tokens', type=int, default=32000, help='Ask for a checkpoint after this observed input usage')
    parser.add_argument('--hard-tokens', type=int, default=48000, help='Interrupt after this observed input usage; not a pre-call cap')
    parser.add_argument('--max-steps', type=int, default=24, help='Interrupt after this many completed command/file/archive operations')


def terminal_text(value, limit=4000):
    text = str(value)
    result = ''.join(char if char in '\n\t' or not unicodedata.category(char).startswith('C')
                     else f'\\u{ord(char):04x}' for char in text[:limit])
    return result + ('\n[display excerpt]' if len(text) > limit else '')


def render_event(event):
    method, params = event.get('method'), event.get('params', {})
    item = params.get('item', {})
    if method == 'engram/episode':
        print(f"\nEpisode {params['episode']} · fresh context", flush=True)
    elif method == 'engram/checkpoint':
        cp = params['checkpoint']
        print(f"\n{terminal_text(cp['summary'])}", flush=True)
        for check in cp['checks']:
            print(f"  Check: {terminal_text(check, 1000)}", flush=True)
        for step in cp['next_steps']:
            print(f"  Next: {terminal_text(step, 1000)}", flush=True)
    elif method == 'item/started' and item.get('type') == 'commandExecution':
        print('$ ' + terminal_text(item.get('command', ''), 2000), flush=True)
    elif method == 'item/completed':
        kind = item.get('type')
        if kind == 'commandExecution':
            output = item.get('aggregatedOutput') or ''
            if output:
                print(terminal_text(output, 2400), flush=True)
            print(f"  command {terminal_text(item.get('status'))}, exit {terminal_text(item.get('exitCode'))}", flush=True)
        elif kind == 'fileChange':
            for change in item.get('changes', [])[:40]:
                print('  File: ' + terminal_text(change.get('path', ''), 1000), flush=True)
        elif kind == 'agentMessage' and item.get('phase') == 'commentary':
            print(terminal_text(item.get('text', '')), flush=True)
    elif method in {'engram/episodeLimit', 'engram/steer', 'engram/interrupt'}:
        print(terminal_text(params.get('reason', method)), flush=True)


def approve_terminal(request):
    """Only an actual escalation request prompts; ordinary repo work is sandboxed."""
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print('Codex escalation declined: an interactive terminal is required.', file=sys.stderr, flush=True)
        return False
    print('\nCodex requested additional permission:', file=sys.stderr)
    print(terminal_text(json.dumps(request.get('params', {}), ensure_ascii=False, indent=2), 8000), file=sys.stderr)
    print('Approve this request? [y/N] ', end='', file=sys.stderr, flush=True)
    try:
        return input().strip().lower() in {'y', 'yes'}
    except EOFError:
        return False


def make_coding_runtime(args, store, memory):
    from context_adna import parse_projects
    adna = parse_projects(getattr(args, 'adna_project', []))
    from context_coding_provider import CodingProvider
    if args.provider != 'codex':
        raise ValueError('Terminal coding currently uses the Codex subscription adapter; API fallback is disabled')
    if args.strict:
        raise ValueError('Terminal coding rotates episodes; strict control of every internal model call is unavailable')
    budget = Budget(input_ceiling=args.input_ceiling, soft_target=args.soft_target,
        context_window=args.context_window or 40000, output_reserve=args.max_output, margin=args.margin)
    provider = CodingProvider(model=args.model, cwd=args.repo.resolve(), timeout=args.episode_seconds,
        soft_tokens=args.soft_tokens, hard_tokens=args.hard_tokens, max_steps=args.max_steps, approve=approve_terminal)
    try:
        sources = (() if args.no_engram else (EngramSource(memory),)) + adna
        return CodingRuntime(store, provider, budget, sources=sources,
                             max_episodes=args.max_episodes, on_event=render_event)
    except BaseException:
        provider.close()
        raise


def resume_command(args, store, memory):
    # Resolve every persistence/retrieval selector so this works from any cwd,
    # including named instances and data directories containing spaces.
    command = [sys.executable, str(Path(__file__).with_name('context_cli.py')), '--data-dir', str(store.path.parent),
               '--thread', args.thread, '--model', args.model]
    if args.no_engram:
        command.append('--no-engram')
    else:
        command.extend(['--engram-db', str(memory)])
    for flag, value in (('--input-ceiling', args.input_ceiling), ('--soft-target', args.soft_target),
                        ('--max-output', args.max_output), ('--margin', args.margin)):
        command.extend([flag, str(value)])
    if args.context_window:
        command.extend(['--context-window', str(args.context_window)])
    from context_adna import parse_projects
    for source in parse_projects(getattr(args, 'adna_project', [])):
        command.extend(['--adna-project', f'{source.origin}={source.project}'])
    command.extend(['code', '--repo', str(args.repo.resolve()), '--resume',
        '--max-episodes', str(args.max_episodes), '--episode-seconds', str(args.episode_seconds),
        '--soft-tokens', str(args.soft_tokens), '--hard-tokens', str(args.hard_tokens), '--max-steps', str(args.max_steps)])
    return shlex.join(command)


def run_code(args, store, memory):
    if args.provider != 'codex':
        raise ValueError('Terminal coding currently uses the Codex subscription adapter; API fallback is disabled')
    if args.resume and args.thread == 'default':
        raise ValueError('Resume requires the saved --thread name')
    if args.thread == 'default':
        args.thread = 'code-' + uuid.uuid4().hex[:12]
    runtime = make_coding_runtime(args, store, memory)
    try:
        print(f"Engram coding · {terminal_text(args.model)} · ChatGPT subscription", flush=True)
        print(f"Task: {terminal_text(args.thread)}\nRepository: {terminal_text(args.repo.resolve())}", flush=True)
        print('Context is selected between episodes; Codex manages its internal tool context.', flush=True)
        # Print before dispatch so the task remains recoverable after a crash.
        print('Resume command: ' + terminal_text(resume_command(args, store, memory), 16000), flush=True)
        result = runtime.run(args.thread, args.task, args.resume)
        print(f"\nTask {terminal_text(result['status'])} · {result['episodes']} episode(s)", flush=True)
        if result.get('reason'):
            print(terminal_text(result['reason']), flush=True)
        if result['status'] != 'complete':
            print('Resume command: ' + terminal_text(resume_command(args, store, memory), 16000), flush=True)
            return 2
        return 0
    finally:
        # The caller owns the shared store, including when construction fails.
        runtime.provider.close()
