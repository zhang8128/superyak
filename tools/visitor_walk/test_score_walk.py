"""The visitor walk's scorer, tested on synthetic transcripts and a bundle shaped like `ResearchInbox.snapshot()`'s
(checked on 2026-11-23 against a scratch Atlas project: items with kind, title and evidence; relations with subject,
predicate and object; sources with id, title, url and citation)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import score_walk as sw  # noqa: E402

README = """# Superyak

## Try a home in two minutes

## What's inside

| [`atlas/`](atlas/README.md) | Evidence workbench |
"""
ATLAS = """# Atlas

See the [recording guide](docs/research-recording.md).

```sh
make setup-atlas
make atlas-demo
```
"""
DOCS = {"atlas/README.md": ATLAS, "atlas/docs/research-recording.md": "# Recording\n"}
DOI = "10.5555/visitor-test"
TITLE = "Vitamin D and acute respiratory infections: a test title"


def read_doc(path):
    return DOCS.get(path)


class Transcript:
    """Builds stream-json lines: assistant text, tool calls and their results, in order."""

    def __init__(self):
        self.lines, self.n = [], 0
        self.lines.append(json.dumps({"type": "system", "subtype": "init", "claude_code_version": "2.1.330",
                                      "timestamp": "2026-11-23T06:00:00Z"}))

    def text(self, text):
        self.lines.append(json.dumps({"type": "assistant", "timestamp": "2026-11-23T06:01:00Z",
                                      "message": {"content": [{"type": "text", "text": text}]}}))
        return self

    def call(self, name, result="", is_error=False, **inputs):
        self.n += 1
        tid = f"t{self.n}"
        self.lines.append(json.dumps({"type": "assistant", "timestamp": "2026-11-23T06:02:00Z", "message": {
            "content": [{"type": "tool_use", "id": tid, "name": name, "input": inputs}]}}))
        self.lines.append(json.dumps({"type": "user", "timestamp": "2026-11-23T06:03:00Z", "message": {
            "content": [{"type": "tool_result", "tool_use_id": tid, "content": result, "is_error": is_error}]}}))
        return self

    def walk(self, end="2026-11-23T06:30:00Z", error=False):
        self.lines.append(json.dumps({"type": "result", "subtype": "error_during_execution" if error else "success",
                                      "is_error": error, "timestamp": end}))
        return sw.read_transcript(self.lines)


def bundle(title=TITLE, question=sw.FROZEN_QUESTION):
    return {"items": [{"id": "draft-q", "kind": "question", "title": question, "summary": "", "evidence": []},
                      {"id": "draft-c", "kind": "claim", "title": "A finding", "summary": "",
                       "evidence": [{"source_id": "s-1", "locator": "Abstract", "note": ""}]}],
            "relations": [{"id": "r1", "subject": "draft-c", "predicate": "informs", "object": "draft-q"}],
            "sources": [{"id": "s-1", "title": title, "url": f"https://doi.org/{DOI}", "year": 2020,
                         "citation": f"doi:{DOI}"}]}


def resolver(kind, value):
    return TITLE + "." if (kind, value) == ("doi", DOI) else None     # PubMed-style trailing period


def happy():
    return (Transcript()
            .text("I'll follow the README's What's inside section to atlas/README.md for research.")
            .call("Bash", "ok", command="make setup-atlas")
            .call("Bash", "seeded", command="make atlas-demo")
            .call("WebSearch", f"A trial ... https://doi.org/{DOI} ...", query="vitamin D respiratory meta-analysis")
            .call("Bash", "recorded draft-c", command="make atlas ATLAS_PROJECT=/w/p ATLAS_ARGS='record c.json'")
            .call("Bash", f"draft-c ... {DOI}", command="make atlas ATLAS_PROJECT=/w/p ATLAS_ARGS='context vitamin'"))


def test_normalize_is_the_frozen_one():
    assert sw.normalize("Vitamin D – <i>Acute</i> Infections.") == sw.normalize("vitamin d acute infections")
    assert sw.normalize("A:B") == "a b"


def test_a_clean_walk_scores_every_step_unaided_with_an_outside_search_route():
    got = sw.score(happy().walk(), README, read_doc, bundle(), "/w/p", resolver=resolver)
    assert got["steps"] == {s: "unaided" for s in ("S1", "S2", "S3", "S4", "S5", "S6")}
    assert got["named_doc"] == "atlas/README.md"
    assert got["source"] == {"id": "s-1", "identifier": DOI, "route": "outside search"}
    assert got["eligible_to_stop"] and not got["void"] and got["claude_version"] == "2.1.330"


def test_a_title_that_does_not_resolve_to_the_recorded_one_fails_S5_and_S6():
    got = sw.score(happy().walk(), README, read_doc, bundle(title="Something else"), "/w/p", resolver=resolver)
    assert got["steps"]["S5"] == got["steps"]["S6"] == "not done" and got["source"] is None


def test_the_default_project_fails_S4():
    got = sw.score(happy().walk(), README, read_doc, bundle(), "/clone/.engram/atlas/project", resolver=resolver)
    assert got["steps"]["S4"] == "not done"


def test_a_failed_command_before_setup_succeeds_is_a_stall_in_S2():
    t = (Transcript().text("Following What's inside to atlas/README.md.")
         .call("Bash", "Exit code 2", is_error=True, command="make setup-atlas")
         .call("Bash", "ok", command="make setup-atlas")
         .call("Bash", "seeded", command="make atlas-demo"))
    got = sw.score(t.walk(), README, read_doc, {}, "/w/p", resolver=resolver)
    assert got["steps"]["S1"] == "unaided" and got["steps"]["S2"] == "stalled then unaided"
    assert got["steps"]["S3"] == "unaided" and got["stalls"] == [1]


def test_naming_the_doc_only_after_setup_starts_fails_S1():
    t = (Transcript().call("Bash", "ok", command="make setup-atlas")
         .text("I followed What's inside to atlas/README.md."))
    got = sw.score(t.walk(), README, read_doc, {}, "/w/p", resolver=resolver)
    assert got["steps"]["S1"] == "not done" and got["steps"]["S2"] == "not done"


def test_an_identifier_written_first_by_the_walker_is_from_memory():
    t = (Transcript().text("Following What's inside to atlas/README.md.")
         .call("Write", "written", file_path="/w/c.json", content=f"doi:{DOI}")
         .call("Bash", f"draft-c {DOI}", command="make atlas ATLAS_ARGS='context x'"))
    assert sw.route(t.walk(), DOI) == "memory"


def test_superyak_tools_route_when_the_identifier_first_comes_from_a_make_command():
    t = Transcript().call("Bash", f"found {DOI}", command="make atlas ATLAS_ARGS='run'")
    assert sw.route(t.walk(), DOI) == "superyak tools"


def test_reading_the_spec_on_the_web_makes_the_walk_ineligible_to_stop():
    t = happy().call("WebFetch", "the spec", url="https://github.com/zhang8128/superyak/tree/tardis/visitor-walk-spec")
    got = sw.score(t.walk(), README, read_doc, bundle(), "/w/p", resolver=resolver)
    assert got["flags"]["spec_read"] == [6] and not got["eligible_to_stop"]


def test_ssh_use_and_read_only_errors_are_flagged_and_a_read_only_error_is_a_stall():
    t = (Transcript().call("Bash", "", command="git clone git@github.com:zhang8128/superyak.git")
         .call("Bash", "touch: cannot touch '/etc/x': Read-only file system", command="touch /etc/x"))
    walk = t.walk()
    assert sw.flags(walk)["ssh"] == [1] and sw.flags(walk)["read_only"] == [2]
    assert 2 in sw.score(walk, README, read_doc, {}, "/w/p", resolver=resolver)["stalls"]


def test_a_read_outside_the_readme_linked_set_is_a_stall():
    t = (Transcript().text("Following What's inside to atlas/README.md.")
         .call("Read", "contents", file_path="/w/superyak/docs/superpowers/plans/x.md")
         .call("Read", "contents", file_path="/w/superyak/atlas/docs/research-recording.md"))
    assert sw.score(t.walk(), README, read_doc, {}, "/w/p", resolver=resolver)["stalls"] == [1]


def test_the_budget_counts_calls_past_150_and_wall_time_past_an_hour():
    t = Transcript()
    for _ in range(152):
        t.call("Bash", "x", command="ls")
    walk = t.walk(end="2026-11-23T07:00:01Z")
    got = sw.score(walk, README, read_doc, {}, "/w/p", resolver=resolver)
    assert got["budget"] == {"calls": 152, "over_calls": 2, "over_time": True}
    assert not walk.calls[150].in_budget and walk.calls[149].in_budget


def test_an_errored_result_marks_the_walk_void():
    assert happy().walk(error=True).void


def test_S6_needs_the_walker_to_see_the_id_and_identifier_and_the_files_to_confirm():
    t = happy()
    assert sw.score(t.walk(), README, read_doc, bundle(), "/w/p", resolver=resolver,
                    view_files=["no id here"])["steps"]["S6"] == "not done"
    seen_only_by_scorer = (Transcript().text("Following What's inside to atlas/README.md.")
                           .call("Bash", "ok", command="make setup-atlas")
                           .call("Bash", "seeded", command="make atlas-demo"))
    got = sw.score(seen_only_by_scorer.walk(), README, read_doc, bundle(), "/w/p", resolver=resolver,
                   view_files=[f"draft-c {DOI}"])
    assert got["steps"]["S5"] == "unaided" and got["steps"]["S6"] == "not done"


def test_naming_a_document_without_a_readme_section_fails_S1():
    t = (Transcript().text("I'll read atlas/README.md and see.")
         .call("Bash", "ok", command="make setup-atlas"))
    assert sw.score(t.walk(), README, read_doc, {}, "/w/p", resolver=resolver)["steps"]["S1"] == "not done"
