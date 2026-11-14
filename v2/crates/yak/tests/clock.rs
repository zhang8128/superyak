//! The clock (stage 1 plan, task 9): the six tests the plan names, then one for each case the builder decided.

mod common;

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::thread;
use std::time::{Duration, Instant};

use common::*;
use room::limits::{MAX_ATTEMPTS, TURN_SECS};
use room::{DisagreementKind, ItemState, RoomError, Target, Tool};
use yak::clock::{self, ClockError, Event, Mode, Options, Outcome};

fn state(world: &World, n: usize) -> ItemState {
    world.room.item(&world.items[n]).unwrap().state
}

// The six tests of the plan.

#[test]
fn once_through_passes_a_fixable_item() {
    let mut world = World::new(1);
    let fix = world.script("fix.sh", FIX);
    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    assert_eq!(state(&world, 0), ItemState::PassedVerified);
    assert!(matches!(
        outcomes(&events)[..],
        [Outcome::Judged {
            state: ItemState::PassedVerified,
            nothing: None,
            timed_out: false,
            recheck: None,
            ..
        }]
    ));
    assert_eq!(
        world.room.status(now()).unwrap().verified_passes_last_day,
        1
    );
    // The walk is what the worker's stream showed: one Read of a tracked file, by name and blob.
    let (_, attempt, _, _) = &started(&events)[0];
    let walk = world.room.walk(attempt).unwrap();
    assert_eq!(walk.len(), 1);
    assert_eq!(walk[0].tool, Tool::Read);
    assert!(walk[0].ok);
    let blob = git(
        &world.repo,
        &["rev-parse", &format!("{}:answer1.txt", world.base)],
    );
    assert_eq!(
        walk[0].target,
        Target::TrackedFile {
            path: "answer1.txt".into(),
            blob
        }
    );
}

#[test]
fn the_only_new_ref_is_the_turns_branch() {
    let mut world = World::new(1);
    let fix = world.script("fix.sh", FIX);
    let before = world.refs();
    let head = git(&world.repo, &["rev-parse", "HEAD"]);
    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    let after = world.refs();
    let added: Vec<&String> = after.iter().filter(|r| !before.contains(r)).collect();
    let removed: Vec<&String> = before.iter().filter(|r| !after.contains(r)).collect();
    let name = world.room_ref(&world.items[0], 1);
    assert_eq!(added, [&name]);
    assert!(removed.is_empty());
    // The ref names the commit that was handed in and judged, and nothing else in the repository moved.
    let Outcome::Judged { commit, .. } = &outcomes(&events)[0] else {
        panic!("not judged");
    };
    assert_eq!(&git(&world.repo, &["rev-parse", &name]), commit);
    assert_eq!(
        git(&world.repo, &["show", &format!("{name}:answer1.txt")]),
        "42"
    );
    assert_eq!(git(&world.repo, &["rev-parse", "HEAD"]), head);
    assert_eq!(git(&world.repo, &["status", "--porcelain"]), "");
    assert_eq!(git(&world.repo, &["remote"]), "");
    for r in &before {
        let at = |refs: &[String]| refs.contains(r);
        assert!(at(&after));
    }
    assert_eq!(
        git(&world.repo, &["rev-parse", "refs/heads/wrong"]),
        world.wrong
    );
}

#[test]
fn stop_ends_a_running_worker() {
    let mut world = World::new(2);
    // It ignores SIGTERM, and so does its child, so only the SIGKILL after the grace ends them.
    let slow = world.script("slow.sh", "#!/bin/sh\ntrap '' TERM\nsleep 600\n");
    let turns = world.room_dir.join("turns");
    let room_dir = world.room_dir.clone();
    let stopper = thread::spawn(move || {
        let deadline = Instant::now() + Duration::from_secs(60);
        let mut pid_file = None;
        assert!(wait_until(deadline, || {
            pid_file = fs::read_dir(&turns).ok().and_then(|entries| {
                entries
                    .flatten()
                    .map(|e| e.path())
                    .find(|p| p.extension().is_some_and(|x| x == "pid"))
            });
            pid_file.is_some()
        }));
        let group = read_group(&pid_file.unwrap(), deadline);
        fs::write(room_dir.join("STOP"), "").unwrap();
        (group, Instant::now())
    });
    let (result, events) = world.run(&[&slow], Mode::Forever, NEVER, TURN_SECS);
    let returned = Instant::now();
    let (group, stopped_at) = stopper.join().unwrap();
    result.unwrap();
    assert!(
        returned - stopped_at < Duration::from_secs(15),
        "the clock took {:?} to stop",
        returned - stopped_at
    );
    assert!(
        wait_until(Instant::now() + Duration::from_secs(2), || !group_alive(
            group
        )),
        "the worker's group {group} is still alive"
    );
    // No new turn started, nothing was handed in, and the item is open again with no attempt counted: a person
    // stopped the room, and the item did nothing wrong.
    assert_eq!(started(&events).len(), 1);
    assert_eq!(outcomes(&events), [Outcome::Stopped]);
    let view = world.room.item(&world.items[0]).unwrap();
    assert_eq!((view.state, view.attempts), (ItemState::Open, 0));
    assert_eq!(state(&world, 1), ItemState::Open);
    assert!(world.room_refs().is_empty());
    assert!(world.turns().is_empty(), "left: {:?}", world.turns());
}

