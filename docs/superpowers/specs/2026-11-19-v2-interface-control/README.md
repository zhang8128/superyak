# v2: the interface control. How many frozen cases test names and values only

Tardis, 2026-11-19 (UTC). Advisory; Serenity's design question in all hands 72d039eb, this design in 7b42c066,
agreed in 9ba6b55d. Written and committed before any frozen case is run on an interface. No model turn is run.

## The question

The second pilot's report (`v2` ef87f6cc) sorts each frozen case that does not pass on the parent by the first line
of its failure there. 295 of the first pilot's 304, and 43 of pool P's 59, first fail on an import, an attribute, a
call's arguments or a collection error. What such a case tests once that barrier is gone, the report says, "is not
known from this". This control removes the barrier with no model: it gives the parent the names the commit adds,
with bodies that do nothing, and runs the frozen cases there.

- A case that **passes on the parent plus the interface** tests names and values only. It is set aside, as a case
  passing on the parent is.
- The rest are **behaviour candidates**. Of those, a case whose test function holds a string the commit adds is
  **string-bound**, and is read apart. No string the commit adds is given as a value.
- Then every row already run, in both pilots, is counted on the behaviour candidates, from `cases.json`'s
  `rows_first_pilot` and `rows_second_pilot`. It is a look, and there is no rule: whether the line's rows pass more
  of them than nothing's in pool P, and the first pilot's conditions on them at its twelve.

The answer is still agreement with one reference: its orderings, shapes and error types. It asks whether a plan helps
beyond its names, not whether the line helps a room. No room gives a turn the interface.

## Inputs, pinned

- `docs/reports/2026-11-19-v2-a-line-that-says-a-plan-may-exist-pilot/cases.json` at `v2` 95f36a45, sha256
  07e9d27b6a685761580da09016cc007fe75973d6d291a0d9f9b3ea8e73d81263: 24 items, with each item's commit, first parent,
  test files, frozen cases and the cases that pass on the parent.
- The superyak repository's own history for each commit and parent.

## The harness, and its two checks before any interface

Each run is one item at one tree:
- the tree is the parent, with each of the item's test files (`tests`) checked out from the commit;
- the command is `python -m pytest -q -p no:cacheprovider --tb=short -rfE --junitxml=<file> <tests>`, from `peer/`,
  with the peer's virtual environment of Tardis's main checkout (its Python and pytest versions are printed with the
  output);
- the environment is `PATH`, a fresh `HOME` and `TMPDIR`, `PYTHONPATH=peer` and `PYTHONDONTWRITEBYTECODE=1`, as the
  pilots' jail sets them;
- a case is `classname::name` of the JUnit report, the pilots' form, and it passes when its JUnit status is passed.

Two checks are run first, at every item, before any interface is made:

- **A.** At the parent, the frozen cases that pass are exactly `pass_on_the_parent`.
- **B.** At the commit itself (its source with the same tests), every frozen case passes.

The harness may be mended until A and B hold, since neither involves an interface. An item where they still do not
hold, on this machine and not in the pilots' jail, is named and left out, never fitted.

## The interface

For each Python file under `peer/superyak_peer` that the commit changes, the parent's and the commit's versions are
both parsed. A **name the commit adds** is any of these, absent at the parent:
- a module-level `def`, `async def` or `class`;
- a module-level name assigned by `=` or by an annotation with a value;
- a method of a class that both versions hold.

A name is **given** when it appears as a whole word (a maximal run of ASCII letters, digits and underscores) in one
of the item's test files at the commit, or in a given name's own decorators, bases, defaults or value. That rule is
applied until nothing more is added.

What is given, at the parent's file:
- **a function or method:** the commit's decorators, name and parameters with their defaults, with no annotations.
  Its body is `raise NotImplementedError("interface control")`;
- **a class:** its decorators and bases, its class-level assignments by the value rule below, and its methods as
  above;
