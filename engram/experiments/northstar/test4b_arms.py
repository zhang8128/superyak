"""North-star test 4, stage B, the arms' half: what each arm's turn is given, and how its reply is read.

From docs/superpowers/specs/2026-11-23-north-star-test-4-stage-b-design.md, drafts 2 and later
(`tardis/test4-stage-b` 1371523b). It was written and hashed before any stage B world rule existed, so no world can
have shaped the prompts, and no world's rules or code were read.

- **R0** gives a turn the task and the open patches only.
- **R1** adds the record as it is: each earlier turn's patch description, its diff, its verdict and its summary. It
  holds no content key, so noticing a repeat is the turn's own work.
- **R2** adds stage A's adaptive-by-content policy's choice and flags, computed from the content keys the harness
  supplies, and shown as advice the turn may ignore.

A turn replies with one JSON object, `{"choice": int, "summary": str, "flags": [...]}`. `read_reply` refuses anything
else, which makes that turn a stall.
"""
from __future__ import annotations

import json
import re

from experiments.northstar.test4_policies import adaptive_content

ARMS = ("R0", "R1", "R2")
FLAG_KEYS = {"repeat", "cycle", "contradiction", "premise"}

INTRO = ("You are one turn of a team working on a small code task. You remember nothing of earlier turns{memory}. "
         "Exactly one of the open patches below makes the task's frozen test pass. Choose one patch to try now.")
REPLY = ("Reply with only one JSON object and nothing else: "
         '{"choice": <the number of the patch you choose>, "summary": "<one sentence on what you tried and why>", '
         '"flags": [<zero or more flags>]}. '
         'A flag is one of: {"repeat": "<the number of an open patch you believe was already tried under another '
         'description>"}, {"cycle": "<a short note>"}, {"contradiction": <the turn number of a record entry whose '
         'summary disagrees with its verdict>}, {"premise": <the turn number of an entry that changed what earlier '
         'verdicts mean>}.')


def _patches(patches):
    return "\n\n".join(f"Patch {i}: {p['description']}\n```diff\n{p['diff']}\n```" for i, p in enumerate(patches))


def _record(record):
    if not record:
        return "The record is empty: no earlier turn has tried anything."
    lines = []
    for e in record:
        verdict = e["verdict"] if e["verdict"] is not None else "none (its turn ended before the test ran)"
        summary = e["summary"] if e["summary"] is not None else "none (its turn ended before it wrote one)"
        lines.append(f"Turn {e['turn']}: tried \"{e['description']}\"\n```diff\n{e['diff']}\n```\n"
                     f"Verdict from the frozen test: {verdict}. Its summary: {summary}")
    return "The record of earlier turns, oldest first:\n\n" + "\n\n".join(lines)


def advice(record, patches, keys, seed):
    """R2's advice: stage A's adaptive-by-content policy, run on the record and the open patches' content keys.
    `keys` gives, for each record entry and then each open patch, the harness's content key, in that order."""
    entry_keys, option_keys = keys[:len(record)], keys[len(record):]
    policy_record = [{"turn": e["turn"], "state": e.get("state", "L0"), "name": e["description"], "content": k,
                      "verdict": {"pass": "pass", "fail": "fail"}.get(e["verdict"], "fail"),
                      "summary": {"approach": k, "says": "worked" if e["verdict"] == "pass" else "failed"},
                      "observation": None}
                     for e, k in zip(record, entry_keys) if e["verdict"] is not None]
    options = [{"name": p["description"], "content": k} for p, k in zip(patches, option_keys)]
    index, flags = adaptive_content(policy_record, options, seed)
    tried = sorted({f["repeat"] for f in flags if "repeat" in f})
    repeats = [i for i, k in enumerate(option_keys) if k in tried]
    text = (f"Advice from a bandit that keys patches by the file each one produces, not by their descriptions: "
            f"try patch {index}.")
    if repeats:
        text += " It sees that patch " + ", ".join(map(str, repeats)) + " changes exactly what an earlier turn's patch did."
    return text + " You may ignore this advice."


def prompt(arm, task, patches, record, keys=None, seed=0):
    """The whole prompt one turn of `arm` reads."""
    if arm not in ARMS:
        raise ValueError(f"No arm {arm}")
    parts = [INTRO.format(memory="" if arm == "R0" else ", except what the record below says"),
             "The task:\n" + task, "The open patches:\n\n" + _patches(patches)]
    if arm in ("R1", "R2"):
        parts.append(_record(record))
    if arm == "R2":
        parts.append(advice(record, patches, keys, seed))
    parts.append(REPLY)
    return "\n\n".join(parts)


class Malformed(ValueError):
    """A reply that isn't one JSON object of the frozen shape: that turn is a stall, and spent."""


def read_reply(text, k):
    """`(choice, summary, flags)` from a turn's reply, or Malformed."""
    match = re.fullmatch(r"\s*(?:```(?:json)?\s*)?(\{.*\})(?:\s*```)?\s*", text, re.S)
    if not match:
        raise Malformed("not one JSON object")
    try:
        got = json.loads(match.group(1))
    except ValueError as error:
        raise Malformed(f"not JSON: {error}") from error
    if not isinstance(got, dict) or set(got) != {"choice", "summary", "flags"}:
        raise Malformed("keys must be exactly choice, summary and flags")
    choice, summary, flags = got["choice"], got["summary"], got["flags"]
    if type(choice) is not int or not 0 <= choice < k:
        raise Malformed(f"choice must be an integer from 0 to {k - 1}")
    if not isinstance(summary, str) or not summary.strip():
        raise Malformed("summary must be a non-empty string")
    if not isinstance(flags, list) or any(not isinstance(f, dict) or len(f) != 1 or set(f) - FLAG_KEYS
                                          for f in flags):
        raise Malformed("flags must be a list of one-key flags")
    return choice, summary.strip(), flags
