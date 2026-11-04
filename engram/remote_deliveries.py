"""What arrived from another peer's store, so it is never kept here (ship home and crossing spec 2.5's second rule;
plan P16, S7, S8, nit 8).

`remote-deliveries.db` sits beside the receiving store's graph.db. For each remote item a crossing delivers it holds
the SHA-256 of the item's normalized text (`item`) and of each of its sentences of 12 words or more (`sentence`), with
the read's disclosureId, for 90 days. Every tool that stores text at the home asks `refused` first, on its raw
arguments, in every gate mode.

Normalized: Unicode NFKC, leading Markdown markers stripped (`- `, `* `, `+ `, `> `, `1. `, `1) `, repeatedly), then
casefolded, with whitespace runs made one space and stripped. Sentences are split on the text before it is normalized,
twice: after `.`, `!` or `?` followed by whitespace, or at a newline; and with newlines folded, after an end mark only
(section 2 review, S2), so a hard-wrapped sentence copied unwrapped still matches. Each is then normalized, markers
and all, and its words are its whitespace-separated runs. A text is refused when its normalized digest is among the recorded digests of either
part, or when one of its sentences of 12 words or more has a digest among them.

What it doesn't catch, said plainly: a paraphrase, a copy made after 90 days, a delivered sentence under 12 words
however long its item, and a 12-word sentence carried with other words on the same line ("Note: ...").

The file runs in WAL with a busy timeout, so a guard's read never waits on a writer. A record or a read that stays
busy past the timeout raises RecordBusy ("busy, try again"); a file that is not SQLite, lacks the table or is corrupt
raises Unreadable with its cause. A missing file means nothing was ever delivered remotely, since a failed record
delivers nothing."""
from __future__ import annotations

from contextlib import closing
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import threading
import unicodedata

