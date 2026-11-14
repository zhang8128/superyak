//! The clock: the loop that runs turns. Stage 1 plan, task 9.
//!
//! One pass, in the plan's order: stop if the room is stopped; return expired leases; freeze the drafts; take an
//! item for the next worker in turn; make its sandbox; run the worker, renewing the lease; fetch what it committed
//! into the item's repository as `refs/heads/room/<item>/<lease_no>`, then hand that commit in (the plan has these
//! two the other way round; see `Clock::work` for why); run the frozen check; record the verdict and the walk;
//! remove the sandbox. One verified pass in `RECHECK_ONE_IN`, chosen by the
//! caller's random numbers, is checked again in a fresh clone. The fetched ref is the clock's only effect outside
//! the room's directory.
//!
//! The clock holds the room's only writing connection, so nothing else changes the room while a turn runs: what a
//! turn sees in the room at the start is still true at its end, except for the passing of time.
#![allow(
    dead_code,
    reason = "main.rs also declares this module until task 10 makes the binary use the library's"
)]

use std::collections::HashMap;
use std::ffi::OsStr;
use std::fs;
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use rand::Rng;
use room::limits::{CLOCK_POLL_SECS, RECHECK_ONE_IN, TERM_GRACE_SECS, TURN_SECS};
use room::{AttemptId, ItemId, ItemState, Lease, Room, RoomError, Step, Ts};
use turn::{Sandbox, TurnError, WorkerRun, check, worker};

/// The longest a lease goes without a renewal while its turn runs, in seconds. A shorter lease is renewed three
/// times as often as it lasts, so a test's lease of a few seconds holds too.
pub const RENEW_SECS: i64 = 300;

/// How long a draft that could not be frozen waits before it is tried again: long enough not to rerun a slow
/// failing check every pass, short enough that a repository that was away for a while is picked up.
const FREEZE_RETRY: Duration = Duration::from_secs(3600);

/// How often the clock looks at the stop file and the lease while a worker or a check runs.
const WATCH: Duration = Duration::from_millis(100);

/// Below the room's directory: one sandbox per attempt, its pid file and its check's scratch space.
const TURNS: &str = "turns";
/// Below the room's directory: the frozen copies of every check, by hash.
const CHECKS: &str = "checks";

/// What the clock's environment passes to the git it runs itself. Everything else, `GIT_DIR` included, is left out.
const GIT_ENV_KEPT: &[&str] = &[
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ",
];

/// The flags of the turn crate's own git (`turn::sandbox::SAFE_GIT_FLAGS`, which is private to it): no hooks, no
/// filesystem monitor, no attributes file of the user's. And for the fetch, the local transport, with every
/// incoming object checked.
const GIT_FLAGS: [&str; 10] = [
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.attributesFile=/dev/null",
    "-c",
    "protocol.file.allow=always",
    "-c",
    "fetch.fsckObjects=true",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    /// Run until the room is stopped.
    Forever,
    /// Run until no worker can take anything and no turn is outstanding, then return.
    OnceThrough,
}

#[derive(Debug, thiserror::Error)]
pub enum ClockError {
    #[error(transparent)]
    Room(#[from] RoomError),
    #[error(transparent)]
    Turn(#[from] TurnError),
    #[error("the clock needs at least one worker")]
    NoWorkers,
    #[error("could not freeze {item}: {reason} ({failed} draft(s) failed, {frozen} froze)")]
    Freeze {
        item: String,
        reason: String,
        frozen: u32,
        failed: u32,
    },
    #[error("git: {0}")]
    Git(String),
    #[error("{0}")]
    Io(String),
}

/// What the clock did, as it does it, for whoever runs it to show. Nothing in an event comes from a transcript.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Event {
    /// Something a clock that died left was removed at the start of a run: `name` is its path in the room's
    /// directory. For a pid file, `group` is the process group it named and `running` whether anything was still
    /// in that group. The clock never signals
    /// such a group: it cannot tell that the number was not given to someone else's processes since.
    Cleared {
        name: String,
        group: Option<u32>,
        running: bool,
    },
    /// A draft's check was frozen; `state` is where that left the item.
    Frozen { item: ItemId, state: ItemState },
    /// A draft's check could not be frozen. The item stays a draft, and is tried again after an hour.
    NotFrozen { item: ItemId, reason: String },
    Started {
        item: ItemId,
        attempt: AttemptId,
        lease_no: u32,
        worker: String,
    },
    Ended {
        item: ItemId,
        lease_no: u32,
        outcome: Outcome,
    },
    /// The daily ceiling refused a turn. In `Forever` the clock waits for the next UTC day, and says so once a day.
    Ceiling { used: u32, limit: u32 },
    /// Something after the fact did not complete (a walk refused, a directory not removed). The room is consistent.
    Problem { item: Option<ItemId>, what: String },
}

/// How a turn ended.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Outcome {
    /// The commit was handed in, checked, and the verdict recorded: `state` is the item's state after it.
    Judged {
        state: ItemState,
        commit: String,
        /// Why the turn handed in its base commit, when it did: it committed nothing, or its work could not be
        /// taken back. The room fails a base hand-in.
        nothing: Option<String>,
        /// The worker ran out of time. What it had committed by then was judged all the same.
        timed_out: bool,
        /// The item's state after a recheck, when one ran.
        recheck: Option<ItemState>,
    },
    /// The stop file ended the turn before it handed in. The item keeps its lease until the lease expires.
    Stopped,
    /// The room called the lease stale (the machine slept past it, say). The turn ended without handing in, and
    /// the next pass's `expire_due` returns the item.
    LeaseLost,
    /// The turn could not start (no sandbox could be made). Nothing was handed in; the lease will expire.
    NotRun { reason: String },
    /// The commit was handed in, but no verdict could be reached or recorded. The item stays `Checking` until its
    /// lease expires.
    Unchecked { reason: String },
}

