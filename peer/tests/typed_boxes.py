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

A dialog is different (the first reader on ca211228, finding 1). Dialogs live in their own root, #dialogs, beside
#app (fix:dialog-redraw-loses-typed-words), and keepTyping never looks there. While a render draws a dialog with the
markup that drew the open one, the open one is kept as it is, words and caret with it. When its markup changes, it's
replaced, and drawDialogs carries the person's words and ticks into the control with the same id (or a tick box's name
and value), the same chain inside the dialog and the same drawn default, and focuses that control again: an id, not a
mark, finds it there. So a mark means nothing inside a dialog, and a dialog's box is kept from another thing's keys only
by the dialog being for one thing while it's open: each one says which thing, and names its known gap. The watch reads
both roots.

The watch also reports a typed box the app's own code focuses, on a signed-in page and outside a dialog, that comes
away with no owner (Tardis, all hands feecc21d): an action that opens a box to type in names it with focusForTyping.

The watch also wraps render(): after every draw, the open editor's data-layer-id and the open room's data-room must
be the thing drawingFor() names, the caret gate's own idea of what's drawn (Tardis, all hands 16566adf). It wraps at the
first change to the page after app.js runs, so a document's first draw can go unchecked (the reader's nit 4 on a2451971).

What the watch can't see (that reader's finding 7): contexts from launch_persistent_context or connect_over_cdp, and the
async API (test_typed_boxes.py fails if a test uses them); frames, which have no #app; a page with JavaScript off, where
no app runs either; and a report sent after a test's last flush, which the next test's start drops. A mark passes on
being there: the watch can't tell whether its value names the box's thing (finding 6), so a reviewer checks that.
"""
import functools
import json
import os
import re

# The ways a box may be told apart. Each box lists one or more, and one of them must hold wherever it's drawn.
# - ('mark', key, ...): outside any dialog, each key (as element.dataset names it) is on the box or a parent in #app.
# - ('dialog', why): inside a <dialog> and drawn once; `why` says the one thing that dialog is for while it's open.
# - ('drawing', why): what the drawing is for (its route and id, and the room or layer on screen) names what the box is
#   for, and the page draws the box once.
SIGN_IN = ('drawing', "the sign-in page: showLogin draws it with nobody signed in, when render() draws nothing")
REAUTH = ('dialog', "the sign-in-again dialog: the person signed in now")
RULES = {
    'username': [SIGN_IN],
    'password': [SIGN_IN],
    'invitation-token': [SIGN_IN],
    'new-username': [SIGN_IN],
    'new-name': [SIGN_IN],
    'new-password': [SIGN_IN],
    'space-name': [('dialog', "the new-space dialog: one space not made yet")],
    'layer-title': [('mark', 'layerId')],
    'layer-body': [('mark', 'layerId')],
    'assistant-request': [('mark', 'layerId')],
    'brief-body': [('mark', 'room')],
    'board-outcome': [('mark', 'room', 'key')],
    'board-key': [('mark', 'room')],
    'board-title': [('mark', 'room')],
    'grant-reason': [('mark', 'id')],  # the grant's <li data-id>
    'message-body': [('mark', 'room')],
    'chat-title': [('dialog', "the new-chat dialog (only its 'new' kind draws this box): one chat not made yet")],
    'trust-password': [('mark', 'contact')],  # the contact's <li data-contact>
    'imprint-password': [('dialog', "the imprint dialog: the one request its link's code named. A new #imprint?code= "
                                    "while it's open changes only the code; the dialog still shows that request, and "
                                    "Allow is refused with a 404 before the password is read (the re-check's nit 2)")],
    'peer-card': [('drawing', "Connections' one box for pasting a new card")],
    'pair-code': [('mark', 'fingerprint')],
    'display-name': [('dialog', "the account dialog: the signed-in person's own name")],
    'reauth-username': [REAUTH],
    'reauth-password': [REAUTH],
    # research.js draws these twice: in a source's settings form, and in the new-source dialog.
    '${prefix}-name': [('mark', 'sourceId'), ('dialog', "the new-source dialog: one source not made yet")],
    '${prefix}-description': [('mark', 'sourceId'), ('dialog', "the new-source dialog: one source not made yet")],
    'home-search': [('drawing', "the header's search box, drawn once on every signed-in page: its subject is the query")],
    'space-rename': [('drawing', "a space's page: its route's id names the space")],
}

PROBLEMS = []  # what the watched pages reported since the running test began
SEEN = set()   # every typed box id drawn in this run; TYPED_BOX_SEEN=<file> writes them at the end
_contexts = []
_patched = []  # the classes watching() has patched, so a second call (pytester, a nested run) changes nothing


def pattern(listed):
    """A listed id as a regular expression: a template's ${...} part stands for any text."""
    return '^' + '.+'.join(re.escape(part) for part in re.split(r'\$\{[^}]*\}', listed)) + '$'


def ordered():
    """RULES as the watch reads them: exact ids first, so a template's looser ways never cover an id listed exactly."""
    return sorted(RULES.items(), key=lambda item: '${' in item[0])


