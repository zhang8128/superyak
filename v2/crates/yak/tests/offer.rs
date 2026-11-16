//! The offer through the clock and the command line (spec 2026-11-16, section 4): the block is made once,
//! before any turn, from a file the room reads whole; a file it refuses stops the clock before any turn; every
//! turn of a clock is given the same block; and what is kept of how the block was made makes it again.
mod common;

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Output;
use std::time::Duration;

use assert_cmd::Command;
use common::{NEVER, World};
use room::limits::{LEASE_SECS, MAX_ATTEMPTS};
use room::offer::{self, Arm, Block, Offered};
use room::{ItemId, ItemState, Room, TurnView};
use serde_json::{Value, json};
use yak::clock::{ClockError, Mode, Offering};

const HISTORY: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

/// A whole offer file whose goals and roads are these paths: each goal reached over `roads` and then itself.
fn offer_file(goals: &[(&str, &str, &[&str])], gone: &[&str]) -> Value {
    let mut all: Vec<Value> = goals
        .iter()
        .map(|(goal, state, roads)| {
            let mut ways: Vec<Value> = roads
                .iter()
                .enumerate()
                .map(|(n, to)| json!({"to": to, "walked_by": n + 2, "state": "same"}))
                .collect();
            ways.push(json!({"to": goal, "walked_by": 1, "state": state}));
            json!({"path": goal, "state": state,
                   "route": {"roads": ways, "cost_millis": 700, "dearer_ways": 1}})
        })
        .collect();
    all.extend(
        gone.iter().map(
            |path| json!({"path": path, "state": "gone", "route": null, "none": "not_taught"}),
        ),
    );
    json!({
        "offer": 1, "history": HISTORY, "ranker": "ranker-1", "store": "store-1", "kernel": "kernel-1",
        "measure": {"name": "share", "version": "1"},
        "chosen": [{"attempt": "a0123456789ab", "score": 3}],
        "goals": all
    })
}

fn parse(value: &Value) -> offer::Offer {
    offer::read(&serde_json::to_vec(value).unwrap()).unwrap()
}

fn offering(arm: Arm, value: Option<&Value>) -> Offering {
    Offering {
        arm,
        offer: value.map(parse),
        order: 3,
        seed: 11,
    }
}

/// The World's repository tracks check.sh and answer1.txt to answer4.txt.
fn world_offer() -> Value {
    offer_file(&[("answer1.txt", "changed", &["check.sh"])], &["old.txt"])
}

/// A worker that does nothing: none of these clocks reaches a turn.
fn idle(world: &World) -> String {
    world.script("idle.sh", "#!/bin/sh\nexit 0\n")
}

/// Takes every draft's check as frozen, without running it, so that its item can be taken, and the clock has no
/// draft to freeze.
fn frozen(world: &mut World) {
    for id in world.items.clone() {
        let made = room::Frozen {
            check_hash: "1".repeat(64),
            red_on_base: true,
            red_on_wrong: vec![true],
        };
        assert_eq!(
            world.room.record_frozen(&id, made).unwrap(),
            ItemState::Open
        );
    }
}

fn offer_refusal(world: &mut World, offering: Offering) -> String {
    world.offer = Some(offering);
    let worker = idle(world);
    let (result, events) = world.run(&[&worker], Mode::OnceThrough, NEVER, 60);
    let Err(refused @ ClockError::Offer(_)) = result else {
        panic!("the offer was not refused: {result:?}");
    };
    let said = refused.to_string();
    // No turn was started, nothing was taken, and nothing is left in the room's turns.
    assert!(common::started(&events).is_empty());
    for item in world.room.items().unwrap() {
        assert_eq!((item.lease_no, item.attempts), (0, 0), "{item:?}");
    }
    assert!(world.turns().is_empty());
    assert!(!said.contains('\n'));
    said
}

