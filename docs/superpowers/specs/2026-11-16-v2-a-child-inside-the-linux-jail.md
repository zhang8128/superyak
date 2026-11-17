# A program inside the Linux jail cannot start a child: the cause, and the mend

Serenity, 2026-11-16, revision 3. It changes the jail's boundary by one kind of socket pair. A fresh reader
of the other family read revision 1 as a change to the boundary and approved it with three named changes,
all made in revision 2; a later section says where. The code was read again before it was pushed.

Revision 3 corrects one row of the argument. A second Linux machine, on a later kernel, answered one try
otherwise than the row said. In the runs made, nothing that decides what an end can reach or be reached by
differed. The last section says what was found, what was changed and what was not. A fresh reader of the
other family read it and the test's change, and named three changes, all made.

## What was found

"Ready to test" asks for one turn with a block on a second machine. On the second machine (Linux 6.12,
aarch64) the turn was given the block, the same bytes as on the first, and the worker's commit was right:
run by hand, outside the jail, the item's check passed all 23 of its cases. The room failed the turn. Its
check had ended in two seconds.

What the room keeps of a check is its exit code and a hash of its output, so the cause was looked for with
checks written as ladders, whose exit code says which rung failed, and a stand-in worker, with no model:

1. Inside the jail a check finds `cargo`, both versions print, the vendored crates can be listed, and a
   check can write a program into its clone and into its scratch directory and run it there.
2. Inside the jail the old items' own build of `yak`, word for word, fails. Its output holds "could not
   execute process" and "Operation not permitted".
3. Outside the jail, in a fresh clone with the same environment, the same build passes in 61 seconds.
4. Traced outside the jail, one build of the room's crate makes this call 73 times, and no other socket
   call: `socketpair(AF_UNIX, SOCK_SEQPACKET|SOCK_CLOEXEC, 0)`.
5. The Linux filter (`v2/crates/turn/src/filter.rs`) lets a pair through only when it is a Unix pair of
   the stream kind, and refuses every other pair with "operation not permitted".

**The leading cause: the way `cargo` starts a child here asks for a pair that the filter refuses.** The
reader read the pinned toolchain's standard library: to start a child it first tries a way that needs no
socket, and where that way does not apply it falls back to one that first makes a Unix pair of the
seqpacket kind. The trace shows `cargo` on that second way.

- **It is not every program built with this toolchain.** One that starts a child the first way is not
  stopped. A shell is not stopped either: it starts its children without a socket.
- **It was the leading cause until one controlled run, and that run is made.** "Operation not permitted"
  beside "could not execute process" does not name the call that was refused. So ladder 3's build, word for
  word, in a fresh clone, was put through a jail that differs in one thing: a `yak` built from a scratch
  copy of the tree in which the filter also lets through a Unix pair of the seqpacket kind (one step added,
  and committed nowhere). It ended with 0 where it had ended with 112, and the room judged the stand-in
  turn passed and verified. The pair is what stopped the child.

**Why it was not seen.** No test runs, inside the Linux jail, a program of ours that starts a child that
way: checks in the tests are shell scripts. The first run and the pilot were on macOS, whose jail has no
such filter. A model worker's own shell is not inside the room's jail.

**What it costs as it stands.** On Linux the room cannot judge an item whose check builds Rust with
`cargo`: the three old items, and any item of the v2 crates. And freezing an item does not notice: a check
that cannot run fails on the base and on the wrong commit, which is all that freezing asks, so the item
freezes and then every turn at it fails, right or wrong.

## The mend

**The filter lets through a Unix pair of the stream kind or of the seqpacket kind.** Nothing else
changes: a datagram pair is still refused, and a pair of any other family; `socket` is as it was, with no
Unix socket; the seven calls refused outright; the check of the machine's kind and of the other numbering.

**Two narrower mends, and why not.** Letting the pair through only with the close-on-exec flag the trace
shows would hold nothing: a run can clear that flag afterwards. Making our own programs start children
another way would not mend `cargo`, which is not ours.

## Why this does not widen what a run can reach

The filter's reason for refusing a datagram pair is that one end could be sent from to a named socket: a
socket file inside a directory the jail shows, where some service of the machine listens. The question is
whether an end of a seqpacket pair can be made to reach anything but its other end.

**It rests on how the kernel treats that kind of socket,** read by the spec's reader in the kernel's
source at version 6.12, the second machine's (`net/unix/af_unix.c`):

