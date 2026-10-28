"""Checklists: what the run and firing logs say about each list (spec, Renegotiation). Pure: it proposes, never applies.

Standard library only.
"""
import json
from pathlib import Path

from .checklists import _clean
from typing import NamedTuple

KILLER = 'killer:'
NEVER = 'never retires'


class Proposal(NamedTuple):
    kind: str          # retire, keep, drop, why, unrun
    key: str
    version: int
    item: int | None   # numbered from 1
    detail: str
    killer: bool = False


def read_lines(path: Path) -> list[dict]:
    try:
        text = Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []
    lines = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            lines.append(value)
    return lines


def _time(line: dict) -> float:
    value = line.get('time')
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _same(line: dict, other: dict) -> bool:
    return (isinstance(line.get('session'), str) and line.get('session') == other.get('session') and line.get('key') == other.get('key')
            and line.get('version') == other.get('version'))


def unrun(fired: list[dict], runs: list[dict]) -> list[tuple[dict, str | None]]:
    out = []
    for line in fired:
        if 'moment' not in line:
            continue
        later = [r for r in runs if _same(r, line) and _time(r) >= _time(line)]
        if any(isinstance(r.get('answers'), list) for r in later):
            continue
        refusal = next((r['refused'] for r in later if isinstance(r.get('refused'), str)), None)
        out.append((line, refusal))
    return out


def _answer(run: dict, index: int) -> dict:
    answers = run.get('answers')
    if isinstance(answers, list) and index < len(answers) and isinstance(answers[index], dict):
        return answers[index]
    return {}


def _reasons(answers: list[dict]) -> str:
    groups: dict[str, int] = {}
    for a in answers:
        reason = a.get('reason')
        name = _clean(reason) if isinstance(reason, str) and reason else 'no reason'
        groups[name] = groups.get(name, 0) + 1
    return '; '.join(f'{name} ({n})' for name, n in groups.items())


def report(fired: list[dict], runs: list[dict], last: int = 10, texts: dict | None = None) -> list[Proposal]:
    groups: dict[tuple[str, int], list[dict]] = {}
    for run in sorted((r for r in runs if isinstance(r.get('answers'), list)), key=_time):
        key, version = run.get('key'), run.get('version')
        if isinstance(key, str) and isinstance(version, int):
            groups.setdefault((key, version), []).append(run)
    proposals: list[Proposal] = []
    for (key, version), group in groups.items():
        width = max(len(r['answers']) for r in group)
        recent = group[-last:]
        for index in range(width):
            number = index + 1
            item_text = None
            if texts is not None:
                listed = texts.get((key, version)) or []
                item_text = listed[index] if index < len(listed) else None
            killer = bool(item_text) and item_text.lstrip().lower().startswith(KILLER)
            never = bool(item_text) and NEVER in item_text.lower()
            given = [_answer(r, index) for r in group]
            recent_given = [a.get('answer') for a in (_answer(r, index) for r in recent)]
            if len(recent) >= last and all(a == 'done-before-asked' for a in recent_given) and not never:
                evidence = f'done-before-asked in {last} of the last {last} runs'
                if texts is None:
                    detail = evidence
                elif killer:
                    detail = f'rung: held by a script or test; evidence: {evidence}; it stays killer'
                else:
                    detail = f'rung: remembered (a rail lesson); evidence: {evidence}'
                proposals.append(Proposal('retire', key, version, number, detail, killer))
            guarded = texts is not None and (killer or never)   # Ruling 47: no count removes these
            if len(recent) >= last and all(a == 'n/a' for a in recent_given) and not guarded:
                proposals.append(Proposal('drop', key, version, number, f'n/a in {last} of the last {last} runs', killer))
            caught = [a for a in given if a.get('answer') == 'caught']
            if caught:
                proposals.append(Proposal('keep', key, version, number,
                                          f'caught {len(caught)} time(s): {_reasons(caught)}', killer))
            skipped = [a for a in given if a.get('answer') == 'skipped']
            if (killer and skipped) or len(skipped) * 2 > len(group):   # a killer skip at any count (section 2's M2)
                proposals.append(Proposal('why', key, version, number,
                                          f'skipped in {len(skipped)} of {len(group)} runs: {_reasons(skipped)}', killer))
    counts: dict[tuple[str, int], list[str | None]] = {}
    for line, refusal in unrun(fired, runs):
        key, version = line.get('key'), line.get('version')
        if isinstance(key, str) and isinstance(version, int):
            counts.setdefault((key, version), []).append(refusal)
    for (key, version), refusals in counts.items():
        kinds = sorted({r for r in refusals if r})
        extra = f'; refused as {", ".join(kinds)}' if kinds else ''
        proposals.append(Proposal('unrun', key, version, None, f'fired {len(refusals)} time(s) with no run{extra}'))
    return proposals


def render_report(proposals: list[Proposal], misses: int) -> str:
    ordered = sorted(proposals, key=lambda p: not (p.kind == 'why' and p.killer))
    lines = []
    for p in ordered:
        where = f'{_clean(p.key)} v{p.version}' + (f' item {p.item}' if p.item is not None else '')
        mark = ' (killer)' if p.killer else ''
        lines.append(f'{p.kind}: {where}{mark}: {_clean(p.detail)}')
    if not lines:
        lines.append('Nothing to propose.')
    if misses:
        lines.append(f'{misses} firing(s) missed in the log.')
    lines.append('These are proposals. Nothing was changed.')
    return '\n'.join(lines)