#[test]
fn an_offer_the_room_refuses_stops_the_clock_before_any_turn() {
    // A path not tracked at the item's base.
    let mut world = World::new(1);
    let item = world.items[0].0.clone();
    let untracked = offer_file(&[("answer1.txt", "same", &["nope/missing.txt"])], &[]);
    let said = offer_refusal(&mut world, offering(Arm::Route, Some(&untracked)));
    assert!(
        said.contains("goals[0].route.roads[0].to is not a tracked file at the base")
            && said.contains(&item)
            && said.ends_with("the clock started no turn"),
        "{said}"
    );
    // A path marked gone that the base tracks.
    let mut world = World::new(1);
    let present = offer_file(&[("answer1.txt", "same", &[])], &["answer2.txt"]);
    let said = offer_refusal(&mut world, offering(Arm::Shuffled, Some(&present)));
    assert!(said.contains("goals[1].path is marked gone"), "{said}");
    // The arm nothing with an offer, and an arm that offers without one.
    let mut world = World::new(1);
    let said = offer_refusal(&mut world, offering(Arm::Nothing, Some(&world_offer())));
    assert!(
        said.contains("the arm nothing takes no offer file"),
        "{said}"
    );
    for arm in [Arm::Route, Arm::Shuffled] {
        let mut world = World::new(1);
        let said = offer_refusal(&mut world, offering(arm, None));
        assert!(said.contains("needs an offer file"), "{said}");
    }
    // A base that cannot be listed.
    let mut world = World::new(1);
    fs::rename(&world.repo, world.scratch("moved")).unwrap();
    let said = offer_refusal(&mut world, offering(Arm::Route, Some(&world_offer())));
    assert!(said.contains("could not be listed"), "{said}");
}

/// The control for the refusals above: the same clock with a file whose paths are all tracked goes on past the
/// offer. Its ceiling of no turns stops it at the first take, so no turn runs.
#[test]
fn an_offer_whose_paths_are_tracked_lets_the_clock_go_on() {
    for arm in [Arm::Route, Arm::Shuffled] {
        let mut world = World::new(1);
        frozen(&mut world);
        world.room.set_ceiling(0, 1).unwrap();
        world.offer = Some(offering(arm, Some(&world_offer())));
        let worker = idle(&world);
        let (result, _) = world.run(&[&worker], Mode::OnceThrough, NEVER, 60);
        assert!(
            matches!(
                result,
                Err(ClockError::Room(room::RoomError::Ceiling { .. }))
            ),
            "{result:?}"
        );
    }
    let mut world = World::new(1);
    frozen(&mut world);
    world.room.set_ceiling(0, 1).unwrap();
    world.offer = Some(offering(Arm::Nothing, None));
    let worker = idle(&world);
    let (result, _) = world.run(&[&worker], Mode::OnceThrough, NEVER, 60);
    assert!(matches!(result, Err(ClockError::Room(_))), "{result:?}");
}

/// Each base is checked, and only those of items a turn may still be given: an abandoned item's base is not.
#[test]
fn the_offer_is_checked_at_the_base_of_every_item_a_turn_may_still_be_given() {
    // Three items at the first base, which does not track extra.txt, and a fourth at a base that does.
    let mut world = World::new(2);
    let base = world.base.clone();
    let model = world
        .room
        .add_item(room::NewItem {
            title: "answer 3 is 42".into(),
            repo: world.repo.clone(),
            base_commit: base,
            after: Vec::new(),
            check: room::CheckSpec {
                command: "sh check.sh 3".into(),
                files: vec!["check.sh".into()],
                timeout_secs: 30,
                // A check a model wrote cannot verify a pass.
                origin: room::CheckOrigin::Model,
                wrong_artifacts: vec![world.wrong.clone()],
                written_by: "claude:test".into(),
            },
        })
        .unwrap();
    world.items.push(model);
    common::git(&world.repo, &["checkout", "-q", "-b", "more"]);
    fs::write(world.repo.join("extra.txt"), "x\n").unwrap();
    common::git(&world.repo, &["add", "extra.txt"]);
    common::git(&world.repo, &["commit", "-q", "-m", "extra"]);
    let more = common::git(&world.repo, &["rev-parse", "HEAD"]);
    common::git(&world.repo, &["checkout", "-q", "main"]);
    world.add_at("answer 4 is 42", "sh check.sh 4", &["check.sh"], &more);
    let ids: Vec<String> = world.items.iter().map(|id| id.0.clone()).collect();
    let extra = offer_file(&[("extra.txt", "same", &["check.sh"])], &[]);
    // Refused at the first base, named by the first item at it, and at no other.
    let said = offer_refusal(&mut world, offering(Arm::Route, Some(&extra)));
    assert!(said.contains(&ids[0]), "{said}");
    for other in &ids[1..] {
        assert!(!said.contains(other.as_str()), "{said}");
    }
    // And the other way about: extra.txt said to be gone. The first base does not track it and takes that; the
    // fourth item's base tracks it and refuses, named by the fourth item. So both live bases are looked at,
    // whichever comes first.
    let gone = offer_file(&[], &["extra.txt"]);
    let said = offer_refusal(&mut world, offering(Arm::Route, Some(&gone)));
    assert!(said.contains(&ids[3]), "{said}");
    for other in &ids[..3] {
        assert!(!said.contains(other.as_str()), "{said}");
    }
    // Each item at the first base finished, one of each way: passed and verified, abandoned, passed and not
    // verified. Then only the fourth's base is checked, and it tracks extra.txt.
    frozen(&mut world);
    let mut now = common::now();
    let pass = |world: &mut World, now: i64| -> ItemState {
        let lease = world.room.take("script:x", now).unwrap().expect("taken");
        world.room.hand_in(&lease, &world.wrong, now).unwrap();
        let verdict = room::Verdict {
            passed: true,
            exit_code: 0,
            timed_out: false,
            commit: world.wrong.clone(),
            check_hash: "1".repeat(64),
            output_sha256: "4".repeat(64),
        };
        world
            .room
            .record_verdict(&lease.item, lease.lease_no, &verdict, now)
            .unwrap()
    };
    assert_eq!(pass(&mut world, now), ItemState::PassedVerified);
    while world.room.item(&world.items[1]).unwrap().state != ItemState::Abandoned {
        let lease = world.room.take("script:x", now).unwrap().expect("taken");
        assert_eq!(lease.item, world.items[1]);
        now += LEASE_SECS + 1;
        world.room.expire_due(now).unwrap();
        assert!(world.room.item(&world.items[1]).unwrap().attempts <= MAX_ATTEMPTS);
    }
    assert_eq!(pass(&mut world, now), ItemState::PassedUnverified);
    assert_eq!(
        world.room.item(&world.items[3]).unwrap().state,
        ItemState::Open
    );
    world.room.set_ceiling(0, 1).unwrap();
    world.offer = Some(offering(Arm::Route, Some(&extra)));
    let worker = idle(&world);
    let (result, _) = world.run(&[&worker], Mode::OnceThrough, NEVER, 60);
    assert!(
        matches!(
            result,
            Err(ClockError::Room(room::RoomError::Ceiling { .. }))
        ),
        "{result:?}"
    );
}

