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

/// Runs `program args` inside the jail the way the room does: started in the checkout, with a cleared
/// environment whose home and place for temporary files are the scratch directory. A refusal seen here is one
/// a real run would meet, and not one made by starting somewhere the jail does not show.
fn run_in(jail: &Jail, program: &str, args: &[String]) -> Output {
    let (program, args) = jail.command(program, args);
    Command::new(program)
        .args(args)
        .current_dir(jail.checkout())
        .env_clear()
        .env(
            "PATH",
            "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
        )
        .env("HOME", jail.scratch())
        .env("TMPDIR", jail.scratch())
        .stdin(Stdio::null())
        .output()
        .unwrap()
}

/// Runs `sh -c script` inside the jail, after proving the jail can be entered at all.
fn jailed(jail: &Jail, script: &str) -> Output {
    let probe = run_in(jail, "/usr/bin/true", &[]);
    assert!(
        probe.status.success(),
        "cannot enter a jail here ({}). These tests must run outside any other sandbox.",
        String::from_utf8_lossy(&probe.stderr).trim()
    );
    run_in(jail, "/bin/sh", &["-c".to_string(), script.to_string()])
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

/// What `sh -c script` prints with no jail: the control for a read the jail refuses.
fn unjailed(script: &str) -> String {
    let out = Command::new("/bin/sh")
        .args(["-c", script])
        .stdin(Stdio::null())
        .output()
        .unwrap();
    String::from_utf8_lossy(&out.stdout).into_owned()
}

#[test]
fn a_jailed_run_reads_only_what_it_is_shown() {
    let g = ground();
    let read = format!("cat {}/readable", sh_quote(&g.outside));
    // The control: with no jail the same command reads the file.
    assert_eq!(unjailed(&read), "CANARY-READABLE");

    let out = jailed(&jail(&g), &read);
    assert!(!out.status.success(), "read a file nobody showed it");
    assert!(!String::from_utf8_lossy(&out.stdout).contains("CANARY"));
    // Nor can it list the directory its checkout is in.
    let root = g.checkout.parent().unwrap();
    let out = jailed(&jail(&g), &format!("ls {}", sh_quote(root)));
    assert!(!String::from_utf8_lossy(&out.stdout).contains("outside"));

    let shown = jail(&g).allow_read(&g.outside).unwrap();
    let out = jailed(&shown, &read);
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&out.stdout), "CANARY-READABLE");
}

#[test]
fn a_jailed_run_cannot_read_the_home_of_whoever_runs_the_room() {
    let home = PathBuf::from(std::env::var_os("HOME").expect("this test needs HOME"));
    let list = format!("ls -a {}", sh_quote(&home));
    // The control: with no jail the home lists more than `.` and `..`.
    assert!(unjailed(&list).lines().count() > 2, "the home is empty");

    let g = ground();
    let out = jailed(&jail(&g), &list);
    assert!(!out.status.success());
    assert_eq!(String::from_utf8_lossy(&out.stdout), "");
}

