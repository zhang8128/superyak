//! A turn's sandbox: a local clone with no remote, a scrubbed environment, and runs that end with everything
//! they started.
//!
//! Each run gets its own process group and random environment marker. Supervision records observed
//! descendants by process identity and confirms their cleanup, including after normal exit.

use std::ffi::{OsStr, OsString};
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex, OnceLock, PoisonError};
use std::thread;
use std::time::{Duration, Instant};

use room::limits::TERM_GRACE_SECS;

use crate::jail::{self, Jail};
use crate::process::{Identity, Supervisor, marker};
use crate::{TurnError, io};

/// The longest line a run hands over. The rest of a longer line is dropped, so one line without an end cannot
/// fill memory.
pub const MAX_LINE_BYTES: usize = 8 << 20;

/// What a run's environment keeps from the clock's. Everything else (tokens, agent sockets, `GIT_*`, the
/// room's own variables) is left out. `SDKROOT` and `DEVELOPER_DIR` say where the system's compiler kit is on
/// macOS: without them the developer-tool shim asks on every call, and where it may not write its cache (the
/// machine's own temporary directory, hidden from a worker) it complains on every `git` and every link.
const ENV_KEPT: &[&str] = &[
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "TZ",
    "CODEX_HOME",
    "CLAUDE_CONFIG_DIR",
    "SDKROOT",
    "DEVELOPER_DIR",
];

/// Where the agent programs keep their settings and sign-ins. A model worker's run keeps these; a jailed run
/// loses them, and the directories they name are hidden from it.
pub(crate) const AGENT_HOMES: [&str; 2] = ["CODEX_HOME", "CLAUDE_CONFIG_DIR"];

/// The name and address the turn's own commits carry. No person made them.
const TURN_NAME: &str = "yak turn";
const TURN_EMAIL: &str = "turn@yak.invalid";

/// The systemd scope outlives the run's own limit by this much, as a backstop (`SCOPE_SLACK` in runs.py).
const SCOPE_SLACK_SECS: u64 = 30;

/// The shell that starts a run, by its full path: it runs before the jail is entered, in a worker's checkout,
/// so it is never looked up.
const BOOTSTRAP_SHELL: &str = "/bin/sh";

/// The search path a run gets when the clock's has no absolute entry.
const PLAIN_PATH: &str = "/usr/bin:/bin";

/// How long the room's own git may take. It is long, for a large clone; what matters is that it is not for
/// ever, whatever a worker left in a repository the room reads.
pub const ROOM_GIT_SECS: u64 = 600;

/// How much of one git command's output the room keeps. It is large, for the list of a big commit's files;
/// what matters is that it is not without end, whatever a worker left in a repository the room reads. A command
/// that prints more is refused, whoever asked.
pub const ROOM_GIT_OUTPUT_BYTES: usize = 64 << 20;
/// The longest name a turn is given for its prompt's first line (`Sandbox::name_turn`).
pub const TURN_NAME_CHARS: usize = 64;

/// How much the room keeps of what a git command says of its failure.
const ROOM_GIT_COMPLAINT_BYTES: usize = 64 << 10;

const POLL: Duration = Duration::from_millis(50);
/// After a run ends, lines still in the pipe are handed over until none comes for this long.
const DRAIN_IDLE: Duration = Duration::from_millis(500);

pub struct Sandbox {
    /// The clone's directory, canonical.
    pub dir: PathBuf,
    /// The branch the clone is on, made at the base commit.
    pub branch: String,
    base: String,
    config: Vec<u8>,
    pid_file: Option<PathBuf>,
    stop: Arc<AtomicBool>,
    /// Which directory the clone is: its device and its number there, taken when it was made.
    id: (u64, u64),
    /// The same for the scratch directory, once a jailed run has made it.
    scratch_id: OnceLock<(u64, u64)>,
    /// Whether a run was ever started in this sandbox.
    a_run_began: AtomicBool,
    /// What a model worker's shell is not shown, as real paths: the item's repository, and what the room adds.
    hidden_from_worker: Vec<PathBuf>,
    /// The turn's own temporary directory and which directory it is, once made.
    worker_tmp: Mutex<Option<(PathBuf, (u64, u64))>>,
    /// The turn's name, when the room gave it one for its worker's prompt to begin with.
    turn: Option<String>,
}

/// Which directory `path` is: its device and its number on that device. A link is not a directory.
fn identity(path: &Path) -> Result<(u64, u64), TurnError> {
    let meta = fs::symlink_metadata(path).map_err(io(format!("look at {}", path.display())))?;
    if !meta.is_dir() {
        return Err(TurnError::Refused(format!(
            "{} is not a directory",
            path.display()
        )));
    }
    Ok((meta.dev(), meta.ino()))
}

/// Removes whatever is at `path` (a file, a link, a directory) without following a link. Nothing there is fine.
fn clear(path: &Path) -> Result<(), TurnError> {
    match fs::symlink_metadata(path) {
        Ok(meta) if meta.is_dir() => remove_tree(path),
        Ok(_) => fs::remove_file(path).map_err(io(format!("remove {}", path.display()))),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(io(format!("look at {}", path.display()))(e)),
    }
}

/// What a run is, beside its program: one in the jail, with the jail and its scratch directory; a model worker's
/// own program, with the turn's own temporary directory; or neither.
#[derive(Clone, Copy)]
enum Started<'a> {
    Plain,
    Model(&'a Path),
    Jailed(&'a Jail, &'a Path),
}

/// How many names a private directory is tried under before the room gives up.
const PRIVATE_DIR_TRIES: u32 = 5;

/// Makes a new directory `yak-<name>` in `parent` with mode 0700, where nothing is at that name: not a file,
/// not a link, not a directory. When something is, another name is asked of `name` and tried, up to
/// `PRIVATE_DIR_TRIES` names in all. Anything else that stops it is said at once.
fn private_dir(
    parent: &Path,
    name: &mut dyn FnMut() -> Result<String, TurnError>,
) -> Result<PathBuf, TurnError> {
    use std::os::unix::fs::DirBuilderExt;
    for _ in 0..PRIVATE_DIR_TRIES {
        let path = parent.join(format!("yak-{}", name()?));
        match fs::DirBuilder::new().mode(0o700).create(&path) {
            Ok(()) => return Ok(path),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(e) => return Err(io(format!("make {}", path.display()))(e)),
        }
    }
    Err(TurnError::Refused(format!(
        "no private directory could be made in {}: something was already at each of {PRIVATE_DIR_TRIES} new names",
        parent.display()
    )))
}

/// Writes a file that must not exist yet, so a link put in its place is never written through.
fn write_new(path: &Path, content: &[u8]) -> Result<(), TurnError> {
    let what = || format!("write {}", path.display());
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(io(what()))?;
    file.write_all(content).map_err(io(what()))
}

/// How many times the room inspects git metadata that changes under the inspection, before it refuses.
const INSPECTIONS: u32 = 5;

/// What one pass over the metadata found.
enum Inspected {
    Plain,
    /// This path was listed and was gone when it was looked at.
    Moved(PathBuf),
}

/// Confirms that everything under `git_dir` is a plain file or a directory. The inspection rests on nothing
/// changing the clone any more: the worker has ended. If a path that was listed is gone when it is looked at,
/// something is still changing it, and what was seen so far confirms nothing. The room waits a moment and
/// inspects again from the start, a few times, and then refuses: it does not run git on metadata that will
/// not hold still. `look` is how a path is looked at, so that a test can make one move.
fn plain_metadata(
    root: &Path,
    git_dir: &Path,
    look: &mut dyn FnMut(&Path) -> std::io::Result<fs::Metadata>,
) -> Result<(), TurnError> {
    let mut pause = Duration::from_millis(20);
    let mut inspections = 0;
    loop {
        inspections += 1;
        match inspect_once(root, git_dir, look)? {
            Inspected::Plain => return Ok(()),
            Inspected::Moved(path) if inspections >= INSPECTIONS => {
                return Err(TurnError::Refused(format!(
                    "git metadata kept changing while the room inspected it ({} went away): something the \
                     worker started is still running",
                    path.strip_prefix(root).unwrap_or(&path).display()
                )));
            }
            Inspected::Moved(_) => {
                thread::sleep(pause);
                pause *= 2;
            }
        }
    }
}

