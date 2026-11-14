//! Process identities and bounded cleanup of a run's observed descendants.

use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::Read;
use std::path::Path;
use std::process::Stdio;
use std::thread;
use std::time::{Duration, Instant};

use crate::sandbox::scrubbed;
use crate::{TurnError, io};

pub(crate) const SUPERVISION_POLL: Duration = Duration::from_millis(200);
const CLEANUP_LIMIT: Duration = Duration::from_secs(3);

/// A run as its pid file records it: the leader's group and start time, then every other process the run was
/// seen to start, each with its own start time. A process number alone says nothing once it has been given to
/// another process; with the start time it names one process.
///
/// The others are kept because a clock that dies takes its memory with it. A child that was seen for a while
/// and then left the group and lost its parent can no longer be found from the leader, and after a crash the
/// record is all that is left to end it by.
pub(crate) struct Identity {
    pub group: u32,
    pub start: String,
    pub others: Vec<(u32, String)>,
}

impl Identity {
    /// The group, a line end, the leader's start time, a line end, then one line for each other process: its
    /// number, a space, its start time.
    pub fn text(&self) -> String {
        let mut text = format!("{}\n{}\n", self.group, self.start);
        for (pid, start) in &self.others {
            text.push_str(&format!("{pid} {start}\n"));
        }
        text
    }

    pub fn read(path: &Path) -> Result<Option<Self>, TurnError> {
        let content = match fs::read_to_string(path) {
            Ok(content) => content,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(io("read the run identity")(e)),
        };
        let number = |text: &str| {
            text.parse::<u32>()
                .ok()
                .filter(|&p| p > 1 && p <= i32::MAX as u32)
        };
        let invalid = || TurnError::Refused("invalid run identity".into());
        let mut lines = content.lines();
        let (Some(group), Some(start)) = (lines.next(), lines.next()) else {
            return Err(invalid());
        };
        if start.is_empty() {
            return Err(invalid());
        }
        let group = number(group).ok_or_else(|| TurnError::Refused("invalid run group".into()))?;
        let mut others = Vec::new();
        for line in lines {
            let (pid, start) = line.split_once(' ').ok_or_else(invalid)?;
            let pid = number(pid).ok_or_else(invalid)?;
            if start.is_empty() {
                return Err(invalid());
            }
            others.push((pid, start.to_string()));
        }
        Ok(Some(Self {
            group,
            start: start.into(),
            others,
        }))
    }
}

pub(crate) fn marker() -> Result<String, TurnError> {
    let mut bytes = [0; 16];
    fs::File::open("/dev/urandom")
        .map_err(io("open random source"))?
        .read_exact(&mut bytes)
        .map_err(io("read run randomness"))?;
    Ok(crate::check::hex(&bytes))
}

struct Process {
    pid: u32,
    parent: u32,
    group: u32,
    start: String,
}

pub(crate) struct Supervisor {
    pub identity: Identity,
    seen: HashMap<u32, String>,
    last_poll: Instant,
    best_effort: bool,
}

impl Supervisor {
    pub fn start(group: u32) -> Result<Self, TurnError> {
        match snapshot(None) {
            Ok(processes) => {
                let leader = processes
                    .iter()
                    .find(|p| p.pid == group)
                    .ok_or_else(|| TurnError::Io("the run has no live leader".into()))?;
                let mut supervisor = Self::new(Identity {
                    group,
                    start: leader.start.clone(),
                    others: Vec::new(),
                });
                supervisor.learn(&processes);
                Ok(supervisor)
            }
            Err(_) if crate::sandbox::supervision_is_best_effort() => Ok(Self {
                identity: Identity {
                    group,
                    start: "unverified".into(),
                    others: Vec::new(),
                },
                seen: HashMap::new(),
                last_poll: Instant::now(),
                best_effort: true,
            }),
            Err(e) => Err(e),
        }
    }

    fn new(identity: Identity) -> Self {
        let mut seen = HashMap::from([(identity.group, identity.start.clone())]);
        seen.extend(identity.others.iter().cloned());
        Self {
            identity,
            seen,
            last_poll: Instant::now(),
            best_effort: false,
        }
    }

    /// A supervisor for a run a dead clock left, from its record. Returns none when no process the record
    /// names is still the process it was: then there is nothing of that run to end. The leader need not be
    /// among those left; a child it started may have outlived it.
    pub fn recover(identity: Identity) -> Result<Option<Self>, TurnError> {
        let processes = snapshot(None)?;
        let mut supervisor = Self::new(identity);
        if !processes
            .iter()
            .any(|p| supervisor.seen.get(&p.pid) == Some(&p.start))
        {
            return Ok(None);
        }
        supervisor.learn(&processes);
        Ok(Some(supervisor))
    }

    /// The run as its pid file should record it now: the leader, and every other process seen so far.
    pub fn record(&self) -> Identity {
        let mut others: Vec<(u32, String)> = self
            .seen
            .iter()
            .filter(|(pid, _)| **pid != self.identity.group)
            .map(|(pid, start)| (*pid, start.clone()))
            .collect();
        others.sort();
        Identity {
            group: self.identity.group,
            start: self.identity.start.clone(),
            others,
        }
    }

