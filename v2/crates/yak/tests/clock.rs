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

fn assert_measured(world: &World, events: &[Event], ended: room::Ended) {
    let attempts = started(events);
    assert!(!attempts.is_empty());
    for (_, attempt, _, _) in attempts {
        let m = world
            .room
            .measured(&attempt)
            .unwrap()
            .expect("every turn is measured");
        assert_eq!(m.ended, ended);
        assert_eq!(
            m.active_ms,
            m.sandbox_ms + m.worker_ms + m.seal_ms + m.bring_ms + m.check_ms.unwrap_or(0)
        );
        assert!(m.sandbox_ms > 0);
        assert!(m.worker_ms > 0);
    }
}

/// Off unless asked for: a caller that sets nothing gets the prompt as it was.
#[test]
fn a_clock_gives_no_turn_a_line_of_its_own_unless_asked() {
    assert!(!Options::default().own_prompts);
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn every_way_a_turn_ends_leaves_a_measured_record() {
    for (body, limit, ended) in [
        (FIX.to_string(), TURN_SECS, room::Ended::Exited),
        (
            "#!/bin/sh\necho 41 > answer1.txt\ngit commit -qam wrong\n".into(),
            TURN_SECS,
            room::Ended::Exited,
        ),
        ("#!/bin/sh\nexit 0\n".into(), TURN_SECS, room::Ended::Exited),
        (format!("{FIX}sleep 600\n"), 1, room::Ended::TimedOut),
        (
            format!("{FIX}mv .git .git-old\nln -s .git-old .git\n"),
            TURN_SECS,
            room::Ended::Exited,
        ),
        (
            "#!/bin/sh\nkill -TERM $$\n".into(),
            TURN_SECS,
            room::Ended::Signalled,
        ),
    ] {
        let mut world = World::new(1);
        let _bound = StopsWithin::for_a_test(&world.room_dir);
        let script = world.script("worker.sh", &body);
        let (result, events) = world.run(&[&script], Mode::OnceThrough, NEVER, limit);
        result.unwrap();
        assert_measured(&world, &events, ended);
        if body == "#!/bin/sh\nexit 0\n" {
            // A turn that hands in nothing is still checked, on its base, and the room really spent that time:
            // it is in the turn's active seconds.
            let m = world
                .room
                .measured(&started(&events)[0].1)
                .unwrap()
                .unwrap();
            let check = m.check_ms.expect("the base was checked");
            assert_eq!(
                m.active_ms,
                m.sandbox_ms + m.worker_ms + m.seal_ms + m.bring_ms + check
            );
        }
        if ended == room::Ended::TimedOut {
            let attempt = &started(&events)[0].1;
            let m = world.room.measured(attempt).unwrap().unwrap();
            assert!(!m.tokens.complete);
            assert_eq!(world.room.walk(attempt).unwrap().len(), 1);
            assert!(m.worker_ms >= 1000);
        }
    }
    // These event-driven tests own a stop and also assert the measured records.
    stop_ends_a_running_worker();
    a_lease_that_goes_stale_mid_turn_is_left_to_expire();
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_turn_with_no_steps_still_has_a_record() {
    let mut world = World::new(1);
    let script = world.script("silent.sh", "#!/bin/sh\nexit 0\n");
    let (result, events) = world.run(&[&script], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    assert_measured(&world, &events, room::Ended::Exited);
    for (_, attempt, _, _) in started(&events) {
        let m = world.room.measured(&attempt).unwrap().unwrap();
        assert_eq!(m.steps_seen, 0);
        assert_eq!(m.unknown_steps, 0);
        assert!(!m.tokens.complete);
    }
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_turn_that_cannot_make_a_sandbox_is_measured_as_not_run() {
    let mut world = World::new(1);
    let worker = world.script("idle.sh", "#!/bin/sh\nexit 0\n");
    let _bound = StopsWithin::for_a_test(&world.room_dir);
    let repo = world.repo.clone();
    let removed = world.scratch("removed-repo");
    let stop = world.room_dir.join("STOP");
    let mut events = Vec::new();
    let mut report = |event: &Event| {
        if matches!(event, Event::Started { .. }) {
            fs::rename(&repo, &removed).unwrap();
            fs::write(&stop, "").unwrap();
        }
        events.push(event.clone());
    };
    clock::run_with(
        &mut world.room,
        &[worker],
        Mode::OnceThrough,
        &mut Fixed(NEVER),
        Options {
            report: Some(&mut report),
            ..Options::default()
        },
    )
    .unwrap();
    let attempt = &started(&events)[0].1;
    let m = world.room.measured(attempt).unwrap().unwrap();
    assert_eq!(m.ended, room::Ended::NotRun);
    assert_eq!(
        (m.worker_ms, m.seal_ms, m.bring_ms, m.check_ms),
        (0, 0, 0, None)
    );
    assert_eq!(m.active_ms, m.sandbox_ms);
    assert_eq!(m.exit_code, None);
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_turns_changes_are_the_difference_between_its_base_and_its_commit() {
    let mut world = World::new(1);
    // `a b.txt` is not a plain path: it is counted, not kept.
    let body = "#!/bin/sh\necho 42 > answer1.txt\necho new > added.txt\necho new > 'a b.txt'\nrm answer2.txt\ngit add -A\ngit commit -qm change\n";
    let script = world.script("changes.sh", body);
    let (result, events) = world.run(&[&script], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    let attempt = &started(&events)[0].1;
    let m = world.room.measured(attempt).unwrap().unwrap();
    assert_eq!(m.unknown_changes, 1);
    let changes = world.room.changes(attempt).unwrap();
    assert_eq!(
        changes,
        vec![
            room::ChangedFile {
                path: "added.txt".into(),
                change: room::Change::Added
            },
            room::ChangedFile {
                path: "answer1.txt".into(),
                change: room::Change::Changed
            },
            room::ChangedFile {
                path: "answer2.txt".into(),
                change: room::Change::Removed
            },
        ]
    );
}

/// At most `MAX_CHANGES` changed files are kept for one turn; the rest are counted.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_turn_that_changes_more_files_than_are_kept_counts_the_rest() {
    let mut world = World::new(1);
    let body = format!(
        "#!/bin/sh\ni=0\nwhile [ $i -lt {} ]; do : > \"f$i.txt\"; i=$((i + 1)); done\ngit add -A\n\
         git commit -qm many\n",
        room::limits::MAX_CHANGES + 1
    );
    let script = world.script("many.sh", &body);
    let (result, events) = world.run(&[&script], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    let attempt = &started(&events)[0].1;
    assert_eq!(
        world.room.changes(attempt).unwrap().len(),
        room::limits::MAX_CHANGES
    );
    assert_eq!(
        world
            .room
            .measured(attempt)
            .unwrap()
            .unwrap()
            .unknown_changes,
        1
    );
}

/// The check's work directory that has begun to wait, by the file it leaves there: `turns/<attempt>.check/*/
/// waiting`.
fn waiting_check(turns: &std::path::Path) -> Option<std::path::PathBuf> {
    fs::read_dir(turns)
        .ok()?
        .flatten()
        .filter(|e| e.file_name().to_string_lossy().ends_with(".check"))
        .flat_map(|e| fs::read_dir(e.path()).into_iter().flatten().flatten())
        .map(|e| e.path().join("waiting"))
        .find(|flag| flag.exists())
}

/// How a worker ended is the worker's own: a lease lost after it ended (here, while its commit is checked)
/// leaves it as the worker left it, though the turn ends as a lost lease. The lease is lost as the room sees a
/// lease lost: the item's lease has moved on, so the verdict is refused.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_worker_that_ran_out_of_time_stays_so_when_the_lease_is_lost_during_the_check() {
    let mut world = World::new(0);
    // The check waits on the turn's commit only (freezing it runs it on the base and the wrong commit), says
    // so, and goes on once this test has taken the lease away.
    world.add_check(
        "answer 1 is 42",
        "if grep -qx 42 answer1.txt; then : > waiting; until [ -e go ]; do sleep 0.1; done; fi; sh check.sh 1",
        &["check.sh"],
    );
    let late = world.script("late.sh", &format!("{FIX}sleep 600\n"));
    let _bound = StopsWithin::for_a_test(&world.room_dir);
    let turns = world.room_dir.join("turns");
    let store = world.room_dir.join("room.sqlite3");
    let item = world.items[0].0.clone();
    let stop = world.room_dir.join("STOP");
    let taker = {
        let stop = stop.clone();
        thread::spawn(move || {
            let mut waiting = None;
            wait_until(Instant::now() + Duration::from_secs(90), || {
                waiting = waiting_check(&turns);
                waiting.is_some() || stop.exists()
            });
            let Some(waiting) = waiting else {
                return false;
            };
            let moved = std::process::Command::new("python3")
                .args([
                    "-I",
                    "-c",
                    "import sqlite3, sys\n\
                     c = sqlite3.connect(sys.argv[1], timeout=30)\n\
                     c.execute('UPDATE items SET lease_no = lease_no + 1 WHERE id = ?', (sys.argv[2],))\n\
                     c.commit()\n",
                ])
                .arg(&store)
                .arg(&item)
                .status()
                .unwrap();
            assert!(moved.success());
            fs::write(waiting.with_file_name("go"), "").unwrap();
            true
        })
    };
    // The item's lease has moved on to one nobody holds, so the room is stopped when the turn ends.
    let mut after_one = |e: &Event| {
        if matches!(e, Event::Ended { .. }) {
            fs::write(&stop, "").unwrap();
        }
    };
    let (result, events) = world.run_hooked(&[&late], Mode::OnceThrough, NEVER, 2, &mut after_one);
    assert!(taker.join().unwrap(), "the check never began to wait");
    result.unwrap();
    assert_eq!(outcomes(&events), [Outcome::LeaseLost]);
    let m = world
        .room
        .measured(&started(&events)[0].1)
        .unwrap()
        .unwrap();
    assert_eq!(m.ended, room::Ended::TimedOut);
    assert!(matches!(m.exit_code, Some(code) if code != 0), "{m:?}");
    assert!(m.check_ms.is_some(), "{m:?}");
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_stop_during_the_changed_file_list_leaves_no_ref_or_check() {
    let Some(dir) = std::env::var_os("YAK_DIFF_TEST_DIR") else {
        let d = tempfile::tempdir().unwrap();
        let wrapper = d.path().join("git");
        let marker = d.path().join("diff-started");
        fs::write(&wrapper, format!("#!/bin/sh\nfor arg in \"$@\"; do\n  if [ \"$arg\" = diff ]; then\n    : > '{}'\n    while :; do sleep 1; done\n  fi\ndone\nexec /usr/bin/git \"$@\"\n", marker.display())).unwrap();
        fs::set_permissions(&wrapper, fs::Permissions::from_mode(0o755)).unwrap();
        let path = std::env::join_paths(
            std::iter::once(d.path().to_path_buf())
                .chain(std::env::split_paths(&std::env::var_os("PATH").unwrap())),
        )
        .unwrap();
        let out = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "a_stop_during_the_changed_file_list_leaves_no_ref_or_check",
                "--include-ignored",
                "--nocapture",
            ])
            .env("YAK_DIFF_TEST_DIR", d.path())
            .env("PATH", path)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}\n{}",
            String::from_utf8_lossy(&out.stdout),
            String::from_utf8_lossy(&out.stderr)
        );
        assert!(marker.is_file(), "the inner run never started the diff");
        return;
    };
    let mut world = World::new(1);
    let worker = world.script("fix.sh", FIX);
    let _bound = StopsWithin::for_a_test(&world.room_dir);
    let stop = world.room_dir.join("STOP");
    let marker = std::path::PathBuf::from(dir).join("diff-started");
    let stopper = thread::spawn(move || {
        wait_until(Instant::now() + Duration::from_secs(60), || {
            marker.exists() || stop.exists()
        });
        let began = marker.exists();
        fs::write(stop, "").unwrap();
        began
    });
    let (result, events) = world.run(&[&worker], Mode::OnceThrough, NEVER, TURN_SECS);
    assert!(stopper.join().unwrap(), "the diff never started");
    result.unwrap();
    assert_eq!(outcomes(&events), [Outcome::Stopped]);
    assert!(world.room_refs().is_empty());
    let turn = world.room.turns(&world.items[0]).unwrap().remove(0);
    assert_eq!(turn.passed, None);
    // The stop came after the worker had ended, by itself: how it ended is its own.
    assert_eq!(turn.measured.unwrap().ended, room::Ended::Exited);
}

/// A step's times count from the turn's start, the moment the room starts to make its sandbox, as the record's
/// durations do. Seen with a sandbox that takes two seconds to make, from a git whose fetch of the turn's base
/// waits that long: the step, seen once the worker runs, is seen after the sandbox was made.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_steps_times_count_from_before_its_sandbox_was_made() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().canonicalize().unwrap();
    let wrapper = dir.join("git");
    // Only the fetch that makes the turn's own sandbox, `turns/<attempt>`: not a check's, not a freeze's.
    fs::write(
        &wrapper,
        "#!/bin/sh\ncase \" $* \" in\n*/turns/a????????????\" -c protocol.version=2 \"*) sleep 2;;\nesac\n\
         exec /usr/bin/git \"$@\"\n",
    )
    .unwrap();
    fs::set_permissions(&wrapper, fs::Permissions::from_mode(0o755)).unwrap();
    let mut path = dir.clone().into_os_string();
    path.push(":/usr/bin:/bin:/usr/sbin:/sbin");
    let out = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "inner_a_turn_whose_sandbox_is_slow_to_make",
            "--nocapture",
        ])
        .env("YAK_INNER_SLOW_SANDBOX", "1")
        .env("PATH", path)
        .output()
        .unwrap();
    let printed = String::from_utf8_lossy(&out.stdout).into_owned();
    let number = |label: &str| -> u64 {
        let line = printed
            .lines()
            .find(|l| l.starts_with(label))
            .unwrap_or_else(|| {
                panic!(
                    "the inner run did not report {label}: {printed} {}",
                    String::from_utf8_lossy(&out.stderr)
                )
            });
        line[label.len()..].trim().parse().unwrap()
    };
    let (sandbox_ms, seen_ms) = (number("SANDBOX_MS "), number("SEEN_MS "));
    // The control: the sandbox did take its two seconds.
    assert!(sandbox_ms >= 2_000, "{printed}");
    assert!(seen_ms >= sandbox_ms, "{printed}");
    assert!(printed.contains("PARTS ADD UP true"), "{printed}");
}

