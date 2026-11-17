//! What a run inside the jail cannot do.
//!
//! These tests enter a real jail. A jail cannot be entered from inside another sandbox (a team builder's, for
//! instance): there they fail with a message that says so, and so a plain `cargo test` leaves out each one that
//! enters a jail and prints why. Where the room can run, the whole suite is asked for with `-- --include-ignored`:
//! a jail nobody tested is not a jail.

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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
///
/// Of the seven calls the filter refuses outright, one is tried here from inside a jail: one of the keyring's
/// three. The other six are held by the filter's own tests, which run its program as the kernel would, and
/// not by a try inside a jail.
#[cfg(target_os = "linux")]
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
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

/// What a run can try with one end of a Unix pair of the seqpacket kind, to reach a socket that listens by
/// name. `argv[1]` is that socket's path. Each try says one line. A try the kernel must refuse is held to the
/// error the kernel is known to give for it, read from a run on Linux 6.12 with no jail: a timeout, or any
/// other error, is this helper failing and not the kernel refusing, and it ends the helper there with an
/// error, which fails the test.
#[cfg(target_os = "linux")]
const AN_END_OF_A_SEQPACKET_PAIR: &str = r#"import ctypes, errno, os, socket, stat, sys
target = sys.argv[1]
def say(name, word):
    print(name + ":" + word, flush=True)
def refused(name, attempt, expected):
    try:
        attempt()
    except OSError as e:
        if isinstance(e, TimeoutError) or e.errno != expected:
            raise
        say(name, "refused")
        return
    say(name, "made")
say("name", "socket" if stat.S_ISSOCK(os.stat(target).st_mode) else "not-a-socket")
# With no jail a socket of that kind is made. In the jail the filter refuses it: "operation not permitted".
refused("socket-of-that-kind", lambda: socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET).close(), errno.EPERM)
try:
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
except PermissionError:
    say("pair", "refused")
    sys.exit(0)
say("pair", "made")
a.settimeout(2)
b.settimeout(2)
a.send(b"hello")
say("own-pair", "works" if b.recv(16) == b"hello" else "broken")
def named_send(name, payload):
    # The kernel drops the name and gives the message to the joined end.
    a.sendto(payload, target)
    say(name, "to-the-other-end" if b.recv(16) == payload else "lost")
named_send("named-send", b"NAMED")
refused("join", lambda: a.connect(target), errno.EISCONN)
# Unjoining, as a datagram socket is unjoined: joining "no family".
libc = ctypes.CDLL(None, use_errno=True)
no_family = (ctypes.c_ubyte * 16)()
if libc.connect(a.fileno(), no_family, 16) == 0:
    say("unjoin", "made")
elif ctypes.get_errno() == errno.EINVAL:
    say("unjoin", "refused")
else:
    raise OSError(ctypes.get_errno(), "unjoining failed, and not as the kernel refuses it")
named_send("named-send-after-unjoin", b"UNJOINED")
refused("join-after-unjoin", lambda: a.connect(target), errno.EISCONN)
b.close()
refused("named-send-after-close", lambda: a.sendto(b"AFTER", target), errno.EPIPE)
refused("join-after-close", lambda: a.connect(target), errno.EISCONN)
"#;

/// An end of a Unix pair of the kind named, given a name and told to listen: what that leaves. Each line is
/// one try. As in the script above, an error that is not the refusal expected ends the helper with an error.
/// Asked for "a-socket-joined-to-nothing" it is the control: such a socket, treated the same way, listens
/// and takes a caller in, so the lines can tell an end that does from one that does not.
/// With a fourth word it waits, each time it has told the end to listen, for a caller outside to have tried
/// the end's name: it leaves a file beside the name to say it is ready, and goes on when the caller has left
/// one to say it has called. That is how the run inside the jail is called from outside it.
#[cfg(target_os = "linux")]
const A_NAMED_END_OF_A_PAIR: &str = r#"import errno, os, socket, sys, time
kind = {"stream": socket.SOCK_STREAM, "seqpacket": socket.SOCK_SEQPACKET}[sys.argv[1]]
mine = sys.argv[2]
joined = {"an-end-of-a-pair": True, "a-socket-joined-to-nothing": False}[sys.argv[3]]
called_from_outside = len(sys.argv) > 4
def say(name, word):
    print(name + ":" + word, flush=True)