FILE_NAME = "remote-deliveries.db"
KEEP_SECONDS = 90 * 86400
PRUNE_SECONDS = 3600
BUSY_MS = 2000
MIN_WORDS = 12
_MARKER = re.compile(r"(?:[-*+>]|[0-9]+[.)])\s+")
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n")
_FOLDED_SPLIT = re.compile(r"(?<=[.!?])\s+")   # newlines folded into the sentence: splits at end marks only
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS remote_deliveries(disclosure_id TEXT NOT NULL, publisher TEXT NOT NULL, "
    "memory_id TEXT NOT NULL, part TEXT NOT NULL CHECK(part IN ('item','sentence')), digest TEXT NOT NULL, "
    "at INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS remote_deliveries_digest ON remote_deliveries(digest)",
    "CREATE INDEX IF NOT EXISTS remote_deliveries_at ON remote_deliveries(at)",
    "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)


class RecordBusy(Exception):
    """The file stayed locked past the busy timeout: busy, try again. Never read as unreadable."""


class Unreadable(Exception):
    """The file is not SQLite, lacks the table, or is corrupt: every keep is refused until it is fixed."""


def path_for(db_path) -> Path:
    """The record beside a store: `<the store's directory>/remote-deliveries.db`. A store with no file (`:memory:`)
    has no place for one: ValueError, so a delivery to it is never recorded in some working directory instead."""
    if not db_path or str(db_path) == ":memory:" or str(db_path).startswith("file::memory:"):
        raise ValueError("a store with no file has no remote deliveries record")
    return Path(db_path).parent / FILE_NAME


def strip_markers(text: str) -> str:
    """Leading Markdown markers, removed repeatedly (S8): "> - x" is "x". A marker mid-text is left alone."""
    text = text.lstrip()
    while True:
        found = _MARKER.match(text)
        if found is None:
            return text
        text = text[found.end():].lstrip()


def normalize(text: str) -> str:
    return " ".join(strip_markers(unicodedata.normalize("NFKC", text)).casefold().split())


def sentences(text: str) -> list[str]:
    """The text's sentences, split before normalizing (so newlines still split), each normalized; empty ones dropped."""
    return [s for s in (normalize(part) for part in _SPLIT.split(text)) if s]


def folded_sentences(text: str) -> list[str]:
    """The text's sentences with newlines folded to spaces, split only after an end mark (section 2 review, S2), so a
    sentence hard-wrapped across lines is one sentence; each normalized, empty ones dropped."""
    return [s for s in (normalize(part) for part in _FOLDED_SPLIT.split(text)) if s]


def digest(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def digests(text: str) -> tuple[str, list[str]]:
    """(the item digest, the digests of its sentences of MIN_WORDS words or more, split both ways: at end marks and
    newlines, and with newlines folded, so a wrapped sentence copied unwrapped matches, and the reverse)."""
    long = [s for s in sentences(text) + folded_sentences(text) if len(s.split()) >= MIN_WORDS]
    return digest(normalize(text)), list(dict.fromkeys(digest(s) for s in long))


def _is_busy(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    if code is not None and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return True
    return isinstance(error, sqlite3.OperationalError) and "locked" in str(error).lower()


def _open(path: Path) -> sqlite3.Connection:
    """The file opened read-write (never read-only: a WAL file with no -wal or -shm would read as unreadable),
    with the busy timeout. It is created 0600 if absent."""
    con = sqlite3.connect(str(path), timeout=BUSY_MS / 1000, isolation_level=None)
    con.execute(f"PRAGMA busy_timeout={int(BUSY_MS)}")
    return con


def _fault(error: Exception, path: Path) -> Exception:
    if isinstance(error, sqlite3.Error) and _is_busy(error):
        return RecordBusy("busy, try again")
    return Unreadable(f"{path}: {error}")


def _create(path: Path) -> None:
    """Make the file WAL from the moment it exists: set up under a name of its own, then linked into place (a link never
    replaces a file another writer made first). Two connections setting up one file in rollback mode can deadlock, and
    SQLite then answers one of them busy at once."""
    staged = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.new")
    os.close(os.open(staged, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
    try:
        with closing(sqlite3.connect(str(staged), isolation_level=None)) as con:
            con.execute("PRAGMA journal_mode=WAL")
            for statement in _SCHEMA:
                con.execute(statement)
        try:
            os.link(staged, path)
        except FileExistsError:
            pass                                  # another writer made it first: that one is used
    finally:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{staged}{suffix}").unlink(missing_ok=True)


def record(path, items, *, now: int) -> None:
    """Record each delivered remote item (dicts with disclosureId, publisher, memoryId, content) in one transaction,
    and, at most once an hour per file (the last prune's time is in `meta`), delete rows older than 90 days in it."""
    path = Path(path)
    rows = []
    for item in items:
        whole, parts = digests(item["content"])
        rows.append((item["disclosureId"], item["publisher"], item["memoryId"], "item", whole, now))
        rows += [(item["disclosureId"], item["publisher"], item["memoryId"], "sentence", d, now) for d in parts]
    try:
        if not path.exists():
            _create(path)
        with closing(_open(path)) as con:
            if con.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                con.execute("PRAGMA journal_mode=WAL")
            for statement in _SCHEMA:
                con.execute(statement)
            con.execute("BEGIN IMMEDIATE")
            try:
                con.executemany("INSERT INTO remote_deliveries VALUES(?,?,?,?,?,?)", rows)
                last = con.execute("SELECT value FROM meta WHERE key='last_prune'").fetchone()
                if last is None or now - int(last[0]) >= PRUNE_SECONDS:
                    con.execute("DELETE FROM remote_deliveries WHERE at < ?", (now - KEEP_SECONDS,))
                    con.execute("INSERT INTO meta VALUES('last_prune', ?) ON CONFLICT(key) DO UPDATE SET "
                                "value=excluded.value", (str(now),))
                con.execute("COMMIT")
            except BaseException:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                raise
    except (sqlite3.Error, ValueError) as error:
        raise _fault(error, path) from error


def _recorded(path: Path, wanted, now: int) -> set:
    """Which of the `wanted` digests are recorded in the last 90 days. RecordBusy or Unreadable when it can't read."""
    wanted = sorted(set(wanted))
    if not wanted or not path.exists():
        return set()
    try:
        with closing(_open(path)) as con:
            columns = {row[1] for row in con.execute("PRAGMA table_info(remote_deliveries)")}
            if not {"digest", "at", "part"} <= columns:
                raise Unreadable(f"{path}: it holds no remote_deliveries table")
            marks = ",".join("?" * len(wanted))
            return {row[0] for row in con.execute(
                f"SELECT DISTINCT digest FROM remote_deliveries WHERE digest IN ({marks}) AND at >= ?",
                (*wanted, now - KEEP_SECONDS))}
    except sqlite3.Error as error:
        raise _fault(error, path) from error


def _spans(text: str, pattern) -> list[tuple[int, int]]:
    spans, start = [], 0
    for found in pattern.finditer(text):
        spans.append((start, found.start()))
        start = found.end()
    return spans + [(start, len(text))]


def redact(path, text: str, *, now: int) -> str:
    """For a tool that stores only a log line (section 2 review, Rio Grande's third place): `text` with a delivered
    item, or each delivered sentence of 12 words or more (either split), replaced by its digest, so the log holds no
    remote text and the tool works as normal. RecordBusy or Unreadable when the record can't be read."""
    path = Path(path)
    if not isinstance(text, str) or not text.strip() or not path.exists():
        return text
    whole = digest(normalize(text))
    parts = []
    for pattern in (_SPLIT, _FOLDED_SPLIT):
        for start, end in _spans(text, pattern):
            sentence = normalize(text[start:end])
            if len(sentence.split()) >= MIN_WORDS:
                parts.append((start, end, digest(sentence)))
    found = _recorded(path, [whole] + [d for _, _, d in parts], now)
    if whole in found:
        return f"[delivered from another peer, sha256 {whole}]"
    marked = sorted((start, end, d) for start, end, d in parts if d in found)
    merged = []
    for start, end, d in marked:
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]), merged[-1][2])
        else:
            merged.append((start, end, d))
    for start, end, d in reversed(merged):
        text = f"{text[:start]}[delivered from another peer, sha256 {d}]{text[end:]}"
    return text


def refused(path, texts, *, now: int) -> bool:
    """Whether any of `texts` is a copy of a remote item delivered in the last 90 days, whole or by a sentence of 12
    words or more. False when the file is absent. RecordBusy or Unreadable when it can't be read (S7)."""
    path = Path(path)
    candidates = [t for t in texts if isinstance(t, str) and t.strip()]
    if not candidates or not path.exists():
        return False
    wanted = set()
    for text in candidates:
        whole, parts = digests(text)
        wanted.add(whole)
        wanted.update(parts)
    return bool(_recorded(path, wanted, now))