#[test]
fn workers_take_turns() {
    let mut world = World::new(4);
    let a = world.script("a.sh", FIX);
    let b = world.script("b.sh", FIX);
    let (result, events) = world.run(&[&a, &b], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    let workers: Vec<String> = started(&events).into_iter().map(|s| s.3).collect();
    assert_eq!(workers, [a.clone(), b.clone(), a, b]);
    for n in 0..4 {
        assert_eq!(state(&world, n), ItemState::PassedVerified);
    }
}

#[test]
fn a_recheck_that_differs_is_listed() {
    let mut world = World::new(0);
    // Red on the base and on the wrong commit; on the fix it passes the first time and fails when rechecked. A
    // check in the jail cannot leave a mark outside its checkout to count its runs, so it tells the recheck by
    // where it runs: the clock gives a recheck a directory of its own, `turns/<attempt>.recheck`.
    let command = "case \"$PWD\" in *.recheck/*) exit 1;; esac; grep -qx 42 answer1.txt";
    let id = world.add_check("answer 1 is 42, once", command, &[]);
    let fix = world.script("fix.sh", FIX);
    let (result, events) = world.run(&[&fix], Mode::OnceThrough, ALWAYS, TURN_SECS);
    result.unwrap();
    assert!(matches!(
        outcomes(&events)[..],
        [Outcome::Judged {
            state: ItemState::PassedVerified,
            recheck: Some(ItemState::PassedUnverified),
            ..
        }]
    ));
    assert_eq!(state(&world, 0), ItemState::PassedUnverified);
    let listed = world.room.disagreements().unwrap();
    assert!(
        listed
            .iter()
            .any(|d| d.kind == DisagreementKind::RecheckDiffers && d.item == id),
        "{listed:?}"
    );
}

#[test]
fn the_sandbox_is_gone_after_the_verdict() {
    let mut world = World::new(1);
    let fix = world.script("fix.sh", FIX);
    let turns = world.room_dir.join("turns");
    let mut seen_during = Vec::new();
    let mut left_at_end = None;
    let mut report = |e: &Event| match e {
        Event::Started { attempt, .. } => seen_during.push(attempt.0.clone()),
        Event::Ended { .. } => {
            left_at_end = Some(fs::read_dir(&turns).unwrap().count());
        }
        _ => {}
    };
    clock::run_with(
        &mut world.room,
        &[fix],
        Mode::OnceThrough,
        &mut Fixed(NEVER),
        Options {
            report: Some(&mut report),
            poll: Duration::from_millis(100),
            ..Options::default()
        },
    )
    .unwrap();
    assert_eq!(seen_during.len(), 1);
    // By the time the turn is reported ended, its sandbox, pid file and check scratch are gone.
    assert_eq!(left_at_end, Some(0));
    assert!(world.turns().is_empty());
    assert_eq!(state(&world, 0), ItemState::PassedVerified);
    // The room keeps only the frozen check; neither the freeze's nor the check's clone is left.
    let checks: Vec<_> = fs::read_dir(world.room_dir.join("checks"))
        .unwrap()
        .flatten()
        .map(|e| e.file_name())
        .collect();
    assert_eq!(checks.len(), 1, "{checks:?}");
}

// The cases the builder decided, one test each.

/// A worker that commits nothing hands in its base, which fails; the item is taken again until it is abandoned,
/// and the loop goes on to the next item.
#[test]
fn a_turn_that_commits_nothing_fails_and_the_room_moves_on() {
    let mut world = World::new(2);
    let idle = world.script("idle.sh", "#!/bin/sh\nexit 0\n");
    // Random numbers that would pick every pass for a recheck: a failure is never rechecked.
    let (result, events) = world.run(&[&idle], Mode::OnceThrough, ALWAYS, TURN_SECS);
    result.unwrap();
    let problems: Vec<&Event> = events
        .iter()
        .filter(|e| matches!(e, Event::Problem { .. }))
        .collect();
    assert!(problems.is_empty(), "{problems:?}");
    let ends = outcomes(&events);
    assert_eq!(ends.len(), 2 * MAX_ATTEMPTS as usize);
    for (k, outcome) in ends.iter().enumerate() {
        let Outcome::Judged {
            state,
            commit,
            nothing,
            ..
        } = outcome
        else {
            panic!("turn {k}: {outcome:?}");
        };
        assert_eq!(commit, &world.base);
        assert_eq!(nothing.as_deref(), Some("the turn committed nothing"));
        let last = k % MAX_ATTEMPTS as usize == MAX_ATTEMPTS as usize - 1;
        let expected = if last {
            ItemState::Abandoned
        } else {
            ItemState::Failed
        };
        assert_eq!(*state, expected, "turn {k}");
    }
    for n in 0..2 {
        let view = world.room.item(&world.items[n]).unwrap();
        assert_eq!(view.state, ItemState::Abandoned);
        assert_eq!(view.attempts, MAX_ATTEMPTS);
    }
    // A base hand-in brings nothing new into the repository, so it makes no ref.
    assert!(world.room_refs().is_empty());
}

/// A worker that runs out of time is ended with its group, and what it had committed by then is judged.
#[test]
fn a_turn_out_of_time_is_judged_by_what_it_committed() {
    let mut world = World::new(1);
    let late = world.script("late.sh", &format!("{FIX}sleep 600\n"));
    let groups = Groups::watch(world.room_dir.join("turns"));
    let started_at = Instant::now();
    let (result, events) = world.run(&[&late], Mode::OnceThrough, NEVER, 2);
    let groups = groups.seen();
    result.unwrap();
    assert!(started_at.elapsed() < Duration::from_secs(60));
    assert!(matches!(
        outcomes(&events)[..],
        [Outcome::Judged {
            state: ItemState::PassedVerified,
            timed_out: true,
            nothing: None,
            ..
        }]
    ));
    assert!(!groups.is_empty(), "no pid file was seen");
    for group in groups {
        assert!(
            wait_until(Instant::now() + Duration::from_secs(2), || !group_alive(
                group
            )),
            "the group {group} is still alive"
        );
    }
}

/// A lease the room calls stale mid-turn (here a lease of one second, so the first renewal is too late) ends the
/// worker, hands in nothing and makes no ref; the next pass returns the item, until it is abandoned.
#[test]
fn a_lease_that_goes_stale_mid_turn_is_left_to_expire() {
    let mut world = World::new(1);
    world.room.set_lease_secs(1).unwrap();
    let fix = FIX.strip_prefix("#!/bin/sh\n").unwrap();
    let slow = world.script("slow.sh", &format!("#!/bin/sh\nsleep 30\n{fix}"));
    let groups = Groups::watch(world.room_dir.join("turns"));
    let began = Instant::now();
    let (result, events) = world.run(&[&slow], Mode::OnceThrough, NEVER, TURN_SECS);
    let groups = groups.seen();
    result.unwrap();
    // Each worker is ended when its lease is lost, not left to run its 30 seconds.
    assert!(
        began.elapsed() < Duration::from_secs(20),
        "{:?}",
        began.elapsed()
    );
    assert_eq!(
        outcomes(&events),
        vec![Outcome::LeaseLost; MAX_ATTEMPTS as usize]
    );
    let view = world.room.item(&world.items[0]).unwrap();
    assert_eq!(view.state, ItemState::Abandoned);
    assert_eq!(view.lease_no, MAX_ATTEMPTS);
    assert!(world.room_refs().is_empty());
    assert!(world.turns().is_empty());
    assert!(!groups.is_empty(), "no pid file was seen");
    for group in groups {
        assert!(!group_alive(group), "the group {group} is still alive");
    }
}

/// After a restart the clock finds a dead clock's turn. It ends the run that turn's record describes, when that
/// run is still the process it was; removes its sandbox, records and scratch; never fetches from that sandbox;
/// and takes the item again once the lease expires.
///
/// It acts only on a record the room wrote. A record of this attempt whose process number has since gone to
/// another process ends nothing. And a file that only looks like a record, named for no attempt of the room, is
/// not read at all, however truly it describes a process that is running: ending a process on the word of a
/// file anyone could have put there is not the clock's to do.
#[test]
fn a_restart_ends_a_dead_clocks_run_and_clears_its_files() {
    let mut world = World::new(1);
    assert_eq!(clock::freeze_drafts(&mut world.room).unwrap(), 1);
    world.room.set_lease_secs(2).unwrap();
    let id = world.items[0].clone();
    let dead = world
        .room
        .take("script:/dead-clock", now())
        .unwrap()
        .unwrap();
    assert_eq!(dead.lease_no, 1);

    // What the dead clock left: a clone holding a fix on the turn's branch, a directory the worker made
    // unwritable, a record of a run that is still going, and a check's scratch directory.
    let turns = world.room_dir.join("turns");
    fs::create_dir_all(&turns).unwrap();
    let clone = turns.join(&dead.attempt.0);
    git(&world.repo, &["clone", "-q", ".", clone.to_str().unwrap()]);
    git(
        &clone,
        &["checkout", "-q", "-b", &format!("room/{}/1", id.0)],
    );
    fs::write(clone.join("answer1.txt"), "42\n").unwrap();
    git(&clone, &["commit", "-q", "-am", "dead fix"]);
    let locked = clone.join("locked");
    fs::create_dir(&locked).unwrap();
    fs::write(locked.join("f"), "x").unwrap();
    fs::set_permissions(&locked, fs::Permissions::from_mode(0o500)).unwrap();
    let record = |name: &str, text: String| fs::write(turns.join(name), text).unwrap();
    // The dead turn's own run, still going: the record holds its group and its start time.
    let left = Orphan::start();
    record(
        &format!("{}.pid", dead.attempt.0),
        format!("{}\n{}\n", left.0, started_at(left.0)),
    );
    // A record of the same attempt's check whose number has since gone to a process that started at another
    // time.
    let reused = Orphan::start();
    record(
        &format!("{}.check.pid", dead.attempt.0),
        format!("{}\nMon Jan 1 00:00:00 2001\n", reused.0),
    );
    // A file that is no record of the room's, though everything it says of a running process is true.
    let foreign = Orphan::start();
    record(
        "a-stranger.pid",
        format!("{}\n{}\n", foreign.0, started_at(foreign.0)),
    );
    fs::create_dir(turns.join(format!("{}.check", dead.attempt.0))).unwrap();
    // And a freeze's scratch clone in checks/.
    let freeze_scratch = world.room_dir.join("checks").join(".work-1-2-3");
    fs::create_dir_all(freeze_scratch.join("clone")).unwrap();

    let fix = world.script("fix.sh", FIX);
    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    let ended = wait_until(Instant::now() + Duration::from_secs(2), || !left.alive());
    let spared = [reused.alive(), foreign.alive()];
    result.unwrap();
    assert!(ended, "the dead clock's run was left going");
    assert_eq!(
        spared,
        [true, true],
        "the clock ended a process no record of the room's described"
    );

    let cleared: Vec<&Event> = events
        .iter()
        .filter(|e| matches!(e, Event::Cleared { .. }))
        .collect();
    assert_eq!(cleared.len(), 6, "{cleared:?}");
    assert!(!freeze_scratch.exists());
    for (name, ended) in [
        (format!("turns/{}.pid", dead.attempt.0), true),
        (format!("turns/{}.check.pid", dead.attempt.0), false),
        ("turns/a-stranger.pid".to_string(), false),
    ] {
        assert!(
            cleared.contains(&&Event::Cleared { name, ended }),
            "{cleared:?}"
        );
    }
    // The file that is no record is said to be none, and nothing else is called a problem.
    let problems: Vec<&Event> = events
        .iter()
        .filter(|e| matches!(e, Event::Problem { .. }))
        .collect();
    assert!(
        matches!(problems[..], [Event::Problem { item: None, what }] if what.contains("a-stranger.pid")),
        "{problems:?}"
    );
    // Everything was cleared before the clock's own turn began.
    let first_start = events
        .iter()
        .position(|e| matches!(e, Event::Started { .. }))
        .unwrap();
    let cleared_first = events[..first_start]
        .iter()
        .filter(|e| matches!(e, Event::Cleared { .. }))
        .count();
    assert_eq!(cleared_first, 6);
    let view = world.room.item(&id).unwrap();
    assert_eq!(view.state, ItemState::PassedVerified);
    assert_eq!(view.lease_no, 2);
    assert_eq!(world.room_refs(), [world.room_ref(&id, 2)]);
    assert!(world.turns().is_empty(), "left: {:?}", world.turns());
}

/// A record of an attempt of the room's that cannot be read as one may be all that is left of a run still
/// going. The clock stops where it is: it removes nothing, starts no turn, and says which record. With the
/// record gone, by a person's hand, it starts.
#[test]
fn a_record_that_cannot_be_read_stops_the_clock_with_everything_in_place() {
    let mut world = World::new(1);
    assert_eq!(clock::freeze_drafts(&mut world.room).unwrap(), 1);
    world.room.set_lease_secs(2).unwrap();
    let dead = world
        .room
        .take("script:/dead-clock", now())
        .unwrap()
        .unwrap();
    let turns = world.room_dir.join("turns");
    fs::create_dir_all(turns.join(&dead.attempt.0)).unwrap();
    let record = turns.join(format!("{}.pid", dead.attempt.0));
    fs::write(&record, "4242").unwrap();
    let fix = world.script("fix.sh", FIX);

    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    assert!(
        matches!(&result, Err(ClockError::Unrecovered { record, .. }) if record.ends_with(".pid")),
        "{result:?}"
    );
    assert!(started(&events).is_empty(), "a turn started: {events:?}");
    assert!(
        !events.iter().any(|e| matches!(e, Event::Cleared { .. })),
        "something was removed: {events:?}"
    );
    assert!(record.exists() && turns.join(&dead.attempt.0).is_dir());

    fs::remove_file(&record).unwrap();
    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    assert_eq!(started(&events).len(), 1);
    assert_eq!(state(&world, 0), ItemState::PassedVerified);
}

/// A sandbox is removed only if it is still the directory the room made. If something else is at its path when
/// the turn ends, the clock leaves it where it is, says so, and goes on.
#[test]
fn a_sandbox_that_was_replaced_is_left_where_it_is() {
    let mut world = World::new(1);
    // It commits nothing: three turns, each a failure.
    let slow = world.script("slow.sh", "#!/bin/sh\nsleep 3\n");
    let turns = world.room_dir.join("turns");
    let moved = world.scratch("moved-away");
    let swapper = thread::spawn(move || {
        // The first turn's sandbox, once its worker is running: the name in `turns/` with no dot in it.
        let deadline = Instant::now() + Duration::from_secs(60);
        let mut sandbox = None;
        assert!(wait_until(deadline, || {
            let names: Vec<String> = fs::read_dir(&turns)
                .into_iter()
                .flatten()
                .flatten()
                .map(|e| e.file_name().to_string_lossy().into_owned())
                .collect();
            let running = names.iter().any(|n| n.ends_with(".pid"));
            sandbox = names.into_iter().find(|n| !n.contains('.'));
            running && sandbox.is_some()
        }));
        let at = turns.join(sandbox.unwrap());
        fs::rename(&at, &moved).unwrap();
        fs::create_dir(&at).unwrap();
        fs::write(at.join("canary"), "KEEP").unwrap();
        at
    });
    let (result, events) = world.run(&[&slow], Mode::OnceThrough, NEVER, TURN_SECS);
    let at = swapper.join().unwrap();
    result.unwrap();
    assert_eq!(fs::read_to_string(at.join("canary")).unwrap(), "KEEP");
    assert!(
        events.iter().any(
            |e| matches!(e, Event::Problem { what, .. } if what.contains("the sandbox was not removed"))
        ),
        "{events:?}"
    );
    // The room went on: the item was tried its three times.
    assert_eq!(outcomes(&events).len(), MAX_ATTEMPTS as usize);
    assert_eq!(state(&world, 0), ItemState::Abandoned);
    // Nothing else of any turn is left.
    let name = at.file_name().unwrap().to_string_lossy().into_owned();
    assert_eq!(world.turns(), [name]);
}

/// A scratch directory is the room's to remove only if a run of the room's made it. One that was at its path
/// before any run is not: the sandbox's own removal leaves it, and so does the clock's tidying after the turn.
#[test]
fn a_scratch_directory_the_room_did_not_make_is_left_where_it_is() {
    let mut world = World::new(1);
    let fix = world.script("fix.sh", FIX);
    let turns = world.room_dir.join("turns");
    let mut canaries = Vec::new();
    let mut plant = |e: &Event| {
        if let Event::Started { attempt, .. } = e {
            let scratch = turns.join(format!("{}.scratch", attempt.0));
            fs::create_dir_all(&scratch).unwrap();
            fs::write(scratch.join("canary"), "KEEP").unwrap();
            canaries.push(scratch);
        }
    };
    let (result, events) =
        world.run_hooked(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS, &mut plant);
    result.unwrap();
    assert!(!canaries.is_empty());
    for scratch in &canaries {
        assert_eq!(
            fs::read_to_string(scratch.join("canary")).unwrap(),
            "KEEP",
            "{events:?}"
        );
    }
    // Each is said, and nothing else of any turn is left.
    let said = events
        .iter()
        .filter(
            |e| matches!(e, Event::Problem { what, .. } if what.contains("the sandbox was not removed")),
        )
        .count();
    assert_eq!(said, canaries.len(), "{events:?}");
    let mut names: Vec<String> = canaries
        .iter()
        .map(|p| p.file_name().unwrap().to_string_lossy().into_owned())
        .collect();
    names.sort();
    assert_eq!(world.turns(), names);
}

/// A check has a sandbox of its own, inside the check's work directory. If something else is at that sandbox's
/// path when the check is done, it is left, and the clock's tidying leaves the work directory that holds it.
/// No verdict is taken from that check: the item waits out its lease and is tried again. A recheck is a check
/// like any other, and what took its sandbox's place is left in the same way.
#[test]
fn what_took_a_checks_sandboxs_place_is_left_with_the_directory_that_holds_it() {
    for (which, rng) in [("check", NEVER), ("recheck", ALWAYS)] {
        let mut world = World::new(0);
        world.room.set_lease_secs(2).unwrap();
        // Slow only on the fix, so freezing it on the base and the wrong commit stays quick.
        let id = world.add_check(
            "answer 1 is 42, slowly",
            "if grep -qx 42 answer1.txt; then sleep 3; fi; sh check.sh 1",
            &["check.sh"],
        );
        let fix = world.script("fix.sh", FIX);
        let turns = world.room_dir.join("turns");
        let moved = world.scratch("moved-away");
        let swapper = thread::spawn(move || {
            // The sandbox of the first check of that kind, once it is running: the one name without a dot in
            // the work directory beside its record.
            let deadline = Instant::now() + Duration::from_secs(60);
            let ending = format!(".{which}.pid");
            let mut sandbox = None;
            assert!(wait_until(deadline, || {
                let record = fs::read_dir(&turns)
                    .into_iter()
                    .flatten()
                    .flatten()
                    .map(|e| e.path())
                    .find(|p| p.to_string_lossy().ends_with(&ending));
                sandbox = record.and_then(|record| {
                    fs::read_dir(record.with_extension(""))
                        .into_iter()
                        .flatten()
                        .flatten()
                        .map(|e| e.path())
                        .find(|p| !p.file_name().unwrap().to_string_lossy().contains('.'))
                });
                sandbox.is_some()
            }));
            // Well inside the check's three seconds.
            thread::sleep(Duration::from_secs(1));
            let at = sandbox.unwrap();
            fs::rename(&at, &moved).unwrap();
            fs::create_dir(&at).unwrap();
            fs::write(at.join("canary"), "KEEP").unwrap();
            at
        });
        let (result, events) = world.run(&[&fix], Mode::OnceThrough, rng, TURN_SECS);
        let at = swapper.join().unwrap();
        result.unwrap();
        assert_eq!(
            fs::read_to_string(at.join("canary")).unwrap(),
            "KEEP",
            "{which}"
        );
        let ends = outcomes(&events);
        let passed = |outcome: &Outcome| {
            matches!(
                outcome,
                Outcome::Judged {
                    state: ItemState::PassedVerified,
                    ..
                }
            )
        };
        if which == "check" {
            assert!(
                matches!(&ends[0], Outcome::Unchecked { reason } if reason.contains("not what the room made there")),
                "{ends:?}"
            );
            // The room went on: the lease ran out, and the next turn passed.
            assert!(passed(&ends[1]), "{ends:?}");
            assert_eq!(world.room.item(&id).unwrap().lease_no, 2);
        } else {
            // The pass stands, and what became of the recheck is said.
            assert!(ends.len() == 1 && passed(&ends[0]), "{ends:?}");
            assert!(
                events.iter().any(|e| matches!(e, Event::Problem { what, .. }
                    if what.contains("the recheck could not run") && what.contains("not what the room made there"))),
                "{events:?}"
            );
        }
        // Nothing else of any turn is left: only the work directory that holds what was found.
        let holder = at.parent().unwrap().file_name().unwrap();
        assert_eq!(
            world.turns(),
            [holder.to_string_lossy().into_owned()],
            "{which}"
        );
        assert!(holder.to_string_lossy().ends_with(&format!(".{which}")));
    }
}

/// When the clock stops at a run it cannot end, what stays is that run's: its record and its directories, and
/// every other directory, since nothing is removed. A run the clock had already ended by then is over, and its
/// record went as it ended.
#[test]
fn a_clock_stopped_at_one_run_has_ended_the_ones_before_it_and_removed_nothing_else() {
    let mut world = World::new(2);
    assert_eq!(clock::freeze_drafts(&mut world.room).unwrap(), 2);
    world.room.set_ceiling(100, 2).unwrap();
    let mut dead: Vec<String> = (0..2)
        .map(|_| {
            let lease = world
                .room
                .take("script:/dead-clock", now())
                .unwrap()
                .unwrap();
            lease.attempt.0
        })
        .collect();
    // The clock goes through the records in the order of their names.
    dead.sort();
    let turns = world.room_dir.join("turns");
    for attempt in &dead {
        fs::create_dir_all(turns.join(attempt)).unwrap();
    }
    // The first is of a run that is still going; the second cannot be read.
    let left = Orphan::start();
    let (first, second) = (
        turns.join(format!("{}.pid", dead[0])),
        turns.join(format!("{}.pid", dead[1])),
    );
    fs::write(&first, format!("{}\n{}\n", left.0, started_at(left.0))).unwrap();
    fs::write(&second, "4242").unwrap();
    let fix = world.script("fix.sh", FIX);

    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    let named = format!("turns/{}.pid", dead[1]);
    assert!(
        matches!(&result, Err(ClockError::Unrecovered { record, .. }) if *record == named),
        "{result:?}"
    );
    assert!(started(&events).is_empty(), "a turn started: {events:?}");
    assert!(
        !events.iter().any(|e| matches!(e, Event::Cleared { .. })),
        "something was removed: {events:?}"
    );
    assert!(
        wait_until(Instant::now() + Duration::from_secs(2), || !left.alive()),
        "the first run was left going"
    );
    assert!(
        !first.exists(),
        "the record of a run that was ended is still there"
    );
    assert!(second.exists());
    for attempt in &dead {
        assert!(turns.join(attempt).is_dir());
    }
}

/// In `OnceThrough`, the ceiling ends the run with its reason, for the command line to say.
#[test]
fn the_ceiling_ends_a_once_through_run() {
    let mut world = World::new(2);
    world.room.set_ceiling(1, 1).unwrap();
    let fix = world.script("fix.sh", FIX);
    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    assert!(
        matches!(
            result,
            Err(ClockError::Room(RoomError::Ceiling { used: 1, limit: 1 }))
        ),
        "{result:?}"
    );
    assert_eq!(started(&events).len(), 1);
    assert_eq!(state(&world, 0), ItemState::PassedVerified);
    assert_eq!(state(&world, 1), ItemState::Open);
}

/// A hand-in whose check cannot run (here the worker removed the room's frozen copies) gets no verdict: the item
/// stays `Checking` until its lease expires, and is taken again until it is abandoned.
#[test]
fn a_check_that_cannot_run_leaves_the_item_to_expire() {
    let mut world = World::new(1);
    world.room.set_lease_secs(2).unwrap();
    let fix = world.script("fix.sh", FIX);
    // The frozen copies go while the first turn runs. A worker cannot do this itself: the jail keeps it out of
    // the room's directory. So the test does it, when the clock says a turn has started.
    let checks = world.room_dir.join("checks");
    let mut vandal = |event: &Event| {
        if matches!(event, Event::Started { .. }) && checks.exists() {
            fs::remove_dir_all(&checks).unwrap();
        }
    };
    let (result, events) =
        world.run_hooked(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS, &mut vandal);
    result.unwrap();
    let ends = outcomes(&events);
    assert_eq!(ends.len(), MAX_ATTEMPTS as usize);
    for outcome in &ends {
        let Outcome::Unchecked { reason } = outcome else {
            panic!("{outcome:?}");
        };
        assert!(reason.starts_with("the check could not run"), "{reason}");
    }
    let id = &world.items[0];
    assert_eq!(world.room.item(id).unwrap().state, ItemState::Abandoned);
    // Each hand-in was fetched before its check was tried, so each lease left its ref.
    let expected: Vec<String> = (1..=MAX_ATTEMPTS).map(|n| world.room_ref(id, n)).collect();
    assert_eq!(world.room_refs(), expected);
    assert!(world.turns().is_empty());
}

/// A worker that replaces its clone's `.git` with a link cannot have its work taken back: the turn hands in its
/// base and fails, and no git runs in what the worker left.
#[test]
fn a_worker_that_breaks_its_clone_hands_in_nothing() {
    let mut world = World::new(1);
    let body = format!("{FIX}mv .git .git-moved\nln -s .git-moved .git\n");
    let breaker = world.script("break.sh", &body);
    let (result, events) = world.run(&[&breaker], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    let ends = outcomes(&events);
    assert_eq!(ends.len(), MAX_ATTEMPTS as usize);
    for outcome in &ends {
        let Outcome::Judged {
            commit, nothing, ..
        } = outcome
        else {
            panic!("{outcome:?}");
        };
        assert_eq!(commit, &world.base);
        let nothing = nothing.as_deref().unwrap();
        assert!(nothing.starts_with("its clone was not usable"), "{nothing}");
    }
    assert_eq!(state(&world, 0), ItemState::Abandoned);
    assert!(world.room_refs().is_empty());
    assert!(world.turns().is_empty());
}

/// A draft whose check cannot be frozen (its base commit is not in the repository) stays a draft; the others are
/// frozen and run. `freeze_drafts` says which failed after trying the rest.
#[test]
fn a_draft_that_cannot_be_frozen_stays_a_draft() {
    let mut world = World::new(0);
    let missing = "0".repeat(40);
    let broken = world.add_at("no such base", "sh check.sh 1", &["check.sh"], &missing);
    let fine = world.add(2);
    let err = clock::freeze_drafts(&mut world.room).unwrap_err();
    let ClockError::Freeze {
        item,
        frozen,
        failed,
        ..
    } = &err
    else {
        panic!("{err:?}");
    };
    assert_eq!((item, *frozen, *failed), (&broken.0, 1, 1));
    assert_eq!(world.room.item(&fine).unwrap().state, ItemState::Open);

    let fix = world.script("fix.sh", FIX);
    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    let not_frozen = events
        .iter()
        .filter(|e| matches!(e, Event::NotFrozen { item, .. } if *item == broken))
        .count();
    assert_eq!(not_frozen, 1, "tried once per run, not once per pass");
    assert_eq!(world.room.item(&broken).unwrap().state, ItemState::Draft);
    assert_eq!(
        world.room.item(&fine).unwrap().state,
        ItemState::PassedVerified
    );
}

/// A commit that cannot be brought into the item's repository (here its object store is read-only) is a turn that
/// handed in nothing: the base is handed in and fails, so the attempt counts, and no ref is made.
#[test]
fn a_commit_that_cannot_be_fetched_fails_the_turn() {
    let mut world = World::new(1);
    assert_eq!(clock::freeze_drafts(&mut world.room).unwrap(), 1);
    let objects = world.repo.join(".git").join("objects");
    let set_mode = |mode: u32| {
        let mut dirs = vec![objects.clone()];
        while let Some(dir) = dirs.pop() {
            fs::set_permissions(&dir, fs::Permissions::from_mode(mode)).unwrap();
            for entry in fs::read_dir(&dir).unwrap().flatten() {
                if entry.file_type().unwrap().is_dir() {
                    dirs.push(entry.path());
                }
            }
        }
    };
    set_mode(0o555);
    let fix = world.script("fix.sh", FIX);
    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    set_mode(0o755);
    result.unwrap();
    let ends = outcomes(&events);
    assert_eq!(ends.len(), MAX_ATTEMPTS as usize);
    for outcome in &ends {
        let Outcome::Judged {
            commit, nothing, ..
        } = outcome
        else {
            panic!("{outcome:?}");
        };
        assert_eq!(commit, &world.base);
        let nothing = nothing.as_deref().unwrap();
        assert!(
            nothing.starts_with("its commit could not be fetched"),
            "{nothing}"
        );
    }
    assert_eq!(state(&world, 0), ItemState::Abandoned);
    assert!(world.room_refs().is_empty());
    assert!(world.turns().is_empty());
}

/// A turn longer than its lease keeps it: the clock renews it while the worker runs and while the check runs, so
/// the pass is recorded under the first lease. A reader sees the expiry move on in both states.
#[test]
fn a_long_turn_keeps_its_lease() {
    use std::sync::Arc;
    use std::sync::atomic::{AtomicBool, Ordering};

    let mut world = World::new(0);
    world.room.set_lease_secs(2).unwrap();
    // Slow only on the fix, so freezing it on the base and the wrong commit stays quick.
    let id = world.add_check(
        "answer 1 is 42, slowly",
        "if grep -qx 42 answer1.txt; then sleep 3; fi; sh check.sh 1",
        &["check.sh"],
    );
    let fix = FIX.strip_prefix("#!/bin/sh\n").unwrap();
    let slow = world.script("slow.sh", &format!("#!/bin/sh\nsleep 3\n{fix}"));
    let done = Arc::new(AtomicBool::new(false));
    let reader = {
        let (dir, id, done) = (world.room_dir.clone(), id.clone(), done.clone());
        thread::spawn(move || {
            let room = room::Room::open_read_only(&dir).unwrap();
            let mut seen: Vec<(ItemState, i64)> = Vec::new();
            while !done.load(Ordering::SeqCst) {
                let state = room.item(&id).unwrap().state;
                if let Some(lease) = room.current_lease(&id).unwrap()
                    && !seen.contains(&(state, lease.expires))
                {
                    seen.push((state, lease.expires));
                }
                thread::sleep(Duration::from_millis(100));
            }
            seen
        })
    };
    let (result, events) = world.run(&[&slow], Mode::OnceThrough, NEVER, TURN_SECS);
    done.store(true, Ordering::SeqCst);
    let seen = reader.join().unwrap();
    result.unwrap();
    assert!(matches!(
        outcomes(&events)[..],
        [Outcome::Judged {
            state: ItemState::PassedVerified,
            ..
        }]
    ));
    assert_eq!(world.room.item(&id).unwrap().lease_no, 1);
    for during in [ItemState::Leased, ItemState::Checking] {
        let expiries = seen.iter().filter(|(s, _)| *s == during).count();
        assert!(expiries >= 2, "{during:?}: {seen:?}");
    }
}

/// A ref the clock would make that is already in the repository is not replaced: that turn hands in nothing and
/// fails, and the next lease makes its own.
#[test]
fn a_ref_already_there_is_not_overwritten() {
    let mut world = World::new(1);
    let id = world.items[0].clone();
    let taken = world.room_ref(&id, 1);
    git(&world.repo, &["update-ref", &taken, &world.base]);
    let fix = world.script("fix.sh", FIX);
    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    let ends = outcomes(&events);
    let Outcome::Judged {
        state,
        commit,
        nothing,
        ..
    } = &ends[0]
    else {
        panic!("{:?}", ends[0]);
    };
    assert_eq!((state, commit), (&ItemState::Failed, &world.base));
    assert!(
        nothing
            .as_deref()
            .unwrap()
            .starts_with("its commit could not be fetched")
    );
    assert!(matches!(
        ends[1],
        Outcome::Judged {
            state: ItemState::PassedVerified,
            ..
        }
    ));
    assert_eq!(git(&world.repo, &["rev-parse", &taken]), world.base);
    assert_eq!(world.room_refs(), [taken, world.room_ref(&id, 2)]);
}

/// In `Forever`, the ceiling does not end the clock: it waits for the next day, and says so once.
#[test]
fn in_forever_the_ceiling_waits_and_says_so_once() {
    let mut world = World::new(2);
    world.room.set_ceiling(1, 1).unwrap();
    let fix = world.script("fix.sh", FIX);
    let stop = world.room_dir.join("STOP");
    let mut ceilings = 0;
    let mut turns = 0;
    let mut report = |e: &Event| match e {
        Event::Ceiling { used: 1, limit: 1 } => {
            ceilings += 1;
            if ceilings == 1 {
                // Long enough for several more passes to find the ceiling.
                let stop = stop.clone();
                thread::spawn(move || {
                    thread::sleep(Duration::from_millis(800));
                    fs::write(stop, "").unwrap();
                });
            }
        }
        Event::Started { .. } => turns += 1,
        _ => {}
    };
    clock::run_with(
        &mut world.room,
        &[fix],
        Mode::Forever,
        &mut Fixed(NEVER),
        Options {
            report: Some(&mut report),
            poll: Duration::from_millis(100),
            ..Options::default()
        },
    )
    .unwrap();
    assert_eq!((ceilings, turns), (1, 1));
    assert_eq!(state(&world, 0), ItemState::PassedVerified);
    assert_eq!(state(&world, 1), ItemState::Open);
}

/// A worker whose program is not there would fail every item it took: it is refused before any is taken.
#[test]
fn a_worker_that_cannot_run_is_refused_before_any_turn() {
    let mut world = World::new(1);
    let missing = format!("script:{}", world.scratch("no-such-script.sh").display());
    let not_executable = world.scratch("plain.sh");
    fs::write(&not_executable, "#!/bin/sh\nexit 0\n").unwrap();
    let not_executable = format!("script:{}", not_executable.display());
    let fix = world.script("fix.sh", FIX);
    for workers in [
        vec![missing.as_str()],
        vec![fix.as_str(), not_executable.as_str()],
    ] {
        let (result, events) = world.run(&workers, Mode::OnceThrough, NEVER, TURN_SECS);
        assert!(
            matches!(result, Err(ClockError::Turn(_))),
            "{workers:?}: {result:?}"
        );
        assert!(started(&events).is_empty());
    }
    assert_eq!(world.room.turns_today(now()).unwrap(), 0);
    assert_eq!(state(&world, 0), ItemState::Draft);
}

/// The inner half of the tests below, and nothing by itself. The room's switches are read from the environment,
/// and a test cannot change its own, so an outer half runs this one again in a child whose environment it chose.
#[test]
fn inner_a_clock_under_the_rooms_switches() {
    let Some(workers) = std::env::var_os("YAK_INNER_WORKERS") else {
        return;
    };
    let mut world = World::new(1);
    let fix = world.script("fix.sh", FIX);
    let workers: Vec<String> = workers
        .to_str()
        .unwrap()
        .split(',')
        .map(|name| {
            if name == "FIX" {
                fix.clone()
            } else {
                name.to_string()
            }
        })
        .collect();
    let workers: Vec<&str> = workers.iter().map(String::as_str).collect();
    // With `YAK_INNER_GIT_DIR` naming a directory that is first on this process's search path, a `git` is put
    // there that is the real git except where the mode says otherwise: at the clock's fetch, or where the clock
    // makes the turn's ref. Taking a ref back (`update-ref -d`) is always the real git's.
    if let Some(dir) = std::env::var_os("YAK_INNER_GIT_DIR") {
        let mode = std::env::var("YAK_INNER_GIT_MODE").unwrap();
        let stop = format!(": > '{}'", world.room_dir.join("STOP").display());
        let me = std::process::id();
        let real = "/usr/bin/git \"$@\"";
        let (at_fetch, at_ref) = match mode.as_str() {
            "slow-fetch" => ("sleep 4".to_string(), ":".to_string()),
            // Nine seconds, where the whole of a run takes a few: one that waited them out is seen on any machine.
            "fetch-stop" => (format!("{stop}; sleep 9"), ":".to_string()),
            // The fetch stops the room and then fails.
            "fetch-stop-fail" => (format!("{stop}; exit 1"), ":".to_string()),
            // The fetch is done at once and leaves something holding its output, under a git limit of 2 s.
            "fetch-held" => ("sleep 47.251 & exit 0".to_string(), ":".to_string()),
            "slow-ref" => (":".to_string(), "sleep 4".to_string()),
            // The room is stopped as the ref is about to be made.
            "ref-stop" => (":".to_string(), format!("{stop}; sleep 9")),
            // The ref is made, and the room is stopped before the clock has it back.
            "ref-then-stop" => (
                ":".to_string(),
                format!("{real}; made=$?; {stop}; sleep 1; exit $made"),
            ),
            // The machine sleeps while the ref is made: the clock is held still for longer than the lease, the
            // ref is made meanwhile, and the clock goes on.
            "ref-asleep" => (
                ":".to_string(),
                format!("kill -STOP {me}; sleep 3; {real}; made=$?; kill -CONT {me}; exit $made"),
            ),
            other => panic!("unknown mode {other}"),
        };
        if matches!(mode.as_str(), "slow-fetch" | "slow-ref" | "ref-asleep") {
            world.room.set_lease_secs(2).unwrap();
        }
        if mode == "fetch-held" {
            world.git_secs = 2;
        }
        let wrapper = std::path::Path::new(&dir).join("git");
        fs::write(
            &wrapper,
            format!(
                "#!/bin/sh\ncase \" $* \" in\n*\" update-ref --no-deref -d \"*) ;;\n*\" fetch \"*) {at_fetch};;\n\
                 *\" update-ref \"*) {at_ref};;\nesac\nexec {real}\n"
            ),
        )
        .unwrap();
        fs::set_permissions(&wrapper, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let began = Instant::now();
    let (result, events) = world.run(&workers, Mode::OnceThrough, NEVER, TURN_SECS);
    println!("TOOK {} s", began.elapsed().as_secs());
    match result {
        Ok(()) => println!("RAN {} turn(s)", started(&events).len()),
        Err(e) => println!("REFUSED {e}"),
    }
    println!("FIRST {:?}", outcomes(&events).first());
    println!("REFS {}", world.room_refs().len());
    let view = world.room.item(&world.items[0]).unwrap();
    println!(
        "ITEM {:?} attempts {} lease {}",
        view.state, view.attempts, view.lease_no
    );
    println!(
        "PROBLEMS {}",
        events
            .iter()
            .filter(|e| matches!(e, Event::Problem { .. }))
            .count()
    );
}

/// Runs the inner test above in a child with `git` wrapped as `mode` says, and returns what it printed.
fn with_git(mode: &str) -> String {
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().canonicalize().unwrap();
    let mut path = dir.clone().into_os_string();
    path.push(":/usr/bin:/bin:/usr/sbin:/sbin");
    let out = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "inner_a_clock_under_the_rooms_switches",
            "--nocapture",
        ])
        .env("YAK_INNER_WORKERS", "FIX")
        .env("YAK_INNER_GIT_DIR", &dir)
        .env("YAK_INNER_GIT_MODE", mode)
        .env("PATH", path)
        .env_remove("YAK_JAIL")
        .env_remove("YAK_SUPERVISION")
        .output()
        .unwrap();
    let printed = String::from_utf8_lossy(&out.stdout).into_owned();
    assert!(
        printed.contains("ITEM "),
        "{mode}: the inner run did not report: {printed} {}",
        String::from_utf8_lossy(&out.stderr)
    );
    printed
}

/// How long the inner run's clock took, in whole seconds.
fn took(printed: &str) -> u64 {
    let line = printed.lines().find(|l| l.starts_with("TOOK ")).unwrap();
    line.split(' ').nth(1).unwrap().parse().unwrap()
}

/// The clock's fetch can take a while. It is watched as the worker was: the lease is kept while it runs, and it
/// is ended as soon as the room is stopped. Whatever it returned, the room is asked again before anything more
/// is done, so a fetch that stops the room and then fails starts no check either. Seen with a `git` that is
/// slow to fetch.
#[test]
fn a_slow_fetch_keeps_its_lease_and_ends_with_no_ref_once_the_room_is_stopped() {
    // A fetch of four seconds under a lease of two: the lease is renewed meanwhile, and the turn is judged
    // under the lease it began with.
    let slow = with_git("slow-fetch");
    assert!(
        slow.contains("FIRST Some(Judged { state: PassedVerified"),
        "{slow}"
    );
    assert!(slow.contains("REFS 1"), "{slow}");
    assert!(
        slow.contains("ITEM PassedVerified attempts 1 lease 1"),
        "{slow}"
    );
    assert!(took(&slow) >= 4, "the fetch was not slow: {slow}");

    // Stopped by a person as the fetch began: the fetch is ended and not waited out, no ref is made, the item
    // is open again and the attempt does not count.
    let stopped = with_git("fetch-stop");
    assert!(stopped.contains("FIRST Some(Stopped)"), "{stopped}");
    assert!(stopped.contains("REFS 0"), "{stopped}");
    assert!(stopped.contains("ITEM Open attempts 0"), "{stopped}");
    assert!(took(&stopped) < 9, "the fetch was waited out: {stopped}");

    // A fetch that fails is a turn that handed in nothing. One that also stopped the room is a stopped turn:
    // nothing is handed in, and no check runs.
    let failed = with_git("fetch-stop-fail");
    assert!(failed.contains("FIRST Some(Stopped)"), "{failed}");
    assert!(failed.contains("REFS 0"), "{failed}");
    assert!(failed.contains("ITEM Open attempts 0"), "{failed}");
}

/// Making the turn's ref is watched in the same way, and it is the one thing the clock does outside the room's
/// directory. So a ref is made only under a lease the turn holds, in a room that is not stopped; and where
/// either changed while it was being made, the ref is taken back before the turn ends. Seen with a `git` that
/// is slow to make a ref, or that makes it while the clock is held still.
#[test]
fn a_ref_is_made_only_under_a_lease_the_turn_holds_in_a_room_that_is_not_stopped() {
    // Four seconds to make the ref under a lease of two: the lease is renewed meanwhile.
    let slow = with_git("slow-ref");
    assert!(
        slow.contains("FIRST Some(Judged { state: PassedVerified"),
        "{slow}"
    );
    assert!(slow.contains("REFS 1"), "{slow}");
    assert!(
        slow.contains("ITEM PassedVerified attempts 1 lease 1"),
        "{slow}"
    );
    assert!(took(&slow) >= 4, "making the ref was not slow: {slow}");

    // The room is stopped as the ref is about to be made: git is ended, and no ref is made.
    let stopped = with_git("ref-stop");
    assert!(stopped.contains("FIRST Some(Stopped)"), "{stopped}");
    assert!(stopped.contains("REFS 0"), "{stopped}");
    assert!(stopped.contains("ITEM Open attempts 0"), "{stopped}");
    assert!(took(&stopped) < 9, "git was waited out: {stopped}");

    // The room is stopped just after the ref was made: the ref is taken back.
    let after = with_git("ref-then-stop");
    assert!(after.contains("FIRST Some(Stopped)"), "{after}");
    assert!(after.contains("REFS 0"), "{after}");
    assert!(after.contains("ITEM Open attempts 0"), "{after}");
    assert!(after.contains("PROBLEMS 0"), "{after}");

    // The lease ran out while the ref was being made, which no renewal could prevent: the clock itself was
    // held still. The ref is taken back, and the turn ends as one whose lease was lost.
    let asleep = with_git("ref-asleep");
    assert!(asleep.contains("FIRST Some(LeaseLost)"), "{asleep}");
    assert!(asleep.contains("REFS 0"), "{asleep}");
    assert!(asleep.contains("PROBLEMS 0"), "{asleep}");
}

/// The clock's own git has a time limit that covers its output too, and the clock's fetch runs under it: a git
/// that is done at once and leaves something holding its output does not hold the turn. Seen with a limit of
/// two seconds and a `git` whose fetch leaves a `sleep` of 47 seconds behind.
#[test]
fn the_clocks_fetch_runs_under_the_rooms_git_limit() {
    let held = with_git("fetch-held");
    assert!(
        held.contains("did not finish in 2 seconds and was ended"),
        "{held}"
    );
    assert!(held.contains("REFS 0"), "{held}");
    // Three turns, each ended at its limit, and none of them waited out.
    assert!(held.contains("ITEM Abandoned attempts 3"), "{held}");
    assert!(took(&held) < 40, "{held}");
    let all = std::process::Command::new("ps")
        .args(["-Ao", "command="])
        .output()
        .unwrap();
    let left = String::from_utf8_lossy(&all.stdout)
        .lines()
        .filter(|command| command.trim() == "sleep 47.251")
        .count();
    assert_eq!(left, 0, "what the fetch started is still running");
}

/// The inner half of the test below, and nothing by itself: a clock whose look at the machine's processes
/// starts to fail part of the way through a run. `YAK_INNER_PS_DIR` names a directory that is first on this
/// process's search path; a `ps` is put there that is the real one until a file named `ps-fails` appears in a
/// sandbox of the room's, and fails from then on.
#[test]
fn inner_a_clock_that_can_no_longer_look_at_its_processes() {
    let Some(dir) = std::env::var_os("YAK_INNER_PS_DIR") else {
        return;
    };
    let mode = std::env::var("YAK_INNER_PS_MODE").unwrap();
    let mut world = World::new(0);
    // A short lease: a clock that went on where it should have stopped would leave an item waiting out its
    // lease, and this run would wait with it.
    world.room.set_lease_secs(2).unwrap();
    let room = world.room_dir.display().to_string();
    let wrapper = std::path::Path::new(&dir).join("ps");
    fs::write(
        &wrapper,
        format!(
            "#!/bin/sh\nfor flag in '{room}'/turns/*/ps-fails '{room}'/turns/*/*/ps-fails \
             '{room}'/checks/.work-*/*/ps-fails; do\n  [ -e \"$flag\" ] && exit 2\ndone\n\
             for real in /bin/ps /usr/bin/ps; do [ -x \"$real\" ] && exec \"$real\" \"$@\"; done\nexit 2\n"
        ),
    )
    .unwrap();
    fs::set_permissions(&wrapper, fs::Permissions::from_mode(0o755)).unwrap();
    let breaks = ": > ps-fails; sleep 5";
    // The first item is the one whose run breaks the look; the second is an ordinary one that must not start.
    let (worker, first) = match mode.as_str() {
        "plain" => (world.script("fix.sh", FIX), "sh check.sh 1".to_string()),
        "worker" => (
            world.script("breaks.sh", &format!("#!/bin/sh\n{breaks}\n")),
            "sh check.sh 1".to_string(),
        ),
        // Only on the fix, so that freezing it on the base and on the wrong commit is undisturbed.
        "check" => (
            world.script("fix.sh", FIX),
            format!("if grep -qx 42 answer1.txt; then {breaks}; fi; sh check.sh 1"),
        ),
        "freeze" => (
            world.script("fix.sh", FIX),
            format!("{breaks}; sh check.sh 1"),
        ),
        other => panic!("unknown mode {other}"),
    };
    world.add_check("answer 1 is 42", &first, &["check.sh"]);
    world.add(2);

    // Names are printed as they are, with the id of the first run's attempt written `A`.
    let report = |world: &World,
                  label: &str,
                  result: Result<(), ClockError>,
                  events: &[Event],
                  attempt: &Option<String>| {
        let lettered = |name: String| match attempt {
            Some(id) => name.replace(id.as_str(), "A"),
            None => name,
        };
        match result {
            Ok(()) => println!("{label} OK"),
            Err(ClockError::Unrecovered { record, why }) => {
                println!("{label} UNRECOVERED {} BECAUSE {why}", lettered(record))
            }
            Err(e) => println!("{label} ERROR {e}"),
        }
        println!("{label} STARTED {}", started(events).len());
        let named = |dir: &str| {
            let mut names: Vec<String> = fs::read_dir(world.room_dir.join(dir))
                .into_iter()
                .flatten()
                .flatten()
                .map(|e| lettered(e.file_name().to_string_lossy().into_owned()))
                .collect();
            names.sort();
            names
        };
        println!("{label} TURNS {:?}", named("turns"));
        let work: Vec<String> = named("checks")
            .into_iter()
            .filter(|name| name.starts_with(".work-"))
            .map(|name| {
                let kind = if name.ends_with(".pid") {
                    "record"
                } else {
                    "directory"
                };
                // What a check's work directory holds: its sandbox, by the first part of its name.
                let inside: Vec<String> = fs::read_dir(world.room_dir.join("checks").join(&name))
                    .into_iter()
                    .flatten()
                    .flatten()
                    .map(|e| e.file_name().to_string_lossy().into_owned())
                    .filter(|n| !n.contains('.'))
                    .map(|n| n.split('-').next().unwrap_or_default().to_string())
                    .collect();
                format!("{kind}{inside:?}")
            })
            .collect();
        println!("{label} WORK {work:?}");
        if let Some(id) = attempt {
            let inside = fs::read_dir(world.room_dir.join("turns").join(format!("{id}.check")))
                .into_iter()
                .flatten()
                .flatten()
                .filter(|e| !e.file_name().to_string_lossy().contains('.'))
                .count();
            println!("{label} CHECK-SANDBOXES {inside}");
        }
        let states: Vec<ItemState> = world
            .items
            .iter()
            .map(|id| world.room.item(id).unwrap().state)
            .collect();
        println!("{label} ITEMS {states:?}");
    };
    let (result, events) = world.run(&[&worker], Mode::OnceThrough, NEVER, TURN_SECS);
    let attempt = started(&events).first().map(|turn| turn.1.0.clone());
    report(&world, "FIRST", result, &events, &attempt);
    if mode != "plain" {
        // A clock started again while the look still fails finds the record, and stops the same way.
        let (result, events) = world.run(&[&worker], Mode::OnceThrough, NEVER, TURN_SECS);
        report(&world, "AGAIN", result, &events, &attempt);
    }
}

/// A run ends when the room has seen that every process it started is gone. When that cannot be seen (here the
/// look at the machine's processes starts to fail) the run may still be going, and the clock stops: it removes
/// nothing of that run, neither its record nor its sandbox, and starts no other turn. That holds for a
/// worker's run, for a check's and for a check being frozen. A clock started again finds the record and stops
/// in the same way until the run can be ended.
#[test]
fn a_run_that_cannot_be_confirmed_ended_stops_the_clock_with_everything_in_place() {
    let under = |mode: &str| {
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path().canonicalize().unwrap();
        let mut path = dir.clone().into_os_string();
        path.push(":/usr/bin:/bin:/usr/sbin:/sbin");
        let out = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "inner_a_clock_that_can_no_longer_look_at_its_processes",
                "--nocapture",
            ])
            .env("YAK_INNER_PS_DIR", &dir)
            .env("YAK_INNER_PS_MODE", mode)
            .env("PATH", path)
            .env_remove("YAK_JAIL")
            .env_remove("YAK_SUPERVISION")
            .output()
            .unwrap();
        let printed = String::from_utf8_lossy(&out.stdout).into_owned();
        assert!(
            printed.contains("FIRST ITEMS "),
            "{mode}: the inner run did not report: {printed} {}",
            String::from_utf8_lossy(&out.stderr)
        );
        printed
    };
    // The control: with the same `ps` in the way and nothing breaking it, both items pass and nothing is left.
    let plain = under("plain");
    assert!(plain.contains("FIRST OK"), "{plain}");
    assert!(plain.contains("FIRST STARTED 2"), "{plain}");
    assert!(plain.contains("FIRST TURNS []"), "{plain}");
    assert!(
        plain.contains("FIRST ITEMS [PassedVerified, PassedVerified]"),
        "{plain}"
    );

    // A worker's run.
    let worker = under("worker");
    assert!(
        worker.contains("FIRST UNRECOVERED turns/A.pid BECAUSE "),
        "{worker}"
    );
    assert!(worker.contains("FIRST STARTED 1"), "{worker}");
    let turns = worker
        .lines()
        .find(|l| l.starts_with("FIRST TURNS "))
        .unwrap();
    assert!(
        turns.contains("\"A\"") && turns.contains("\"A.pid\""),
        "{worker}"
    );
    assert!(worker.contains("FIRST ITEMS [Leased, Open]"), "{worker}");
    assert!(
        worker.contains("AGAIN UNRECOVERED turns/A.pid BECAUSE "),
        "{worker}"
    );
    assert!(worker.contains("AGAIN STARTED 0"), "{worker}");
    let again = worker
        .lines()
        .find(|l| l.starts_with("AGAIN TURNS "))
        .unwrap();
    assert_eq!(
        again.strip_prefix("AGAIN "),
        turns.strip_prefix("FIRST "),
        "{worker}"
    );

    // A check's run: the worker's sandbox, the check's own and the check's record all stay.
    let check = under("check");
    assert!(
        check.contains("FIRST UNRECOVERED turns/A.check.pid BECAUSE "),
        "{check}"
    );
    assert!(check.contains("FIRST STARTED 1"), "{check}");
    let turns = check
        .lines()
        .find(|l| l.starts_with("FIRST TURNS "))
        .unwrap();
    for name in ["\"A\"", "\"A.check\"", "\"A.check.pid\""] {
        assert!(turns.contains(name), "{name}: {check}");
    }
    assert!(check.contains("FIRST CHECK-SANDBOXES 1"), "{check}");
    assert!(check.contains("FIRST ITEMS [Checking, Open]"), "{check}");
    assert!(
        check.contains("AGAIN UNRECOVERED turns/A.check.pid BECAUSE "),
        "{check}"
    );
    assert!(check.contains("AGAIN STARTED 0"), "{check}");

    // A check being frozen: its work directory, the sandbox in it and its record all stay, and no turn starts.
    let freeze = under("freeze");
    assert!(
        freeze.contains("FIRST UNRECOVERED checks/.work-") && freeze.contains(".pid BECAUSE "),
        "{freeze}"
    );
    assert!(freeze.contains("FIRST STARTED 0"), "{freeze}");
    assert!(
        freeze.contains("FIRST WORK [\"directory[\\\"check\\\"]\", \"record[]\"]"),
        "{freeze}"
    );
    assert!(freeze.contains("FIRST ITEMS [Draft, Draft]"), "{freeze}");
    assert!(
        freeze.contains("AGAIN UNRECOVERED checks/.work-"),
        "{freeze}"
    );
    assert!(freeze.contains("AGAIN STARTED 0"), "{freeze}");
}