/// A tracked file is a regular file, executable or not, as a walk's is: a link the base tracks is not one.
#[test]
fn a_tracked_file_is_a_regular_file_executable_or_not() {
    let mut world = World::new(0);
    common::git(&world.repo, &["checkout", "-q", "-b", "kinds"]);
    let run = world.repo.join("run.sh");
    fs::write(&run, "#!/bin/sh\n").unwrap();
    fs::set_permissions(&run, fs::Permissions::from_mode(0o755)).unwrap();
    std::os::unix::fs::symlink("check.sh", world.repo.join("link.txt")).unwrap();
    common::git(&world.repo, &["add", "run.sh", "link.txt"]);
    common::git(&world.repo, &["commit", "-q", "-m", "kinds"]);
    let kinds = common::git(&world.repo, &["rev-parse", "HEAD"]);
    common::git(&world.repo, &["checkout", "-q", "main"]);
    let listed = common::git(&world.repo, &["ls-tree", &kinds, "run.sh", "link.txt"]);
    assert!(
        listed.contains("100755 blob") && listed.contains("120000 blob"),
        "{listed}"
    );
    world.add_at("answer 1 is 42", "sh check.sh 1", &["check.sh"], &kinds);
    frozen(&mut world);
    world.room.set_ceiling(0, 1).unwrap();
    let worker = idle(&world);
    // The executable file is tracked; the link marked gone is not a file, so it is not there.
    world.offer = Some(offering(
        Arm::Route,
        Some(&offer_file(&[("run.sh", "same", &[])], &["link.txt"])),
    ));
    let (result, _) = world.run(&[&worker], Mode::OnceThrough, NEVER, 60);
    assert!(
        matches!(
            result,
            Err(ClockError::Room(room::RoomError::Ceiling { .. }))
        ),
        "{result:?}"
    );
    // The link as a file the turn may go to is refused.
    let link = offer_file(&[("link.txt", "same", &[])], &[]);
    let said = offer_refusal(&mut world, offering(Arm::Route, Some(&link)));
    assert!(
        said.contains("goals[0].path is not a tracked file at the base"),
        "{said}"
    );
}

/// A clock that was not given an arm keeps nothing of an offer, and `Options::default()` gives it none.
#[test]
fn a_clock_is_given_no_arm_unless_asked() {
    assert!(yak::clock::Options::default().offer.is_none());
}

