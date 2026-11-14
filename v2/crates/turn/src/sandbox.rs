//! A turn's sandbox: a local clone with no remote, a scrubbed environment, and runs that end with everything
//! they started.
//!
//! Each run gets its own process group. Ending one is SIGTERM to the group, up to `TERM_GRACE_SECS` for its
//! leader to go, then SIGKILL to the group: the idea of `_end_group` in `agent/superyak_agent/runs.py`. With no
//! `unsafe`, the signal is sent by the `kill` program. A run whose leader exits on its own also has whatever it
//! left in its group killed, so a background job can neither outlive the turn nor hold its output pipe open.

use std::ffi::OsString;
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::thread;
use std::time::{Duration, Instant};

use room::limits::TERM_GRACE_SECS;

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
    pid_file: Option<PathBuf>,
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
        made.0 = None;
        Ok(Sandbox {
            dir,
            branch: branch.to_string(),
            base,
            pid_file: None,
        })
    }

    /// The commit the sandbox was made at, in full.
    pub fn base(&self) -> &str {
        &self.base
    }

    /// The commit the sandbox's HEAD is at now.
    pub fn head(&self) -> Result<String, TurnError> {
        rev_parse(&self.dir, "HEAD")
    }

    /// From now on, each run writes its process group id to `path` as decimal text as soon as it starts, and
    /// removes the file when it ends. The clock keeps it beside the sandbox, not inside the clone.
    pub fn set_pid_file(&mut self, path: PathBuf) {
        self.pid_file = Some(path);
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
        let launch = Launch::new(program, args, limit_secs);
        let (reader, writer) = std::io::pipe().map_err(io("make a pipe"))?;
        let mut command = scrubbed(&launch.program);
        command
            .args(&launch.args)
            .envs(launch.env)
            .current_dir(&self.dir)
            .stdin(Stdio::piped())
            .stdout(writer.try_clone().map_err(io("make a pipe"))?)
            .stderr(writer)
            .process_group(0);
        let mut child = command.spawn().map_err(io(format!("start {program}")))?;
        // The command holds the pipe's write ends; until it is gone the pipe never reaches its end.
        drop(command);
        let group = child.id();
        let _pid_file = match PidFile::write(self.pid_file.as_deref(), group) {
            Ok(file) => file,
            Err(e) => {
                end_group(&mut child, group);
                return Err(e);
            }
        };
        if let Some(mut input) = child.stdin.take() {
            let input_text = stdin.to_string();
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
            let now = Instant::now();
            if now >= deadline {
                timed_out = true;
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
                    return Err(io("wait for the run")(e));
                }
            }
            if closed {
                thread::sleep(wait);
            }
        };
        drain(&rx, on_line);
        Ok(RunStatus {
            exit_code: exit_code(status),
            timed_out,
        })
    }

    /// Removes the sandbox's directory, even where a worker took away its own write permission.
    pub fn destroy(self) -> Result<(), TurnError> {
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
    fn write(path: Option<&Path>, group: u32) -> Result<PidFile, TurnError> {
        let Some(path) = path else {
            return Ok(PidFile(None));
        };
        // Written whole and then renamed, so a reader never sees half a number.
        let mut partial = path.as_os_str().to_owned();
        partial.push(".partial");
        let partial = PathBuf::from(partial);
        fs::write(&partial, group.to_string()).map_err(io("write the pid file"))?;
        fs::rename(&partial, path).map_err(io("write the pid file"))?;
        Ok(PidFile(Some(path.to_path_buf())))
    }
}

impl Drop for PidFile {
    fn drop(&mut self) {
        if let Some(path) = &self.0 {
            let _ = fs::remove_file(path);
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

/// git with the scrubbed environment, no prompts, no hooks and no filesystem monitor: the turn's own git
/// commands must not run anything a worker configured in its clone.
fn git_command() -> Command {
    let mut command = scrubbed("git");
    command
        .args([
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
        ])
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