/// Settings `run` takes from `limits.rs`, for a command line or a test to change.
pub struct Options<'a> {
    /// The wall-clock limit of one worker run.
    pub turn_secs: u32,
    /// How long the clock waits between passes that found nothing to do.
    pub poll: Duration,
    /// Called with each event as it happens.
    pub report: Option<&'a mut dyn FnMut(&Event)>,
}

impl Default for Options<'_> {
    fn default() -> Self {
        Options {
            turn_secs: TURN_SECS,
            poll: Duration::from_secs(u64::from(CLOCK_POLL_SECS)),
            report: None,
        }
    }
}

/// Runs the clock with the limits of `limits.rs` until the room is stopped or, in `OnceThrough`, until nothing is
/// left that a worker can take.
pub fn run(
    room: &mut Room,
    workers: &[String],
    mode: Mode,
    rng: &mut dyn Rng,
) -> Result<(), ClockError> {
    run_with(room, workers, mode, rng, Options::default())
}

/// `run`, with the settings given.
pub fn run_with(
    room: &mut Room,
    workers: &[String],
    mode: Mode,
    rng: &mut dyn Rng,
    options: Options<'_>,
) -> Result<(), ClockError> {
    if workers.is_empty() {
        return Err(ClockError::NoWorkers);
    }
    // A worker that cannot be named, or whose program is not there, would fail every item it took until each was
    // abandoned; it is refused before any is taken.
    for name in workers {
        worker::from_name(name)?;
        ready(name)?;
    }
    let mut clock = Clock {
        room,
        workers,
        turn_secs: options.turn_secs,
        poll: options.poll,
        report: options.report,
        next: 0,
        unfreezable: HashMap::new(),
        ceiling_day: None,
    };
    clock.clear_turns()?;
    loop {
        if clock.room.stopped() {
            return Ok(());
        }
        clock.room.expire_due(now())?;
        clock.freeze()?;
        if clock.room.stopped() {
            return Ok(());
        }
        let taken_at = now();
        match clock.take(taken_at)? {
            Taken::Lease(lease) => {
                clock.turn(lease, taken_at, rng)?;
                continue;
            }
            Taken::Stopped => return Ok(()),
            Taken::Ceiling { used, limit } => {
                if mode == Mode::OnceThrough {
                    return Err(RoomError::Ceiling { used, limit }.into());
                }
                let day = taken_at.div_euclid(86_400);
                if clock.ceiling_day != Some(day) {
                    clock.ceiling_day = Some(day);
                    clock.tell(&Event::Ceiling { used, limit });
                }
            }
            Taken::Nothing => {
                // A lease a dead clock left is waited out: `expire_due` returns its item to be taken again.
                if mode == Mode::OnceThrough && !clock.outstanding()? {
                    return Ok(());
                }
            }
        }
        clock.sleep(clock.poll);
    }
}

/// Freezes every draft whose check is not frozen yet, and records each. Returns how many were recorded, or, when
/// any could not be frozen, the first such item's reason after trying the rest.
pub fn freeze_drafts(room: &mut Room) -> Result<u32, ClockError> {
    let mut frozen = 0u32;
    let mut failed: Vec<(ItemId, String)> = Vec::new();
    for id in room.drafts()? {
        match freeze_one(room, &id) {
            Ok(_) => frozen += 1,
            Err(Unfrozen::Item(reason)) => failed.push((id, reason)),
            Err(Unfrozen::Store(e)) => return Err(e.into()),
        }
    }
    match failed.first() {
        None => Ok(frozen),
        Some((item, reason)) => Err(ClockError::Freeze {
            item: item.0.clone(),
            reason: reason.clone(),
            frozen,
            failed: u32::try_from(failed.len()).unwrap_or(u32::MAX),
        }),
    }
}

