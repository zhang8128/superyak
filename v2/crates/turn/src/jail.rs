//! An OS-level jail for runs the room does not trust: a check, and the room's own git in a worker's tree.
//!
//! Inside the jail a process can read and run only what it is shown: the system's own programs and libraries,
//! its checkout, a scratch directory, and whatever else is named for it. It can write only in the checkout and
//! the scratch directory. It can reach no network, signal nothing outside, and ask nothing of the system's
//! services: everything not named here is denied. A home directory, the shared temporary directories and other
//! disks are not shown, so nobody has to list what in them is secret. A path can also be hidden inside
//! something that is shown.
//!
//! **Other processes, on macOS.** "Deny by default" does not cover questions about processes there: they are
//! answered unless denied. And a process's arguments and environment, where tokens are, come out through
//! either of two doors: those questions, or a system setting under `kern.proc`. The profile shuts both, and
//! `tests/jail.rs` holds the measurement. On Linux a jailed run's processes are numbered apart and it sees
//! no other.
//!
//! **Whom the jail holds, and whom it does not.** The jail is for code the room runs and did not write: a
//! check's command, a script worker, and the room's own git in a tree a worker has had its hands on. A model
//! worker (`claude:`, `codex:`) is not put in this jail. It runs under its own program's sandbox, which the room
//! sets to let it write in its clone and nowhere else of the room's, and to read what a jailed run is shown and
//! no more (`places`, read for it by `worker.rs`). The room's own files (`turns/`, `checks/`,
//! the store) are therefore safe from a jailed run by this module, and from a model worker only as far as that
//! program's sandbox holds. Where the room trusts one of those files it says so: a run's record is acted on
//! only for an attempt the room made, and a sandbox is removed only if it is still the directory the room made.
//! Those checks raise the bar against a file put there from outside; they are not a wall against a process
//! with the person's own authority.
//!
//! **What "the same directory" means.** A sandbox remembers which directory it made, by device and number, and
//! looks again before each run and before removing it. That catches a directory swapped between two runs. It
//! does not hold a directory still while a run is going; the jail's own rules do that for a jailed run.
//!
//! **Writing, on Linux.** A jailed run there also has an empty `/tmp`, `/run` and `/dev` of its own, and can
//! write in them. They are the run's alone, in memory, and gone with it. Nothing written there reaches the
//! machine's own.
//!
//! On macOS this is `sandbox-exec` with a profile that denies by default. On Linux it is `bwrap` with only the
//! system directories and what is named visible, every namespace private, and nothing it started able to
//! outlive it. With neither tool, `Jail::new` refuses. Nothing here falls back to running unjailed.
//!
//! The caller starts the jailed program with a cleared environment. The Linux form relies on that: it does not
//! clear the environment itself.

use std::path::{Path, PathBuf};

use crate::TurnError;

const SEATBELT: &str = "/usr/bin/sandbox-exec";
const BUBBLEWRAP_DIRS: [&str; 3] = ["/usr/bin", "/bin", "/usr/local/bin"];

/// What a jailed run on Linux can see of the system, read-only: programs, libraries and what they share. Not
/// all of `/usr`, since a machine's own services keep settings and data under `/usr/local/etc` and
/// `/usr/local/var`. A directory that does not exist is left out.
const LINUX_SYSTEM_DIRS: [&str; 17] = [
    "/usr/bin",
    "/usr/sbin",
    "/usr/lib",
    "/usr/lib32",
    "/usr/lib64",
    "/usr/libexec",
    "/usr/share",
    "/usr/include",
    "/usr/local/bin",
    "/usr/local/sbin",
    "/usr/local/lib",
    "/usr/local/share",
    "/usr/local/include",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
];

/// The names in `/etc` that ordinary tools read, and no others: `/etc` is also where a machine's services keep
/// their settings, and some of those are readable by everyone on it.
const LINUX_ETC: [&str; 23] = [
    "/etc/alternatives",
    "/etc/ca-certificates",
    "/etc/debian_version",
    "/etc/group",
    "/etc/hosts",
    "/etc/ld.so.cache",
    "/etc/ld.so.conf",
    "/etc/ld.so.conf.d",
    "/etc/localtime",
    "/etc/login.defs",
    "/etc/mime.types",
    "/etc/nsswitch.conf",
    "/etc/os-release",
    "/etc/passwd",
    "/etc/perl",
    "/etc/protocols",
    "/etc/python3",
    "/etc/services",
    "/etc/shells",
    "/etc/ssl/certs",
    "/etc/ssl/openssl.cnf",
    "/etc/terminfo",
    "/etc/timezone",
];

/// What a jailed run on macOS can read and run of the system. None of it is a place a person keeps files of
/// their own. A path that is not there is harmless.
///
/// `/System` is named part by part, and never whole: `/System/Volumes` is where the other disks are mounted,
/// the one that holds every home among them. Of it a run is shown only the system libraries' own disk image.
const MACOS_SYSTEM_DIRS: [&str; 18] = [
    "/System/Library",
    "/System/Cryptexes",
    "/System/Volumes/Preboot/Cryptexes",
    "/bin",
    "/sbin",
    "/usr/bin",
    "/usr/lib",
    "/usr/libexec",
    "/usr/sbin",
    "/usr/share",
    "/Library/Apple",
    "/Library/Developer",
    "/Library/Frameworks",
    "/private/etc/manpaths.d",
    "/private/etc/paths.d",
    "/private/etc/ssl/certs",
    "/private/var/db/timezone",
    "/private/var/select",
];

/// Where a package manager on macOS puts programs, and which parts of that a jailed run can read and run: not
/// `etc` and `var`, where services keep settings and data.
const MACOS_PACKAGE_ROOTS: [&str; 2] = ["/opt/homebrew", "/usr/local"];
const MACOS_PACKAGE_PARTS: [&str; 9] = [
    "bin",
    "sbin",
    "lib",
    "libexec",
    "opt",
    "Cellar",
    "Frameworks",
    "share",
    "include",
];

/// Single names a run on macOS reads: the root directory's own list (every program reads it as it starts), the
/// three links at the root, the link that says where the developer tools are, and the files in `/private/etc`
/// that ordinary tools read. Not all of `/private/etc`, where services keep their settings too.
const MACOS_SYSTEM_FILES: [&str; 23] = [
    "/",
    "/etc",
    "/tmp",
    "/var",
    "/private/var/db/xcode_select_link",
    "/private/etc/bashrc",
    "/private/etc/group",
    "/private/etc/hosts",
    "/private/etc/localtime",
    "/private/etc/manpaths",
    "/private/etc/passwd",
    "/private/etc/paths",
    "/private/etc/profile",
    "/private/etc/protocols",
    "/private/etc/resolv.conf",
    "/private/etc/services",
    "/private/etc/shells",
    "/private/etc/ssl/cert.pem",
    "/private/etc/ssl/openssl.cnf",
    "/private/etc/ssl/x509v3.cnf",
    "/private/etc/zprofile",
    "/private/etc/zshenv",
    "/private/etc/zshrc",
];

/// The system settings a jailed run on macOS can read: the machine's hardware, and the system's version and
/// limits. Nothing under `kern.proc`: that is the table of every process of the person, and one of the two
/// ways to another process's arguments and environment.
const MACOS_SETTING_GROUPS: [&str; 6] = [
    "hw.",
    "kern.os",
    "machdep.",
    "security.mac.",
    "sysctl.",
    "vm.",
];
const MACOS_SETTINGS: [&str; 10] = [
    "kern.argmax",
    "kern.boottime",
    "kern.clockrate",
    "kern.hostname",
    "kern.maxfilesperproc",
    "kern.maxproc",
    "kern.ngroups",
    "kern.secure_kernel",
    "kern.usrstack64",
    "kern.version",
];

