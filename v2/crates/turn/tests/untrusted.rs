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
    let spec = spec(format!(
        "curl -s -m 3 -o /dev/null http://127.0.0.1:{port}/; true"
    ));
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
    assert!(verdict.exit_code == 0);
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
    let args = common::strings(&["-c", script.to_str().unwrap()]);
    let mut said = Vec::new();
    match sandbox.run_untrusted("sh", &args, "", 30, &mut |line| said.push(line.to_string())) {
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
    let mut child = std::process::Command::new(std::env::current_exe().unwrap());
    child
        .args([
            "--exact",
            "inner_a_run_under_the_rooms_settings",
            "--nocapture",
        ])
        .env("YAK_INNER", script)
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
    let toolchain = home.dir.join(".cargo");
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
    for (named, why) in [
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
