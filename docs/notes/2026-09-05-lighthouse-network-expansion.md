# Lighthouse network expansion — parked discussion notes

Date: 2026-09-05
Status: Architectural exploration, not an approved implementation specification.
Priority: Resume after the dynamic-context runtime work has a useful foundation.

## Purpose

Bridge independently governed memory and knowledge systems. Participants keep
their own systems and choose which sources to encounter, for which purposes,
and under which sharing conditions. Support individuals and institutions as
participants, including research collaborators, regional health services,
libraries, and cafes.

The motivating example is the French cheese institute and a friend, Mike,
who consistently brings good cheese. Institutional expertise and personally
earned trust both matter. They concern different questions and need their
own histories. Do not collapse them into one global reputation score.

The AI-city framing includes private memories, chosen neighborhoods, public
institutions, and crossings between incompatible systems. Connections should
be inspectable, scoped, revocable for future access, and never silently
inherited from the infrastructure operator. Participants need room to change;
an introduction built only from founding memories can become stale.

## Current foundation and its limits

Source inspection on this date found clean checkouts at engram `9440bd8` and
the sibling lighthouse repository `0a9f615`. This was not a new deployment
verification or test-suite run.

- Engram has explicit `share`, `unshare`, and `shares`, copied published
  records with provenance, audience policies, and a Unix-socket publisher.
- The publisher checks policy before retrieval, separates recall from content
  reads, and records disclosures. Audience grants are publisher-held.
- Normal Engram `recall()` does not yet have the Lighthouse receiver arm.
- Lighthouse provides bounded offline Hyper-to-aDNA translation checks,
  portable Engram recall traces, policy evaluation, receipts, and shadow
  evaluation. These checks establish specific contracts within their fixtures.
- The local publisher takes receiver names from request frames. Content-digest
  verification is not cryptographic authentication of a remote participant.
- Higher-category and sheaf mechanisms are partial, experiment-gated
  implementations. The existing spectral cohesion proxy does not prove that
  natural-language claims are true or mutually consistent.

Relevant existing designs:

- [Layered publisher and sharing](../superpowers/specs/2026-09-02-layered-lighthouse-design.md)
- [Contextual memory](../superpowers/specs/2026-08-07-evolving-category-memory-design.md)
- [Sheaf cohesion](../superpowers/specs/2026-06-13-sheaf-cohesion-design.md)
- The sibling lighthouse repository's README and normative protocol summaries.

## Distinctions to preserve

Separate the subject, an account about it, its author, its publisher, and the
recipient's relationship to that source.

- A library can publish accounts about works, editions, translations, and
  particular copies. Reader annotations remain separately attributed.
- A cafe can publish individually addressable menu items through one
  lighthouse. A recipe, today's offering, an ingredient batch, and a customer's
  experience have different identities and histories.
- A person can publish a selected introduction or note through their own app
  or a chosen host. Participation should not require operating a server.
- A regional health office can publish public service information and maintain
  separately permissioned operational views. The first actual workflow should
  be selected with its participants.

The recipient assesses trust; the publisher governs access. Encountering a
source, following updates, trusting an account for a purpose, and granting
access to one's own material are separate relationships. A neighbor's
recommendation can introduce another source without automatically conferring
trust or access.

## Interchange and delivery

Keep the common exchange contract small: source identity, requested scope and
purpose, original account, provenance, time/version, sharing terms, and links
to revisions. Preserve the original material alongside any adapter-produced
interpretation. An adapter must identify unsupported or lossy mappings.

Keep permissions such as read, recall, suggest, inject into context, retain,
derive, and reshare distinct. Withdrawal stops future authorized access; it
cannot force deletion of plaintext already received elsewhere.

The same account model should be usable through institutional services and
direct peer connections. Discovery, authenticated transport, offline delivery,
and synchronization remain engineering work. Invitations and chosen directories
are candidate discovery mechanisms; a universal registry is not assumed.

User-proposed watermark/voice signatures could help recognize a source and its
declared role or affiliations. Recognition should resolve to an authenticated
identity. Watermark detection alone is not sufficient authentication.

Kairos's separate quantum-secure blockchain work is a possible attestation
integration to investigate. Its cryptographic design and interface have not
been inspected here. Do not assume every account belongs on a ledger or that
the current Lighthouse protocol implements that integration.

## Mathematical role

Categorical structure should express typed transformations and their
composition. Higher cells can retain justified comparisons, corrections, and
coherence between transformations. Arbitrarily increasing a record's level
does not establish those laws.

Sheaf structure can express local views, their restriction maps, and
compatibility over specified overlaps. Access policy selects the available
material before comparison. Compatibility depends on the chosen maps; it
does not establish truth, erase disagreement, or authorize disclosure.

Useful questions include whether a translated claim keeps its meaning, which
assumptions were lost, and which derived interpretations need reconsideration
after an observation changes. Preserve source histories and distinguish a
received account from the recipient's own experience of encountering it.

## Expansion sequence to revisit

1. Complete the live Engram receiver with source-visible delivery and receipts.
2. Add authenticated cross-machine participants and transport, including key
   lifecycle and unavailable-source behavior.
3. Provide understandable neighbor selection, scoped sharing, explanations of
   source influence, and withdrawal controls.
4. Connect a real second system through one limited adapter and conformance
   examples; avoid requiring it to adopt Engram's internal store.
5. Carry revisions, withdrawal notices, and dependency changes through the
   receiving side. Record translation corrections with their evidence.
6. Evaluate repeated use by actual participants: usefulness, fidelity,
   attribution, scope enforcement, latency, and whether people return.

A candidate pilot involves one individual, one peer, and one institutional
source across two independently operated systems. Demonstrate sharing,
consultation, disagreement, correction, and withdrawal of future access.
Institutional and personally earned trust should remain intelligible in the
same exchange. No particular external deployment or outreach is authorized by
these notes.

## Existing standards to examine

- [PROV-O](https://www.w3.org/TR/prov-o/): attribution, derivation, and revision.
- [Solid](https://solidproject.org/TR/protocol): personal resources and access.
- [ActivityPub](https://www.w3.org/TR/activitypub/): server-to-server federation;
  direct device-to-device delivery needs its own transport work.
- [BIBFRAME](https://www.loc.gov/bibframe/docs/bibframe2-model.html): works,
  published forms, and individual copies.
- [Schema.org MenuItem](https://schema.org/MenuItem): existing menu vocabulary.

These cover parts of the problem. Their compatibility with the intended
Lighthouse profiles must be checked; listing them is not an implementation
decision.

## Current priority: dynamic working context

The immediate work is automatic memory preparation and a bounded context
assembled before each model call, including calls within tool-using turns.
Current Codex hooks add text to history; they do not replace that history.
The local-agent prompt builder and bounded category compiler are partial
starting points. Selection must preserve instructions, active intent,
corrections, recent continuity, and required tool state.

Store the full exchange outside working context, and retrieve relevant views
as needed. Keep only a short pointer to this note in active task context.
The eventual runtime must enforce the full input budget plus response reserve,
not merely limit the number of recalled memories. Runtime integration and
behavioral validation are still required; saving this note enables neither.
