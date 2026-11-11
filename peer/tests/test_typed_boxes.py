"""tests/typed_boxes.py names every typed box the app's scripts draw, with how a redraw tells it apart (Tardis's
test:every-typed-box-has-an-owner). The watch itself is tested in test_browser.py."""
from pathlib import Path
import re

import pytest

from tests import typed_boxes

STATIC = Path(__file__).resolve().parents[1] / 'superyak_peer' / 'static'
# Each template id in typed_boxes.RULES, as the ids its script draws (research.js: `creating ? 'new-source' : 'source'`).
EXPANDED = {'${prefix}-name': ['source-name', 'new-source-name'],
            '${prefix}-description': ['source-description', 'new-source-description']}
TESTS = Path(__file__).resolve().parent
# The input types a browser knows; any other type="..." is drawn as text (and box.type then says "text").
INPUT_TYPES = {'button', 'checkbox', 'color', 'date', 'datetime-local', 'email', 'file', 'hidden', 'image', 'month',
               'number', 'password', 'radio', 'range', 'reset', 'search', 'submit', 'tel', 'text', 'time', 'url', 'week'}


def typed_inputs():
    """The input types app.js gives a caret back to, read from app.js itself so this can't drift from it."""
    found = re.search(r'^const TYPED_INPUTS = new Set\(\[([^\]]*)\]\)', (STATIC / 'app.js').read_text(), re.M)
    assert found, "app.js no longer defines TYPED_INPUTS the way this test reads it"
    return set(re.findall(r'"([^"]+)"', found.group(1)))


def typed_boxes_in(source, typed):
    """Each typed box's id as its template writes it: a textarea, or an input of a type app.js gives a caret back to.
    What it can't judge, it fails on: a box made by createElement, or a type set inside a ${...}."""
    made = re.search(r'createElement\(\s*[\'"`](input|textarea)', source, re.I)
    assert not made, f"a box made with createElement, which this test can't list: {made.group(0)}"
    ids = []
    for tag in re.finditer(r'<(input|textarea)\b[^>]*>', source, re.I):
        text = tag.group(0)
        assert not re.search(r'\$\{[^}]*\btype\s*=', text, re.I), f"a box whose type is set inside an expression: {text[:100]}"
        kind = re.search(r'\stype\s*=\s*"([^"]*)"', text, re.I)
        kind = kind.group(1).lower() if kind else 'text'
        assert '${' not in kind, f"a box whose type comes from data, so this test can't judge it: {text[:100]}"
        if kind not in INPUT_TYPES:
            kind = 'text'  # as the browser draws it
        if tag.group(1).lower() == 'input' and kind not in typed:
            continue
        box = re.search(r'\sid="([^"]*)"', text)
        assert box, f"a typed box with no id that this test can find: give it one, or teach the test: {text[:100]}"
        ids.append(box.group(1))
    return ids


def test_the_list_names_every_typed_box_the_scripts_draw():
    typed = typed_inputs()
    drawn = {box for script in sorted(STATIC.rglob('*.js')) for box in typed_boxes_in(script.read_text(), typed)}
    listed = set(typed_boxes.RULES)
    assert sorted(drawn - listed) == [], "typed boxes no list names: add each to tests/typed_boxes.py with how it's told apart"
    assert sorted(listed - drawn) == [], 'listed in tests/typed_boxes.py, but no script draws them now: take them out'


def test_the_finder_sees_a_box_of_each_kind_and_skips_the_rest():
    typed = typed_inputs()
    source = ('<input class="input" id="a" name="a"><textarea id="b"></textarea><input id="c" type="password">'
              '<input id="d" type="checkbox"><input id="e" type="number"><input id="f" type="email">'
              '<INPUT id="g"><TextArea id="h"></TextArea><input id="i" type="Text"><input id="j" type="nonsense">'
              '<input id="k" type="Number">')
    assert typed_boxes_in(source, typed) == ['a', 'b', 'c', 'g', 'h', 'i', 'j']


@pytest.mark.parametrize('source', [
    '<input id="a"${n ? \' type="number"\' : ""}>',
    '<input id="a" type="${kind}">',
    'const box = document.createElement("input");',
    "const box = document.createElement('TEXTAREA');",
    '<input class="input" name="a">',
])
def test_the_finder_fails_on_a_box_it_cant_judge(source):
    with pytest.raises(AssertionError):
        typed_boxes_in(source, typed_inputs())