/// One pass over the metadata: every path under `git_dir`, each looked at once.
fn inspect_once(
    root: &Path,
    git_dir: &Path,
    look: &mut dyn FnMut(&Path) -> std::io::Result<fs::Metadata>,
) -> Result<Inspected, TurnError> {
    let gone = |e: &std::io::Error| e.kind() == std::io::ErrorKind::NotFound;
    let mut pending = vec![git_dir.to_path_buf()];
    while let Some(path) = pending.pop() {
        let meta = match look(&path) {
            Ok(meta) => meta,
            Err(e) if gone(&e) => return Ok(Inspected::Moved(path)),
            Err(e) => return Err(io("inspect git metadata")(e)),
        };
        if meta.is_symlink() {
            return Err(TurnError::Refused(
                "git metadata must contain no symbolic links".into(),
            ));
        }
        // A named pipe where a ref should be would hold git, which opens a ref to read it, until somebody
        // wrote to the pipe. Nothing but files and directories belongs here.
        if !meta.is_dir() && !meta.is_file() {
            return Err(TurnError::Refused(format!(
                "git metadata must hold only files and directories: {} is neither",
                path.strip_prefix(root).unwrap_or(&path).display()
            )));
        }
        if meta.is_dir() {
            let entries = match fs::read_dir(&path) {
                Ok(entries) => entries,
                Err(e) if gone(&e) => return Ok(Inspected::Moved(path)),
                Err(e) => return Err(io("read git metadata")(e)),
            };
            for entry in entries {
                pending.push(entry.map_err(io("read git metadata entry"))?.path());
            }
        }
    }
    Ok(Inspected::Plain)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RunStatus {
    /// The leader's exit code, or 128 plus the signal that ended it.
    pub exit_code: i32,
    pub timed_out: bool,
    /// The sandbox's switch ended the run: the room did, when it was stopped or the turn's lease was lost. Not
    /// the program, and not its limit.
    pub stopped: bool,
}

impl Sandbox {
    /// Clones `repo` into `dir` (which must not exist, or be empty) and checks out a new `branch` at
    /// `base_commit`. The clone holds the objects `base_commit` reaches and no other object of `repo`: not
    /// another turn's commit brought into it, not another branch, not an object nothing names. It has no remote,
    /// cannot fetch or push over any transport, runs no hooks and commits as the turn.
    pub fn create(
        repo: &Path,
        base_commit: &str,
        dir: &Path,
        branch: &str,
    ) -> Result<Sandbox, TurnError> {
        if base_commit.is_empty() || base_commit.starts_with('-') {
            return Err(TurnError::Refused(format!(
                "{base_commit:?} is not a commit"
            )));
        }
        check_branch(branch)?;
        if let Ok(meta) = fs::symlink_metadata(dir) {
            let empty = meta.is_dir()
                && fs::read_dir(dir)
                    .map_err(io("read the sandbox directory"))?
                    .next()
                    .is_none();
            if !empty {
                return Err(TurnError::Refused(format!(
                    "{} already exists",
                    dir.display()
                )));
            }
        }
        // A name means what it means in the item's repository.
        let base = rev_parse(repo, &format!("{base_commit}^{{commit}}"))?;
        let repo = std::path::absolute(repo).map_err(io("find the item's repository"))?;
        let mut made = Remove(Some(dir.to_path_buf()));
        // An empty repository of the item's kind of object id, given the base by its id: git sends a commit asked
        // for with what it reaches, and nothing else. A clone would copy every object the repository holds.
        let format = if base.len() == 64 { "sha256" } else { "sha1" };
        let mut init = git_command();
        init.args(["init", "-q", &format!("--object-format={format}"), "--"])
            .arg(dir);
        output(init, "init")?;
        let mut fetch = git_command();
        fetch
            .arg("-C")
            .arg(dir)
            // Version 2 of git's protocol sends any object asked for by its id, a base that is no branch's tip
            // among them; the file protocol is allowed for this one fetch, before the clone's own settings
            // forbid every protocol.
            .args([
                "-c",
                "protocol.version=2",
                "-c",
                "protocol.file.allow=always",
                "fetch",
                "-q",
                "--no-tags",
                "--no-write-fetch-head",
                "--no-recurse-submodules",
                "--no-auto-maintenance",
                "--",
            ])
            .arg(&repo)
            .arg(&base);
        output(fetch, "fetch the base")?;
        for (key, value) in [
            ("user.name", TURN_NAME),
            ("user.email", TURN_EMAIL),
            ("commit.gpgsign", "false"),
            ("tag.gpgsign", "false"),
            ("core.hooksPath", "/dev/null"),
            ("protocol.allow", "never"),
            ("credential.helper", ""),
            // Git's own tidying is off in the clone. A commit would otherwise start it in the background, and
            // it would still be changing `.git` after the worker had ended, under the room's inspection.
            // `maintenance.auto` is what a commit asks; `gc.auto` is for a git old enough to ask that.
            ("maintenance.auto", "false"),
            ("gc.auto", "0"),
            // No git in the clone looks for an ignore or attributes file in a home: a worker's shell may not
            // read the home, and git there warns of every file it was refused.
            ("core.excludesFile", "/dev/null"),
            ("core.attributesFile", "/dev/null"),
        ] {
            git(dir, &["config", key, value])?;
        }
        git(dir, &["checkout", "-q", "-b", branch, &base])?;
        let dir = fs::canonicalize(dir).map_err(io("find the sandbox"))?;
        // The room's own copy of the clone's config, put back before the room runs git there after a worker.
        let config =
            fs::read(dir.join(".git").join("config")).map_err(io("read the clone's config"))?;
        // The item's repository keeps every commit brought into it, earlier turns' answers among them.
        let repo = fs::canonicalize(&repo).map_err(io("find the item's repository"))?;
        made.0 = None;
        let id = identity(&dir)?;
        Ok(Sandbox {
            dir,
            branch: branch.to_string(),
            base,
            config,
            pid_file: None,
            stop: Arc::new(AtomicBool::new(false)),
            id,
            scratch_id: OnceLock::new(),
            a_run_began: AtomicBool::new(false),
            hidden_from_worker: vec![repo],
            worker_tmp: Mutex::new(None),
            turn: None,
        })
    }

    /// Hides `path` from a model worker's shell, as its real path. A path that is not absolute, or is not there,
    /// is refused: one quietly left out would look hidden and not be.
    pub fn hide_from_worker(&mut self, path: &Path) -> Result<(), TurnError> {
        if !path.is_absolute() {
            return Err(TurnError::Refused(format!(
                "{} cannot be hidden from a worker: it is not an absolute path",
                path.display()
            )));
        }
        let real = fs::canonicalize(path).map_err(|e| {
            TurnError::Refused(format!(
                "{} cannot be hidden from a worker: it is not there ({e})",
                path.display()
            ))
        })?;
        self.hidden_from_worker.push(real);
        Ok(())
    }

    /// Names the turn this sandbox is for. Its worker's prompt then begins with a line that holds the name, so
    /// that two turns given the same item do not begin alike (a worker's program keeps what it was lately sent,
    /// and reads back a prompt that begins the same way). The name is the room's own, an attempt's id: letters,
    /// digits and `-`, `TURN_NAME_CHARS` of them at most and nothing else, since it goes into a prompt.
    pub fn name_turn(&mut self, turn: &str) -> Result<(), TurnError> {
        if turn.is_empty()
            || turn.len() > TURN_NAME_CHARS
            || !turn.chars().all(|c| c.is_ascii_alphanumeric() || c == '-')
        {
            // What was refused may be long or hold anything: its length is said, not the name.
            return Err(TurnError::Refused(format!(
                "a turn's name is 1 to {TURN_NAME_CHARS} letters, digits and `-`: the one given, of {} bytes, is not",
                turn.len()
            )));
        }
        self.turn = Some(turn.to_string());
        Ok(())
    }

    /// The turn's name, when it was given one.
    pub fn turn(&self) -> Option<&str> {
        self.turn.as_deref()
    }

    /// What a model worker's shell is not shown, as real paths: first the item's repository, then what was
    /// added with `hide_from_worker`, in that order.
    pub fn hidden_from_worker(&self) -> &[PathBuf] {
        &self.hidden_from_worker
    }

    /// The turn's own temporary directory: made on the first call, and the same afterwards. It is a new
    /// directory directly under the real path of `/tmp`, `yak-` and 16 hex characters from the system's random
    /// source, with mode 0700, made so that making it fails if anything is already at its name. It is removed
    /// with the sandbox, and only if it is still the directory that was made.
    ///
    /// Why under `/tmp` and not beside the sandbox: Claude gives a shell command a temporary directory shared
    /// by every session on the machine unless the one it is told to use has a short path (measured: a path of
    /// 77 characters was not used, one of 19 was).
    pub fn worker_tmp(&self) -> Result<PathBuf, TurnError> {
        let mut made = self
            .worker_tmp
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if let Some((path, _)) = &*made {
            return Ok(path.clone());
        }
        let root = fs::canonicalize("/tmp").map_err(io("find /tmp"))?;
        let path = private_dir(&root, &mut || Ok(marker()?[..16].to_string()))?;
        *made = Some((path.clone(), identity(&path)?));
        Ok(path)
    }

    /// The temporary directories every turn on the machine shares: the real path of `/tmp`, and the real path of
    /// the clock's own `TMPDIR` when that is set, is there and is another directory.
    pub fn shared_tmp() -> Vec<PathBuf> {
        let mut shared: Vec<PathBuf> = fs::canonicalize("/tmp").into_iter().collect();
        if let Some(own) = std::env::var_os("TMPDIR").and_then(|dir| fs::canonicalize(dir).ok())
            && own.is_dir()
            && !shared.contains(&own)
        {
            shared.push(own);
        }
        shared
    }

    /// The commit the sandbox was made at, in full.
    pub fn base(&self) -> &str {
        &self.base
    }

    /// Refuses unless the clone's directory is still the one that was made. A worker that moved it away and
    /// left a link or another directory at its path would otherwise have the room run, read and write there.
    fn own(&self) -> Result<(), TurnError> {
        match identity(&self.dir) {
            Ok(id) if id == self.id => Ok(()),
            _ => Err(TurnError::Refused(format!(
                "the sandbox at {} was replaced, and nothing more is done there",
                self.dir.display()
            ))),
        }
    }

    /// The commit the turn's branch is at now, read after `reclaim`.
    pub fn head(&self) -> Result<String, TurnError> {
        self.reclaim()?;
        rev_parse(&self.dir, &format!("refs/heads/{}", self.branch))
    }

    /// Restores the room's git configuration and branch after confirming that all metadata paths are plain.
    /// The room's git ignores system and global config, writes no reflogs and runs no hooks.
    pub fn reclaim(&self) -> Result<(), TurnError> {
        self.own()?;
        let git_dir = self.dir.join(".git");
        for dir in [
            git_dir.clone(),
            git_dir.join("objects"),
            git_dir.join("refs"),
        ] {
            if !fs::symlink_metadata(&dir).is_ok_and(|m| m.is_dir()) {
                return Err(TurnError::Refused(format!(
                    "the worker replaced {}",
                    dir.display()
                )));
            }
        }
        plain_metadata(&self.dir, &git_dir, &mut |path| fs::symlink_metadata(path))?;
        let info = git_dir.join("objects").join("info");
        if fs::symlink_metadata(&info).is_ok_and(|m| !m.is_dir()) {
            clear(&info)?;
        }
        clear(&info.join("alternates"))?;
        for name in [
            "commondir",
            "config.worktree",
            "index.lock",
            "config",
            "HEAD",
            "logs",
        ] {
            clear(&git_dir.join(name))?;
        }
        write_new(&git_dir.join("config"), &self.config)?;
        write_new(
            &git_dir.join("HEAD"),
            format!("ref: refs/heads/{}\n", self.branch).as_bytes(),
        )
    }

    /// Requires a single repository and an index containing only ordinary entries.
    pub(crate) fn single_repository(&self) -> Result<(), TurnError> {
        let mut pending = vec![self.dir.clone()];
        while let Some(dir) = pending.pop() {
            for entry in fs::read_dir(&dir).map_err(io("read the work tree"))? {
                let entry = entry.map_err(io("read a work tree entry"))?;
                if entry
                    .file_name()
                    .to_string_lossy()
                    .eq_ignore_ascii_case(".git")
                {
                    if dir == self.dir {
                        continue;
                    }
                    return Err(TurnError::Refused(
                        "the work tree must contain a single repository".into(),
                    ));
                }
                if entry
                    .file_type()
                    .map_err(io("inspect a work tree entry"))?
                    .is_dir()
                {
                    pending.push(entry.path());
                }
            }
        }
        self.ordinary_index()
    }

    pub(crate) fn ordinary_index(&self) -> Result<(), TurnError> {
        self.own()?;
        let entries = git(&self.dir, &["ls-files", "--stage", "-z"])?;
        if entries
            .split(|&b| b == 0)
            .any(|entry| entry.starts_with(b"160000 "))
        {
            return Err(TurnError::Refused(
                "the index must contain no gitlinks".into(),
            ));
        }
        Ok(())
    }

    /// The switch that stops this sandbox, for another thread to set: the clock does when the room is
    /// stopped or the turn's lease is lost. Once it is set, a run in progress is ended as one that ran out
    /// of time is (its group gets SIGTERM, then SIGKILL after the grace, and the descendants it was seen to
    /// start are ended), and no later run starts. It is never unset.
    pub fn stop_switch(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.stop)
    }

    /// Whether a run was ever started in this sandbox: a worker's program, a check, the room's own git. Until
    /// one is, nothing has run here, whatever a worker's `run` returned.
    pub fn started_a_run(&self) -> bool {
        self.a_run_began.load(Ordering::Relaxed)
    }

    /// Each run atomically writes its group and leader start time, one per line, to this path, and
    /// removes the file after confirmed cleanup. The clock keeps it beside the clone.
    pub fn set_pid_file(&mut self, path: PathBuf) {
        self.pid_file = Some(path);
    }

    /// Ends a run a dead clock left, from its pid file: the leader and every process the run was seen to start,
    /// each only if it is still the process the file describes. Returns whether anything was ended. With
    /// nothing of the run left, nothing is signalled. The file is removed once the run is known to be gone,
    /// and kept if it could not be ended.
    pub fn end_stale(pid_file: &Path) -> Result<bool, TurnError> {
        let Some(identity) = Identity::read(pid_file)? else {
            return Ok(false);
        };
        match Supervisor::recover(identity)? {
            None => Ok(false),
            Some(mut supervisor) => {
                let ended = supervisor.end()?;
                match fs::remove_file(pid_file) {
                    Ok(()) => {}
                    Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                    Err(e) => return Err(io("remove the recovered pid file")(e)),
                }
                Ok(ended)
            }
        }
    }

    /// Runs `program` in the sandbox with the scrubbed environment, in its own process group, for at most
    /// `limit_secs`. Its stdout and stderr share one pipe and are handed to `on_line` a line at a time, without
    /// the line end, as they come; nothing is held whole. On Linux, when a user systemd scope can be made, the
    /// run is held to 2 GB of memory.
    pub fn run(
        &self,
        program: &str,
        args: &[String],
        stdin: &str,
        limit_secs: u32,
        on_line: &mut dyn FnMut(&str),
    ) -> Result<RunStatus, TurnError> {
        self.run_with(Started::Plain, program, args, stdin, limit_secs, on_line)
    }

    /// Runs a model worker's own program as `run` does, telling it where it may keep temporary files and that
    /// its git reads no global settings: `TMPDIR` and `CLAUDE_CODE_TMPDIR` are the turn's own temporary
    /// directory (`worker_tmp`), and `GIT_CONFIG_GLOBAL` is `/dev/null`. Its shell may not read the home, and git
    /// stops where it may not read the settings it looks for there (measured: "fatal: unable to access
    /// '.../.gitconfig': Operation not permitted").
    pub(crate) fn run_model(
        &self,
        program: &str,
        args: &[String],
        stdin: &str,
        limit_secs: u32,
        on_line: &mut dyn FnMut(&str),
    ) -> Result<RunStatus, TurnError> {
        let tmp = self.worker_tmp()?;
        self.run_with(
            Started::Model(&tmp),
            program,
            args,
            stdin,
            limit_secs,
            on_line,
        )
    }

    /// Runs `program` as `run` does, inside an OS-level jail: it can write only in the sandbox and a scratch
    /// directory beside it, reach no network, and signal nothing outside. Its home and its place for temporary
    /// files are the scratch directory. This is for what the room does not trust: a check, a script worker, and
    /// the room's own git in a worker's tree. With `YAK_JAIL=off` it is `run`. With no jail tool on the
    /// machine it is refused.
    pub fn run_untrusted(
        &self,
        program: &str,
        args: &[String],
        stdin: &str,
        limit_secs: u32,
        on_line: &mut dyn FnMut(&str),
    ) -> Result<RunStatus, TurnError> {
        if !jail::wanted() {
            return self.run(program, args, stdin, limit_secs, on_line);
        }
        self.own()?;
        let scratch = self.scratch();
        match self.scratch_id.get() {
            None => {
                // Made here, and it must not be there already: whatever was would not be the room's.
                fs::create_dir(&scratch).map_err(io("make the scratch directory"))?;
                let _ = self.scratch_id.set(identity(&scratch)?);
            }
            Some(&id) => {
                if identity(&scratch).ok() != Some(id) {
                    return Err(TurnError::Refused(format!(
                        "the scratch directory at {} was replaced, and nothing more runs with it",
                        scratch.display()
                    )));
                }
            }
        }
        let mut jail = jail::for_checkout(&self.dir, &scratch)?;
        // A program named by its path (a script worker's) is shown to the run: that one file, not what is
        // beside it.
        if Path::new(program).is_absolute() {
            if let Some(hidden) = jail.hides(Path::new(program)) {
                return Err(TurnError::Refused(format!(
                    "{program} cannot run in the jail: {} is hidden from every run",
                    hidden.display()
                )));
            }
            jail = jail.allow_read(Path::new(program))?;
        }
        self.run_with(
            Started::Jailed(&jail, &scratch),
            program,
            args,
            stdin,
            limit_secs,
            on_line,
        )
    }

    /// The scratch directory a jailed run may write in: beside the sandbox, never inside the clone.
    fn scratch(&self) -> PathBuf {
        let mut name = self.dir.file_name().unwrap_or_default().to_os_string();
        name.push(".scratch");
        self.dir.with_file_name(name)
    }

    fn run_with(
        &self,
        started: Started<'_>,
        program: &str,
        args: &[String],
        stdin: &str,
        limit_secs: u32,
        on_line: &mut dyn FnMut(&str),
    ) -> Result<RunStatus, TurnError> {
        if self.stop.load(Ordering::Relaxed) {
            return Err(TurnError::Refused(
                "this sandbox was stopped, and nothing more runs in it".into(),
            ));
        }
        self.own()?;
        let wrapped;
        let (program, args) = match started {
            Started::Jailed(jail, _) => {
                let (tool, tool_args) = jail.command(program, args);
                wrapped = (tool.to_string_lossy().into_owned(), tool_args);
                (wrapped.0.as_str(), wrapped.1.as_slice())
            }
            Started::Plain | Started::Model(_) => (program, args),
        };
        let launch = Launch::new(program, args, limit_secs);
        let marker = marker()?;
        let (reader, writer) = std::io::pipe().map_err(io("make a pipe"))?;
        // The leader waits on stdin until its identity has been recorded, then exec preserves that identity.
        let mut command = scrubbed(BOOTSTRAP_SHELL);
        command
            .args([
                "-c",
                "IFS= read -r yak_start || exit 125; exec \"$@\"",
                "yak-run",
            ])
            .arg(&launch.program)
            .args(&launch.args)
            .envs(launch.env)
            .env("YAK_TURN", &marker)
            .current_dir(&self.dir);
        match started {
            Started::Jailed(_, scratch) => {
                command.env("HOME", scratch).env("TMPDIR", scratch);
                for name in AGENT_HOMES {
                    command.env_remove(name);
                }
                // A jailed run's git reads no settings of the machine's. Its home is the scratch directory, so
                // it has none of a person's either. A check then means the same on every machine; and git works
                // where its own settings file is kept somewhere the jail does not show, which it otherwise takes
                // for an error and stops at (Homebrew's git, whose settings are under `/opt/homebrew/etc`).
                for (name, value) in JAILED_GIT_ENV {
                    command.env(name, value);
                }
            }
            Started::Model(tmp) => {
                command
                    .env("TMPDIR", tmp)
                    .env("CLAUDE_CODE_TMPDIR", tmp)
                    .env("GIT_CONFIG_GLOBAL", "/dev/null");
            }
            Started::Plain => {}
        }
        command
            .stdin(Stdio::piped())
            .stdout(writer.try_clone().map_err(io("make a pipe"))?)
            .stderr(writer)
            .process_group(0);
        let mut child = command.spawn().map_err(io(format!("start {program}")))?;
        self.a_run_began.store(true, Ordering::Relaxed);
        // The command holds the pipe's write ends; until it is gone the pipe never reaches its end.
        drop(command);
        let group = child.id();
        let mut supervisor = match Supervisor::start(group) {
            Ok(supervisor) => supervisor,
            Err(e) => {
                end_group(&mut child, group);
                return Err(e);
            }
        };
        let mut pid_file = match PidFile::write(self.pid_file.as_deref(), &supervisor.record()) {
            Ok(file) => file,
            Err(e) => {
                end_group(&mut child, group);
                return Err(e);
            }
        };
        if let Some(mut input) = child.stdin.take() {
            let input_text = format!("\n{stdin}");
            // A child that never reads its stdin must not hold the run up, so the write has its own thread.
            thread::spawn(move || {
                let _ = input.write_all(input_text.as_bytes());
            });
        }
        let (tx, rx) = mpsc::sync_channel::<String>(2);
        thread::spawn(move || read_lines(reader, |line| tx.send(line).is_ok()));

        let deadline = Instant::now() + Duration::from_secs(u64::from(limit_secs));
        let (mut timed_out, mut stopped) = (false, false);
        let status = loop {
            // A process seen for the first time goes into the record at once: after a crash the record is
            // what a later clock ends this run by.
            let seen = supervisor.poll().and_then(|grew| match grew {
                true => pid_file.update(&supervisor.record()),
                false => Ok(()),
            });
            if let Err(e) = seen {
                end_group(&mut child, group);
                self.confirm_ended(&mut supervisor, &mut pid_file)?;
                return Err(e);
            }
            let now = Instant::now();
            if now >= deadline || self.stop.load(Ordering::Relaxed) {
                // A program that has already ended by itself was not ended by its limit or by the switch, though
                // one of them came before the room looked again: it keeps its own end.
                match child.try_wait() {
                    Ok(Some(status)) => {
                        signal_group(group, "KILL");
                        break status;
                    }
                    Ok(None) => {}
                    Err(e) => {
                        end_group(&mut child, group);
                        self.confirm_ended(&mut supervisor, &mut pid_file)?;
                        return Err(io("wait for the run")(e));
                    }
                }
                timed_out = now >= deadline;
                stopped = !timed_out;
                break end_group(&mut child, group);
            }
            let wait = (deadline - now).min(POLL);
            let closed = match rx.recv_timeout(wait) {
                Ok(line) => {
                    on_line(&line);
                    continue;
                }
                Err(RecvTimeoutError::Timeout) => false,
                Err(RecvTimeoutError::Disconnected) => true,
            };
            match child.try_wait() {
                Ok(Some(status)) => {
                    // The leader is done; anything it left behind in its group goes with it.
                    signal_group(group, "KILL");
                    break status;
                }
                Ok(None) => {}
                Err(e) => {
                    end_group(&mut child, group);
                    self.confirm_ended(&mut supervisor, &mut pid_file)?;
                    return Err(io("wait for the run")(e));
                }
            }
            if closed {
                thread::sleep(wait);
            }
        };
        self.confirm_ended(&mut supervisor, &mut pid_file)?;
        drain(&rx, on_line);
        Ok(RunStatus {
            exit_code: exit_code(status),
            timed_out,
            stopped,
        })
    }

    /// Ends whatever the run was seen to start that is still going, and then removes the run's record. When
    /// the end cannot be confirmed the record stays, since it is then all there is to find the run by, and the
    /// error (`TurnError::Unended`) names it. Every way out of a run that was started goes through here.
    fn confirm_ended(
        &self,
        supervisor: &mut Supervisor,
        pid_file: &mut PidFile,
    ) -> Result<(), TurnError> {
        supervisor.end().map_err(|why| TurnError::Unended {
            record: match &self.pid_file {
                Some(path) => path.display().to_string(),
                None => "(this run kept none)".to_string(),
            },
            why: why.to_string(),
        })?;
        pid_file.remove();
        Ok(())
    }

    /// Removes the sandbox: the clone that was made, even where a worker took away its own write permission,
    /// the scratch directory a jailed run was given, and the turn's own temporary directory. Only those. If
    /// something else is at any of those paths by now (a link put in the place of one, say), it is not the room's
    /// to remove: it is left as it is, the rest is still removed, and the error (`TurnError::Left`) holds the
    /// paths that were left, for a caller that tidies around them.
    pub fn destroy(self) -> Result<(), TurnError> {
        let mut left = Vec::new();
        // A removal that fails does not end the others, and does not take the place of what was left.
        let mut failed: Option<TurnError> = None;
        let mut tried = |removal: Result<(), TurnError>| {
            if let Err(e) = removal {
                failed.get_or_insert(e);
            }
        };
        let scratch = self.scratch();
        // The scratch directory, when a jailed run made one and it is still that one.
        match self.scratch_id.get() {
            Some(&id) if identity(&scratch).ok() == Some(id) => tried(remove_tree(&scratch)),
            // Something is there that the room did not make, or that is no longer what it made.
            _ if fs::symlink_metadata(&scratch).is_ok() => left.push(scratch.clone()),
            _ => {}
        }
        // The Linux jail's filter, a file beside the scratch directory.
        let mut filter = scratch.into_os_string();
        filter.push(".filter");
        let filter = PathBuf::from(filter);
        if fs::symlink_metadata(&filter).is_ok_and(|meta| meta.is_file()) {
            tried(fs::remove_file(&filter).map_err(io("remove the jail's filter")));
        }
        // The turn's own temporary directory, when one was made and it is still that one: a link is no directory.
        let made = self
            .worker_tmp
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .take();
        if let Some((tmp, id)) = made {
            if identity(&tmp).ok() == Some(id) {
                tried(remove_tree(&tmp));
            } else if fs::symlink_metadata(&tmp).is_ok() {
                left.push(tmp);
            }
        }
        if identity(&self.dir).ok() == Some(self.id) {
            tried(remove_tree(&self.dir));
        } else if fs::symlink_metadata(&self.dir).is_ok() {
            left.push(self.dir.clone());
        }
        match (left.is_empty(), failed) {
            (true, None) => Ok(()),
            (true, Some(e)) => Err(e),
            (false, failed) => Err(TurnError::Left {
                paths: left,
                also: failed.map(|e| e.to_string()),
            }),
        }
    }
}

