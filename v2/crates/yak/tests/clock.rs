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

/// After a restart the clock finds a dead clock's turn. It ends the run the pid file describes, when that run is
/// still the process it was; removes its sandbox, pid file and scratch; never fetches from that sandbox; and takes
/// the item again once the lease expires. A pid file whose number has gone to another process, or that describes
/// no run, is removed, and the process it names is left alone.
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
    // unwritable, a pid file for a run that is still going, and a check's scratch directory.
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
    let left = Orphan::start();
    let pid_file = |name: &str, text: String| fs::write(turns.join(name), text).unwrap();
    pid_file(
        &format!("{}.pid", dead.attempt.0),
        format!("{}\n{}\n", left.0, started_at(left.0)),
    );
    // Two pid files that describe no run of the room's: one whose number now belongs to a process that started
    // at another time, and one in the form written before the start time was kept.
    let reused = Orphan::start();
    pid_file(
        "a-reused.pid",
        format!("{}\nMon Jan 1 00:00:00 2001\n", reused.0),
    );
    let bare = Orphan::start();
    pid_file("a-bare.pid", bare.0.to_string());
    fs::create_dir(turns.join(format!("{}.check", dead.attempt.0))).unwrap();
    // And a freeze's scratch clone in checks/.
    let freeze_scratch = world.room_dir.join("checks").join(".work-1-2-3");
    fs::create_dir_all(freeze_scratch.join("clone")).unwrap();

    let fix = world.script("fix.sh", FIX);
    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    let ended = wait_until(Instant::now() + Duration::from_secs(2), || !left.alive());
    let spared = [reused.alive(), bare.alive()];
    result.unwrap();
    assert!(ended, "the dead clock's run was left going");
    assert_eq!(
        spared,
        [true, true],
        "the clock signalled a process no pid file described"
    );

    let cleared: Vec<&Event> = events
        .iter()
        .filter(|e| matches!(e, Event::Cleared { .. }))
        .collect();
    assert_eq!(cleared.len(), 6, "{cleared:?}");
    assert!(!freeze_scratch.exists());
    for (name, ended) in [
        (format!("turns/{}.pid", dead.attempt.0), true),
        ("turns/a-reused.pid".to_string(), false),
        ("turns/a-bare.pid".to_string(), false),
    ] {
        assert!(
            cleared.contains(&&Event::Cleared { name, ended }),
            "{cleared:?}"
        );
    }
    // The file that describes no run is said to be one, and nothing else is called a problem: only pid files
    // are read as descriptions of runs.
    let problems: Vec<&Event> = events
        .iter()
        .filter(|e| matches!(e, Event::Problem { .. }))
        .collect();
    assert!(
        matches!(problems[..], [Event::Problem { item: None, what }] if what.contains("a-bare.pid")),
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
