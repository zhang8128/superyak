# Personal dashboards, private chats, and forgiving sharing

Date: 2026-09-12. Status: proposed product design for discussion; no application
implementation or deployment is claimed. Kairos confirmed **a personal home across
chats, care circles, projects, and organizations** as the main entry point.
This navigation choice is accepted; other detailed behaviors remain proposed.
This document develops the existing
[medical pilot plan](../../medical-lighthouse-pilot-plan.md).

## Open-source, peer-to-peer system

Kairos reaffirmed **open-source and peer-to-peer** as requirements. These govern
the personal home, private chats, sharing layers, and organization dashboards.
They are not optional additions after building a centrally hosted product.

- People can run a peer themselves or choose a trusted host. An organization can
  operate a peer for its participants without becoming the network's owner.
  Participants should not need to administer a server to use their dashboard.
- Each peer maintains its own records, attributed identities, private memory,
  and access decisions. A personal home assembles authorized local and received
  information. It does not require a global database of people and conversations.
- Peers exchange explicitly addressed, authorized messages and selected versioned
  publications. Discovery and relay services can help them connect, but must not
  be the authority that grants access or the sole required operator of the network.
- No mandatory Superyak-wide account service, organization administrator, paid
  model API, or cloud control service may be required to run the core system.
  The preferred Gemma 4 route should be locally hostable after compatibility is
  verified. This deployment's American-model rule remains in force.
- People can retain local drafts and read authorized local material while another
  peer is unavailable. Show delivery, correction, and withdrawal acknowledgment
  states honestly. Reconnection must recheck grants before releasing queued data.
- Export and host migration must preserve source identities, versions, ownership,
  and sharing history. A move must not silently renew grants or leave an old host
  authorized. Host/key recovery needs a tested procedure before promising seamless
  portability or a particular encryption guarantee.
- Release the application, peer protocol/schema definitions, conformance examples,
  and self-hosting documentation under a chosen open-source license. Public source
  distribution and a person's public sharing layer are separate decisions; running
  open-source software does not publish the person's data.

The first transport slice needs authenticated peer identities and encrypted
delivery through an established protocol. The existing aDNA adapters and content
digests do not establish that boundary. Keep operator trust and which endpoints
can decrypt explicit, including any agent/model recipient; do not imply that a
relay connection alone provides private application messaging.

### Present state and release boundary

The repository currently has reusable memory, evidence, scoped local sharing,
and aDNA projection code. Its local Unix-socket exchange is not a completed
cross-machine private chat service. Dashboards, participant authentication, and
sharing layers in this document remain proposed application work.

On this inspection, GitHub `zhang8128/superyak` is private and has no root license.
A public source release still needs a license decision, preservation of imported
notices, and review of what enters the public source and history. The current
tracked handoffs and historical reports include personal operational context;
do not make the entire existing repository public without reviewing that material.
Private `.engram/` archives and participant data remain excluded. Prepare a
reviewable source release without deleting or rewriting the preserved private
research history. This design does not change repository visibility or licensing.

## Corrected context and intended experience

Kairos corrected the hackathon organization to **Wilhelm Foundation**. The earlier
Research to the People attribution was a mix-up. This correction changes the
hackathon context; it does not establish anyone's organizational affiliation,
rename one organization into another, or change recipients or permissions.
Keep historical messages intact and make the current correction easy to find.

People may confuse names, change their minds, speak imprecisely, lose their
place, or need help. The product should preserve their work and make recovery
ordinary. Nobody should have to explain a disability or select a patient role
to use these supports. Being a patient, doctor, researcher, family member, or
organizer changes the useful presentation; it does not by itself grant access.

## Approach

Use a **personal home with shared spaces**. A person can belong to several care
circles, projects, and organizations without creating a new identity each time.
An organization has its own dashboard and can contain teams and projects, but
membership and content access are separate. Navigation hierarchy does not imply
permission inheritance. A project can involve more than one organization.

An organization-first hub would make event navigation prominent but make people
switch homes when their relationships overlap. A permission matrix for every
action would offer flexibility at the cost of everyday comprehension. The
recommended design keeps organizational hubs available and uses a small number
of audience presets, with details available when needed.

## The dashboards

| View | Useful contents | Boundary |
| --- | --- | --- |
| My home | Resume a chat, questions, notes, tasks, invitations, what changed, sharing overview | Only material this person can access |
| Patient or family view | Personal priorities, observations, appointment questions, chosen updates | Each person has their own space; family access is invited |
| Clinician or researcher view | Authorized cases/projects, concise evidence, source links, unresolved questions | Credentials and affiliation do not automatically open cases |
| Care circle or project | Shared questions, contributions, tasks, selected sources and results | Its current authorized audience, not the whole organization |
| Organization or hackathon | Projects offered to the organization, announcements, invitations, operational help | Administration does not grant private chat or record access |
| Public page | Deliberately published updates, public research, contact information chosen for publication | No private titles, counts, identities, attachments, or source links |