/// A path in `parent` that nothing in this process has used: `<prefix>-<pid>-<count>-<nanoseconds>`.
pub(crate) fn fresh_path(parent: &Path, prefix: &str) -> PathBuf {
    static COUNT: AtomicU64 = AtomicU64::new(0);
    let count = COUNT.fetch_add(1, Ordering::Relaxed);
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.subsec_nanos())
        .unwrap_or(0);
    parent.join(format!("{prefix}-{}-{count}-{nanos}", std::process::id()))
}

/// Removes a directory tree, making directories in it writable first if a plain removal is refused.
pub(crate) fn remove_tree(dir: &Path) -> Result<(), TurnError> {
    match fs::remove_dir_all(dir) {
        Ok(()) => return Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(_) => {}
    }
    let mut stack = vec![dir.to_path_buf()];
    while let Some(path) = stack.pop() {
        // symlink_metadata, so a link to somewhere else is never followed or changed.
        if fs::symlink_metadata(&path).is_ok_and(|m| m.is_dir()) {
            let _ = fs::set_permissions(&path, fs::Permissions::from_mode(0o700));
            if let Ok(entries) = fs::read_dir(&path) {
                stack.extend(entries.flatten().map(|e| e.path()));
            }
        }
    }
    fs::remove_dir_all(dir).map_err(io(format!("remove {}", dir.display())))
}