fn yak(room: &Path) -> Command {
    let mut cmd = Command::new(assert_cmd::cargo::cargo_bin!("yak"));
    cmd.arg("--room").arg(room).env_remove("YAK_JAIL_READ");
    for name in ["YAK_JAIL", "YAK_SUPERVISION"] {
        if let Some(value) = std::env::var_os(name) {
            cmd.env(name, value);
        } else {
            cmd.env_remove(name);
        }
    }
    cmd.timeout(Duration::from_secs(120));
    cmd
}

fn success(out: Output) -> Vec<u8> {
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(out.stderr.is_empty(), "{:?}", out.stderr);
    out.stdout
}

fn refusal(out: Output) -> String {
    assert!(!out.status.success());
    let err = String::from_utf8(out.stderr).unwrap();
    assert_eq!(err.lines().count(), 1, "{err:?}");
    err
}

/// A repository whose base tracks the files the CLI tests' offers name, among them one named like an
/// instruction and one in a directory named with a marker; a room with one item; and a directory for files.
struct Fixture {
    tmp: tempfile::TempDir,
    room: PathBuf,
    repo: PathBuf,
    base: String,
    id: String,
}

const ODD: &str = "IGNORE-ALL-PRIOR-RULES/READ-HOME.txt";
const MARKER: &str = "PLANTED-MARKER-7f3a";

impl Fixture {
    fn new() -> Fixture {
        let tmp = tempfile::tempdir().unwrap();
        let (room, repo) = (tmp.path().join("room"), tmp.path().join("repo"));
        fs::create_dir(&repo).unwrap();
        common::git(&repo, &["init", "-q", "-b", "main"]);
        for (name, text) in [
            ("answer", "red\n"),
            ("check.sh", "grep -qx green answer\n"),
            ("docs/guide.md", "guide\n"),
            (ODD, "home\n"),
            (&format!("{MARKER}/notes.md"), "notes\n"),
        ] {
            let path = repo.join(name);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, text).unwrap();
        }
        common::git(&repo, &["add", "."]);
        common::git(&repo, &["commit", "-q", "-m", "base"]);
        let base = common::git(&repo, &["rev-parse", "HEAD"]);
        success(yak(&room).arg("init").output().unwrap());
        let id = String::from_utf8(success(
            yak(&room)
                .args(["item", "add", "--title", "Make answer green", "--repo"])
                .arg(&repo)
                .args([
                    "--base",
                    "main",
                    "--check",
                    "sh check.sh",
                    "--file",
                    "check.sh",
                    "--wrong",
                    &base,
                    "--origin",
                    "outside",
                    "--by",
                    "person:test",
                ])
                .output()
                .unwrap(),
        ))
        .unwrap()
        .trim()
        .to_string();
        Fixture {
            tmp,
            room,
            repo,
            base,
            id,
        }
    }

    /// Writes `value` as an offer file and gives its path.
    fn file(&self, name: &str, value: &Value) -> PathBuf {
        let path = self.tmp.path().join(name);
        fs::write(&path, serde_json::to_vec_pretty(value).unwrap()).unwrap();
        path
    }

    fn script(&self, body: &str) -> String {
        let path = self.tmp.path().join("worker.sh");
        fs::write(&path, format!("#!/bin/sh\n{body}\n")).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
        format!("script:{}", path.display())
    }

    fn render(&self, arm: &str, file: &Path, seed: u64) -> Command {
        let mut cmd = yak(&self.room);
        cmd.args(["offer", "render", "--arm", arm, "--offer"])
            .arg(file)
            .args(["--seed", &seed.to_string()]);
        cmd
    }

    fn turns(&self) -> Vec<TurnView> {
        Room::open_read_only(&self.room)
            .unwrap()
            .turns(&ItemId(self.id.clone()))
            .unwrap()
    }
}

/// The CLI fixture's offer: two goals over the file named like an instruction, one through the marked
/// directory, and one goal gone.
fn fixture_offer() -> Value {
    offer_file(
        &[
            ("answer", "changed", &[ODD, &format!("{MARKER}/notes.md")]),
            ("docs/guide.md", "same", &[ODD]),
        ],
        &["old.txt"],
    )
}