- **a module-level value:** the commit's own statement when it holds no string constant. This is generous, since a
  value is not a name: a case that only checks such a constant's value passes on the interface and is set aside. A
  statement that holds a string constant (a message, a template, a pattern, a set of keys) is given as
  `NAME = NotImplemented`, the name alone. For a class-level annotation the commit's annotation is kept;
- **an import the commit's file adds:** the statement itself, when a given part needs it.

New module-level parts go at the end of the parent's file, in the commit's order. New methods go at the end of their
class. Nothing the parent already holds is changed. That means **a changed signature of an existing function is not
given**: those cases stay behind the barrier and are counted apart, by the bin's words "unexpected keyword", "missing
N required" and "takes N positional". Files that aren't Python are not given.

Strings the interface does carry: a parameter's default and a decorator's arguments (a route's path, say), copied
as the commit writes them, since they are a signature's own words. A test that holds one of these strings still
counts as string-bound below.

Before any frozen case runs on them, each item's interface is made as a patch, applied to the parent and imported
(`python -c "import superyak_peer.<module>"` for every changed module). The extraction may be mended until every
import succeeds. Then the 24 patches and their sha256 are committed.

## The run, once

At each item, the frozen cases are run on the parent plus its committed interface.

- **C.** Every case in `pass_on_the_parent` still passes. Where one does not, the interface changed what the parent
  did. The item is named and left out, and not mended.
- For each kept item: the cases passing there, outside `pass_on_the_parent`, are **names and values only**. The rest
  of the cases outside `pass_on_the_parent` are the **behaviour candidates**.

**String-bound.** A behaviour candidate is string-bound when its test function's own body holds a string constant,
other than the function's docstring, that:
- is at least 4 characters long;
- appears on a line the commit adds under `peer/superyak_peer`;
- appears in no file under `peer/superyak_peer` at the parent.

Helpers and fixtures are not read, so the string-bound count is a lower bound (Serenity, 9ba6b55d).

## What is printed

- **By item:**
  - checks A, B and C;
  - the frozen cases and those passing on the parent;
  - names and values only;
  - the behaviour candidates, string-bound and not;
  - the cases left behind a changed signature;
  - the names given.
- **By row of both pilots, summed by pool and row kind (second pilot) and by condition (first pilot)**, beside the
  report's own sums over the cases outside `pass_on_the_parent`:
  - the cases passed among the behaviour candidates;
  - the same among those that are not string-bound.

Every count comes from the run's files by script, and none is typed.

## Added before the run

Serenity read the reading and three patches and said go, with two additions to what is printed (all hands
18876231). Neither changes an interface or the run:

1. **How each behaviour candidate fails on the parent plus its interface**, by the first line of its failure there:
   - **a given body:** the line holds "NotImplementedError: interface control";
   - **still a barrier:** the second pilot's report's first-line rule. The case was not collected, or the line holds
     any of `ImportError`, `ModuleNotFoundError`, `AttributeError`, `NameError`, "has no attribute", "cannot import
     name", "unexpected keyword", "got an unexpected", "missing N required", "takes N positional" or "fixture '...'
     not found";
   - **an assertion:** the line begins `AssertionError` or `assert `;
   - **other.**

   A barrier the interface does not remove, such as an attribute set in `__init__`, a new key, or a name the tests
   reach without writing it, stays among the candidates. So the candidates are an upper bound, and this says by how
   much.
2. **The rows' passes by item**, as well as summed. A sum can be one item.

Where check C leaves an item out, the cases that stopped passing are printed.

**A memory cap, added by Tardis for this machine.** Serenity's census ran a Mac out of memory on a test that feeds an
endless device to a read with no bound (all hands 5de57809). Two of these items' tests read `/dev/zero`, under the
test's own 2 GiB cap, which holds on Linux. Tardis has 10 GB and runs other sessions. So every pytest run is started
under `prlimit --as=3221225472` (3 GiB of address space, which its children inherit), two items at a time. A and B
are run again under the cap. They must give exactly the same passes as before, or the run waits.
