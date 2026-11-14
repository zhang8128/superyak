//! What the clock's tests share: a room beside a tiny repository whose items each want one answer file to say 42,
//! scripts for workers, fixed random numbers, and process probes.
#![allow(dead_code)]

use std::convert::Infallible;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread::{JoinHandle, sleep};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use room::{AttemptId, CheckOrigin, CheckSpec, ItemId, NewItem, Room};
use yak::clock::{ClockError, Event, Mode, Options, Outcome, run_with};

/// How many answer files the repository has, and so how many standard items it can hold.
pub const ANSWERS: usize = 4;

/// Random numbers that never pick a recheck (1 % RECHECK_ONE_IN != 0), and that always do.
pub const NEVER: u32 = 1;
pub const ALWAYS: u32 = 0;

/// A source of random numbers that always gives the same one.
pub struct Fixed(pub u32);

impl rand::TryRng for Fixed {
    type Error = Infallible;
    fn try_next_u32(&mut self) -> Result<u32, Infallible> {
        Ok(self.0)
    }
    fn try_next_u64(&mut self) -> Result<u64, Infallible> {
        Ok(u64::from(self.0))
    }
    fn try_fill_bytes(&mut self, dst: &mut [u8]) -> Result<(), Infallible> {
        dst.fill(0);
        Ok(())
    }
}

/// A worker that reports one Read of `answer1.txt` in the Claude stream format, writes 42 in every answer file,
/// and commits.
pub const FIX: &str = r#"#!/bin/sh
printf '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Read","input":{"file_path":"%s/answer1.txt"}}]}}\n' "$PWD"
printf '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1","content":"0"}]}}\n'
for f in answer*.txt; do echo 42 > "$f"; done
git commit -q -am fix
"#;

/// Runs git in `dir` with a fixed identity and no hooks; returns its trimmed stdout. Panics on failure.
pub fn git(dir: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_INDEX_FILE")
        .arg("-C")
        .arg(dir)
        .args([
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
        ])
        .args(args)
        .output()
        .expect("git runs");
    assert!(
        out.status.success(),
        "git {args:?} failed: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout)
        .unwrap()
        .trim_end()
        .to_string()
}

fn commit(dir: &Path, message: &str) -> String {
    git(dir, &["add", "-A"]);
    git(dir, &["commit", "-q", "-m", message]);
    git(dir, &["rev-parse", "HEAD"])
}

pub fn now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64
}

/// A room, and a repository with `check.sh` and `answer1.txt` to `answer4.txt`, each "0" at `base` and "41" at
/// `wrong`. Item `n` is "answer n is 42", checked by `sh check.sh n`, written by a person, from outside the room.
pub struct World {
    pub tmp: tempfile::TempDir,
    pub repo: PathBuf,
    pub base: String,
    pub wrong: String,
    pub room_dir: PathBuf,
    pub room: Room,
    pub items: Vec<ItemId>,
    /// The limit `run` gives the clock's own git, in seconds: the clock's usual one unless a test changes it.
    pub git_secs: u64,
    /// The time limit of each check added from here on, in seconds.
    pub check_secs: u32,
}

impl World {
    pub fn new(items: usize) -> World {
        assert!(items <= ANSWERS);
        let tmp = tempfile::tempdir().unwrap();
        let repo = tmp.path().join("repo");
        fs::create_dir(&repo).unwrap();
        git(&repo, &["init", "-q", "-b", "main"]);
        fs::write(
            repo.join("check.sh"),
            "#!/bin/sh\ngrep -qx 42 \"answer$1.txt\"\n",
        )
        .unwrap();
        let answers = |value: &str| {
            for n in 1..=ANSWERS {
                fs::write(repo.join(format!("answer{n}.txt")), format!("{value}\n")).unwrap();
            }
        };
        answers("0");
        let base = commit(&repo, "base");
        git(&repo, &["checkout", "-q", "-b", "wrong"]);
        answers("41");
        let wrong = commit(&repo, "wrong");
        git(&repo, &["checkout", "-q", "main"]);
        let room_dir = tmp.path().join("room");
        let room = Room::init(&room_dir).unwrap();
        let mut world = World {
            tmp,
            repo,
            base,
            wrong,
            room_dir,
            room,
            items: Vec::new(),
            git_secs: Options::default().git_secs,
            check_secs: 30,
        };
        for n in 1..=items {
            world.add(n);
        }
        world
    }

    /// Adds the standard item for answer `n`.
    pub fn add(&mut self, n: usize) -> ItemId {
        self.add_check(
            &format!("answer {n} is 42"),
            &format!("sh check.sh {n}"),
            &["check.sh"],
        )
    }

