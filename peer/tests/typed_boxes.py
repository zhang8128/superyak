"""Every typed box the app draws, and how a redraw tells it from another (Tardis's test:every-typed-box-has-an-owner,
all hands e69a8cb2, after fix:care-starter-loses-first-words).

render() gives the caret back only to the box the person last typed in, drawn again for the same drawing, with the same
chain of elements up to #app and the same words (keepTyping in app.js). That keeps a person's keys where they meant them
only if a box for one of several things (a layer, a room, a grant) carries that thing's data on itself or a parent. A
box without such a mark looks the same for each of them, so a redraw could put the next keys in another thing's box.

So each typed box is listed here with the ways it may be told apart, and conftest.py watches every browser context a
test opens: a test that draws a box this list doesn't name, or draws it without what the list says, fails.
test_typed_boxes.py checks that the list names every typed box the static scripts write, so a new box fails CI until
someone says how it's told apart.
"""
import functools
import json
import os
import re

# The ways a box may be told apart. Each box lists one or more, and one of them must hold wherever it's drawn.
# - ('mark', key, ...): each key (as element.dataset names it) is on the box or a parent inside #app.
# - ('dialog',): it's drawn inside a <dialog>, and render() gives no caret back while a dialog is open or drawn.
# - ('drawing', why): what the drawing is for (its route and id, and the room or layer on screen) names what the box is
#   for, and the page draws the box once.
SIGN_IN = ('drawing', "the sign-in page: showLogin draws it with nobody signed in, when render() draws nothing")
RULES = {
    'username': [SIGN_IN],
    'password': [SIGN_IN],
    'invitation-token': [SIGN_IN],
    'new-username': [SIGN_IN],
    'new-name': [SIGN_IN],
    'new-password': [SIGN_IN],
    'space-name': [('dialog',)],
    'layer-title': [('mark', 'layerId')],
    'layer-body': [('mark', 'layerId')],
    'assistant-request': [('mark', 'layerId')],
    'brief-body': [('mark', 'room')],
    'board-outcome': [('mark', 'room', 'key')],
    'board-key': [('mark', 'room')],
    'board-title': [('mark', 'room')],
    'grant-reason': [('mark', 'id')],  # the grant's <li data-id>
    'message-body': [('mark', 'room')],
    'chat-title': [('dialog',)],
    'trust-password': [('mark', 'contact')],  # the contact's <li data-contact>
    'imprint-password': [('dialog',)],
    'peer-card': [('drawing', "Connections' one box for pasting a new card")],
    'pair-code': [('mark', 'fingerprint')],
    'display-name': [('dialog',)],
    'reauth-username': [('dialog',)],
    'reauth-password': [('dialog',)],
    # research.js draws these twice: in a source's settings form, and in the new-source dialog.
    '${prefix}-name': [('mark', 'sourceId'), ('dialog',)],
    '${prefix}-description': [('mark', 'sourceId'), ('dialog',)],
    'home-search': [('drawing', "the home and search pages' own box: the route is the drawing")],
    'space-rename': [('drawing', "a space's page: its route's id names the space")],
}

PROBLEMS = []  # what the watched pages reported since the running test began
SEEN = set()   # every typed box id drawn in this run; TYPED_BOX_SEEN=<file> writes them at the end
_contexts = []


def pattern(listed):
    """A listed id as a regular expression: a template's ${...} part stands for any text."""
    return '^' + '.+'.join(re.escape(part) for part in re.split(r'\$\{[^}]*\}', listed)) + '$'