#[test]
fn offer_render_prints_the_block_and_nothing_else() {
    let f = Fixture::new();
    let file = f.file("offer.json", &fixture_offer());
    let read = parse(&fixture_offer());
    for (name, arm) in [("route", Arm::Route), ("shuffled", Arm::Shuffled)] {
        for seed in [0, 1, u64::MAX] {
            let printed = success(f.render(name, &file, seed).output().unwrap());
            let block = offer::render(&read, arm, seed).unwrap();
            assert_eq!(printed, block.text().as_bytes(), "{name} {seed}");
            // Checked at the base, as the clock checks it, the same block.
            let checked = success(
                f.render(name, &file, seed)
                    .arg("--repo")
                    .arg(&f.repo)
                    .args(["--base", "main"])
                    .output()
                    .unwrap(),
            );
            assert_eq!(checked, printed);
        }
    }
    // It needs no room.
    let printed = success(
        Command::new(assert_cmd::cargo::cargo_bin!("yak"))
            .args(["offer", "render", "--arm", "route", "--offer"])
            .arg(&file)
            .args(["--seed", "0"])
            .env_remove("HOME")
            .output()
            .unwrap(),
    );
    assert_eq!(
        printed,
        offer::render(&read, Arm::Route, 0)
            .unwrap()
            .text()
            .as_bytes()
    );
}

#[test]
fn offer_render_refuses_what_the_clock_refuses() {
    let f = Fixture::new();
    // A path the base does not track: refused when checked at the base, with one line and no block.
    let untracked = f.file(
        "untracked.json",
        &offer_file(&[("answer", "same", &["nope.txt"])], &[]),
    );
    let out = f
        .render("route", &untracked, 0)
        .arg("--repo")
        .arg(&f.repo)
        .args(["--base", &f.base])
        .output()
        .unwrap();
    assert!(out.stdout.is_empty());
    assert!(refusal(out).contains("is not a tracked file at the base"));
    // A base that is not a commit of the repository.
    let file = f.file("offer.json", &fixture_offer());
    let out = f
        .render("route", &file, 0)
        .arg("--repo")
        .arg(&f.repo)
        .args(["--base", "no-such-commit"])
        .output()
        .unwrap();
    assert!(refusal(out).contains("is not a commit"));
    // A file that is not whole, and one over the limit.
    let broken = f.tmp.path().join("broken.json");
    fs::write(&broken, b"{\"offer\": 1,").unwrap();
    assert!(refusal(f.render("route", &broken, 0).output().unwrap()).contains("is not JSON"));
    let large = f.tmp.path().join("large.json");
    fs::write(&large, vec![b' '; offer::MAX_OFFER_BYTES + 1]).unwrap();
    assert!(
        refusal(f.render("shuffled", &large, 0).output().unwrap())
            .contains("is over 1048576 bytes")
    );
    // The arm nothing renders nothing, and is refused as an arm here; --repo without --base is refused.
    refusal(f.render("nothing", &file, 0).output().unwrap());
    refusal(
        f.render("route", &file, 0)
            .arg("--repo")
            .arg(&f.repo)
            .output()
            .unwrap(),
    );
    // And --base without --repo: a base looked for in no repository is refused, not passed over unchecked.
    let out = f
        .render("route", &file, 0)
        .arg("--base")
        .arg("main")
        .output()
        .unwrap();
    assert!(out.stdout.is_empty());
    assert!(refusal(out).contains("--repo"));
}

/// What a turn's record keeps of its block is the block `yak offer render` makes again from the same file and
/// seed, by its SHA-256 and its length, as `yak item turns --json` prints them.
#[test]
fn a_turns_kept_hash_and_length_are_those_of_the_block_made_again() {
    for (name, arm, seed) in [
        ("route", Arm::Route, 5),
        ("shuffled", Arm::Shuffled, 5),
        ("shuffled", Arm::Shuffled, u64::MAX),
    ] {
        let f = Fixture::new();
        let file = f.file("offer.json", &fixture_offer());
        let mut room = Room::open(&f.room).unwrap();
        // Its check is taken as frozen, so that the item can be taken without running it.
        let frozen = room::Frozen {
            check_hash: "1".repeat(64),
            red_on_base: true,
            red_on_wrong: vec![true],
        };
        room.record_frozen(&ItemId(f.id.clone()), frozen).unwrap();
        let lease = room.take("codex:sol", common::now()).unwrap().unwrap();
        let (_, given) = offer::give(arm, Some(&parse(&fixture_offer())), 2, seed).unwrap();
        room.record_offer(&lease.attempt, &given).unwrap();
        drop(room);
        let printed: Value = serde_json::from_slice(&success(
            yak(&f.room)
                .args(["item", "turns", &f.id, "--json"])
                .output()
                .unwrap(),
        ))
        .unwrap();
        let kept = &printed[0]["offered"];
        assert_eq!(kept["arm"], json!(name));
        assert_eq!((&kept["order"], &kept["seed"]), (&json!(2), &json!(seed)));
        // Made again from the same file and seed: the same bytes as the block the turn was given, and so
        // the same SHA-256 (the room's, checked against Python's hashlib in the room's own pinned test).
        let again = success(f.render(name, &file, seed).output().unwrap());
        let block = offer::render(&parse(&fixture_offer()), arm, seed).unwrap();
        assert_eq!(again, block.text().as_bytes());
        assert_eq!(kept["made"]["block_sha256"], json!(block.sha256()));
        assert_eq!(kept["made"]["block_bytes"], json!(again.len()));
        assert_eq!(kept["made"]["renderer"], json!(offer::RENDERER_VERSION));
        assert_eq!(kept["made"]["empty"], json!(false));
        assert_eq!(
            kept["made"]["goals"],
            json!(["answer", "docs/guide.md", "old.txt"])
        );
    }
}

