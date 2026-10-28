"""Builders for checklist tests."""
import json
import os
from pathlib import Path

EXAMPLE = b'''---
id: before-push
title: Before any push
when: command git push
version: 3
owner: ships of this repository
see: docs/checklists.md#before-any-push
---
- [ ] The branch's base is on the rewritten history: `git merge-base --is-ancestor 60dd851 HEAD`.
- [ ] Nothing in the diff names a person's details or holds a key or token.
'''


def list_text(list_id, when='start', items=('Do the thing.',), *, title=None, version=1,
              owner='ships of this repository', read=None, post=None, see=None, body=None) -> bytes:
    head = f'---\nid: {list_id}\ntitle: {title if title is not None else "List " + list_id}\nwhen: {when}\n' \
           f'version: {version}\nowner: {owner}\n'
    for key, value in (('read', read), ('post', post), ('see', see)):
        if value is not None:
            head += f'{key}: {value}\n'
    if read is not None:
        text = body if body is not None else ''
    else:
        text = '\n'.join(f'- [ ] {item}' for item in items)
    return (head + '---\n' + text + '\n').encode()


def write_list(directory, list_id, **kw) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o755)
    path = directory / f'{list_id}.md'
    path.write_bytes(list_text(list_id, **kw))
    os.chmod(path, 0o644)
    return path


def checkout(root, *lists) -> Path:
    root = Path(root)
    (root / '.git').mkdir(parents=True, exist_ok=True)
    directory = root / '.superyak' / 'checklists'
    for list_id, kw in lists:
        write_list(directory, list_id, **kw)
    if not lists:
        directory.mkdir(parents=True, exist_ok=True)
    for d in (root / '.superyak', directory):
        os.chmod(d, 0o755)
    return root


def trust_dirs(own_dir, *dirs) -> None:
    own_dir = Path(own_dir)
    own_dir.mkdir(parents=True, exist_ok=True)
    path = own_dir / 'trusted.json'
    path.write_text(json.dumps({'trusted': [os.path.realpath(d) for d in dirs]}))
    os.chmod(path, 0o600)