def test_every_way_listed_is_one_the_watch_knows():
    for box, ways in typed_boxes.RULES.items():
        assert ways, box
        for way in ways:
            if way[0] == 'mark':
                assert len(way) > 1 and all(re.fullmatch(r'[a-z][A-Za-z]*', key) for key in way[1:]), (box, way)
            else:
                assert way[0] in ('dialog', 'drawing') and len(way) == 2 and way[1], (box, way)


def test_a_template_id_stands_for_each_id_it_draws_and_exact_ids_come_first():
    matches = re.compile(typed_boxes.pattern('${prefix}-name')).match
    assert matches('source-name') and matches('new-source-name')
    assert not matches('-name') and not matches('source-names') and not matches('source-name-2')
    order = [listed for listed, _ in typed_boxes.ordered()]
    templates = [at for at, listed in enumerate(order) if '${' in listed]
    assert templates and min(templates) > max(at for at, listed in enumerate(order) if '${' not in listed)


def test_no_test_opens_a_browser_the_watch_cant_see():
    """The watch patches Browser.new_context and new_page (Tardis's edge 1, all hands 393c338c)."""
    unseen = re.compile(r'launch_persistent_context|connect_over_cdp|playwright\.async_api|async_playwright')
    mine = {Path(typed_boxes.__file__).resolve(), Path(__file__).resolve()}
    found = [f'{path.name}:{n}' for path in sorted(TESTS.rglob('*.py')) if path.resolve() not in mine
             for n, line in enumerate(path.read_text().splitlines(), 1) if unseen.search(line)]
    assert found == [], 'a browser the typed-box watch never sees: patch it in tests/typed_boxes.py first'


def test_watching_twice_patches_once():
    class Browser:
        def new_context(self):
            return 'context'

        def new_page(self):
            return 'page'

    class Context:
        def close(self):
            return 'closed'

    typed_boxes.watching(Browser, Context)
    once = Browser.new_context, Browser.new_page, Context.close
    typed_boxes.watching(Browser, Context)
    assert (Browser.new_context, Browser.new_page, Context.close) == once
    assert once[0].__wrapped__ is not None


def test_no_script_focuses_a_listed_box_by_id_except_through_focus_for_typing():
    """Tardis's nit 2 on bd25f63a (all hands 18404245): the watch sees only the paths tests reach, so this reads every
    script for a bare .focus() on a typed box named by id (querySelector("#id") or getElementById("id")), outside a
    dialog's boxes. Each must go through focusForTyping or reopenForTyping, which give it an owner. It reads one line
    at a time for a plain #id selector, so it can't see a focus on a variable (keepTyping's own, the dialog trap's), a
    compound selector, a call split over lines or an id built at run time; the watch still covers what tests reach
    (the re-check's nit 3 on ee71f24f). A template id is checked as each id it draws, listed in EXPANDED."""
    typed = set()
    for box, ways in typed_boxes.RULES.items():
        if any(way[0] != 'dialog' for way in ways):
            typed.update(EXPANDED[box] if '${' in box else [box])
    bare = re.compile(r'(?:querySelector|getElementById)\(\s*([\'"`])#?([A-Za-z][\w-]*)\1\s*\)\??\.focus\(')
    found = [f'{script.name}:{n} #{match.group(2)}' for script in sorted(STATIC.rglob('*.js'))
             for n, line in enumerate(script.read_text().splitlines(), 1)
             for match in bare.finditer(line) if match.group(2) in typed]
    assert found == [], 'a typed box focused by id with no owner: open it with focusForTyping (or reopenForTyping)'


def test_the_focus_reader_finds_a_bare_focus_by_id():
    bare = re.compile(r'(?:querySelector|getElementById)\(\s*([\'"`])#?([A-Za-z][\w-]*)\1\s*\)\??\.focus\(')
    line = 'document.querySelector("#board-key")?.focus(); document.getElementById(\'brief-body\').focus();'
    assert [m.group(2) for m in bare.finditer(line)] == ['board-key', 'brief-body']


def test_every_template_id_is_expanded_into_the_ids_it_draws():
    templates = {box for box in typed_boxes.RULES if '${' in box}
    assert set(EXPANDED) == templates, 'a template id with no expansion: list the ids it draws in EXPANDED'
    for template, ids in EXPANDED.items():
        assert ids and all(re.fullmatch(typed_boxes.pattern(template), box) for box in ids), template
