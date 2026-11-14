//! What the room does not trust runs in the jail: a check, a script worker, and the room's own git in a
//! worker's tree. Each test would pass a write or a connection through if the run were not jailed.
//!
//! Like `tests/jail.rs`, these enter a real jail and so cannot run inside another sandbox.

mod common;

use std::fs;
use std::net::TcpListener;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::{Duration, Instant};

use common::Repo;
use room::{CheckOrigin, CheckSpec};
use turn::Sandbox;
use turn::check::{freeze, run_check};
use turn::worker;

fn spec(command: String) -> CheckSpec {
    CheckSpec {
        command,
        files: vec![],
        timeout_secs: 30,
        origin: CheckOrigin::Outside,
        wrong_artifacts: vec![],
        written_by: "person:test".into(),
    }
}

fn quote(path: &Path) -> String {
    format!("'{}'", path.to_str().unwrap())
}

fn reached(listener: &TcpListener) -> bool {
    let end = Instant::now() + Duration::from_millis(400);
    while Instant::now() < end {
        if listener.accept().is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    false
}

/// The check's command tries to write beside the repository, then passes only if the file is not there. So the
/// verdict is a pass exactly when the write was stopped.
#[test]
fn a_check_cannot_write_outside_its_checkout() {
    let repo = Repo::new(&[("a.txt", "one\n")]);
    repo.write("a.txt", "two\n");
    let fix = repo.commit("fix");
    let outside = repo.scratch("outside");
    fs::create_dir(&outside).unwrap();
    let canary = outside.join("made-by-the-check");
    let spec = spec(format!(
        "echo x > {0} 2>/dev/null; test ! -e {0}",
        quote(&canary)
    ));
    let checks = repo.scratch("checks");
    let frozen = freeze(&repo.path, &repo.base, &spec, &checks).unwrap();
    let verdict = run_check(
        &repo.path,
        &fix,
        &spec,
        &frozen.check_hash,
        &checks,
        &repo.scratch("work"),
    )
    .unwrap();
    assert!(!canary.exists(), "the check wrote outside its checkout");
    assert!(verdict.passed, "exit {}", verdict.exit_code);
}

#[test]
fn a_check_has_no_network() {
    let repo = Repo::new(&[("a.txt", "one\n")]);
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let port = listener.local_addr().unwrap().port();
    let fetch = format!("curl -s -m 3 -o /dev/null http://127.0.0.1:{port}/");
    // The control: with no jail the same fetch reaches the listener, so curl is here and the listener works.
    let mut free = std::process::Command::new("/bin/sh")
        .args(["-c", &fetch])
        .spawn()
        .unwrap();
    let control = reached(&listener);
    let _ = free.kill();
    let _ = free.wait();
    assert!(
        control,
        "control failed: an unjailed fetch never reached the listener"
    );
    // The check passes only when curl ran and could not connect (its exit code 7). A curl that is missing, or
    // one that connected, fails the check.
    let spec = spec(format!("{fetch}; test $? -eq 7"));
    let checks = repo.scratch("checks");
    let frozen = freeze(&repo.path, &repo.base, &spec, &checks).unwrap();
    assert!(
        !reached(&listener),
        "freezing the check reached the listener"
    );
    let verdict = run_check(
        &repo.path,
        &repo.base,
        &spec,
        &frozen.check_hash,
        &checks,
        &repo.scratch("work"),
    )
    .unwrap();
    assert_eq!(verdict.exit_code, 0, "curl did not run and fail to connect");
    assert!(!reached(&listener), "the check reached the listener");
}

/// A check may still use temporary files and a home directory: both are its scratch directory.
#[test]
fn a_check_has_a_home_and_a_place_for_temporary_files() {
    let repo = Repo::new(&[("a.txt", "one\n")]);
    let spec = spec(
        "t=$(mktemp) && echo ok > \"$t\" && echo also > \"$HOME/made\" && cat <<END\nhere\nEND"
            .into(),
    );
    let checks = repo.scratch("checks");
    let frozen = freeze(&repo.path, &repo.base, &spec, &checks).unwrap();
    let verdict = run_check(
        &repo.path,
        &repo.base,
        &spec,
        &frozen.check_hash,
        &checks,
        &repo.scratch("work"),
    )
    .unwrap();
    assert!(verdict.passed, "exit {}", verdict.exit_code);
}

/// A script worker is a stand-in for a worker's own code, so it is jailed too. It makes its own commit, as a
/// script worker does, which also shows git works inside the jail.
#[test]
fn a_script_worker_cannot_write_outside_its_sandbox_and_its_commit_still_lands() {
    let repo = Repo::new(&[("a.txt", "one\n")]);
    let outside = repo.scratch("outside");
    fs::create_dir(&outside).unwrap();
    let canary = outside.join("made-by-the-worker");
    let script = outside.join("worker.sh");
    fs::write(
        &script,
        format!(
            "#!/bin/sh\necho x > {} 2>/dev/null\necho two > a.txt\n\
                 git add -A && git -c user.name=t -c user.email=t@example.invalid commit -q -m two\n",
            quote(&canary)
        ),
    )
    .unwrap();
    fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();

    let sandbox =
        Sandbox::create(&repo.path, &repo.base, &repo.scratch("turn"), "room/i1/1").unwrap();
    let before = sandbox.head().unwrap();
    let run = worker::from_name(&format!("script:{}", script.display()))
        .unwrap()
        .run(&sandbox, "an item", "true", 30)
        .unwrap();
    assert_eq!(run.exit_code, 0);
    assert!(!canary.exists(), "the worker wrote outside its sandbox");
    assert_ne!(
        sandbox.head().unwrap(),
        before,
        "the worker's change was not committed"
    );
    sandbox.destroy().unwrap();
    assert!(
        !repo.scratch("turn.scratch").exists(),
        "the scratch directory was left behind"
    );
}

/// A tripwire, not a behaviour test. After `reclaim`, nothing known makes the room's git run a worker's code,
/// so no test can show the jail stopping it. This reads the source and fails if the room's git in a worker's
/// tree stops going through the jail.
#[test]
fn the_rooms_git_in_a_workers_tree_goes_through_the_jail() {
    let source = include_str!("../src/worker.rs");
    let seal = source
        .split("fn seal(")
        .nth(1)
        .expect("worker.rs has a seal function");
    let body = seal.split("\nfn ").next().unwrap();
    assert!(body.contains("sandbox.run_untrusted("));
    assert!(!body.contains("sandbox.run("));
}

/// The inner half of the two tests below, and nothing by itself. What the room's jail shows and hides is
/// read from the environment, and a test cannot change its own. So the outer half runs this test again in a
/// child whose environment it chose, and reads what the child prints.
#[test]
fn inner_a_run_under_the_rooms_settings() {
    let Some(script) = std::env::var_os("YAK_INNER") else {
        return;
    };
    let repo = Repo::new(&[("a.txt", "one\n")]);
    let sandbox =
        Sandbox::create(&repo.path, &repo.base, &repo.scratch("turn"), "room/i1/1").unwrap();
    // `YAK_INNER` is a script for `sh`, or with `YAK_INNER_PROGRAM` set it is the path of a program to run.
    let script = script.to_str().unwrap();
    let (program, args) = match std::env::var_os("YAK_INNER_PROGRAM") {
        Some(_) => (script, Vec::new()),
        None => ("sh", common::strings(&["-c", script])),
    };
    // With `YAK_INNER_PLANT` set, the checkout holds a program named `sh` that leaves a mark at that path and
    // then runs the real shell: what a worker would commit to be run in place of the room's own.
    if let Some(mark) = std::env::var_os("YAK_INNER_PLANT") {
        let shim = sandbox.dir.join("sh");
        let body = format!(
            "#!/bin/sh\n/usr/bin/touch '{}'\nexec /bin/sh \"$@\"\n",
            mark.to_str().unwrap()
        );
        fs::write(&shim, body).unwrap();
        fs::set_permissions(&shim, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let mut said = Vec::new();
    let mut on_line = |line: &str| said.push(line.to_string());
    // With `YAK_INNER_PLAIN` set the run is the plain one, as a model worker's is.
    let ran = match std::env::var_os("YAK_INNER_PLAIN") {
        Some(_) => sandbox.run(program, &args, "", 30, &mut on_line),
        None => sandbox.run_untrusted(program, &args, "", 30, &mut on_line),
    };
    match ran {
        Ok(status) => {
            for line in said {
                println!("SAID {line}");
            }
            println!("ENDED {}", status.exit_code);
        }
        Err(e) => println!("REFUSED {e}"),
    }
}

/// Runs the inner half with `script` and these variables set, and returns what it printed.
fn under(script: &str, variables: &[(&str, &Path)], jail: bool) -> String {
    under_without(script, variables, &[], jail)
}

/// `under`, with these variables taken out of the child's environment as well.
fn under_without(
    script: &str,
    variables: &[(&str, &Path)],
    without: &[&str],
    jail: bool,
) -> String {
    let mut child = std::process::Command::new(std::env::current_exe().unwrap());
    child
        .args([
            "--exact",
            "inner_a_run_under_the_rooms_settings",
            "--nocapture",
        ])
        .env("YAK_INNER", script)
        .env_remove("YAK_INNER_PROGRAM")
        .env_remove("YAK_INNER_PLANT")
        .env_remove("YAK_INNER_PLAIN")
        .env_remove("YAK_JAIL")
        .env_remove("YAK_JAIL_READ")
        .env_remove("CLAUDE_CONFIG_DIR")
        .env_remove("CODEX_HOME");
    if !jail {
        child.env("YAK_JAIL", "off");
    }
    for (name, value) in variables {
        child.env(name, value);
    }
    for name in without {
        child.env_remove(name);
    }
    let out = child.output().unwrap();
    let printed = String::from_utf8_lossy(&out.stdout).into_owned();
    assert!(
        printed.contains("ENDED ") || printed.contains("REFUSED "),
        "the inner run did not report: {printed} {}",
        String::from_utf8_lossy(&out.stderr)
    );
    printed
}

/// A home with a toolchain in it, as `~/.cargo` is: a tool, and a file of credentials beside it.
struct Home {
    _tmp: tempfile::TempDir,
    dir: std::path::PathBuf,
}

fn home() -> Home {
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().canonicalize().unwrap().join("home");
    for sub in [".cargo/bin", ".cargo/agent", ".ssh", "codex"] {
        fs::create_dir_all(dir.join(sub)).unwrap();
    }
    let tool = dir.join(".cargo/bin/tool.sh");
    fs::write(&tool, "#!/bin/sh\necho TOOL-RAN\n").unwrap();
    fs::set_permissions(&tool, fs::Permissions::from_mode(0o755)).unwrap();
    for secret in [
        ".cargo/credentials.toml",
        ".cargo/agent/sign-in",
        ".netrc",
        ".ssh/id",
        "codex/auth.json",
    ] {
        fs::write(dir.join(secret), format!("CANARY {secret}\n")).unwrap();
    }
    Home { _tmp: tmp, dir }
}

#[test]
fn a_run_is_shown_the_tools_named_for_it_and_none_of_the_homes_secrets() {
    let home = home();
    let at = |name: &str| quote(&home.dir.join(name));
    let script = format!(
        "echo \"claude=[${{CLAUDE_CONFIG_DIR-unset}}] codex=[${{CODEX_HOME-unset}}]\"\n\
         {tool}\n\
         cat {a} {b} {c} {d} {e}\n\
         ls -a {home}\n\
         echo finished",
        tool = at(".cargo/bin/tool.sh"),
        a = at(".cargo/credentials.toml"),
        b = at(".cargo/agent/sign-in"),
        c = at(".netrc"),
        d = at(".ssh/id"),
        e = at("codex/auth.json"),
        home = quote(&home.dir),
    );
    // The tool's own directory is named, and not the one above it that also holds the credentials.
    let toolchain = home.dir.join(".cargo/bin");
    let agent = home.dir.join(".cargo/agent");
    let codex = home.dir.join("codex");
    let variables: [(&str, &Path); 4] = [
        ("HOME", &home.dir),
        ("YAK_JAIL_READ", &toolchain),
        ("CLAUDE_CONFIG_DIR", &agent),
        ("CODEX_HOME", &codex),
    ];

    // A line of the listing of the home, which names the script itself never prints alone.
    let listed = |printed: &str| printed.lines().any(|line| line == "SAID .netrc");

    // The control: with the jail off, the same script reads all five, lists the home and sees both variables.
    let free = under(&script, &variables, false);
    assert_eq!(free.matches("SAID CANARY ").count(), 5, "{free}");
    assert!(listed(&free), "{free}");
    assert!(
        free.contains(&format!("claude=[{}]", agent.display())),
        "{free}"
    );

    let jailed = under(&script, &variables, true);
    assert!(
        jailed.contains("SAID TOOL-RAN"),
        "the named tool did not run: {jailed}"
    );
    assert!(jailed.contains("SAID finished"), "{jailed}");
    assert!(!jailed.contains("CANARY"), "a secret was read: {jailed}");
    assert!(!listed(&jailed), "the home was listed: {jailed}");
    assert!(
        jailed.contains("SAID claude=[unset] codex=[unset]"),
        "an agent's settings directory was passed on: {jailed}"
    );
}

#[test]
fn a_named_path_that_is_wrong_or_would_show_the_home_is_refused() {
    let home = home();
    let above = home.dir.parent().unwrap().to_path_buf();
    let missing = home.dir.join("no-such-tools");
    let keys = home.dir.join(".ssh");
    let key = home.dir.join(".ssh/id");
    // A directory that holds a secret, and one that only could: nothing is at `.local/share` in this home, and
    // the jail is given the directory above it as it is at this moment, not as it will be.
    let holds_one = home.dir.join(".cargo");
    let could_hold_one = home.dir.join(".local");
    fs::create_dir(&could_hold_one).unwrap();
    for (named, why) in [
        (keys.as_path(), "is hidden"),
        (key.as_path(), "is hidden"),
        (holds_one.as_path(), "would also show"),
        (could_hold_one.as_path(), "would also show"),
        (home.dir.as_path(), "holds the home directory"),
        (above.as_path(), "holds the home directory"),
        (Path::new("tools/bin"), "not an absolute path"),
        (missing.as_path(), "not there"),
    ] {
        let printed = under(
            "echo ran",
            &[("HOME", &home.dir), ("YAK_JAIL_READ", named)],
            true,
        );
        assert!(
            printed.contains("REFUSED ") && printed.contains(why),
            "{}: {printed}",
            named.display()
        );
        assert!(!printed.contains("SAID ran"), "{printed}");
    }
    // Set and empty names nothing, and the run goes ahead.
    let printed = under(
        "echo ran",
        &[("HOME", &home.dir), ("YAK_JAIL_READ", Path::new(""))],
        true,
    );
    assert!(printed.contains("SAID ran"), "{printed}");
}

/// A worker's program kept where keys are kept would be named for its run and still be hidden from it. The
/// room says so, and does not start a run that can only fail to find its own program.
#[test]
fn a_program_kept_in_a_hidden_place_is_refused_by_name() {
    let home = home();
    let tool = home.dir.join(".ssh/tool.sh");
    fs::write(&tool, "#!/bin/sh\necho TOOL-RAN\n").unwrap();
    fs::set_permissions(&tool, fs::Permissions::from_mode(0o755)).unwrap();
    let settings: [(&str, &Path); 2] = [("HOME", &home.dir), ("YAK_INNER_PROGRAM", Path::new("1"))];

    // The control: with the jail off it runs, so the refusal below is the jail's rule and not a broken program.
    let free = under(tool.to_str().unwrap(), &settings, false);
    assert!(free.contains("SAID TOOL-RAN"), "{free}");

    let printed = under(tool.to_str().unwrap(), &settings, true);
    assert!(
        printed.contains("REFUSED ") && printed.contains("is hidden from every run"),
        "{printed}"
    );
    assert!(!printed.contains("TOOL-RAN"), "{printed}");
}

/// The jail keeps a home out by knowing where it is. With no usable `HOME` it would hide nothing and refuse
/// nothing, so it does not start. The same goes for an agent's settings directory that is named but cannot
/// be placed.
#[test]
fn a_jail_with_no_usable_home_does_not_start() {
    let home = home();
    let file = home.dir.join(".netrc");
    let missing = home.dir.join("no-such-home");
    for wrong in [
        Path::new("relative/home"),
        file.as_path(),
        missing.as_path(),
    ] {
        let printed = under("echo ran", &[("HOME", wrong)], true);
        assert!(
            printed.contains("REFUSED ") && printed.contains("HOME"),
            "{}: {printed}",
            wrong.display()
        );
        assert!(!printed.contains("SAID ran"), "{printed}");
    }
    let printed = under_without("echo ran", &[], &["HOME"], true);
    assert!(
        printed.contains("REFUSED ") && printed.contains("HOME"),
        "unset: {printed}"
    );
    for agent in ["CLAUDE_CONFIG_DIR", "CODEX_HOME"] {
        let printed = under(
            "echo ran",
            &[("HOME", &home.dir), (agent, Path::new("relative/settings"))],
            true,
        );
        assert!(
            printed.contains("REFUSED ") && printed.contains(agent),
            "{agent}: {printed}"
        );
    }
    // The control: with a home that is one, the same run goes ahead.
    let printed = under("echo ran", &[("HOME", &home.dir)], true);
    assert!(printed.contains("SAID ran"), "{printed}");
}

/// The room starts a run through a shell of its own, before the jail is entered, in the worker's checkout, and
/// a plain run (a model worker's) starts its program by name from there too. A search path with a relative
/// entry would find a program the worker committed to the checkout, and run it in place of the room's shell or
/// of the worker's own program, outside any jail.
#[test]
fn a_program_in_the_checkout_is_never_run_in_place_of_the_one_named() {
    let home = home();
    let mark = home.dir.join("the-shim-ran");
    for path in [
        ".:/usr/bin:/bin",
        ":/usr/bin:/bin",
        "/usr/bin::/bin",
        "bin:/usr/bin:/bin",
    ] {
        for plain in [false, true] {
            let mut settings: Vec<(&str, &Path)> = vec![
                ("HOME", &home.dir),
                ("PATH", Path::new(path)),
                ("YAK_INNER_PLANT", &mark),
            ];
            if plain {
                settings.push(("YAK_INNER_PLAIN", Path::new("1")));
            }
            let printed = under("echo ran", &settings, true);
            assert!(printed.contains("SAID ran"), "{path}: {printed}");
            assert!(
                !mark.exists(),
                "PATH={path}, plain run {plain}: the checkout's own sh ran outside the jail"
            );
        }
    }
}

/// A named directory that is a link is the directory it leads to. The home's `.cargo` may be a link to
/// somewhere else, and a credentials file made there later is the same file `~/.cargo/credentials.toml` names.
/// So the jail refuses the link as it would the directory, and refuses its target named directly as well.
#[test]
fn a_named_link_to_a_directory_that_could_hold_a_secret_is_refused() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().canonicalize().unwrap();
    let home = root.join("home");
    let elsewhere = root.join("tools-cargo");
    fs::create_dir_all(&home).unwrap();
    fs::create_dir_all(elsewhere.join("bin")).unwrap();
    std::os::unix::fs::symlink(&elsewhere, home.join(".cargo")).unwrap();
    for named in [home.join(".cargo"), elsewhere.clone()] {
        let printed = under(
            "echo ran",
            &[("HOME", &home), ("YAK_JAIL_READ", &named)],
            true,
        );
        assert!(
            printed.contains("REFUSED ") && printed.contains("would also show"),
            "{}: {printed}",
            named.display()
        );
    }
    // The tool's own directory inside it can be named, by either road.
    for named in [home.join(".cargo/bin"), elsewhere.join("bin")] {
        let printed = under(
            "echo ran",
            &[("HOME", &home), ("YAK_JAIL_READ", &named)],
            true,
        );
        assert!(
            printed.contains("SAID ran"),
            "{}: {printed}",
            named.display()
        );
    }
    // A link further in. `~/.local` is a directory, and `share` inside it is a link to somewhere else: the name
    // `~/.local/share` is still a name inside `~/.local`, and what is put there once the link is gone would be
    // shown.
    let further = root.join("share-elsewhere");
    fs::create_dir_all(&further).unwrap();
    fs::create_dir_all(home.join(".local")).unwrap();
    std::os::unix::fs::symlink(&further, home.join(".local/share")).unwrap();
    let named = home.join(".local");
    let printed = under(
        "echo ran",
        &[("HOME", &home), ("YAK_JAIL_READ", &named)],
        true,
    );
    assert!(
        printed.contains("REFUSED ") && printed.contains("would also show"),
        "a link further in: {printed}"
    );
}

/// Two links in a row. `~/.local` leads to one place, and `share` in that place leads to a third. Neither the
/// name as written nor the place both links lead to is inside the first place; the name with only the first
/// link followed is. Naming the first place is refused, by either road.
#[test]
fn a_secrets_place_is_known_through_each_link_on_the_way_to_it() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().canonicalize().unwrap();
    let (home, first, third) = (
        root.join("home"),
        root.join("local-elsewhere"),
        root.join("share-elsewhere"),
    );
    for dir in [&home, &first, &third] {
        fs::create_dir_all(dir).unwrap();
    }
    fs::create_dir_all(first.join("bin")).unwrap();
    std::os::unix::fs::symlink(&first, home.join(".local")).unwrap();
    std::os::unix::fs::symlink(&third, first.join("share")).unwrap();
    for named in [home.join(".local"), first.clone()] {
        let printed = under(
            "echo ran",
            &[("HOME", &home), ("YAK_JAIL_READ", &named)],
            true,
        );
        assert!(
            printed.contains("REFUSED ") && printed.contains("would also show"),
            "{}: {printed}",
            named.display()
        );
    }
    // The control: a directory beside the link can be named.
    let named = first.join("bin");
    let printed = under(
        "echo ran",
        &[("HOME", &home), ("YAK_JAIL_READ", &named)],
        true,
    );
    assert!(printed.contains("SAID ran"), "{printed}");
}

/// A link to somewhere that is not there yet. `~/.cargo` leads to a directory that does not exist, inside one
/// that does. A credentials file made later, once that directory is, would lie inside the one that does: so
/// naming that one is refused. A link is followed by what it says, whether or not anything is there.
#[test]
fn a_secrets_place_is_known_through_a_link_to_somewhere_not_there_yet() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().canonicalize().unwrap();
    let (home, grant) = (root.join("home"), root.join("grant"));
    fs::create_dir_all(&home).unwrap();
    fs::create_dir_all(grant.join("bin")).unwrap();
    std::os::unix::fs::symlink(grant.join("future-cargo"), home.join(".cargo")).unwrap();
    let printed = under(
        "echo ran",
        &[("HOME", &home), ("YAK_JAIL_READ", &grant)],
        true,
    );
    assert!(
        printed.contains("REFUSED ") && printed.contains("would also show"),
        "{printed}"
    );
    // The control: a directory beside where the link leads can be named.
    let named = grant.join("bin");
    let printed = under(
        "echo ran",
        &[("HOME", &home), ("YAK_JAIL_READ", &named)],
        true,
    );
    assert!(printed.contains("SAID ran"), "{printed}");

    // And a protected name behind links that lead round in a ring cannot be placed at all: no jail starts
    // beside it, whatever is named.
    let lost = root.join("lost-home");
    fs::create_dir_all(&lost).unwrap();
    std::os::unix::fs::symlink(lost.join(".ssh-b"), lost.join(".ssh")).unwrap();
    std::os::unix::fs::symlink(lost.join(".ssh"), lost.join(".ssh-b")).unwrap();
    let printed = under("echo ran", &[("HOME", &lost)], true);
    assert!(
        printed.contains("REFUSED ") && printed.contains("links"),
        "{printed}"
    );
}