/// Places in a home that hold keys, tokens and agent settings. A run is not shown the home at all; these stay
/// hidden even when a directory that holds one is named for it (`~/.cargo` for a toolchain, say).
const HOME_SECRETS: [&str; 19] = [
    ".ssh",
    ".aws",
    ".gnupg",
    ".config",
    ".docker",
    ".kube",
    ".claude",
    ".codex",
    ".superyak",
    ".engram",
    ".netrc",
    ".git-credentials",
    ".npmrc",
    ".pypirc",
    ".cargo/credentials",
    ".cargo/credentials.toml",
    ".local/share",
    ".password-store",
    "Library/Keychains",
];

/// Whether the room jails what it does not trust. It does, unless `YAK_JAIL` is `off`. That switch exists for
/// tests that must run inside another sandbox, where no jail can be entered. A clock that runs model workers
/// must refuse to start with it set.
pub fn wanted() -> bool {
    wanted_from(std::env::var("YAK_JAIL").ok().as_deref())
}

fn wanted_from(value: Option<&str>) -> bool {
    value != Some("off")
}

/// The jail the room puts around `checkout`. Each path in `YAK_JAIL_READ` (separated by colons) is shown to it,
/// for a toolchain outside the system directories. The home's keys and tokens, and the directories the agent
/// programs keep their settings in, stay hidden whatever is shown.
///
/// A path in `YAK_JAIL_READ` is refused when it is not absolute, is not there, holds the home directory, is
/// hidden, or holds a place where keys or settings are kept, whether or not anything is there yet. One that
/// was silently left out would look like a missing tool, and the home would show everything the jail is for.
/// So a toolchain is named by its own directory (`~/.cargo/bin`), not by one above it (`~/.cargo`, which is
/// also where a credentials file goes).
pub fn for_checkout(checkout: &Path, scratch: &Path) -> Result<Jail, TurnError> {
    let settings = Settings::read()?;
    let mut jail = Jail::new(checkout, scratch)?;
    for path in &settings.hidden {
        jail = jail.hide(path)?;
    }
    for path in &settings.shown {
        jail = jail.allow_read(path)?;
    }
    Ok(jail)
}

/// Whether a jail can be made on this machine with the settings as they are, without making one. A clock asks
/// before its first turn, so that a wrong `YAK_JAIL_READ` entry or a machine with no jail tool is said at the
/// start, and not as a check that mysteriously cannot be frozen. Nothing is written.
pub fn check_settings() -> Result<(), TurnError> {
    let (kind, _) = Jail::detect().ok_or_else(no_jail_tool)?;
    if kind == Kind::Bubblewrap && crate::filter::this_machine().is_none() {
        return Err(unknown_machine());
    }
    Settings::read().map(|_| ())
}

fn no_jail_tool() -> TurnError {
    TurnError::Refused(
        "no jail on this machine: it needs sandbox-exec on macOS or bwrap on Linux".into(),
    )
}

fn unknown_machine() -> TurnError {
    TurnError::Refused(
        "no jail on this kind of machine: its system calls are not known here".into(),
    )
}

/// What the room's jail hides and shows on this machine, for a run the room puts in its own program's sandbox
/// and not in the jail: a model worker's. Its shell is to be shown what a jailed run is shown, and no more.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Places {
    /// The home, as a real path.
    pub home: PathBuf,
    /// The home's keys and settings, and the agents' settings directories, that are there, as real paths.
    pub hidden: Vec<PathBuf>,
    /// Each directory named in `YAK_JAIL_READ`, as a real path.
    pub shown: Vec<PathBuf>,
    /// The system directories every jailed run on this machine is shown, those that are there, named as the
    /// jail names them.
    pub system: Vec<PathBuf>,
}

/// The jail's places, read as `for_checkout` reads them and refused where it refuses: one reading of the
/// settings and the lists the jail already has, not a second copy of either.
pub fn places() -> Result<Places, TurnError> {
    let Settings {
        home,
        hidden,
        shown,
        system,
    } = Settings::read()?;
    Ok(Places {
        home,
        hidden,
        shown,
        system,
    })
}

/// What the environment says the room's jail hides and shows, checked.
struct Settings {
    /// The home, as a real path.
    home: PathBuf,
    /// The home's keys and tokens and the agents' settings directories: the ones that are there, as real paths.
    hidden: Vec<PathBuf>,
    /// Each path in `YAK_JAIL_READ`, as a real path.
    shown: Vec<PathBuf>,
    /// The directories every run on this machine is shown, those that are there. None where the machine has no
    /// jail tool, which a jail itself refuses (`Jail::new`).
    system: Vec<PathBuf>,
}

impl Settings {
    fn read() -> Result<Settings, TurnError> {
        // The jail keeps a home out by knowing where it is. With none it would hide nothing and refuse nothing,
        // so it does not start.
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .filter(|home| home.is_absolute())
            .and_then(|home| home.canonicalize().ok())
            .filter(|home| home.is_dir())
            .ok_or_else(|| {
                TurnError::Refused(
                    "the jail needs HOME to be the full path of a directory that exists: it keeps a home out \
                     by knowing where it is"
                        .into(),
                )
            })?;
        // Every protected name, whether or not anything is there now, and those that are there as real paths.
        let mut protected = Vec::new();
        let mut hidden = Vec::new();
        let mut hide = |path: &Path| -> Result<(), TurnError> {
            // Every place the name could come to be: a directory on the way to it may be a link.
            protected.extend(places_of(path)?);
            if path.exists() {
                hidden.push(real_path(path)?);
            }
            Ok(())
        };
        for name in HOME_SECRETS {
            hide(&home.join(name))?;
        }
        for name in crate::sandbox::AGENT_HOMES {
            if let Some(dir) = std::env::var_os(name).map(PathBuf::from) {
                if !dir.is_absolute() {
                    return Err(TurnError::Refused(format!(
                        "{name} must be a full path for the jail to hide it: it is {}",
                        dir.display()
                    )));
                }
                hide(&dir)?;
            }
        }
        // A directory every run is shown is shown as it is when the run starts, like one that was named. A place
        // where keys or settings would be kept must not lie in one, unless what is there now is already hidden:
        // then whatever is put there later is hidden with it.
        // Whether the jail's own rules on this machine tell capital letters from small.
        let folds = matches!(Jail::detect(), Some((Kind::Seatbelt, _)));
        if let Some((kind, _)) = Jail::detect()
            && let Some((place, dir)) =
                shown_by_default(&always_shown(kind), &protected, &hidden, folds)
        {
            return Err(TurnError::Refused(format!(
                "{} is where keys or settings are kept, or would be, and {}, which every run is shown, would \
                 show it: the jail does not start beside it",
                place.display(),
                dir.display()
            )));
        }
        let mut shown = Vec::new();
        if let Some(list) = std::env::var_os("YAK_JAIL_READ") {
            for path in std::env::split_paths(&list).filter(|p| !p.as_os_str().is_empty()) {
                let refuse = |why: &str| {
                    TurnError::Refused(format!("YAK_JAIL_READ names {}, {why}", path.display()))
                };
                if !path.is_absolute() {
                    return Err(refuse("which is not an absolute path"));
                }
                let real = path
                    .canonicalize()
                    .map_err(|_| refuse("which is not there"))?;
                if real.parent().is_none() || inside(&home, &real, folds) {
                    return Err(refuse(
                        "which holds the home directory: name the tool's own directory",
                    ));
                }
                if let Some(hidden) = hidden.iter().find(|hidden| inside(&real, hidden, folds)) {
                    return Err(refuse(&format!(
                        "which is hidden from every run: {} holds keys or settings",
                        hidden.display()
                    )));
                }
                // A jail is given a directory as it is when the run starts. A secret that appears in it
                // afterwards would be shown with the rest, and on Linux cannot be covered once the run is
                // going. So a directory that holds a protected name, or could, is not named at all.
                if let Some(inside) = protected
                    .iter()
                    .chain(&hidden)
                    .find(|protected| inside(protected, &real, folds))
                {
                    return Err(refuse(&format!(
                        "which would also show {}, where keys or settings are kept, if that is ever there: \
                         name the tool's own directory inside it",
                        inside.display()
                    )));
                }
                shown.push(real_path(&real)?);
            }
        }
        let system = match Jail::detect() {
            Some((kind, _)) => always_shown(kind)
                .into_iter()
                .filter(|dir| dir.exists())
                .collect(),
            None => Vec::new(),
        };
        Ok(Settings {
            home,
            hidden,
            shown,
            system,
        })
    }
}