    pub fn add_check(&mut self, title: &str, command: &str, files: &[&str]) -> ItemId {
        let base = self.base.clone();
        self.add_at(title, command, files, &base)
    }

    pub fn add_at(&mut self, title: &str, command: &str, files: &[&str], base: &str) -> ItemId {
        let id = self
            .room
            .add_item(NewItem {
                title: title.to_string(),
                repo: self.repo.clone(),
                base_commit: base.to_string(),
                after: Vec::new(),
                check: CheckSpec {
                    command: command.to_string(),
                    files: files.iter().map(|f| f.to_string()).collect(),
                    timeout_secs: self.check_secs,
                    origin: CheckOrigin::Outside,
                    wrong_artifacts: vec![self.wrong.clone()],
                    written_by: "person:tester".to_string(),
                },
            })
            .unwrap();
        self.items.push(id.clone());
        id
    }

    /// Writes an executable script beside the repository and returns its worker name.
    pub fn script(&self, name: &str, body: &str) -> String {
        let dir = self.tmp.path().join("scripts");
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join(name);
        fs::write(&path, body).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
        format!("script:{}", path.display())
    }

    /// A path beside the repository that does not exist yet.
    pub fn scratch(&self, name: &str) -> PathBuf {
        self.tmp.path().join(name)
    }

    pub fn refs(&self) -> Vec<String> {
        git(&self.repo, &["for-each-ref", "--format=%(refname)"])
            .lines()
            .map(str::to_string)
            .collect()
    }

    /// The refs the clock made: `refs/heads/room/...`.
    pub fn room_refs(&self) -> Vec<String> {
        self.refs()
            .into_iter()
            .filter(|r| r.starts_with("refs/heads/room/"))
            .collect()
    }

    pub fn room_ref(&self, item: &ItemId, lease_no: u32) -> String {
        format!("refs/heads/room/{}/{lease_no}", item.0)
    }

    /// The names in the room's `turns/`, sorted; none when it does not exist.
    pub fn turns(&self) -> Vec<String> {
        let Ok(entries) = fs::read_dir(self.room_dir.join("turns")) else {
            return Vec::new();
        };
        let mut names: Vec<String> = entries
            .flatten()
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        names
    }

    /// Runs the clock with these workers and random numbers, polling every 100 ms, and returns what it said.
    pub fn run(
        &mut self,
        workers: &[&str],
        mode: Mode,
        rng: u32,
        turn_secs: u32,
    ) -> (Result<(), ClockError>, Vec<Event>) {
        self.run_hooked(workers, mode, rng, turn_secs, &mut |_| {})
    }

    /// `run`, calling `hook` with each event as the clock reports it, on the clock's own thread: a test changes
    /// the world there at a known point of a turn.
    pub fn run_hooked(
        &mut self,
        workers: &[&str],
        mode: Mode,
        rng: u32,
        turn_secs: u32,
        hook: &mut dyn FnMut(&Event),
    ) -> (Result<(), ClockError>, Vec<Event>) {
        let workers: Vec<String> = workers.iter().map(|w| w.to_string()).collect();
        let mut events = Vec::new();
        let mut report = |e: &Event| {
            hook(e);
            events.push(e.clone());
        };
        let result = run_with(
            &mut self.room,
            &workers,
            mode,
            &mut Fixed(rng),
            Options {
                turn_secs,
                poll: Duration::from_millis(100),
                report: Some(&mut report),
                git_secs: self.git_secs,
            },
        );
        (result, events)
    }
}

pub fn outcomes(events: &[Event]) -> Vec<Outcome> {
    events
        .iter()
        .filter_map(|e| match e {
            Event::Ended { outcome, .. } => Some(outcome.clone()),
            _ => None,
        })
        .collect()
}

/// Each turn started: its item, attempt, lease number and worker.
pub fn started(events: &[Event]) -> Vec<(ItemId, AttemptId, u32, String)> {
    events
        .iter()
        .filter_map(|e| match e {
            Event::Started {
                item,
                attempt,
                lease_no,
                worker,
            } => Some((item.clone(), attempt.clone(), *lease_no, worker.clone())),
            _ => None,
        })
        .collect()
}