def refused(name, attempt, expected):
    try:
        attempt()
    except OSError as e:
        if isinstance(e, TimeoutError) or e.errno != expected:
            raise
        say(name, "refused")
        return
    say(name, "made")
if joined:
    end, other = socket.socketpair(socket.AF_UNIX, kind)
    other.settimeout(2)
else:
    end = socket.socket(socket.AF_UNIX, kind)
end.bind(mine)
say("bind", "made")
# Not blocking, so that accepting is asked of the kernel at once and never waited for.
end.setblocking(False)
def told_to_listen(name, step):
    # Whether the kernel answers yes or "invalid" is not held: it is not the same on every kernel. Any other
    # error ends the helper. What is held is what the answer leaves, in the lines after: an end that does not
    # listen, that takes no caller in, and that a socket made for its name cannot join.
    try:
        end.listen(4)
    except OSError as e:
        if e.errno != errno.EINVAL:
            raise
    say(name, "listens" if end.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) else "does-not-listen")
    if called_from_outside:
        open(mine + ".ready-" + step, "w").close()
        until = time.monotonic() + 60
        while not os.path.exists(mine + ".called-" + step):
            if time.monotonic() > until:
                raise TimeoutError("no caller outside said it had called")
            time.sleep(0.05)
def a_caller(name):
    # A socket made for the end's name, by this same process. With no jail one is made, and the kernel refuses
    # its joining. In the jail none can be made: the filter's own refusal, "operation not permitted", and no
    # other error. That line says nothing of the end: the caller from outside is what tries the end there.
    try:
        caller = socket.socket(socket.AF_UNIX, kind)
    except OSError as e:
        if e.errno != errno.EPERM:
            raise
        say(name, "none-can-be-made")
        return
    caller.settimeout(2)
    refused(name, lambda: caller.connect(mine), errno.ECONNREFUSED)
    caller.close()
def heard(name):
    # What has arrived at the end. Its other end sends it nothing here, so anything is from somewhere else.
    # Once the other end is closed, the end reads that closing, which is no bytes.
    try:
        arrived = end.recv(16)
    except BlockingIOError:
        arrived = b""
    say(name, "nothing" if arrived == b"" else "something")
told_to_listen("listen", "1")
if not joined:
    a_caller("a-caller")
    refused("accept", lambda: end.accept()[0].close(), errno.EINVAL)
    sys.exit(0)
refused("accept", lambda: end.accept(), errno.EINVAL)
a_caller("a-caller")
heard("heard")
# And the end is still joined to its other end.
end.send(b"still")
say("own-pair", "works" if other.recv(16) == b"still" else "broken")
other.close()
told_to_listen("listen-after-close", "2")
refused("accept-after-close", lambda: end.accept(), errno.EINVAL)
a_caller("a-caller-after-close")
heard("heard-after-close")
"#;

/// Listens by name with a socket of the seqpacket kind, and says each thing that arrives, until its input
/// ends. Told to stop, it first lets in whatever is still waiting, so that "stopped" means nothing else came.
/// It gives up by itself after a minute. With a second argument it hears nothing until it is told to stop:
/// that is for the test of the letting-in itself.
#[cfg(target_os = "linux")]
const LISTEN_AS_SEQPACKET: &str = r#"import select, socket, sys, time
hear_only_at_the_end = len(sys.argv) > 2
s = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
s.bind(sys.argv[1])
s.listen(8)
def hear(conn):
    conn.settimeout(1)
    try:
        data = conn.recv(64)
    except OSError:
        data = b""
    print("arrived:" + data.decode(errors="replace"), flush=True)