/// The directories every run is shown without their being named, on a machine whose jail is of this kind.
fn always_shown(kind: Kind) -> Vec<PathBuf> {
    match kind {
        Kind::Seatbelt => {
            let mut dirs: Vec<PathBuf> = MACOS_SYSTEM_DIRS.iter().map(PathBuf::from).collect();
            for root in MACOS_PACKAGE_ROOTS {
                dirs.extend(
                    MACOS_PACKAGE_PARTS
                        .iter()
                        .map(|part| Path::new(root).join(part)),
                );
            }
            dirs
        }
        Kind::Bubblewrap => LINUX_SYSTEM_DIRS
            .iter()
            .chain(&LINUX_ETC)
            .map(PathBuf::from)
            .collect(),
    }
}

/// Whether `path` is `dir` or lies in it, as the jail's own rules would have it. `folds` says those rules do
/// not tell capital letters from small: macOS's do not, measured on macOS 27 with a rule written `share` and a
/// directory kept as `SHARE`, each way round. A name that is there has been spelled as the disk has it before
/// it gets here, so this matters for a name that is not there yet, which has no spelling but the one written.
/// Two names that differ in how an accented letter is put together are not taken as one.
fn inside(path: &Path, dir: &Path, folds: bool) -> bool {
    if !folds {
        return path.starts_with(dir);
    }
    let small = |path: &Path| -> Vec<String> {
        path.components()
            .map(|part| part.as_os_str().to_string_lossy().to_lowercase())
            .collect()
    };
    small(path).starts_with(&small(dir))
}

/// A place where keys or settings are kept, or would be, that one of the directories every run is shown would
/// show, with that directory; or none.
///
/// A run is given such a directory under its name, and what it is given is whatever that name leads to. So a
/// place is looked for at the name and at where the name leads, above it as well as inside it. One exception:
/// a place that is there and hidden, inside a directory whose name leads nowhere else, is hidden with whatever
/// is put in it later. Where the name does lead elsewhere, hiding a place by its own name does not hide it
/// under the directory's, so nothing is excepted.
fn shown_by_default(
    dirs: &[PathBuf],
    protected: &[PathBuf],
    hidden: &[PathBuf],
    folds: bool,
) -> Option<(PathBuf, PathBuf)> {
    for dir in dirs {
        let leads_to = dir.canonicalize().unwrap_or_else(|_| dir.clone());
        let elsewhere = leads_to != *dir;
        for at in [dir, &leads_to] {
            let shown = protected.iter().chain(hidden).find(|place| {
                let touches = inside(place, at, folds) || inside(at, place, folds);
                // This is the one comparison here that lets a place through, so it does not ignore letters. A
                // hidden path is spelled as the disk has it, and so is every part of a place that is there.
                // Where the rules might tell two spellings apart after all, a place is not called covered
                // by a hidden path that only resembles it.
                let covered = !elsewhere && hidden.iter().any(|hidden| place.starts_with(hidden));
                touches && !covered
            });
            if let Some(place) = shown {
                return Some((place.clone(), dir.clone()));
            }
        }
    }
    None
}

/// How many links one path may lead through. More than this is a loop, or as good as one.
const MAX_LINKS: usize = 40;

/// Every place `path` could come to name.
///
/// A name that is not there yet has no one place. It will be wherever the links on the way to it lead when it
/// is made, and a link there today can be replaced by a directory tomorrow. So the path is walked a part at a
/// time, and at every link met on the way there are two answers: the link stays, and the walk goes on where it
/// leads; or it becomes a directory, and then the name is right there, with the rest as written. Each second
/// answer is a place, and so is where the walk ends.
///
/// A link is followed by what it says, whether or not anything is there: a directory made later where a link
/// points is where the name would land. Below a part that is not there the rest is kept as written, since
/// nothing below it can be a link yet; but only below it. A `..` climbs back out, and from there the walk
/// looks again. The path as written is always among the places.
///
/// A name that is there is spelled as the machine spells it. On a disk where capital and small letters name the
/// same file, a place written `.cargo` and a directory kept as `.Cargo` are one, and are compared as one.
///
/// A path that leads through more than `MAX_LINKS` links has no answer. That is an error, and a jail does not
/// start beside a protected name it cannot place.
fn places_of(path: &Path) -> Result<Vec<PathBuf>, TurnError> {
    use std::collections::VecDeque;
    use std::path::Component;

    fn parts(path: &Path) -> impl Iterator<Item = Part> + '_ {
        path.components().filter_map(|part| match part {
            Component::RootDir => Some(Part::Root),
            Component::ParentDir => Some(Part::Up),
            Component::Normal(name) => Some(Part::Name(name.to_os_string())),
            Component::CurDir | Component::Prefix(_) => None,
        })
    }
    if !path.is_absolute() {
        return Err(TurnError::Refused(format!(
            "a protected path must be absolute: {}",
            path.display()
        )));
    }
    let mut found: Vec<PathBuf> = Vec::new();
    let mut keep = |place: PathBuf| {
        if !found.contains(&place) {
            found.push(place);
        }
    };
    let mut left: VecDeque<Part> = parts(path).collect();
    let mut at = PathBuf::new();
    let mut links = 0;
    while let Some(part) = left.pop_front() {
        let name = match part {
            Part::Root => {
                at = PathBuf::from("/");
                continue;
            }
            Part::Up => {
                // Above a name that is not there is the directory the walk came from; and `at` has no link
                // in it, so the directory above a name that is there is the one its name says.
                at.pop();
                continue;
            }
            Part::Name(name) => name,
        };
        at.push(&name);
        // Every name is looked at, also one below a part that is not there. Such a name cannot be there
        // either, and is kept as written; but a `..` may have led back up out of what is not there since,
        // and what comes after it can be a link. The walk never stops looking.
        match std::fs::symlink_metadata(&at) {
            Ok(meta) if meta.file_type().is_symlink() => {
                // Were this a directory, the name would be here, with the rest as written inside it.
                keep(inside_a_new_directory(path, &at, left.iter())?);
                links += 1;
                if links > MAX_LINKS {
                    return Err(TurnError::Refused(format!(
                        "{} leads through more than {MAX_LINKS} links, so the jail cannot say where it is",
                        path.display()
                    )));
                }
                let target = std::fs::read_link(&at).map_err(|e| {
                    TurnError::Refused(format!("the link {} cannot be read: {e}", at.display()))
                })?;
                // The walk goes on with what the link says, from beside the link, and then with what was
                // still to come.
                at.pop();
                let mut next: VecDeque<Part> = parts(&target).collect();
                next.append(&mut left);
                left = next;
            }
            Ok(_) => {
                // It is there, and it is no link. Its name is taken as the machine has it, not as it was
                // written: where capital and small letters name the same file, `.Cargo` on the disk is what
                // `.cargo` means, and two spellings of one place must compare as one. Everything before it
                // has been through here already, so this changes the last name only.
                at = at.canonicalize().map_err(|e| {
                    TurnError::Refused(format!("the jail cannot look at {}: {e}", at.display()))
                })?;
            }
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::NotFound | std::io::ErrorKind::NotADirectory
                ) =>
            {
                // Not there. It is kept as written, and the walk goes on.
            }
            Err(e) => {
                return Err(TurnError::Refused(format!(
                    "the jail cannot look at {}: {e}",
                    at.display()
                )));
            }
        }
    }
    keep(at);
    Ok(found)
}

