"""Explicit, bounded, read-only aDNA project context with origin-qualified IDs.

Documents remain source accounts. This adapter never runs aDNA skills, follows
lattice references, publishes records, or grants access to another peer.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
from urllib.parse import quote, unquote

from context_compile import Candidate


LEGS = ("who", "what", "how")
ROOT_FILES = {"AGENTS.md", "CLAUDE.md", "MANIFEST.md", "STATE.md", "README.md"}
ORIGIN = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
MAX_FILE_BYTES = 64 * 1024


def parse_projects(specs):
    """Parse explicit INSTANCE=PATH selectors; never infer a peer identity."""
    if len(specs) > 6:
        raise ValueError("At most six aDNA projects can be selected")
    sources = []
    seen = set()
    for spec in specs:
        origin, separator, path = spec.partition("=")
        if not separator or not path or not ORIGIN.fullmatch(origin):
            raise ValueError("aDNA projects require INSTANCE=PATH with a lowercase DNS-style instance name")
        if origin in seen:
            raise ValueError("aDNA project origins must be unique")
        seen.add(origin)
        sources.append(AdnaSource(path, origin=origin))
    return tuple(sources)


class AdnaSource:
    mode = "adna_project"

    def __init__(self, path, *, origin, max_files=1024, max_bytes=8 * 1024 * 1024, timeout=1.0):
        if not isinstance(origin, str) or not ORIGIN.fullmatch(origin):
            raise ValueError("Invalid aDNA origin")
        if type(max_files) is not int or not 1 <= max_files <= 4096:
            raise ValueError("aDNA max_files must be between 1 and 4096")
        if type(max_bytes) is not int or not 1 <= max_bytes <= 32 * 1024 * 1024:
            raise ValueError("Invalid aDNA byte budget")
        if not isinstance(timeout, (float, int)) or not 0 < timeout <= 5:
            raise ValueError("Invalid aDNA scan timeout")
        self.project = Path(path).expanduser().resolve()
        for root, layout in ((self.project, "bare"), (self.project / ".agentic", "embedded"),
                             (self.project / ".adna", "framework")):
            if root.is_dir() and not root.is_symlink() and all((root / leg).is_dir() for leg in LEGS):
                self.root, self.layout = root, layout
                break
        else:
            raise ValueError("Select an aDNA project containing who/, what/, how/ (bare, .agentic, or .adna)")
        self.origin = origin
        self.max_files, self.max_bytes, self.timeout = max_files, max_bytes, float(timeout)
        info = self.root.stat()
        self._identity = (info.st_dev, info.st_ino)
        self.coverage = {}

    def _root_fd(self):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != self._identity:
            os.close(fd)
            raise OSError("aDNA project root was replaced")
        return fd

    @staticmethod
    def _allowed(relative):
        parts = PurePosixPath(relative).parts
        if (not parts or len(parts) > 12 or "\\" in relative or len(quote(relative, safe="/")) > 180
                or any(p.startswith(".") or p == "/" for p in parts)
                or str(PurePosixPath(relative)) != relative):
            return False
        if len(parts) == 1:
            return relative in ROOT_FILES
        return parts[0] in LEGS and (relative.endswith(".md") or relative.endswith((".lattice.yaml", ".lattice.yml")))

    def _document(self, relative):
        if not self._allowed(relative):
            return None
        fd = None
        try:
            fd = self._root_fd()
            parts = PurePosixPath(relative).parts
            for index, part in enumerate(parts):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if index < len(parts) - 1:
                    flags |= os.O_DIRECTORY
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                return None
            chunks, size = [], 0
            while size <= MAX_FILE_BYTES:
                chunk = os.read(fd, min(8192, MAX_FILE_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            if size > MAX_FILE_BYTES:
                return None
            raw = b"".join(chunks)
            text = raw.decode("utf-8")
            if "\0" in text:
                return None
            return text, hashlib.sha256(raw).hexdigest(), len(raw)
        except (OSError, UnicodeError):
            return None
        finally:
            if fd is not None:
                os.close(fd)

    def _scan(self):
        deadline = time.monotonic() + self.timeout
        self.coverage = {"origin": self.origin, "complete": True, "files_scanned": 0,
                         "bytes_scanned": 0, "skipped_files": 0, "entries_scanned": 0}
        status = self.coverage
        stopped = False

        def walk(fd, prefix=""):
            nonlocal stopped
            entries = []
            with os.scandir(fd) as iterator:
                for entry in iterator:
                    status["entries_scanned"] += 1
                    if status["entries_scanned"] > 8192 or time.monotonic() >= deadline:
                        status["complete"] = False
                        stopped = True
                        return
                    entries.append(entry.name)
            for name in sorted(entries):
                if stopped or status["files_scanned"] >= self.max_files or time.monotonic() >= deadline:
                    status["complete"] = False
                    stopped = True
                    return
                if name.startswith("."):
                    continue
                relative = f"{prefix}/{name}" if prefix else name
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        if (prefix or name in LEGS) and len(PurePosixPath(relative).parts) < 12:
                            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                            try:
                                yield from walk(child, relative)
                            finally:
                                os.close(child)
                    elif self._allowed(relative):
                        status["files_scanned"] += 1
                        document = self._document(relative)
                        if document is None:
                            status["skipped_files"] += 1
                            status["complete"] = False
                            continue
                        text, version, size = document
                        if status["bytes_scanned"] + size > self.max_bytes:
                            status["complete"] = False
                            stopped = True
                            return
                        status["bytes_scanned"] += size
                        yield relative, text, version
                except OSError:
                    status["skipped_files"] += 1
                    status["complete"] = False
        try:
            fd = self._root_fd()
            try:
                yield from walk(fd)
            finally:
                os.close(fd)
        except OSError:
            status["complete"] = False
            status["unavailable"] = True

    def _id(self, relative):
        return f"adna:{self.origin}:" + quote(relative, safe="/")

    def _relative(self, source_id):
        prefix = f"adna:{self.origin}:"
        if not isinstance(source_id, str) or not source_id.startswith(prefix):
            return None
        encoded = source_id[len(prefix):]
        relative = unquote(encoded)
        return relative if self._allowed(relative) and quote(relative, safe="/") == encoded else None

    def search(self, query, limit=8):
        terms = set(re.findall(r"[^\W_]+", query[:2000].casefold()))
        found = []
        for relative, text, version in self._scan():
            score = len(terms & set(re.findall(r"[^\W_]+", (relative + " " + text).casefold())))
            if not score:
                continue
            # Keep originals available by ID; select a located excerpt for the
            # bounded model input when the matching material is late in a file.
            position = next((m.start() for m in re.finditer(r"[^\W_]+", text) if m.group().casefold() in terms), 0)
            start = max(0, position - 300) if len(text) > 8192 else 0
            account = {"origin": self.origin, "path": relative, "leg": relative.split("/")[0] if "/" in relative else "governance",
                       "account": text[start:start + 8192], "offset": start,
                       "truncated": start > 0 or len(text) > 8192, "content_sha256": version}
            found.append(Candidate(self._id(relative), "user", (json.dumps(account, ensure_ascii=False),),
                                   score=float(score), reason="aDNA source account", version=version))
        return sorted(found, key=lambda c: (-c.score, c.id))[:max(0, min(int(limit), 32))]

    def read(self, source_id, *, offset=0, limit=4096):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 4096:
            raise ValueError("Invalid aDNA source page")
        relative = self._relative(source_id)
        document = self._document(relative) if relative is not None else None
        if document is None:
            return None
        text, version, _ = document
        return {"id": source_id, "origin": self.origin, "path": relative, "version": version,
                "text": text[offset:offset + limit], "offset_unit": "characters",
                "next_offset": offset + limit if offset + limit < len(text) else None}

    def valid(self, candidate):
        relative = self._relative(candidate.id)
        document = self._document(relative) if relative is not None else None
        return document is not None and document[1] == candidate.version

    def inspect(self):
        documents = [{"id": self._id(path), "path": path, "version": version} for path, _, version in self._scan()]
        return {"origin": self.origin, "project": str(self.project), "root": str(self.root),
                "layout": self.layout, "documents": documents, "coverage": dict(self.coverage)}
