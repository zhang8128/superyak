//! The frozen check (spec section 7). A check is frozen from the item's base commit before any turn takes the
//! item, and every verdict is reached with those frozen copies written over whatever the commit has in their
//! place, so a worker that rewrote, deleted or redirected a check's file is judged by the check as it was.

use std::fs;
use std::io::Write;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

use room::{CheckSpec, Frozen, Verdict};
use sha2::{Digest, Sha256};

use crate::sandbox::{fresh_path, git, remove_tree};
use crate::{Sandbox, TurnError, io};

/// The longest path a check may name, in bytes. The room's walks refuse longer ones too.
const MAX_PATH_BYTES: usize = 512;

/// One file of a check: its path in the repository, its bytes at base and whether it is executable.
struct CheckFile {
    path: String,
    content: Vec<u8>,
    executable: bool,
}

/// Freezes `spec` at `base_commit`: copies its files from that commit to `checks_dir/<check_hash>/`, then runs
/// the check on `base_commit` and on each wrong artifact to say which of them it fails on.
pub fn freeze(
    repo: &Path,
    base_commit: &str,
    spec: &CheckSpec,
    checks_dir: &Path,
) -> Result<Frozen, TurnError> {
    let paths = check_paths(spec)?;
    if base_commit.is_empty() || base_commit.starts_with('-') {
        return Err(TurnError::Refused(format!(
            "{base_commit:?} is not a commit"
        )));
    }
    let files = paths
        .iter()
        .map(|path| read_at(repo, base_commit, path))
        .collect::<Result<Vec<_>, _>>()?;
    let check_hash = hash_of(&spec.command, &files);
    write_frozen(checks_dir, &check_hash, &files)?;

    let scratch = fresh_path(checks_dir, ".work");
    let result = (|| {
        let red = |commit: &str| -> Result<bool, TurnError> {
            Ok(!run_check(repo, commit, spec, &check_hash, checks_dir, &scratch)?.passed)
        };
        let red_on_base = red(base_commit)?;
        let red_on_wrong = spec
            .wrong_artifacts
            .iter()
            .map(|commit| red(commit))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Frozen {
            check_hash: check_hash.clone(),
            red_on_base,
            red_on_wrong,
        })
    })();
    remove_tree(&scratch)?;
    result
}

/// Runs the check frozen as `check_hash` on `commit`: in a fresh clone under `work` (a scratch directory, made
/// if missing and left empty), with the frozen copies written over the same paths, by `sh -c` at the clone's
/// root, for at most `spec.timeout_secs`. The verdict names the commit in full and hashes the check's output.
pub fn run_check(
    repo: &Path,
    commit: &str,
    spec: &CheckSpec,
    check_hash: &str,
    checks_dir: &Path,
    work: &Path,
) -> Result<Verdict, TurnError> {
    let paths = check_paths(spec)?;
    if check_hash.len() != 64
        || !check_hash
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(TurnError::Refused(format!(
            "{check_hash:?} is not a check hash"
        )));
    }
    let frozen_dir = checks_dir.join(check_hash);
    let files = paths
        .iter()
        .map(|path| read_frozen(&frozen_dir, path))
        .collect::<Result<Vec<_>, _>>()?;
    if hash_of(&spec.command, &files) != check_hash {
        return Err(TurnError::Refused(format!(
            "the frozen copies in {} do not match their hash",
            frozen_dir.display()
        )));
    }
    fs::create_dir_all(work).map_err(io("make the check's work directory"))?;
    let sandbox = Sandbox::create(repo, commit, &fresh_path(work, "check"), "check")?;
    let result = judge(&sandbox, spec, &files, check_hash);
    let removed = sandbox.destroy();
    let verdict = result?;
    removed?;
    Ok(verdict)
}

fn judge(
    sandbox: &Sandbox,
    spec: &CheckSpec,
    files: &[CheckFile],
    check_hash: &str,
) -> Result<Verdict, TurnError> {
    for file in files {
        place(&sandbox.dir, file)?;
    }
    let mut output = Sha256::new();
    let args = ["-c".to_string(), spec.command.clone()];
    let status = sandbox.run("sh", &args, "", spec.timeout_secs, &mut |line| {
        output.update(line.as_bytes());
        output.update(b"\n");
    })?;
    Ok(Verdict {
        passed: status.exit_code == 0 && !status.timed_out,
        exit_code: status.exit_code,
        timed_out: status.timed_out,
        commit: sandbox.base().to_string(),
        check_hash: check_hash.to_string(),
        output_sha256: hex(&output.finalize()),
    })
}

/// The SHA-256 of the command, a newline, then each file sorted by path as the path, a NUL, the hex SHA-256 of
/// its content and a newline.
fn hash_of(command: &str, files: &[CheckFile]) -> String {
    let mut hash = Sha256::new();
    hash.update(command.as_bytes());
    hash.update(b"\n");
    for file in files {
        hash.update(file.path.as_bytes());
        hash.update([0]);
        hash.update(hex(&Sha256::digest(&file.content)).as_bytes());
        hash.update(b"\n");
    }
    hex(&hash.finalize())
}

pub(crate) fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write as _;
    let mut text = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        let _ = write!(text, "{byte:02x}");
    }
    text
}