enum Unfrozen {
    /// This item's check could not be frozen or recorded; others may be.
    Item(String),
    /// The room's store failed.
    Store(RoomError),
}

fn freeze_one(room: &mut Room, id: &ItemId) -> Result<ItemState, Unfrozen> {
    let store = |e: RoomError| {
        if fatal(&e) {
            Unfrozen::Store(e)
        } else {
            Unfrozen::Item(e.to_string())
        }
    };
    let spec = room.item_spec(id).map_err(store)?;
    let checks = room.dir().join(CHECKS);
    let frozen = check::freeze(&spec.repo, &spec.base_commit, &spec.check, &checks)
        .map_err(|e| Unfrozen::Item(e.to_string()))?;
    room.record_frozen(id, frozen).map_err(store)
}

/// A room error that says the store itself cannot be trusted or reached, which ends the clock. The others are
/// about one item or one lease.
fn fatal(e: &RoomError) -> bool {
    matches!(
        e,
        RoomError::Missing(_)
            | RoomError::Damaged(_)
            | RoomError::NewerSchema { .. }
            | RoomError::Locked
            | RoomError::Db(_)
    )
}

enum Taken {
    Lease(Lease),
    Nothing,
    Stopped,
    Ceiling { used: u32, limit: u32 },
}

struct Clock<'r, 'o> {
    room: &'r mut Room,
    workers: &'r [String],
    turn_secs: u32,
    poll: Duration,
    report: Option<&'o mut dyn FnMut(&Event)>,
    /// The worker whose turn it is next.
    next: usize,
    /// Drafts that failed to freeze, and when: a broken one is tried again after `FREEZE_RETRY`, not every pass.
    unfreezable: HashMap<ItemId, Instant>,
    /// The UTC day the ceiling was last reported.
    ceiling_day: Option<i64>,
}

/// Why the clock stopped watching a job, beyond the job finishing.
#[derive(Debug, Clone, Copy, Default)]
struct Watched {
    /// The stop file appeared.
    stopped: bool,
    /// A renewal said the lease is no longer this turn's.
    lost: bool,
}

/// Keeps a lease renewed while its turn runs.
struct Keeper {
    lease: Lease,
    every: i64,
    last: Ts,
}

impl Keeper {
    fn new(lease: &Lease, taken_at: Ts) -> Keeper {
        let span = lease.expires.saturating_sub(taken_at);
        Keeper {
            lease: lease.clone(),
            every: (span / 3).clamp(1, RENEW_SECS),
            last: taken_at,
        }
    }

    fn due(&self, now: Ts) -> bool {
        now.saturating_sub(self.last) >= self.every
    }
}

impl Clock<'_, '_> {
    fn tell(&mut self, event: &Event) {
        if let Some(report) = self.report.as_mut() {
            report(event);
        }
    }

