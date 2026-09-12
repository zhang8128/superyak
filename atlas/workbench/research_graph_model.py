"""Fresh, source-bound model calls for questions and question relevance."""

import re
from copy import deepcopy

from .validation import CLAIM_QUESTION_PREDICATES


REVISION = "question-overlap-v3"
STR = {"type": "string"}
LEGACY_PREDICATES = {"claim": "informs", "approach": "addresses", "experiment": "tests"}
OVERLAP_PREDICATES = CLAIM_QUESTION_PREDICATES | {"addresses", "tests"}


def _object(properties):
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


def _array(items, maximum):
    return {"type": "array", "items": items, "maxItems": maximum}


EVIDENCE = _object({"passage_id": STR, "quote": STR})
REVIEW_EVIDENCE = _object({"passage_id": STR})
QUESTION_SCHEMA = _object({
    "useful": {"type": "boolean"},
    **{key: STR for key in ("title", "summary", "scope", "limitations", "motivation", "advance", "duplicate_of")},
    "parents": _array(STR, 3), "views": _array(STR, 8), "premises": _array(STR, 3),
    "evidence": _array(EVIDENCE, 6),
})
QUESTION_REVIEW_SCHEMA = _object({
    "verdict": {"enum": ["useful", "duplicate", "unsupported", "uncertain"]},
    "reason": STR, "duplicate_of": STR, "evidence": _array(REVIEW_EVIDENCE, 6),
    "relations": _array(_object({
        "kind": {"enum": ["parent", "premise"]}, "record_id": STR,
        "verdict": {"enum": ["supported", "unsupported", "uncertain"]},
        "reason": {"type": "string", "maxLength": 600}, "evidence": _array(REVIEW_EVIDENCE, 6),
    }), 6),
})
OVERLAP_SCHEMA = _object({
    "links": _array(_object({"record_id": STR, "predicate": {"enum": sorted(OVERLAP_PREDICATES)},
                            "rationale": STR,
                            "answer_scope": {"type": "string", "description":
                                "Covered answer scope for answers/partially_answers; literal empty string for all other predicates."},
                            "remaining": {"type": "string", "description":
                                "Unresolved issue for partially_answers/raises_question; literal empty string for all other predicates."},
                            "evidence": _array(EVIDENCE, 3)}), 3),
    "reason": STR,
})
OVERLAP_REVIEW_SCHEMA = _object({"decisions": _array(_object({
    "record_id": STR, "predicate": {"enum": sorted(OVERLAP_PREDICATES)},
    "verdict": {"enum": ["supported", "unsupported", "uncertain"]},
    "reason": STR, "evidence": _array(REVIEW_EVIDENCE, 3),
}), 3)})
LEGACY_OVERLAP_LINK = _object({"record_id": STR, "rationale": STR, "evidence": _array(EVIDENCE, 3)})
LEGACY_OVERLAP_DECISION = _object({"record_id": STR, "verdict": STR, "reason": STR,
                                   "evidence": _array(REVIEW_EVIDENCE, 3)})


def _shape(value, schema):
    if not isinstance(value, dict) or set(value) != set(schema["required"]):
        raise ValueError("Unexpected graph proposal fields")


def _text(value, maximum=2000, blank=False):
    if not isinstance(value, str) or len(value) > maximum or (not blank and not value.strip()):
        raise ValueError("Graph proposal requires bounded nonblank text")


def _ids(values, allowed, maximum, *, empty=False):
    if (not isinstance(values, list) or not int(not empty) <= len(values) <= maximum
            or any(not isinstance(v, str) or v not in allowed for v in values)
            or len(set(values)) != len(values)):
        raise ValueError("Graph proposal references missing, duplicate, or ineligible inputs")