/// The rule for a named directory holds for the directories every run is shown without their being named. A
/// place where an agent's settings would be kept, which is not there yet and would lie in one of those, would
/// be shown the day it is made: no jail starts beside it. One that is there is hidden where it is, with
/// whatever is put in it later, and the jail starts.
#[test]
fn a_secrets_place_in_a_directory_every_run_is_shown_stops_the_jail_unless_it_is_hidden() {
    let tmp = tempfile::tempdir().unwrap();
    let home = tmp.path().canonicalize().unwrap();
    // Nothing is made at this path, by this test or by the jail.
    let would_be = Path::new("/usr/share/yak-test-a-place-that-is-never-made/codex");
    assert!(!would_be.exists() && !would_be.parent().unwrap().exists());
    let printed = under(
        "echo ran",
        &[("HOME", &home), ("CODEX_HOME", would_be)],
        true,
    );
    assert!(
        printed.contains("REFUSED ") && printed.contains("every run is shown"),
        "{printed}"
    );
    // The control: the same name somewhere no run is shown.
    let elsewhere = home.join("not-made-either/codex");
    let printed = under(
        "echo ran",
        &[("HOME", &home), ("CODEX_HOME", &elsewhere)],
        true,
    );
    assert!(printed.contains("SAID ran"), "{printed}");
    // And one that is there, in a directory every run is shown: it is hidden, and the run goes on without it.
    // Hidden is seen by what is in it: on Linux the run finds an empty directory in its place, on macOS it is
    // refused the directory itself.
    let there = Path::new("/usr/share/man");
    if there.join("man1").is_dir() {
        let script = "echo ran; ls /usr/share/man/man1 >/dev/null 2>&1 && echo SEEN || echo UNSEEN";
        let printed = under(script, &[("HOME", &home), ("CODEX_HOME", there)], true);
        assert!(printed.contains("SAID ran"), "{printed}");
        assert!(printed.contains("UNSEEN"), "{printed}");
        // The control: with nothing hiding it, the same run sees it.
        let printed = under(script, &[("HOME", &home)], true);
        assert!(printed.contains("SAID SEEN"), "{printed}");
    }
}