/// The spec's files, sorted and without repeats, once each is a plain relative path; and a command and a time
/// limit that can run.
fn check_paths(spec: &CheckSpec) -> Result<Vec<String>, TurnError> {
    if spec.command.trim().is_empty() {
        return Err(TurnError::Refused("a check needs a command".to_string()));
    }
    if spec.timeout_secs == 0 {
        return Err(TurnError::Refused(
            "a check needs a time limit above zero".to_string(),
        ));
    }
    let mut paths = spec.files.clone();
    for path in &paths {
        if !plain_path(path) {
            return Err(TurnError::Refused(format!(
                "{path:?} is not a plain relative path"
            )));
        }
    }
    paths.sort();
    paths.dedup();
    Ok(paths)
}

/// A relative path of named components, none of them `.`, `..` or `.git`, with no NUL, line end or carriage
/// return, and no longer than `MAX_PATH_BYTES`.
pub(crate) fn plain_path(path: &str) -> bool {
    !path.is_empty()
        && path.len() <= MAX_PATH_BYTES
        && !path.contains(['\0', '\n', '\r'])
        && path
            .split('/')
            .all(|c| !c.is_empty() && c != "." && c != ".." && !c.eq_ignore_ascii_case(".git"))
}

/// A file's bytes and mode at `commit`, which must be a regular tracked file there.
fn read_at(repo: &Path, commit: &str, path: &str) -> Result<CheckFile, TurnError> {
    let listing = git(
        repo,
        &["--literal-pathspecs", "ls-tree", "-z", commit, "--", path],
    )?;
    let entry = listing
        .split(|&b| b == 0)
        .filter_map(|e| {
            let tab = e.iter().position(|&b| b == b'\t')?;
            (&e[tab + 1..] == path.as_bytes())
                .then(|| String::from_utf8_lossy(&e[..tab]).into_owned())
        })
        .next();
    let executable = match entry.as_deref().and_then(|meta| meta.split(' ').next()) {
        Some("100644") => false,
        Some("100755") => true,
        Some(mode) => {
            return Err(TurnError::Refused(format!(
                "{path:?} is not a regular file at {commit} (mode {mode})"
            )));
        }
        None => {
            return Err(TurnError::Refused(format!(
                "{path:?} is not tracked at {commit}"
            )));
        }
    };
    let content = git(repo, &["cat-file", "blob", &format!("{commit}:{path}")])?;
    Ok(CheckFile {
        path: path.to_string(),
        content,
        executable,
    })
}

fn read_frozen(frozen_dir: &Path, path: &str) -> Result<CheckFile, TurnError> {
    let file = frozen_dir.join(path);
    let meta =
        fs::symlink_metadata(&file).map_err(io(format!("read the frozen copy of {path}")))?;
    if !meta.is_file() {
        return Err(TurnError::Refused(format!(
            "the frozen copy of {path:?} is not a file"
        )));
    }
    let content = fs::read(&file).map_err(io(format!("read the frozen copy of {path}")))?;
    Ok(CheckFile {
        path: path.to_string(),
        content,
        executable: meta.permissions().mode() & 0o111 != 0,
    })
}

/// Writes the frozen copies to `checks_dir/<check_hash>/`, all at once: into a fresh directory that is then
/// renamed into place. A directory already there that holds the same copies is kept; anything else is replaced.
fn write_frozen(checks_dir: &Path, check_hash: &str, files: &[CheckFile]) -> Result<(), TurnError> {
    let target = checks_dir.join(check_hash);
    let intact = files.iter().all(|f| {
        read_frozen(&target, &f.path)
            .is_ok_and(|kept| kept.content == f.content && kept.executable == f.executable)
    });
    if intact && target.is_dir() {
        return Ok(());
    }
    fs::create_dir_all(checks_dir).map_err(io("make the checks directory"))?;
    let partial = fresh_path(checks_dir, ".freeze");
    fs::create_dir(&partial).map_err(io("make a frozen copy"))?;
    let written = files.iter().try_for_each(|file| place(&partial, file));
    let moved = written.and_then(|()| {
        if fs::symlink_metadata(&target).is_ok() {
            remove_tree(&target)?;
        }
        fs::rename(&partial, &target).map_err(io("put the frozen copies in place"))
    });
    if moved.is_err() {
        let _ = remove_tree(&partial);
    }
    moved
}

/// Writes `file` under `root`, replacing whatever is in the way (a file where a directory belongs, a link, a
/// directory where the file belongs) and never following a link.
fn place(root: &Path, file: &CheckFile) -> Result<(), TurnError> {
    let mut at = root.to_path_buf();
    let mut parts = file.path.split('/').peekable();
    while let Some(part) = parts.next() {
        at.push(part);
        let last = parts.peek().is_none();
        match fs::symlink_metadata(&at) {
            Ok(meta) if meta.is_dir() && !last => continue,
            Ok(meta) if meta.is_dir() => remove_tree(&at)?,
            Ok(_) => {
                fs::remove_file(&at).map_err(io(format!("clear the way for {}", file.path)))?
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(io(format!("look at {}", file.path))(e)),
        }
        if !last {
            fs::create_dir(&at).map_err(io(format!("make the directory for {}", file.path)))?;
        }
    }
    write_new(&at, file)
}

fn write_new(at: &PathBuf, file: &CheckFile) -> Result<(), TurnError> {
    let mode = if file.executable { 0o755 } else { 0o644 };
    let what = || format!("write the frozen copy of {}", file.path);
    let mut out = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(mode)
        .open(at)
        .map_err(io(what()))?;
    out.write_all(&file.content).map_err(io(what()))?;
    // The mode exactly, whatever the umask took away.
    fs::set_permissions(at, fs::Permissions::from_mode(mode)).map_err(io(what()))
}
