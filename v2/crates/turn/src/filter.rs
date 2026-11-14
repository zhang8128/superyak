//! The system-call filter the Linux jail gives `bwrap`.
//!
//! `bwrap` gives a run its own network, but a Unix socket is a file. One that lies inside anything the jail
//! shows (a named tool directory, say, where some service of the machine listens) can be connected to from
//! inside, whatever the network is, and a mount that is read-only does not stop it. So a jailed run is not
//! given the means: it cannot make a Unix socket.
//!
//! What the filter refuses, with "operation not permitted":
//!
//! - `socket` for the Unix family;
//! - `socketpair` for the Unix family, except a stream pair. A stream pair is two ends joined to each other and
//!   can reach nothing else; programs use one to talk to their own children. A datagram end could be sent
//!   from to a named socket;
//! - `io_uring_setup`: that interface can make sockets too, and a filter of system calls does not see what
//!   it does.
//!
//! A call made through another kind of machine's numbering (32-bit calls on a 64-bit machine) ends the process:
//! the numbers below would mean other calls there.
//!
//! The program is in the form the kernel takes: eight bytes an instruction. It is built from named steps and
//! jumps to labels, and `tests` runs it as the kernel would, so a jump that lands in the wrong place is found
//! on any machine.

/// The numbers of one kind of machine.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Machine {
    /// How the kernel names this kind of machine to a filter.
    pub arch: u32,
    pub socket: u32,
    pub socketpair: u32,
    pub io_uring_setup: u32,
    /// Whether calls numbered from this value up are another numbering on the same machine (x32).
    pub other_numbering_from: Option<u32>,
}

pub(crate) const AARCH64: Machine = Machine {
    arch: 0xC000_00B7,
    socket: 198,
    socketpair: 199,
    io_uring_setup: 425,
    other_numbering_from: None,
};

pub(crate) const X86_64: Machine = Machine {
    arch: 0xC000_003E,
    socket: 41,
    socketpair: 53,
    io_uring_setup: 425,
    other_numbering_from: Some(0x4000_0000),
};

/// The numbers of the machine this was built for, if they are known here. With none, there is no Linux jail.
pub(crate) fn this_machine() -> Option<Machine> {
    if !cfg!(target_endian = "little") {
        return None;
    }
    if cfg!(target_arch = "aarch64") {
        Some(AARCH64)
    } else if cfg!(target_arch = "x86_64") {
        Some(X86_64)
    } else {
        None
    }
}

const UNIX_FAMILY: u32 = 1;
const STREAM: u32 = 1;
/// The part of a socket's type that says which kind it is; the rest are flags.
const KIND_OF_TYPE: u32 = 0xf;

const ALLOW: u32 = 0x7fff_0000;
/// Refuse the call with "operation not permitted".
const REFUSE: u32 = 0x0005_0000 | 1;
const END_THE_PROCESS: u32 = 0x8000_0000;

// Where things are in what the kernel shows a filter: the call's number, the kind of machine, then the
// arguments, eight bytes each, low half first.
const AT_NUMBER: u32 = 0;
const AT_ARCH: u32 = 4;
const AT_FIRST: u32 = 16;
const AT_SECOND: u32 = 24;

