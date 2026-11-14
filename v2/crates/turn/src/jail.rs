//! An OS-level jail for runs the room does not trust: a check, and the room's own git in a worker's tree.
//!
//! Inside the jail a process can read files, start programs, and write only in its checkout and a scratch
//! directory. It can reach no network, signal nothing outside, and ask nothing of the system's services:
//! everything not named here is denied. With no way to send or keep anything, what a run learns cannot leave
//! it: only its exit code and the hash of its output do. Named directories can be hidden from reading as well.
//!
//! On macOS this is `sandbox-exec` with a profile that denies by default. On Linux it is `bwrap` with only the
//! system directories and named tool directories visible, every namespace private, and nothing it started able
//! to outlive it. With neither tool, `Jail::new` refuses. Nothing here falls back to running unjailed.
//!
//! The caller starts the jailed program with a cleared environment. The Linux form relies on that: it does not
//! clear the environment itself.

use std::path::{Path, PathBuf};

use crate::TurnError;

const SEATBELT: &str = "/usr/bin/sandbox-exec";
const BUBBLEWRAP_DIRS: [&str; 3] = ["/usr/bin", "/bin", "/usr/local/bin"];

/// What a jailed run on Linux can see of the system, read-only. A directory that does not exist is left out.
const LINUX_SYSTEM_DIRS: [&str; 6] = ["/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"];

/// Which tool makes the jail on this machine.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    /// macOS `sandbox-exec`.
    Seatbelt,
    /// Linux `bwrap`.
    Bubblewrap,
}