print("listening", flush=True)
end = time.monotonic() + 60
stopped = False
while time.monotonic() < end and not stopped:
    watched = [sys.stdin] if hear_only_at_the_end else [s, sys.stdin]
    ready, _, _ = select.select(watched, [], [], 0.2)
    if s in ready:
        hear(s.accept()[0])
    if sys.stdin in ready:
        stopped = True
s.setblocking(False)
for _ in range(64):
    try:
        conn = s.accept()[0]
    except BlockingIOError:
        break
    hear(conn)
print("stopped" if stopped else "gave-up", flush=True)
"#;

/// A socket made for that listener, which is what a run inside the jail cannot make.
#[cfg(target_os = "linux")]
const CALL_AS_SEQPACKET: &str = r#"import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
s.settimeout(5)
s.connect(sys.argv[1])
s.send(b"CONTROL")
"#;

/// How long one of the new tests' own commands may take. Past it the command is ended and the test fails.
const A_COMMAND_MAY_TAKE: Duration = Duration::from_secs(120);

/// Runs a command to its end or to a limit, with nothing on its input. Past the limit it is ended and reaped,
/// and the test fails with what the command had said by then.
fn within(mut command: Command, limit: Duration, what: &str) -> Output {
    use std::sync::{Arc, Mutex};
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap_or_else(|e| panic!("{what} did not start: {e}"));
    // What it says is gathered as it comes, so that a command ended at the limit still shows what it said.
    let gather = |mut from: Box<dyn Read + Send>| {
        let said = Arc::new(Mutex::new(Vec::new()));
        let into = Arc::clone(&said);
        let reader = std::thread::spawn(move || {
            let mut buffer = [0u8; 4096];
            while let Ok(n) = from.read(&mut buffer) {
                if n == 0 {
                    break;
                }
                into.lock().unwrap().extend_from_slice(&buffer[..n]);
            }
        });
        (said, reader)
    };
    let (stdout, out_reader) = gather(Box::new(child.stdout.take().unwrap()));
    let (stderr, err_reader) = gather(Box::new(child.stderr.take().unwrap()));
    let end = Instant::now() + limit;
    let status = loop {
        if let Some(status) = child.try_wait().unwrap() {
            break status;
        }
        if Instant::now() >= end {
            let _ = child.kill();
            let _ = child.wait();
            panic!(
                "{what} did not end within {limit:?}. It had said: {}{}",
                String::from_utf8_lossy(&stdout.lock().unwrap()),
                String::from_utf8_lossy(&stderr.lock().unwrap())
            );
        }
        std::thread::sleep(Duration::from_millis(20));
    };
    // It has ended, so its ends of the pipes are closed and the readers finish.
    out_reader.join().unwrap();
    err_reader.join().unwrap();
    let stdout = stdout.lock().unwrap().clone();
    let stderr = stderr.lock().unwrap().clone();
    Output {
        status,
        stdout,
        stderr,
    }
}

/// As `run_in`, under a limit.
fn run_in_within(jail: &Jail, program: &str, args: &[String], limit: Duration) -> Output {
    let (wrapped, wrapped_args) = jail.command(program, args);
    let mut command = Command::new(wrapped);
    command
        .args(wrapped_args)
        .current_dir(jail.checkout())
        .env_clear()
        .env(
            "PATH",
            "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
        )
        .env("HOME", jail.scratch())
        .env("TMPDIR", jail.scratch());
    within(command, limit, "the jailed command")
}

/// The listener a test started. However the test ends, it is ended and reaped.
#[cfg(target_os = "linux")]
struct Listening {
    child: std::process::Child,
    lines: std::sync::mpsc::Receiver<String>,
}

