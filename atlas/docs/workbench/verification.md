# Workbench verification — 2026-09-07

Baseline implementation revision: `ea2de19f6afd4ca29758dde01b63837fbd83955e`. The workbench runs from the repository root and ships a standalone [HTML pilot](../../artifacts/cell-fate-workbench.html). Runtime tests used Python 3.13.5; Python 3.11 grammar was checked for all eleven owned Python source/test files, but a separate Python 3.11 runtime was not tested.

## Software evidence

| Check | Observed result |
|---|---|
| Five workbench test modules | 44 passed in 1.42 seconds, without warnings. Tests use real SQLite databases and filesystem/subprocess inputs. |
| CLI workflow | Init, import, identical repeat, facet searches, show, export, render, and demonstration withdrawal passed using temporary databases. |
| Browser workflow | 32 assertions passed in installed headless Chrome with isolated temporary profiles: navigation, source locators, intersecting facets, empty states, keyboard activation, mobile layout, history, and malicious input retained as text. No app runtime errors or HTTP requests were observed. |
| Pilot provenance | All six source titles, issue years and DOI citations match independently retrieved primary metadata. Eight scoped claims remain source-reported; twenty relations remain proposed. |
| Artifact reproduction | A new SQLite database imported the pilot, exported it, and rendered HTML that matched the shipped artifact byte for byte. |
| Archived notes | All 828 notes imported as proposed questions, with no imported sources or relations. Repeating the import inserted nothing. All five previously identified normalized-title duplicate candidate pairs were recovered. |
| Archive in browser | All 828 records remained available with a two-question preview. Search for `fate` returned 57 records. The desktop workspace began 678 pixels from the top, with no runtime errors or HTTP requests. |
| Original checkout | All 883 fingerprinted source/prompt/note files matched their pre-implementation SHA-256 values. The archived offline test baseline was 30 passed. |

Owned test command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
  tests/workbench/test_store.py tests/workbench/test_legacy.py \
  tests/workbench/test_cli.py tests/workbench/test_render.py \
  tests/workbench/test_pilot.py -q -p no:cacheprovider
```

The implementation work included failing tests before the behavior was added. The large-collection browser check exposed an unbounded introduction: search originally appeared more than 136,000 pixels down the page. A regression test failed with 100 introductory cards, then passed with two preview cards while retaining all 100 list/detail entries. The actual 828-note collection was checked afterward.

Artifact after the final presentation cleanup: 129,955 bytes. SHA-256:

```text
1fd28d4d3bc5e0bf0e4128ed3c519c53d41a26c234d20a34af213bebf16d5ab0
```

## Final presentation cleanup

After the baseline checks above, connected tests received a neutral “Connected test” heading and their actual status badge. Collection and result counts now use correct singular/plural labels, including “approaches” and “1 of 1 record.” The corpus and its statuses did not change.

Focused regression command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
  tests/workbench/test_render.py tests/workbench/test_pilot.py -q -p no:cacheprovider
```

Result: 23 passed in 0.70 seconds. New regressions first reproduced the status-label and count errors (7 failures, 2 already-passing count cases). This is a narrow follow-up; the 44-test result above remains the full-suite baseline.

A focused real Chrome check passed 15 assertions covering connected-test headings and proposed/source-reported/reviewed badges; dynamic counts of 1 of 1 record, 0 of 1 record and 1 of 17 records; and the regenerated pilot's collection counts. No runtime exceptions or HTTP requests were observed. The pilot was regenerated through the CLI using a new temporary database, and its bytes matched a second render of that database's export. These checks supplement the original browser workflow; they do not claim a repeated full browser suite or a human evaluation.

## Scope of the checks

This delivery covers the evidence store, CLI, legacy adapter, offline renderer, pilot corpus, and associated documentation/tests. Concurrent Lighthouse work arrived as commit `de05238` in the same checkout; later unrelated research-recording additions were also present. Both were preserved and excluded from this delivery's review and test scope; their integration is not certified by these results. No archived source or vault file was migrated in place, and Docker/model-dependent tests were not run for this delivery.

The source collection is a selected 2016–2024 demonstration. Software tests and screenshot inspection do not establish scientific correctness, accessibility certification, clinical suitability, or usefulness to researchers. No expert adjudication, human usability study, biological experiment, or funding assessment has been completed. The [evaluation sheet](evaluation.md) records the next human assessment.

## Review outcome

Task reviews and the final review of the owned delivery found no Critical or Important issues. Two minor presentation findings were corrected in `50caa6c`; the scoped follow-up review confirmed both addressed with no new breakage. All owned changes are committed on `feat/research-workbench`. Concurrent work remains outside this review and is preserved in the checkout.
