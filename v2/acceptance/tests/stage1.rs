//! Stage 1's acceptance suite (plan task 0), black-box against the `yak` binary of task 10 and the `script:<path>`
//! worker of task 8. Every test fails until the builders finish. Builders do not edit this crate.
//!
//! Build `yak` before running this crate alone: `cargo build -p yak && cargo test -p acceptance`. `cargo test
//! --workspace` builds it first.
//!
//! What a test reads back is only what the plan fixes: exit codes, `RoomError`'s messages on stderr, the item states
//! of `types.rs` in `yak item show ID --json` (field `state`), `yak status --json` (task 5's `Status`), and the one ref
//! the clock fetches per turn, `refs/heads/room/<item>/<lease_no>` (task 9).

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output, Stdio};
use std::thread::sleep;
use std::time::{Duration, Instant};

use acceptance::{Fixture, build, fixing_worker, git, green, refs, worker};
use tempfile::TempDir;

const MARKER: &str = "MARKER-9f3a-0c41";

struct Room {
    _dir: TempDir,
    room: PathBuf,
    scratch: PathBuf,
    fx: Fixture,
}

/// The `yak` binary that `cargo test --workspace` built: another package's, which CARGO_BIN_EXE_ doesn't name. It's
/// in an ancestor of this test's own binary (target/<profile>/, whether the test sits in deps/ or, since Cargo's
/// build-dir change, in build/<crate>/<hash>/out/), else in the workspace's own target/. YAK_BIN overrides both.
fn yak_bin() -> PathBuf {
    let name = format!("yak{}", std::env::consts::EXE_SUFFIX);
    if let Some(path) = std::env::var_os("YAK_BIN") {
        return PathBuf::from(path);
    }
    let me = std::env::current_exe().expect("this test's path");
    let workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("target");
    let found = me
        .ancestors()
        .skip(1)
        .map(|dir| dir.join(&name))
        .chain(["debug", "release"].map(|profile| workspace.join(profile).join(&name)))
        .find(|path| path.is_file());
    found.unwrap_or_else(|| {
        panic!(
            "no {name} beside {}: run `cargo build -p yak` first",
            me.display()
        )
    })
}

/// `yak ARGS --room ROOM`, with stdin closed: nothing in stage 1 may wait on a keystroke.
fn yak(room: &Path, args: &[&str]) -> Output {
    Command::new(yak_bin())
        .args(args)
        .arg("--room")
        .arg(room)
        .stdin(Stdio::null())
        .output()
        .expect("yak runs")
}