    /// Sleeps for `how_long`, or until the stop file appears.
    fn sleep(&self, how_long: Duration) {
        let end = Instant::now() + how_long;
        while !self.room.stopped() {
            let left = end.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return;
            }
            thread::sleep(left.min(WATCH));
        }
    }

    /// Whether any item is leased or being checked: a turn of a clock that died, waiting for its lease to expire.
    fn outstanding(&self) -> Result<bool, ClockError> {
        Ok(self
            .room
            .items()?
            .iter()
            .any(|item| matches!(item.state, ItemState::Leased | ItemState::Checking)))
    }

    /// Removes whatever is in `turns/`, and the scratch a freeze leaves in `checks/` (`.work-*`, `.freeze-*`). The
    /// room's writer lock is held, so all of it is from a clock that died. Its sandboxes are never fetched from, and
    /// the process groups its pid files name are never signalled.
    fn clear_turns(&mut self) -> Result<(), ClockError> {
        let mut paths = Vec::new();
        for (dir, scratch_only) in [(TURNS, false), (CHECKS, true)] {
            let dir = self.room.dir().join(dir);
            let entries = match fs::read_dir(&dir) {
                Ok(entries) => entries,
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
                Err(e) => return Err(ClockError::Io(format!("read {}: {e}", dir.display()))),
            };
            let mut found: Vec<PathBuf> = entries
                .flatten()
                .map(|e| e.path())
                .filter(|p| {
                    let name = p.file_name().unwrap_or_default().to_string_lossy();
                    !scratch_only || name.starts_with(".work-") || name.starts_with(".freeze-")
                })
                .collect();
            found.sort();
            paths.extend(found);
        }
        for path in paths {
            let name = path
                .strip_prefix(self.room.dir())
                .unwrap_or(&path)
                .to_string_lossy()
                .into_owned();
            let group = name.ends_with(".pid").then(|| read_group(&path)).flatten();
            let running = group.is_some_and(group_alive);
            match remove_path(&path) {
                Ok(()) => self.tell(&Event::Cleared {
                    name,
                    group,
                    running,
                }),
                Err(what) => self.tell(&Event::Problem { item: None, what }),
            }
        }
        Ok(())
    }

    /// Freezes the drafts that are not waiting out a failure, one at a time, between looks at the stop file.
    fn freeze(&mut self) -> Result<(), ClockError> {
        for id in self.room.drafts()? {
            if self.room.stopped() {
                return Ok(());
            }
            if self
                .unfreezable
                .get(&id)
                .is_some_and(|failed| failed.elapsed() < FREEZE_RETRY)
            {
                continue;
            }
            match freeze_one(self.room, &id) {
                Ok(state) => self.tell(&Event::Frozen { item: id, state }),
                Err(Unfrozen::Item(reason)) => {
                    self.unfreezable.insert(id.clone(), Instant::now());
                    self.tell(&Event::NotFrozen { item: id, reason });
                }
                Err(Unfrozen::Store(e)) => return Err(e.into()),
            }
        }
        Ok(())
    }

    /// Takes an item for the next worker in turn. A worker that is given nothing (it wrote every open item's check,
    /// say) hands its turn to the one after it.
    fn take(&mut self, now: Ts) -> Result<Taken, ClockError> {
        let count = self.workers.len();
        for offset in 0..count {
            let index = (self.next + offset) % count;
            match self.room.take(&self.workers[index], now) {
                Ok(Some(lease)) => {
                    self.next = (index + 1) % count;
                    return Ok(Taken::Lease(lease));
                }
                Ok(None) => {}
                Err(RoomError::Stopped) => return Ok(Taken::Stopped),
                Err(RoomError::Ceiling { used, limit }) => {
                    return Ok(Taken::Ceiling { used, limit });
                }
                Err(e) => return Err(e.into()),
            }
        }
        Ok(Taken::Nothing)
    }

    /// One turn, from the lease to the removal of everything it left in `turns/`.
    fn turn(&mut self, lease: Lease, taken_at: Ts, rng: &mut dyn Rng) -> Result<(), ClockError> {
        self.tell(&Event::Started {
            item: lease.item.clone(),
            attempt: lease.attempt.clone(),
            lease_no: lease.lease_no,
            worker: lease.worker.clone(),
        });
        let result = self.attempt(&lease, taken_at, rng);
        self.tidy(&lease);
        let outcome = result?;
        self.tell(&Event::Ended {
            item: lease.item.clone(),
            lease_no: lease.lease_no,
            outcome,
        });
        Ok(())
    }

    fn attempt(
        &mut self,
        lease: &Lease,
        taken_at: Ts,
        rng: &mut dyn Rng,
    ) -> Result<Outcome, ClockError> {
        let (outcome, steps) = self.work(lease, taken_at)?;
        // The walk is the turn's ledger, whatever became of its hand-in.
        self.record_walk(lease, &steps)?;
        let Outcome::Judged {
            state,
            commit,
            nothing,
            timed_out,
            recheck: None,
        } = outcome
        else {
            return Ok(outcome);
        };
        let recheck = if state == ItemState::PassedVerified
            && !self.room.stopped()
            && rng.next_u32().is_multiple_of(RECHECK_ONE_IN)
        {
            self.recheck(lease, &commit)?
        } else {
            None
        };
        Ok(Outcome::Judged {
            state,
            commit,
            nothing,
            timed_out,
            recheck,
        })
    }

    /// Runs the worker and judges its commit. Returns how the turn ended and the steps its stream showed.
    fn work(&mut self, lease: &Lease, taken_at: Ts) -> Result<(Outcome, Vec<Step>), ClockError> {
        let title = self.room.item(&lease.item)?.title;
        let spec = self.room.item_spec(&lease.item)?;
        let Some(frozen) = spec.frozen.clone() else {
            // `take` never leases an item without a frozen check; this is not reached.
            return Ok((
                Outcome::NotRun {
                    reason: "the item has no frozen check".into(),
                },
                Vec::new(),
            ));
        };
        let turns = self.room.dir().join(TURNS);
        fs::create_dir_all(&turns)
            .map_err(|e| ClockError::Io(format!("make {}: {e}", turns.display())))?;
        let branch = format!("room/{}/{}", lease.item.0, lease.lease_no);
        let mut sandbox = match Sandbox::create(
            &spec.repo,
            &spec.base_commit,
            &turns.join(&lease.attempt.0),
            &branch,
        ) {
            Ok(sandbox) => sandbox,
            Err(e) => {
                // A check of the base would fail the same way, since it clones the same repository at the same
                // commit; so nothing is handed in, and the lease expires.
                let reason = format!("no sandbox: {e}");
                return Ok((Outcome::NotRun { reason }, Vec::new()));
            }
        };
        let pid_file = turns.join(format!("{}.pid", lease.attempt.0));
        sandbox.set_pid_file(pid_file.clone());
        let mut keeper = Keeper::new(lease, taken_at);

        let ran = {
            let (name, limit, sandbox) = (&lease.worker, self.turn_secs, &sandbox);
            let command = &spec.check.command;
            let title = &title;
            // A worker is not `Send`, so it is made where it runs.
            let job = move || -> Result<WorkerRun, TurnError> {
                worker::from_name(name)?.run(sandbox, title, command, limit)
            };
            self.watch(&mut keeper, Some(&pid_file), job)?
        };
        let (ran, watched) = ran;
        let (steps, timed_out, failure) = match ran {
            Ok(run) => (run.steps, run.timed_out, None),
            Err(e) => (Vec::new(), false, Some(e.to_string())),
        };
        let failure_said = failure.clone();
        if watched.stopped {
            // `Room::release` belongs here once it is on v2: a person stopped the turn, so the attempt should not
            // count against the item, and the item need not wait out its lease.
            return Ok((Outcome::Stopped, steps));
        }
        if watched.lost {
            return Ok((Outcome::LeaseLost, steps));
        }

        // What the turn hands in: its branch, read back after the clone is reclaimed from the worker; or its base,
        // when it committed nothing or its work cannot be taken back.
        let base = sandbox.base().to_string();
        let (mut commit, mut nothing) = match sandbox.head() {
            Ok(head) if head != base => (head, None),
            Ok(_) => (
                base.clone(),
                Some(failure.unwrap_or_else(|| "the turn committed nothing".into())),
            ),
            Err(e) => (base.clone(), Some(format!("its clone was not usable: {e}"))),
        };
        if let (Some(what), None) = (failure_said, &nothing) {
            // It committed, so its commit is judged; what went wrong after (its seal, say) is still said.
            self.tell(&Event::Problem {
                item: Some(lease.item.clone()),
                what: format!("the worker failed after committing: {what}"),
            });
        }
        // The fetch comes before the hand-in, so that what is handed in is always in the item's repository for the
        // check to clone; a commit that cannot be brought over is a turn that handed in nothing, and fails. A renewal
        // first makes sure the lease is still this turn's: no other writer can take it between here and the
        // hand-in, so the only ref a turn makes is under a lease it held.
        if commit != base {
            match self.room.renew(lease, now()) {
                Ok(_) => keeper.last = now(),
                Err(e) if fatal(&e) => return Err(e.into()),
                Err(_) => return Ok((Outcome::LeaseLost, steps)),
            }
            let name = format!("refs/heads/{branch}");
            if let Err(e) = fetch(&sandbox, &spec.repo, &commit, &name) {
                nothing = Some(format!("its commit could not be fetched: {e}"));
                commit = base.clone();
            }
        }
        match self.room.hand_in(lease, &commit, now()) {
            Ok(()) => {}
            Err(e) if fatal(&e) => return Err(e.into()),
            Err(RoomError::Stale { .. }) => return Ok((Outcome::LeaseLost, steps)),
            Err(e) => {
                let reason = format!("the hand-in was refused: {e}");
                return Ok((Outcome::Unchecked { reason }, steps));
            }
        }

        let checks = self.room.dir().join(CHECKS);
        let scratch = turns.join(format!("{}.check", lease.attempt.0));
        let checked = {
            let (repo, check, hash) = (&spec.repo, &spec.check, &frozen.check_hash);
            let (commit, checks, scratch) = (&commit, &checks, &scratch);
            let job = move || {
                remove_path(scratch).map_err(TurnError::Io)?;
                check::run_check(repo, commit, check, hash, checks, scratch)
            };
            // The check is not ended by the stop file: it has no pid file, and its own time limit bounds it. Its
            // lease is kept so that it stays this turn's for anyone reading the room; a renewal refused while the
            // check runs (the machine slept) does not throw the verdict away, since the hand-in was made under a
            // live lease and `record_verdict` refuses one whose lease number moved on.
            self.watch(&mut keeper, None, job)?.0
        };
        // Whatever verdict the check reaches is recorded as it is; the room classifies it.
        let verdict = match checked {
            Ok(verdict) => verdict,
            Err(e) => {
                // `Room::release` could go here too, but it does not count the attempt: a check that can never run
                // (its frozen copies gone) would then be retried until the daily ceiling. Expiry counts it, and
                // abandons the item after `MAX_ATTEMPTS`; use `release` here only for a cause known to pass.
                let reason = format!("the check could not run: {e}");
                return Ok((Outcome::Unchecked { reason }, steps));
            }
        };
        let state = match self
            .room
            .record_verdict(&lease.item, lease.lease_no, &verdict, now())
        {
            Ok(state) => state,
            Err(e) if fatal(&e) => return Err(e.into()),
            Err(RoomError::Stale { .. }) => return Ok((Outcome::LeaseLost, steps)),
            Err(e) => {
                let reason = format!("the verdict was refused: {e}");
                return Ok((Outcome::Unchecked { reason }, steps));
            }
        };
        if let Err(e) = sandbox.destroy() {
            let what = format!("the sandbox was not removed: {e}");
            self.tell(&Event::Problem {
                item: Some(lease.item.clone()),
                what,
            });
        }
        Ok((
            Outcome::Judged {
                state,
                commit,
                nothing,
                timed_out,
                recheck: None,
            },
            steps,
        ))
    }

    /// Runs `job` on its own thread while this one watches the stop file and keeps the lease. When the stop file
    /// appears or the lease is lost, and `group_file` names the job's process group, the group gets SIGTERM and,
    /// after `TERM_GRACE_SECS`, SIGKILL, until the job returns.
    fn watch<T: Send>(
        &mut self,
        keeper: &mut Keeper,
        group_file: Option<&Path>,
        job: impl FnOnce() -> T + Send,
    ) -> Result<(T, Watched), ClockError> {
        thread::scope(|scope| {
            let handle = scope.spawn(job);
            let mut watched = Watched::default();
            let mut failure: Option<RoomError> = None;
            let mut ending_since: Option<Instant> = None;
            let mut termed: Vec<u32> = Vec::new();
            while !handle.is_finished() {
                thread::sleep(WATCH);
                if !watched.stopped && self.room.stopped() {
                    watched.stopped = true;
                }
                let at = now();
                if !watched.lost && failure.is_none() && keeper.due(at) {
                    match self.room.renew(&keeper.lease, at) {
                        Ok(_) => keeper.last = at,
                        Err(e) if fatal(&e) => failure = Some(e),
                        Err(_) => watched.lost = true,
                    }
                }
                let ending = watched.stopped || watched.lost || failure.is_some();
                if let (true, Some(file)) = (ending, group_file) {
                    let since = *ending_since.get_or_insert_with(Instant::now);
                    // Read each time: a worker's own git runs (its seal) start groups of their own.
                    if let Some(group) = read_group(file) {
                        if since.elapsed() >= Duration::from_secs(u64::from(TERM_GRACE_SECS)) {
                            signal_group(group, "KILL");
                        } else if !termed.contains(&group) {
                            signal_group(group, "TERM");
                            termed.push(group);
                        }
                    }
                }
            }
            let value = match handle.join() {
                Ok(value) => value,
                Err(panic) => std::panic::resume_unwind(panic),
            };
            match failure {
                Some(e) => Err(e.into()),
                None => Ok((value, watched)),
            }
        })
    }

    fn record_walk(&mut self, lease: &Lease, steps: &[Step]) -> Result<(), ClockError> {
        if steps.is_empty() {
            return Ok(());
        }
        match self.room.record_walk(&lease.attempt, steps) {
            Ok(_) => Ok(()),
            Err(e) if fatal(&e) => Err(e.into()),
            Err(e) => {
                let what = format!("the walk was refused: {e}");
                self.tell(&Event::Problem {
                    item: Some(lease.item.clone()),
                    what,
                });
                Ok(())
            }
        }
    }

    /// Checks a verified pass again, in a fresh clone of the item's repository, and records what it says.
    fn recheck(&mut self, lease: &Lease, commit: &str) -> Result<Option<ItemState>, ClockError> {
        let spec = self.room.item_spec(&lease.item)?;
        let Some(frozen) = spec.frozen else {
            return Ok(None);
        };
        let checks = self.room.dir().join(CHECKS);
        let scratch = self
            .room
            .dir()
            .join(TURNS)
            .join(format!("{}.recheck", lease.attempt.0));
        let checked = remove_path(&scratch).map_err(TurnError::Io).and_then(|()| {
            check::run_check(
                &spec.repo,
                commit,
                &spec.check,
                &frozen.check_hash,
                &checks,
                &scratch,
            )
        });
        let problem = match checked {
            Ok(verdict) => match self
                .room
                .record_recheck(&lease.item, lease.lease_no, &verdict)
            {
                Ok(state) => return Ok(Some(state)),
                Err(e) if fatal(&e) => return Err(e.into()),
                Err(e) => format!("the recheck was refused: {e}"),
            },
            Err(e) => format!("the recheck could not run: {e}"),
        };
        self.tell(&Event::Problem {
            item: Some(lease.item.clone()),
            what: problem,
        });
        Ok(None)
    }

    /// Removes everything of this attempt's in `turns/`: its sandbox, its pid file, a worker's settings file and
    /// the check's scratch directories.
    fn tidy(&mut self, lease: &Lease) {
        let turns = self.room.dir().join(TURNS);
        let Ok(entries) = fs::read_dir(&turns) else {
            return;
        };
        let prefix = format!("{}.", lease.attempt.0);
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if (name == lease.attempt.0 || name.starts_with(&prefix))
                && let Err(what) = remove_path(&entry.path())
            {
                self.tell(&Event::Problem {
                    item: Some(lease.item.clone()),
                    what,
                });
            }
        }
    }
}

