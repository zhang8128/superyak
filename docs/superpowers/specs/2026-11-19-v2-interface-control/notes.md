# The interface control: notes after the run

Tardis, 2026-11-19. The run was made once, at 60756065's script and interfaces: `run/`, `run-output.txt`. The tables
are `read.md` and `read.json`. This file holds what was found after the run. Nothing in it changed the run.

## Two collection failures the value rule made

At 2ebc78e1 (89 cases) and 3f349e89 (95), the item's test module was not collected on parent plus interface. The
error, reproduced after the run by `pytest --collect-only` on the same tree (`why_collect.py`), is the same at both:

    E   TypeError: 'NotImplementedType' object is not iterable

Each test module iterates, at collection, a module-level value the commit adds:
- `@pytest.mark.parametrize('method', sorted(BODYLESS_METHODS))` at 2ebc78e1's `peer/tests/test_public_body_cap.py:81`;
- `@pytest.mark.parametrize('key', sorted(CROSSING_KEYS))` at 3f349e89's `peer/tests/test_crossing_wire.py:72`. The README's value rule gives a value that holds strings as `NotImplemented`, so
those 184 cases stay behind the strings the control withheld. They count under "still a barrier".

The 266 cases still behind a barrier are:
- 184 behind those withheld values;
- 80 behind a changed signature of an existing function: 59 at 3879e609, 16 at 426ad7fb, 4 at c9ceb15b, 1 at
  027834bf;
- 2 at d20c739b, behind an attribute set in `__init__`.

## A view chosen after the counts were read

`after_view.py` (output `after-view.txt`) counts the rows on the 135 behaviour candidates that got past the barrier:
those that reached a given body, an assertion or another failure. It also counts them on the ones of those that are
not string-bound. The README did not name this view. It is given because the candidates in part A and pool N are
mostly still behind a barrier, as Serenity's first addition was there to show.