#[test]
fn the_clock_refuses_a_wrong_arm_or_offer_before_any_turn() {
    let f = Fixture::new();
    let worker = f.script("exit 0");
    let file = f.file("offer.json", &fixture_offer());
    let clock = || {
        let mut cmd = yak(&f.room);
        cmd.args(["clock", "run", "--once-through", "--worker", &worker]);
        cmd
    };
    // What clap refuses: an offer, an order or a seed without an arm; an arm without an order or a seed.
    for args in [
        vec!["--offer", file.to_str().unwrap()],
        vec!["--order", "1"],
        vec!["--seed", "1"],
        vec![
            "--arm",
            "route",
            "--order",
            "1",
            "--offer",
            file.to_str().unwrap(),
        ],
        vec![
            "--arm",
            "route",
            "--seed",
            "1",
            "--offer",
            file.to_str().unwrap(),
        ],
        vec!["--arm", "sideways", "--order", "1", "--seed", "1"],
        vec!["--arm", "nothing", "--order", "-1", "--seed", "1"],
        vec!["--arm", "nothing", "--order", "1", "--seed", "1.5"],
    ] {
        let err = refusal(clock().args(&args).output().unwrap());
        assert!(
            err.contains("required argument")
                || err.contains("invalid value")
                || err.contains("unexpected argument"),
            "{args:?}: {err}"
        );
    }
    // What the room refuses: the arm nothing with a file, an arm that offers without one, a file not whole.
    let broken = f.tmp.path().join("broken.json");
    fs::write(&broken, b"").unwrap();
    for (args, said) in [
        (
            vec!["--arm", "nothing", "--offer", file.to_str().unwrap()],
            "takes no offer file",
        ),
        (vec!["--arm", "route"], "needs an offer file"),
        (vec!["--arm", "shuffled"], "needs an offer file"),
        (
            vec!["--arm", "route", "--offer", broken.to_str().unwrap()],
            "the file is empty",
        ),
    ] {
        let out = clock()
            .args(&args)
            .args(["--order", "1", "--seed", "1"])
            .output()
            .unwrap();
        let err = refusal(out);
        assert!(err.contains(said), "{args:?}: {err}");
    }
    // No turn was taken by any of them.
    assert!(f.turns().is_empty());
}

/// A worker that hands in the prompt it was given and never the answer, so its item is taken again.
const HANDS_IN_ITS_PROMPT: &str = "cat > prompt.txt\ngit add prompt.txt\ngit -c user.name=Test -c user.email=test@example.invalid commit -qm prompt";

/// The prompt each turn was given, from the commit it handed in, beside its record.
fn prompts_handed_in(f: &Fixture) -> Vec<(TurnView, String)> {
    f.turns()
        .into_iter()
        .map(|turn| {
            let commit = turn.commit.clone().expect("a turn handed a commit in");
            // Every byte of it, the last line's end too: the helper that runs git trims what it prints.
            let out = std::process::Command::new("git")
                .env_remove("GIT_DIR")
                .env_remove("GIT_WORK_TREE")
                .env_remove("GIT_INDEX_FILE")
                .arg("-C")
                .arg(&f.repo)
                .args(["show", &format!("{commit}:prompt.txt")])
                .output()
                .unwrap();
            assert!(
                out.status.success(),
                "{}",
                String::from_utf8_lossy(&out.stderr)
            );
            let prompt = String::from_utf8(out.stdout).expect("a prompt is text");
            (turn, prompt)
        })
        .collect()
}

/// The block in a prompt: from the opening sentence to the blank line before the rules.
fn block_in(prompt: &str) -> &str {
    let start = prompt.find(offer::OPENING).expect("a block");
    let end = prompt.find("\nThe room's rules:\n").unwrap();
    &prompt[start..end]
}