/// macOS mounts the disk that holds every home again below `/System/Volumes/Data`, so a home has a second
/// name that starts with `/System`. The run with no jail is the control: it shows the second name works here.
#[cfg(target_os = "macos")]
#[test]
fn a_jailed_run_cannot_reach_a_home_or_another_disk_by_its_other_name() {
    let g = ground();
    let home = PathBuf::from(std::env::var_os("HOME").expect("this test needs HOME"));
    let other_name = |path: &Path| {
        let mut name = std::ffi::OsString::from("/System/Volumes/Data");
        name.push(path.as_os_str());
        PathBuf::from(name)
    };
    let script = format!(
        "ls -a {home}; cat {file}; ls /System/Volumes; ls /System/Volumes/Data; echo finished",
        home = sh_quote(&other_name(&home)),
        file = sh_quote(&other_name(&g.outside.join("readable"))),
    );
    let free = unjailed(&script);
    assert!(free.contains("CANARY-READABLE"), "control failed: {free}");
    assert!(
        free.lines().any(|line| line == "Data") && free.lines().any(|line| line == "Users"),
        "control failed: {free}"
    );

    let out = jailed(&jail(&g), &script);
    assert_eq!(
        String::from_utf8_lossy(&out.stdout),
        "finished\n",
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}

#[test]
fn what_is_hidden_stays_hidden_inside_what_is_shown() {
    let g = ground();
    let root = g.checkout.parent().unwrap();
    // The whole ground is shown, and one directory and one file in it are hidden.
    let jail = Jail::new(&g.checkout, &g.scratch)
        .unwrap()
        .allow_read(root)
        .unwrap()
        .hide(&g.hidden)
        .unwrap()
        .hide(&g.outside.join("readable"))
        .unwrap();
    fs::write(g.outside.join("other"), "CANARY-OTHER").unwrap();

    let out = jailed(&jail, &format!("cat {}/other", sh_quote(&g.outside)));
    assert_eq!(String::from_utf8_lossy(&out.stdout), "CANARY-OTHER");
    let out = jailed(
        &jail,
        &format!(
            "cat {0}/secret; ls {0}; cat {1}/readable",
            sh_quote(&g.hidden),
            sh_quote(&g.outside)
        ),
    );
    assert!(!out.status.success());
    let seen = String::from_utf8_lossy(&out.stdout);
    assert!(!seen.contains("CANARY"), "read what was hidden: {seen}");
    assert!(
        !seen.contains("secret"),
        "listed a hidden directory: {seen}"
    );
}

/// Showing something inside a hidden directory does not bring it back: hiding wins, in whichever order the
/// two were asked for.
#[test]
fn what_is_shown_inside_something_hidden_stays_hidden() {
    let g = ground();
    let secret = g.hidden.join("secret");
    let read = format!("cat {}", sh_quote(&secret));
    assert_eq!(unjailed(&read), "CANARY-HIDDEN");
    let shown_then_hidden = Jail::new(&g.checkout, &g.scratch)
        .unwrap()
        .allow_read(&secret)
        .unwrap()
        .hide(&g.hidden)
        .unwrap();
    let hidden_then_shown = jail(&g).allow_read(&secret).unwrap();
    for jail in [shown_then_hidden, hidden_then_shown] {
        let out = jailed(&jail, &read);
        assert!(!out.status.success());
        assert!(!String::from_utf8_lossy(&out.stdout).contains("CANARY"));
        assert_eq!(jail.hides(&secret), Some(g.hidden.as_path()));
    }
    assert_eq!(jail(&g).hides(&g.outside), None);
}

/// A room kept below a hidden directory (`~/.superyak`, say) must still give a run its own checkout.
#[test]
fn a_checkout_inside_a_hidden_directory_is_still_the_runs_own() {
    let g = ground();
    let root = g.checkout.parent().unwrap();
    fs::write(g.checkout.join("mine"), "MINE").unwrap();
    let jail = Jail::new(&g.checkout, &g.scratch)
        .unwrap()
        .hide(root)
        .unwrap();
    let out = jailed(
        &jail,
        &format!(
            "cat {0}/mine && echo more > {0}/made && echo t > {1}/made",
            sh_quote(&g.checkout),
            sh_quote(&g.scratch)
        ),
    );
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&out.stdout), "MINE");
    // What is beside it stays hidden.
    let out = jailed(&jail, &format!("cat {}/readable", sh_quote(&g.outside)));
    assert!(!String::from_utf8_lossy(&out.stdout).contains("CANARY"));
}