/// Removes a path when dropped, unless forgotten: what a failed `create` leaves.
struct Remove(Option<PathBuf>);

impl Drop for Remove {
    fn drop(&mut self) {
        if let Some(path) = self.0.take() {
            let _ = remove_tree(&path);
        }
    }
}

struct PidFile(Option<PathBuf>);

impl PidFile {
    fn write(path: Option<&Path>, identity: &Identity) -> Result<PidFile, TurnError> {
        let Some(path) = path else {
            return Ok(PidFile(None));
        };
        let file = PidFile(Some(path.to_path_buf()));
        file.put(identity)?;
        Ok(file)
    }

    /// Writes the record anew, when the run has been seen to start another process.
    fn update(&self, identity: &Identity) -> Result<(), TurnError> {
        self.put(identity)
    }

    /// Written whole and then renamed, so a reader never sees half a record.
    fn put(&self, identity: &Identity) -> Result<(), TurnError> {
        let Some(path) = &self.0 else {
            return Ok(());
        };
        let mut partial = path.as_os_str().to_owned();
        partial.push(".partial");
        let partial = PathBuf::from(partial);
        clear(&partial)?;
        write_new(&partial, identity.text().as_bytes())?;
        fs::rename(&partial, path).map_err(io("write the pid file"))
    }