/// Whether any process remains in this process group.
pub fn group_alive(group: u32) -> bool {
    Command::new("kill")
        .args(["-0", "--", &format!("-{group}")])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Polls `done` until it is true or `deadline` passes; returns its last answer.
pub fn wait_until(deadline: Instant, mut done: impl FnMut() -> bool) -> bool {
    loop {
        if done() {
            return true;
        }
        if Instant::now() >= deadline {
            return false;
        }
        sleep(Duration::from_millis(50));
    }
}

/// The process group a turn's pid file names: its first line. The second is the leader's start time.
fn group_in(path: &Path) -> Option<u32> {
    fs::read_to_string(path)
        .ok()
        .and_then(|text| text.lines().next().and_then(|line| line.parse().ok()))
}

/// Reads the process group from a turn's pid file, waiting until it holds one.
pub fn read_group(path: &Path, deadline: Instant) -> u32 {
    let mut group = None;
    assert!(
        wait_until(deadline, || {
            group = group_in(path);
            group.is_some()
        }),
        "no process group in {}",
        path.display()
    );
    group.unwrap()
}

/// Watches the room's `turns/` while a clock runs, and remembers every process group a pid file there named. A
/// worker in the jail cannot leave its own process id anywhere a test could read it afterwards; the pid file
/// is the room's own record of it.
pub struct Groups {
    done: Arc<AtomicBool>,
    watcher: JoinHandle<Vec<u32>>,
}

impl Groups {
    pub fn watch(turns: PathBuf) -> Groups {
        let done = Arc::new(AtomicBool::new(false));
        let stop = done.clone();
        let watcher = std::thread::spawn(move || {
            let mut seen = Vec::new();
            while !stop.load(Ordering::SeqCst) {
                for entry in fs::read_dir(&turns).into_iter().flatten().flatten() {
                    let path = entry.path();
                    if path.extension().is_some_and(|x| x == "pid")
                        && let Some(group) = group_in(&path)
                        && !seen.contains(&group)
                    {
                        seen.push(group);
                    }
                }
                sleep(Duration::from_millis(10));
            }
            seen
        });
        Groups { done, watcher }
    }

    /// Stops watching and returns the groups seen, in the order they appeared.
    pub fn seen(self) -> Vec<u32> {
        self.done.store(true, Ordering::SeqCst);
        self.watcher.join().unwrap()
    }
}

/// A process that leads its own group and is nobody's child here, as a run is whose clock has died: it was
/// started by a process that has already gone. Ended when this is dropped.
pub struct Orphan(pub u32);

impl Orphan {
    pub fn start() -> Orphan {
        // The first process leaves at once; the second leads a new session, says its id and closes its output,
        // so that reading it does not wait for the ten minutes.
        let out = Command::new("perl")
            .args([
                "-MPOSIX",
                "-e",
                "exit if fork; setsid(); $| = 1; print \"$$\\n\"; close STDOUT; close STDERR; close STDIN; sleep 600",
            ])
            .stdin(Stdio::null())
            .output()
            .expect("perl runs");
        let pid = String::from_utf8_lossy(&out.stdout)
            .trim()
            .parse()
            .expect("the orphan said its process id");
        Orphan(pid)
    }

    pub fn alive(&self) -> bool {
        Command::new("kill")
            .args(["-0", "--", &self.0.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }
}

impl Drop for Orphan {
    fn drop(&mut self) {
        let _ = Command::new("kill")
            .args(["-9", "--", &self.0.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}

/// The start time of process `pid` as the room records it in a pid file: `ps`'s `lstart`, single-spaced.
pub fn started_at(pid: u32) -> String {
    let out = Command::new("ps")
        .env("LC_ALL", "C")
        .args(["-o", "lstart=", "-p", &pid.to_string()])
        .output()
        .expect("ps runs");
    let text = String::from_utf8_lossy(&out.stdout);
    let start = text.split_whitespace().collect::<Vec<_>>().join(" ");
    assert!(!start.is_empty(), "no start time for process {pid}");
    start
}

/// The room's store held against every writer, as a store that has failed looks to a clock: another program
/// takes the database's write lock and keeps it, so the clock's next write waits out its patience and fails.
/// Readers are not held up. Let go when this is dropped.
pub struct StoreHeld(std::process::Child);

impl StoreHeld {
    pub fn hold(room_dir: &Path) -> StoreHeld {
        let taken = room_dir.with_file_name(format!(
            "store-held-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .subsec_nanos()
        ));
        let script = "import sqlite3, sys, time\n\
                      held = sqlite3.connect(sys.argv[1], isolation_level=None, timeout=30)\n\
                      held.execute('BEGIN IMMEDIATE')\n\
                      open(sys.argv[2], 'w').close()\n\
                      time.sleep(120)\n";
        let child = Command::new("python3")
            .args(["-I", "-c", script])
            .arg(room_dir.join("room.sqlite3"))
            .arg(&taken)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("python3 runs");
        assert!(
            wait_until(Instant::now() + Duration::from_secs(40), || taken.exists()),
            "the store's write lock was not taken"
        );
        StoreHeld(child)
    }
}

impl Drop for StoreHeld {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