/// On a disk where capital and small letters name the same file, a directory kept as `.Cargo` is where
/// `~/.cargo/credentials.toml` would be made. Naming it to the jail is refused like `~/.cargo` itself. On a
/// disk that tells the two apart they are two names, and `.Cargo` is an ordinary directory.
#[test]
fn a_secrets_place_is_known_whatever_letters_its_name_is_kept_in() {
    let tmp = tempfile::tempdir().unwrap();
    let home = tmp.path().canonicalize().unwrap();
    let kept = home.join(".Cargo");
    fs::create_dir_all(kept.join("bin")).unwrap();
    let folds = home.join(".cargo").is_dir();
    let printed = under(
        "echo ran",
        &[("HOME", &home), ("YAK_JAIL_READ", &kept)],
        true,
    );
    if folds {
        assert!(
            printed.contains("REFUSED ") && printed.contains("would also show"),
            "{printed}"
        );
        // Written in small letters, it is the same directory and the same answer.
        let written = home.join(".cargo");
        let printed = under(
            "echo ran",
            &[("HOME", &home), ("YAK_JAIL_READ", &written)],
            true,
        );
        assert!(
            printed.contains("REFUSED ") && printed.contains("would also show"),
            "{printed}"
        );
    } else {
        assert!(printed.contains("SAID ran"), "{printed}");
    }
    // The control, on either kind of disk: the tool's own directory inside it can be named.
    let named = kept.join("bin");
    let printed = under(
        "echo ran",
        &[("HOME", &home), ("YAK_JAIL_READ", &named)],
        true,
    );
    assert!(printed.contains("SAID ran"), "{printed}");
}