WATCH = """(() => {
  const rules = %s.map(([pattern, listed, ways]) => [new RegExp(pattern), listed, ways]);
  const told = new Set();
  const tell = (kind, text) => {
    if (told.has(kind + ' ' + text)) return;
    told.add(kind + ' ' + text);
    try { window.__typedBox(kind, text).catch(() => {}); } catch (_) { /* the page is closing */ }
  };
  const mark = (key) => 'data-' + key.replace(/[A-Z]/g, (letter) => '-' + letter.toLowerCase());
  const missing = (box, app, way) => {  // the marks this way needs that the box and its parents don't carry
    const keys = new Set();
    for (let at = box; at && at !== app; at = at.parentElement) for (const key of Object.keys(at.dataset)) if (key !== 'version') keys.add(key);
    return way.slice(1).filter((key) => !keys.has(key));
  };
  const holds = (box, app, way) => way[0] === 'dialog' ? !!box.closest('dialog')
    : way[0] === 'drawing' ? app.querySelectorAll('#' + CSS.escape(box.id)).length === 1 : !missing(box, app, way).length;
  const describe = (box, app, way) => way[0] === 'mark' ? missing(box, app, way).map(mark).join(' and ') + ' on it or a parent'
    : way[0] === 'dialog' ? 'inside a dialog' : 'drawn once on its page';
  const check = () => {
    const app = document.getElementById('app');
    let typed;
    try { typed = TYPED_INPUTS; } catch (_) { return; }  // not the app's page, or app.js hasn't run yet
    if (!app) return;
    const page = (location.hash || '#').split(/[?/]/)[0];  // the route alone: no ids or codes in a failure
    for (const box of app.querySelectorAll('input, textarea')) {
      if ((box.tagName === 'INPUT' && !typed.has(box.type)) || !box.id) continue;  // typingIn's own rule: never a caret
      tell('seen', box.id);
      const rule = rules.find(([pattern]) => pattern.test(box.id));
      if (!rule) tell('problem', `#${box.id} on ${page} isn't listed: say how a redraw tells it apart`);
      else if (!rule[2].some((way) => holds(box, app, way))) {
        tell('problem', `#${box.id} on ${page} is drawn without ${rule[2].map((way) => describe(box, app, way)).join(', or ')} (listed as ${rule[1]})`);
      }
    }
  };
  new MutationObserver(check).observe(document, { childList: true, subtree: true });
})();"""


def watch(context):
    """Watch every page of this context: each typed box it draws is checked against RULES."""
    def heard(_source, kind, text):
        if kind == 'seen':
            SEEN.add(text)
        else:
            PROBLEMS.append(text)
    context.expose_binding('__typedBox', heard)
    rules = [[pattern(listed), listed, [list(way) for way in ways]] for listed, ways in RULES.items()]
    context.add_init_script(script=WATCH % json.dumps(rules))
    _contexts.append(context)


def flush(context):
    """One round trip to each open page, so any report it sent before now has reached PROBLEMS."""
    try:
        pages = list(context.pages)
    except Exception:
        return
    for page in pages:
        try:
            if not page.is_closed():
                page.evaluate('0')
        except Exception:
            pass  # navigating or closing: what it sent before is still delivered in order


def watching(browser_class, context_class):
    """Patch playwright so every context a test makes is watched, and flushed as it closes (conftest.py)."""
    new_context, new_page, close = browser_class.new_context, browser_class.new_page, context_class.close

    @functools.wraps(new_context)
    def made(browser, *args, **kwargs):
        context = new_context(browser, *args, **kwargs)
        watch(context)
        return context

    @functools.wraps(new_page)
    def page_made(browser, *args, **kwargs):
        page = new_page(browser, *args, **kwargs)
        watch(page.context)  # its first document has no watch: every later one does
        return page

    @functools.wraps(close)
    def closed(context, *args, **kwargs):
        flush(context)
        return close(context, *args, **kwargs)

    browser_class.new_context, browser_class.new_page, context_class.close = made, page_made, closed


def start():
    PROBLEMS.clear()
    _contexts.clear()


def take():
    """What the watched pages reported since the test began, after flushing each open one; this clears it."""
    for context in list(_contexts):
        flush(context)
    found = list(PROBLEMS)
    PROBLEMS.clear()
    return found


def check():
    found = take()
    _contexts.clear()
    assert not found, ('A typed box was drawn that a redraw can\'t tell apart; list it in tests/typed_boxes.py with '
                       'how, or mark it:\n' + '\n'.join(found))


def write_seen():
    where = os.environ.get('TYPED_BOX_SEEN')
    if where:
        with open(where, 'w') as out:
            out.write('\n'.join(sorted(SEEN)) + '\n')
