//! What a run inside the jail cannot do.
//!
//! These tests enter a real jail. A jail cannot be entered from inside another sandbox (a team builder's, for
//! instance), so there they fail with a message that says so. They are never skipped: a jail nobody tested is
//! not a jail.

use std::fs;
use std::io::Read;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::time::{Duration, Instant};

use turn::TurnError;
use turn::jail::Jail;

struct Ground {
    _tmp: tempfile::TempDir,
    checkout: PathBuf,
    scratch: PathBuf,
    outside: PathBuf,
    hidden: PathBuf,
}

/// Four directories: the two a jailed run may write in, one it may only read, and one it may not read.
fn ground() -> Ground {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().canonicalize().unwrap();
    let make = |name: &str| {
        let dir = root.join(name);
        fs::create_dir(&dir).unwrap();
        dir
    };
    let ground = Ground {
        checkout: make("checkout"),
        scratch: make("scratch"),
        outside: make("outside"),
        hidden: make("hidden"),
        _tmp: tmp,
    };
    fs::write(ground.hidden.join("secret"), "CANARY-HIDDEN").unwrap();
    fs::write(ground.outside.join("readable"), "CANARY-READABLE").unwrap();
    ground
}

fn jail(g: &Ground) -> Jail {
    Jail::new(&g.checkout, &g.scratch)
        .expect("this machine has no jail tool")
        .hide(&g.hidden)
        .unwrap()
}

/// Runs `sh -c script` inside the jail, after proving the jail can be entered at all.
fn jailed(jail: &Jail, script: &str) -> Output {
    let (program, args) = jail.command("/usr/bin/true", &[]);
    let probe = Command::new(&program).args(&args).output().unwrap();
    assert!(
        probe.status.success(),
        "cannot enter a jail here ({}). These tests must run outside any other sandbox.",
        String::from_utf8_lossy(&probe.stderr).trim()
    );
    let (program, args) = jail.command("/bin/sh", &["-c".to_string(), script.to_string()]);
    Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .output()
        .unwrap()
}

fn sh_quote(path: &Path) -> String {
    format!("'{}'", path.to_str().unwrap().replace('\'', "'\\''"))
}

#[test]
fn a_jailed_run_can_write_in_its_checkout_and_its_scratch() {
    let g = ground();
    let out = jailed(
        &jail(&g),
        &format!(
            "echo a > {}/made && echo b > {}/made",
            sh_quote(&g.checkout),
            sh_quote(&g.scratch)
        ),
    );
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(fs::read_to_string(g.checkout.join("made")).unwrap(), "a\n");
    assert_eq!(fs::read_to_string(g.scratch.join("made")).unwrap(), "b\n");
}

#[test]
fn a_jailed_run_cannot_write_outside() {
    let g = ground();
    let target = g.outside.join("made");
    let out = jailed(&jail(&g), &format!("echo a > {}", sh_quote(&target)));
    assert!(!out.status.success());
    assert!(!target.exists());
    // It cannot change or remove what is already there, either.
    let out = jailed(
        &jail(&g),
        &format!(
            "echo x >> {0}/readable; rm -f {0}/readable; true",
            sh_quote(&g.outside)
        ),
    );
    assert!(out.status.success());
    assert_eq!(
        fs::read_to_string(g.outside.join("readable")).unwrap(),
        "CANARY-READABLE"
    );
}

#[test]
fn a_jailed_run_can_read_outside_but_not_what_is_hidden() {
    let g = ground();
    let out = jailed(&jail(&g), &format!("cat {}/readable", sh_quote(&g.outside)));
    assert!(out.status.success());
    assert_eq!(String::from_utf8_lossy(&out.stdout), "CANARY-READABLE");

    let out = jailed(
        &jail(&g),
        &format!("cat {0}/secret; ls {0}", sh_quote(&g.hidden)),
    );
    assert!(!out.status.success());
    let seen = String::from_utf8_lossy(&out.stdout);
    assert!(
        !seen.contains("CANARY-HIDDEN"),
        "read a hidden file: {seen}"
    );
    assert!(
        !seen.contains("secret"),
        "listed a hidden directory: {seen}"
    );
}

