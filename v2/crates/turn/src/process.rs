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

pub(crate) struct Identity {
    pub group: u32,
    pub start: String,
}

impl Identity {
    pub fn text(&self) -> String {
        format!("{}\n{}\n", self.group, self.start)
    }

    pub fn read(path: &Path) -> Result<Option<Self>, TurnError> {
        let content = match fs::read_to_string(path) {
            Ok(content) => content,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(io("read the run identity")(e)),
        };
        let fields: Vec<_> = content.lines().collect();
        if fields.len() != 2 || fields[1].is_empty() {
            return Err(TurnError::Refused("invalid run identity".into()));
        }
        let group = fields[0]
            .parse::<u32>()
            .ok()
            .filter(|&p| p > 1 && p <= i32::MAX as u32)
            .ok_or_else(|| TurnError::Refused("invalid run group".into()))?;
        Ok(Some(Self {
            group,
            start: fields[1].into(),
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
                });
                supervisor.learn(&processes);
                Ok(supervisor)
            }
            Err(_) if crate::sandbox::supervision_is_best_effort() => Ok(Self {
                identity: Identity {
                    group,
                    start: "unverified".into(),
                },
                seen: HashMap::new(),
                last_poll: Instant::now(),
                best_effort: true,
            }),
            Err(e) => Err(e),
        }
    }

    fn new(identity: Identity) -> Self {
        let seen = HashMap::from([(identity.group, identity.start.clone())]);
        Self {
            identity,
            seen,
            last_poll: Instant::now(),
            best_effort: false,
        }
    }

    /// Returns no supervisor when the stored leader is absent or has a different identity.
    pub fn recover(identity: Identity) -> Result<Option<Self>, TurnError> {
        let processes = snapshot(None)?;
        if !processes
            .iter()
            .any(|p| p.pid == identity.group && p.start == identity.start)
        {
            return Ok(None);
        }
        let mut supervisor = Self::new(identity);
        supervisor.learn(&processes);
        Ok(Some(supervisor))
    }

    fn learn(&mut self, processes: &[Process]) {
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
                    self.seen.insert(p.pid, p.start.clone());
                }
            }
            if roots.len() == before {
                break;
            }
        }
    }

    pub fn poll(&mut self) -> Result<(), TurnError> {
        if !self.best_effort && self.last_poll.elapsed() >= SUPERVISION_POLL {
            self.learn(&snapshot(None)?);
            self.last_poll = Instant::now();
        }
        Ok(())
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
        });
        supervisor.learn(&[
            process(10, 1, 10, "different"),
            process(11, 10, 10, "other"),
        ]);
        assert_eq!(supervisor.seen.len(), 1);
        assert_eq!(supervisor.seen.get(&10).map(String::as_str), Some("leader"));
    }
}
