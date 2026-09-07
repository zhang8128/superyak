"""Record explicit receiver judgments in the Lighthouse kit's labels format."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from lighthouse_protocol import canonical_json
from lighthouse_receipts import validate_receipt


def _references(pairs):
    refs = set()
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("INVALID_MEMORY_REFERENCE")
        publisher, memory_id = pair
        if (not isinstance(publisher, str) or not publisher.startswith("urn:")
                or len(publisher) <= 4 or any(char.isspace() for char in publisher)
                or not isinstance(memory_id, str) or not memory_id.strip()):
            raise ValueError("INVALID_MEMORY_REFERENCE")
        ref = (publisher, memory_id)
        if ref in refs:
            raise ValueError("DUPLICATE_JUDGMENT")
        refs.add(ref)
    return refs


def build_labels(receipt: dict, *, relevant, forbidden=()) -> dict:
    """Copy turn identity and record only caller-supplied memory judgments.

    Absent memories are allowed: false-negative judgments must remain possible.
    Receipt selection and delivery are evidence, not relevance labels.
    """
    validate_receipt(receipt)
    positive, negative = _references(relevant), _references(forbidden)
    if not positive:
        raise ValueError("EMPTY_RELEVANCE_JUDGMENT")
    if positive & negative:
        raise ValueError("CONFLICTING_JUDGMENT")

    def records(refs):
        return [dict(publisher=publisher, memoryId=memory_id)
                for publisher, memory_id in sorted(refs, key=canonical_json)]

    payload = receipt["payload"]
    return {
        "formatVersion": "1.0", "instance": receipt["issuer"],
        "turns": [{
            "turnId": payload["turnId"], "context": deepcopy(payload["context"]),
            "purpose": payload["purpose"],
            "relevant": records(positive), "forbidden": records(negative),
        }],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Record explicit relevance judgments; no labels are inferred."
    )
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--relevant", nargs=2, action="append", required=True,
                        metavar=("PUBLISHER_URN", "MEMORY_ID"))
    parser.add_argument("--forbidden", nargs=2, action="append", default=[],
                        metavar=("PUBLISHER_URN", "MEMORY_ID"))
    parser.add_argument("--output", type=Path, help="New labels file; defaults to stdout")
    args = parser.parse_args(argv)
    try:
        with args.receipt.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("RECEIPT_TOO_LARGE")
        labels = build_labels(json.loads(raw), relevant=args.relevant, forbidden=args.forbidden)
        rendered = canonical_json(labels) + "\n"
        if args.output is None:
            print(rendered, end="")
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
    except (OSError, ValueError, TypeError) as error:
        parser.exit(2, f"lighthouse_label: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
