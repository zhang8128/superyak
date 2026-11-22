"""Issue #8's corpus v0: a Wikipedia multistream dump becomes records for ``atlas/workbench/research_corpus.build``.

Each record is one main-namespace article that isn't a redirect: its title, page id and revision id from the dump,
its lead section (the text before the first heading) as plain text, and the links that lead section's own wikitext
makes, with redirects resolved one step. Nothing here reads a question, so a corpus built from it stays
question-independent.

``read_streams`` takes the dump's first N page streams, using the offsets in its index file, so a slice can be built
without the whole file. The wikitext cleaning is deliberately simple. It drops templates, tables, references,
comments, files and categories, keeps link labels, and loses whatever a template would have rendered, such as dates
and infobox facts. That loss is the same for every arm.
"""
from __future__ import annotations

import bz2
import re
from typing import Iterable, Iterator
from xml.etree import ElementTree

TEXT_LIMIT = 18000
_SKIP_LINKS = re.compile(r"^\s*:?\s*(file|image|media|category|wikipedia|wp|wikt|wiktionary|help|template|portal|"
                         r"special|user|talk|draft|module|[a-z]{2,3}(-[a-z]+)?)\s*:", re.I)
_LINK = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")
_EXTERNAL = re.compile(r"\[(?:https?:)?//[^\s\]]+(?:\s+([^\]]*))?\]")


def canonical(title: str) -> str:
    """A link target as MediaWiki names the page: no anchor, spaces not underscores, the first letter upper case."""
    title = " ".join(title.split("#", 1)[0].replace("_", " ").split())
    return title[:1].upper() + title[1:]


def lead(wikitext: str) -> str:
    match = re.search(r"^==", wikitext, re.M)
    return (wikitext[:match.start()] if match else wikitext).strip()


def _drop_nested(text: str, opener: str, closer: str) -> str:
    out, depth, i = [], 0, 0
    while i < len(text):
        if text.startswith(opener, i):
            depth, i = depth + 1, i + len(opener)
        elif depth and text.startswith(closer, i):
            depth, i = depth - 1, i + len(closer)
        else:
            if not depth:
                out.append(text[i])
            i += 1
    return "".join(out)


def _drop_media(text: str) -> str:
    """[[File:...]], [[Image:...]] and [[Category:...]], whose captions may hold links of their own."""
    out, i = [], 0
    while i < len(text):
        if text.startswith("[[", i) and re.match(r"\[\[\s*:?\s*(file|image|media|category)\s*:", text[i:i + 20], re.I):
            depth, j = 0, i
            while j < len(text):
                if text.startswith("[[", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("]]", j):
                    depth, j = depth - 1, j + 2
                    if depth == 0:
                        break
                else:
                    j += 1
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def clean(wikitext: str) -> tuple[str, list[str]]:
    """Plain text and the article links, in order of first appearance."""
    text = re.sub(r"<!--.*?-->", "", wikitext, flags=re.S)
    text = re.sub(r"<ref[^>/]*/>", "", text, flags=re.I)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.I | re.S)
    text = _drop_nested(text, "{{", "}}")
    text = _drop_nested(text, "{|", "|}")
    text = _drop_media(text)
    links: list[str] = []

    def link(match: re.Match) -> str:
        target, label = match.group(1), match.group(2)
        if _SKIP_LINKS.match(target):   # not an article: keep a label's words, collect no link
            return label or ""
        name = canonical(target)
        if name and name not in links:
            links.append(name)
        return label if label is not None else target.split("#", 1)[0]

    text = _LINK.sub(link, text)
    text = _EXTERNAL.sub(lambda m: m.group(1) or "", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"<[^>]+>", "", text)
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p), links


def read_streams(dump, index, streams: int) -> Iterator[bytes]:
    """The dump's first ``streams`` page streams, decompressed, each a run of whole <page> elements."""
    offsets: list[int] = []
    with bz2.open(index, "rt", encoding="utf-8") as lines:
        for line in lines:
            offset = int(line.split(":", 1)[0])
            if not offsets or offset != offsets[-1]:
                offsets.append(offset)
                if len(offsets) >= streams:
                    break
    with open(dump, "rb") as handle:
        for offset in offsets[:streams]:
            yield read_stream(handle, offset)


def read_stream(handle, offset: int) -> bytes:
    """One bz2 stream of the dump, starting at ``offset``, decompressed."""
    handle.seek(offset)
    decompressor, parts = bz2.BZ2Decompressor(), []
    while not decompressor.eof:
        chunk = handle.read(1 << 20)
        if not chunk:
            raise ValueError(f"the stream at {offset} ends early")
        parts.append(decompressor.decompress(chunk))
    return b"".join(parts)


def parse_pages(chunks: Iterable[bytes]) -> Iterator[dict]:
    for chunk in chunks:
        if b"<!DOCTYPE" in chunk or b"<!ENTITY" in chunk:  # a dump's pages never declare one: refuse, don't expand
            raise ValueError("a page stream declares a DTD or an entity")
        root = ElementTree.fromstring(b"<pages>" + chunk + b"</pages>")
        for page in root.iter("page"):
            redirect = page.find("redirect")
            revision = page.find("revision")
            yield {"title": page.findtext("title", ""), "ns": int(page.findtext("ns", "-1")),
                   "page_id": int(page.findtext("id", "0")),
                   "rev_id": int(revision.findtext("id", "0")) if revision is not None else 0,
                   "redirect": redirect.get("title") if redirect is not None else None,
                   "text": (revision.findtext("text") or "") if revision is not None else ""}


def records(pages: Iterable[dict]) -> list[dict]:
    """Corpus records from parsed pages: articles only, lead sections only, links through redirects resolved."""
    pages = list(pages)
    redirects = {canonical(p["title"]): canonical(p["redirect"]) for p in pages if p["ns"] == 0 and p["redirect"]}
    out = []
    for p in pages:
        if p["ns"] != 0 or p["redirect"]:
            continue
        text, links = clean(lead(p["text"]))
        if not text or len(text) > TEXT_LIMIT:
            continue
        title = canonical(p["title"])
        resolved = list(dict.fromkeys(redirects.get(name, name) for name in links))
        out.append({"title": title, "page_id": p["page_id"], "rev_id": p["rev_id"], "text": text,
                    "links": [name for name in resolved if name != title]})
    return out