fn kept(turn: &TurnView) -> &Offered {
    turn.offered.as_ref().expect("the turn's offer is kept")
}

/// Under each arm that offers, through the clock's restart of itself: every turn at the item was given the same
/// block, after its check's command and before its rules, and that block's SHA-256 and length are the ones kept
/// with the turn, which `yak offer render` makes again.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn every_turn_of_a_clock_is_given_the_one_block_whose_hash_and_length_are_kept() {
    for (name, arm) in [("route", Arm::Route), ("shuffled", Arm::Shuffled)] {
        let f = Fixture::new();
        let file = f.file("offer.json", &fixture_offer());
        let worker = f.script(HANDS_IN_ITS_PROMPT);
        let out = yak(&f.room)
            .args(["clock", "run", "--once-through", "--worker", &worker])
            .args(["--arm", name, "--offer"])
            .arg(&file)
            .args(["--order", "4", "--seed", "21"])
            .env("YAK_TEST_CANARY", "offer-canary")
            .output()
            .unwrap();
        assert_eq!(
            String::from_utf8_lossy(&out.stdout).lines().next(),
            Some("starting again with a clean environment")
        );
        let given = prompts_handed_in(&f);
        assert!(
            given.len() >= 2,
            "{name}: the item was taken {} time(s): {}",
            given.len(),
            String::from_utf8_lossy(&out.stdout)
        );
        let block = offer::render(&parse(&fixture_offer()), arm, 21).unwrap();
        let expected =
            turn::worker::prompt_with(None, Some(&block), "Make answer green", "sh check.sh");
        let again = success(f.render(name, &file, 21).output().unwrap());
        for (turn, prompt) in &given {
            assert_eq!(prompt, &expected, "{name}");
            let found = block_in(prompt);
            assert_eq!(found, block.text());
            let kept = kept(turn);
            assert_eq!((kept.arm, kept.order, kept.seed), (arm, 4, 21));
            let made = kept.made.as_ref().unwrap();
            assert_eq!(
                (made.block_sha256.as_str(), made.block_bytes),
                (block.sha256().as_str(), found.len() as u64)
            );
            assert_eq!(again, found.as_bytes());
            assert!(!made.empty);
        }
        // `yak item turns --json` prints the same records.
        let printed: Value = serde_json::from_slice(&success(
            yak(&f.room)
                .args(["item", "turns", &f.id, "--json"])
                .output()
                .unwrap(),
        ))
        .unwrap();
        for (n, (turn, _)) in given.iter().enumerate() {
            assert_eq!(
                printed[n]["offered"],
                serde_json::to_value(kept(turn)).unwrap()
            );
        }
    }
}

/// An empty offer is kept as empty under its arm; the arm nothing is kept as nothing, with today's prompt; and a
/// clock given no arm keeps no offer at all.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn an_empty_offer_is_told_from_the_arm_nothing_and_from_no_arm() {
    let empty = offer_file(&[], &["old.txt"]);
    let as_it_was = turn::worker::prompt(None, "Make answer green", "sh check.sh");
    for case in ["empty", "nothing", "none"] {
        let f = Fixture::new();
        let file = f.file("offer.json", &empty);
        let worker = f.script(HANDS_IN_ITS_PROMPT);
        let mut clock = yak(&f.room);
        clock.args(["clock", "run", "--once-through", "--worker", &worker]);
        match case {
            "empty" => {
                clock.args(["--arm", "route", "--offer"]).arg(&file);
            }
            "nothing" => {
                clock.args(["--arm", "nothing"]);
            }
            _ => {}
        }
        if case != "none" {
            clock.args(["--order", "1", "--seed", "2"]);
        }
        let out = clock.output().unwrap();
        let given = prompts_handed_in(&f);
        assert!(
            !given.is_empty(),
            "{case}: {}",
            String::from_utf8_lossy(&out.stdout)
        );
        for (turn, prompt) in &given {
            match case {
                "empty" => {
                    let kept = kept(turn);
                    assert_eq!(kept.arm, Arm::Route);
                    let made = kept.made.as_ref().unwrap();
                    assert!(made.empty);
                    let block = block_in(prompt);
                    assert_eq!(
                        block,
                        format!(
                            "{}\n\nEarlier turns left nothing for this item.\n",
                            offer::OPENING
                        )
                    );
                    let rendered = offer::render(&parse(&empty), Arm::Route, 2).unwrap();
                    assert_eq!(block, rendered.text());
                    assert_eq!(
                        (made.block_sha256.as_str(), made.block_bytes),
                        (rendered.sha256().as_str(), block.len() as u64)
                    );
                }
                "nothing" => {
                    assert_eq!(
                        kept(turn),
                        &Offered {
                            arm: Arm::Nothing,
                            order: 1,
                            seed: 2,
                            made: None
                        }
                    );
                    assert_eq!(prompt, &as_it_was);
                }
                _ => {
                    assert_eq!(turn.offered, None);
                    assert_eq!(prompt, &as_it_was);
                }
            }
        }
    }
}