#[cfg(target_os = "linux")]
impl Listening {
    /// Starts it at `target` and waits, under a limit, for it to say that it listens.
    fn start(target: &Path, hear_only_at_the_end: bool) -> Self {
        use std::io::{BufRead, BufReader};
        let mut command = Command::new("/usr/bin/python3");
        command.args(["-c", LISTEN_AS_SEQPACKET, target.to_str().unwrap()]);
        if hear_only_at_the_end {
            command.arg("hear-only-at-the-end");
        }
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let stdout = child.stdout.take().unwrap();
        let (send, lines) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if send.send(line).is_err() {
                    break;
                }
            }
        });
        let listening = Listening { child, lines };
        assert_eq!(listening.line(), "listening", "the listener did not start");
        listening
    }

    /// The next thing it says, waited for under a limit.
    fn line(&self) -> String {
        self.lines
            .recv_timeout(Duration::from_secs(20))
            .expect("the listener said nothing more within its limit")
    }

    /// Ends its input, and gives everything it said after what was already read, under a limit. It must end
    /// well.
    fn stop(&mut self) -> Vec<String> {
        drop(self.child.stdin.take());
        let end = Instant::now() + Duration::from_secs(20);
        let mut rest = Vec::new();
        loop {
            match self
                .lines
                .recv_timeout(end.saturating_duration_since(Instant::now()))
            {
                Ok(line) => rest.push(line),
                Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
                Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                    panic!("the listener did not stop within its limit; it had said {rest:?}")
                }
            }
        }
        loop {
            if let Some(status) = self.child.try_wait().unwrap() {
                assert!(status.success(), "the listener ended badly: {status}");
                break;
            }
            assert!(Instant::now() < end, "the listener did not end");
            std::thread::sleep(Duration::from_millis(20));
        }
        rest
    }
}