# A report names the route and the box's id only, never a value, a code or an id from the data: the words land in a
# public CI log (Tardis, all hands 393c338c).
WATCH = """(() => {
  const rules = %s.map(([pattern, listed, ways]) => [new RegExp(pattern), listed, ways]);
  const told = new Set();
  const tell = (kind, text) => {
    if (told.has(kind + ' ' + text)) return;
    told.add(kind + ' ' + text);
    try { window.__typedBox(kind, text).catch(() => {}); } catch (_) { /* the page is closing */ }
  };
  const mark = (key) => 'data-' + key.replace(/[A-Z]/g, (letter) => '-' + letter.toLowerCase());
  const roots = () => ['app', 'dialogs'].map((id) => document.getElementById(id)).filter(Boolean);
  const missing = (box, app, way) => {  // the marks this way needs that the box and its parents don't carry
    const keys = new Set();
    for (let at = box; at && !roots().includes(at); at = at.parentElement) for (const key of Object.keys(at.dataset)) if (key !== 'version') keys.add(key);
    return way.slice(1).filter((key) => !keys.has(key));
  };
  // Drawn once across both roots: a dialog's box and a page's box with the same id would share every refocus by id.
  const once = (box) => roots().reduce((count, root) => count + root.querySelectorAll('#' + CSS.escape(box.id)).length, 0) === 1;
  const holds = (box, app, way) => way[0] === 'dialog' ? !!box.closest('dialog') && once(box, app)
    : way[0] === 'drawing' ? once(box, app) : !box.closest('dialog') && !missing(box, app, way).length;
  const describe = (box, app, way) => way[0] === 'dialog' ? 'drawn once inside a dialog'
    : way[0] === 'drawing' ? 'drawn once on its page'
    : box.closest('dialog') ? 'a mark outside a dialog (a dialog\\'s redraw ignores marks)'
    : missing(box, app, way).map(mark).join(' and ') + ' on it or a parent';
  // Tardis's condition on naming the drawing by what's drawn (all hands 16566adf): after every render(), the editor and
  // the room on screen are the thing drawingFor() names, so the caret's gate and the view can't drift apart again.
  const drawingMatches = () => {
    let drawn;
    try { drawn = JSON.parse(drawingFor()); } catch (_) { return; }
    const app = document.getElementById('app');
    const editor = app && app.querySelector('section.editor[data-layer-id]');
    if (drawn[0] === 'layers' && editor && editor.dataset.layerId !== drawn[1]) {
      tell('problem', "the editor drawn on #layers isn't the layer drawingFor() names");
    }
    const room = app && app.querySelector('.messages[data-room]');
    if (drawn[0] === 'chats' && room && room.dataset.room !== drawn[1]) {
      tell('problem', "the room drawn on #chats isn't the room drawingFor() names");
    }
  };
  const wrapRender = () => {
    let real;
    try { real = render; } catch (_) { return; }  // not the app's page, or app.js hasn't run yet
    if (typeof real !== 'function' || real.__watched) return;
    const watched = function (...args) { const out = real.apply(this, args); drawingMatches(); return out; };
    watched.__watched = true;
    window.render = watched;  // app.js, dashboard.js and research.js all call render() through the global
  };
  const check = () => {
    wrapRender();
    const app = document.getElementById('app');
    let typed;
    try { typed = TYPED_INPUTS; } catch (_) { return; }  // not the app's page, or app.js hasn't run yet
    if (!app) return;
    const page = (location.hash || '#').split(/[?/]/)[0];  // the route alone: no ids or codes in a failure
    for (const box of roots().flatMap((root) => [...root.querySelectorAll('input, textarea')])) {
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
  // Tardis's second condition on focusForTyping (all hands feecc21d): a typed box the app's own code focuses, on a
  // signed-in page and outside a dialog, must come away with an owner, or a redraw before the person's first key sends
  // it nowhere. keepTyping and focusForTyping give it one; a bare .focus() doesn't. Checked once the focus's own task has
  // run, since both set the owner just after focusing. Playwright's own actions focus from another world, unseen here.
  const realFocus = HTMLElement.prototype.focus;
  HTMLElement.prototype.focus = function (...args) {
    const out = realFocus.apply(this, args);
    const box = this;
    queueMicrotask(() => {
      let typed, owner, signedIn;
      try { typed = TYPED_INPUTS; owner = typedBox; signedIn = !!state.me; } catch (_) { return; }
      const app = document.getElementById('app');
      if (!signedIn || !app || !app.contains(box) || box.closest('dialog') || !box.id || owner === box) return;
      if (!(box.tagName === 'TEXTAREA' || (box.tagName === 'INPUT' && typed.has(box.type)))) return;
      if (document.activeElement !== box) return;
      const page = (location.hash || '#').split(/[?/]/)[0];
      tell('problem', `#${box.id} on ${page} was focused by the app with no owner: open it with focusForTyping`);
    });
    return out;
  };
})();"""


def watch(context):
    """Watch every page of this context: each typed box it draws is checked against RULES."""
    def heard(_source, kind, text):
        if kind == 'seen':
            SEEN.add(text)
        else:
            PROBLEMS.append(text)
    context.expose_binding('__typedBox', heard)
    rules = [[pattern(listed), listed, [list(way) for way in ways]] for listed, ways in ordered()]
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
    """Patch playwright so every context a test makes is watched, and flushed as it closes (conftest.py). Once only."""
    if (browser_class, context_class) in _patched:
        return
    _patched.append((browser_class, context_class))
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