def _citations(entries, packet, *, quotes, required_records=(), allow_empty=False):
    if not isinstance(entries, list) or not int(not allow_empty) <= len(entries) <= 6:
        raise ValueError("Graph proposal needs located source evidence")
    passages = {p["id"]: p for p in packet["document"]["passages"]}
    owners = {pid: source["record_id"] for source in packet["sources"] for pid in source["passage_ids"]}
    cited = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ({"passage_id", "quote"} if quotes else {"passage_id"}):
            raise ValueError("Invalid graph evidence fields")
        identifier = entry["passage_id"]
        if not isinstance(identifier, str) or identifier not in passages:
            raise ValueError("Graph evidence must reference supplied passages")
        if quotes:
            quote = entry["quote"]
            if (not isinstance(quote, str) or not 4 <= len(quote.split()) <= 25
                    or quote not in passages[identifier]["text"]):
                raise ValueError("Graph evidence must quote 4–25 contiguous supplied words")
        cited.add(owners[identifier])
    if set(required_records) - cited:
        raise ValueError("Every proposed premise or link requires its own source evidence")
    return cited


def title_key(title):
    return " ".join(re.findall(r"[^\W_]+", title.casefold()))


def validate_question(candidate, packet, questions, views):
    _shape(candidate, QUESTION_SCHEMA)
    if type(candidate["useful"]) is not bool:
        raise ValueError("Question usefulness must be boolean")
    _text(candidate["duplicate_of"], blank=True)
    ids = {q["id"] for q in questions}
    if candidate["duplicate_of"] and candidate["duplicate_of"] not in ids:
        raise ValueError("Duplicate question ID was not supplied")
    if not candidate["useful"] or candidate["duplicate_of"]:
        return False
    for key in ("title", "summary", "scope", "limitations", "motivation", "advance"):
        _text(candidate[key], 240 if key == "title" else 2000)
    _ids(candidate["parents"], {q["id"] for q in questions if q.get("eligible_parent", True)}, 3)
    _ids(candidate["premises"], {r["id"] for r in packet["records"]}, 3)
    _ids(candidate["views"], set(views), 8)
    _citations(candidate["evidence"], packet, quotes=True, required_records=candidate["premises"])
    return not any(title_key(q["title"]) == title_key(candidate["title"]) for q in questions)


def validate_question_review(result, packet, candidate, questions, *, legacy=False):
    decision = result.get("analysis")
    schema = QUESTION_REVIEW_SCHEMA
    if legacy and isinstance(decision, dict) and "relations" not in decision:
        schema = _object({key: value for key, value in schema["properties"].items() if key != "relations"})
    _shape(decision, schema)
    if decision["verdict"] not in {"useful", "duplicate", "unsupported", "uncertain"}:
        raise ValueError("Invalid question review verdict")
    _text(decision["reason"])
    _text(decision["duplicate_of"], blank=True)
    if decision["verdict"] == "duplicate":
        if decision["duplicate_of"] not in {q["id"] for q in questions}:
            raise ValueError("Duplicate review needs an existing question ID")
    elif decision["duplicate_of"]:
        raise ValueError("Only a duplicate decision may name a duplicate question")
    _citations(decision["evidence"], packet, quotes=False,
               required_records=candidate["premises"] if decision["verdict"] == "useful" else (),
               allow_empty=decision["verdict"] in {"uncertain", "duplicate"})
    if "relations" not in decision:
        return decision
    relations = decision["relations"]
    expected = {("parent", identifier) for identifier in candidate["parents"]} | {
        ("premise", identifier) for identifier in candidate["premises"]}
    if not isinstance(relations, list) or len(relations) > 6:
        raise ValueError("Question review requires a bounded relation decisions list")
    seen = set()
    for relation in relations:
        _shape(relation, QUESTION_REVIEW_SCHEMA["properties"]["relations"]["items"])
        kind, identifier, verdict = relation["kind"], relation["record_id"], relation["verdict"]
        if not isinstance(kind, str) or not isinstance(identifier, str) or (kind, identifier) not in expected or (kind, identifier) in seen:
            raise ValueError("Question review must assess each proposed relation exactly once")
        if not isinstance(verdict, str) or verdict not in {"supported", "unsupported", "uncertain"}:
            raise ValueError("Invalid question relation verdict")
        _text(relation["reason"], 600)
        cited = _citations(relation["evidence"], packet, quotes=False,
                           required_records=[identifier] if kind == "premise" and verdict != "uncertain" else (),
                           allow_empty=verdict == "uncertain")
        if kind == "parent" and verdict != "uncertain" and not cited.intersection(candidate["premises"]):
            raise ValueError("A parent relation decision must cite a motivating premise")
        seen.add((kind, identifier))
    if (decision["verdict"] == "useful" or relations) and seen != expected:
        raise ValueError("Every parent and premise requires its own relation decision")
    return decision