#[cfg(target_os = "linux")]
impl Drop for Listening {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// The control client, under a limit: a socket made for the listener, with no jail.
#[cfg(target_os = "linux")]
fn call_the_listener(target: &Path) {
    let mut command = Command::new("/usr/bin/python3");
    command.args(["-c", CALL_AS_SEQPACKET, target.to_str().unwrap()]);
    let called = within(command, A_COMMAND_MAY_TAKE, "the control client");
    assert!(
        called.status.success(),
        "control failed: {}",
        String::from_utf8_lossy(&called.stderr)
    );
}

/// The filter lets a run make a Unix pair of the seqpacket kind, because a program built with this toolchain
/// makes one before it starts a child. This holds an end of such a pair to its other end. A socket of that
/// kind listens by name inside the checkout, which the jail shows. From inside, the name is seen; a pair is
/// made and works; and nothing a run tries with an end of it reaches the listener: a send that names the
/// listener goes to the other end, joining the listener is refused, unjoining is refused, and the same again
/// once the other end is closed. Whether an end given a name can be reached is the next test's.
///
/// Two controls. A socket made for the listener, outside the jail, reaches it: so the listener was there to
/// be reached. And the same tries with no jail give the same lines but one: there a socket of that kind can
/// be made. So it is the kernel that keeps an end to its other end, and the filter that keeps a run from the
/// socket that would reach the listener.
///
/// What it does not try: handing an open file across the pair, socket options, and type bits the kernel
/// itself refuses. That an end can reach nothing else rests on how the kernel treats this kind of socket, as
/// the spec argues; these tries are there to fail if a kernel behaves otherwise.
#[cfg(target_os = "linux")]
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn on_linux_an_end_of_a_seqpacket_pair_reaches_only_its_other_end() {
    let g = ground();
    let target = g.checkout.join("t.sock");
    let mut listener = Listening::start(&target, false);
    call_the_listener(&target);
    assert_eq!(
        listener.line(),
        "arrived:CONTROL",
        "control failed: a socket made for the listener did not reach it"
    );

    let tries = [
        "-c".to_string(),
        AN_END_OF_A_SEQPACKET_PAIR.to_string(),
        target.to_str().unwrap().to_string(),
    ];
    let lines = |a_socket_of_that_kind: &str| {
        format!(
            "name:socket\nsocket-of-that-kind:{a_socket_of_that_kind}\npair:made\nown-pair:works\n\
             named-send:to-the-other-end\njoin:refused\nunjoin:refused\n\
             named-send-after-unjoin:to-the-other-end\njoin-after-unjoin:refused\n\
             named-send-after-close:refused\njoin-after-close:refused\n"
        )
    };
    let mut free = Command::new("/usr/bin/python3");
    free.args(&tries);
    let free = within(free, A_COMMAND_MAY_TAKE, "the tries with no jail");
    assert_eq!(
        String::from_utf8_lossy(&free.stdout),
        lines("made"),
        "control failed: {}",
        String::from_utf8_lossy(&free.stderr)
    );
    assert!(
        free.status.success(),
        "control failed: {}",
        String::from_utf8_lossy(&free.stderr)
    );
    let out = run_in_within(&jail(&g), "/usr/bin/python3", &tries, A_COMMAND_MAY_TAKE);
    assert_eq!(
        String::from_utf8_lossy(&out.stdout),
        lines("refused"),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );

    // Its input ends. It lets in whatever still waits, and says what else it heard: nothing.
    assert_eq!(
        listener.stop(),
        ["stopped"],
        "something arrived at the listener"
    );
}

/// A caller outside the jail, for an end that a jailed run has named inside its checkout, which is a directory
/// of the machine's own and so is seen from outside. Each time the run says it is ready, this looks at the
/// name, makes a socket of the kind for it, and tries to join; then it says that it has called. If it joins
/// it sends a marker, which the run's own lines would then show as heard. `argv[3]` is how many times it is
/// to call: twice for an end of a pair, before and after its other end is closed, and once for the control.
#[cfg(target_os = "linux")]
const A_CALLER_FROM_OUTSIDE: &str = r#"import errno, os, socket, stat, sys, time
kind = {"stream": socket.SOCK_STREAM, "seqpacket": socket.SOCK_SEQPACKET}[sys.argv[1]]
mine = sys.argv[2]
def say(name, word):
    print(name + ":" + word, flush=True)
for step, name in (("1", "from-outside"), ("2", "from-outside-after-close"))[:int(sys.argv[3])]:
    until = time.monotonic() + 60
    while not os.path.exists(mine + ".ready-" + step):
        if time.monotonic() > until:
            raise TimeoutError("the run inside never said it was ready")
        time.sleep(0.05)
    say(name + "-the-name-is", "a-socket" if stat.S_ISSOCK(os.stat(mine).st_mode) else "not-a-socket")
    caller = socket.socket(socket.AF_UNIX, kind)
    caller.settimeout(2)
    try:
        caller.connect(mine)
    except OSError as e:
        if isinstance(e, TimeoutError) or e.errno != errno.ECONNREFUSED:
            raise
        say(name, "refused")
    else:
        caller.send(b"FROM-OUTSIDE")
        say(name, "joined")
    caller.close()
    open(mine + ".called-" + step, "w").close()
"#;

/// The filter sees a call's number and not the kind of socket it is made on, and a run may listen on its own
/// empty network: so it cannot refuse an end of a pair being told to listen. That such an end, given a name,
/// takes no caller in rests on the kernel, for both kinds of pair the filter lets through, and this tries it
/// on every machine it runs on. What the kernel answers to the telling is not held: it differs from kernel to
/// kernel (6.12 refuses a joined end; 7.0 says yes, and the end is as it was).
///
/// Who could call such an end, if it did listen: not the run itself, which the filter keeps from making a
/// Unix socket, but anything outside the jail that can reach the name, since the checkout and the scratch
/// are directories of the machine's own. A caller let in could hand the run bytes, or an open file. So the
/// end named inside the jail is called from outside it, by a process with no jail, before and after the
/// other end is closed: it sees the name as a socket, and its joining is refused.
///
/// Three controls. A socket of the kind joined to nothing, treated the same way with no jail in the same
/// directory, listens, and takes in both a caller of its own making and the caller from outside: so the
/// lines can tell, and the caller from outside is one that joins where something listens. The same tries on
/// an end of a pair with no jail, where the caller is the process itself. And the caller from outside sees
/// the name the jailed run bound as a socket: so it tried the end, and not a name that was not there. There
/// is no control in which a caller outside reaches a listener inside the jail, since nothing inside can
/// make a Unix socket that listens.
#[cfg(target_os = "linux")]
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn on_linux_a_named_end_of_a_pair_takes_no_caller_in() {
    let g = ground();
    let lines = |a_caller: &str| {
        format!(
            "bind:made\nlisten:does-not-listen\naccept:refused\na-caller:{a_caller}\n\
             heard:nothing\nown-pair:works\nlisten-after-close:does-not-listen\n\
             accept-after-close:refused\na-caller-after-close:{a_caller}\nheard-after-close:nothing\n"
        )
    };
    for kind in ["stream", "seqpacket"] {
        let tries = |own_name: String, which: &str| {
            vec![
                "-c".to_string(),
                A_NAMED_END_OF_A_PAIR.to_string(),
                kind.to_string(),
                g.checkout.join(own_name).to_str().unwrap().to_string(),
                which.to_string(),
            ]
        };
        let outside = |own_name: String, times: &str| {
            let mut outside = Command::new("/usr/bin/python3");
            outside.args([
                "-c",
                A_CALLER_FROM_OUTSIDE,
                kind,
                g.checkout.join(own_name).to_str().unwrap(),
                times,
            ]);
            // Started first: it waits for the helper to say it is ready.
            std::thread::spawn(move || {
                within(outside, A_COMMAND_MAY_TAKE, "the caller from outside")
            })
        };
        let caller = outside(format!("alone-{kind}.sock"), "1");
        let mut alone = Command::new("/usr/bin/python3");
        let mut words = tries(format!("alone-{kind}.sock"), "a-socket-joined-to-nothing");
        words.push("called-from-outside".to_string());
        alone.args(words);
        let alone = within(alone, A_COMMAND_MAY_TAKE, "the control with no jail");
        let caller = caller.join().expect("the caller from outside");
        assert_eq!(
            String::from_utf8_lossy(&alone.stdout),
            "bind:made\nlisten:listens\na-caller:made\naccept:made\n",
            "control failed: a {kind} socket joined to nothing did not listen and take a caller in: {}",
            String::from_utf8_lossy(&alone.stderr)
        );
        assert_eq!(
            String::from_utf8_lossy(&caller.stdout),
            "from-outside-the-name-is:a-socket\nfrom-outside:joined\n",
            "control failed: the caller from outside did not join a {kind} socket that listens: {}",
            String::from_utf8_lossy(&caller.stderr)
        );
        let mut free = Command::new("/usr/bin/python3");
        free.args(tries(format!("free-{kind}.sock"), "an-end-of-a-pair"));
        let free = within(free, A_COMMAND_MAY_TAKE, "the tries with no jail");
        assert_eq!(
            String::from_utf8_lossy(&free.stdout),
            lines("refused"),
            "control failed, a {kind} pair: {}",
            String::from_utf8_lossy(&free.stderr)
        );
        assert!(
            free.status.success(),
            "control failed, a {kind} pair: {}",
            String::from_utf8_lossy(&free.stderr)
        );
        let caller = outside(format!("jailed-{kind}.sock"), "2");
        let mut jailed = tries(format!("jailed-{kind}.sock"), "an-end-of-a-pair");
        jailed.push("called-from-outside".to_string());
        let out = run_in_within(&jail(&g), "/usr/bin/python3", &jailed, A_COMMAND_MAY_TAKE);
        let outside = caller.join().expect("the caller from outside");
        assert_eq!(
            String::from_utf8_lossy(&outside.stdout),
            "from-outside-the-name-is:a-socket\nfrom-outside:refused\n\
             from-outside-after-close-the-name-is:a-socket\nfrom-outside-after-close:refused\n",
            "a {kind} pair, called from outside the jail: {}",
            String::from_utf8_lossy(&outside.stderr)
        );
        assert!(
            outside.status.success(),
            "a {kind} pair, called from outside the jail: {}",
            String::from_utf8_lossy(&outside.stderr)
        );
        assert_eq!(
            String::from_utf8_lossy(&out.stdout),
            lines("none-can-be-made"),
            "a {kind} pair: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        assert!(
            out.status.success(),
            "a {kind} pair: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    }
}

/// The listener's own word that nothing else came is only as good as its letting-in. Here two callers are
/// waiting, unheard, when it is told to stop: it hears both before it says that it has stopped.
#[cfg(target_os = "linux")]
#[test]
fn a_listener_told_to_stop_first_hears_whoever_still_waits() {
    let tmp = tempfile::tempdir().unwrap();
    let target = tmp.path().join("t.sock");
    let mut listener = Listening::start(&target, true);
    call_the_listener(&target);
    call_the_listener(&target);
    assert_eq!(
        listener.stop(),
        ["arrived:CONTROL", "arrived:CONTROL", "stopped"]
    );
}

/// Not a test of the jail by itself. When a file named `start-a-child` is in the directory this is run in, it
/// starts a child by a bare name, found on a path it gives, and says what came of it. The test below runs
/// this same test program inside the jail to do that. A bare name with a path of its own is what makes the
/// standard library start the child the way that first makes a Unix pair of the seqpacket kind. It fails
/// when the child could not be started or ended badly, after saying which.
#[test]
fn started_with_a_file_beside_it_this_starts_a_child_by_a_bare_name() {
    let here = std::env::current_dir().unwrap();
    if !here.join("start-a-child").exists() {
        return;
    }
    match Command::new("yak-jail-child").env("PATH", &here).output() {
        Ok(out) if out.status.success() => {
            println!("\nchild:{}", String::from_utf8_lossy(&out.stdout).trim());
        }
        Ok(out) => {
            println!("\nchild-ended-badly:{}", out.status);
            panic!("the child ended badly");
        }
        Err(e) => {
            println!("\nno-child:{}", e.raw_os_error().unwrap_or(0));
            panic!("the child was not started: {e}");
        }
    }
}

/// A program built with this toolchain starts another inside the jail, and reads what it wrote. On Linux this
/// failed until the filter let a Unix pair of the seqpacket kind through: the program was refused the pair it
/// makes first, with "operation not permitted", and so `cargo` could not build inside the jail. The run with
/// no jail is the control.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_program_of_ours_starts_a_child_inside_the_jail() {
    use std::os::unix::fs::PermissionsExt;
    let g = ground();
    let helper = g.checkout.join("helper");
    fs::copy(std::env::current_exe().unwrap(), &helper).unwrap();
    let child = g.checkout.join("yak-jail-child");
    fs::write(&child, "#!/bin/sh\necho CHILD-MARKER\n").unwrap();
    fs::set_permissions(&child, fs::Permissions::from_mode(0o755)).unwrap();
    fs::write(g.checkout.join("start-a-child"), "").unwrap();
    let args = [
        "--exact",
        "started_with_a_file_beside_it_this_starts_a_child_by_a_bare_name",
        "--nocapture",
        "--test-threads=1",
    ]
    .map(String::from);
    let said = |out: &Output| {
        String::from_utf8_lossy(&out.stdout)
            .lines()
            .filter(|line| line.starts_with("child") || line.starts_with("no-child:"))
            .collect::<Vec<_>>()
            .join(" ")
    };
    let both = |out: &Output| {
        format!(
            "{}{}",
            String::from_utf8_lossy(&out.stdout),
            String::from_utf8_lossy(&out.stderr)
        )
    };
    let mut free = Command::new(&helper);
    free.args(&args).current_dir(&g.checkout);
    let free = within(free, A_COMMAND_MAY_TAKE, "the helper with no jail");
    assert_eq!(
        said(&free),
        "child:CHILD-MARKER",
        "control failed: {}",
        both(&free)
    );
    assert!(free.status.success(), "control failed: {}", both(&free));
    let out = run_in_within(
        &jail(&g),
        helper.to_str().unwrap(),
        &args,
        A_COMMAND_MAY_TAKE,
    );
    assert_eq!(said(&out), "child:CHILD-MARKER", "{}", both(&out));
    assert!(out.status.success(), "{}", both(&out));
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
fn a_jailed_run_cannot_write_to_the_terminal() {
    let g = ground();
    // The shell first says it started, on the output it was given, which is that terminal. Then it tries the
    // terminal by its name. Without the first, a jail whose shell never started would pass: nothing of it reaches
    // the terminal then either.
    let write = [
        "-c".to_string(),
        "echo MARK-started; echo MARK-typed > /dev/tty".to_string(),
    ];
    let free = seen_on_its_terminal(&g, (Path::new("/bin/sh"), &write));
    assert!(
        free.contains("MARK-started") && free.contains("MARK-typed"),
        "control failed: {free:?}"
    );
    let (tool, args) = jail(&g).command("/bin/sh", &write);
    let jailed = seen_on_its_terminal(&g, (&tool, &args));
    assert!(
        jailed.contains("MARK-started"),
        "the jailed shell did not start: {jailed:?}"
    );
    assert!(!jailed.contains("MARK-typed"), "{jailed:?}");
}

/// The jail must not break an honest check: a shell pipeline, git, a scripting language making a temporary
/// file, the random device, the machine's processor count, and the user's name, with the scratch directory as home
/// and as the place for temporary files. Each thing the jail allows beyond reading and writing is used here, so
/// taking one away fails this test.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
fn a_jailed_run_cannot_open_a_terminal_device() {
    let g = ground();
    // Given to the interpreter as an argument. A here-document would need a temporary file, and the jail
    // lets a run write only in its own two directories.
    // A terminal can be closed by whoever owns it between the listing of the names and the try: that one is
    // gone, and nothing of it was opened. So the test asks that at least three were refused, and not only
    // that three names were listed.
    let script = r#"import glob, os, sys
opened = []
refused = 0
paths = ['/dev/tty', '/dev/ptmx'] + sorted(glob.glob('/dev/ttys*'))[:4] + sorted(glob.glob('/dev/pty*'))[:2]
for path in paths:
    try:
        os.close(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY))
        opened.append(path)
    except PermissionError:
        refused += 1
    except FileNotFoundError:
        pass
    except OSError as e:
        opened.append(f'{path}:errno{e.errno}')
print(len(paths), refused, ' '.join(opened))
sys.exit(1 if opened or refused < 3 else 0)
"#;
    let out = run_in(
        &jail(&g),
        "/usr/bin/python3",
        &["-c".to_string(), script.to_string()],
    );
    assert!(
        out.status.success(),
        "paths tried, those refused, then any that opened or failed for another reason: {} {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
}

/// A run can change everything inside its two directories and nothing about the directories themselves. If it
/// could move its checkout away and leave a link in its place, the next run in that sandbox would be jailed
/// around whatever the link names.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
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
# Another process's arguments and environment, asked for by each of the two numbers the kernel has for them.
def environment(number):
    mib = (c.c_int * 3)(1, number, other)
    buf = c.create_string_buffer(262144)
    n = c.c_size_t(len(buf))
    raw = buf.raw[: n.value] if lib.sysctl(mib, 3, buf, c.byref(n), None, 0) == 0 else b""
    return b"YAK_JAIL_CANARY=FAKE_ONLY" in raw
read = [environment(49), environment(38)]
said.append("environment-of-other:" + ("read" if all(read) else "refused" if not any(read) else "read-one-way"))
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
fn the_jail_passes_the_exit_code_through() {
    let g = ground();
    assert_eq!(jailed(&jail(&g), "exit 7").status.code(), Some(7));
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
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