/// A jail around one checkout: where a run may write, what else it may read, and what it may not.
#[derive(Debug, Clone)]
pub struct Jail {
    kind: Kind,
    tool: PathBuf,
    checkout: PathBuf,
    scratch: PathBuf,
    readable: Vec<PathBuf>,
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
            readable: Vec::new(),
            hidden: Vec::new(),
        })
    }

    /// Also lets the run read `dir`, for a toolchain or vendored code outside the system directories. On macOS
    /// a run can already read everything not hidden, so this changes nothing there. A directory that does not
    /// exist is left out.
    pub fn allow_read(mut self, dir: &Path) -> Result<Jail, TurnError> {
        if dir.exists() {
            self.readable.push(real_dir(dir)?);
        }
        Ok(self)
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
            Kind::Bubblewrap => {
                let mut args = self.bubblewrap_args();
                args.push("--".to_string());
                args
            }
        };
        wrapped.push(program.to_string());
        wrapped.extend(args.iter().cloned());
        (self.tool.clone(), wrapped)
    }

    /// Deny everything, then allow: starting programs, signalling what is in the same jail, reading files and
    /// system settings, and writing in the two directories and to the null devices. Of the device files it may
    /// read only the null, zero and random devices and its own open files, so no terminal. It may look up no
    /// system service and make no named semaphore, which would be shared with every process outside. Where two
    /// rules match, the later one decides.
    fn seatbelt_profile(&self) -> String {
        let mut profile = String::from(
            "(version 1)\n\
             (deny default)\n\
             (allow process-exec)\n\
             (allow process-fork)\n\
             (allow signal (target same-sandbox))\n\
             (allow sysctl-read)\n\
             (allow file-read*)\n\
             (deny file-read* (subpath \"/dev\"))\n\
             (allow file-read* (literal \"/dev\") (literal \"/dev/null\") (literal \"/dev/zero\") \
             (literal \"/dev/random\") (literal \"/dev/urandom\") (subpath \"/dev/fd\"))\n\
             (allow file-write*",
        );
        for dir in [&self.checkout, &self.scratch] {
            profile.push_str(&format!(" (subpath {})", quoted(dir)));
        }
        profile.push_str(
            " (literal \"/dev/null\") (literal \"/dev/zero\"))\n\
             (deny file-read* file-write* (literal \"/dev/tty\"))\n",
        );
        for dir in &self.hidden {
            profile.push_str(&format!("(deny file-read* (subpath {}))\n", quoted(dir)));
        }
        profile
    }

    /// Only the system directories and the named ones, read-only; the two directories writable; an empty
    /// directory over `/tmp`, `/run` and each hidden one; every namespace private; no capabilities; its own
    /// session, so it has no terminal; and gone when its parent goes.
    fn bubblewrap_args(&self) -> Vec<String> {
        let mut args: Vec<String> = [
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--cap-drop",
            "ALL",
        ]
        .iter()
        .map(|s| s.to_string())
        .collect();
        for dir in LINUX_SYSTEM_DIRS {
            args.extend([
                "--ro-bind-try".to_string(),
                dir.to_string(),
                dir.to_string(),
            ]);
        }
        args.extend(
            [
                "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", "/run",
            ]
            .map(String::from),
        );
        for dir in &self.readable {
            let dir = text(dir);
            args.extend(["--ro-bind".to_string(), dir.clone(), dir]);
        }
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

    fn sample(kind: Kind) -> Jail {
        Jail {
            kind,
            tool: PathBuf::from("/jail-tool"),
            checkout: PathBuf::from("/room/checkout"),
            scratch: PathBuf::from("/room/scratch"),
            readable: vec![PathBuf::from("/tools")],
            hidden: vec![PathBuf::from("/home/someone/keys")],
        }
    }

    #[test]
    fn a_quote_or_backslash_in_a_path_is_escaped() {
        assert_eq!(quoted(Path::new("/a\"b\\c")), "\"/a\\\"b\\\\c\"");
    }

    #[test]
    fn the_macos_profile_denies_by_default_and_names_what_it_allows() {
        let profile = sample(Kind::Seatbelt).seatbelt_profile();
        assert!(profile.starts_with("(version 1)\n(deny default)\n"));
        assert!(!profile.contains("(allow default)"));
        // Nothing is allowed without a filter except these.
        for line in profile
            .lines()
            .filter(|l| l.starts_with("(allow ") && !l.contains(" ("))
        {
            assert!(
                [
                    "(allow process-exec)",
                    "(allow process-fork)",
                    "(allow sysctl-read)",
                    "(allow file-read*)"
                ]
                .contains(&line),
                "an unfiltered allow that is not on the list: {line}"
            );
        }
        // No network, no terminal, no system service, and nothing shared between processes.
        assert!(!profile.contains("network"));
        assert!(!profile.contains("ipc-"));
        assert!(profile.contains("(deny file-read* (subpath \"/dev\"))"));
        assert!(!profile.contains("mach-lookup") && !profile.contains("global-name"));
        assert!(profile.contains("(deny file-read* file-write* (literal \"/dev/tty\"))"));
        assert!(profile.contains("(deny file-read* (subpath \"/home/someone/keys\"))"));
    }

    #[test]
    fn the_linux_form_shows_only_system_and_named_directories() {
        let args = sample(Kind::Bubblewrap).bubblewrap_args();
        let joined = args.join(" ");
        assert!(joined.contains("--unshare-all"));
        assert!(joined.contains("--cap-drop ALL"));
        assert!(joined.contains("--new-session"));
        assert!(joined.contains("--die-with-parent"));
        // The whole machine is never bound, and the usual homes of sockets are empty directories.
        assert!(!joined.contains("--ro-bind / /") && !joined.contains("--bind / /"));
        assert!(joined.contains("--tmpfs /tmp") && joined.contains("--tmpfs /run"));
        assert!(joined.contains("--ro-bind /tools /tools"));
        assert!(joined.contains("--bind /room/checkout /room/checkout"));
        assert!(joined.contains("--tmpfs /home/someone/keys"));
        // Every writable bind is one of the two directories.
        let writable: Vec<&str> = args
            .windows(2)
            .filter(|w| w[0] == "--bind")
            .map(|w| w[1].as_str())
            .collect();
        assert_eq!(writable, ["/room/checkout", "/room/scratch"]);
    }
}