def normalize_overlap_candidate(candidate, record_kinds=None):
    """Make an explicit request copy; original legacy job fields remain untouched."""
    _shape(candidate, OVERLAP_SCHEMA)
    if record_kinds is not None and not isinstance(record_kinds, dict):
        raise ValueError("Overlap record kinds must map record IDs to kinds")
    normalized = deepcopy(candidate)
    if not isinstance(normalized["links"], list):
        raise ValueError("Overlap links must be a list")
    for link in normalized["links"]:
        if isinstance(link, dict) and "predicate" not in link:
            _shape(link, LEGACY_OVERLAP_LINK)
            kind = (record_kinds or {}).get(link["record_id"], "claim")
            if not isinstance(kind, str) or kind not in LEGACY_PREDICATES:
                raise ValueError("Unsupported overlap record kind")
            link.update(predicate=LEGACY_PREDICATES[kind], answer_scope="", remaining="")
        else:
            _shape(link, OVERLAP_SCHEMA["properties"]["links"]["items"])
    return normalized


def validate_overlap(candidate, packet, *, legacy=False, record_kinds=None):
    _shape(candidate, OVERLAP_SCHEMA)
    _text(candidate["reason"])
    links = candidate["links"]
    if not isinstance(links, list) or len(links) > 3:
        raise ValueError("An overlap turn can propose at most three links")
    records, seen = {r["id"] for r in packet["records"]}, set()
    for link in links:
        _shape(link, LEGACY_OVERLAP_LINK if legacy and isinstance(link, dict) and "predicate" not in link else
               OVERLAP_SCHEMA["properties"]["links"]["items"])
        identifier = link["record_id"]
        if not isinstance(identifier, str) or identifier not in records or identifier in seen:
            raise ValueError("Overlap links must identify distinct supplied records")
        seen.add(identifier)
        _text(link["rationale"])
        _citations(link["evidence"], packet, quotes=True, required_records=[identifier])
    normalized = normalize_overlap_candidate(candidate, record_kinds)
    for link in normalized["links"]:
        predicate = link["predicate"]
        if not isinstance(predicate, str) or predicate not in OVERLAP_PREDICATES:
            raise ValueError("Invalid overlap predicate")
        if record_kinds is not None:
            kind = record_kinds.get(link["record_id"])
            allowed = CLAIM_QUESTION_PREDICATES if kind == "claim" else {LEGACY_PREDICATES.get(kind)} if isinstance(kind, str) else set()
            if predicate not in allowed:
                raise ValueError("Overlap predicate is not permitted for the supplied record kind")
        scope, remaining = link["answer_scope"], link["remaining"]
        _text(scope, blank=predicate not in {"answers", "partially_answers"})
        _text(remaining, blank=predicate not in {"partially_answers", "raises_question"})
        if ((predicate == "answers" and remaining != "") or (predicate == "raises_question" and scope != "")
                or (predicate in {"informs", "addresses", "tests"} and (scope != "" or remaining != ""))):
            raise ValueError("Overlap answer scope and remaining issue do not match the predicate")
    return bool(links)