    fn remove(&mut self) {
        if let Some(path) = self.0.take() {
            let _ = fs::remove_file(&path);
        }
    }
}

/// What actually gets started for a run: the program itself, or the program inside a memory-capped scope.
struct Launch {
    program: String,
    args: Vec<String>,
    env: Vec<(String, OsString)>,
}

impl Launch {
    fn new(program: &str, args: &[String], limit_secs: u32) -> Launch {
        if memory_cap_available() {
            let (program, args) = scope_command(program, args, limit_secs);
            Launch {
                program,
                args,
                env: bus_env(),
            }
        } else {
            Launch {
                program: program.to_string(),
                args: args.to_vec(),
                env: Vec::new(),
            }
        }
    }
}

/// The command that runs `program` in a transient user scope held to 2 GB and no swap, as runs.py does. The
/// scope needs the session bus, which the program itself does not get.
pub fn scope_command(program: &str, args: &[String], limit_secs: u32) -> (String, Vec<String>) {
    scope_command_for(program, args, limit_secs, scope_can_be_told_not_to_expand())
}

/// `scope_command`, told whether this machine's `systemd-run` knows `--expand-environment`.
///
/// A newer `systemd-run` rewrites the command it is given before it runs it: `$$` becomes `$`, and `${NAME}`
/// becomes whatever `NAME` is in its own environment, or nothing. The command is the room's: a check's, or a
/// worker's. It must reach the program as it was written, so where the option is known it is turned off.
/// Where it is not known, `systemd-run` is too old to rewrite anything. Seen on Ubuntu 26.04, where every run
/// with a `$` in its command line went wrong; Debian 12 does not have the option and does not rewrite.
fn scope_command_for(
    program: &str,
    args: &[String],
    limit_secs: u32,
    told_not_to_expand: bool,
) -> (String, Vec<String>) {
    let mut argv: Vec<String> = ["--user", "--scope", "--quiet"]
        .iter()
        .map(|s| s.to_string())
        .collect();
    if told_not_to_expand {
        argv.push("--expand-environment=no".to_string());
    }
    argv.extend(
        ["-p", "MemoryMax=2G", "-p", "MemorySwapMax=0", "-p"]
            .iter()
            .map(|s| s.to_string()),
    );
    argv.push(format!(
        "RuntimeMaxSec={}",
        u64::from(limit_secs) + SCOPE_SLACK_SECS
    ));
    for word in [
        "--",
        "env",
        "-u",
        "DBUS_SESSION_BUS_ADDRESS",
        "-u",
        "XDG_RUNTIME_DIR",
        program,
    ] {
        argv.push(word.to_string());
    }
    argv.extend(args.iter().cloned());
    ("systemd-run".to_string(), argv)
}

fn bus_env() -> Vec<(String, OsString)> {
    ["DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"]
        .iter()
        .filter_map(|name| std::env::var_os(name).map(|v| (name.to_string(), v)))
        .collect()
}

/// Whether runs can be wrapped in a memory-capped systemd scope: Linux, `systemd-run` present, a user manager
/// that answers, and a command line that comes through it unchanged. Many CI machines have the program and no
/// user manager, so it is tried once.
/// Whether this machine's `systemd-run` knows `--expand-environment`, asked of its own help once.
#[cfg(target_os = "linux")]
fn scope_can_be_told_not_to_expand() -> bool {
    static KNOWN: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *KNOWN.get_or_init(|| {
        let mut help = scrubbed("systemd-run");
        help.arg("--help").stdin(Stdio::null());
        output_within(help, "systemd-run --help", Duration::from_secs(10), None)
            .is_ok_and(|said| String::from_utf8_lossy(&said).contains("--expand-environment"))
    })
}

#[cfg(not(target_os = "linux"))]
fn scope_can_be_told_not_to_expand() -> bool {
    false
}

#[cfg(target_os = "linux")]
fn memory_cap_available() -> bool {
    static AVAILABLE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *AVAILABLE.get_or_init(|| {
        // The trial is a command that only succeeds if its words arrive as written: `test '$$' != '$'`. A
        // scope that rewrote them would hand over `$` twice, and the test would fail. Then no run is put in a
        // scope here: a run without the memory cap is still the run that was asked for, and a run whose
        // command was rewritten is not.
        let words = ["$$", "!=", "$"].map(String::from);
        let (program, args) = scope_command("test", &words, 30);
        let mut probe = scrubbed(program);
        probe
            .args(args)
            .envs(bus_env())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let Ok(mut child) = probe.spawn() else {
            return false;
        };
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            match child.try_wait() {
                Ok(Some(status)) => return status.success(),
                Ok(None) if Instant::now() < deadline => thread::sleep(POLL),
                _ => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return false;
                }
            }
        }
    })
}

#[cfg(not(target_os = "linux"))]
fn memory_cap_available() -> bool {
    false
}

/// Whether the room goes on where it cannot watch a run's processes: only with `YAK_SUPERVISION=best-effort`.
/// Like `YAK_JAIL=off`, the switch is for tests inside another sandbox, where processes cannot be listed. A
/// clock that runs model workers refuses to start with it set.
pub fn supervision_is_best_effort() -> bool {
    std::env::var("YAK_SUPERVISION").as_deref() == Ok("best-effort")
}

/// A command with only the kept variables of the clock's environment, and a search path of absolute
/// entries only.
pub(crate) fn scrubbed(program: impl AsRef<OsStr>) -> Command {
    let mut command = Command::new(program);
    command.env_clear();
    for name in ENV_KEPT {
        if let Some(value) = std::env::var_os(name) {
            command.env(name, value);
        }
    }
    let path = std::env::var_os("PATH").unwrap_or_default();
    command.env("PATH", absolute_entries(&path));
    command
}

/// The entries of a search path that are full paths. A relative or empty entry is looked up in whatever
/// directory a program starts in, and the room starts programs in a worker's checkout: a file the worker
/// committed there would be run in place of the room's own shell or git, outside any jail.
pub(crate) fn absolute_entries(path: &OsStr) -> OsString {
    let kept: Vec<PathBuf> = std::env::split_paths(path)
        .filter(|entry| entry.is_absolute())
        .collect();
    std::env::join_paths(kept)
        .ok()
        .filter(|joined| !joined.is_empty())
        .unwrap_or_else(|| OsString::from(PLAIN_PATH))
}

/// What a jailed run's git is told: no settings file and no attributes file of the machine's.
const JAILED_GIT_ENV: [(&str, &str); 2] =
    [("GIT_CONFIG_NOSYSTEM", "1"), ("GIT_ATTR_NOSYSTEM", "1")];

/// Flags for every git the room runs: no hooks, no filesystem monitor, no attributes file of the user's.
pub(crate) const SAFE_GIT_FLAGS: [&str; 12] = [
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.attributesFile=/dev/null",
    "-c",
    "core.logAllRefUpdates=false",
    "-c",
    "submodule.recurse=false",
    "-c",
    "diff.ignoreSubmodules=all",
];

/// And no system or global config, where a driver for an attribute could be named.
pub(crate) const SAFE_GIT_ENV: [(&str, &str); 2] = [
    ("GIT_CONFIG_NOSYSTEM", "1"),
    ("GIT_CONFIG_GLOBAL", "/dev/null"),
];

/// git as the room runs it, for the clock's own fetch as well: the flags and environment are kept in this one
/// place.
pub fn safe_git() -> Command {
    git_command()
}

/// git with the scrubbed environment, no prompts, no hooks and no filesystem monitor: the turn's own git
/// commands must not run anything a worker configured in its clone.
fn git_command() -> Command {
    let mut command = scrubbed("git");
    command
        .args(SAFE_GIT_FLAGS)
        .envs(SAFE_GIT_ENV)
        .env("GIT_TERMINAL_PROMPT", "0")
        .stdin(Stdio::null());
    command
}