These are configurable views of the same attributed work, not separate truth
stores. Someone can be a clinician in one space and a family member in another.
Show the active space and represented role beside the composer and sensitive
actions. Avoid forcing people into one permanent category.

My home starts with **Continue**, **Chats**, **My information**, **Shared spaces**,
and **My sharing layers**. Detail can expand without changing the underlying evidence.
An empty view offers a useful first action. A restricted view does not reveal
whether another person's private record exists.

## Take time to construct sharing layers

**People can spend time building what they want to share, with whom, and how they
want to appear publicly.** This is an ongoing workspace they can return to over
days or weeks. It is optional at onboarding; they can use their private dashboard
and chats while every outward layer remains off. There is no deadline, completion
score, or pressure to publish.

**My sharing layers** lets a person name and arrange layers, choose audiences,
select particular information and attachments, write a different account for each
audience, and save reusable presets. For example:

| Layer someone might construct | Selected contents |
| --- | --- |
| Only me | Private notes and drafts |
| Family updates | A short update and requests for practical help |
| Care team | Selected observations, questions, and source documents |
| Project collaborators | A research question and chosen evidence |
| Organization profile | Interests, contributions, and ways to collaborate |
| Public presence | A deliberately written story, public research, or selected updates |

These are editable starting suggestions. They are not a compulsory ladder or
progressively larger copies of the private record. A public research contribution
may contain no personal health information at all. A person can have several
different public pages or project layers, each with its own selected contents.
Only material they are authorized to release can be included.

Within a layer, **Save draft** preserves construction without changing live access.
People can pause, resume, duplicate a draft, remove information, compare revisions,
and preview **as this audience** or **as a public visitor**. A chosen helper or
approved model can assist with drafting, but manual construction works throughout.
Help does not receive access to every layer merely because it was invited to one.

Show **Draft**, **Active**, and **Changes not yet published** clearly. The current
published version remains unchanged while its replacement is being prepared.
**Apply this version** or **Publish this version** releases the selected revision
after its audience/content preview. Simple On/Off switches remain the everyday
controls for activating or withdrawing a constructed layer. Editing a preset does
not silently expand already active grants or include future private content.

Copy for the workspace: **“Build your sharing layers at your own pace. Save them
privately, see what each audience would see, and turn them on when you're ready.”**

## Simple sharing controls

Every item shows a short, effective audience label: **Only you**, **You and Sam**,
**Care circle · 4 people**, **Project team**, or **Public version available**.
Opening that label shows the actual recipients and the routes through which
they have access. Audience names use stable identities behind editable labels.

For a private note, the initial panel might be:

| Share this version with | Switch |
| --- | --- |
| Selected people | Off |
| My care circle | Off |
| This project team | Off |
| Wilhelm Foundation organization space | Off |
| Public internet — publish a selected version | Off |

Show only audiences relevant to the current space. Selecting an audience shows
its name and members before applying the grant. Organizational audiences must
say **All current and future members of this space** if membership is dynamic;
never quietly substitute that for a fixed list of people. Care circles and
private chats use explicit named membership in the first slice.

The switches control explicit grants for this item. Sharing with a project does
not turn on organization-wide sharing. An organization administrator can set
defaults for new organization-owned material, but cannot widen a person's
private material or a chat they do not control. Changes to defaults do not
retroactively expose existing items. Explicit restrictions on particular
recipients take precedence over group grants within authenticated access.

Turning one route off removes that grant. If another route still permits access,
say **Still visible through Project team**. The plain-language audience summary
must describe effective access, rather than merely display switch positions.
An item inside an already shared space offers **Make a private copy**; its UI
must not pretend that turning off a nonexistent direct grant makes it private.

### Public is a deliberate publication

Public means readable without membership or sign-in. It is a separate selected
publication, not a live window into a private dashboard, case, or chat. The
preview shows the exact text, attachments, identifiers, and public source links
to be released. The user must have authority to release that material; receiving
a private document or participating in a chat is not permission to publish it.

While turning public on, **Publish this version** applies the previewed choice.
Subsequent private edits remain private until another version is published.
Turning it off withdraws the hosted public version immediately when connected.
The source can remain shared with named people or groups. Because a public
version is accessible to anyone, it cannot promise exclusion of an individual;
do not offer a contradictory public-plus-personal-exclusion guarantee.