/// Refuses a worker whose program is not an executable file: a script's path, or `claude` or `codex` on `PATH`,
/// which a sandbox's run keeps.
fn ready(name: &str) -> Result<(), ClockError> {
    let (family, rest) = name.split_once(':').unwrap_or((name, ""));
    let program = match family {
        "script" => std::path::absolute(rest)
            .map_err(|e| ClockError::Io(format!("find {rest}: {e}")))?
            .into_os_string(),
        "claude" => worker::ClaudeWorker::new(rest).program().into(),
        "codex" => worker::CodexWorker::new(rest).program().into(),
        _ => return Ok(()),
    };
    let executable = |path: &Path| {
        fs::metadata(path).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
    };
    let program = PathBuf::from(program);
    let found = if program.components().count() > 1 {
        executable(&program)
    } else {
        std::env::var_os("PATH").is_some_and(|path| {
            std::env::split_paths(&path).any(|dir| executable(&dir.join(&program)))
        })
    };
    if found {
        Ok(())
    } else {
        Err(TurnError::Refused(format!(
            "worker {name}: {} is not an executable program here",
            program.display()
        ))
        .into())
    }
}

/// Seconds since the Unix epoch, now.
fn now() -> Ts {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| Ts::try_from(d.as_secs()).unwrap_or(Ts::MAX))
        .unwrap_or(0)
}

