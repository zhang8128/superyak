"""The hold's checklists provider (spec, The hold; Rulings 15, 16, 33, 34).

Standard library only, plus checklists, checklist_firing and holds: the hold path stays light. `provider` finds and
renders the lists a command matches before any lock (S5); `candidates` runs under the session record's lock and only
marks the record, which the entry saves when it prints.
"""
from pathlib import Path

from superyak_agent import checklist_firing as fp, checklists, holds

HELD = 'Held once: checklist {id} v{version} applies. It is a checklist, not a refusal.'
FIXED_CHARS = 200   # the first line, the re-run line and the blank lines between a deny's parts


def held(record: dict) -> int:
    """The commands held this session, by either provider; a damaged count reads as none and heals on the next hold."""
    count = record.get('holds')
    return count if type(count) is int and count > 0 else 0


class ChecklistProvider:
    def __init__(self, matching: tuple, texts: dict):
        self.matching = matching    # the loaded lists with a `command` moment the command matches
        self.texts = texts          # list key -> its rendered text

    def candidates(self, command: str, record: dict, now: float, limit: int) -> list:
        """The due lists placed in this hold, at most `limit`, each whole (Ruling 34): the placed lists' texts, the
        fixed lines and room for a lesson in each hold left over must fit in OUTPUT_CHARS; past the cap only the lists'
        texts count. The placed lists are marked fired with the command's digest and every other due list passed, so
        the re-run passes (Rulings 15, 16, 33). Past the cap nothing is held, so no digest is kept: a list shows as
        context at every matching command (section 2's M1)."""
        due, digest = fp.due_at_command(self.matching, record, command, now)
        past = held(record) >= holds.HOLDS_PER_SESSION
        placed, passed = [], []
        for loaded, kinds in due:
            texts = [self.texts[p.key] for p, _ in placed] + [self.texts[loaded.key]]
            size = len('\n\n'.join(texts))
            if not past:
                size += FIXED_CHARS + holds.LESSON_BYTES * max(0, holds.HOLDS_PER_SESSION - len(texts))
            if len(placed) < limit and size <= holds.OUTPUT_CHARS:
                placed.append((loaded, kinds))
            else:
                passed.append((loaded, kinds))
        fp.mark_fired(record, placed, now, digest=None if past else digest)
        if not past:
            fp.mark_passed(record, passed, digest)
        return [holds.Hold('checklist', loaded.key, self.texts[loaded.key]) for loaded, _ in placed]

    def spend(self, command: str, record: dict) -> bool:
        """The command goes through unheld: every matching list's pass for it is spent, the re-run's included, so a
        later identical command is held again, or shown as context past the cap (section 2's M1)."""
        return fp.spend(record, self.matching, fp.command_digest(command))


def provider(home: Path, cwd: str | None, command: str) -> ChecklistProvider:
    """The lists this ship trusts here whose `command` moment the command matches, each rendered, before any lock."""
    found = checklists.find(cwd, Path(home) / 'checklists')
    matching = tuple(loaded for loaded in found.lists
                     if any(m.kind == 'command' and checklists.command_matches(m.words, command)
                            for m in loaded.checklist.moments))
    return ChecklistProvider(matching, {loaded.key: checklists.render(loaded) for loaded in matching})


def _version(record: dict, key: str):
    entry = record.get('fired', {}).get(key, {})
    return entry.get('version')


def first_line(record: dict, hold: holds.Hold) -> str:
    """The deny's first line, naming the first list as it was when it fired."""
    return HELD.format(id=hold.key.split('/', 1)[1], version=_version(record, hold.key))


def fired_lines(record: dict, shown: list, session: str, now: float) -> list[dict]:
    return [fp.fired_line(now, session, hold.key, _version(record, hold.key), 'command')
            for hold in shown if hold.kind == 'checklist']