/// Runs git in `dir` and returns its stdout.
pub(crate) fn git(dir: &Path, args: &[&str]) -> Result<Vec<u8>, TurnError> {
    let mut command = git_command();
    command.arg("-C").arg(dir).args(args);
    output(command, &args.join(" "))
}

fn output(command: Command, what: &str) -> Result<Vec<u8>, TurnError> {
    output_within(command, what, Duration::from_secs(ROOM_GIT_SECS), None)
}

/// Runs the room's git, as `safe_git` made it and with what the caller added, for at most `ROOM_GIT_SECS`, and
/// returns its stdout. For the clock's own fetch: one runner, so one limit.
pub fn safe_git_output(command: Command, what: &str) -> Result<Vec<u8>, TurnError> {
    output(command, what)
}

/// `safe_git_output` for at most `limit`, and ended sooner if `stop` is set meanwhile: the clock sets it when
/// the room is stopped or the turn's lease is lost. Set before the start, nothing is started.
pub fn safe_git_output_until(
    command: Command,
    what: &str,
    limit: Duration,
    stop: &AtomicBool,
) -> Result<Vec<u8>, TurnError> {
    output_within(command, what, limit, Some(stop))
}

/// `safe_git_output_until` for a question git answers with its exit code: gives that code and the output,
/// where the other treats every code but 0 as a failure. No code means a signal ended it.
pub fn safe_git_code_until(
    command: Command,
    what: &str,
    limit: Duration,
    stop: &AtomicBool,
) -> Result<(Option<i32>, Vec<u8>), TurnError> {
    let (status, stdout, _) = ended_within(command, what, limit, Some(stop))?;
    Ok((status.code(), stdout))
}

/// Runs `command` for at most `limit` and returns its stdout. The room's own git reads repositories a worker
/// has had its hands on, and must not wait on one for ever.
///
/// The limit covers everything: the program, and its output, which something the program started may hold
/// open after the program itself is done. The program runs in a group of its own, and when the limit passes
/// the whole group is ended, so nothing it started is left. The same is done as soon as `stop` is set.
fn output_within(
    command: Command,
    what: &str,
    limit: Duration,
    stop: Option<&AtomicBool>,
) -> Result<Vec<u8>, TurnError> {
    let (status, stdout, stderr) = ended_within(command, what, limit, stop)?;
    if status.success() {
        return Ok(stdout);
    }
    let stderr = String::from_utf8_lossy(&stderr);
    let stderr: String = stderr.trim().chars().take(300).collect();
    Err(TurnError::Git(format!("{what} failed: {stderr}")))
}

/// `output_within`, giving the program's own end and both of its outputs whatever that end was. An error here
/// is the runner's: it could not start the program, or ended it.
fn ended_within(
    mut command: Command,
    what: &str,
    limit: Duration,
    stop: Option<&AtomicBool>,
) -> Result<(ExitStatus, Vec<u8>, Vec<u8>), TurnError> {
    let stopped = || stop.is_some_and(|stop| stop.load(Ordering::Relaxed));
    let halted = || TurnError::Git(format!("{what} was ended before it finished"));
    if stopped() {
        return Err(halted());
    }
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0)
        .spawn()
        .map_err(io("start git"))?;
    let group = child.id();
    // Each pipe is read on its own thread, so a full one never holds the program up, and hands over what it
    // read when the pipe closes. No more than `keep` bytes are kept, and the thread says whether there was more.
    // Of the output, nothing past the limit is read, and the program is ended as soon as that is seen. Of what
    // the program says of a failure, the rest is read and dropped: a program is not ended for having much to
    // complain of.
    let read = |pipe: Option<Box<dyn Read + Send>>, keep: usize, drop_the_rest: bool| {
        let (done, wait) = mpsc::channel::<(Vec<u8>, bool)>();
        thread::spawn(move || {
            let mut bytes = Vec::new();
            let mut more = false;
            if let Some(mut pipe) = pipe {
                let _ = (&mut pipe).take(keep as u64).read_to_end(&mut bytes);
                if drop_the_rest {
                    let _ = std::io::copy(&mut pipe, &mut std::io::sink());
                } else {
                    more = pipe.read(&mut [0u8; 1]).is_ok_and(|read| read > 0);
                }
            }
            let _ = done.send((bytes, more));
        });
        wait
    };
    let stdout = read(
        child
            .stdout
            .take()
            .map(|p| Box::new(p) as Box<dyn Read + Send>),
        ROOM_GIT_OUTPUT_BYTES,
        false,
    );
    let stderr = read(
        child
            .stderr
            .take()
            .map(|p| Box::new(p) as Box<dyn Read + Send>),
        ROOM_GIT_COMPLAINT_BYTES,
        true,
    );
    let deadline = Instant::now() + limit;
    let late = |child: &mut Child| {
        signal_group(group, "KILL");
        let _ = child.kill();
        let _ = child.wait();
        if stopped() {
            return halted();
        }
        TurnError::Git(format!(
            "{what} did not finish in {} seconds and was ended",
            limit.as_secs()
        ))
    };
    let too_much = || {
        TurnError::Git(format!(
            "{what} printed more than {ROOM_GIT_OUTPUT_BYTES} bytes, and the room keeps no more of a git \
             command's output than that"
        ))
    };
    // git usually answers in a few milliseconds, so the first looks come quickly and the later ones less often.
    let mut pause = Duration::from_millis(1);
    let mut printed: Option<Vec<u8>> = None;
    let status = loop {
        // Its output is looked at while it runs: a program that has printed too much is ended now, and not
        // when it next writes or when its time is up.
        if printed.is_none()
            && let Ok((bytes, more)) = stdout.try_recv()
        {
            if more {
                signal_group(group, "KILL");
                let _ = child.kill();
                let _ = child.wait();
                return Err(too_much());
            }
            printed = Some(bytes);
        }
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline && !stopped() => {
                thread::sleep(pause);
                pause = (pause * 2).min(POLL);
            }
            Ok(None) | Err(_) => return Err(late(&mut child)),
        }
    };
    // What a pipe held, waited for in short looks so that the switch is seen while waiting.
    let read_out = |pipe: &mpsc::Receiver<(Vec<u8>, bool)>| loop {
        let now = Instant::now();
        if now >= deadline || stopped() {
            return None;
        }
        match pipe.recv_timeout((deadline - now).min(POLL)) {
            Ok(bytes) => return Some(bytes),
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => return None,
        }
    };
    let stdout = match printed {
        Some(bytes) => bytes,
        None => match read_out(&stdout) {
            Some((bytes, false)) => bytes,
            Some((_, true)) => {
                signal_group(group, "KILL");
                return Err(too_much());
            }
            None => return Err(late(&mut child)),
        },
    };
    // What it says of a failure is cut short where it is too long; that is no refusal.
    let Some((stderr, _)) = read_out(&stderr) else {
        return Err(late(&mut child));
    };
    // The program is done and so is its output. Anything it left in its group goes with it.
    signal_group(group, "KILL");
    Ok((status, stdout, stderr))
}

/// The full id of `rev` in `dir`.
pub(crate) fn rev_parse(dir: &Path, rev: &str) -> Result<String, TurnError> {
    let out = git(
        dir,
        &["rev-parse", "--verify", "--quiet", "--end-of-options", rev],
    )?;
    let id = String::from_utf8_lossy(&out).trim().to_string();
    if id.len() == 40 || id.len() == 64 {
        Ok(id)
    } else {
        Err(TurnError::Git(format!("rev-parse {rev} gave no id")))
    }
}

fn check_branch(branch: &str) -> Result<(), TurnError> {
    let mut command = git_command();
    command.args(["check-ref-format", &format!("refs/heads/{branch}")]);
    let ok = !branch.starts_with('-') && command.output().is_ok_and(|o| o.status.success());
    if ok {
        Ok(())
    } else {
        Err(TurnError::Refused(format!(
            "{branch:?} is not a branch name"
        )))
    }
}

/// Sends `signal` to every process in `group`. A group with nothing left in it is not an error.
fn signal_group(group: u32, signal: &str) {
    let target = format!("-{group}");
    let sent = scrubbed("kill")
        .args(["-s", signal, "--", &target])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    if sent.is_err() {
        // No kill program on this machine: the shell's own kill does the same.
        let _ = scrubbed("sh")
            .args(["-c", "kill -s \"$1\" -- \"$2\"", "sh", signal, &target])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}

/// SIGTERM to the group, up to `TERM_GRACE_SECS` for its leader to go, then SIGKILL to the group; returns
/// the leader's status.
fn end_group(child: &mut Child, group: u32) -> ExitStatus {
    signal_group(group, "TERM");
    let deadline = Instant::now() + Duration::from_secs(u64::from(TERM_GRACE_SECS));
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) | Err(_) => break,
            Ok(None) => thread::sleep(POLL),
        }
    }
    signal_group(group, "KILL");
    match child.wait() {
        Ok(status) => status,
        // Already reaped: only try_wait above can have done that, and it reported nothing better.
        Err(_) => ExitStatus::from_raw(9),
    }
}

/// Hands over what is still in the pipe once a run has ended, until the pipe closes or goes quiet. A process
/// that left its group and kept the pipe cannot hold the turn for more than the grace.
fn drain(rx: &Receiver<String>, on_line: &mut dyn FnMut(&str)) {
    let deadline = Instant::now() + Duration::from_secs(u64::from(TERM_GRACE_SECS));
    while Instant::now() < deadline {
        match rx.recv_timeout(DRAIN_IDLE) {
            Ok(line) => on_line(&line),
            Err(_) => return,
        }
    }
}