/// Where the rest of a walk would lead if the link at `link` were a directory with nothing in it: `link`, then
/// `rest` as written. That holds as long as the rest stays inside that directory. If it climbs back out with
/// `..`, it is on ground that is there again, where it could meet other links: a second walk, with answers of
/// its own. None is given for it. The jail does not start beside a protected name laid out like that.
fn inside_a_new_directory<'a>(
    protected: &Path,
    link: &Path,
    rest: impl Iterator<Item = &'a Part>,
) -> Result<PathBuf, TurnError> {
    let mut place = link.to_path_buf();
    let mut deep = 1usize;
    for part in rest {
        match part {
            Part::Name(name) => {
                place.push(name);
                deep += 1;
            }
            // A link's own words are walked as soon as they are met, so a root is never still to come.
            Part::Root | Part::Up => {
                place.pop();
                deep -= 1;
                if deep == 0 {
                    return Err(TurnError::Refused(format!(
                        "{} leads through the link {}, and then back up out of where it is: the jail cannot \
                         say where that would be if the link became a directory",
                        protected.display(),
                        link.display()
                    )));
                }
            }
        }
    }
    Ok(place)
}

/// A part of a path still to be walked.
enum Part {
    Root,
    Up,
    Name(std::ffi::OsString),
}

/// Which tool makes the jail on this machine.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    /// macOS `sandbox-exec`.
    Seatbelt,
    /// Linux `bwrap`.
    Bubblewrap,
}

/// A jail around one checkout: where a run may write, what else it is shown, and what stays hidden.
#[derive(Debug, Clone)]
pub struct Jail {
    kind: Kind,
    tool: PathBuf,
    checkout: PathBuf,
    scratch: PathBuf,
    readable: Vec<PathBuf>,
    hidden: Vec<Hidden>,
    /// On Linux, the file that holds the system-call filter (`crate::filter`), beside the scratch directory
    /// and so outside everything a jailed run sees.
    filter: Option<PathBuf>,
}

/// The descriptor a Linux jail's filter is passed to `bwrap` on.
const FILTER_DESCRIPTOR: &str = "9";