/// Nothing of the block's text is kept: after a real run, a marker in a road's directory name and the block's
/// own sentences are in no file of the room's directory. The control: the goals' paths are there, kept.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn after_a_run_nothing_of_the_block_is_in_the_rooms_directory() {
    for arm in ["route", "shuffled"] {
        let f = Fixture::new();
        let file = f.file("offer.json", &fixture_offer());
        let worker = f.script(HANDS_IN_ITS_PROMPT);
        let _ = yak(&f.room)
            .args(["clock", "run", "--once-through", "--worker", &worker])
            .args(["--arm", arm, "--offer"])
            .arg(&file)
            .args(["--order", "1", "--seed", "1"])
            .output()
            .unwrap();
        // The turns were given the marker: without that, finding it nowhere would say nothing.
        let given = prompts_handed_in(&f);
        assert!(!given.is_empty() && given.iter().all(|(_, p)| p.contains(MARKER)));
        let mut files = Vec::new();
        let mut left = vec![f.room.clone()];
        while let Some(dir) = left.pop() {
            for entry in fs::read_dir(&dir).unwrap() {
                let path = entry.unwrap().path();
                let meta = fs::symlink_metadata(&path).unwrap();
                if meta.is_dir() {
                    left.push(path);
                } else if meta.is_file() {
                    files.push((path.clone(), fs::read(&path).unwrap()));
                }
            }
        }
        let holds =
            |bytes: &[u8], words: &str| bytes.windows(words.len()).any(|w| w == words.as_bytes());
        assert!(files.iter().any(|(_, bytes)| holds(bytes, "docs/guide.md")));
        for (path, bytes) in &files {
            for words in [
                MARKER,
                "IGNORE-ALL-PRIOR-RULES",
                "What follows is what the room saw",
                "walked by",
                "in an order drawn by chance",
            ] {
                assert!(!holds(bytes, words), "{} holds {words:?}", path.display());
            }
        }
    }
}

/// A stand-in for a model worker's program, first on the clock's search path, keeps the prompt it is sent in its
/// sandbox, and the room commits it for the worker.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_stand_in_worker_is_sent_the_block_whose_hash_and_length_are_kept() {
    for program in ["claude", "codex"] {
        for (name, arm) in [("route", Arm::Route), ("shuffled", Arm::Shuffled)] {
            let f = Fixture::new();
            let file = f.file("offer.json", &fixture_offer());
            let bin = f.tmp.path().join("bin");
            fs::create_dir(&bin).unwrap();
            let stand_in = bin.join(program);
            fs::write(&stand_in, "#!/bin/sh\ncat > prompt.txt\n").unwrap();
            fs::set_permissions(&stand_in, fs::Permissions::from_mode(0o755)).unwrap();
            let out = yak(&f.room)
                .args([
                    "clock",
                    "run",
                    "--once-through",
                    "--daily-turns",
                    "1",
                    "--worker",
                ])
                .arg(format!("{program}:test"))
                .args(["--arm", name, "--offer"])
                .arg(&file)
                .args(["--order", "7", "--seed", "8"])
                .env(
                    "PATH",
                    format!(
                        "{}:{}",
                        bin.display(),
                        std::env::var("PATH").unwrap_or_default()
                    ),
                )
                .output()
                .unwrap();
            let given = prompts_handed_in(&f);
            assert_eq!(
                given.len(),
                1,
                "{program} {name}: {}{}",
                String::from_utf8_lossy(&out.stdout),
                String::from_utf8_lossy(&out.stderr)
            );
            let (turn, prompt) = &given[0];
            let block: Block = offer::render(&parse(&fixture_offer()), arm, 8).unwrap();
            let found = block_in(prompt);
            assert_eq!(found, block.text());
            let made = kept(turn).made.as_ref().unwrap();
            assert_eq!(
                (made.block_sha256.as_str(), made.block_bytes),
                (block.sha256().as_str(), found.len() as u64),
                "{program} {name}"
            );
        }
    }
}