#[test]
fn inner_a_turn_whose_sandbox_is_slow_to_make() {
    if std::env::var_os("YAK_INNER_SLOW_SANDBOX").is_none() {
        return;
    }
    let mut world = World::new(1);
    let fix = world.script("fix.sh", FIX);
    let _bound = StopsWithin::for_a_test(&world.room_dir);
    let (result, events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    let attempt = &started(&events)[0].1;
    let m = world.room.measured(attempt).unwrap().unwrap();
    let walk = world.room.walk(attempt).unwrap();
    println!("SANDBOX_MS {}", m.sandbox_ms);
    println!("SEEN_MS {}", walk[0].seen_ms.unwrap());
    println!(
        "PARTS ADD UP {}",
        m.active_ms
            == m.sandbox_ms + m.worker_ms + m.seal_ms + m.bring_ms + m.check_ms.unwrap_or(0)
    );
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_second_look_is_timed_beside_the_turn() {
    let mut world = World::new(1);
    let script = world.script("fix.sh", FIX);
    let (result, events) = world.run(&[&script], Mode::OnceThrough, ALWAYS, TURN_SECS);
    result.unwrap();
    assert_measured(&world, &events, room::Ended::Exited);
    let m = world
        .room
        .measured(&started(&events)[0].1)
        .unwrap()
        .unwrap();
    assert!(m.recheck_ms.unwrap() > 0);
    assert!(matches!(
        outcomes(&events)[0],
        Outcome::Judged {
            recheck: Some(_),
            ..
        }
    ));
}

fn state(world: &World, n: usize) -> ItemState {
    world.room.item(&world.items[n]).unwrap().state
}

// The six tests of the plan.

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
fn stop_ends_a_running_worker() {
    let mut world = World::new(2);
    // It ignores SIGTERM, and so does its child, so only the SIGKILL after the grace ends them.
    let slow = world.script("slow.sh", "#!/bin/sh\ntrap '' TERM\nsleep 600\n");
    let turns = world.room_dir.join("turns");
    let room_dir = world.room_dir.clone();
    // Only the stopper stops this clock, and it does so once a worker's record is there. If none appears, the
    // clock is stopped all the same, and the test fails below and does not wait for ever.
    let _bound = StopsWithin::for_a_test(&world.room_dir);
    let stopper = thread::spawn(move || {
        let deadline = Instant::now() + Duration::from_secs(60);
        let stop = room_dir.join("STOP");
        let mut pid_file = None;
        // It waits for the record, and no longer once the room has been stopped without one.
        wait_until(deadline, || {
            pid_file = fs::read_dir(&turns).ok().and_then(|entries| {
                entries
                    .flatten()
                    .map(|e| e.path())
                    .find(|p| p.extension().is_some_and(|x| x == "pid"))
            });
            pid_file.is_some() || stop.exists()
        });
        let pid_file = pid_file.expect("a worker's record appears before the room is stopped");
        let group = read_group(&pid_file, deadline);
        fs::write(stop, "").unwrap();
        (group, Instant::now())
    });
    let (result, events) = world.run(&[&slow], Mode::Forever, NEVER, TURN_SECS);
    let returned = Instant::now();
    for event in &events {
        if let Event::NotFrozen { reason, .. } = event {
            eprintln!("NOT FROZEN {reason}");
        }
    }
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
    assert_measured(&world, &events, room::Ended::Stopped);
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn workers_take_turns() {
    let mut world = World::new(4);
    let a = world.script("a.sh", FIX);
    let b = world.script("b.sh", FIX);
    let (result, events) = world.run(&[&a, &b], Mode::OnceThrough, NEVER, TURN_SECS);
    result.unwrap();
    let workers: Vec<String> = started(&events).into_iter().map(|s| s.3).collect();
    // When this fails, what the clock did is the first thing wanted, so it is said with the failure.
    assert_eq!(workers, [a.clone(), b.clone(), a, b], "{events:#?}");
    for n in 0..4 {
        assert_eq!(state(&world, n), ItemState::PassedVerified);
    }
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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

/// A lease the room calls stale (here a lease of one second, so the first renewal is too late) ends the turn:
/// nothing is handed in and no ref is made, and the next pass returns the item, until it is abandoned. A
/// worker that had started is ended and not left to run.
///
/// On a busy machine a lease of one second can run out before the worker has started, and then there is no
/// run to see. So this test does not ask that one was seen. The test after the next shows a lease running
/// out while the worker runs, by holding the clock still, where nothing is left to how busy the machine is.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
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
    for group in groups {
        assert!(!group_alive(group), "the group {group} is still alive");
    }
    // Every turn is measured. One whose lease ran out before its worker's program had started says its worker
    // did not run; every other says the lease was lost while its worker ran. Which it is depends on how busy
    // the machine is, so neither is asked for by itself here. (A turn that did not run can still hold time in
    // the worker's part: the room had begun to start it.)
    let attempts = started(&events);
    assert_eq!(attempts.len(), MAX_ATTEMPTS as usize);
    for (_, attempt, _, _) in attempts {
        let m = world
            .room
            .measured(&attempt)
            .unwrap()
            .expect("every turn is measured");
        assert_eq!(
            m.active_ms,
            m.sandbox_ms + m.worker_ms + m.seal_ms + m.bring_ms + m.check_ms.unwrap_or(0),
            "{m:?}"
        );
        match m.ended {
            room::Ended::LeaseLost => assert!(m.worker_ms > 0, "{m:?}"),
            room::Ended::NotRun => assert_eq!(m.exit_code, None, "{m:?}"),
            _ => panic!("a turn whose lease went stale is recorded as {m:?}"),
        }
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
#[ignore = "needs the room: a list of processes and a jail"]
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
    // The dead clock's lease is the short one, so the test does not wait long for it. The turn that follows
    // gets one it cannot lose on a busy machine.
    world.room.set_lease_secs(30).unwrap();

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
#[ignore = "needs the room: a list of processes and a jail"]
fn a_record_that_cannot_be_read_stops_the_clock_with_everything_in_place() {
    let mut world = World::new(1);
    assert_eq!(clock::freeze_drafts(&mut world.room).unwrap(), 1);
    world.room.set_lease_secs(2).unwrap();
    let dead = world
        .room
        .take("script:/dead-clock", now())
        .unwrap()
        .unwrap();
    world.room.set_lease_secs(30).unwrap();
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
#[ignore = "needs the room: a list of processes and a jail"]
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

/// A turn's record is written before its sandbox is removed, so that a clock that dies removing it leaves the
/// record. Seen when the removal is refused: at the moment the clock says so, the record is in the store.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_turns_record_is_written_before_its_sandbox_is_removed() {
    let mut world = World::new(1);
    let slow = world.script("slow.sh", "#!/bin/sh\nsleep 3\n");
    let _bound = StopsWithin::for_a_test(&world.room_dir);
    let turns = world.room_dir.join("turns");
    let moved = world.scratch("moved-away");
    // As in the test above: the sandbox is moved away while its worker runs, and a directory put in its place.
    let swapper = thread::spawn(move || {
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
    });
    let room_dir = world.room_dir.clone();
    let stop = world.room_dir.join("STOP");
    let mut attempt = None;
    let mut measured_then = None;
    // On the clock's own thread, as it says each thing: the store is read where the removal was refused.
    let mut hook = |e: &Event| match e {
        Event::Started { attempt: a, .. } => attempt = Some(a.clone()),
        Event::Problem { what, .. } if what.contains("the sandbox was not removed") => {
            let reader = room::Room::open_read_only(&room_dir).unwrap();
            measured_then = Some(
                reader
                    .measured(attempt.as_ref().unwrap())
                    .unwrap()
                    .is_some(),
            );
        }
        // One turn is enough.
        Event::Ended { .. } => fs::write(&stop, "").unwrap(),
        _ => {}
    };
    let (result, events) =
        world.run_hooked(&[&slow], Mode::OnceThrough, NEVER, TURN_SECS, &mut hook);
    swapper.join().unwrap();
    result.unwrap();
    assert_eq!(measured_then, Some(true), "{events:?}");
}

/// A scratch directory is the room's to remove only if a run of the room's made it. One that was at its path
/// before any run is not: the sandbox's own removal leaves it, and so does the clock's tidying after the turn.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_scratch_directory_the_room_did_not_make_is_left_where_it_is() {
    // On a disk where capital and small letters name the same file, a directory kept as `<attempt>.SCRATCH` is
    // at the scratch directory's place too, and is left like one kept in small letters.
    let probe = tempfile::tempdir().unwrap();
    fs::create_dir(probe.path().join("Letters")).unwrap();
    let folds = probe.path().join("letters").is_dir();
    let endings: &[&str] = if folds {
        &["scratch", "SCRATCH"]
    } else {
        &["scratch"]
    };
    for ending in endings {
        let mut world = World::new(1);
        let fix = world.script("fix.sh", FIX);
        let turns = world.room_dir.join("turns");
        let mut canaries = Vec::new();
        let mut plant = |e: &Event| {
            if let Event::Started { attempt, .. } = e {
                let scratch = turns.join(format!("{}.{ending}", attempt.0));
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
                "{ending}: {events:?}"
            );
        }
        // Each is said, and nothing else of any turn is left.
        let said = events
            .iter()
            .filter(
                |e| matches!(e, Event::Problem { what, .. } if what.contains("the sandbox was not removed")),
            )
            .count();
        assert_eq!(said, canaries.len(), "{ending}: {events:?}");
        let mut names: Vec<String> = canaries
            .iter()
            .map(|p| p.file_name().unwrap().to_string_lossy().into_owned())
            .collect();
        names.sort();
        assert_eq!(world.turns(), names, "{ending}");
    }
}

/// What is found at the scratch directory's place need not be a directory. A file there is left too, and a
/// file can go by a second name in the same directory: both names are left, whichever the clock meets first.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_file_at_the_scratch_directorys_place_is_left_under_every_name_it_has() {
    let mut world = World::new(1);
    let fix = world.script("fix.sh", FIX);
    let turns = world.room_dir.join("turns");
    let mut planted = Vec::new();
    let mut plant = |e: &Event| {
        if let Event::Started { attempt, .. } = e {
            fs::create_dir_all(&turns).unwrap();
            let at = turns.join(format!("{}.scratch", attempt.0));
            fs::write(&at, "KEEP").unwrap();
            // Two more names for the same file, one sorting before the attempt's and one after.
            for other in ["0-other-name", "zz-other-name"] {
                let _ = fs::hard_link(&at, turns.join(other));
            }
            planted.push(at);
        }
    };
    let (result, events) =
        world.run_hooked(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS, &mut plant);
    result.unwrap();
    assert!(!planted.is_empty());
    for at in &planted {
        assert_eq!(fs::read_to_string(at).unwrap(), "KEEP", "{events:?}");
    }
}

/// A check has a sandbox of its own, inside the check's work directory. If something else is at that sandbox's
/// path when the check is done, it is left, and the clock's tidying leaves the work directory that holds it.
/// No verdict is taken from that check: the item waits out its lease and is tried again. A recheck is a check
/// like any other, and what took its sandbox's place is left in the same way.
///
/// The third way is a scratch directory put beside the check's sandbox before its first run. With the jail on
/// that run cannot start, so the check fails for a reason of its own as well, and what the removal left is
/// still what the clock is told.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn what_took_a_checks_sandboxs_place_is_left_with_the_directory_that_holds_it() {
    for (which, rng, how) in [
        ("check", NEVER, "swap"),
        ("recheck", ALWAYS, "swap"),
        ("check", NEVER, "plant"),
    ] {
        let mut world = World::new(0);
        world.room.set_lease_secs(6).unwrap();
        // Slow only on the fix, so freezing it on the base and the wrong commit stays quick.
        let id = world.add_check(
            "answer 1 is 42, slowly",
            "if grep -qx 42 answer1.txt; then sleep 3; fi; sh check.sh 1",
            &["check.sh"],
        );
        let fix = world.script("fix.sh", FIX);
        let turns = world.room_dir.join("turns");
        let moved = world.scratch("moved-away");
        let meddler = thread::spawn(move || {
            // The sandbox of the first check of that kind: the one name without a dot in its work directory.
            // To take its place the check must be running, so its record is waited for; to plant a scratch
            // directory beside it no run may have started, so the directory alone is.
            let deadline = Instant::now() + Duration::from_secs(60);
            let holder_ending = format!(".{which}");
            let mut sandbox = None;
            while sandbox.is_none() && Instant::now() < deadline {
                let names: Vec<std::path::PathBuf> = fs::read_dir(&turns)
                    .into_iter()
                    .flatten()
                    .flatten()
                    .map(|e| e.path())
                    .collect();
                sandbox = names
                    .iter()
                    .filter(|p| p.to_string_lossy().ends_with(&holder_ending))
                    .filter(|holder| {
                        how == "plant"
                            || names.contains(&holder.with_extension(format!("{which}.pid")))
                    })
                    .flat_map(|holder| fs::read_dir(holder).into_iter().flatten().flatten())
                    .map(|e| e.path())
                    .find(|p| !p.file_name().unwrap().to_string_lossy().contains('.'));
                thread::sleep(Duration::from_millis(1));
            }
            let at = sandbox.expect("the check made a sandbox");
            if how == "plant" {
                let mut name = at.file_name().unwrap().to_os_string();
                name.push(".scratch");
                let scratch = at.with_file_name(name);
                fs::create_dir(&scratch).unwrap();
                fs::write(scratch.join("canary"), "KEEP").unwrap();
                return scratch;
            }
            // Well inside the check's three seconds.
            thread::sleep(Duration::from_secs(1));
            fs::rename(&at, &moved).unwrap();
            fs::create_dir(&at).unwrap();
            fs::write(at.join("canary"), "KEEP").unwrap();
            at
        });
        let (result, events) = world.run(&[&fix], Mode::OnceThrough, rng, TURN_SECS);
        let at = meddler.join().unwrap();
        result.unwrap();
        assert_eq!(
            fs::read_to_string(at.join("canary")).unwrap(),
            "KEEP",
            "{which}, {how}"
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
                "{how}: {ends:?}"
            );
            // The room went on: the lease ran out, and the next turn passed.
            assert!(passed(&ends[1]), "{how}: {ends:?}");
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
            "{which}, {how}"
        );
        assert!(holder.to_string_lossy().ends_with(&format!(".{which}")));
    }
}

/// What a check left is remembered also when the room's store fails while the check runs. The store's failure
/// ends the clock; it does not take the place of what the check said, and the clock's tidying on the way out
/// still leaves the directory that holds what was found.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn what_a_check_left_is_remembered_though_the_store_fails_meanwhile() {
    let mut world = World::new(0);
    world.room.set_lease_secs(6).unwrap();
    world.add_check(
        "answer 1 is 42, slowly",
        "if grep -qx 42 answer1.txt; then sleep 3; fi; sh check.sh 1",
        &["check.sh"],
    );
    let fix = world.script("fix.sh", FIX);
    let (turns, room_dir) = (world.room_dir.join("turns"), world.room_dir.clone());
    let moved = world.scratch("moved-away");
    let meddler = thread::spawn(move || {
        let deadline = Instant::now() + Duration::from_secs(60);
        let mut sandbox = None;
        assert!(wait_until(deadline, || {
            let record = fs::read_dir(&turns)
                .into_iter()
                .flatten()
                .flatten()
                .map(|e| e.path())
                .find(|p| p.to_string_lossy().ends_with(".check.pid"));
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
        thread::sleep(Duration::from_secs(1));
        let at = sandbox.unwrap();
        fs::rename(&at, &moved).unwrap();
        fs::create_dir(&at).unwrap();
        fs::write(at.join("canary"), "KEEP").unwrap();
        // And from here the store takes no write: the clock's next renewal fails.
        (at, StoreHeld::hold(&room_dir))
    });
    let (result, _events) = world.run(&[&fix], Mode::OnceThrough, NEVER, TURN_SECS);
    let (at, held) = meddler.join().unwrap();
    drop(held);
    assert!(
        matches!(result, Err(ClockError::Room(_))),
        "the clock did not end for its store: {result:?}"
    );
    assert_eq!(fs::read_to_string(at.join("canary")).unwrap(), "KEEP");
    let holder = at.parent().unwrap().file_name().unwrap();
    assert_eq!(world.turns(), [holder.to_string_lossy().into_owned()]);
}

/// When the clock stops at a run it cannot end, what stays is that run's: its record and its directories, and
/// every other directory, since nothing is removed. A run the clock had already ended by then is over, and its
/// record went as it ended.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
fn a_check_that_cannot_run_leaves_the_item_to_expire() {
    let mut world = World::new(1);
    // Long enough that a turn on a busy machine hands in before it runs out, short enough to wait out thrice.
    world.room.set_lease_secs(5).unwrap();
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
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
#[ignore = "needs the room: a list of processes and a jail"]
fn a_long_turn_keeps_its_lease() {
    use std::sync::Arc;
    use std::sync::atomic::{AtomicBool, Ordering};

    let mut world = World::new(0);
    // A lease of six seconds is renewed every two, and a worker and a check of seven seconds each outlast it.
    // Two seconds would do on a quiet machine and is lost on a busy one, where a second can pass unseen.
    world.room.set_lease_secs(6).unwrap();
    // Slow only on the fix, so freezing it on the base and the wrong commit stays quick.
    let id = world.add_check(
        "answer 1 is 42, slowly",
        "if grep -qx 42 answer1.txt; then sleep 7; fi; sh check.sh 1",
        &["check.sh"],
    );
    let fix = FIX.strip_prefix("#!/bin/sh\n").unwrap();
    let slow = world.script("slow.sh", &format!("#!/bin/sh\nsleep 7\n{fix}"));
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
#[ignore = "needs the room: a list of processes and a jail"]
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

/// A symbolic ref that names nothing is a name that is taken, though a listing of refs leaves it out. The turn
/// that would have made its ref there hands in nothing and fails, the symbolic ref is as it was, and the next
/// lease makes its own.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_symbolic_ref_that_names_nothing_is_a_name_that_is_taken() {
    let mut world = World::new(1);
    let id = world.items[0].clone();
    let taken = world.room_ref(&id, 1);
    git(
        &world.repo,
        &["symbolic-ref", &taken, "refs/heads/no-such-branch"],
    );
    // The control for what this is about: the listing does not show it.
    assert!(world.room_refs().is_empty());
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
        nothing.as_deref().unwrap().contains("is already there"),
        "{nothing:?}"
    );
    assert!(matches!(
        ends[1],
        Outcome::Judged {
            state: ItemState::PassedVerified,
            ..
        }
    ));
    // Still a symbolic ref, and still to the same name.
    assert_eq!(
        git(&world.repo, &["symbolic-ref", &taken]),
        "refs/heads/no-such-branch"
    );
    assert_eq!(world.room_refs(), [world.room_ref(&id, 2)]);
}

/// In `Forever`, the ceiling does not end the clock: it waits for the next day, and says so once.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn in_forever_the_ceiling_waits_and_says_so_once() {
    let mut world = World::new(2);
    world.room.set_ceiling(1, 1).unwrap();
    let fix = world.script("fix.sh", FIX);
    let stop = world.room_dir.join("STOP");
    // This clock is stopped once it has said the ceiling was reached. If it never says so, it is stopped all
    // the same, and the test fails below and does not wait for ever.
    let _bound = StopsWithin::for_a_test(&world.room_dir);
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
        Event::NotFrozen { reason, .. } => eprintln!("NOT FROZEN {reason}"),
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

/// Where a clock cannot look at processes (inside another program's sandbox, say) no check is frozen and no
/// turn starts. The two tests above whose clock only a helper stops must still end there. Found by the first
/// run with model workers: a worker ran these tests in its own sandbox, and they never ended.
///
/// Each is run here by itself with a `ps` that fails first on its search path. It fails, since nothing it
/// waits for can happen, and that is right. What is asked is that it ends.
#[test]
fn a_test_whose_clock_waits_for_work_ends_where_no_turn_can_start() {
    let dir = tempfile::tempdir().unwrap();
    let ps = dir.path().join("ps");
    fs::write(
        &ps,
        "#!/bin/sh\necho 'ps: Operation not permitted' >&2\nexit 1\n",
    )
    .unwrap();
    fs::set_permissions(&ps, fs::Permissions::from_mode(0o755)).unwrap();
    let path = std::env::join_paths(
        std::iter::once(dir.path().to_path_buf())
            .chain(std::env::split_paths(&std::env::var_os("PATH").unwrap())),
    )
    .unwrap();
    for name in [
        "stop_ends_a_running_worker",
        "in_forever_the_ceiling_waits_and_says_so_once",
    ] {
        // What a child prints goes to files and not through pipes: something that outlived a killed child and
        // still held a pipe would be waited for, with no end, in the one test that is here to show an end.
        let printed_at = dir.path().join(format!("{name}.out"));
        let said_at = dir.path().join(format!("{name}.err"));
        let mut child = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                name,
                "--exact",
                "--include-ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env("PATH", &path)
            .env("YAK_TEST_STOPS_WITHIN_SECS", "3")
            .stdin(std::process::Stdio::null())
            .stdout(fs::File::create(&printed_at).unwrap())
            .stderr(fs::File::create(&said_at).unwrap())
            .spawn()
            .unwrap();
        let deadline = Instant::now() + Duration::from_secs(90);
        let ended = wait_until(deadline, || child.try_wait().unwrap().is_some());
        if !ended {
            let _ = child.kill();
        }
        let status = child.wait().unwrap();
        let printed = format!(
            "{}\n{}",
            String::from_utf8_lossy(&fs::read(&printed_at).unwrap()),
            String::from_utf8_lossy(&fs::read(&said_at).unwrap())
        );
        assert!(ended, "{name} did not end where no turn can start");
        assert!(!status.success(), "{name} passed with a ps that fails");
        assert!(
            printed.contains("inspect processes:")
                || printed.contains("process inspection is unavailable"),
            "{name} did not report its failed look at processes: {printed}"
        );
    }
}

/// The stop a test owns: it stops the room at its limit, and never once it has been dropped.
#[test]
fn a_tests_own_stop_acts_at_its_limit_and_not_after_it_is_dropped() {
    let dir = tempfile::tempdir().unwrap();
    let stop = dir.path().join("STOP");
    let bound = StopsWithin::new(dir.path(), Duration::from_millis(200));
    assert!(wait_until(Instant::now() + Duration::from_secs(30), || {
        stop.exists()
    }));
    drop(bound);
    fs::remove_file(&stop).unwrap();
    // Dropped at once, long before its limit: its watcher has gone by the time `drop` returns, without having
    // stopped the room, and nothing is left that could stop it later.
    drop(StopsWithin::new(dir.path(), Duration::from_secs(5)));
    assert!(!stop.exists());
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
    // A worker that hands in a commit the repository had all along. A sandbox holds only what its base reaches,
    // so the worker cannot be pointed at a commit that lies elsewhere in the repository. It makes one that can
    // be made beforehand bit for bit: the same change, the turn's own name, fixed dates and the same word.
    const SAME_DATE: &str = "2026-01-01T00:00:00Z";
    let same = world.script(
        "same.sh",
        &format!(
            "#!/bin/sh\nfor f in answer*.txt; do echo 41 > \"$f\"; done\n\
             GIT_AUTHOR_DATE={SAME_DATE} GIT_COMMITTER_DATE={SAME_DATE} git commit -q -am same\n"
        ),
    );
    // That commit, made here in the item's repository without touching its files: the tree of the `wrong`
    // branch (every answer 41) on top of the base, by the name every turn commits under.
    let already = {
        let tree = git(
            &world.repo,
            &["rev-parse", &format!("{}^{{tree}}", world.wrong)],
        );
        let out = std::process::Command::new("git")
            .arg("-C")
            .arg(&world.repo)
            .args(["commit-tree", &tree, "-p", &world.base, "-m", "same"])
            .env("GIT_AUTHOR_NAME", "yak turn")
            .env("GIT_AUTHOR_EMAIL", "turn@yak.invalid")
            .env("GIT_COMMITTER_NAME", "yak turn")
            .env("GIT_COMMITTER_EMAIL", "turn@yak.invalid")
            .env("GIT_AUTHOR_DATE", SAME_DATE)
            .env("GIT_COMMITTER_DATE", SAME_DATE)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        String::from_utf8(out.stdout).unwrap().trim().to_string()
    };
    let mut workers: Vec<String> = workers
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
    let first_ref = world.room_ref(&world.items[0], 1);
    // With `YAK_INNER_GIT_DIR` naming a directory that is first on this process's search path, a `git` is put
    // there that is the real git except where the mode says otherwise: at the clock's fetch, where the clock
    // looks whether the ref's name is free, or where it makes the ref. Taking a ref back (`update-ref -d`) is
    // always the real git's. The clock's fetch is the one whose source is a sandbox, under the room's `turns`:
    // a sandbox is itself made by a fetch, from the item's repository, and that one is left alone.
    if let Some(dir) = std::env::var_os("YAK_INNER_GIT_DIR") {
        let dir = std::path::PathBuf::from(dir);
        let mode = std::env::var("YAK_INNER_GIT_MODE").unwrap();
        let stop = format!(": > '{}'", world.room_dir.join("STOP").display());
        // Left behind by a wrapped git that was let run to its end where it should have been ended.
        let waited = format!(": > '{}'", dir.join("waited-out").display());
        let me = std::process::id();
        let real = "/usr/bin/git \"$@\"";
        // The clock held still for longer than its lease, as a machine that sleeps holds it.
        let asleep = |meanwhile: &str| {
            format!("kill -STOP {me}; sleep 8; {meanwhile}; made=$?; kill -CONT {me}")
        };
        let nothing = || ":".to_string();
        let (at_fetch, at_look, at_ref) = match mode.as_str() {
            "slow-fetch" => ("sleep 8".to_string(), nothing(), nothing()),
            "fetch-stop" => (format!("{stop}; sleep 9; {waited}"), nothing(), nothing()),
            // The fetch stops the room and then fails.
            "fetch-stop-fail" => (format!("{stop}; exit 1"), nothing(), nothing()),
            // The fetch is done at once and leaves something holding its output, under a git limit of 2 s.
            "fetch-held" => {
                // Named by this process, so that what another run left behind is not taken for this one's.
                println!("SLEEPER sleep 47.{me}");
                (format!("sleep 47.{me} & exit 0"), nothing(), nothing())
            }
            "slow-ref" => (nothing(), nothing(), "sleep 8".to_string()),
            // The room is stopped as the ref is about to be made.
            "ref-stop" => (nothing(), nothing(), format!("{stop}; sleep 9; {waited}")),
            // The ref is made, and the room is stopped before the clock has it back.
            "ref-then-stop" => (
                nothing(),
                nothing(),
                format!("{real}; made=$?; {stop}; sleep 1; exit $made"),
            ),
            // The machine sleeps while the ref is made.
            "ref-asleep" => (
                nothing(),
                nothing(),
                format!("{}; exit $made", asleep(real)),
            ),
            // The ref is made, and from then on the room's store takes no write. The holder leaves this
            // program's group, which the clock ends with it, and says when it has the store.
            "ref-then-store" => {
                let (holder, held) = (dir.join("hold.py"), dir.join("held"));
                fs::write(
                    &holder,
                    "import os, sqlite3, sys, time\nos.setsid()\n\
                     held = sqlite3.connect(sys.argv[1], isolation_level=None, timeout=30)\n\
                     held.execute('BEGIN IMMEDIATE')\nopen(sys.argv[2], 'w').close()\ntime.sleep(15)\n",
                )
                .unwrap();
                (
                    nothing(),
                    nothing(),
                    format!(
                        "{real}; made=$?; python3 -I '{}' '{}' '{held}' </dev/null >/dev/null 2>&1 & \
                         while [ ! -e '{held}' ]; do sleep 0.1; done; exit $made",
                        holder.display(),
                        world.room_dir.join("room.sqlite3").display(),
                        held = held.display(),
                    ),
                )
            }
            // The ref's name is taken already, and names the very commit the worker hands in. The room is
            // stopped, or the lease runs out, as the clock looks at the name.
            "taken-ref-stop" => (nothing(), stop.clone(), nothing()),
            "taken-ref-asleep" => (nothing(), asleep(":"), nothing()),
            "same-commit" => (nothing(), nothing(), nothing()),
            other => panic!("unknown mode {other}"),
        };
        if matches!(
            mode.as_str(),
            "slow-fetch" | "slow-ref" | "ref-asleep" | "taken-ref-asleep"
        ) {
            // Renewed every two seconds, so it is kept on a busy machine and outlasted by eight seconds.
            world.room.set_lease_secs(6).unwrap();
        }
        if mode == "fetch-held" {
            world.git_secs = 2;
        }
        if mode.starts_with("taken-ref") {
            git(&world.repo, &["update-ref", &first_ref, &already]);
            workers = vec![same.clone()];
        }
        // The control for that: with no ref in the way, the same worker's turn is given the name, and the
        // commit it names is the one made beforehand. Without this, the two modes above could pass with a
        // worker whose commit was some other one.
        if mode == "same-commit" {
            workers = vec![same.clone()];
        }
        let wrapper = dir.join("git");
        fs::write(
            &wrapper,
            format!(
                "#!/bin/sh\ncase \" $* \" in\n*\" update-ref --no-deref -d \"*) ;;\n\
                 *\" for-each-ref --format=%(refname) refs/heads/room/\"*) {at_look};;\n\
                 *\" fetch \"*\"/turns/\"*) {at_fetch};;\n*\" update-ref \"*) {at_ref};;\nesac\nexec {real}\n"
            ),
        )
        .unwrap();
        fs::set_permissions(&wrapper, fs::Permissions::from_mode(0o755)).unwrap();
        println!("WRAPPED {mode}");
    }
    // With `YAK_INNER_ASLEEP` set, the clock is held still for eight seconds while a worker that waits for
    // thirty is running, under a lease of six: the lease runs out while the worker runs, and no renewal could
    // have kept it. Another program does the holding, since this one cannot move while it is held. It begins
    // a second after the worker's record is there, however long the machine took to get that far.
    let asleep = std::env::var_os("YAK_INNER_ASLEEP").is_some();
    let waits = world.script("waits.sh", "#!/bin/sh\nsleep 30\n");
    let mut holder = None;
    if asleep {
        world.room.set_lease_secs(6).unwrap();
        workers = vec![waits.clone()];
        let me = std::process::id();
        let held = std::process::Command::new("/bin/sh")
            .args([
                "-c",
                &format!(
                    "tries=0; until ls '{}'/*.pid >/dev/null 2>&1; do \
                     tries=$((tries + 1)); [ \"$tries\" -gt 900 ] && exit 3; sleep 0.1; done; \
                     sleep 1; kill -STOP {me}; sleep 8; kill -CONT {me}",
                    world.room_dir.join("turns").display()
                ),
            ])
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .unwrap();
        holder = Some(held);
    }
    let groups = asleep.then(|| Groups::watch(world.room_dir.join("turns")));
    let workers: Vec<&str> = workers.iter().map(String::as_str).collect();
    let began = Instant::now();
    // The room is stopped when the first turn ends, so that the run is that one turn.
    let stop = world.room_dir.join("STOP");
    let mut after_one = |e: &Event| {
        if asleep && matches!(e, Event::Ended { .. }) {
            fs::write(&stop, "").unwrap();
        }
    };
    let (result, events) = world.run_hooked(
        &workers,
        Mode::OnceThrough,
        NEVER,
        TURN_SECS,
        &mut after_one,
    );
    println!("TOOK {} s", began.elapsed().as_secs());
    if let Some(mut holder) = holder {
        // This line runs, so the clock is not being held: the holder is done, or has not begun. If it has
        // not begun (no worker's record ever appeared) it is ended here, and nothing is left waiting.
        let _ = holder.kill();
        let _ = holder.wait();
    }
    if let Some(groups) = groups {
        let seen = groups.seen();
        // A moment for the last signal to land.
        thread::sleep(Duration::from_millis(500));
        let alive = seen.iter().filter(|group| group_alive(**group)).count();
        println!("GROUPS seen {} alive {alive}", seen.len());
        println!("TURNS left {:?}", world.turns());
    }
    match result {
        Ok(()) => println!("RAN {} turn(s)", started(&events).len()),
        Err(e) => println!("REFUSED {e}"),
    }
    println!("FIRST {:?}", outcomes(&events).first());
    // The first turn's record, where it has one: how its worker ended, and whether it holds a worker's time.
    if let Some((_, attempt, _, _)) = started(&events).first()
        && let Ok(Some(m)) = world.room.measured(attempt)
    {
        let time = if m.worker_ms > 0 { "ran" } else { "none" };
        println!("MEASURED {:?} worker {time}", m.ended);
    }
    println!("REFS {}", world.room_refs().len());
    let named = if world.room_refs().contains(&first_ref) {
        let commit = git(&world.repo, &["rev-parse", &first_ref]);
        match commit {
            c if c == already => "the commit made beforehand".to_string(),
            c if c == world.wrong => "the wrong commit".to_string(),
            c if c == world.base => "the base".to_string(),
            _ => "the turn's commit".to_string(),
        }
    } else {
        "nothing".to_string()
    };
    println!("REF1 names {named}");
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
    if let Some(dir) = std::env::var_os("YAK_INNER_GIT_DIR") {
        let waited = std::path::Path::new(&dir).join("waited-out").exists();
        println!("WAITED-OUT {waited}");
    }
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

/// A lease that runs out while the worker runs ends the worker and the turn: nothing is handed in, no ref is
/// made, and nothing of the turn is left. Seen with the clock held still for longer than its lease, once a
/// worker that waits for thirty seconds is running.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_lease_that_runs_out_while_the_worker_runs_ends_the_worker() {
    let out = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "inner_a_clock_under_the_rooms_switches",
            "--nocapture",
        ])
        .env("YAK_INNER_WORKERS", "FIX")
        .env("YAK_INNER_ASLEEP", "1")
        .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        .env_remove("YAK_JAIL")
        .env_remove("YAK_SUPERVISION")
        .output()
        .unwrap();
    let printed = String::from_utf8_lossy(&out.stdout).into_owned();
    assert!(
        printed.contains("ITEM "),
        "the inner run did not report: {printed} {}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(printed.contains("FIRST Some(LeaseLost)"), "{printed}");
    // Its record says the same of its worker, which had run: here nothing is left to how busy the machine is.
    assert!(
        printed.contains("MEASURED LeaseLost worker ran"),
        "{printed}"
    );
    // The worker had started, and it is gone: not left to wait out its thirty seconds.
    assert!(printed.contains("GROUPS seen 1 alive 0"), "{printed}");
    assert!(took(&printed) < 25, "{printed}");
    assert!(printed.contains("REFS 0"), "{printed}");
    assert!(printed.contains("TURNS left []"), "{printed}");
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
#[ignore = "needs the room: a list of processes and a jail"]
fn a_slow_fetch_keeps_its_lease_and_ends_with_no_ref_once_the_room_is_stopped() {
    // A fetch of eight seconds under a lease of six: the lease is renewed meanwhile, and the turn is judged
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
    assert!(took(&slow) >= 8, "the fetch was not slow: {slow}");

    // Stopped by a person as the fetch began: the fetch is ended and not waited out, no ref is made, the item
    // is open again and the attempt does not count.
    let stopped = with_git("fetch-stop");
    assert!(stopped.contains("FIRST Some(Stopped)"), "{stopped}");
    assert!(stopped.contains("REFS 0"), "{stopped}");
    assert!(stopped.contains("ITEM Open attempts 0"), "{stopped}");
    assert!(
        stopped.contains("WAITED-OUT false"),
        "the fetch was waited out: {stopped}"
    );

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
#[ignore = "needs the room: a list of processes and a jail"]
fn a_ref_is_made_only_under_a_lease_the_turn_holds_in_a_room_that_is_not_stopped() {
    // Eight seconds to make the ref under a lease of six: the lease is renewed meanwhile.
    let slow = with_git("slow-ref");
    assert!(
        slow.contains("FIRST Some(Judged { state: PassedVerified"),
        "{slow}"
    );
    assert!(slow.contains("REFS 1"), "{slow}");
    assert!(slow.contains("REF1 names the turn's commit"), "{slow}");
    assert!(
        slow.contains("ITEM PassedVerified attempts 1 lease 1"),
        "{slow}"
    );
    assert!(took(&slow) >= 8, "making the ref was not slow: {slow}");

    // The room is stopped as the ref is about to be made: git is ended, and no ref is made.
    let stopped = with_git("ref-stop");
    assert!(stopped.contains("FIRST Some(Stopped)"), "{stopped}");
    assert!(stopped.contains("REFS 0"), "{stopped}");
    assert!(stopped.contains("ITEM Open attempts 0"), "{stopped}");
    assert!(
        stopped.contains("WAITED-OUT false"),
        "git was waited out: {stopped}"
    );

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

/// A ref that was there before the turn came to make its own is never the turn's to take back, whatever it
/// names. Here it names the very commit the worker hands in, one the repository had all along. The turn ends,
/// for a stop or for a lease that ran out as the clock looked at the name, and the ref is as it was.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_ref_that_was_already_there_is_left_when_the_turn_ends_without_a_hand_in() {
    // The control: the worker's commit is the very one made beforehand. Its turn fails the check (every answer
    // is 41), and the ref the clock made for it names that commit.
    let control = with_git("same-commit");
    assert!(
        control.contains("REF1 names the commit made beforehand"),
        "{control}"
    );
    for (mode, ended) in [
        ("taken-ref-stop", "FIRST Some(Stopped)"),
        ("taken-ref-asleep", "FIRST Some(LeaseLost)"),
    ] {
        let taken = with_git(mode);
        assert!(taken.contains(ended), "{mode}: {taken}");
        assert!(taken.contains("REFS 1"), "{mode}: {taken}");
        assert!(
            taken.contains("REF1 names the commit made beforehand"),
            "{mode}: {taken}"
        );
        assert!(taken.contains("PROBLEMS 0"), "{mode}: {taken}");
    }
}

/// When the room's store fails just after the ref was made, the clock ends, as it does for any failure of its
/// store. The turn hands nothing in, so its ref is taken back first: that needs git, not the store.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_ref_is_taken_back_when_the_store_fails_before_the_hand_in() {
    let failed = with_git("ref-then-store");
    assert!(failed.contains("REFUSED "), "{failed}");
    assert!(failed.contains("locked"), "{failed}");
    assert!(failed.contains("REFS 0"), "{failed}");
    assert!(failed.contains("REF1 names nothing"), "{failed}");
}

/// The clock's own git has a time limit that covers its output too, and the clock's fetch runs under it: a git
/// that is done at once and leaves something holding its output does not hold the turn. Seen with a limit of
/// two seconds and a `git` whose fetch leaves a `sleep` of 47 seconds behind.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
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
    let sleeper = held
        .lines()
        .find_map(|line| line.strip_prefix("SLEEPER "))
        .expect("the inner run names what its fetch leaves running");
    assert!(
        gone(sleeper),
        "what the fetch started ({sleeper}) is still running"
    );
}

/// The inner half of the tests below, and nothing by itself: a clock whose look at the machine's processes
/// starts to fail part of the way through a run. `YAK_INNER_PS_DIR` names a directory that is first on this
/// process's search path; a `ps` is put there that is the real one until a file named `ps-fails` appears in a
/// sandbox of the room's, and fails from then on.
///
/// In the modes that end in `-store` the room's store fails as well: its write lock is taken by another
/// program while the run is going, so the clock's next renewal fails. From that moment the `ps` here waits six
/// seconds and then fails, each time it is asked. So the run is still being ended, and cannot be confirmed
/// ended, when the store's failure is already known: both are there when the clock comes to decide.
#[test]
fn inner_a_clock_that_can_no_longer_look_at_its_processes() {
    let Some(dir) = std::env::var_os("YAK_INNER_PS_DIR") else {
        return;
    };
    let mode = std::env::var("YAK_INNER_PS_MODE").unwrap();
    let mut world = World::new(0);
    // Short enough that a clock which went on where it should have stopped is over in seconds, since an item
    // would wait out its lease and this run with it; long enough to be kept on a busy machine.
    world.room.set_lease_secs(6).unwrap();
    let room = world.room_dir.display().to_string();
    let wrapper = std::path::Path::new(&dir).join("ps");
    // Made by this test once it holds the store.
    let store_held = std::path::Path::new(&dir).join("store-held");
    fs::write(
        &wrapper,
        format!(
            "#!/bin/sh\nif [ -e '{held}' ]; then sleep 6; exit 2; fi\n\
             for flag in '{room}'/turns/*/ps-fails '{room}'/turns/*/*/ps-fails \
             '{room}'/checks/.work-*/*/ps-fails; do\n  [ -e \"$flag\" ] && exit 2\ndone\n\
             for real in /bin/ps /usr/bin/ps; do [ -x \"$real\" ] && exec \"$real\" \"$@\"; done\nexit 2\n",
            held = store_held.display()
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
        // In these two the run only waits. What breaks the look is the store being held.
        "worker-store" => (
            world.script("waits.sh", "#!/bin/sh\nsleep 600\n"),
            "sh check.sh 1".to_string(),
        ),
        "check-store" => (
            world.script("fix.sh", FIX),
            "if grep -qx 42 answer1.txt; then sleep 600; fi; sh check.sh 1".to_string(),
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
        let said = events.iter().any(
            |e| matches!(e, Event::Problem { what, .. } if what.contains("the room's store failed as well")),
        );
        println!("{label} STORE-SAID {said}");
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
        if let Some(id) = attempt {
            let measured = world.room.measured(&room::AttemptId(id.clone()));
            println!("{label} MEASURED {}", matches!(measured, Ok(Some(_))));
        }
    };
    // In the `-store` modes: once the run in question has its record, the store is held.
    let holder = mode.ends_with("-store").then(|| {
        let (turns, room_dir) = (world.room_dir.join("turns"), world.room_dir.clone());
        let of_a_check = mode == "check-store";
        thread::spawn(move || {
            let deadline = Instant::now() + Duration::from_secs(90);
            let there = wait_until(deadline, || {
                fs::read_dir(&turns)
                    .into_iter()
                    .flatten()
                    .flatten()
                    .any(|e| {
                        let name = e.file_name().to_string_lossy().into_owned();
                        name.ends_with(".pid") && name.ends_with(".check.pid") == of_a_check
                    })
            });
            assert!(there, "the run never had a record");
            let held = StoreHeld::hold(&room_dir);
            fs::write(&store_held, "").unwrap();
            held
        })
    });
    // A turn limit of twenty seconds: a clock that went on where it should have stopped would otherwise run a
    // worker that never ends for the room's usual limit, and this test with it.
    let turn_secs = 20;
    let (result, events) = world.run(&[&worker], Mode::OnceThrough, NEVER, turn_secs);
    let held = holder.map(|holder| holder.join().unwrap());
    let attempt = started(&events).first().map(|turn| turn.1.0.clone());
    report(&world, "FIRST", result, &events, &attempt);
    // The store is let go before the clock is started again.
    drop(held);
    if mode != "plain" {
        // A clock started again while the look still fails finds the record, and stops the same way.
        let (result, events) = world.run(&[&worker], Mode::OnceThrough, NEVER, turn_secs);
        report(&world, "AGAIN", result, &events, &attempt);
    }
}

/// Runs the inner test above in a child with `ps` wrapped, in `mode`, and returns what it printed.
fn with_ps(mode: &str) -> String {
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
}

/// What an inner run that stopped at a worker's run must have printed.
fn stopped_at_the_workers_run(printed: &str) {
    assert!(
        printed.contains("FIRST UNRECOVERED turns/A.pid BECAUSE "),
        "{printed}"
    );
    assert!(printed.contains("FIRST STARTED 1"), "{printed}");
    let turns = printed
        .lines()
        .find(|l| l.starts_with("FIRST TURNS "))
        .unwrap();
    assert!(
        turns.contains("\"A\"") && turns.contains("\"A.pid\""),
        "{printed}"
    );
    assert!(printed.contains("FIRST ITEMS [Leased, Open]"), "{printed}");
    assert!(
        printed.contains("AGAIN UNRECOVERED turns/A.pid BECAUSE "),
        "{printed}"
    );
    assert!(printed.contains("AGAIN STARTED 0"), "{printed}");
    let again = printed
        .lines()
        .find(|l| l.starts_with("AGAIN TURNS "))
        .unwrap();
    assert_eq!(
        again.strip_prefix("AGAIN "),
        turns.strip_prefix("FIRST "),
        "{printed}"
    );
}

/// What an inner run that stopped at a check's run must have printed: the worker's sandbox, the check's own and
/// the check's record all stay.
fn stopped_at_the_checks_run(printed: &str) {
    assert!(
        printed.contains("FIRST UNRECOVERED turns/A.check.pid BECAUSE "),
        "{printed}"
    );
    assert!(printed.contains("FIRST STARTED 1"), "{printed}");
    let turns = printed
        .lines()
        .find(|l| l.starts_with("FIRST TURNS "))
        .unwrap();
    for name in ["\"A\"", "\"A.check\"", "\"A.check.pid\""] {
        assert!(turns.contains(name), "{name}: {printed}");
    }
    assert!(printed.contains("FIRST CHECK-SANDBOXES 1"), "{printed}");
    assert!(
        printed.contains("FIRST ITEMS [Checking, Open]"),
        "{printed}"
    );
    assert!(
        printed.contains("AGAIN UNRECOVERED turns/A.check.pid BECAUSE "),
        "{printed}"
    );
    assert!(printed.contains("AGAIN STARTED 0"), "{printed}");
}

/// A run ends when the room has seen that every process it started is gone. When that cannot be seen (here the
/// look at the machine's processes starts to fail) the run may still be going, and the clock stops: it removes
/// nothing of that run, neither its record nor its sandbox, and starts no other turn. That holds for a
/// worker's run, for a check's and for a check being frozen. A clock started again finds the record and stops
/// in the same way until the run can be ended.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_run_that_cannot_be_confirmed_ended_stops_the_clock_with_everything_in_place() {
    // The control: with the same `ps` in the way and nothing breaking it, both items pass and nothing is left.
    let plain = with_ps("plain");
    assert!(plain.contains("FIRST OK"), "{plain}");
    assert!(plain.contains("FIRST STARTED 2"), "{plain}");
    assert!(plain.contains("FIRST TURNS []"), "{plain}");
    assert!(
        plain.contains("FIRST ITEMS [PassedVerified, PassedVerified]"),
        "{plain}"
    );

    // The attempt's measured record is written, though the clock stopped for its run.
    let worker = with_ps("worker");
    stopped_at_the_workers_run(&worker);
    assert!(worker.contains("FIRST MEASURED true"), "{worker}");
    let check = with_ps("check");
    stopped_at_the_checks_run(&check);
    assert!(check.contains("FIRST MEASURED true"), "{check}");

    // A check being frozen: its work directory, the sandbox in it and its record all stay, and no turn starts.
    let freeze = with_ps("freeze");
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

/// The same when the room's store fails in the same turn. A store that fails ends the clock, and it is why the
/// run was being ended; but it is no leave to remove what is left of a run that may still be going. The clock
/// stops for the run, with its record and its directories in place, and says that the store failed as well.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_run_that_cannot_be_confirmed_ended_is_kept_though_the_store_fails_too() {
    let worker = with_ps("worker-store");
    stopped_at_the_workers_run(&worker);
    assert!(worker.contains("FIRST STORE-SAID true"), "{worker}");

    let check = with_ps("check-store");
    stopped_at_the_checks_run(&check);
    assert!(check.contains("FIRST STORE-SAID true"), "{check}");
}

/// With the jail or the watch on processes switched off, the clock runs script workers and no model: a model
/// writes code that the room then runs, and those two switches are what holds that code.
///
/// The search path here has no `claude` or `codex` on it. So where the switches allow a model, the clock stops
/// at the next thing it checks, that the program is there, and no model is started by this test whatever the
/// clock does.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
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
