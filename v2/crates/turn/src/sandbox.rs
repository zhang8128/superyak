//! A turn's sandbox: a local clone with no remote, a scrubbed environment, and runs that end with everything
//! they started.
//!
//! Each run gets its own process group and random environment marker. Supervision records observed
//! descendants by process identity and confirms their cleanup, including after normal exit.

use std::ffi::OsString;
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
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
/// room's own variables) is left out.
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
];

/// Where the agent programs keep their settings and sign-ins. A model worker's run keeps these; a jailed run
/// loses them, and the directories they name are hidden from it.
pub(crate) const AGENT_HOMES: [&str; 2] = ["CODEX_HOME", "CLAUDE_CONFIG_DIR"];

/// The name and address the turn's own commits carry. No person made them.
const TURN_NAME: &str = "yak turn";
const TURN_EMAIL: &str = "turn@yak.invalid";

/// The systemd scope outlives the run's own limit by this much, as a backstop (`SCOPE_SLACK` in runs.py).
const SCOPE_SLACK_SECS: u64 = 30;

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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RunStatus {
    /// The leader's exit code, or 128 plus the signal that ended it.
    pub exit_code: i32,
    pub timed_out: bool,
}

impl Sandbox {
    /// Clones `repo` into `dir` (which must not exist, or be empty) and checks out a new `branch` at
    /// `base_commit`. The clone has no remote, cannot fetch or push over any transport, runs no hooks and
    /// commits as the turn.
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
        // A name means what it means in the item's repository: the clone loses the remote's branch names.
        let base = rev_parse(repo, &format!("{base_commit}^{{commit}}"))?;
        let mut made = Remove(Some(dir.to_path_buf()));
        let mut clone = git_command();
        clone.args([
            "clone",
            "-q",
            "--no-hardlinks",
            "--local",
            "--no-checkout",
            "--",
        ]);
        clone.arg(repo).arg(dir);
        output(clone, "clone")?;
        git(dir, &["remote", "remove", "origin"])?;
        for (key, value) in [
            ("user.name", TURN_NAME),
            ("user.email", TURN_EMAIL),
            ("commit.gpgsign", "false"),
            ("tag.gpgsign", "false"),
            ("core.hooksPath", "/dev/null"),
            ("protocol.allow", "never"),
            ("credential.helper", ""),
        ] {
            git(dir, &["config", key, value])?;
        }
        git(dir, &["checkout", "-q", "-b", branch, &base])?;
        let dir = fs::canonicalize(dir).map_err(io("find the sandbox"))?;
        // The room's own copy of the clone's config, put back before the room runs git there after a worker.
        let config =
            fs::read(dir.join(".git").join("config")).map_err(io("read the clone's config"))?;
        made.0 = None;
        Ok(Sandbox {
            dir,
            branch: branch.to_string(),
            base,
            config,
            pid_file: None,
            stop: Arc::new(AtomicBool::new(false)),
        })
    }

    /// The commit the sandbox was made at, in full.
    pub fn base(&self) -> &str {
        &self.base
    }

    /// The commit the turn's branch is at now, read after `reclaim`.
    pub fn head(&self) -> Result<String, TurnError> {
        self.reclaim()?;
        rev_parse(&self.dir, &format!("refs/heads/{}", self.branch))
    }

    /// Restores the room's git configuration and branch after confirming that all metadata paths are plain.
    /// The room's git ignores system and global config, writes no reflogs and runs no hooks.
    pub fn reclaim(&self) -> Result<(), TurnError> {
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
        let mut pending = vec![git_dir.clone()];
        while let Some(path) = pending.pop() {
            let meta = fs::symlink_metadata(&path).map_err(io("inspect git metadata"))?;
            if meta.is_symlink() {
                return Err(TurnError::Refused(
                    "git metadata must contain no symbolic links".into(),
                ));
            }
            if meta.is_dir() {
                for entry in fs::read_dir(path).map_err(io("read git metadata"))? {
                    pending.push(entry.map_err(io("read git metadata entry"))?.path());
                }
            }
        }
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

    /// Each run atomically writes its group and leader start time, one per line, to this path, and
    /// removes the file after confirmed cleanup. The clock keeps it beside the clone.
    pub fn set_pid_file(&mut self, path: PathBuf) {
        self.pid_file = Some(path);
    }

    /// Recovers a run after a clock restart, confirming the stored leader identity before signalling its
    /// observed descendants. An absent or changed leader identity results in no signals.
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
        self.run_with(None, program, args, stdin, limit_secs, on_line)
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
        let scratch = self.scratch();
        fs::create_dir_all(&scratch).map_err(io("make the scratch directory"))?;
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
            Some((&jail, &scratch)),
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
        jailed: Option<(&Jail, &Path)>,
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
        let wrapped;
        let (program, args) = match jailed {
            Some((jail, _)) => {
                let (tool, tool_args) = jail.command(program, args);
                wrapped = (tool.to_string_lossy().into_owned(), tool_args);
                (wrapped.0.as_str(), wrapped.1.as_slice())
            }
            None => (program, args),
        };
        let launch = Launch::new(program, args, limit_secs);
        let marker = marker()?;
        let (reader, writer) = std::io::pipe().map_err(io("make a pipe"))?;
        // The leader waits on stdin until its identity has been recorded, then exec preserves that identity.
        let mut command = scrubbed("sh");
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
        if let Some((_, scratch)) = jailed {
            command.env("HOME", scratch).env("TMPDIR", scratch);
            for name in AGENT_HOMES {
                command.env_remove(name);
            }
        }
        command
            .stdin(Stdio::piped())
            .stdout(writer.try_clone().map_err(io("make a pipe"))?)
            .stderr(writer)
            .process_group(0);
        let mut child = command.spawn().map_err(io(format!("start {program}")))?;
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
        let mut pid_file = match PidFile::write(self.pid_file.as_deref(), &supervisor.identity) {
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
        let mut timed_out = false;
        let status = loop {
            if let Err(e) = supervisor.poll() {
                end_group(&mut child, group);
                if supervisor.end().is_ok() {
                    pid_file.remove();
                }
                return Err(e);
            }
            let now = Instant::now();
            if now >= deadline || self.stop.load(Ordering::Relaxed) {
                timed_out = now >= deadline;
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
                    if supervisor.end().is_ok() {
                        pid_file.remove();
                    }
                    return Err(io("wait for the run")(e));
                }
            }
            if closed {
                thread::sleep(wait);
            }
        };
        supervisor.end()?;
        pid_file.remove();
        drain(&rx, on_line);
        Ok(RunStatus {
            exit_code: exit_code(status),
            timed_out,
        })
    }

    /// Removes the sandbox's directory, even where a worker took away its own write permission.
    pub fn destroy(self) -> Result<(), TurnError> {
        let scratch = self.scratch();
        if fs::symlink_metadata(&scratch).is_ok() {
            remove_tree(&scratch)?;
        }
        remove_tree(&self.dir)
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
        // Written whole and then renamed, so a reader never sees half a number.
        let mut partial = path.as_os_str().to_owned();
        partial.push(".partial");
        let partial = PathBuf::from(partial);
        write_new(&partial, identity.text().as_bytes())?;
        fs::rename(&partial, path).map_err(io("write the pid file"))?;
        Ok(PidFile(Some(path.to_path_buf())))
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
    let mut argv: Vec<String> = [
        "--user",
        "--scope",
        "--quiet",
        "-p",
        "MemoryMax=2G",
        "-p",
        "MemorySwapMax=0",
        "-p",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
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

/// Whether runs can be wrapped in a memory-capped systemd scope: Linux, `systemd-run` present, and a user
/// manager that answers. Many CI machines have the program and no user manager, so it is tried once.
#[cfg(target_os = "linux")]
fn memory_cap_available() -> bool {
    static AVAILABLE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *AVAILABLE.get_or_init(|| {
        let (program, args) = scope_command("true", &[], 30);
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

/// A command with only the kept variables of the clock's environment.
pub(crate) fn scrubbed(program: impl AsRef<std::ffi::OsStr>) -> Command {
    let mut command = Command::new(program);
    command.env_clear();
    for name in ENV_KEPT {
        if let Some(value) = std::env::var_os(name) {
            command.env(name, value);
        }
    }
    command
}

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

fn output(mut command: Command, what: &str) -> Result<Vec<u8>, TurnError> {
    let out = command.output().map_err(io("start git"))?;
    if out.status.success() {
        return Ok(out.stdout);
    }
    let stderr = String::from_utf8_lossy(&out.stderr);
    let stderr: String = stderr.trim().chars().take(300).collect();
    Err(TurnError::Git(format!("{what} failed: {stderr}")))
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

    #[test]
    fn the_scope_caps_memory_and_hides_the_bus_from_the_program() {
        let (program, args) = scope_command("claude", &["-p".to_string()], 1200);
        assert_eq!(program, "systemd-run");
        let joined = args.join(" ");
        assert!(joined.starts_with(
            "--user --scope --quiet -p MemoryMax=2G -p MemorySwapMax=0 -p RuntimeMaxSec=1230 -- "
        ));
        assert!(
            joined.ends_with("-- env -u DBUS_SESSION_BUS_ADDRESS -u XDG_RUNTIME_DIR claude -p")
        );
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
