# A program inside the Linux jail cannot start a child: the cause, and the mend

Serenity, 2026-11-16. Not yet read. It changes the jail's boundary by one kind of socket pair, so a fresh
reader of the other family reads it as a change to the boundary before any code is written, and reads the
code again before it is pushed.

## What was found

"Ready to test" asks for one turn with a block on a second machine. On the second machine (Linux, aarch64)
the turn was given the block, the same bytes as on the first, and the worker's commit was right: run by
hand, outside the jail, the item's check passed all 23 of its cases. The room failed the turn. Its check
had ended in two seconds.

What the room keeps of a check is its exit code and a hash of its output, so the cause was found with
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

**So a program built with this toolchain cannot start another program inside the Linux jail.** Before it
starts a child it makes a Unix pair of the seqpacket kind, and the filter refuses that. The lead has not
read the standard library's source, which is not installed here: what is shown is the trace, the filter's
rule and the refusal. `cargo` is one such program. `yak` is another, wherever it runs git. A shell is not:
it starts its children without a socket.

**Why it was not seen.** No test runs, inside the Linux jail, a program of ours that starts a child:
checks in the tests are shell scripts. The first run and the pilot were on macOS, whose jail has no such
filter. A model worker's own shell is not inside the room's jail.

**What it costs as it stands.** On Linux the room cannot judge an item whose check builds or runs Rust:
the three old items, and any item of the v2 crates. And freezing an item does not notice: a check that
cannot run fails on the base and on the wrong commit, which is all that freezing asks, so the item
freezes and then every turn at it fails, right or wrong.

## The mend

**The filter lets through a Unix pair of the stream kind or of the seqpacket kind.** Nothing else
changes: a datagram pair is still refused, and a pair of any other family; `socket` is as it was, with no
Unix socket; the seven calls refused outright; the other numbering.

**Why this is held not to widen what a run can reach,** which is what the reader is asked to press on:

- The filter's reason for refusing a datagram pair is that one end could be sent from to a named socket:
  a socket file inside a directory the jail shows, where some service of the machine listens.
- A seqpacket pair, like a stream pair, is two ends joined to each other when it is made. The claim is
  that neither end can be made to reach anything else: a send that names another socket goes to the
  joined end or is refused, and an end that is joined cannot be joined to a named socket.
- That claim is shown by tests inside the jail, and not taken from reading the kernel.
- What a pair of either kind can carry between its two ends (open files among it) is the same for both
  kinds, and both ends are inside the jail.

## How we know

Each row has a case that must pass and a case that must be refused.

| What | Shown by |
| --- | --- |
| The filter's program | Run as the kernel would, for both kinds of machine: a Unix seqpacket pair is let through with any flags; a Unix datagram pair, and a seqpacket pair of another family, are refused; every case the tests held before holds unchanged |
| A program of ours starts a child inside the jail | On Linux, inside the jail, a program built with this toolchain starts another and reads what it wrote. Without the mend the same test fails |
| A seqpacket end reaches only its other end | On Linux, inside the jail, with a socket listening by name inside a directory the jail shows: from one end of a seqpacket pair, a send that names that socket does not arrive there, and a try at joining that socket is refused. The control: outside the jail the same listener is reached by a socket made for it, so the listener was there to be reached |
| What was refused is still refused | Inside the jail: a Unix socket by `socket`, a Unix datagram pair, and each of the seven calls, as the tests have them now |
| The old items can be judged on Linux | On the second machine, by the lead: the turn's right commit passes its check inside the jail, and the base and the wrong commit still fail it |
| Both kinds of machine | The filter's tests and the jail's tests run in the project's checks on x86-64 Linux, where the numbers come from the published table |

## What is not changed

- **macOS.** Its jail has no such filter.
- **Freezing.** That a check which cannot run freezes as one that says no is a limit, written down here
  and not mended here. Until it is: before an item is used on a machine, a commit known to be right is
  shown to pass that item's check through the room's jail on that machine. For the items made from merged
  commits, that is each item's reference.
- **Any other part of the filter,** and how the jail shows files, the network or processes.