Use **View as a visitor** for public previews. Organization dashboards and
project dashboards can have selected public pages under the same rule. Private
dashboard widgets and private source URLs never enter the public export.

**Stop all sharing of this item** removes all grants and withdraws its public
publication. Report remaining acknowledgments from remote peers separately.
Withdrawal stops further access through controlled services; it cannot erase
copies people already received. An offline change is **Waiting to apply**, not
**Off everywhere**. Restoration creates a new deliberate grant; a late network
retry cannot undo a newer withdrawal.

## Private chats

People can create a personal agent chat, a private direct chat, or an invited
group chat. Human participation works without an AI assistant. The composer
always shows who will receive the message and whether an agent is participating.
Organization administrators cannot read private chat contents through their
administrative role. Private conversations do not appear in public or
organization search, activity feeds, notifications, or aggregate summaries.

In the first slice, adding a participant starts a linked room for the new
audience. Previous messages stay in the original room. An optional handover
summary is previewed for sharing by people authorized to release its contents.
The new participant sees only the new room and selected handover. This avoids
making old messages visible as an unnoticed side effect of an invitation.

Removing a participant stops their future delivery and hosted access. The
remaining participants continue in a new audience epoch; sends queued under
obsolete membership must be rechecked before delivery. Keep prior authorship
and disclosure history without promising to retract plaintext already read.

There is no **make this entire private chat public** switch. **Share an update**
creates a separate draft with selected content and an audience preview. Other
people's words and attachments need the appropriate release authority. This
does not add a confirmation to every ordinary message within an unchanged room.

Agent inputs, retrieved memories, attachments, summaries, and tool outputs must
fit the chat's audience before entering the shared generation context. A private
conversation with one's agent must not be copied into a group model session.
Generated summaries receive no broader sharing rights merely because an agent
rewrote the inputs. Explicitly preparing a publishable summary remains private
until its selected release is authorized.

**Private** here specifies application audiences. It is not a claim of end-to-end
encryption or immunity from the hosting operator. Participant-to-participant
encryption, server handling, and any model provider's access need an explicit
implementation decision and tested description before real private chat launch.
An invited agent's execution location and data access belong in that description.

## Support for mistakes and uncertainty

| Situation | Product response |
| --- | --- |
| An organization or person was mixed up | Accept the correction in ordinary language; show the changed relationship or description and an undo action |
| The intended person is unclear | Keep the text as a draft; offer only candidates the author is allowed to see; resolve identity before sending or granting access |
| A fact or date is uncertain | Keep it marked as uncertain; allow a range, approximate date, or “I don't know” |
| Two people remember differently | Preserve attributed accounts side by side; offer clarification without making one erase the other |
| A correction affects earlier summaries | Mark linked summaries as needing revision; do not continue presenting the superseded account as current |
| Someone chose the wrong space | Keep the draft and offer a move; recompute audience and attachment access before sending |
| Someone needs help or a break | Save drafts and their place, show a short resume card, allow pause or a scoped help request |

A correction is an amendment with an author, time, original source, and affected
relationship or claim. Do not perform a global text replacement or merge entity
IDs because two names were confused. Names, affiliations, memberships, and access
grants are separate records. A new affiliation claim is not a membership grant.

For Kairos's example, the assistant can say: **“Got it — Wilhelm Foundation for
the hackathon. I've updated that context; sharing stays the same.”** The current
context uses the correction while the original statement remains historical.
Corrections travel only to audiences already authorized for the affected content;
their existence and details must not leak across private spaces.

Routine reversible edits happen directly with undo. A new recipient, broader
audience, or public release gets a concrete preview at that boundary. Repeated
internal steps within an already authorized task do not need repeated approval.
For sensitive identity mismatches, hold the affected send/import while allowing
unrelated drafting to continue. Never use a model's name match as authentication.

Support editable dictation, keyboard and screen-reader operation, adjustable
text, large controls, explicit text alongside icons, and a low-stimulation view.
Do not encode access state only with color. Keep **Saved**, **Sent**, **Waiting**,
and **Needs attention** distinct. Preserve drafts across reauthentication and
network failures. Notification previews should be content-free by default.

A helper receives an explicit, time-limited invitation to a selected support
view. They act under their own identity. Sharing setup status or a selected
screen is separate from opening medical information or private conversations.
Revoking help closes future access without losing the person's work.

## Integration with the current repository

All model-assisted work must follow the [American-model requirement](../../model-policy.md).
Gemma 4 is Kairos's preferred family. This includes private drafting and public
summary preparation; changing the audience does not relax model eligibility.
No automatic fallback to the earlier Qwen, Kimi, GLM, or DeepSeek choices is allowed.