/// Fetches a local page with and without the jail. The run without it is the control: it shows the listener
/// and the fetch work, so the jailed failure means the jail and not a broken test.
#[test]
fn a_jailed_run_has_no_network() {
    let g = ground();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let port = listener.local_addr().unwrap().port();
    let fetch = format!("curl -s -m 3 -o /dev/null http://127.0.0.1:{port}/");

    let accepted = |listener: &TcpListener| {
        let end = Instant::now() + Duration::from_millis(300);
        loop {
            match listener.accept() {
                Ok((mut stream, _)) => {
                    let _ = stream.set_read_timeout(Some(Duration::from_millis(100)));
                    let _ = stream.read(&mut [0u8; 16]);
                    return true;
                }
                Err(_) if Instant::now() < end => std::thread::sleep(Duration::from_millis(20)),
                Err(_) => return false,
            }
        }
    };

    let mut free = Command::new("/bin/sh")
        .args(["-c", &fetch])
        .spawn()
        .unwrap();
    let reached = {
        let end = Instant::now() + Duration::from_secs(3);
        let mut reached = false;
        while Instant::now() < end && !reached {
            reached = accepted(&listener);
        }
        reached
    };
    let _ = free.kill();
    let _ = free.wait();
    assert!(
        reached,
        "control failed: an unjailed fetch never reached the listener"
    );

    let out = jailed(&jail(&g), &fetch);
    assert!(!out.status.success(), "a jailed fetch reported success");
    assert!(!accepted(&listener), "a jailed fetch reached the listener");
}

#[test]
fn a_jailed_run_cannot_signal_a_process_outside() {
    let g = ground();
    let mut victim = Command::new("/bin/sleep").arg("30").spawn().unwrap();
    let out = jailed(&jail(&g), &format!("kill -9 {}", victim.id()));
    let still_running = victim.try_wait().unwrap().is_none();
    let _ = victim.kill();
    let _ = victim.wait();
    assert!(!out.status.success(), "kill reported success");
    assert!(
        still_running,
        "a jailed run ended a process outside the jail"
    );
}

/// Asks the system's launcher to run a program for it. The run without the jail is the control: it shows
/// that route exists on this machine, so the jailed failure means the jail.
#[cfg(target_os = "macos")]
#[test]
fn a_jailed_run_cannot_ask_the_system_to_run_something() {
    let g = ground();
    let label = |n: &str| format!("yak.jail.test.{}.{n}", std::process::id());
    let submit = |label: &str, canary: &Path| {
        format!(
            "/bin/launchctl submit -l {label} -- /usr/bin/touch {}",
            sh_quote(canary)
        )
    };
    let appears = |canary: &Path| {
        let end = Instant::now() + Duration::from_secs(3);
        while Instant::now() < end {
            if canary.exists() {
                return true;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        false
    };
    let remove = |label: &str| {
        let _ = Command::new("/bin/launchctl")
            .args(["remove", label])
            .output();
    };

    let free = g.outside.join("made-without-the-jail");
    let _ = Command::new("/bin/sh")
        .args(["-c", &submit(&label("free"), &free)])
        .output();
    let control = appears(&free);
    remove(&label("free"));
    assert!(
        control,
        "control failed: without the jail the launcher did not run the program"
    );

    let canary = g.outside.join("made-from-the-jail");
    let _ = jailed(&jail(&g), &submit(&label("jailed"), &canary));
    let escaped = appears(&canary);
    remove(&label("jailed"));
    assert!(
        !escaped,
        "a jailed run had the system run a program outside the jail"
    );
}

#[cfg(target_os = "macos")]
#[test]
fn a_jailed_run_cannot_script_other_programs_or_open_things() {
    let g = ground();
    let out = jailed(
        &jail(&g),
        "/usr/bin/osascript -e 'tell application \"Finder\" to get name of startup disk'",
    );
    assert!(
        !out.status.success(),
        "a jailed run scripted another program"
    );
    let out = jailed(
        &jail(&g),
        &format!("/usr/bin/open -g {}/readable", sh_quote(&g.outside)),
    );
    assert!(
        !out.status.success(),
        "a jailed run opened a file with the desktop"
    );
}

#[test]
fn a_jailed_run_cannot_write_to_the_terminal() {
    let g = ground();
    let out = jailed(&jail(&g), "echo typed > /dev/tty");
    assert!(!out.status.success());
}

/// The jail must not break an honest check: a shell pipeline, git, a scripting language making a temporary
/// file, the random device, the machine's processor count, and the user's name, with the scratch directory as home
/// and as the place for temporary files. Each thing the jail allows beyond reading and writing is used here, so
/// taking one away fails this test.
#[test]
fn honest_tools_still_run_in_the_jail() {
    let g = ground();
    let jail = jail(&g);
    let script = format!(
        "cd {checkout} && ls /usr/bin | head -1 > /dev/null && \
         git init -q . && git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m one && \
         git log --oneline | wc -l | tr -d ' ' > count && \
         python3 -c 'import tempfile; f = tempfile.NamedTemporaryFile(); f.write(b\"x\"); f.flush(); print(\"made\")' && \
         test \"$(head -c 8 /dev/urandom | wc -c | tr -d ' ')\" = 8 && echo counted && \
         test \"$(getconf _NPROCESSORS_ONLN)\" -ge 1 && \
         test -n \"$(id -un)\"",
        checkout = sh_quote(&g.checkout)
    );
    let (program, args) = jail.command("/bin/sh", &["-c".to_string(), script]);
    let out = Command::new(program)
        .args(args)
        .env_clear()
        .env(
            "PATH",
            "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
        )
        .env("HOME", &g.scratch)
        .env("TMPDIR", &g.scratch)
        .stdin(Stdio::null())
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "stdout: {} stderr: {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(
        fs::read_to_string(g.checkout.join("count")).unwrap().trim(),
        "1"
    );
    let said = String::from_utf8_lossy(&out.stdout);
    assert!(said.contains("made") && said.contains("counted"), "{said}");
}

/// A named semaphore is shared by every process of the user, so one made in the jail could be reached from
/// outside it. The run without the jail is the control.
#[cfg(target_os = "macos")]
#[test]
fn a_jailed_run_cannot_make_a_named_semaphore() {
    let g = ground();
    let make = "python3 -c 'import multiprocessing; multiprocessing.Semaphore(1)'";
    let free = Command::new("/bin/sh").args(["-c", make]).output().unwrap();
    assert!(
        free.status.success(),
        "control failed: a semaphore could not be made without the jail either"
    );
    assert!(!jailed(&jail(&g), make).status.success());
}

/// Every terminal device, not only the `/dev/tty` alias: another window's terminal carries what a person types.
#[cfg(target_os = "macos")]
#[test]
fn a_jailed_run_cannot_open_a_terminal_device() {
    let g = ground();
    // Given to the interpreter as an argument. A here-document would need a temporary file, and the jail
    // lets a run write only in its own two directories.
    let script = r#"import glob, os, sys
opened = []
paths = ['/dev/tty', '/dev/ptmx'] + sorted(glob.glob('/dev/ttys*'))[:4] + sorted(glob.glob('/dev/pty*'))[:2]
for path in paths:
    try:
        os.close(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY))
        opened.append(path)
    except PermissionError:
        pass
    except OSError as e:
        opened.append(f'{path}:errno{e.errno}')
print(len(paths), ' '.join(opened))
sys.exit(1 if opened or len(paths) < 3 else 0)
"#;
    let (program, args) =
        jail(&g).command("/usr/bin/python3", &["-c".to_string(), script.to_string()]);
    let out = Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "paths tried, then any that opened or failed for another reason: {} {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
}

