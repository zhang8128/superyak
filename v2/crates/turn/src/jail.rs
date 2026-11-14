//! An OS-level jail for runs the room does not trust: a check, and the room's own git in a worker's tree.
//!
//! Inside the jail a process can read most of the machine. It can write only in its checkout and a scratch
//! directory, reach no network, and signal nothing outside. With reading open but no way to send or keep
//! anything, what a run learns cannot leave it: only its exit code and the hash of its output do. Named
//! directories can be hidden from reading as well.
//!
//! On macOS this is `sandbox-exec` with a profile that allows by default and then denies. On Linux it is
//! `bwrap`, which also gives the run its own process namespace, so nothing it started outlives it. With neither
//! tool, `Jail::new` refuses. Nothing here falls back to running unjailed.

use std::path::{Path, PathBuf};

use crate::TurnError;

const SEATBELT: &str = "/usr/bin/sandbox-exec";
const BUBBLEWRAP_DIRS: [&str; 3] = ["/usr/bin", "/bin", "/usr/local/bin"];

/// Which tool makes the jail on this machine.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    /// macOS `sandbox-exec`.
    Seatbelt,
    /// Linux `bwrap`.
    Bubblewrap,
}

/// A jail around one checkout: where a run may write, and what it may not read.
#[derive(Debug, Clone)]
pub struct Jail {
    kind: Kind,
    tool: PathBuf,
    checkout: PathBuf,
    scratch: PathBuf,
    hidden: Vec<PathBuf>,
}

impl Jail {
    /// The jail tool this machine has, if any.
    pub fn detect() -> Option<(Kind, PathBuf)> {
        if cfg!(target_os = "macos") && Path::new(SEATBELT).is_file() {
            return Some((Kind::Seatbelt, PathBuf::from(SEATBELT)));
        }
        if cfg!(target_os = "linux") {
            for dir in BUBBLEWRAP_DIRS {
                let tool = Path::new(dir).join("bwrap");
                if tool.is_file() {
                    return Some((Kind::Bubblewrap, tool));
                }
            }
        }
        None
    }

    /// A jail whose run may write only under `checkout` and `scratch`. Both must be existing directories.
    pub fn new(checkout: &Path, scratch: &Path) -> Result<Jail, TurnError> {
        let (kind, tool) = Self::detect().ok_or_else(|| {
            TurnError::Refused(
                "no jail on this machine: it needs sandbox-exec on macOS or bwrap on Linux".into(),
            )
        })?;
        Ok(Jail {
            kind,
            tool,
            checkout: real_dir(checkout)?,
            scratch: real_dir(scratch)?,
            hidden: Vec::new(),
        })
    }

    /// Also hides `dir` from reading. A directory that does not exist is left out.
    pub fn hide(mut self, dir: &Path) -> Result<Jail, TurnError> {
        if dir.exists() {
            self.hidden.push(real_dir(dir)?);
        }
        Ok(self)
    }

    pub fn kind(&self) -> Kind {
        self.kind
    }

    /// The program and arguments that run `program args` inside this jail.
    pub fn command(&self, program: &str, args: &[String]) -> (PathBuf, Vec<String>) {
        let mut wrapped = match self.kind {
            Kind::Seatbelt => vec!["-p".to_string(), self.seatbelt_profile()],
            Kind::Bubblewrap => self.bubblewrap_args(),
        };
        if self.kind == Kind::Bubblewrap {
            wrapped.push("--".to_string());
        }
        wrapped.push(program.to_string());
        wrapped.extend(args.iter().cloned());
        (self.tool.clone(), wrapped)
    }

    /// Allow everything, then take away the network, signals to anything outside, and writing anywhere but the
    /// two directories. In this language the last rule that matches decides.
    fn seatbelt_profile(&self) -> String {
        let mut profile = String::from(
            "(version 1)\n\
             (allow default)\n\
             (deny network*)\n\
             (deny signal)\n\
             (allow signal (target same-sandbox))\n\
             (deny file-write*)\n\
             (allow file-write*",
        );
        for dir in [&self.checkout, &self.scratch] {
            profile.push_str(&format!(" (subpath {})", quoted(dir)));
        }
        for device in ["/dev/null", "/dev/zero", "/dev/tty", "/dev/dtracehelper"] {
            profile.push_str(&format!(" (literal \"{device}\")"));
        }
        profile.push_str(")\n");
        for dir in &self.hidden {
            profile.push_str(&format!("(deny file-read* (subpath {}))\n", quoted(dir)));
        }
        profile
    }

    /// The whole machine read-only, the two directories writable, an empty directory over each hidden one, and
    /// private network, process, IPC and host-name namespaces.
    fn bubblewrap_args(&self) -> Vec<String> {
        let mut args: Vec<String> = [
            "--die-with-parent",
            "--new-session",
            "--unshare-net",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--ro-bind",
            "/",
            "/",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
        ]
        .iter()
        .map(|s| s.to_string())
        .collect();
        for dir in [&self.checkout, &self.scratch] {
            let dir = text(dir);
            args.extend(["--bind".to_string(), dir.clone(), dir]);
        }
        for dir in &self.hidden {
            args.extend(["--tmpfs".to_string(), text(dir)]);
        }
        args
    }
}

/// The real, absolute form of an existing directory, refused if it cannot be written safely into a jail's rules.
fn real_dir(path: &Path) -> Result<PathBuf, TurnError> {
    if !path.is_absolute() {
        return Err(TurnError::Refused(format!(
            "a jail's directory must be absolute: {}",
            path.display()
        )));
    }
    let real = path.canonicalize().map_err(|e| {
        TurnError::Refused(format!(
            "a jail's directory must exist: {}: {e}",
            path.display()
        ))
    })?;
    if !real.is_dir() {
        return Err(TurnError::Refused(format!(
            "a jail's directory must be a directory: {}",
            real.display()
        )));
    }
    match real.to_str() {
        Some(s) if !s.contains(['\n', '\r', '\0']) => Ok(real),
        _ => Err(TurnError::Refused(
            "a jail's directory must be plain text on one line".into(),
        )),
    }
}

fn text(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

/// A path as a string in the macOS profile language: backslash and double quote are escaped.
fn quoted(path: &Path) -> String {
    let mut out = String::from("\"");
    for ch in text(path).chars() {
        if matches!(ch, '\\' | '"') {
            out.push('\\');
        }
        out.push(ch);
    }
    out.push('"');
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_quote_or_backslash_in_a_path_is_escaped() {
        assert_eq!(quoted(Path::new("/a\"b\\c")), "\"/a\\\"b\\\\c\"");
    }
}