| Existing foundation | Reuse | Missing product boundary |
| --- | --- | --- |
| Engram individual stores and `sharing.py` | Attributed private memory, explicit selected copies, share withdrawal | Authenticated people, resource ownership, invitations, effective access and organizational membership |
| Engram context chat and corrections | Durable threads, source manifests, an existing correction interaction | Multiuser private rooms, membership enforcement and audience-scoped model contexts |
| Atlas evidence journal and views | Sources, proposed findings, source links and research views | Authorized per-person queries and filtered exports before rendering |
| Lighthouse policies and receipts | Scoped decisions, origin/digest binding and explicit disclosure evidence | Authenticated application peer delivery and propagated grant changes |
| Local aDNA sources and projections | Separate source identities and selected artifact interchange | Proven multi-peer private application transport |

The current Engram web server is a loopback service with local-origin checks;
thread IDs are not multiuser authorization. Existing `group:*` and `commons`
sharing names are internal audience vocabulary. In particular, `commons` is not
an implemented public-internet publication feature. Neither the existing static
Atlas pages nor a visual sharing switch supplies an access-control boundary.

The application needs stable person/space/resource IDs; explicit membership and
grants; resource revisions; chat audience epochs; attributed corrections; and
selected publication records. Apply authorization at read, search, export,
model-input assembly, tool execution, and delivery. Recheck the current grant
version at an output boundary so a result prepared before withdrawal cannot be
sent afterward. Filter on the server before returning data to a dashboard.

Keep private memory with its owning peer and maintain the peer-to-peer/aDNA
requirement. A nested organization does not become the network's central owner.
Do not design a new distributed coordination system or cluster capacity model
for this slice. Real transport and hosting choices must be verified separately.

## First demonstrable slice and acceptance

Use fictional participants and synthetic case material: a patient, family member,
clinician, and organizer, with one overlapping project and one public visitor.
This is a test fixture, not a limit on the hackathon's intended participation.

Demonstrate personal dashboards, a private room, a shared project update, a public
version, and a correction. A clickable mockup can validate comprehension, but
must be labeled simulated; only server-enforced tests can establish isolation.

The first implementation milestone is a small path between **two independently
hosted peers**: each has a personal home and separate store, one private message
crosses the authenticated boundary, and one selected item is shared, corrected,
and withdrawn. Exercise disconnected delivery and restart. Local isolated
instances are useful preparation; the final peer demonstration must cross two
machines without a shared database or mandatory central application service.
Add richer organization views on this proven boundary. Do not scale a mock chat
or pick a distributed framework before measuring this path.

1. Correct the hackathon organization. Future context uses Wilhelm Foundation;
   original history survives; membership and grants are byte-for-byte unchanged.
2. A doctor and organizer cannot access an uninvited chat through its URL, search,
   export, notifications, agent tools, or a generated summary.
3. A patient shares one update with a care circle. Unrelated chats and attachments
   remain inaccessible; organization membership alone does not reveal the update.
4. Publish a selected version. A signed-out visitor sees exactly that version;
   later private edits and private citation targets remain unavailable.
5. Withdraw an audience grant while a task or delivery is queued. Its output does
   not reach the removed recipient. Show any alternative grant and outstanding
   peer acknowledgment accurately; repeating the operation cannot restore access.
6. Add a chat participant. The linked new room contains no earlier messages beyond
   the explicitly shared handover. Remove a participant and recheck queued sends.
7. Interrupt a draft or support flow. Resume without losing text or silently
   changing the selected audience. A helper cannot impersonate the participant.
8. Change an organization's sharing default and membership. Existing private
   items remain private; any dynamic audience exposure matches its visible rule.
9. Construct several sharing layers over separate sessions with all switches off.
   Drafts, wording, and selected audiences survive interruption; nobody else can
   retrieve them. Activate one selected version, edit its replacement privately,
   and prove that both the active version and other layers remain unchanged.
10. Attempt a model-assisted draft with a disallowed or unidentified model. No
    request is dispatched and no fallback occurs; the saved draft remains editable.
11. Run the selected message/share/correction/withdrawal path across two machines.
    Unshared content stays at its authorized endpoints; colliding local IDs keep
    distinct origins; restart does not duplicate accepted deliveries; queued work
    cannot bypass a newer withdrawal. Removing an optional discovery/relay service
    does not erase local data or confer authority on another operator.

Ask trial users to identify who can see each example, correct a mistaken name,
recover a draft, and stop sharing. Record misunderstandings, missed corrections,
unintended audience choices, recovery success and time spent. No numerical
usability, security, or scale success is claimed before these observations.

Uploads and authorized medical-record connections remain requirements of the
larger pilot. This audience-and-recovery slice does not replace them or claim
to have implemented accounts, encryption, clinical access, or live deployment.
