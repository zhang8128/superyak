"""Explicit answer roles remain readable, scoped and independently assessed."""

from copy import deepcopy
import json

from workbench.automation import ResearchInbox
from workbench.render import render_bundle
from workbench.research_evidence import eligible_inputs
from workbench.research_graph_review import GraphReviewLedger, exclusions
from workbench.research_views import export_research
from test_research_graph_views import add_question, add_relation, note, project
from test_research_graph_workers import researcher


ROLES = (
    ("answers", "Proposed answers", "Questions this finding answers", "The measured outcome in the sampled cells.", ""),
    ("partially_answers", "Partial answers", "Questions this finding partly answers", "The observed response at day two.",
     "Whether the response persists at later times."),
    ("raises_question", "Findings that raise this question", "Questions this finding raises", "",
     "Which measurement explains the unexplained mismatch?"),
    ("informs", "Relevant findings", "Related questions", "", ""),
)


def visible_note(project, identifier):
    return note(project, identifier).read_text().split("> [!info]- Technical details")[0]


def section(text, heading):
    return text.split(f"### {heading}\n\n", 1)[1].split("\n\n### ", 1)[0].split("\n\n## ", 1)[0]


def test_mixed_answer_roles_have_separate_reciprocal_sections_and_stable_notes(project):
    snapshot = ResearchInbox(project).snapshot()
    questions = [add_question(snapshot, f"q-answer-{i}", f"Scoped answer question {i}") for i in range(4)]
    claims = [r for r in snapshot["bundle"]["items"] if r["kind"] == "claim"][:4]
    assert len(claims) == 4
    add_relation(snapshot, claims[0]["id"], "informs", questions[0]["id"], "The original relevance link remains recorded.")
    assert export_research(project, snapshot, "before-answers")["status"] == "current"
    path = note(project, claims[0]["id"])
    with path.open("a") as stream:
        stream.write("\nMy comparison of these competing answers.\n")
    for index, (predicate, _, _, scope, remaining) in enumerate(ROLES):
        context = {"answer_scope": scope, "remaining": remaining, "review_verdict": "supported",
                   "review_reason": f"Separate assessment for {predicate}.", "input_digest": "technical-binding"}
        add_relation(snapshot, claims[0]["id"], predicate, questions[index]["id"],
                     f"The shared finding has role {index}.", context=context)
        if index:
            add_relation(snapshot, claims[index]["id"], predicate, questions[0]["id"],
                         f"Another finding has role {index}.", context=context)
    before = deepcopy(snapshot)
    result = export_research(project, snapshot, "after-answers")
    assert result["status"] == "current", result["errors"]
    assert note(project, claims[0]["id"]) == path
    assert "My comparison of these competing answers." in path.read_text()
    claim_text, question_text = visible_note(project, claims[0]["id"]), visible_note(project, questions[0]["id"])
    assert "The original relevance link remains recorded." in section(claim_text, "Related questions")
    assert "The original relevance link remains recorded." in section(question_text, "Relevant findings")
    for index, (predicate, question_heading, claim_heading, scope, remaining) in enumerate(ROLES):
        claim_section, question_section = section(claim_text, claim_heading), section(question_text, question_heading)
        assert f"[[{note(project, questions[index]['id']).stem}|" in claim_section
        assert f"[[{note(project, claims[index]['id']).stem}|" in question_section
        for text in (claim_section, question_section):
            assert f"**{predicate.replace('_', ' ')}**" in text
            assert "Link review: **Supported**" in text
            if scope:
                assert f"Answer scope: {scope}" in text
            if remaining:
                assert f"Remaining uncertainty: {remaining}" in text
            assert "technical-binding" not in text
    assert "#atlas/claim" in claim_text and "#atlas/question" in question_text
    assert len(list((project / "Research/Records").glob("*.md"))) == len(snapshot["bundle"]["items"])
    assert not (project / ".atlas/research/agenda.json").exists()
    assert snapshot == before
    canvas = json.loads((project / "Research/Atlas Map.canvas").read_text())
    for predicate in ("answers", "partially answers", "raises question"):
        assert any(edge["label"] == f"{predicate} · proposed" for edge in canvas["edges"])


def test_rejected_answer_stays_visible_with_latest_reason_and_original_finding(researcher):
    snapshot = researcher.inbox.snapshot()
    claim = next(iter(eligible_inputs(researcher, snapshot).values()))["record"]
    original_claim = deepcopy(claim)
    relation = add_relation(snapshot, claim["id"], "answers", "q-regulation", "A proposed direct response.",
                            context={"answer_scope": "The measured population.", "remaining": "",
                                     "review_verdict": "supported", "review_reason": "Initial scope appeared to match."})
    reason = "The proposed answer does not cover the population named by this question."
    ledger = GraphReviewLedger(researcher.project)
    ledger.store(relation, {"analysis": {"verdict": "unsupported", "reason": reason}}, model="later-reviewer")
    before = deepcopy(snapshot)
    result = export_research(researcher.project, snapshot, "rejected-answer")
    assert result["status"] == "current", result["errors"]
    for identifier, heading in ((claim["id"], "Questions this finding answers"), ("q-regulation", "Proposed answers")):
        text = section(visible_note(researcher.project, identifier), heading)
        assert "Link review: **Unsupported**" in text
        assert reason in text
        assert "Initial scope appeared to match." not in text
        assert "Answer scope: The measured population." in text
    assert exclusions(researcher.project, snapshot) == {relation["id"]}
    assert claim["id"] in eligible_inputs(researcher, snapshot)
    assert claim == original_claim
    assert snapshot == before
    assert len(list((researcher.project / "Research/Records").glob("*.md"))) == len(snapshot["bundle"]["items"])


def test_question_without_answer_keeps_relevance_separate_and_does_not_claim_resolution(project):
    snapshot = ResearchInbox(project).snapshot()
    question = add_question(snapshot, "q-unanswered", "Which measurement is still missing?")
    claim = next(r for r in snapshot["bundle"]["items"] if r["kind"] == "claim")
    add_relation(snapshot, claim["id"], "informs", question["id"], "Useful background without a direct response.")
    assert export_research(project, snapshot, "unanswered")["status"] == "current"
    text = visible_note(project, question["id"])
    assert section(text, "Proposed answers") == "None recorded."
    assert section(text, "Partial answers") == "None recorded."
    assert "Useful background without a direct response." in section(text, "Relevant findings")
    assert "**Question · proposed**" in text
    assert "question is resolved" not in text.lower() and "question is closed" not in text.lower()
    assert question["status"] == "proposed"


def test_browser_shows_human_predicate_and_answer_scope_outside_technical_details(project):
    snapshot = ResearchInbox(project).snapshot()
    claim = next(r for r in snapshot["bundle"]["items"] if r["kind"] == "claim")
    for predicate, _, _, scope, remaining in ROLES:
        add_relation(snapshot, claim["id"], predicate, "q-fate", "A scoped <comparison>.",
                     context={"answer_scope": scope, "remaining": remaining})
    html = render_bundle(snapshot["bundle"])
    for predicate, _, _, scope, remaining in ROLES:
        marker = f'<span class="predicate">{predicate.replace("_", " ")}</span>'
        assert marker in html
        relation_text = html.split(marker, 1)[1].split("<details>", 1)[0]
        if scope:
            assert "Answer scope" in relation_text and scope in relation_text
        if remaining:
            assert "Remaining uncertainty" in relation_text and remaining in relation_text
        assert "A scoped &lt;comparison&gt;." in relation_text