/// Reads lines, each cut at `MAX_LINE_BYTES`, and passes each to `send` until it returns false or the input ends.
fn read_lines(input: impl Read, mut send: impl FnMut(String) -> bool) {
    let mut reader = BufReader::with_capacity(64 << 10, input);
    let mut line: Vec<u8> = Vec::new();
    loop {
        let buf = match reader.fill_buf() {
            Ok(buf) => buf,
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(_) => break,
        };
        if buf.is_empty() {
            if !line.is_empty() {
                send(finish(&mut line));
            }
            return;
        }
        let (chunk, used, ended) = match buf.iter().position(|&b| b == b'\n') {
            Some(i) => (&buf[..i], i + 1, true),
            None => (buf, buf.len(), false),
        };
        let room = MAX_LINE_BYTES.saturating_sub(line.len());
        line.extend_from_slice(&chunk[..chunk.len().min(room)]);
        reader.consume(used);
        if ended && !send(finish(&mut line)) {
            return;
        }
    }
}

fn finish(line: &mut Vec<u8>) -> String {
    if line.last() == Some(&b'\r') {
        line.pop();
    }
    let text = String::from_utf8_lossy(line).into_owned();
    if line.capacity() > 1 << 20 {
        *line = Vec::new();
    } else {
        line.clear();
    }
    text
}