#[test]
fn one_file_can_be_shown_and_run_without_its_neighbours() {
    use std::os::unix::fs::PermissionsExt;
    let g = ground();
    let tool = g.outside.join("tool.sh");
    fs::write(&tool, "#!/bin/sh\necho TOOL-RAN\n").unwrap();
    fs::set_permissions(&tool, fs::Permissions::from_mode(0o755)).unwrap();
    let run = format!("{}; cat {}/readable", sh_quote(&tool), sh_quote(&g.outside));

    // Not shown, it cannot be run.
    let out = jailed(&jail(&g), &run);
    assert!(!String::from_utf8_lossy(&out.stdout).contains("TOOL-RAN"));

    let shown = jail(&g).allow_read(&tool).unwrap();
    let out = jailed(&shown, &run);
    let said = String::from_utf8_lossy(&out.stdout);
    assert!(
        said.contains("TOOL-RAN"),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(!said.contains("CANARY"), "read the file beside it: {said}");
}

#[test]
fn the_whole_machine_cannot_be_shown() {
    let g = ground();
    assert!(matches!(
        jail(&g).allow_read(Path::new("/")),
        Err(TurnError::Refused(_))
    ));
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

/// Three ways to send to a Unix socket that some program outside is listening on. `argv[1]` is a stream
/// socket's path and `argv[2]` a datagram socket's. The third way starts from a pair of joined datagram ends,
/// which is no socket to anywhere until one end is told an address.
const SEND_TO_UNIX_SOCKETS: &str = r#"import socket, sys
def attempt(name, send):
    try:
        send()
        print(name + ":sent")
    except OSError as e:
        print(name + ":refused")
def stream():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sys.argv[1])
    s.sendall(b"STREAM")
def datagram():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.sendto(b"DATAGRAM", sys.argv[2])
def from_a_pair():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
    a.sendto(b"PAIR", sys.argv[2])
attempt("stream", stream)
attempt("datagram", datagram)
attempt("pair", from_a_pair)
# A pair of joined stream ends reaches nothing but itself, and programs use one to talk to their children.
a, b = socket.socketpair()
a.sendall(b"x")
print("own-pair:" + ("works" if b.recv(1) == b"x" else "broken"))
"#;

/// A Unix socket is a file. On Linux a jailed run has a network of its own, and that does not keep it from a
/// socket file it can see: the checkout here, or a tool directory named for it where some service of the
/// machine listens. The run with no jail is the control: all three sends arrive.
#[test]
fn a_jailed_run_cannot_reach_a_unix_socket_it_can_see() {
    use std::os::unix::net::{UnixDatagram, UnixListener};
    let g = ground();
    let (stream_at, datagram_at) = (g.checkout.join("s.sock"), g.checkout.join("d.sock"));
    let listener = UnixListener::bind(&stream_at).unwrap();
    listener.set_nonblocking(true).unwrap();
    let datagrams = UnixDatagram::bind(&datagram_at).unwrap();
    datagrams
        .set_read_timeout(Some(Duration::from_millis(300)))
        .unwrap();
    // What arrived: whether a stream connection was made, and each datagram received.
    let arrived = || {
        let end = Instant::now() + Duration::from_millis(300);
        let mut connected = false;
        while Instant::now() < end && !connected {
            connected = listener.accept().is_ok();
            std::thread::sleep(Duration::from_millis(20));
        }
        let mut got = Vec::new();
        let mut buffer = [0u8; 16];
        while let Ok(n) = datagrams.recv(&mut buffer) {
            got.push(String::from_utf8_lossy(&buffer[..n]).into_owned());
        }
        got.sort();
        (connected, got)
    };
    let args = [
        "-c".to_string(),
        SEND_TO_UNIX_SOCKETS.to_string(),
        stream_at.to_str().unwrap().to_string(),
        datagram_at.to_str().unwrap().to_string(),
    ];

    // Sending from one end of a joined pair to some other address is something Linux allows and macOS does
    // not, jail or no jail. So without a jail it arrives on Linux only.
    let pair_goes = cfg!(target_os = "linux");
    let free = Command::new("/usr/bin/python3")
        .args(&args)
        .output()
        .unwrap();
    assert_eq!(
        String::from_utf8_lossy(&free.stdout),
        format!(
            "stream:sent\ndatagram:sent\npair:{}\nown-pair:works\n",
            if pair_goes { "sent" } else { "refused" }
        ),
        "control failed: {}",
        String::from_utf8_lossy(&free.stderr)
    );
    let mut sent = vec!["DATAGRAM".to_string()];
    if pair_goes {
        sent.push("PAIR".to_string());
    }
    assert_eq!(arrived(), (true, sent), "control failed");

    let out = run_in(&jail(&g), "/usr/bin/python3", &args);
    assert_eq!(
        String::from_utf8_lossy(&out.stdout),
        "stream:refused\ndatagram:refused\npair:refused\nown-pair:works\n",
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert_eq!(arrived(), (false, Vec::new()), "something arrived");
}

/// Things of the kernel's that a private network and private process numbers do not cover, each tried from
/// inside: the person's keyring, a kind of netlink other than routes, and the kernel's cipher sockets as a
/// stand-in for every family the jail has not named. And two things a run keeps: netlink for routes, which a
/// name lookup asks about, and its own loopback.
#[cfg(target_os = "linux")]
const BEYOND_THE_NETWORK: &str = r#"import ctypes, platform, socket
libc = ctypes.CDLL(None, use_errno=True)
keyctl = {"aarch64": 219, "x86_64": 250}[platform.machine()]
# Ask which keyring is the session's (operation 0, keyring -3), without making one.
print("keyring:" + ("reached" if libc.syscall(keyctl, 0, -3, 0) >= 0 else "refused"))
try:
    print("key-list:" + ("shown" if open("/proc/keys").read().strip() else "hidden"))
except OSError:
    print("key-list:hidden")
def make(name, *args):
    try:
        socket.socket(*args).close()
        print(name + ":made")
    except OSError:
        print(name + ":refused")
make("netlink-routes", socket.AF_NETLINK, socket.SOCK_RAW, 0)
make("netlink-device-events", socket.AF_NETLINK, socket.SOCK_RAW, 15)
make("cipher-socket", socket.AF_ALG, socket.SOCK_SEQPACKET, 0)
try:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    caller = socket.socket()
    caller.settimeout(3)
    caller.connect(listener.getsockname())
    print("own-loopback:works")
except OSError as e:
    print("own-loopback:broken " + str(e))
"#;

/// The run with no jail is the control: there all of it is reached.
#[cfg(target_os = "linux")]
#[test]
fn a_jailed_run_on_linux_reaches_no_keyring_and_makes_only_the_sockets_it_is_let() {
    let g = ground();
    let args = ["-c".to_string(), BEYOND_THE_NETWORK.to_string()];
    let free = Command::new("/usr/bin/python3")
        .args(&args)
        .output()
        .unwrap();
    assert_eq!(
        String::from_utf8_lossy(&free.stdout),
        "keyring:reached\nkey-list:shown\nnetlink-routes:made\nnetlink-device-events:made\n\
         cipher-socket:made\nown-loopback:works\n",
        "control failed: {}",
        String::from_utf8_lossy(&free.stderr)
    );
    let out = run_in(&jail(&g), "/usr/bin/python3", &args);
    assert_eq!(
        String::from_utf8_lossy(&out.stdout),
        "keyring:refused\nkey-list:hidden\nnetlink-routes:made\nnetlink-device-events:refused\n\
         cipher-socket:refused\nown-loopback:works\n",
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
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

/// Two questions to the desktop's own services that show nothing on the screen: run a one-line script, and
/// list the running programs. With no jail both are answered, which is the control. The two below them would
/// act on a person's desktop if they worked, so they are tried only inside the jail.
#[cfg(target_os = "macos")]
#[test]
fn a_jailed_run_cannot_script_other_programs_or_open_things() {
    let g = ground();
    let script = "/usr/bin/osascript -e 'return 6 * 7'";
    let list = "/usr/bin/lsappinfo list | head -1";
    assert_eq!(unjailed(script).trim(), "42", "control failed");
    assert!(!unjailed(list).trim().is_empty(), "control failed");
    let out = jailed(&jail(&g), script);
    assert!(!String::from_utf8_lossy(&out.stdout).contains("42"));
    let out = jailed(&jail(&g), list);
    assert_eq!(String::from_utf8_lossy(&out.stdout).trim(), "");

    let out = jailed(
        &jail(&g),
        "/usr/bin/osascript -e 'tell application \"Finder\" to get name of startup disk'",
    );
    assert!(
        !out.status.success(),
        "a jailed run scripted another program"
    );
    fs::write(g.checkout.join("to-open.txt"), "x").unwrap();
    let out = jailed(
        &jail(&g),
        &format!("/usr/bin/open -g {}/to-open.txt", sh_quote(&g.checkout)),
    );
    assert!(
        !out.status.success(),
        "a jailed run opened a file with the desktop"
    );
}

/// Gives a command a terminal of its own and prints everything that reaches that terminal. `argv[1:]` is the
/// command. A program that writes to `/dev/tty` writes to this terminal, so what it wrote is in the output.
/// It gives up after twenty seconds, so a command that never ends cannot hold a test.
const UNDER_A_TERMINAL: &str = r#"import os, pty, select, sys, time
pid, terminal = pty.fork()
if pid == 0:
    try:
        os.execv(sys.argv[1], sys.argv[1:])
    finally:
        os._exit(127)
seen = b""
end = time.time() + 20
while time.time() < end:
    ready, _, _ = select.select([terminal], [], [], 0.2)
    if terminal in ready:
        try:
            data = os.read(terminal, 4096)
        except OSError:
            break
        if not data:
            break
        seen += data
    elif os.waitpid(pid, os.WNOHANG)[0] == pid:
        pid = 0
        break
if pid:
    try:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
    except OSError:
        pass
sys.stdout.write(seen.decode(errors="replace"))
"#;

/// What reaches a terminal when `command` runs with that terminal as its own.
fn seen_on_its_terminal(g: &Ground, command: (&Path, &[String])) -> String {
    let out = Command::new("/usr/bin/python3")
        .args(["-c", UNDER_A_TERMINAL])
        .arg(command.0)
        .args(command.1)
        .current_dir(&g.checkout)
        .env_clear()
        .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        .env("HOME", &g.scratch)
        .env("TMPDIR", &g.scratch)
        .stdin(Stdio::null())
        .output()
        .unwrap();
    String::from_utf8_lossy(&out.stdout).into_owned()
}

/// The command is started from a terminal, as a clock a person started by hand is. With no jail what it writes
/// to `/dev/tty` reaches that terminal, which is the control: a test with no terminal at all would see the
/// write fail whatever the jail did.
#[test]
fn a_jailed_run_cannot_write_to_the_terminal() {
    let g = ground();
    let write = ["-c".to_string(), "echo MARK-typed > /dev/tty".to_string()];
    let free = seen_on_its_terminal(&g, (Path::new("/bin/sh"), &write));
    assert!(free.contains("MARK-typed"), "control failed: {free:?}");
    let (tool, args) = jail(&g).command("/bin/sh", &write);
    let jailed = seen_on_its_terminal(&g, (&tool, &args));
    assert!(!jailed.contains("MARK-typed"), "{jailed:?}");
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
    let make = "python3 -c 'import multiprocessing; print(\"ready\", flush=True); multiprocessing.Semaphore(1)'";
    let free = Command::new("/bin/sh").args(["-c", make]).output().unwrap();
    assert!(
        free.status.success(),
        "control failed: a semaphore could not be made without the jail either"
    );
    let out = jailed(&jail(&g), make);
    // It got as far as making one, and that is what was refused.
    assert_eq!(
        String::from_utf8_lossy(&out.stdout).trim(),
        "ready",
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(!out.status.success());
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
    let out = run_in(
        &jail(&g),
        "/usr/bin/python3",
        &["-c".to_string(), script.to_string()],
    );
    assert!(
        out.status.success(),
        "paths tried, then any that opened or failed for another reason: {} {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
}

/// A run can change everything inside its two directories and nothing about the directories themselves. If it
/// could move its checkout away and leave a link in its place, the next run in that sandbox would be jailed
/// around whatever the link names.
#[test]
fn a_jailed_run_cannot_replace_its_checkout_or_its_scratch() {
    let g = ground();
    fs::write(g.checkout.join("mine"), "MINE").unwrap();
    let (c, s, o) = (
        sh_quote(&g.checkout),
        sh_quote(&g.scratch),
        sh_quote(&g.outside),
    );
    // The control: what is inside both is the run's to make, move and remove.
    let out = jailed(
        &jail(&g),
        &format!(
            "mkdir {c}/d && mv {c}/mine {c}/d/mine && mv {c}/d/mine {c}/mine && rmdir {c}/d && echo t > {s}/t && rm {s}/t && echo fine"
        ),
    );
    assert_eq!(
        String::from_utf8_lossy(&out.stdout),
        "fine\n",
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );

    use std::os::unix::fs::{MetadataExt, PermissionsExt};
    let which = |root: &Path| {
        let meta = fs::symlink_metadata(root).unwrap();
        assert!(meta.is_dir(), "{} is no longer a directory", root.display());
        (meta.dev(), meta.ino())
    };
    let before = [which(&g.checkout), which(&g.scratch)];
    jailed(
        &jail(&g),
        &format!(
            "mv {c} {s}/moved; ln -s {o} {c}; rmdir {s}; ln -s {o} {s}; mv {s} {c}/moved; chmod 000 {c}; true"
        ),
    );
    // Each is still a directory, and the same one. What is inside them is the run's own to move about, and on
    // Linux `mv` does that when it finds it cannot rename the directory itself.
    assert_eq!([which(&g.checkout), which(&g.scratch)], before);
    assert_eq!(
        fs::read_dir(&g.outside).unwrap().count(),
        1,
        "outside changed"
    );
    // On macOS the run cannot change its checkout's permissions either. On Linux it can, as it can for any
    // directory of its own, and the room removes such a tree all the same.
    let mode = fs::symlink_metadata(&g.checkout)
        .unwrap()
        .permissions()
        .mode()
        & 0o777;
    if cfg!(target_os = "macos") {
        assert_ne!(mode, 0, "the checkout's permissions were taken away");
    }
    fs::set_permissions(&g.checkout, fs::Permissions::from_mode(0o700)).unwrap();
}

#[test]
fn the_whole_machine_cannot_be_a_checkout_or_a_scratch() {
    let g = ground();
    assert!(matches!(
        Jail::new(Path::new("/"), &g.scratch),
        Err(TurnError::Refused(_))
    ));
    assert!(matches!(
        Jail::new(&g.checkout, Path::new("/")),
        Err(TurnError::Refused(_))
    ));
}

/// What a process says about another one, asked three ways. `argv[1]` is the other process.
#[cfg(target_os = "macos")]
const ASK_ABOUT_ANOTHER: &str = r#"import ctypes as c, os, sys
lib = c.CDLL(None, use_errno=True)
other = int(sys.argv[1])
said = []
# The process table: every process's number and name.
mib = (c.c_int * 4)(1, 14, 0, 0)
n = c.c_size_t(0)
said.append("table:" + ("listed" if lib.sysctl(mib, 4, None, c.byref(n), None, 0) == 0 and n.value else "refused"))
# Where another process's program is, and where this one's is.
libproc = c.CDLL("/usr/lib/libproc.dylib", use_errno=True)
buf = c.create_string_buffer(4096)
said.append("path-of-other:" + ("told" if libproc.proc_pidpath(other, buf, 4096) > 0 else "refused"))
said.append("path-of-self:" + ("told" if libproc.proc_pidpath(os.getpid(), buf, 4096) > 0 else "refused"))
# Another process's arguments and environment.
mib = (c.c_int * 3)(1, 49, other)
buf = c.create_string_buffer(262144)
n = c.c_size_t(len(buf))
raw = buf.raw[: n.value] if lib.sysctl(mib, 3, buf, c.byref(n), None, 0) == 0 else b""
said.append("environment-of-other:" + ("read" if b"YAK_JAIL_CANARY=FAKE_ONLY" in raw else "refused"))
print(" ".join(said))
"#;

/// A stand-in for some other process of the same person: a sleeper with a made-up variable in its environment.
#[cfg(target_os = "macos")]
struct Canary(std::process::Child);

#[cfg(target_os = "macos")]
impl Canary {
    fn start() -> Canary {
        let child = Command::new("/usr/bin/python3")
            .args(["-c", "import time; time.sleep(60)"])
            .env("YAK_JAIL_CANARY", "FAKE_ONLY")
            .stdin(Stdio::null())
            .spawn()
            .unwrap();
        // Long enough for the interpreter to have started, so that what is asked about is that program.
        std::thread::sleep(Duration::from_millis(500));
        Canary(child)
    }

    /// What `ASK_ABOUT_ANOTHER` prints about this process, asked from inside `jail` or with no jail.
    fn asked(&self, jail: Option<&Jail>) -> String {
        let args = [
            "-c".to_string(),
            ASK_ABOUT_ANOTHER.to_string(),
            self.0.id().to_string(),
        ];
        let out = match jail {
            Some(jail) => run_in(jail, "/usr/bin/python3", &args),
            None => Command::new("/usr/bin/python3")
                .args(&args)
                .output()
                .unwrap(),
        };
        String::from_utf8_lossy(&out.stdout).trim().to_string()
    }
}

#[cfg(target_os = "macos")]
impl Drop for Canary {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// The run with no jail is the control: all four questions are answered there.
///
/// The fourth, another process's arguments and environment, is where tokens are. On macOS it is answered
/// through either of two doors: questions about other processes, which "deny by default" does not cover, and a
/// system setting under `kern.proc`. Shutting one leaves the other open. Measured on macOS 27.0.1: the read
/// succeeds with every system setting denied, and it succeeds with questions about others denied; it fails
/// only with both. `the_macos_profile_denies_by_default_and_names_what_it_allows` holds the profile to both.
#[cfg(target_os = "macos")]
#[test]
fn a_jailed_run_cannot_ask_about_another_process_or_read_its_environment() {
    let g = ground();
    let canary = Canary::start();
    assert_eq!(
        canary.asked(None),
        "table:listed path-of-other:told path-of-self:told environment-of-other:read",
        "control failed"
    );
    assert_eq!(
        canary.asked(Some(&jail(&g))),
        "table:refused path-of-other:refused path-of-self:told environment-of-other:refused"
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