| What a run might try with an end of the pair | What the kernel does |
| --- | --- |
| Nothing: the pair as made | Both ends are joined to each other and marked as joined (`unix_socketpair`) |
| Send, naming another socket | The name is dropped and the message goes to the joined end (`unix_seqpacket_sendmsg`) |
| Join a named socket | Joining needs an end that is not joined; a joined end is refused (`unix_stream_connect`) |
| Close the other end, then join a named socket | The end left over is shut down and is not made unjoined again; a send then fails, and it still cannot join |
| Unjoin, by joining "no family" | Refused: that way of unjoining belongs to datagram sockets (`unix_validate_addr`) |
| Give it a name, then listen and accept | Naming does not unjoin it. A joined end was not seen to come to listen: 6.12 refuses the telling; on 7.0 the telling was answered yes, and the end was then seen not to listen (corrected in revision 3, from runs on one machine of each, the later as reported by the ship that ran it; 7.0's source was not read). Accepting needs an end that listens, and a socket made for the end's name was refused on both |

- **Open files.** A pair of either kind can carry an open file from one end to the other. That hands on
  something the sender already holds and makes nothing new, and both ends are inside the jail. An end
  inherited from outside the jail would need an argument of its own, for either kind of pair.
- **How sure.** This is reading of the kernel's source at that one version, not a run on that machine and
  not an audit of the kernel. The tests below try each row. A finite set of tries cannot show that an end
  can never reach anything else; the reading is the argument, and the tests are there to fail if a kernel
  behaves otherwise. One did, in the last row: see "What a second machine found".

## How we know

Each row has a case that must pass and a case that must be refused. The first row is a run made before the
mend was built. The tests in the rows after it were written with the mend: the filter's in
`v2/crates/turn/src/filter.rs`, the jail's in `v2/crates/turn/tests/jail.rs`.

| What | Shown by |
| --- | --- |
| The controlled run | Made, before the mend is built: ladder 3's build through the jail with only this pair let through ended with 0, where it had ended with 112 |
| The filter's program | Run as the kernel would, for both kinds of machine. A Unix seqpacket pair is let through, alone and with each of the two flags the kernel takes; the two cases that today hold it refused become cases that hold it let through. A Unix datagram pair, and a seqpacket pair of another family, are refused. Every other case the tests hold now (stream pairs, sockets, the seven calls, another kind of machine, the other numbering) holds unchanged |
| A program of ours starts a child inside the jail | On Linux, inside the jail, a helper built with this toolchain starts a child by a bare name found on a path it is given, which is what makes the standard library take the way that asks for the pair. Without the mend it fails at starting the child, with "operation not permitted", and the test says so; with it, the helper reads a marker the child wrote |
| A seqpacket end reaches only its other end | On Linux. The test itself listens, outside the jail, on a socket of the seqpacket kind with a name inside a directory the jail shows. Control: from outside the jail a socket of that kind joins it and a marker arrives, which is read and set aside. Then inside the jail: the name is seen and is a socket; a pair is made and one end's message reaches the other; a send that names the listener arrives at the other end and nothing arrives at the listener; joining the listener is refused; the same two again after the other end is closed; and unjoining is refused. Every wait has a limit, and an error of the helper that is not one of those refusals fails the test |
| A named end of a pair takes no caller in | On Linux, for both kinds of pair the filter lets through (revision 3). Control, with no jail: a socket of the kind that is joined to nothing, given a name in the checkout and told to listen, listens, and takes in a caller of its own making and a caller from another process. Then an end of a pair, treated the same way, with no jail: the kernel says it does not listen; accepting is refused; a socket made for its name is refused; nothing has arrived at the end; and it still reaches its other end. All but that last again after the other end is closed. Then the same inside the jail, where the run itself can make no Unix socket to call with (which says nothing of the end): there the end is called from outside the jail, by a process with no jail, through its name in the checkout, before and after the other end is closed. That caller sees the name as a socket, and its joining is refused. Whether the kernel answers yes or "invalid" to the telling is not held; any other error fails the test |
| What was refused is still refused | Inside the jail, as now: a Unix socket by `socket`, a Unix datagram pair, and the keyring by one of its three calls. The other six of the seven calls are held by the filter's program run as the kernel would, not by a live try, and that is said where the tests are |
| The old items can be judged on Linux | On the second machine, by the lead, through the room's own check: for each of the three old items, a commit known to be right passes, and the base and the wrong commit fail |
| Both kinds of machine | The project's checks run the whole suite on x86-64 Linux, with the tests that need the room asked for, so the filter's tests and the jail's tests run there. The numbers for that kind of machine were checked by the reader against the kernel's table. A filter's program run as the kernel would is not a showing that the jail installs it there: the live tests are. Since revision 3 the jail's tests have also been run by hand on a second x86-64 machine, on a later kernel: the last section |

## What is not changed

- **macOS.** Its jail has no such filter.
- **Freezing.** That a check which cannot run freezes as one that says no is a limit, written down here
  and not mended here. The rule that stands in for a mend is in the run's own instructions, where whoever
  runs items will see it: section 6 of `2026-11-16-v2-a-route-offered.md`, under "Its reference", and the
  pilot's list in its section 7.
- **Any other part of the filter,** and how the jail shows files, the network or processes.

## What the reader named, and where it is made

| Named change | Where |
| --- | --- |
| 1. Correct the evidence claims: the cause is the way of starting a child that was seen, not every program of the toolchain; it is the leading cause until a controlled run; tests that exist are told from tests to be written; and the claim about reach rests on the kernel's source and not on tests alone | "What was found", from "The leading cause"; "Why this does not widen"; the first line under "How we know" |
| 2. Put the stopgap for freezing where a run's instructions are, with what is recorded | The route spec's section 6, "Its reference", and its section 7; pointed to under "What is not changed" |
| 3. Make the seqpacket test decisive: a listener of the same kind, a pair shown to work, and the cases after closing, unjoining and listening | The fourth row of "How we know" |

It also asked that the row on a program of ours be made to take the way that asks for the pair, that the
row on what is still refused say truly which calls are tried live, and that all three old items be shown.
Those are in their rows.

## What a second machine found (revision 3)

Another ship ran the jail's tests on a machine of its own: x86-64, kernel 7.0, with `bwrap` under its
distribution's own confinement, which the project's checks never meet because they turn it off. What it ran
is given here as it reported it; its output is on its machine and not in this repository. What the first
Linux machine (6.12, aarch64) printed was read by the author.

- **At the pushed mend, 23 of the jail's 24 tests were reported passed there,** among them the child
  started inside the jail. One failed, and in its control, with no jail at all: an end of a seqpacket pair,
  given a name and told to listen, was answered "yes", where the row above said it would be refused.
- **A probe in plain Python, run on both kernels, with no jail.** An end of a pair is given a name and told
  to listen; then a socket made for that name tries to join it.

  | What is tried | 6.12 (aarch64), as printed | 7.0 (x86-64), as reported |
  | --- | --- | --- |
  | Told to listen | Refused: "invalid" | Answered yes |
  | Does the kernel say it listens | No | No |
  | A socket made for the name joins it | Refused: "connection refused" | The same |
  | Accepting | Refused: "invalid" | The same |
  | What arrives at the end | Nothing | Nothing |
  | The end sends to its own other end, while that is open | Arrives | Arrives |

  On each kernel a stream pair and a seqpacket pair gave the same lines, with the other end open and with
  it closed.
- **So in these runs the yes was empty.** On 7.0 the telling was answered yes; after it the kernel said
  the end did not listen, and the socket made for its name was refused. No listening and no joining was
  seen on either kernel. That is what was observed, on one machine of each. It is not a reading of 7.0's
  source, and it does not say that no kernel will ever do otherwise.
- **It is the kernel's difference, not the mend's.** A stream pair, which the filter has let through from
  the first, answered the same way on each kernel.
- **The fault was in the test, and in the row's words.** The test held what the kernel answers, where it
  should have held what the answer leaves. The row said listening "needs an end that is not joined", which
  was a reading of one version. The test did what this spec says tests are for, and failed when a kernel
  behaved otherwise.
- **The same test's tries inside the jail, on that machine,** run by themselves: but for the answer to the
  telling they were reported as on the first machine. A Unix socket could not be made, joining was
  refused, and accepting was refused.
- **The old rule, tried there.** With the filter made to refuse a seqpacket pair again, the child started
  inside the jail was reported to fail on that machine as it did on the first. So the fault this spec is
  about, and its mend, are each shown by a live run on both kinds of machine.
- **The whole suite at the pushed mend, on that machine:** 512 tests reported passed and 1 failed, the one
  above, with none ignored.

**What it would mean if an end did listen.** The run itself could not call it: the filter keeps a run from
making a Unix socket. But the checkout and the scratch are directories of the machine's own, so anything
outside the jail that can reach the name could join it, and hand the run bytes, or an open file, which the
run did not hold. Nothing outside does so today, and on these kernels nothing could. It is why the test
below calls the jailed end from outside the jail, and does not rest on the run being unable to call itself.

**What was changed.** The tries at listening left the seqpacket test, and a test of their own holds what
must hold on any kernel, for both kinds of pair: the row "A named end of a pair takes no caller in" under
"How we know". It has a control that shows its lines can tell an end that listens from one that does not,
and it calls the jailed end from outside. The filter's opening comment no longer says a joined end cannot
be made to listen, and says truly what a send that names another socket does from each kind of end. With
the change the jail's 25 tests pass on 6.12 (aarch64).

**What was not changed: the filter.** It is given a call's number and its arguments as numbers. It cannot
see what kind of socket a descriptor is, nor read the address a call points at. And a run may listen on its
own empty network, as some of the tests it is there to run do. So it cannot refuse the telling for this
kind of socket alone, and refusing it for every kind would take from a run what the jail is there to let it
do. That a named end of a pair takes no caller in is the kernel's doing, and is tried by a test on every
machine the jail's tests run on.

**What this does not show.**

- Why 7.0 answers yes. Its source was not read. The corrected row rests on runs on one machine of each
  kernel, not on a reading of the later one.
- The other rows on 7.0 by reading. They are held there by the tests that try them, reported passed.
- Any kernel but these two.
- A caller from outside that reaches a listener inside the jail. There is none to make: nothing inside can
  make a Unix socket that listens. The control is a listener with no jail, in the same directory.
- The stream kind's own tries at reaching out. A send that names a listener, joining one, unjoining, and
  the same after the other end is closed are tried for the seqpacket kind against a listener of that kind.
  The stream kind, let through from the first, has no such test against a stream listener. This revision's
  reader named it; it is not made here.
- An open file handed across a pair, which no test tries.