/// With the jail or the watch on processes switched off, the clock runs script workers and no model: a model
/// writes code that the room then runs, and those two switches are what holds that code.
///
/// The search path here has no `claude` or `codex` on it. So where the switches allow a model, the clock stops
/// at the next thing it checks, that the program is there, and no model is started by this test whatever the
/// clock does.
#[test]
fn with_a_protection_switched_off_the_clock_runs_no_model_worker() {
    let under = |workers: &str, switches: &[(&str, &str)]| {
        let mut child = std::process::Command::new(std::env::current_exe().unwrap());
        child
            .args([
                "--exact",
                "inner_a_clock_under_the_rooms_switches",
                "--nocapture",
            ])
            .env("YAK_INNER_WORKERS", workers)
            .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
            .env_remove("YAK_JAIL")
            .env_remove("YAK_SUPERVISION");
        for (name, value) in switches {
            child.env(name, value);
        }
        let out = child.output().unwrap();
        let printed = String::from_utf8_lossy(&out.stdout).into_owned();
        assert!(
            printed.contains("RAN ") || printed.contains("REFUSED "),
            "the inner run did not report: {printed} {}",
            String::from_utf8_lossy(&out.stderr)
        );
        printed
    };
    for (switch, value) in [("YAK_JAIL", "off"), ("YAK_SUPERVISION", "best-effort")] {
        for workers in ["claude:opus", "FIX,codex:gpt-6.1-sol"] {
            let printed = under(workers, &[(switch, value)]);
            assert!(
                printed.contains("REFUSED ") && printed.contains(switch),
                "{switch} with {workers}: {printed}"
            );
        }
        // Script workers alone still run with it off: that is what the switch is for.
        let printed = under("FIX", &[(switch, value)]);
        assert!(printed.contains("RAN 1 turn"), "{switch}: {printed}");
    }
    // The control: with neither switch set, the refusal is the next check's, and names neither.
    let printed = under("claude:opus", &[]);
    assert!(
        printed.contains("REFUSED ") && printed.contains("not an executable program"),
        "{printed}"
    );
    assert!(!printed.contains("YAK_"), "{printed}");
}