    /// Takes in what is running now, and says whether the record changed: a process seen for the first time, or
    /// a number that now belongs to another process than the one recorded under it.
    fn learn(&mut self, processes: &[Process]) -> bool {
        let mut changed = false;
        let anchored = processes
            .iter()
            .any(|p| p.pid == self.identity.group && p.start == self.identity.start);
        let mut roots: HashSet<u32> = processes
            .iter()
            .filter(|p| self.seen.get(&p.pid) == Some(&p.start))
            .map(|p| p.pid)
            .collect();
        loop {
            let before = roots.len();
            for p in processes {
                if roots.contains(&p.parent) || (anchored && p.group == self.identity.group) {
                    roots.insert(p.pid);
                    changed |= self.seen.insert(p.pid, p.start.clone()).as_ref() != Some(&p.start);
                }
            }
            if roots.len() == before {
                break;
            }
        }
        changed
    }

    /// Looks at the processes again when it is time to, and says whether the record changed, so that the caller
    /// can write it anew.
    pub fn poll(&mut self) -> Result<bool, TurnError> {
        self.poll_with(|| snapshot(None))
    }

    /// `poll`, with the look at the machine's processes given: a test gives a list it made up.
    fn poll_with(
        &mut self,
        look: impl FnOnce() -> Result<Vec<Process>, TurnError>,
    ) -> Result<bool, TurnError> {
        if self.best_effort || self.last_poll.elapsed() < SUPERVISION_POLL {
            return Ok(false);
        }
        let changed = self.learn(&look()?);
        self.last_poll = Instant::now();
        Ok(changed)
    }

    /// Confirms each recorded identity before signalling and confirms all recorded live processes are gone.
    pub fn end(&mut self) -> Result<bool, TurnError> {
        if self.best_effort {
            return Ok(false);
        }
        let deadline = Instant::now() + CLEANUP_LIMIT;
        let mut ended = false;
        let mut signal = "TERM";
        loop {
            let processes = snapshot(None)?;
            self.learn(&processes);
            let remaining: Vec<_> = processes
                .iter()
                .filter(|p| self.seen.get(&p.pid) == Some(&p.start))
                .collect();
            if remaining.is_empty() {
                return Ok(ended);
            }
            if Instant::now() >= deadline {
                return Err(TurnError::Io(
                    "recorded run processes remain after cleanup".into(),
                ));
            }
            for p in remaining {
                if snapshot(Some(p.pid))?
                    .iter()
                    .any(|current| current.start == p.start)
                {
                    let status = scrubbed("kill")
                        .args(["-s", signal, "--", &p.pid.to_string()])
                        .stdin(Stdio::null())
                        .stdout(Stdio::null())
                        .stderr(Stdio::null())
                        .status()
                        .map_err(io("signal a run process"))?;
                    ended |= status.success();
                }
            }
            thread::sleep(SUPERVISION_POLL);
            signal = "KILL";
        }
    }
}

