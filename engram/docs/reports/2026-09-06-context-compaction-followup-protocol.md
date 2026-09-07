# Compaction deadline follow-up

The first comparison's second summary call timed out at 120 seconds. Its first
call took 86.45 seconds and produced a valid 5,131-byte summary of 91 entries.
Inspection found that the provider inherits `xhigh` reasoning from the installed
configuration. The deadline may be too short for this auxiliary workload; the
original timeout alone does not establish whether a valid summary is feasible.

This follow-up changes **only the compaction episode deadline to 300 seconds**.
Model, reasoning configuration, input envelope, summary cap, instructions, chunk
selection, call limit, corpus, questions, and answer settings remain as frozen
in the [first protocol](2026-09-06-context-continuity-protocol.md). No production
provider setting changes. This is a separate exploratory continuation prompted
by an observed failure, not a replacement for the first experiment.

Start from the first experiment's successful step-zero summary, with its full
response, digest, and provenance preserved as an imported result. Reconstruct
step one and require its request digest to equal the recorded failed request
before any new dispatch. Count imported and new auxiliary calls separately.
Capture all subsequent calls and failures without automatic retries; the
existing dispatch journals and non-replay behavior still apply. A second failure
ends this profile's preparation and remains a reported outcome.

If preparation succeeds, capture 100 new comparator answers, with the original
common answer instruction and 120-second answer episodes, at most two concurrent
calls, and the same fixed shuffle seed. Keep the original 200 dynamic/LocalAgent
answers as historical comparison records. Do not regenerate them. The new arm
was generated later and was not interleaved with those answering arms; this is
an exploratory comparison, with that timing limitation reported.

Validate source availability, JSON shape, and byte admission mechanically. Keep
all human ratings unset. A combined review packet may reuse the original 200
captured answers and replace the *displayed comparison slot* with this follow-up
arm, while retaining the original failed arm in the original study and recording
the mapping. It must never relabel this arm as the original successful outcome.

Report preparation success/failure, actual usage and latency, imported auxiliary
cost separately, citation checks, and the provenance of every reused record.
If the longer deadline still fails, diagnose the resulting evidence before
choosing any different profile. No answer or grading feedback enters compaction.