/// Brings `commit` from the sandbox into the item's repository and names it `name`, which must not exist yet. Each
/// lease number is fetched once, so a ref already there was not made by this clock, and is left as it is.
///
/// The clone is reclaimed from the worker first, since the git that serves the fetch reads the clone's
/// configuration. The fetch asks for the commit by its id, so what arrives is that commit and what it holds, whatever
/// the branch says by then; it writes no ref and runs no maintenance of its own. `update-ref` then refuses an object
/// the fetch did not bring, and a ref that exists.
fn fetch(sandbox: &Sandbox, repo: &Path, commit: &str, name: &str) -> Result<(), ClockError> {
    sandbox.reclaim()?;
    let fetched = [
        "fetch",
        "-q",
        "--no-tags",
        "--no-write-fetch-head",
        "--no-recurse-submodules",
        "--no-auto-maintenance",
        "--",
    ]
    .into_iter()
    .map(OsStr::new)
    .chain([sandbox.dir.as_os_str(), OsStr::new(commit)]);
    git(repo, fetched)?;
    git(repo, ["update-ref", "--no-deref", name, commit, ""])?;
    Ok(())
}

/// Runs git in `dir` with none of the clock's git environment, no system or global config, no prompt, and the
/// flags above; returns its trimmed stdout.
fn git<I, S>(dir: &Path, args: I) -> Result<String, ClockError>
where
    I: IntoIterator<Item = S>,
    S: AsRef<OsStr>,
{
    let mut command = Command::new("git");
    command.env_clear();
    for name in GIT_ENV_KEPT {
        if let Some(value) = std::env::var_os(name) {
            command.env(name, value);
        }
    }
    command
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_TERMINAL_PROMPT", "0")
        .arg("-C")
        .arg(dir)
        .args(GIT_FLAGS)
        .args(args)
        .stdin(Stdio::null());
    let out = command
        .output()
        .map_err(|e| ClockError::Git(format!("start git: {e}")))?;
    if out.status.success() {
        return Ok(String::from_utf8_lossy(&out.stdout).trim().to_string());
    }
    let stderr = String::from_utf8_lossy(&out.stderr);
    Err(ClockError::Git(stderr.trim().chars().take(300).collect()))
}

