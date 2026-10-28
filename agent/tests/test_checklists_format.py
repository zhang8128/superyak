"""Checklists: the file format, exactly (spec, A checklist is a file; Tests, Format and Files)."""
import os
import threading
import pytest
from superyak_agent import checklists as cl, station
from checklist_fakes import EXAMPLE, list_text

GOOD = list_text('l', 'start', ('One.', 'Two.'))


def parse(data, name='l.md', own=False):
    return cl.parse(name, data, own)


def test_the_spec_example_parses():
    c = parse(EXAMPLE, 'before-push.md')
    assert (c.id, c.title, c.version, c.owner, c.read, c.post, c.see) == (
        'before-push', 'Before any push', 3, 'ships of this repository', False, None, 'docs/checklists.md#before-any-push')
    assert c.moments == (cl.Moment('command', words='git push'),) and len(c.items) == 2 and c.raw == EXAMPLE


def test_a_read_list_keeps_its_text_and_its_blank_lines():
    c = parse(list_text('why', 'start; every 3h', read='yes', body='- **For people:** homes.\n\nThe rail.'), 'why.md')
    assert c.read and c.items == () and c.body == '- **For people:** homes.\n\nThe rail.'
    assert c.moments == (cl.Moment('start'), cl.Moment('every', hours=3))


@pytest.mark.parametrize('kw, ok', [
    ({'items': ['x'] * 12}, True), ({'items': ['x'] * 13}, False),
    ({'items': ['é' * 100]}, True), ({'items': ['é' * 100 + 'x']}, False),            # 200 bytes, then 201
    ({'title': 't' * 80}, True), ({'title': 't' * 81}, False), ({'owner': 'o' * 80}, True), ({'owner': 'o' * 81}, False),
    ({'read': 'yes', 'body': 'b' * 1500}, True), ({'read': 'yes', 'body': 'b' * 1501}, False),
    ({'see': 's' * 120}, True), ({'see': 's' * 121}, False), ({'see': 'a b'}, False),
    ({'version': '999999'}, True), ({'version': '1000000'}, False), ({'version': '0'}, False), ({'version': '01'}, False),
    ({'when': 'every 1h'}, True), ({'when': 'every 24h'}, True), ({'when': 'every 25h'}, False), ({'when': 'every 0h'}, False),
    ({'when': 'command abcdef'}, True), ({'when': 'command abcde'}, False), ({'when': 'command abc;def'}, False),
    ({'when': 'start; claim; command git push'}, True), ({'when': 'room 1bfd'}, False),
    ({'post': '1bfd1b03e9f94519b1bb3c86c0fafaa1'}, True), ({'post': 'all hands'}, False),
])
def test_every_limit(kw, ok):
    if ok:
        assert parse(list_text('l', **kw)).id == 'l'
    else:
        with pytest.raises(cl.ParseError):
            parse(list_text('l', **kw))


@pytest.mark.parametrize('broken', [
    b'\n' + GOOD, GOOD.replace(b'title: List l\n', b''), GOOD.replace(b'id: l\ntitle: List l\n', b'title: List l\nid: l\n'),
    GOOD.replace(b'id: l\n', b'id: l\nid: l\n'), GOOD.replace(b'owner: ', b'tags: x\nowner: '),
    list_text('l', post='r1', see='a').replace(b'post: r1\nsee: a\n', b'see: a\npost: r1\n'),
    GOOD.replace(b'- [ ] Two.', b'\n- [ ] Two.'), GOOD.replace(b'\n', b'\r\n'), b'\xef\xbb\xbf' + GOOD,
    GOOD.replace(b'title: List l', b'title: "List l"'), GOOD.replace(b'when: start', b'when: start; start'),
    GOOD.replace(b'when: start', b'when: every 1h; every 3h'), GOOD.replace(b'when: start', b'when: start;start'),
    list_text('l', read='no', body='x'), GOOD.replace(b'One.', b'One.\tTab'), GOOD.replace(b'List l', 'List \u202el'.encode()),
    GOOD[:-1], GOOD + b'\n', list_text('l', read='yes', body='Text.\n- [ ] Tick me.'), list_text('l', items=()),
    GOOD.replace(b'One.', b'One\xff.'),
])
def test_anything_else_is_a_parse_error(broken):
    with pytest.raises(cl.ParseError):
        parse(broken)


def test_the_name_is_the_id_and_enter_follows_where_the_file_lives():
    for name, data, own in [('other.md', GOOD, False), ('Before-Push.md', list_text('Before-Push'), False),
                            ('l.md', list_text('l', 'enter /abs'), False), ('l.md', list_text('l', 'enter'), True),
                            ('l.md', list_text('l', 'enter rel/x'), True)]:
        with pytest.raises(cl.ParseError):
            cl.parse(name, data, own)
    assert cl.parse('l.md', list_text('l', 'enter /abs'), True).moments == (cl.Moment('enter', path='/abs'),)
    assert cl.parse('l.md', list_text('l', 'enter'), False).moments == (cl.Moment('enter'),)


def test_symlinks_fifos_and_oversized_files_are_refused_without_blocking(tmp_path):
    (tmp_path / 'real.md').write_bytes(EXAMPLE)
    os.symlink(tmp_path / 'real.md', tmp_path / 'link.md')
    os.mkfifo(tmp_path / 'pipe.md')
    (tmp_path / 'big.md').write_bytes(b'x' * 4097)
    (tmp_path / 'edge.md').write_bytes(b'x' * 4096)
    for name in ('link.md', 'pipe.md', 'big.md'):
        raised = []

        def attempt():
            try:
                cl.read_file(tmp_path / name)
            except cl.ParseError:
                raised.append(name)
        worker = threading.Thread(target=attempt, daemon=True)
        worker.start()
        worker.join(1.0)
        assert raised == [name]                       # refused, and never blocked on the FIFO
    assert cl.read_file(tmp_path / 'edge.md') == b'x' * 4096


def test_post_ids_are_the_stations_plain_ids():
    assert cl.POST_ID.pattern == station.PLAIN_ID.pattern