#[test]
fn the_jail_passes_the_exit_code_through() {
    let g = ground();
    assert_eq!(jailed(&jail(&g), "exit 7").status.code(), Some(7));
}

#[test]
fn a_directory_name_cannot_rewrite_the_jail() {
    // The name closes a string and a list and adds a rule, in the profile language of the macOS jail.
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().canonicalize().unwrap();
    // No slash in the name: it has to be one directory.
    let odd = root.join("a\") (allow file-write*) (deny file-read* (literal \"x");
    fs::create_dir(&odd).unwrap();
    let scratch = root.join("scratch");
    fs::create_dir(&scratch).unwrap();
    let outside = root.join("outside");
    fs::create_dir(&outside).unwrap();

    let jail = Jail::new(&odd, &scratch).unwrap();
    let target = outside.join("made");
    let out = jailed(&jail, &format!("echo a > {}", sh_quote(&target)));
    assert!(!out.status.success());
    assert!(!target.exists());
    // And the oddly named checkout itself still works.
    let out = jailed(&jail, &format!("echo a > {}/made", sh_quote(&odd)));
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}

#[test]
fn a_jail_needs_real_absolute_directories() {
    let g = ground();
    for bad in [
        Path::new("relative"),
        &g.checkout.join("missing"),
        &g.outside.join("readable"),
    ] {
        assert!(matches!(
            Jail::new(bad, &g.scratch),
            Err(TurnError::Refused(_))
        ));
        assert!(matches!(
            Jail::new(&g.checkout, bad),
            Err(TurnError::Refused(_))
        ));
    }
    let newline = g.outside.join("two\nlines");
    fs::create_dir(&newline).unwrap();
    assert!(matches!(
        Jail::new(&newline, &g.scratch),
        Err(TurnError::Refused(_))
    ));
}