/// The process group a pid file names: a regular file holding a decimal number other than 0, 1 and this process.
/// `kill -- -0` would be this process's own group, and `-1` every process it may signal.
fn read_group(path: &Path) -> Option<u32> {
    if !fs::symlink_metadata(path).is_ok_and(|m| m.is_file()) {
        return None;
    }
    let mut text = String::new();
    fs::File::open(path)
        .ok()?
        .take(32)
        .read_to_string(&mut text)
        .ok()?;
    let text = text.trim();
    if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let group: u32 = text.parse().ok()?;
    (group > 1 && group != std::process::id()).then_some(group)
}

/// Sends `signal` to every process in `group`, through the `kill` program (there is no `unsafe` here), or the
/// shell's own `kill` where there is no such program.
fn signal_group(group: u32, signal: &str) {
    let target = format!("-{group}");
    let sent = Command::new("kill")
        .args(["-s", signal, "--", &target])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    if sent.is_err() {
        let _ = Command::new("sh")
            .args(["-c", "kill -s \"$1\" -- \"$2\"", "sh", signal, &target])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}

/// Whether any process remains in `group`. Signal 0 checks and sends nothing.
fn group_alive(group: u32) -> bool {
    Command::new("kill")
        .args(["-0", "--", &format!("-{group}")])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok_and(|s| s.success())
}

/// Removes whatever is at `path` without following a link, making directories in a tree writable where a worker
/// took that away. Nothing there is fine.
fn remove_path(path: &Path) -> Result<(), String> {
    let what = |e: std::io::Error| format!("remove {}: {e}", path.display());
    let meta = match fs::symlink_metadata(path) {
        Ok(meta) => meta,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(what(e)),
    };
    if !meta.is_dir() {
        return fs::remove_file(path).map_err(what);
    }
    if fs::remove_dir_all(path).is_ok() {
        return Ok(());
    }
    let mut stack = vec![path.to_path_buf()];
    while let Some(dir) = stack.pop() {
        if fs::symlink_metadata(&dir).is_ok_and(|m| m.is_dir()) {
            let _ = fs::set_permissions(&dir, fs::Permissions::from_mode(0o700));
            if let Ok(entries) = fs::read_dir(&dir) {
                stack.extend(entries.flatten().map(|e| e.path()));
            }
        }
    }
    fs::remove_dir_all(path).map_err(what)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_pid_file_names_a_group_only_as_a_plain_number_that_is_not_this_process_or_every_process() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("a.pid");
        let named = |text: &str| {
            fs::write(&path, text).unwrap();
            read_group(&path)
        };
        assert_eq!(named("4242"), Some(4242));
        assert_eq!(named("4242\n"), Some(4242));
        // `kill -- -0` is this process's own group and `-1` every process it may signal.
        for bad in [
            "0",
            "1",
            "-1",
            "-4242",
            "+4242",
            "",
            " ",
            "42a",
            "4294967296",
            "999999999999999999999999999999999999999999",
        ] {
            assert_eq!(named(bad), None, "{bad:?}");
        }
        assert_eq!(named(&std::process::id().to_string()), None);
        let target = dir.path().join("target");
        fs::write(&target, "4242").unwrap();
        let link = dir.path().join("link.pid");
        std::os::unix::fs::symlink(&target, &link).unwrap();
        assert_eq!(read_group(&link), None, "a link is not followed");
        assert_eq!(read_group(&dir.path().join("missing.pid")), None);
    }

    #[test]
    fn a_lease_is_renewed_every_five_minutes_or_three_times_as_often_as_it_lasts() {
        let every = |span: i64| {
            let lease = Lease {
                item: ItemId("i000000000000".into()),
                attempt: AttemptId("a000000000000".into()),
                lease_no: 1,
                worker: "script:x".into(),
                expires: 1_000 + span,
            };
            Keeper::new(&lease, 1_000).every
        };
        assert_eq!(every(room::limits::LEASE_SECS), RENEW_SECS);
        assert_eq!(every(30), 10);
        assert_eq!(every(2), 1);
        assert_eq!(every(1), 1);
        assert_eq!(every(0), 1);
    }
}