#[derive(Clone, Copy)]
enum To {
    Next,
    Label(&'static str),
}

#[derive(Clone, Copy)]
enum Step {
    /// Load the four bytes at this place.
    Load(u32),
    /// Keep only these bits of what is loaded.
    Mask(u32),
    /// Go one way if what is loaded equals the value, the other way if not.
    IfEqual(u32, To, To),
    /// Go one way if what is loaded is this value or more, the other way if not.
    IfAtLeast(u32, To, To),
    /// Answer with this.
    Answer(u32),
}

/// The filter for `machine`, as bytes.
pub(crate) fn socket_filter(machine: Machine) -> Vec<u8> {
    use Step::*;
    use To::*;
    let mut steps: Vec<(Option<&'static str>, Step)> = vec![
        (None, Load(AT_ARCH)),
        (None, IfEqual(machine.arch, Next, Label("end"))),
        (None, Load(AT_NUMBER)),
    ];
    if let Some(from) = machine.other_numbering_from {
        steps.push((None, IfAtLeast(from, Label("end"), Next)));
    }
    steps.extend([
        (None, IfEqual(machine.io_uring_setup, Label("refuse"), Next)),
        (None, IfEqual(machine.socket, Label("socket"), Next)),
        (
            None,
            IfEqual(machine.socketpair, Label("pair"), Label("allow")),
        ),
        (Some("socket"), Load(AT_FIRST)),
        (None, IfEqual(UNIX_FAMILY, Label("refuse"), Label("allow"))),
        (Some("pair"), Load(AT_FIRST)),
        (None, IfEqual(UNIX_FAMILY, Next, Label("allow"))),
        (None, Load(AT_SECOND)),
        (None, Mask(KIND_OF_TYPE)),
        (None, IfEqual(STREAM, Label("allow"), Label("refuse"))),
        (Some("refuse"), Answer(REFUSE)),
        (Some("end"), Answer(END_THE_PROCESS)),
        (Some("allow"), Answer(ALLOW)),
    ]);
    assemble(&steps)
}

/// Turns steps into the kernel's form. A jump is a count of instructions to skip, forwards only.
fn assemble(steps: &[(Option<&'static str>, Step)]) -> Vec<u8> {
    let skip = |from: usize, to: To| -> u8 {
        let target = match to {
            To::Next => from + 1,
            To::Label(name) => steps
                .iter()
                .position(|(label, _)| *label == Some(name))
                .expect("every label a step names is there"),
        };
        let distance = target
            .checked_sub(from + 1)
            .expect("a filter jumps forwards only");
        u8::try_from(distance).expect("a filter's jump is short")
    };
    let mut bytes = Vec::with_capacity(steps.len() * 8);
    for (index, (_, step)) in steps.iter().enumerate() {
        let (code, yes, no, value): (u16, u8, u8, u32) = match *step {
            Step::Load(at) => (0x20, 0, 0, at),
            Step::Mask(bits) => (0x54, 0, 0, bits),
            Step::IfEqual(value, yes, no) => (0x15, skip(index, yes), skip(index, no), value),
            Step::IfAtLeast(value, yes, no) => (0x35, skip(index, yes), skip(index, no), value),
            Step::Answer(answer) => (0x06, 0, 0, answer),
        };
        bytes.extend(code.to_le_bytes());
        bytes.push(yes);
        bytes.push(no);
        bytes.extend(value.to_le_bytes());
    }
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A call as the kernel shows it to a filter.
    struct Call {
        arch: u32,
        number: u32,
        first: u64,
        second: u64,
    }

    /// Runs a filter the way the kernel does and returns its answer. It knows the five kinds of instruction a
    /// filter here is made of, and refuses to run anything else.
    fn run(filter: &[u8], call: &Call) -> u32 {
        assert_eq!(filter.len() % 8, 0);
        let mut seen = [0u8; 64];
        seen[0..4].copy_from_slice(&call.number.to_le_bytes());
        seen[4..8].copy_from_slice(&call.arch.to_le_bytes());
        seen[16..24].copy_from_slice(&call.first.to_le_bytes());
        seen[24..32].copy_from_slice(&call.second.to_le_bytes());
        let count = filter.len() / 8;
        let (mut at, mut loaded) = (0usize, 0u32);
        for _ in 0..count {
            let i = &filter[at * 8..at * 8 + 8];
            let code = u16::from_le_bytes([i[0], i[1]]);
            let (yes, no) = (usize::from(i[2]), usize::from(i[3]));
            let value = u32::from_le_bytes([i[4], i[5], i[6], i[7]]);
            at += 1;
            match code {
                0x20 => {
                    let place = value as usize;
                    loaded = u32::from_le_bytes(seen[place..place + 4].try_into().unwrap());
                }
                0x54 => loaded &= value,
                0x15 => at += if loaded == value { yes } else { no },
                0x35 => at += if loaded >= value { yes } else { no },
                0x06 => return value,
                other => panic!("an instruction this test does not know: {other:#x}"),
            }
            assert!(at < count, "the filter ran off its end");
        }
        panic!("the filter never answered");
    }

    const INTERNET_FAMILY: u64 = 2;
    const DATAGRAM: u64 = 2;
    const SEQUENCED: u64 = 5;
    const CLOSE_ON_EXEC: u64 = 0o2_000_000;
    const NOT_BLOCKING: u64 = 0o4_000;

    #[test]
    fn the_filter_refuses_a_unix_socket_and_allows_what_a_program_needs() {
        for machine in [AARCH64, X86_64] {
            let filter = socket_filter(machine);
            let answer = |number: u32, first: u64, second: u64| {
                run(
                    &filter,
                    &Call {
                        arch: machine.arch,
                        number,
                        first,
                        second,
                    },
                )
            };
            let unix = u64::from(UNIX_FAMILY);
            let stream = u64::from(STREAM);
            // No Unix socket of any kind, whatever flags ride on the type.
            for kind in [stream, DATAGRAM, SEQUENCED, stream | CLOSE_ON_EXEC] {
                assert_eq!(answer(machine.socket, unix, kind), REFUSE);
            }
            // The family is the low half of the argument: the kernel reads no more of it.
            assert_eq!(answer(machine.socket, unix | (7 << 32), stream), REFUSE);
            // An internet socket is the network's business, and the jail has none.
            assert_eq!(answer(machine.socket, INTERNET_FAMILY, stream), ALLOW);
            // A stream pair, with or without flags, and no other pair.
            for flags in [0, CLOSE_ON_EXEC, NOT_BLOCKING, CLOSE_ON_EXEC | NOT_BLOCKING] {
                assert_eq!(answer(machine.socketpair, unix, stream | flags), ALLOW);
                assert_eq!(answer(machine.socketpair, unix, DATAGRAM | flags), REFUSE);
                assert_eq!(answer(machine.socketpair, unix, SEQUENCED | flags), REFUSE);
            }
            assert_eq!(answer(machine.socketpair, INTERNET_FAMILY, DATAGRAM), ALLOW);
            assert_eq!(answer(machine.io_uring_setup, 0, 0), REFUSE);
            // Everything else goes through, also with arguments that look like the ones refused.
            for number in [0, 1, 63, 64, 221, machine.socket + 2, 424, 426] {
                if [machine.socket, machine.socketpair, machine.io_uring_setup].contains(&number) {
                    continue;
                }
                assert_eq!(answer(number, unix, DATAGRAM), ALLOW, "call {number}");
            }
        }
    }

    #[test]
    fn a_call_in_another_machines_numbering_ends_the_process() {
        for (machine, other) in [(AARCH64, X86_64), (X86_64, AARCH64)] {
            let filter = socket_filter(machine);
            // The other machine's number for "write" must not slip past as this machine's "socket".
            let call = Call {
                arch: other.arch,
                number: 1,
                first: 0,
                second: 0,
            };
            assert_eq!(run(&filter, &call), END_THE_PROCESS);
            // 32-bit calls on a 64-bit machine of the same family.
            let call = Call {
                arch: 0x4000_0003,
                number: 359,
                first: u64::from(UNIX_FAMILY),
                second: DATAGRAM,
            };
            assert_eq!(run(&filter, &call), END_THE_PROCESS);
        }
        // The second numbering of x86-64 itself.
        let filter = socket_filter(X86_64);
        for number in [0x4000_0000, 0x4000_0000 + X86_64.socket, u32::MAX] {
            let call = Call {
                arch: X86_64.arch,
                number,
                first: u64::from(UNIX_FAMILY),
                second: DATAGRAM,
            };
            assert_eq!(run(&filter, &call), END_THE_PROCESS, "call {number:#x}");
        }
    }

    #[test]
    fn every_jump_goes_forwards_and_lands_inside() {
        for machine in [AARCH64, X86_64] {
            let filter = socket_filter(machine);
            let count = filter.len() / 8;
            for (index, i) in filter.chunks(8).enumerate() {
                let code = u16::from_le_bytes([i[0], i[1]]);
                if code == 0x15 || code == 0x35 {
                    for skip in [i[2], i[3]] {
                        assert!(index + 1 + usize::from(skip) < count);
                    }
                }
            }
            // The last instruction answers, so no path runs off the end.
            assert_eq!(filter[(count - 1) * 8], 0x06);
        }
    }
}