fn exit_code(status: ExitStatus) -> i32 {
    status
        .code()
        .unwrap_or_else(|| 128 + status.signal().unwrap_or(0))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Metadata with one file in it, and a way of looking that says the file is gone the first `gone` times.
    fn looked_at(gone: u32) -> (tempfile::TempDir, u32, Result<(), TurnError>) {
        let tmp = tempfile::tempdir().unwrap();
        let git_dir = tmp.path().join(".git");
        fs::create_dir_all(git_dir.join("objects")).unwrap();
        fs::write(git_dir.join("objects").join("one"), "x").unwrap();
        let mut looks = 0;
        let result = plain_metadata(tmp.path(), &git_dir, &mut |path| {
            if path.ends_with("objects/one") {
                looks += 1;
                if looks <= gone {
                    return Err(std::io::ErrorKind::NotFound.into());
                }
            }
            fs::symlink_metadata(path)
        });
        (tmp, looks, result)
    }

    #[test]
    fn metadata_that_moves_under_the_inspection_is_inspected_again() {
        // Nothing moves: one look.
        let (_tmp, looks, result) = looked_at(0);
        assert!(result.is_ok(), "{result:?}");
        assert_eq!(looks, 1);
        // A path that was listed and is gone at the first look: the room inspects again, and it holds.
        let (_tmp, looks, result) = looked_at(1);
        assert!(result.is_ok(), "{result:?}");
        assert_eq!(looks, 2);
        // Gone at every look but the last the room allows itself.
        let (_tmp, looks, result) = looked_at(INSPECTIONS - 1);
        assert!(result.is_ok(), "{result:?}");
        assert_eq!(looks, INSPECTIONS);
    }

    #[test]
    fn metadata_that_keeps_moving_is_refused_and_named() {
        let (_tmp, looks, result) = looked_at(u32::MAX);
        assert_eq!(looks, INSPECTIONS);
        let Err(TurnError::Refused(why)) = result else {
            panic!("expected a refusal, and got {result:?}");
        };
        assert!(
            why.contains("kept changing") && why.contains(".git/objects/one"),
            "{why}"
        );
    }

    #[test]
    fn a_directory_that_goes_before_it_is_read_is_inspected_again() {
        let tmp = tempfile::tempdir().unwrap();
        let git_dir = tmp.path().join(".git");
        let objects = git_dir.join("objects");
        fs::create_dir_all(&objects).unwrap();
        let mut looks_at_the_top = 0;
        // The directory is there when it is looked at, and gone before it is read.
        let result = plain_metadata(tmp.path(), &git_dir, &mut |path| {
            let meta = fs::symlink_metadata(path);
            if path == git_dir {
                looks_at_the_top += 1;
            }
            if path == objects {
                fs::remove_dir(&objects).unwrap();
            }
            meta
        });
        assert!(result.is_ok(), "{result:?}");
        assert_eq!(looks_at_the_top, 2);
    }

    #[test]
    fn metadata_that_cannot_be_looked_at_for_another_reason_is_not_inspected_again() {
        let tmp = tempfile::tempdir().unwrap();
        let git_dir = tmp.path().join(".git");
        fs::create_dir_all(&git_dir).unwrap();
        let mut looks = 0;
        let result = plain_metadata(tmp.path(), &git_dir, &mut |_| {
            looks += 1;
            Err(std::io::ErrorKind::PermissionDenied.into())
        });
        assert_eq!(looks, 1);
        assert!(matches!(result, Err(TurnError::Io(_))), "{result:?}");
    }

    /// A private directory is made where nothing is, under another name when something is at the one tried,
    /// five names at most; anything else that stops it is said at once.
    #[test]
    fn a_private_directory_takes_another_name_when_one_is_taken() {
        let tmp = tempfile::tempdir().unwrap();
        let parent = tmp.path();
        // A file at the first name, and a link to nowhere at the second.
        fs::write(parent.join("yak-a"), "").unwrap();
        std::os::unix::fs::symlink(parent.join("nowhere"), parent.join("yak-b")).unwrap();
        let mut names = ["a", "b", "c", "d"].into_iter().map(String::from);
        let made = private_dir(parent, &mut || Ok(names.next().unwrap())).unwrap();
        assert_eq!(made, parent.join("yak-c"));
        let meta = fs::symlink_metadata(&made).unwrap();
        assert!(meta.is_dir());
        assert_eq!(meta.permissions().mode() & 0o7777, 0o700);
        assert!(
            fs::symlink_metadata(parent.join("nowhere")).is_err(),
            "made through the link"
        );
        // Five names taken: refused after five tries, and nothing made at a sixth.
        for name in ["p", "q", "r", "s", "t"] {
            fs::create_dir(parent.join(format!("yak-{name}"))).unwrap();
        }
        let mut tried = 0;
        let mut names = ["p", "q", "r", "s", "t", "u"].into_iter().map(String::from);
        let refused = private_dir(parent, &mut || {
            tried += 1;
            Ok(names.next().unwrap())
        });
        assert!(matches!(refused, Err(TurnError::Refused(_))), "{refused:?}");
        assert_eq!(tried, 5);
        assert!(fs::symlink_metadata(parent.join("yak-u")).is_err());
        // A parent that is not there is no taken name: said at once.
        let mut tried = 0;
        let lost = private_dir(&parent.join("missing"), &mut || {
            tried += 1;
            Ok(format!("n{tried}"))
        });
        assert!(matches!(lost, Err(TurnError::Io(_))), "{lost:?}");
        assert_eq!(tried, 1);
    }

    #[test]
    fn a_search_path_keeps_only_its_absolute_entries() {
        let kept = |path: &str| absolute_entries(OsStr::new(path)).into_string().unwrap();
        assert_eq!(kept("/usr/bin:/bin"), "/usr/bin:/bin");
        // An empty entry and `.` both mean the directory a program starts in.
        assert_eq!(kept(".:/usr/bin:/bin"), "/usr/bin:/bin");
        assert_eq!(kept(":/usr/bin::/bin:"), "/usr/bin:/bin");
        assert_eq!(kept("bin:../tools:/opt/x/bin"), "/opt/x/bin");
        // With nothing left, a run still finds the system's own programs.
        assert_eq!(kept(""), PLAIN_PATH);
        assert_eq!(kept(".:bin"), PLAIN_PATH);
    }

    /// The room keeps no more of a git command's output than its limit. A command that prints more is refused
    /// and ended at once: nothing past the limit is read. What a command says of a failure is cut short and the
    /// rest dropped, and the command goes on to its own end.
    #[test]
    fn the_rooms_git_is_not_read_past_its_limit_of_output() {
        let prints = |bytes: usize| {
            let mut command = Command::new("/bin/sh");
            command.args(["-c", &format!("head -c {bytes} /dev/zero")]);
            command
        };
        // The limit itself, said once more here, so that a change to it is a change someone meant.
        assert_eq!(ROOM_GIT_OUTPUT_BYTES, 67_108_864);
        // The control: exactly the limit is read whole.
        let whole = output_within(
            prints(ROOM_GIT_OUTPUT_BYTES),
            "a read",
            Duration::from_secs(60),
            None,
        );
        assert_eq!(whole.map(|out| out.len()).ok(), Some(ROOM_GIT_OUTPUT_BYTES));
        // One byte more, and many more: refused, quickly, and not as a command that never finished. And a
        // command that prints one byte too many and then waits is ended there and then, not when its time is up.
        let mut idles = Command::new("/bin/sh");
        idles.args([
            "-c",
            &format!("head -c {} /dev/zero; sleep 600", ROOM_GIT_OUTPUT_BYTES + 1),
        ]);
        let start = Instant::now();
        let over = output_within(idles, "a read", Duration::from_secs(120), None);
        assert!(
            matches!(&over, Err(TurnError::Git(why)) if why.contains("a read printed more than")),
            "{:?}",
            over.map(|out| out.len())
        );
        assert!(
            start.elapsed() < Duration::from_secs(30),
            "{:?}",
            start.elapsed()
        );
        // The same when the program itself is done at once and something it started prints too much after it:
        // the program's own good end does not make that output acceptable.
        let mut leaves_one = Command::new("/bin/sh");
        leaves_one.args([
            "-c",
            &format!(
                "(sleep 1; head -c {} /dev/zero) & exit 0",
                ROOM_GIT_OUTPUT_BYTES + 1
            ),
        ]);
        let over = output_within(leaves_one, "a read", Duration::from_secs(120), None);
        assert!(
            matches!(&over, Err(TurnError::Git(why)) if why.contains("a read printed more than")),
            "{:?}",
            over.map(|out| out.len())
        );
        for more in [1, 8 * ROOM_GIT_OUTPUT_BYTES] {
            let start = Instant::now();
            let over = output_within(
                prints(ROOM_GIT_OUTPUT_BYTES + more),
                "a read",
                Duration::from_secs(60),
                None,
            );
            assert!(
                matches!(&over, Err(TurnError::Git(why)) if why.contains("a read printed more than")),
                "{more}: {:?}",
                over.map(|out| out.len())
            );
            assert!(
                start.elapsed() < Duration::from_secs(30),
                "{more}: {:?}",
                start.elapsed()
            );
        }
        // What a command says of its failure is cut short where it is too long, and is no refusal of itself:
        // the command goes on to its own end, which is 3 only if all it had to say was taken from it (9 if the
        // pipe was closed on it).
        let mut complains = Command::new("/bin/sh");
        complains.args([
            "-c",
            "{ head -c 3000000 /dev/zero | tr '\\000' x >&2; } && exit 3; exit 9",
        ]);
        let (status, stdout, stderr) =
            ended_within(complains, "a read", Duration::from_secs(60), None).unwrap();
        assert_eq!(status.code(), Some(3));
        assert!(stdout.is_empty());
        assert_eq!(stderr.len(), ROOM_GIT_COMPLAINT_BYTES);
    }

    #[test]
    fn the_rooms_git_is_ended_when_it_does_not_finish() {
        let mut slow = Command::new("/bin/sleep");
        slow.arg("30");
        let start = Instant::now();
        let ended = output_within(slow, "a slow read", Duration::from_millis(300), None);
        assert!(
            matches!(&ended, Err(TurnError::Git(why)) if why.contains("did not finish")),
            "{ended:?}"
        );
        assert!(start.elapsed() < Duration::from_secs(5));
        // A leader that is done at once, while something it started keeps the pipe: the limit still holds,
        // and what it started is ended with it.
        let mut leaves_one = Command::new("/bin/sh");
        leaves_one.args(["-c", "sleep 37.123 & echo started"]);
        let start = Instant::now();
        let ended = output_within(leaves_one, "a read", Duration::from_millis(500), None);
        assert!(
            matches!(&ended, Err(TurnError::Git(why)) if why.contains("did not finish")),
            "{ended:?}"
        );
        assert!(
            start.elapsed() < Duration::from_secs(5),
            "{:?}",
            start.elapsed()
        );
        thread::sleep(Duration::from_millis(300));
        // Looked for by its whole command, and not by a piece of text: a search for the text would also find
        // whatever shell was told to run this test by name.
        let all = Command::new("ps")
            .args(["-Ao", "command="])
            .output()
            .unwrap();
        let left = String::from_utf8_lossy(&all.stdout)
            .lines()
            .filter(|command| command.trim() == "sleep 37.123")
            .count();
        assert_eq!(left, 0, "the sleeper is still running");
        // One that finishes in time gives its output, and one that fails says why.
        let mut quick = Command::new("/bin/sh");
        quick.args(["-c", "echo out"]);
        assert_eq!(
            output_within(quick, "a quick read", Duration::from_secs(5), None).unwrap(),
            b"out\n"
        );
        let mut failing = Command::new("/bin/sh");
        failing.args(["-c", "echo why >&2; exit 3"]);
        let failed = output_within(failing, "a read", Duration::from_secs(5), None);
        assert!(
            matches!(&failed, Err(TurnError::Git(why)) if why.contains("why")),
            "{failed:?}"
        );
    }

    /// The switch ends the room's git as its limit does, the whole group, and at once: while the program runs,
    /// and while only its output is waited for. Set beforehand, nothing is started at all.
    #[test]
    fn the_rooms_git_is_ended_when_its_switch_is_set() {
        let sleepers = |text: &str| {
            let all = Command::new("ps")
                .args(["-Ao", "command="])
                .output()
                .unwrap();
            String::from_utf8_lossy(&all.stdout)
                .lines()
                .filter(|command| command.trim() == text)
                .count()
        };
        for (script, sleeper) in [
            // The leader itself is slow.
            ("exec sleep 41.317", "sleep 41.317"),
            // The leader is done at once, and something it started keeps the pipe.
            ("sleep 43.519 & echo started", "sleep 43.519"),
        ] {
            let stop = Arc::new(AtomicBool::new(false));
            let setter = {
                let stop = Arc::clone(&stop);
                thread::spawn(move || {
                    thread::sleep(Duration::from_millis(400));
                    stop.store(true, Ordering::Relaxed);
                })
            };
            let mut slow = Command::new("/bin/sh");
            slow.args(["-c", script]);
            let start = Instant::now();
            let ended = safe_git_output_until(slow, "a read", Duration::from_secs(30), &stop);
            let took = start.elapsed();
            setter.join().unwrap();
            assert!(
                matches!(&ended, Err(TurnError::Git(why)) if why.contains("was ended before it finished")),
                "{script}: {ended:?}"
            );
            assert!(
                took >= Duration::from_millis(300) && took < Duration::from_secs(5),
                "{script}: {took:?}"
            );
            thread::sleep(Duration::from_millis(300));
            assert_eq!(
                sleepers(sleeper),
                0,
                "{script}: the sleeper is still running"
            );
        }
        // Set before the start: nothing is started. Seen with a program that is not there: had the runner
        // tried to start it, the error would be that it could not.
        let stop = AtomicBool::new(true);
        let never = Command::new("/no/such/place/yak-never-started");
        let refused = safe_git_output_until(never, "a read", Duration::from_secs(30), &stop);
        assert!(
            matches!(&refused, Err(TurnError::Git(why)) if why.contains("was ended before it finished")),
            "{refused:?}"
        );
        // And the same program with the switch not set is what that error looks like.
        let stop = AtomicBool::new(false);
        let missing = Command::new("/no/such/place/yak-never-started");
        let failed = safe_git_output_until(missing, "a read", Duration::from_secs(30), &stop);
        assert!(matches!(&failed, Err(TurnError::Io(_))), "{failed:?}");
        // The control: with the switch never set, the same runner gives the output.
        let mut quick = Command::new("/bin/sh");
        quick.args(["-c", "echo out"]);
        let stop = AtomicBool::new(false);
        assert_eq!(
            safe_git_output_until(quick, "a read", Duration::from_secs(5), &stop).unwrap(),
            b"out\n"
        );
    }

    #[test]
    fn the_scope_caps_memory_and_hides_the_bus_from_the_program() {
        let (program, args) = scope_command_for("claude", &["-p".to_string()], 1200, false);
        assert_eq!(program, "systemd-run");
        let joined = args.join(" ");
        assert!(joined.starts_with(
            "--user --scope --quiet -p MemoryMax=2G -p MemorySwapMax=0 -p RuntimeMaxSec=1230 -- "
        ));
        assert!(
            joined.ends_with("-- env -u DBUS_SESSION_BUS_ADDRESS -u XDG_RUNTIME_DIR claude -p")
        );
    }

    /// Where `systemd-run` would rewrite the command it is given, it is told not to, before anything else it
    /// is told about the scope; and the command's own words are not touched.
    #[test]
    fn the_scope_is_told_not_to_rewrite_the_command_where_it_would() {
        let words = ["-c".to_string(), "echo $$ ${HOME}".to_string()];
        let (_, args) = scope_command_for("sh", &words, 30, true);
        let joined = args.join(" ");
        assert!(
            joined.starts_with("--user --scope --quiet --expand-environment=no -p MemoryMax=2G "),
            "{joined}"
        );
        assert!(
            joined.ends_with("XDG_RUNTIME_DIR sh -c echo $$ ${HOME}"),
            "{joined}"
        );
        // What this machine is given is one of the two, by what its own `systemd-run` knows.
        let (_, here) = scope_command("sh", &words, 30);
        let told = here.iter().any(|word| word == "--expand-environment=no");
        assert_eq!(told, scope_can_be_told_not_to_expand());
    }

    #[test]
    fn lines_are_cut_at_the_cap_and_lose_their_line_end() {
        let mut input = vec![b'a'; MAX_LINE_BYTES + 10];
        input.extend_from_slice(b"\r\nb\nlast");
        let mut lines = Vec::new();
        read_lines(&input[..], |l| {
            lines.push(l);
            true
        });
        assert_eq!(lines.len(), 3);
        assert_eq!(lines[0].len(), MAX_LINE_BYTES);
        assert_eq!(&lines[1..], ["b", "last"]);
    }
}