/// Something hidden, and whether it is a directory: the Linux form covers a directory and a file differently.
#[derive(Debug, Clone)]
struct Hidden {
    path: PathBuf,
    dir: bool,
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
        let (kind, tool) = Self::detect().ok_or_else(no_jail_tool)?;
        let (checkout, scratch) = (real_dir(checkout)?, real_dir(scratch)?);
        if checkout.parent().is_none() || scratch.parent().is_none() {
            return Err(TurnError::Refused(
                "a jail whose run may write the whole machine is not a jail".into(),
            ));
        }
        // Written afresh for every jail: a run starts with the filter the room wrote for it, whatever was
        // at that path before.
        let filter = match kind {
            Kind::Seatbelt => None,
            Kind::Bubblewrap => {
                let machine = crate::filter::this_machine().ok_or_else(unknown_machine)?;
                let mut name = scratch.file_name().unwrap_or_default().to_os_string();
                name.push(".filter");
                let path = scratch.with_file_name(name);
                write_afresh(&path, &crate::filter::socket_filter(machine))?;
                Some(path)
            }
        };
        Ok(Jail {
            kind,
            tool,
            checkout,
            scratch,
            readable: Vec::new(),
            hidden: Vec::new(),
            filter,
        })
    }

    /// Also shows the run `path`, a directory or one file, to read and to run: a toolchain or vendored code
    /// outside the system directories, or a worker's own program. The whole machine is refused. A path that
    /// does not exist is left out.
    pub fn allow_read(mut self, path: &Path) -> Result<Jail, TurnError> {
        if path.exists() {
            let real = real_path(path)?;
            if real.parent().is_none() {
                return Err(TurnError::Refused(
                    "a jail that is shown the whole machine is not a jail".into(),
                ));
            }
            self.readable.push(real);
        }
        Ok(self)
    }

    /// Hides `path`, a directory or one file, even inside something that is shown. The checkout and the
    /// scratch directory are never hidden: a room kept below a hidden directory still gives a run its own. A
    /// path that does not exist is left out.
    pub fn hide(mut self, path: &Path) -> Result<Jail, TurnError> {
        if path.exists() {
            let path = real_path(path)?;
            let dir = path.is_dir();
            self.hidden.push(Hidden { path, dir });
        }
        Ok(self)
    }

    /// The hidden path that is `path` or holds it, if there is one. Such a path stays hidden when it is shown,
    /// so a caller that is about to name it for a run can say so and not hand over a jail where the named
    /// thing is quietly missing.
    pub fn hides(&self, path: &Path) -> Option<&Path> {
        let real = path.canonicalize().ok()?;
        let folds = self.kind == Kind::Seatbelt;
        self.hidden
            .iter()
            .map(|hidden| hidden.path.as_path())
            .find(|hidden| inside(&real, hidden, folds))
    }

    pub fn kind(&self) -> Kind {
        self.kind
    }

    /// The checkout, in its real form: where a jailed run starts.
    pub fn checkout(&self) -> &Path {
        &self.checkout
    }

    /// The scratch directory, in its real form: a jailed run's home and its place for temporary files.
    pub fn scratch(&self) -> &Path {
        &self.scratch
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
        match &self.filter {
            None => (self.tool.clone(), wrapped),
            // The filter reaches `bwrap` as an open file. A shell opens it and then becomes `bwrap`: the
            // filter's path is the shell's own name here, and everything after it is the command.
            Some(filter) => {
                let mut through_a_shell = vec![
                    "-c".to_string(),
                    format!("exec \"$@\" {FILTER_DESCRIPTOR}<\"$0\""),
                    text(filter),
                    text(&self.tool),
                ];
                through_a_shell.extend(wrapped);
                (PathBuf::from("/bin/sh"), through_a_shell)
            }
        }
    }

    /// Deny everything, then allow: making processes, signalling what is in the same jail, reading the named
    /// system settings, asking about itself, and reading and running the system's own directories, what is
    /// shown, the checkout and the scratch directory. It may write in those two and to the null devices, and
    /// may not remove or rename the two directories themselves, or change their permissions. Of the device files it may read only
    /// the null, zero and random devices and its own open files, so no terminal. It may look up no system
    /// service and make no named semaphore, which would be shared with every process outside.
    ///
    /// Where two rules match, the later one decides. So the order is: what is shown, then what is hidden, then
    /// the run's own two directories, which nothing hides.
    fn seatbelt_profile(&self) -> String {
        let system = always_shown(Kind::Seatbelt);
        let own = [self.checkout.clone(), self.scratch.clone()];
        let subpaths = |paths: &[PathBuf]| -> String {
            paths
                .iter()
                .map(|path| format!(" (subpath {})", quoted(path)))
                .collect()
        };
        let literals = |paths: &[&str]| -> String {
            paths
                .iter()
                .map(|path| format!(" (literal {})", quoted(Path::new(path))))
                .collect()
        };

        let mut profile = String::from(
            "(version 1)\n\
             (deny default)\n\
             (allow process-fork)\n\
             (allow signal (target same-sandbox))\n",
        );
        let settings: String = MACOS_SETTING_GROUPS
            .iter()
            .map(|group| format!(" (sysctl-name-prefix \"{group}\")"))
            .chain(
                MACOS_SETTINGS
                    .iter()
                    .map(|name| format!(" (sysctl-name \"{name}\")")),
            )
            .collect();
        profile.push_str(&format!("(allow sysctl-read{settings})\n"));
        // "Deny by default" does not cover questions about processes: they are answered unless denied. A run
        // may ask about itself, which a program does as it starts. Together with a list of settings that has
        // nothing under `kern.proc`, this is what keeps another process's arguments and environment unread:
        // either one alone leaves them readable.
        profile.push_str("(deny process-info*)\n(allow process-info* (target self))\n");
        profile.push_str(&format!(
            "(allow file-read* process-exec{})\n",
            subpaths(&system)
        ));
        profile.push_str(&format!(
            "(allow file-read*{})\n",
            literals(&MACOS_SYSTEM_FILES)
        ));
        profile.push_str(
            "(allow file-read* (literal \"/dev\") (literal \"/dev/null\") (literal \"/dev/zero\") \
             (literal \"/dev/random\") (literal \"/dev/urandom\") (subpath \"/dev/fd\"))\n",
        );
        if !self.readable.is_empty() {
            profile.push_str(&format!(
                "(allow file-read* process-exec{})\n",
                subpaths(&self.readable)
            ));
        }
        for hidden in &self.hidden {
            profile.push_str(&format!(
                "(deny file-read* process-exec (subpath {}))\n",
                quoted(&hidden.path)
            ));
        }
        profile.push_str(&format!(
            "(allow file-read* process-exec{})\n",
            subpaths(&own)
        ));
        profile.push_str(&format!(
            "(allow file-write*{} (literal \"/dev/null\") (literal \"/dev/zero\"))\n",
            subpaths(&own)
        ));
        // The two directories themselves stay what they are: not removed, not renamed, and their permissions
        // not changed. A run that moved its checkout away and left a link at its path would have the next run
        // in this sandbox jailed around whatever the link names. Only those acts are denied. Denying every
        // write to the two names also refuses a harmless "make this directory if it is not there", and the
        // system's own tools then complain on every start.
        profile.push_str(&format!(
            "(deny file-write-unlink file-write-mode (literal {}) (literal {}))\n",
            quoted(&self.checkout),
            quoted(&self.scratch)
        ));
        // A program that asks where it is looks at each directory on the way down. It may see that those
        // directories exist, and nothing in them.
        let mut above = std::collections::BTreeSet::new();
        let files: Vec<PathBuf> = MACOS_SYSTEM_FILES.iter().map(PathBuf::from).collect();
        for path in system
            .iter()
            .chain(&files)
            .chain(&self.readable)
            .chain(&own)
        {
            above.extend(
                path.ancestors()
                    .skip(1)
                    .filter(|a| a.parent().is_some())
                    .map(Path::to_path_buf),
            );
        }
        if !above.is_empty() {
            let above: String = above
                .iter()
                .map(|path| format!(" (literal {})", quoted(path)))
                .collect();
            profile.push_str(&format!("(allow file-read-metadata{above})\n"));
        }
        profile.push_str("(deny file-read* file-write* (literal \"/dev/tty\"))\n");
        profile
    }

    /// Only the system directories and what is shown, read-only; an empty directory over `/tmp`, `/run` and
    /// each hidden directory, and an empty file over each hidden file; then the two directories, writable, so
    /// that nothing hides them; every namespace private; no capabilities; its own session, so it has no
    /// terminal; and gone when its parent goes.
    ///
    /// A hidden path is covered when it lies inside something shown, or holds something shown: hiding wins
    /// either way, as it does on macOS. One that touches nothing shown is not covered: it is not there at
    /// all, and a cover would make its name, telling the run that it exists.
    fn bubblewrap_args(&self) -> Vec<String> {
        let mut args: Vec<String> = [
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--cap-drop",
            "ALL",
            // The caller clears the environment, but a memory-capped run is started through the session bus,
            // whose address must not follow it in. `/run` is empty inside, so the socket is not there either.
            "--unsetenv",
            "DBUS_SESSION_BUS_ADDRESS",
            "--unsetenv",
            "XDG_RUNTIME_DIR",
        ]
        .iter()
        .map(|s| s.to_string())
        .collect();
        if self.filter.is_some() {
            args.extend(["--seccomp".to_string(), FILTER_DESCRIPTOR.to_string()]);
        }
        for path in LINUX_SYSTEM_DIRS.iter().chain(&LINUX_ETC) {
            args.extend([
                "--ro-bind-try".to_string(),
                path.to_string(),
                path.to_string(),
            ]);
        }
        args.extend(
            [
                "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", "/run",
            ]
            .map(String::from),
        );
        // The kernel lists the keys a process may see, and a run would see those of the person it runs
        // for. The filter refuses the calls that reach a key; these two files would still name them.
        for list in ["/proc/keys", "/proc/key-users"] {
            args.extend([
                "--ro-bind-try".to_string(),
                "/dev/null".to_string(),
                list.to_string(),
            ]);
        }
        for dir in &self.readable {
            let dir = text(dir);
            args.extend(["--ro-bind".to_string(), dir.clone(), dir]);
        }
        let touches_shown = |path: &Path| {
            LINUX_SYSTEM_DIRS
                .iter()
                .chain(&LINUX_ETC)
                .map(Path::new)
                .chain(self.readable.iter().map(PathBuf::as_path))
                .any(|shown| path.starts_with(shown) || shown.starts_with(path))
        };
        for hidden in self.hidden.iter().filter(|h| touches_shown(&h.path)) {
            if hidden.dir {
                args.extend(["--tmpfs".to_string(), text(&hidden.path)]);
            } else {
                args.extend([
                    "--ro-bind".to_string(),
                    "/dev/null".to_string(),
                    text(&hidden.path),
                ]);
            }
        }
        for dir in [&self.checkout, &self.scratch] {
            let dir = text(dir);
            args.extend(["--bind".to_string(), dir.clone(), dir]);
        }
        args
    }
}

/// Writes `bytes` to a new file at `path`, after removing a file or a link that was there. A directory there is
/// refused. The file is never written through something already at the path.
fn write_afresh(path: &Path, bytes: &[u8]) -> Result<(), TurnError> {
    use std::io::Write;
    let what = |e: std::io::Error| TurnError::Io(format!("write {}: {e}", path.display()));
    match std::fs::symlink_metadata(path) {
        Ok(meta) if meta.is_dir() => {
            return Err(TurnError::Refused(format!(
                "{} is a directory, where the jail's filter belongs",
                path.display()
            )));
        }
        Ok(_) => std::fs::remove_file(path).map_err(what)?,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(what(e)),
    }
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .and_then(|mut file| file.write_all(bytes))
        .map_err(what)
}