def validate_overlap_review(result, packet, candidate, *, legacy=False, record_kinds=None):
    validate_overlap(candidate, packet, legacy=legacy, record_kinds=record_kinds)
    normalized = normalize_overlap_candidate(candidate, record_kinds)
    analysis = result.get("analysis")
    _shape(analysis, OVERLAP_REVIEW_SCHEMA)
    decisions = analysis["decisions"]
    proposed = {link["record_id"]: link["predicate"] for link in normalized["links"]}
    if not isinstance(decisions, list) or len(decisions) != len(proposed):
        raise ValueError("Every overlap link requires a separate review decision")
    seen, reviewed = set(), []
    for decision in decisions:
        old = legacy and isinstance(decision, dict) and "predicate" not in decision
        _shape(decision, LEGACY_OVERLAP_DECISION if old else OVERLAP_REVIEW_SCHEMA["properties"]["decisions"]["items"])
        identifier, verdict = decision["record_id"], decision["verdict"]
        if not isinstance(identifier, str) or identifier not in proposed or identifier in seen:
            raise ValueError("Review must assess each proposed link exactly once")
        predicate = decision.get("predicate", proposed[identifier])
        if predicate != proposed[identifier] or (old and predicate not in LEGACY_PREDICATES.values()):
            raise ValueError("Overlap review must assess the exact proposed predicate")
        if not isinstance(verdict, str) or verdict not in {"supported", "unsupported", "uncertain"}:
            raise ValueError("Invalid overlap review verdict")
        seen.add(identifier)
        _text(decision["reason"])
        _citations(decision["evidence"], packet, quotes=False,
                   required_records=[identifier] if verdict == "supported" else (),
                   allow_empty=verdict == "uncertain")
        reviewed.append(deepcopy(decision) | {"predicate": predicate})
    return reviewed


def propose_question(model, anchor, packet, questions, views):
    data = model._comparison_data(anchor, packet)
    data["candidate"].update(existing_questions=questions, allowed_views=views)
    result = model._chat(
        "You are the question worker. Inspect the original source excerpts and propose at most ONE "
        "specific investigable question motivated by a real gap, tension, or missing measurement. "
        "It must advance the supplied parent questions rather than paraphrase them. Give its scope, "
        "limitations, motivation, and an observation that would advance its answer. Unresolved means "
        "unresolved by these supplied excerpts, not unknown to all science. Do not treat a question "
        "or a generated interpretation as independent experimental evidence. Compare existing and "
        "queued questions by meaning, system and requested measurement. Return useful=false if no "
        "distinct grounded question follows; name duplicate_of only for a supplied duplicate ID. "
        "Choose 1–3 supplied eligible_parent IDs only when this is a true subproblem of each. "
        "Choose 1–3 premise record IDs that specifically raise this unresolved question; generic "
        "background relevance is insufficient. Cite 4–25 contiguous words exactly from each premise's "
        "source passages. Choose explicit allowed_views. No invented IDs or asserted answers. "
        "For a useful question leave duplicate_of empty; for no useful question use empty lists "
        "and strings except motivation/limitations as appropriate.", data, QUESTION_SCHEMA)
    validate_question(result["analysis"], packet, questions, views)
    return result


