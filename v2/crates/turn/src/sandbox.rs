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
use std::sync::{Arc, OnceLock};
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

/// The shell that starts a run, by its full path: it runs before the jail is entered, in a worker's checkout,
/// so it is never looked up.
const BOOTSTRAP_SHELL: &str = "/bin/sh";

/// The search path a run gets when the clock's has no absolute entry.
const PLAIN_PATH: &str = "/usr/bin:/bin";

/// How long the room's own git may take. It is long, for a large clone; what matters is that it is not for
/// ever, whatever a worker left in a repository the room reads.
pub const ROOM_GIT_SECS: u64 = 600;

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
        })
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
        let mut pending = vec![git_dir.clone()];
        while let Some(path) = pending.pop() {
            let meta = fs::symlink_metadata(&path).map_err(io("inspect git metadata"))?;
            if meta.is_symlink() {
                return Err(TurnError::Refused(
                    "git metadata must contain no symbolic links".into(),
                ));
            }
            // A named pipe where a ref should be would hold git, which opens a ref to read it, until
            // somebody wrote to the pipe. Nothing but files and directories belongs here.
            if !meta.is_dir() && !meta.is_file() {
                return Err(TurnError::Refused(format!(
                    "git metadata must hold only files and directories: {} is neither",
                    path.strip_prefix(&self.dir).unwrap_or(&path).display()
                )));
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
        self.own()?;
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
        let mut timed_out = false;
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
    /// and the scratch directory a jailed run was given. Only those. If something else is at either path by
    /// now, it is not the room's to remove: it is left as it is, the rest is still removed, and the error
    /// (`TurnError::Left`) holds the paths that were left, for a caller that tidies around them.
    pub fn destroy(self) -> Result<(), TurnError> {
        let mut left = Vec::new();
        let scratch = self.scratch();
        // The scratch directory, when a jailed run made one and it is still that one.
        match self.scratch_id.get() {
            Some(&id) if identity(&scratch).ok() == Some(id) => remove_tree(&scratch)?,
            // Something is there that the room did not make, or that is no longer what it made.
            _ if fs::symlink_metadata(&scratch).is_ok() => left.push(scratch.clone()),
            _ => {}
        }
        // The Linux jail's filter, a file beside the scratch directory.
        let mut filter = scratch.into_os_string();
        filter.push(".filter");
        let filter = PathBuf::from(filter);
        if fs::symlink_metadata(&filter).is_ok_and(|meta| meta.is_file()) {
            fs::remove_file(&filter).map_err(io("remove the jail's filter"))?;
        }
        if identity(&self.dir).ok() == Some(self.id) {
            remove_tree(&self.dir)?;
        } else if fs::symlink_metadata(&self.dir).is_ok() {
            left.push(self.dir.clone());
        }
        if left.is_empty() {
            return Ok(());
        }
        Err(TurnError::Left(left))
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

/// Runs `command` for at most `limit` and returns its stdout. The room's own git reads repositories a worker
/// has had its hands on, and must not wait on one for ever.
///
/// The limit covers everything: the program, and its output, which something the program started may hold
/// open after the program itself is done. The program runs in a group of its own, and when the limit passes
/// the whole group is ended, so nothing it started is left. The same is done as soon as `stop` is set.
fn output_within(
    mut command: Command,
    what: &str,
    limit: Duration,
    stop: Option<&AtomicBool>,
) -> Result<Vec<u8>, TurnError> {
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
    // read when the pipe closes.
    let read = |pipe: Option<Box<dyn Read + Send>>| {
        let (done, wait) = mpsc::channel::<Vec<u8>>();
        thread::spawn(move || {
            let mut bytes = Vec::new();
            if let Some(mut pipe) = pipe {
                let _ = pipe.read_to_end(&mut bytes);
            }
            let _ = done.send(bytes);
        });
        wait
    };
    let stdout = read(
        child
            .stdout
            .take()
            .map(|p| Box::new(p) as Box<dyn Read + Send>),
    );
    let stderr = read(
        child
            .stderr
            .take()
            .map(|p| Box::new(p) as Box<dyn Read + Send>),
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
    // git usually answers in a few milliseconds, so the first looks come quickly and the later ones less often.
    let mut pause = Duration::from_millis(1);
    let status = loop {
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
    let read_out = |pipe: &mpsc::Receiver<Vec<u8>>| loop {
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
    let Some(stdout) = read_out(&stdout) else {
        return Err(late(&mut child));
    };
    let Some(stderr) = read_out(&stderr) else {
        return Err(late(&mut child));
    };
    // The program is done and so is its output. Anything it left in its group goes with it.
    signal_group(group, "KILL");
    if status.success() {
        return Ok(stdout);
    }
    let stderr = String::from_utf8_lossy(&stderr);
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