/// The real, absolute form of an existing directory, refused if it cannot be written safely into a jail's rules.
fn real_dir(path: &Path) -> Result<PathBuf, TurnError> {
    let real = real_path(path)?;
    if !real.is_dir() {
        return Err(TurnError::Refused(format!(
            "a jail's directory must be a directory: {}",
            real.display()
        )));
    }
    Ok(real)
}

/// The real, absolute form of an existing file or directory, refused if it cannot be written safely into a
/// jail's rules.
fn real_path(path: &Path) -> Result<PathBuf, TurnError> {
    if !path.is_absolute() {
        return Err(TurnError::Refused(format!(
            "a jail's path must be absolute: {}",
            path.display()
        )));
    }
    let real = path.canonicalize().map_err(|e| {
        TurnError::Refused(format!("a jail's path must exist: {}: {e}", path.display()))
    })?;
    match real.to_str() {
        Some(s) if !s.contains(['\n', '\r', '\0']) => Ok(real),
        _ => Err(TurnError::Refused(
            "a jail's path must be plain text on one line".into(),
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
    fn a_path_is_inside_a_directory_by_its_names_and_by_its_letters_only_where_the_rules_tell_them_apart()
     {
        let inside =
            |path: &str, dir: &str, folds: bool| inside(Path::new(path), Path::new(dir), folds);
        for folds in [false, true] {
            assert!(inside("/a/b/c", "/a/b", folds));
            assert!(inside("/a/b", "/a/b", folds));
            assert!(
                !inside("/a/bc", "/a/b", folds),
                "a name is not the start of a longer name"
            );
            assert!(!inside("/a", "/a/b", folds));
        }
        assert!(inside("/a/B/c", "/a/b", true));
        assert!(inside("/A/b", "/a/B", true));
        assert!(!inside("/a/B/c", "/a/b", false));
        assert!(!inside("/a/Bc", "/a/b", true));
    }

    /// The directories every run is shown are judged by their names and by where their names lead.
    #[test]
    fn a_directory_every_run_is_shown_is_judged_by_where_its_name_leads() {
        let tmp = std::env::temp_dir().join(format!("yak-default-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        for dir in ["plain/there", "home/.local/share", "other"] {
            std::fs::create_dir_all(tmp.join(dir)).unwrap();
        }
        let tmp = tmp.canonicalize().unwrap();
        let at = |path: &str| tmp.join(path);
        let paths = |names: &[&str]| -> Vec<PathBuf> { names.iter().map(|n| at(n)).collect() };
        let judged = |dirs: &[&str], protected: &[&str], hidden: &[&str]| {
            shown_by_default(&paths(dirs), &paths(protected), &paths(hidden), false)
        };
        // Neither the directory nor the place is there yet, and they are written in different letters. Under
        // rules that do not tell the letters apart they are one place; under rules that do, two.
        let (dirs, places) = (paths(&["pkg/share"]), paths(&["pkg/SHARE/later/secret"]));
        assert_eq!(
            shown_by_default(&dirs, &places, &[], true),
            Some((at("pkg/SHARE/later/secret"), at("pkg/share")))
        );
        assert_eq!(shown_by_default(&dirs, &places, &[], false), None);
        // A place that is there and hidden covers what lies in it as spelled, and nothing spelled otherwise:
        // being covered lets a place through, so that one comparison never ignores letters.
        let shown = paths(&["plain"]);
        let (hidden, same, other) = (
            paths(&["plain/there"]),
            paths(&["plain/there/later"]),
            paths(&["plain/THERE/later"]),
        );
        assert_eq!(shown_by_default(&shown, &same, &hidden, true), None);
        assert_eq!(
            shown_by_default(&shown, &other, &hidden, true),
            Some((at("plain/THERE/later"), at("plain")))
        );
        // The same the other way up: the directory inside a place written in other letters.
        let (dirs, places) = (paths(&["Pkg/Made/share"]), paths(&["pkg/made"]));
        assert_eq!(
            shown_by_default(&dirs, &places, &[], true),
            Some((at("pkg/made"), at("Pkg/Made/share")))
        );
        assert_eq!(shown_by_default(&dirs, &places, &[], false), None);
        // A place that is not there yet, inside one of them.
        assert_eq!(
            judged(&["plain"], &["plain/later/secret"], &[]),
            Some((at("plain/later/secret"), at("plain")))
        );
        // A place that is there and hidden, inside one whose name leads nowhere else: hidden is enough.
        assert_eq!(judged(&["plain"], &["plain/there"], &["plain/there"]), None);
        // A place nowhere near.
        assert_eq!(judged(&["plain"], &["other/secret"], &[]), None);
        // One of them inside a place that is not there yet.
        assert_eq!(
            judged(&["never/made/share"], &["never/made"], &[]),
            Some((at("never/made"), at("never/made/share")))
        );
        // One whose name leads into a protected tree. The tree is there and hidden by its own name, which
        // does not hide it under this one.
        std::os::unix::fs::symlink(at("home/.local/share"), at("alias")).unwrap();
        assert_eq!(
            judged(&["alias"], &["home/.local/share"], &["home/.local/share"]),
            Some((at("home/.local/share"), at("alias")))
        );
        // The same for a place inside that tree that is not there yet.
        assert_eq!(
            judged(&["alias"], &["home/.local/share/later"], &[]),
            Some((at("home/.local/share/later"), at("alias")))
        );
        // And one whose name leads somewhere that holds nothing protected.
        std::os::unix::fs::symlink(at("other"), at("harmless")).unwrap();
        assert_eq!(
            judged(
                &["harmless"],
                &["home/.local/share"],
                &["home/.local/share"]
            ),
            None
        );
        std::fs::remove_dir_all(&tmp).unwrap();
    }

    #[test]
    fn a_name_has_a_place_for_every_link_on_the_way_to_it() {
        let tmp = std::env::temp_dir().join(format!("yak-places-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        for dir in ["home", "first", "second", "third", "grant"] {
            std::fs::create_dir_all(tmp.join(dir)).unwrap();
        }
        let tmp = tmp.canonicalize().unwrap();
        let link = |to: &str, at: &str| std::os::unix::fs::symlink(to, tmp.join(at)).unwrap();
        let places = |path: &str| places_of(&tmp.join(path)).unwrap();
        let at = |paths: &[&str]| -> Vec<PathBuf> { paths.iter().map(|p| tmp.join(p)).collect() };

        // home/outer leads to first, and first/inner leads to second.
        link(tmp.join("first").to_str().unwrap(), "home/outer");
        link(tmp.join("second").to_str().unwrap(), "first/inner");
        // A name that is not there, behind both links: as written, behind the first, and behind both.
        assert_eq!(
            places("home/outer/inner/later.toml"),
            at(&[
                "home/outer/inner/later.toml",
                "first/inner/later.toml",
                "second/later.toml"
            ])
        );
        // With no link on the way, a name has the one place.
        assert_eq!(places("third/none/at/all"), at(&["third/none/at/all"]));
        // One that is there has its real place too.
        assert_eq!(places("home/outer"), at(&["home/outer", "first"]));

        // A link to somewhere that is not there yet is followed all the same: a directory made there later
        // is where the name would land.
        link(tmp.join("grant/later").to_str().unwrap(), "home/dangling");
        assert_eq!(
            places("home/dangling/credentials.toml"),
            at(&[
                "home/dangling/credentials.toml",
                "grant/later/credentials.toml"
            ])
        );
        // A link that says where it leads from where it is, and goes up on the way.
        link("../grant/sideways", "home/beside");
        assert_eq!(
            places("home/beside/key"),
            at(&["home/beside/key", "grant/sideways/key"])
        );
        // A link reached through a link, each written from where it is.
        link("up-and-over", "home/chain");
        link("../third/end", "home/up-and-over");
        assert_eq!(
            places("home/chain/key"),
            at(&["home/chain/key", "home/up-and-over/key", "third/end/key"])
        );
        // Dots in the name as written are taken as written.
        assert_eq!(places("home/./none/../other/key"), at(&["home/other/key"]));
        // A loop has no place, and that is an error. It is asked on a thread of its own with a time limit: a
        // walk that went round for ever would otherwise hold this test for ever, and say nothing.
        link("round-b", "home/round-a");
        link("round-a", "home/round-b");
        let ring = tmp.join("home/round-a/key");
        let (answer, wait) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let _ = answer.send(super::places_of(&ring));
        });
        let lost = wait
            .recv_timeout(std::time::Duration::from_secs(10))
            .expect("the walk round a ring of links did not end");
        assert!(
            matches!(&lost, Err(TurnError::Refused(why)) if why.contains("links")),
            "{lost:?}"
        );
        // And a name that is not a full path is not placed at all.
        assert!(super::places_of(Path::new("home/key")).is_err());

        // Up out of a part that is not there, and on to a link that is: the walk looks again once it is out.
        // `third/redirect` leads to `grant`, and the links below lead to it by way of `third/missing/..`.
        link(tmp.join("grant").to_str().unwrap(), "third/redirect");
        link(
            tmp.join("third/missing/../redirect").to_str().unwrap(),
            "home/up-and-back",
        );
        assert_eq!(
            places("home/up-and-back/key"),
            at(&["home/up-and-back/key", "third/redirect/key", "grant/key"])
        );
        // The same written from where the link is.
        link("../third/missing/../redirect", "home/up-and-back-beside");
        assert_eq!(
            places("home/up-and-back-beside/key"),
            at(&[
                "home/up-and-back-beside/key",
                "third/redirect/key",
                "grant/key"
            ])
        );
        // And up out of a file, which can hold nothing today.
        std::fs::write(tmp.join("third/a-file"), "").unwrap();
        link(
            tmp.join("third/a-file/inside/../../redirect")
                .to_str()
                .unwrap(),
            "home/up-out-of-a-file",
        );
        assert_eq!(
            places("home/up-out-of-a-file/key"),
            at(&[
                "home/up-out-of-a-file/key",
                "third/redirect/key",
                "grant/key"
            ])
        );
        // Two steps up from two parts that are not there, and one more that is: still out, and looking.
        link(
            tmp.join("third/no/such/../../redirect").to_str().unwrap(),
            "home/two-up",
        );
        assert_eq!(
            places("home/two-up/key"),
            at(&["home/two-up/key", "third/redirect/key", "grant/key"])
        );
        // A link whose words go through another link and back up out of it. If that inner link became a
        // directory the rest would start again from beside it: a second walk. No answer is given.
        link(
            tmp.join("home/outer/../third/end").to_str().unwrap(),
            "home/through-and-out",
        );
        let lost = super::places_of(&tmp.join("home/through-and-out/key"));
        assert!(
            matches!(&lost, Err(TurnError::Refused(why)) if why.contains("back up out of")),
            "{lost:?}"
        );

        // A name that is there is spelled as the machine has it. Where capital and small letters name the same
        // file, a name written in other letters is that same place; where they do not, it is another name, one
        // that is not there.
        std::fs::create_dir_all(tmp.join("Mixed/Inner")).unwrap();
        let folds = tmp.join("mixed/inner").is_dir();
        assert_eq!(
            places("mixed/inner/later"),
            at(&[if folds {
                "Mixed/Inner/later"
            } else {
                "mixed/inner/later"
            }])
        );
        // The same behind a link: what the link says is spelled as the machine has it too.
        link("../mixed/inner", "home/shouting");
        assert_eq!(
            places("home/shouting/key"),
            at(&[
                "home/shouting/key",
                if folds {
                    "Mixed/Inner/key"
                } else {
                    "mixed/inner/key"
                }
            ])
        );
        std::fs::remove_dir_all(&tmp).unwrap();
    }

    fn sample(kind: Kind) -> Jail {
        Jail {
            kind,
            tool: PathBuf::from("/jail-tool"),
            checkout: PathBuf::from("/room/checkout"),
            scratch: PathBuf::from("/room/scratch"),
            readable: vec![PathBuf::from("/tools"), PathBuf::from("/keys/tool")],
            hidden: vec![
                // A hidden directory that holds something shown: hiding wins.
                Hidden {
                    path: PathBuf::from("/keys"),
                    dir: true,
                },
                Hidden {
                    path: PathBuf::from("/tools/keys"),
                    dir: true,
                },
                Hidden {
                    path: PathBuf::from("/tools/token"),
                    dir: false,
                },
                // A hidden directory that holds the checkout.
                Hidden {
                    path: PathBuf::from("/room"),
                    dir: true,
                },
                // Hidden, and inside nothing that is shown.
                Hidden {
                    path: PathBuf::from("/home/someone/.netrc"),
                    dir: false,
                },
            ],
            filter: match kind {
                Kind::Seatbelt => None,
                Kind::Bubblewrap => Some(PathBuf::from("/room/scratch.filter")),
            },
        }
    }

    #[test]
    fn the_room_jails_unless_told_off() {
        assert!(wanted_from(None));
        assert!(wanted_from(Some("")));
        assert!(wanted_from(Some("on")));
        assert!(wanted_from(Some("OFF")));
        assert!(!wanted_from(Some("off")));
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
        // Nothing is allowed without a filter except making a process. Reading, running and the system's
        // settings are always named.
        for line in profile
            .lines()
            .filter(|l| l.starts_with("(allow ") && !l.contains(" ("))
        {
            assert!(
                line == "(allow process-fork)",
                "an unfiltered allow that is not on the list: {line}"
            );
        }
        // No network, no terminal, no system service, and nothing shared between processes.
        assert!(!profile.contains("network"));
        assert!(!profile.contains("ipc-"));
        assert!(!profile.contains("mach-lookup") && !profile.contains("global-name"));
        assert!(profile.contains("(deny file-read* file-write* (literal \"/dev/tty\"))"));
        // The table of processes is not among the settings, and a run asks only about itself.
        assert!(!profile.contains("\"kern.proc"), "{profile}");
        assert!(profile.contains("(sysctl-name-prefix \"hw.\")"));
        let ask = profile.find("(deny process-info*)\n").unwrap();
        assert!(
            ask < profile
                .find("(allow process-info* (target self))\n")
                .unwrap()
        );
        // The two directories themselves cannot be removed or replaced, and that rule comes after the one that
        // lets a run write in them.
        let write = profile.find("(allow file-write*").unwrap();
        let keep = profile
            .find(
                "(deny file-write-unlink file-write-mode (literal \"/room/checkout\") \
                 (literal \"/room/scratch\"))\n",
            )
            .unwrap();
        assert!(write < keep);
        // Of the device files, only the five named ones and a run's own open files.
        assert!(!profile.contains("(subpath \"/dev\")"));
        assert_eq!(profile.matches("\"/dev/").count(), 8, "{profile}");
        // Nowhere a person keeps their own files is shown by default.
        for place in [
            "\"/System\")",
            "\"/System/Volumes\")",
            "\"/System/Volumes/Data",
            "\"/System/Volumes/Preboot\")",
            "\"/System/Applications",
            "\"/Users",
            "\"/Volumes",
            "\"/private/tmp",
            "\"/private/var/folders",
            "\"/Applications",
            "\"/Library\")",
            "\"/usr\")",
            "\"/opt\")",
            "\"/private\")",
            "\"/private/etc\")",
            "/private/etc/sudoers",
            "\"/private/etc/ssl\")",
            "/private/etc/ssl/private",
            "homebrew/etc",
            "homebrew/var",
            "local/etc",
            "local/var",
        ] {
            let shown = profile
                .lines()
                .filter(|l| !l.starts_with("(allow file-read-metadata"))
                .any(|l| l.contains(place));
            assert!(!shown, "{place} is shown: {profile}");
        }
        // Writing names the two directories and the two devices, and nothing else.
        let writes: Vec<&str> = profile
            .lines()
            .filter(|l| l.starts_with("(allow file-write"))
            .collect();
        assert_eq!(
            writes,
            [
                "(allow file-write* (subpath \"/room/checkout\") (subpath \"/room/scratch\") \
              (literal \"/dev/null\") (literal \"/dev/zero\"))"
            ]
        );
    }

    #[test]
    fn the_macos_profile_hides_after_it_shows_and_gives_the_run_its_own_last() {
        let profile = sample(Kind::Seatbelt).seatbelt_profile();
        let at = |rule: &str| {
            profile
                .find(rule)
                .unwrap_or_else(|| panic!("no rule {rule} in {profile}"))
        };
        let shown = at("(allow file-read* process-exec (subpath \"/tools\")");
        let hidden_dir = at("(deny file-read* process-exec (subpath \"/tools/keys\"))");
        let hidden_file = at("(deny file-read* process-exec (subpath \"/tools/token\"))");
        let hidden_above = at("(deny file-read* process-exec (subpath \"/room\"))");
        let own = at(
            "(allow file-read* process-exec (subpath \"/room/checkout\") (subpath \"/room/scratch\"))",
        );
        assert!(shown < hidden_dir && shown < hidden_file);
        // Both shown paths are in the one rule, so the hidden directory that holds the second is after it.
        assert!(profile.contains("(subpath \"/tools\") (subpath \"/keys/tool\"))"));
        assert!(shown < at("(deny file-read* process-exec (subpath \"/keys\"))"));
        assert!(hidden_dir < own && hidden_file < own && hidden_above < own);
        // The directories above what is shown can be seen to exist, and no more than that.
        let above = profile
            .lines()
            .find(|l| l.starts_with("(allow file-read-metadata"))
            .unwrap();
        for dir in ["\"/room\"", "\"/usr\"", "\"/private/var\"", "\"/opt\""] {
            assert!(
                above.contains(&format!("(literal {dir})")),
                "{dir}: {above}"
            );
        }
        assert!(!above.contains("subpath") && !above.contains("(literal \"/\")"));
    }

    #[test]
    fn the_linux_form_shows_only_system_and_named_directories() {
        let args = sample(Kind::Bubblewrap).bubblewrap_args();
        let joined = args.join(" ");
        assert!(joined.contains("--unshare-all"));
        // The system-call filter is on, and reaches bwrap through a shell that opens it first.
        assert!(joined.contains("--seccomp 9"));
        let jail = sample(Kind::Bubblewrap);
        let (program, argv) = jail.command("true", &[]);
        assert_eq!(program, PathBuf::from("/bin/sh"));
        assert_eq!(
            argv[..4],
            [
                "-c",
                "exec \"$@\" 9<\"$0\"",
                "/room/scratch.filter",
                "/jail-tool"
            ]
        );
        assert_eq!(argv[argv.len() - 2..], ["--", "true"]);
        // The macOS form needs none.
        let (program, argv) = sample(Kind::Seatbelt).command("true", &[]);
        assert_eq!(program, PathBuf::from("/jail-tool"));
        assert_eq!(argv[0], "-p");
        assert!(joined.contains("--cap-drop ALL"));
        assert!(joined.contains("--new-session"));
        assert!(joined.contains("--die-with-parent"));
        // Not all of `/usr` or `/etc`: programs and libraries, and the files ordinary tools read.
        for whole in [
            "/usr /usr",
            "/etc /etc",
            "/usr/local /usr/local",
            "/var",
            "/opt",
            "/home",
            "/root",
        ] {
            assert!(
                !joined.contains(&format!("--ro-bind-try {whole}")),
                "{whole}"
            );
        }
        assert!(!joined.contains("/usr/local/etc") && !joined.contains("/usr/local/var"));
        assert!(joined.contains("--ro-bind-try /usr/bin /usr/bin"));
        assert!(joined.contains("--ro-bind-try /etc/passwd /etc/passwd"));
        assert!(!joined.contains("/etc/shadow") && !joined.contains("/etc/environment"));
        // Of /etc/ssl, the public certificates and the settings file, and not the directory of private keys.
        assert!(joined.contains("--ro-bind-try /etc/ssl/certs /etc/ssl/certs"));
        assert!(!joined.contains("/etc/ssl /etc/ssl") && !joined.contains("/etc/ssl/private"));
        // The kernel's lists of keys are covered: they name the keys of the person the run is for.
        let proc = joined.find("--proc /proc").unwrap();
        for list in ["/proc/keys", "/proc/key-users"] {
            let cover = joined
                .find(&format!("--ro-bind-try /dev/null {list}"))
                .unwrap_or_else(|| panic!("{list} is not covered: {joined}"));
            assert!(proc < cover, "{list} is covered before /proc is mounted");
        }
        // The whole machine is never bound, and the usual homes of sockets are empty directories.
        assert!(!joined.contains("--ro-bind / /") && !joined.contains("--bind / /"));
        assert!(joined.contains("--tmpfs /tmp") && joined.contains("--tmpfs /run"));
        assert!(joined.contains("--ro-bind /tools /tools"));
        assert!(joined.contains("--bind /room/checkout /room/checkout"));
        assert!(joined.contains("--tmpfs /tools/keys"));
        assert!(joined.contains("--ro-bind /dev/null /tools/token"));
        // What is hidden is covered after what is shown, and before the run's own two directories are bound:
        // a hidden directory that holds the checkout must not cover it.
        let at = |part: &str| joined.find(part).unwrap();
        assert!(at("--ro-bind /tools /tools") < at("--tmpfs /tools/keys"));
        assert!(at("--tmpfs /tools/keys") < at("--bind /room/checkout /room/checkout"));
        assert!(at("--ro-bind /dev/null /tools/token") < at("--bind /room/checkout"));
        // A hidden directory that holds something shown is covered after that is bound, so hiding wins.
        assert!(at("--ro-bind /keys/tool /keys/tool") < at("--tmpfs /keys"));
        assert!(at("--tmpfs /keys") < at("--bind /room/checkout"));
        // What is hidden outside everything shown is not there at all, so it gets no cover: a cover would
        // make its name, and tell the run that it exists.
        assert!(!joined.contains("/home/someone"), "{joined}");
        assert!(!joined.contains("--tmpfs /room"), "{joined}");
        // Every writable bind is one of the two directories.
        let writable: Vec<&str> = args
            .windows(2)
            .filter(|w| w[0] == "--bind")
            .map(|w| w[1].as_str())
            .collect();
        assert_eq!(writable, ["/room/checkout", "/room/scratch"]);
    }
}