def review_question(model, anchor, packet, candidate, questions, views, *, premise_predicate="raises_question"):
    if premise_predicate not in {"informs", "raises_question"}:
        raise ValueError("Question review premise predicate must be informs or raises_question")
    criterion = (
        "Review whether each premise specifically raises this question by motivating its unresolved "
        "gap, tension or missing measurement in the original source excerpt. Generic background "
        "relevance and shared terms are insufficient. "
        if premise_predicate == "raises_question" else
        "The saved premise relations are informs. Review whether each premise provides relevant "
        "scoped information for this question using its original source excerpt. Useful background "
        "need not itself raise a new unresolved gap, tension or missing measurement. Shared terms "
        "alone still do not establish relevance. ")
    data = model._comparison_data(anchor, packet, candidate)
    expected = [{"kind": kind, "record_id": identifier} for kind, field in
                (("parent", "parents"), ("premise", "premises")) for identifier in candidate[field]]
    data["candidate"].update(existing_questions=questions, allowed_views=views, required_relations=expected,
                             premise_predicate=premise_predicate)
    schema = deepcopy(QUESTION_REVIEW_SCHEMA)
    schema["properties"]["relations"]["maxItems"] = len(expected)
    schema["properties"]["relations"]["items"]["properties"]["record_id"] = {
        "type": "string", "enum": sorted({entry["record_id"] for entry in expected})}
    result = model._chat(
        "You are the question reviewer in a fresh call. Assess the proposed question's grounded "
        "motivation, specific scope, useful measurement, every parent relation, and distinctness "
        "from supplied existing/queued questions. " + criterion +
        "You are judging a useful research question, not proving its answer true or declaring "
        "global scientific novelty. Return useful only if all those conditions hold. For a "
        "paraphrase return duplicate and duplicate_of the existing ID. Otherwise use unsupported "
        "or uncertain and explain precisely. A useful verdict requires evidence passage_ids from "
        "every premise. Give a SEPARATE relation decision for every supplied required_relations "
        "entry, identified by its exact kind and record_id. Each parent decision explains why "
        "this is a true subproblem of that particular parent and cites source evidence for its "
        "motivation. Each premise decision explains why that particular original finding satisfies "
        "the supplied premise_predicate criterion for this question and cites that premise's own "
        "source passages. Shared vocabulary is not "
        "enough. Relation verdicts are supported, unsupported, or uncertain, each with its own "
        "reason and evidence passage_ids. Write each relation reason as a concise paraphrase "
        "in one or two sentences, at most 600 characters; cite passage IDs and do not repeat "
        "or quote the source paragraph. Do not replace these with one generic explanation. "
        "A useful verdict must assess ALL required relations exactly once; capture is held if "
        "any essential relation is unsupported or uncertain. A non-useful overall decision may "
        "return relations=[]; otherwise assess all required relations. Return only verdict, "
        "reason, duplicate_of (empty unless duplicate), evidence, relations.",
        data, schema)
    validate_question_review(result, packet, candidate, questions)
    return result


def _overlap_generation_schema():
    """Constrain each complete link even when the serializer emits scope first."""
    schema = deepcopy(OVERLAP_SCHEMA)
    link_schema = schema["properties"]["links"]["items"]
    branches = []
    for predicates, answer, remaining in (
            (["informs", "addresses", "tests"], {"const": ""}, {"const": ""}),
            (["answers"], {"minLength": 1}, {"const": ""}),
            (["partially_answers"], {"minLength": 1}, {"minLength": 1}),
            (["raises_question"], {"const": ""}, {"minLength": 1})):
        branch = deepcopy(link_schema)
        branch["properties"]["predicate"] = {"enum": predicates}
        branch["properties"]["answer_scope"].update(answer)
        branch["properties"]["remaining"].update(remaining)
        branches.append(branch)
    schema["properties"]["links"]["items"] = {"anyOf": branches}
    return schema