fn snapshot(pid: Option<u32>) -> Result<Vec<Process>, TurnError> {
    let mut command = scrubbed("ps");
    command.env("LC_ALL", "C");
    command.args(["-o", "pid=,ppid=,pgid=,lstart="]);
    if let Some(pid) = pid {
        command.args(["-p", &pid.to_string()]);
    } else {
        command.arg("-A");
    }
    let output = command
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .map_err(io("inspect processes"))?;
    if !output.status.success()
        && !(pid.is_some() && output.status.code() == Some(1) && output.stdout.is_empty())
    {
        return Err(TurnError::Io("process inspection is unavailable".into()));
    }
    let text = String::from_utf8_lossy(&output.stdout);
    text.lines()
        .map(|line| {
            let fields: Vec<_> = line.split_whitespace().collect();
            let invalid = || TurnError::Io("invalid process identity listing".into());
            if fields.len() != 8 {
                return Err(invalid());
            }
            Ok(Process {
                pid: fields[0].parse().map_err(|_| invalid())?,
                parent: fields[1].parse().map_err(|_| invalid())?,
                group: fields[2].parse().map_err(|_| invalid())?,
                start: fields[3..].join(" "),
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn process(pid: u32, parent: u32, group: u32, start: &str) -> Process {
        Process {
            pid,
            parent,
            group,
            start: start.into(),
        }
    }

    #[test]
    fn observed_descendants_keep_their_identity_after_parent_and_group_changes() {
        let mut supervisor = Supervisor::new(Identity {
            group: 10,
            start: "leader".into(),
            others: Vec::new(),
        });
        supervisor.learn(&[
            process(12, 11, 12, "grandchild"),
            process(11, 10, 11, "child"),
            process(10, 1, 10, "leader"),
        ]);
        assert_eq!(supervisor.seen.len(), 3);
        supervisor.learn(&[
            process(11, 1, 11, "child"),
            process(12, 1, 12, "grandchild"),
            process(13, 12, 13, "later"),
        ]);
        assert_eq!(supervisor.seen.get(&13).map(String::as_str), Some("later"));
    }

    #[test]
    fn a_changed_process_identity_is_never_an_ancestry_root() {
        let mut supervisor = Supervisor::new(Identity {
            group: 10,
            start: "leader".into(),
            others: Vec::new(),
        });
        supervisor.learn(&[
            process(10, 1, 10, "different"),
            process(11, 10, 10, "other"),
        ]);
        assert_eq!(supervisor.seen.len(), 1);
        assert_eq!(supervisor.seen.get(&10).map(String::as_str), Some("leader"));
    }

    #[test]
    fn a_record_keeps_every_process_seen_and_reads_back_the_same() {
        let path = std::env::temp_dir().join(format!("yak-record-{}", std::process::id()));
        let mut supervisor = Supervisor::new(Identity {
            group: 10,
            start: "Sat Nov 14 12:00:00 2026".into(),
            others: Vec::new(),
        });
        supervisor.learn(&[
            process(10, 1, 10, "Sat Nov 14 12:00:00 2026"),
            process(11, 10, 10, "Sat Nov 14 12:00:01 2026"),
            process(12, 11, 12, "Sat Nov 14 12:00:02 2026"),
        ]);
        let record = supervisor.record();
        assert_eq!(
            record.text(),
            "10\nSat Nov 14 12:00:00 2026\n11 Sat Nov 14 12:00:01 2026\n12 Sat Nov 14 12:00:02 2026\n"
        );
        fs::write(&path, record.text()).unwrap();
        let read = Identity::read(&path).unwrap().unwrap();
        fs::remove_file(&path).unwrap();
        assert_eq!(
            (read.group, read.start.as_str()),
            (10, "Sat Nov 14 12:00:00 2026")
        );
        assert_eq!(read.others, record.others);
        // A supervisor made from the record knows all three again, with no process list to learn from.
        let recovered = Supervisor::new(read);
        assert_eq!(recovered.seen.len(), 3);
        assert_eq!(
            recovered.seen.get(&12).map(String::as_str),
            Some("Sat Nov 14 12:00:02 2026")
        );
    }

    #[test]
    fn a_record_that_is_not_one_is_refused() {
        let path = std::env::temp_dir().join(format!("yak-bad-record-{}", std::process::id()));
        for bad in [
            "",
            "10",
            "10\n",
            "10\n\n",
            "1\nstart\n",
            "0\nstart\n",
            "ten\nstart\n",
            "10\nstart\n11\n",
            "10\nstart\n11 \n",
            "10\nstart\nx start\n",
            "10\nstart\n1 start\n",
            "10\nstart\n4294967296 start\n",
        ] {
            fs::write(&path, bad).unwrap();
            assert!(Identity::read(&path).is_err(), "{bad:?} was taken");
        }
        fs::write(&path, "10\nstart\n").unwrap();
        assert!(Identity::read(&path).unwrap().unwrap().others.is_empty());
        fs::remove_file(&path).unwrap();
        assert!(Identity::read(&path).unwrap().is_none());
    }

    /// A process number can be given again within one run: a child ends, and a later child gets its number. The
    /// count of processes seen is then what it was, and the record still has to change, since it names the
    /// later one by a start time that is no longer true.
    #[test]
    fn a_number_given_to_a_later_process_counts_as_something_new() {
        let mut supervisor = Supervisor::new(Identity {
            group: 10,
            start: "leader".into(),
            others: Vec::new(),
        });
        assert!(supervisor.learn(&[process(10, 1, 10, "leader"), process(11, 10, 10, "first"),]));
        // Nothing new: the same two again.
        assert!(!supervisor.learn(&[process(10, 1, 10, "leader"), process(11, 10, 10, "first"),]));
        // The same number, another process.
        assert!(supervisor.learn(&[process(10, 1, 10, "leader"), process(11, 10, 10, "second"),]));
        assert_eq!(supervisor.record().others, [(11, "second".to_string())]);
    }

    /// The same through `poll`, which is what a run asks: it answers with what `learn` found, and not with
    /// whether more processes are known than before.
    #[test]
    fn a_poll_says_the_record_changed_when_a_number_went_to_a_later_process() {
        let mut supervisor = Supervisor::new(Identity {
            group: 10,
            start: "leader".into(),
            others: Vec::new(),
        });
        let look = |supervisor: &mut Supervisor, child: &str| {
            // As if it were time to look again.
            supervisor.last_poll = Instant::now() - SUPERVISION_POLL;
            let list = vec![process(10, 1, 10, "leader"), process(11, 10, 10, child)];
            supervisor.poll_with(|| Ok(list)).unwrap()
        };
        assert!(look(&mut supervisor, "first"));
        assert!(!look(&mut supervisor, "first"));
        // As many processes as before, and one of them another process.
        assert!(look(&mut supervisor, "second"));
        assert_eq!(supervisor.record().others, [(11, "second".to_string())]);
        // Before it is time to look again, nothing is looked at.
        supervisor.last_poll = Instant::now();
        let asked = supervisor.poll_with(|| panic!("looked too soon")).unwrap();
        assert!(!asked);
    }
}
