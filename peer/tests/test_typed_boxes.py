"""tests/typed_boxes.py names every typed box the app's scripts draw, with how a redraw tells it apart (Tardis's
test:every-typed-box-has-an-owner). The watch itself is tested in test_browser.py."""
from pathlib import Path
import re

from tests import typed_boxes

STATIC = Path(__file__).resolve().parents[1] / 'superyak_peer' / 'static'


def typed_inputs():
    """The input types app.js gives a caret back to, read from app.js itself so this can't drift from it."""
    found = re.search(r'^const TYPED_INPUTS = new Set\(\[([^\]]*)\]\)', (STATIC / 'app.js').read_text(), re.M)
    assert found, "app.js no longer defines TYPED_INPUTS the way this test reads it"
    return set(re.findall(r'"([^"]+)"', found.group(1)))


def typed_boxes_in(source, typed):
    """Each typed box's id as its template writes it: a textarea, or an input of a type app.js gives a caret back to."""
    ids = []
    for tag in re.finditer(r'<(input|textarea)\b[^>]*>', source):
        kind = re.search(r'\stype="([^"]*)"', tag.group(0))
        kind = kind.group(1) if kind else 'text'
        assert '${' not in kind, f"a box whose type comes from data, so this test can't judge it: {tag.group(0)[:100]}"
        if tag.group(1) == 'input' and kind not in typed:
            continue
        box = re.search(r'\sid="([^"]*)"', tag.group(0))
        assert box, f"a typed box with no id that this test can find: give it one, or teach the test: {tag.group(0)[:100]}"
        ids.append(box.group(1))
    return ids


def test_the_list_names_every_typed_box_the_scripts_draw():
    typed = typed_inputs()
    drawn = {box for script in sorted(STATIC.glob('*.js')) for box in typed_boxes_in(script.read_text(), typed)}
    listed = set(typed_boxes.RULES)
    assert sorted(drawn - listed) == [], "typed boxes no list names: add each to tests/typed_boxes.py with how it's told apart"
    assert sorted(listed - drawn) == [], 'listed in tests/typed_boxes.py, but no script draws them now: take them out'


def test_the_finder_sees_a_box_of_each_kind_and_skips_the_rest():
    typed = typed_inputs()
    source = ('<input class="input" id="a" name="a"><textarea id="b"></textarea><input id="c" type="password">'
              '<input id="d" type="checkbox"><input id="e" type="number"><input id="f" type="email">')
    assert typed_boxes_in(source, typed) == ['a', 'b', 'c']


def test_every_way_listed_is_one_the_watch_knows():
    for box, ways in typed_boxes.RULES.items():
        assert ways, box
        for way in ways:
            if way[0] == 'mark':
                assert len(way) > 1 and all(re.fullmatch(r'[a-z][A-Za-z]*', key) for key in way[1:]), (box, way)
            elif way[0] == 'drawing':
                assert len(way) == 2 and way[1], (box, way)
            else:
                assert way == ('dialog',), (box, way)


def test_a_template_id_stands_for_each_id_it_draws():
    matches = re.compile(typed_boxes.pattern('${prefix}-name')).match
    assert matches('source-name') and matches('new-source-name')
    assert not matches('-name') and not matches('source-names') and not matches('source-name-2')