def overlap(model, question, packet, *, record_kinds=None):
    data = model._comparison_data(question, packet)
    data["candidate"]["record_kinds"] = record_kinds or {r["id"]: "claim" for r in packet["records"]}
    result = model._chat(
        "You are the overlap worker. Classify the precise relationship between each supplied "
        "record and the target question using only its original source excerpts. Propose at most "
        "three links, one per record. Choose the predicate FIRST, then fill its permitted answer "
        "fields. A claim answers only when it directly responds to the FULL "
        "question within the question's stated scope: answer_scope must name that covered scope, "
        "and remaining must be empty. Do not redefine a broad question as a narrow one to claim "
        "a full answer. Use partially_answers for a direct response to a bounded aspect; give both "
        "answer_scope and the unresolved remaining uncertainty. Use raises_question when the "
        "finding motivates a specific gap, tension or missing measurement: answer_scope is empty "
        "and remaining names that open issue. Mere relevant background uses informs, with both "
        "answer fields empty. The supplied record_kinds map is authoritative: approaches use "
        "addresses and experiments use tests. For informs, addresses and tests, both answer_scope "
        "and remaining MUST be literal empty JSON strings. Example field fragment: "
        '{"predicate":"informs","answer_scope":"","remaining":""}. '
        "Describe the background or system scope in rationale. For every link give "
        "a specific rationale and exact 4–25 word quotations from that record's own passages. "
        "Preserve system, population, intervention and measurement scope. Shared vocabulary is "
        "not enough. Add no new finding, invented answer or claim of scientific validation. "
        "These are proposed links and do not close questions. Return links=[] with a reason when "
        "none is justified. Each link has record_id, predicate, rationale, answer_scope, remaining, "
        "evidence; use only supplied record and passage IDs.", data, _overlap_generation_schema())
    validate_overlap(result["analysis"], packet, record_kinds=record_kinds)
    return result


def review_overlap(model, question, packet, candidate):
    validate_overlap(candidate, packet, legacy=True)
    normalized = normalize_overlap_candidate(candidate)
    proposed_ids = [link["record_id"] for link in normalized["links"]]
    data = model._comparison_data(question, packet, normalized)
    data["candidate"]["review_only_record_ids"] = proposed_ids
    schema = deepcopy(OVERLAP_REVIEW_SCHEMA)
    decisions = schema["properties"]["decisions"]
    decisions.update(minItems=len(proposed_ids), maxItems=len(proposed_ids))
    decisions["items"]["properties"]["record_id"] = {"type": "string", "enum": proposed_ids}
    result = model._chat(
        "You are the overlap reviewer in a fresh call. Give a SEPARATE decision for EVERY proposed "
        "record-to-question link. Assess its exact predicate, rationale, answer_scope and remaining "
        "issue against the original source excerpts and the target question's stated scope; "
        "neither the candidate nor existing graph links are evidence. Return supported only if "
        "the specific relationship is justified within the stated limitations. answers requires "
        "a direct response covering the FULL scoped question and an empty remaining field; "
        "a narrow result cannot answer a broader question by redefining its scope. partially_answers "
        "requires a direct bounded answer_scope and an explicit unresolved remaining issue. "
        "The absence of a full answer is insufficient to establish a partial answer. To support "
        "partially_answers, your reason must identify the concrete part of the target question "
        "that the finding actually answers and the source-supported answer to that part. General "
        "capabilities or topic relevance without an assessed result are background (informs). "
        "For example, describing tools that could evaluate a system does not partially answer "
        "how accurately it predicts, how well it performs, or what outcome it produces when no "
        "such prediction, performance or outcome was assessed. A reason that only lists useful "
        "capabilities while acknowledging the requested result was not assessed does not support "
        "a partial answer. Reject the proposed partially_answers link in that case, retaining "
        "predicate=partially_answers in your decision; do not silently relabel it informs. "
        "raises_question requires a specific unresolved gap in remaining and no claimed answer_scope. "
        "informs is relevant background; addresses is a method and tests is an experiment. Those "
        "generic relations have empty answer fields. Reject an overstrong answer; do not silently "
        "downgrade or repair it into another predicate. An accepted proposed link does not establish "
        "scientific truth or close the question. "
        "Reject superficial keyword matches, false transfer across systems, and unsupported "
        "causality. Decisions contain record_id, predicate (copy the EXACT proposed predicate even "
        "when rejecting it), verdict (supported/unsupported/uncertain), reason, "
        "and evidence passage_ids. Supported decisions must cite that record's own source. "
        "Review ONLY proposal.links: return exactly one decision for each review_only_record_ids "
        "entry. Other input_claims provide context and MUST NOT receive a decision. "
        "Do not repair candidates or invent records.", data, schema)
    validate_overlap_review(result, packet, normalized)
    return result