fn ok(out: &Output) -> String {
    assert!(
        out.status.success(),
        "yak failed: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8_lossy(&out.stdout).trim().to_string()
}

fn refused(out: &Output) -> String {
    assert!(
        !out.status.success(),
        "yak should have refused, and printed: {}",
        String::from_utf8_lossy(&out.stdout)
    );
    let err = String::from_utf8_lossy(&out.stderr).trim().to_string();
    assert_eq!(
        err.lines().count(),
        1,
        "a refusal is one line on stderr: {err:?}"
    );
    err
}

fn setup() -> Room {
    let dir = TempDir::new().expect("a temporary directory");
    let fx = build(dir.path());
    let room = dir.path().join("room");
    let scratch = dir.path().join("scratch");
    fs::create_dir_all(&scratch).expect("make scratch");
    ok(&yak(&room, &["init"]));
    Room {
        _dir: dir,
        room,
        scratch,
        fx,
    }
}

/// Adds item `n` with its own check, its wrong commit, and the given origin and author. Returns the printed id.
fn add(r: &Room, n: usize, origin: &str, by: &str) -> String {
    add_with_check(r, n, &r.fx.items[n].check_command, origin, by)
}

fn add_with_check(r: &Room, n: usize, check: &str, origin: &str, by: &str) -> String {
    let item = &r.fx.items[n];
    let repo = r.fx.repo.to_str().expect("a UTF-8 path");
    let id = ok(&yak(
        &r.room,
        &[
            "item",
            "add",
            "--title",
            &item.title,
            "--repo",
            repo,
            "--base",
            &r.fx.base_commit,
            "--check",
            check,
            "--file",
            &item.check_file,
            "--wrong",
            &item.wrong_commit,
            "--origin",
            origin,
            "--by",
            by,
        ],
    ));
    assert!(
        id.len() == 13 && id.starts_with('i') && id[1..].chars().all(|c| c.is_ascii_hexdigit()),
        "an item id: {id:?}"
    );
    id
}

/// The string value of `key` in a flat JSON object, by hand, so this crate needs no JSON parser.
fn json_str(text: &str, key: &str) -> Option<String> {
    let at = text.find(&format!("\"{key}\""))? + key.len() + 2;
    let rest = text[at..]
        .trim_start()
        .strip_prefix(':')?
        .trim_start()
        .strip_prefix('"')?;
    Some(rest[..rest.find('"')?].to_string())
}

fn json_num(text: &str, key: &str) -> Option<i64> {
    let at = text.find(&format!("\"{key}\""))? + key.len() + 2;
    let rest = text[at..].trim_start().strip_prefix(':')?.trim_start();
    let end = rest
        .find(|c: char| !c.is_ascii_digit() && c != '-')
        .unwrap_or(rest.len());
    rest[..end].parse().ok()
}

/// The item's `attempts` in `yak item show ID --json` (task 10).
fn attempts(r: &Room, id: &str) -> Option<i64> {
    json_num(&ok(&yak(&r.room, &["item", "show", id, "--json"])), "attempts")
}

fn state(r: &Room, id: &str) -> String {
    let shown = ok(&yak(&r.room, &["item", "show", id, "--json"]));
    json_str(&shown, "state").unwrap_or_else(|| panic!("no state in {shown}"))
}

/// `yak clock run --once-through` with these workers and short limits, stdin closed, to its end. A limit `extra`
/// names is given once, as `extra` says (Serenity's run of 858c9ada: the helper's and the test's were both passed).
fn once_through(r: &Room, workers: &[&str], extra: &[&str]) -> Output {
    let mut args = vec!["clock", "run", "--once-through"];
    for w in workers {
        args.extend(["--worker", *w]);
    }
    for (flag, value) in [("--lease-secs", "30"), ("--turn-secs", "60")] {
        if !extra.contains(&flag) {
            args.extend([flag, value]);
        }
    }
    args.extend(extra);
    yak(&r.room, &args)
}

/// A clock running in the background, in its own process group, killed with its workers when dropped.
struct Clock(Child);

impl Clock {
    fn start(r: &Room, workers: &[&str], extra: &[&str]) -> Clock {
        use std::os::unix::process::CommandExt;
        let mut cmd = Command::new(yak_bin());
        cmd.args(["clock", "run"]);
        for w in workers {
            cmd.args(["--worker", *w]);
        }
        cmd.args(extra)
            .arg("--room")
            .arg(&r.room)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        cmd.process_group(0);
        Clock(cmd.spawn().expect("the clock starts"))
    }

    /// The clock's whole group, then the clock itself, so a group kill that missed can't leave `wait` hanging.
    fn kill_group(&mut self) {
        kill_groups(&[self.0.id().to_string()]);
        let _ = self.0.kill();
        let _ = self.0.wait();
    }

    fn exited_within(&mut self, limit: Duration) -> bool {
        let deadline = Instant::now() + limit;
        while Instant::now() < deadline {
            if self.0.try_wait().expect("wait").is_some() {
                return true;
            }
            sleep(Duration::from_millis(100));
        }
        false
    }
}

impl Drop for Clock {
    fn drop(&mut self) {
        self.kill_group();
    }
}

fn wait_for(what: &str, limit: Duration, mut done: impl FnMut() -> bool) {
    let deadline = Instant::now() + limit;
    while !done() {
        assert!(Instant::now() < deadline, "timed out waiting for {what}");
        sleep(Duration::from_millis(200));
    }
}

/// Whether any process of a process group is left. `--` before the negative id: procps-ng's `kill -0 -GROUP` (the
/// Pi's 4.0.2) answers 0 whatever is left (Serenity, 7c3ddd1d).
fn group_alive(group: &str) -> bool {
    Command::new("kill")
        .args(["-0", "--", &format!("-{group}")])
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

// --- The sixteen tests of plan task 0 (e01c0c74) ---

#[test]
fn five_items_pass_with_no_keystrokes() {
    let r = setup();
    let ids: Vec<String> = (0..5)
        .map(|n| add(&r, n, "outside", "person:fixture"))
        .collect();
    let fix = fixing_worker(&r.scratch);
    ok(&once_through(&r, &[&fix], &[]));
    for id in &ids {
        assert_eq!(state(&r, id), "passed_verified", "{id}");
    }
}

#[test]
fn unchanged_tree_does_not_pass() {
    let r = setup();
    let id = add(&r, 0, "outside", "person:fixture");
    let idle = worker(&r.scratch, "idle", "exit 0");
    let _ = once_through(&r, &[&idle], &[]);
    assert_eq!(
        state(&r, &id),
        "abandoned",
        "never passed: failed each of MAX_ATTEMPTS turns"
    );
    assert_eq!(attempts(&r, &id), Some(3), "MAX_ATTEMPTS turns");
}

#[test]
fn a_wrong_artifact_fails() {
    let r = setup();
    let id = add(&r, 0, "outside", "person:fixture");
    let wrong = worker(
        &r.scratch,
        "wrong",
        &format!(
            "echo {}-not > items/item0.txt\ncommit 'the wrong artifact'",
            green(0)
        ),
    );
    let _ = once_through(&r, &[&wrong], &[]);
    assert_eq!(
        state(&r, &id),
        "abandoned",
        "never passed: failed each of MAX_ATTEMPTS turns"
    );
    assert_eq!(attempts(&r, &id), Some(3), "MAX_ATTEMPTS turns");
}

#[test]
fn a_weak_check_never_opens() {
    let r = setup();
    let id = add_with_check(&r, 0, "true", "outside", "person:fixture"); // passes on the base commit
    let fix = fixing_worker(&r.scratch);
    let _ = once_through(&r, &[&fix], &[]);
    assert_eq!(state(&r, &id), "draft");
    let listed = ok(&yak(&r.room, &["disagreements", "--json"]));
    assert!(
        listed.contains("weak_check") && listed.contains(&id),
        "a WeakCheck disagreement for {id}: {listed}"
    );
}

#[test]
fn a_model_written_check_is_unverified() {
    let r = setup();
    let id = add(&r, 0, "model", "claude:fixture");
    let fix = fixing_worker(&r.scratch);
    ok(&once_through(&r, &[&fix], &[]));
    assert_eq!(state(&r, &id), "passed_unverified");
}

#[test]
fn the_check_author_cannot_take_the_item() {
    // By family (spec rule 3, plan e01c0c74): a check written by script:a is never leased to a script: worker.
    let r = setup();
    let fix = fixing_worker(&r.scratch);
    let id = add(&r, 0, "outside", "script:a");
    let _ = once_through(&r, &[&fix], &[]);
    assert_eq!(
        state(&r, &id),
        "open",
        "never leased to its own check's author"
    );
    assert!(
        !refs(&r.fx.repo)
            .iter()
            .any(|line| line.contains(&format!("refs/heads/room/{id}/"))),
        "no turn ran"
    );
}

/// Every entry in `<room>/turns/`, so a test sees each turn the clock starts.
fn turn_entries(r: &Room) -> Vec<PathBuf> {
    let Ok(entries) = fs::read_dir(r.room.join("turns")) else {
        return Vec::new();
    };
    entries
        .filter_map(|entry| entry.ok().map(|e| e.path()))
        .collect()
}

/// The worker's process group, the first line of each `<room>/turns/<attempt>.pid` while a turn runs (plan
/// a028145e; the second line is the leader's start time). A script's own `$$` is no host pid inside the jail.
fn worker_groups(r: &Room) -> Vec<String> {
    turn_entries(r)
        .into_iter()
        .filter(|path| path.extension().is_some_and(|e| e == "pid"))
        .filter_map(|path| fs::read_to_string(path).ok())
        .filter_map(|text| text.lines().next().map(|line| line.trim().to_string()))
        .filter(|group| !group.is_empty())
        .collect()
}

/// The attempts `<room>/turns/` names, by file stem.
fn attempts_seen(r: &Room) -> Vec<String> {
    let mut stems: Vec<String> = turn_entries(r)
        .iter()
        .filter_map(|path| path.file_stem().map(|s| s.to_string_lossy().to_string()))
        .collect();
    stems.sort();
    stems.dedup();
    stems
}

/// SIGKILL to each process group. `--` before the negative id: procps-ng's `kill -9 -GROUP` returns 0 and kills
/// nothing (the Pi's 4.0.2, Serenity 7c3ddd1d); macOS takes the same form.
fn kill_groups(groups: &[String]) {
    for group in groups {
        let _ = Command::new("kill")
            .args(["-9", "--", &format!("-{group}")])
            .status();
    }
}

fn ref_for(r: &Room, id: &str, lease: u32) -> bool {
    refs(&r.fx.repo)
        .iter()
        .any(|line| line.ends_with(&format!("refs/heads/room/{id}/{lease}")))
}

/// A worker that sleeps through its turn. A jailed worker writes only in its checkout (plan, d0ad2636), so no marker
/// outside it says a turn began: the pid file does.
fn sleeper(r: &Room) -> String {
    worker(&r.scratch, "sleeper", "sleep 600")
}

#[test]
fn a_killed_worker_fails_the_turn() {
    // kill -9 on the worker's process group mid-turn, the clock alive: that turn fails, and the item is taken again.
    // Workers take turns (plan task 9): the sleeper's turn is killed, and the fixer takes the item next.
    let r = setup();
    let id = add(&r, 0, "outside", "person:fixture");
    let (slow, fix) = (sleeper(&r), fixing_worker(&r.scratch));
    let _clock = Clock::start(&r, &[&slow, &fix], &["--turn-secs", "600"]);
    wait_for("the first turn to begin", Duration::from_secs(60), || {
        !worker_groups(&r).is_empty()
    });
    kill_groups(&worker_groups(&r));
    wait_for(
        "the item to pass on a later turn",
        Duration::from_secs(120),
        || state(&r, &id) == "passed_verified",
    );
    assert!(ref_for(&r, &id, 2), "taken again, as lease 2");
}

#[test]
fn a_killed_clock_recovers() {
    // Review focus 1: the clock dies mid-turn (power loss: kill -9 on its process group and the worker's). On restart
    // the item is taken again with the next lease number, and the dead turn leaves no ref.
    let r = setup();
    let id = add(&r, 0, "outside", "person:fixture");
    let (slow, fix) = (sleeper(&r), fixing_worker(&r.scratch));
    let mut clock = Clock::start(&r, &[&slow], &["--lease-secs", "3", "--turn-secs", "600"]);
    wait_for("the first turn to begin", Duration::from_secs(60), || {
        !worker_groups(&r).is_empty()
    });
    kill_groups(&worker_groups(&r));
    clock.kill_group();
    sleep(Duration::from_secs(4)); // past the first lease
    ok(&once_through(&r, &[&fix], &["--lease-secs", "3"]));
    assert_eq!(state(&r, &id), "passed_verified");
    assert!(ref_for(&r, &id, 2), "taken again with lease 2");
    assert!(!ref_for(&r, &id, 1), "the dead turn left no ref");
}

#[test]
fn stop_halts_within_fifteen_seconds() {
    let r = setup();
    add(&r, 0, "outside", "person:fixture");
    add(&r, 1, "outside", "person:fixture");
    let slow = sleeper(&r);
    let mut clock = Clock::start(&r, &[&slow], &["--turn-secs", "600"]);
    wait_for("a turn to begin", Duration::from_secs(60), || {
        !worker_groups(&r).is_empty()
    });
    let groups = worker_groups(&r);
    let seen = attempts_seen(&r);
    let began = Instant::now();
    ok(&yak(&r.room, &["stop"]));
    assert!(r.room.join("STOP").exists());
    assert!(
        clock.exited_within(Duration::from_secs(15)),
        "the clock ends within 15 s of STOP"
    );
    wait_for(
        "every worker process to end",
        Duration::from_secs(15).saturating_sub(began.elapsed()),
        || !groups.iter().any(|group| group_alive(group)),
    );
    sleep(Duration::from_secs(2));
    let new: Vec<String> = attempts_seen(&r)
        .into_iter()
        .filter(|attempt| !seen.contains(attempt))
        .collect();
    assert!(new.is_empty(), "no new turn starts after STOP: {new:?}");
}

#[test]
fn the_ceiling_refuses_the_next_turn() {
    let r = setup();
    for n in 0..3 {
        add(&r, n, "outside", "person:fixture");
    }
    let idle = worker(&r.scratch, "idle", "exit 0");
    let out = once_through(&r, &[&idle], &["--daily-turns", "2"]);
    let said = format!(
        "{}{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(
        said.contains("daily ceiling"),
        "the refusal says so: {said}"
    );
    let status = ok(&yak(&r.room, &["status", "--json"]));
    assert_eq!(json_num(&status, "turns_today"), Some(2), "{status}");
}

#[test]
fn a_worker_cannot_change_its_check() {
    // The worker makes the right fix and also rewrites the check, so the item can fail only because a commit that
    // alters a file its check froze is refused (plan, 340df0a8).
    let r = setup();
    let id = add(&r, 0, "outside", "person:fixture");
    let cheat = worker(
        &r.scratch,
        "cheat",
        &format!(
            "echo {} > items/item0.txt\nprintf 'exit 0\\n' > checks/item0.sh\ncommit 'the fix, and a check that always passes'",
            green(0)
        ),
    );
    let _ = once_through(&r, &[&cheat], &[]);
    assert_eq!(
        state(&r, &id),
        "abandoned",
        "a changed check is refused each turn, though the fix is right"
    );
    assert_eq!(attempts(&r, &id), Some(3), "MAX_ATTEMPTS turns");
}

#[test]
fn a_worker_has_no_remote() {
    let r = setup();
    let id = add(&r, 0, "outside", "person:fixture");
    // A jailed worker writes only in its checkout, so it commits its evidence, which arrives with the turn's ref.
    let repo = r.fx.repo.display();
    let body = format!(
        "mkdir -p evidence\ngit remote -v > evidence/remotes.txt\ngit push --all origin 2>/dev/null; echo $? >> evidence/push-exit.txt\ngit push '{repo}' HEAD:refs/heads/pushed 2>/dev/null; echo $? >> evidence/push-exit.txt\necho {g} > items/item0.txt\ngit add -A\ncommit 'make item 0 green, with the evidence'",
        g = green(0)
    );
    let pusher = worker(&r.scratch, "pusher", &body);
    let before = refs(&r.fx.repo);
    let _ = once_through(&r, &[&pusher], &[]);
    let turn = refs(&r.fx.repo)
        .into_iter()
        .find_map(|line| {
            let name = line.split(' ').nth(1)?.to_string();
            name.starts_with(&format!("refs/heads/room/{id}/"))
                .then_some(name)
        })
        .expect("the turn's ref");
    let shown = |file: &str| git(&r.fx.repo, &["show", &format!("{turn}:evidence/{file}")]);
    assert_eq!(shown("remotes.txt"), "", "the sandbox has no remote");
    let codes = shown("push-exit.txt");
    assert!(
        codes.lines().count() == 2 && codes.lines().all(|code| code != "0"),
        "every push fails: {codes:?}"
    );
    let after = refs(&r.fx.repo);
    let new: Vec<&String> = after
        .iter()
        .filter(|line| !before.contains(*line))
        .collect();
    assert!(
        new.iter()
            .all(|line| line.contains(&format!("refs/heads/room/{id}/"))),
        "only the clock's ref: {new:?}"
    );
    assert_eq!(
        git(&r.fx.repo, &["remote"]),
        "",
        "the item's repository gained no remote"
    );
}

#[test]
fn no_prompt_text_reaches_the_store() {
    let r = setup();
    add(&r, 0, "outside", "person:fixture");
    let body = format!(
        "echo {MARKER}\necho {MARKER} >&2\necho {g} > items/item0.txt\ncommit 'make item 0 green {MARKER}'",
        g = green(0)
    );
    let chatty = worker(&r.scratch, "chatty", &body);
    let _ = once_through(&r, &[&chatty], &[]);
    for name in ["room.sqlite3", "room.sqlite3-wal"] {
        let path = r.room.join(name);
        if let Ok(bytes) = fs::read(&path) {
            assert!(
                !bytes.windows(MARKER.len()).any(|w| w == MARKER.as_bytes()),
                "{name} holds the marker"
            );
        }
    }
}

#[test]
fn a_second_clock_refuses() {
    let r = setup();
    add(&r, 0, "outside", "person:fixture");
    let slow = sleeper(&r);
    let _first = Clock::start(&r, &[&slow], &["--turn-secs", "600"]);
    wait_for("the first clock's turn", Duration::from_secs(60), || {
        !worker_groups(&r).is_empty()
    });
    let err = refused(&once_through(&r, &[&slow], &[]));
    assert!(
        err.contains("another process") || err.contains("lock"),
        "says locked: {err}"
    );
}

#[test]
fn a_damaged_store_is_refused() {
    // Review focus 5: a damaged store is refused with a message, never replaced by an empty one.
    let r = setup();
    let store = r.room.join("room.sqlite3");
    let whole = fs::read(&store).expect("the store");
    fs::write(&store, &whole[..whole.len() / 2]).expect("truncate it");
    let before = fs::read(&store).expect("the truncated store");
    let err = refused(&yak(&r.room, &["status"]));
    assert!(err.contains("damaged"), "says damaged: {err}");
    assert_eq!(
        fs::read(&store).expect("the store after"),
        before,
        "its bytes are unchanged"
    );
}

#[test]
fn a_missing_store_is_not_created() {
    // The refusal names the cure (RoomError::Missing), so a binary that refuses everything doesn't pass.
    let dir = TempDir::new().expect("a temporary directory");
    let empty = dir.path().join("empty");
    fs::create_dir_all(&empty).expect("make it");
    let err = refused(&yak(&empty, &["status"]));
    assert!(err.contains("yak init"), "says the room is missing: {err}");
    assert_eq!(
        fs::read_dir(&empty).expect("read it").count(),
        0,
        "no file was created"
    );
    let absent = dir.path().join("absent");
    let err = refused(&yak(&absent, &["status"]));
    assert!(err.contains("yak init"), "says the room is missing: {err}");
    assert!(!absent.exists(), "no directory was created");
}
