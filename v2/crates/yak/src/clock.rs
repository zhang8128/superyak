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

use std::collections::HashMap;
use std::ffi::OsStr;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use rand::Rng;
use room::limits::{CLOCK_POLL_SECS, RECHECK_ONE_IN, TURN_SECS};
use room::{
    AttemptId, Frozen, ItemId, ItemSpec, ItemState, Lease, Room, RoomError, Step, Tokens, Ts,
};
use turn::{RunStatus, Sandbox, Seen, TurnError, check, worker};

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

/// What the clock's fetch adds to the room's git (`turn::sandbox::safe_git`): the local transport, with every
/// incoming object checked.
const FETCH_FLAGS: [&str; 4] = [
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
    /// A run could not be confirmed ended: one an earlier clock left, or one of this clock's own. The clock
    /// stops, and what is left of that run stays where it is.
    #[error(
        "a run could not be confirmed ended ({why}). Its record, {record}, is kept, and so is everything else \
         of that run: the clock removed nothing of it and starts no turn. End that run by hand, remove the \
         record, and start the clock again"
    )]
    Unrecovered { record: String, why: String },
    #[error(
        "{switch} is set, and with it the clock runs no model worker: {worker} is one. A model writes code that \
         the room then runs, and this switch turns off what holds that code"
    )]
    Unprotected {
        switch: &'static str,
        worker: String,
    },
    #[error("{0}")]
    Io(String),
}

/// What the clock did, as it does it, for whoever runs it to show. Nothing in an event comes from a transcript.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Event {
    /// Something a clock that died left was removed at the start of a run: `name` is its path in the room's
    /// directory. For a pid file, `ended` says whether the run it names was still going and was ended. A run is
    /// ended only when its leader is still the process the file describes, by number and by start time; a
    /// number that has since gone to someone else's process is never signalled.
    Cleared { name: String, ended: bool },
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
    /// The stop file ended the turn before it handed in. The item is open again, and the attempt does not count
    /// against it: a person stopped the room, and the item did nothing wrong.
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
    /// The longest one git command of the clock's own may take, in seconds.
    pub git_secs: u64,
}

impl Default for Options<'_> {
    fn default() -> Self {
        Options {
            turn_secs: TURN_SECS,
            poll: Duration::from_secs(u64::from(CLOCK_POLL_SECS)),
            report: None,
            git_secs: turn::sandbox::ROOM_GIT_SECS,
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
    // First of all, and here, so that no caller of the clock can leave it out.
    protected(
        workers,
        turn::jail::wanted(),
        !turn::sandbox::supervision_is_best_effort(),
    )?;
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
        git_limit: Duration::from_secs(options.git_secs),
        next: 0,
        unfreezable: HashMap::new(),
        ceiling_day: None,
        kept: Vec::new(),
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

/// Refuses a model worker when the jail or the watch on a run's processes is switched off. A worker that is not
/// `script:` is a model: it writes code, and the room then runs that code in a check. The two switches exist for
/// tests that run inside another sandbox, with script workers.
fn protected(workers: &[String], jailed: bool, watched: bool) -> Result<(), ClockError> {
    let switch = match (jailed, watched) {
        (true, true) => return Ok(()),
        (false, _) => "YAK_JAIL=off",
        (true, false) => "YAK_SUPERVISION=best-effort",
    };
    match workers.iter().find(|name| !name.starts_with("script:")) {
        None => Ok(()),
        Some(worker) => Err(ClockError::Unprotected {
            switch,
            worker: worker.clone(),
        }),
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
            Err(Unfrozen::Unended(stop)) => return Err(stop),
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
    /// A run of the check could not be confirmed ended. Nothing more is frozen, and the clock stops.
    Unended(ClockError),
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
    let frozen =
        check::freeze(&spec.repo, &spec.base_commit, &spec.check, &checks).map_err(|e| {
            match unended(room.dir(), &e) {
                Some(stop) => Unfrozen::Unended(stop),
                None => Unfrozen::Item(e.to_string()),
            }
        })?;
    room.record_frozen(id, frozen).map_err(store)
}

/// The clock's stop for a run that could not be confirmed ended, and nothing for any other failure. The record
/// is named as `clear_turns` names one: by its path in the room's directory.
fn unended(room_dir: &Path, e: &TurnError) -> Option<ClockError> {
    let TurnError::Unended { record, why } = e else {
        return None;
    };
    let record = Path::new(record);
    Some(ClockError::Unrecovered {
        record: record
            .strip_prefix(room_dir)
            .unwrap_or(record)
            .to_string_lossy()
            .into_owned(),
        why: why.clone(),
    })
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
    /// The longest one git command of the clock's own may take.
    git_limit: Duration,
    /// The worker whose turn it is next.
    next: usize,
    /// Drafts that failed to freeze, and when: a broken one is tried again after `FREEZE_RETRY`, not every pass.
    unfreezable: HashMap<ItemId, Instant>,
    /// The UTC day the ceiling was last reported.
    ceiling_day: Option<i64>,
    /// Paths where a sandbox or a scratch directory should have been and something else was, when the room
    /// came to remove it. They were left as they were, and tidying leaves them too, with whatever holds them.
    kept: Vec<PathBuf>,
}

/// What became of bringing a turn's commit into the item's repository.
enum Brought {
    /// It is there, and the turn's ref names it.
    Named,
    /// The room was stopped meanwhile. No ref of this turn's is left.
    Stopped,
    /// The lease is no longer this turn's. No ref of this turn's is left.
    LeaseLost,
    /// It could not be brought over or named, and why.
    Failed(String),
}

/// One turn: its lease, and what `work` made for it.
#[derive(Clone, Copy)]
struct Turn<'a> {
    lease: &'a Lease,
    taken_at: Ts,
    sandbox: &'a Sandbox,
    title: &'a str,
    spec: &'a ItemSpec,
    frozen: &'a Frozen,
    turns: &'a Path,
    branch: &'a str,
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

    /// Ends the runs a dead clock left going, then removes whatever is in `turns/` and the scratch a freeze
    /// leaves in `checks/` (`.work-*`, `.freeze-*`). The room's writer lock is held, so all of it is from a clock
    /// that died. Its sandboxes are never fetched from. A run is ended before its sandbox is removed from under
    /// it, and if one cannot be ended the clock stops here: that run's record and directories stay as they are,
    /// and so does every other directory. The records of runs already ended by then are gone, each removed as
    /// its run was known to be over.
    ///
    /// What is removed here is removed by where it is. A dead clock's memory of which directory it made is gone
    /// with it, so the check a live turn makes before removing its sandbox cannot be made.
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
        let room_dir = self.room.dir().to_path_buf();
        let name = |path: &Path| {
            path.strip_prefix(&room_dir)
                .unwrap_or(path)
                .to_string_lossy()
                .into_owned()
        };
        // A record is acted on only when it is one the room wrote: named for an attempt the room made, or for a
        // freeze's own work in `checks/`. A file that only looks like one names a process, and ending a process
        // on the word of a file anyone could have put there is not the clock's to do.
        let mut ended = Vec::new();
        for path in paths.iter().filter(|p| is_pid_file(p)) {
            let file = path.file_name().unwrap_or_default().to_string_lossy();
            let in_checks = path.parent().is_some_and(|dir| dir.ends_with(CHECKS));
            let attempt = AttemptId(file.split('.').next().unwrap_or_default().to_string());
            if !in_checks && !self.room.knows_attempt(&attempt)? {
                let what = format!(
                    "{} is named for no attempt of this room: removed unread, and nothing was ended on its word",
                    name(path)
                );
                self.tell(&Event::Problem { item: None, what });
                continue;
            }
            match Sandbox::end_stale(path) {
                Ok(true) => ended.push(path.clone()),
                Ok(false) => {}
                // Nothing is removed and no turn starts: the run may still be going, and its record and its
                // sandbox are what a person needs to find it.
                Err(e) => {
                    return Err(ClockError::Unrecovered {
                        record: name(path),
                        why: e.to_string(),
                    });
                }
            }
        }
        for path in paths {
            let event = match remove_path(&path) {
                Ok(()) => Event::Cleared {
                    name: name(&path),
                    ended: ended.contains(&path),
                },
                Err(what) => Event::Problem { item: None, what },
            };
            self.tell(&event);
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
                Err(Unfrozen::Unended(stop)) => return Err(stop),
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
        // After a run that could not be ended nothing is tidied: its record and its directories are what is
        // left to find it by.
        if !matches!(result, Err(ClockError::Unrecovered { .. })) {
            self.tidy(&lease);
        }
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
        // The pid file is for a clock that starts after this one died. This clock ends its own turn with the
        // sandbox's switch.
        sandbox.set_pid_file(turns.join(format!("{}.pid", lease.attempt.0)));
        let turn = Turn {
            lease,
            taken_at,
            sandbox: &sandbox,
            title: &title,
            spec: &spec,
            frozen: &frozen,
            turns: &turns,
            branch: &branch,
        };
        let outcome = self.work_in(&turn);
        // A run that could not be ended may still be using the sandbox: it stays.
        if matches!(outcome, Err(ClockError::Unrecovered { .. })) {
            return outcome;
        }
        // Otherwise the sandbox goes whatever became of the turn, and by the sandbox's own rule: only what the
        // room made there. Something else found at its path is left, and tidying leaves it too.
        if let Err(e) = sandbox.destroy() {
            self.keep(&e);
            self.tell(&Event::Problem {
                item: Some(lease.item.clone()),
                what: format!("the sandbox was not removed: {e}"),
            });
        }
        outcome
    }

    /// The turn itself, in a sandbox that `work` made and removes.
    fn work_in(&mut self, turn: &Turn<'_>) -> Result<(Outcome, Vec<Step>), ClockError> {
        let Turn {
            lease,
            taken_at,
            sandbox,
            title,
            spec,
            frozen,
            turns,
            branch: _,
        } = *turn;
        let stop = sandbox.stop_switch();
        let mut keeper = Keeper::new(lease, taken_at);

        let mut seen = Seen {
            steps: Vec::new(),
            tokens: Tokens::none(),
            steps_seen: 0,
        };
        let ran = {
            let (name, limit) = (&lease.worker, self.turn_secs);
            let command = &spec.check.command;
            let seen = &mut seen;
            // A worker is not `Send`, so it is made where it runs.
            let job = move || -> Result<RunStatus, TurnError> {
                worker::from_name(name)?.run(sandbox, title, command, limit, seen)
            };
            self.watch(&mut keeper, Some(&stop), job)
        };
        let (ran, watched, store_failed) = ran;
        if let Err(e) = &ran
            && let Some(stop) = unended(self.room.dir(), e)
        {
            // The run comes first: the clock stops for it, with the turn's files in place, whatever the store did.
            self.also_failed(lease, &store_failed);
            return Err(stop);
        }
        if let Some(e) = store_failed {
            return Err(e.into());
        }
        let (steps, timed_out, failure) = match ran {
            Ok(status) => (seen.steps, status.timed_out, None),
            Err(e) => (Vec::new(), false, Some(e.to_string())),
        };
        let failure_said = failure.clone();
        if watched.stopped {
            return self.stopped(lease, steps);
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
        // The commit is brought into the item's repository before the hand-in, so that what is handed in is always
        // there for the check to clone; a commit that cannot be brought over is a turn that handed in nothing, and
        // fails. A renewal first makes sure the lease is still this turn's.
        if commit != base {
            match self.room.renew(lease, now()) {
                Ok(_) => keeper.last = now(),
                Err(e) if fatal(&e) => return Err(e.into()),
                Err(_) => return Ok((Outcome::LeaseLost, steps)),
            }
            match self.bring(&mut keeper, turn, &commit)? {
                Brought::Named => {}
                Brought::Stopped => return self.stopped(lease, steps),
                Brought::LeaseLost => return Ok((Outcome::LeaseLost, steps)),
                Brought::Failed(why) => {
                    nothing = Some(format!("its commit could not be fetched: {why}"));
                    commit = base.clone();
                }
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
            // The check is not ended by the stop file: its sandbox is its own, and its time limit bounds it. Its
            // lease is kept so that it stays this turn's for anyone reading the room; a renewal refused while the
            // check runs (the machine slept) does not throw the verdict away, since the hand-in was made under a
            // live lease and `record_verdict` refuses one whose lease number moved on.
            self.watch(&mut keeper, None, job)
        };
        let (checked, _, store_failed) = checked;
        // First what the check's own failure asks of the clock, whatever the store did: to stop for a run that
        // may still be going, and to remember what was left in place.
        if let Err(e) = &checked {
            if matches!(e, TurnError::Unended { .. }) {
                self.also_failed(lease, &store_failed);
            }
            self.check_failed(e)?;
        }
        if let Some(e) = store_failed {
            return Err(e.into());
        }
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

    /// Brings the turn's commit into the item's repository and names it `refs/heads/<branch>`: a fetch, which
    /// writes no ref, then the ref.
    ///
    /// The clock's git can take a while (its limit is `git_limit`), so each of the two is watched as the worker
    /// was: the lease is kept renewed while it runs, and it is ended, its whole group, as soon as the room is
    /// stopped or the lease is lost. After each, whatever it returned, the room itself is asked: is it stopped,
    /// and is the lease still this turn's? So a turn makes its ref only under a lease it holds, in a room that
    /// is not stopped; and when either changed while the ref was being made, the ref is taken back before the
    /// turn ends. A stop is seen even when the fetch failed: no check is started after it.
    ///
    /// The ref is this turn's only if its name was free when the turn came to make it. A name already taken is
    /// left as it is, also when the room is stopped or the lease is lost at that moment. Nothing else is taken
    /// to write `refs/heads/room/` in the item's repository while the clock runs.
    fn bring(
        &mut self,
        keeper: &mut Keeper,
        turn: &Turn<'_>,
        commit: &str,
    ) -> Result<Brought, ClockError> {
        let (lease, sandbox, repo) = (turn.lease, turn.sandbox, &turn.spec.repo);
        let name = format!("refs/heads/{}", turn.branch);
        let limit = self.git_limit;

        let halt = AtomicBool::new(false);
        let (fetched, _, store_failed) = {
            let halt = &halt;
            let job = move || fetch(sandbox, repo, commit, limit, halt).map_err(|e| e.to_string());
            self.watch(keeper, Some(halt), job)
        };
        // No ref yet, so nothing to take back.
        if let Some(e) = store_failed {
            return Err(e.into());
        }
        if let Some(ended) = self.no_longer_ours(keeper, lease)? {
            return Ok(ended);
        }
        if let Err(why) = fetched {
            return Ok(Brought::Failed(why));
        }

        let halt = AtomicBool::new(false);
        let ((free, named), _, store_failed) = {
            let (halt, name) = (&halt, name.as_str());
            let job = move || {
                // A name that is taken is not this turn's to make, and never its to take back, whatever commit
                // it names: a worker can hand in a commit that was in the repository all along.
                match taken(repo, name, limit, halt) {
                    Ok(false) => (
                        true,
                        publish(repo, name, commit, limit, halt).map_err(|e| e.to_string()),
                    ),
                    Ok(true) => (false, Err(format!("{name} is already there"))),
                    Err(e) => (false, Err(e.to_string())),
                }
            };
            self.watch(keeper, Some(halt), job)
        };
        // Where the name was free, a ref there now is this turn's, and whatever ends the turn from here takes it
        // back first: a git that was ended may or may not have made it, so it is asked to go either way.
        let ended = match store_failed {
            Some(e) => Err(e.into()),
            None => self.no_longer_ours(keeper, lease),
        };
        match ended {
            Ok(None) => {}
            ended => {
                if free {
                    self.unpublish(lease, repo, &name, commit);
                }
                return ended.map(|ended| ended.unwrap_or(Brought::Stopped));
            }
        }
        Ok(match named {
            Ok(()) => Brought::Named,
            Err(why) => Brought::Failed(why),
        })
    }

    /// Asks the room whether a turn should end where it is: `Stopped` when the stop file is there, `LeaseLost`
    /// when a renewal is refused, and nothing when the lease was renewed.
    fn no_longer_ours(
        &mut self,
        keeper: &mut Keeper,
        lease: &Lease,
    ) -> Result<Option<Brought>, ClockError> {
        if self.room.stopped() {
            return Ok(Some(Brought::Stopped));
        }
        match self.room.renew(lease, now()) {
            Ok(_) => {
                keeper.last = now();
                Ok(None)
            }
            Err(e) if fatal(&e) => Err(e.into()),
            Err(_) => Ok(Some(Brought::LeaseLost)),
        }
    }

    /// Takes back the ref of a turn that then hands nothing in. Called only when the name was free before the
    /// turn came to make it (`bring`), so a ref there now is the turn's own. It is removed only while it names
    /// this turn's commit, and one that cannot be taken back is said.
    fn unpublish(&mut self, lease: &Lease, repo: &Path, name: &str, commit: &str) {
        let go = AtomicBool::new(false);
        let limit = self.git_limit;
        // With the commit given, git removes the ref only while it names that commit.
        let removed = git(
            repo,
            ["update-ref", "--no-deref", "-d", name, commit],
            limit,
            &go,
        );
        let Err(why) = removed else {
            return;
        };
        // Not removed. If no ref of that name names this commit, there was nothing of this turn's to take back.
        let named = git(
            repo,
            ["for-each-ref", "--format=%(objectname)", name],
            limit,
            &go,
        );
        if matches!(&named, Ok(names) if names != commit) {
            return;
        }
        self.tell(&Event::Problem {
            item: Some(lease.item.clone()),
            what: format!(
                "{name} was made for a turn that handed nothing in, and could not be removed: {why}"
            ),
        });
    }

    /// Says that the room's store failed as well, when the clock is about to stop for a run it could not end:
    /// the stop is all the caller is given, and the store's failure is why the run was being ended.
    fn also_failed(&mut self, lease: &Lease, store_failed: &Option<RoomError>) {
        if let Some(e) = store_failed {
            self.tell(&Event::Problem {
                item: Some(lease.item.clone()),
                what: format!("the room's store failed as well: {e}"),
            });
        }
    }

    /// What a check that gave no verdict asks of the clock, whatever else is then done about it: to stop, when
    /// its run could not be confirmed ended; and to leave in place what its sandbox's removal left.
    fn check_failed(&mut self, e: &TurnError) -> Result<(), ClockError> {
        if let Some(stop) = unended(self.room.dir(), e) {
            return Err(stop);
        }
        self.keep(e);
        Ok(())
    }

    /// Remembers what a removal left in place (`TurnError::Left`), so that tidying leaves it too. Each is kept
    /// under every name the disk has for it (`spelled`), which is how tidying meets it again: a sandbox knows
    /// the name it would have made, and what was found in its place may be kept in other letters.
    fn keep(&mut self, e: &TurnError) {
        if let TurnError::Left { paths, .. } = e {
            self.kept
                .extend(paths.iter().flat_map(|path| spelled(path)));
        }
    }

    /// A turn the stop file ended. A person stopped the room, so the attempt does not count against the item, and
    /// the item does not wait out its lease. A release the room refuses (the lease just ran out) leaves that to
    /// expiry.
    fn stopped(
        &mut self,
        lease: &Lease,
        steps: Vec<Step>,
    ) -> Result<(Outcome, Vec<Step>), ClockError> {
        match self.room.release(lease, now()) {
            Err(e) if fatal(&e) => Err(e.into()),
            Ok(()) | Err(_) => Ok((Outcome::Stopped, steps)),
        }
    }

    /// Runs `job` on its own thread while this one watches the stop file and keeps the lease. When the stop file
    /// appears, the lease is lost or the room's store fails, `stop` is set: the sandbox then ends its run (SIGTERM
    /// to the group, SIGKILL after `TERM_GRACE_SECS`, and the descendants it saw) and starts no other, so the job
    /// returns.
    ///
    /// What the job returned always comes back, and a failure of the room's store comes back beside it, never
    /// in its place. The job may be saying that a run could not be confirmed ended, or that something was left
    /// where a sandbox should be; the caller acts on that first, and ends the clock for the store after.
    fn watch<T: Send>(
        &mut self,
        keeper: &mut Keeper,
        stop: Option<&AtomicBool>,
        job: impl FnOnce() -> T + Send,
    ) -> (T, Watched, Option<RoomError>) {
        thread::scope(|scope| {
            let handle = scope.spawn(job);
            let mut watched = Watched::default();
            let mut failure: Option<RoomError> = None;
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
                if let (true, Some(stop)) =
                    (watched.stopped || watched.lost || failure.is_some(), stop)
                {
                    stop.store(true, Ordering::Relaxed);
                }
            }
            let value = match handle.join() {
                Ok(value) => value,
                Err(panic) => std::panic::resume_unwind(panic),
            };
            (value, watched, failure)
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
            Err(e) => {
                self.check_failed(&e)?;
                format!("the recheck could not run: {e}")
            }
        };
        self.tell(&Event::Problem {
            item: Some(lease.item.clone()),
            what: problem,
        });
        Ok(None)
    }

    /// Removes everything of this attempt's in `turns/`: its pid file, a worker's settings file, the check's
    /// scratch directories, and what is left of its sandbox when a turn ended before removing it. What a removal
    /// left in place, because it was not what the room made there, is left here too: a sandbox, a scratch
    /// directory, or a check's work directory that holds one.
    fn tidy(&mut self, lease: &Lease) {
        let turns = self.room.dir().join(TURNS);
        let Ok(entries) = fs::read_dir(&turns) else {
            return;
        };
        let prefix = format!("{}.", lease.attempt.0);
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            // What was left in place stays, and so does a directory that holds it.
            let path = placed(&entry.path());
            let left_in_place = self.kept.iter().any(|kept| kept.starts_with(&path));
            if (name == lease.attempt.0 || name.starts_with(&prefix))
                && !left_in_place
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

/// Brings `commit` from the sandbox into the item's repository, and names nothing yet.
///
/// The clone is reclaimed from the worker first, since the git that serves the fetch reads the clone's
/// configuration. The fetch asks for the commit by its id, so what arrives is that commit and what it holds, whatever
/// the branch says by then; it writes no ref and runs no maintenance of its own.
fn fetch(
    sandbox: &Sandbox,
    repo: &Path,
    commit: &str,
    limit: Duration,
    stop: &AtomicBool,
) -> Result<(), ClockError> {
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
    git(repo, fetched, limit, stop)?;
    Ok(())
}

/// Names a fetched commit `name` in the item's repository. The name must not exist yet: each lease number is
/// fetched once, so a ref already there was not made by this clock, and is left as it is. An object the fetch
/// did not bring is refused too.
fn publish(
    repo: &Path,
    name: &str,
    commit: &str,
    limit: Duration,
    stop: &AtomicBool,
) -> Result<(), ClockError> {
    git(
        repo,
        ["update-ref", "--no-deref", name, commit, ""],
        limit,
        stop,
    )?;
    Ok(())
}

/// Whether the ref name `name` is taken in `repo`. A ref that names a commit is, and so is a symbolic ref,
/// also one that names nothing: a listing of refs leaves that kind out, and making a ref of its name would
/// write over it. A question git cannot answer is an error, and the name is then not made.
fn taken(repo: &Path, name: &str, limit: Duration, stop: &AtomicBool) -> Result<bool, ClockError> {
    let mut asked = turn::sandbox::safe_git();
    asked.arg("-C").arg(repo).args(["symbolic-ref", "-q", name]);
    // git says "it is one" with 0 and "it is not" with 1.
    match turn::sandbox::safe_git_code_until(asked, "the clock's git", limit, stop) {
        Ok((Some(0), _)) => return Ok(true),
        Ok((Some(1), _)) => {}
        Ok((code, _)) => {
            return Err(ClockError::Git(format!(
                "symbolic-ref could not say what {name} is (it ended with {code:?})"
            )));
        }
        Err(e) => return Err(ClockError::Git(e.to_string())),
    }
    let listed = git(
        repo,
        ["for-each-ref", "--format=%(refname)", name],
        limit,
        stop,
    )?;
    Ok(!listed.is_empty())
}

/// Runs the room's git in `dir`, with what the fetch needs added, for at most `limit` and until `stop` is set;
/// returns its trimmed stdout.
fn git<I, S>(dir: &Path, args: I, limit: Duration, stop: &AtomicBool) -> Result<String, ClockError>
where
    I: IntoIterator<Item = S>,
    S: AsRef<OsStr>,
{
    let mut command = turn::sandbox::safe_git();
    command.arg("-C").arg(dir).args(FETCH_FLAGS).args(args);
    match turn::sandbox::safe_git_output_until(command, "the clock's git", limit, stop) {
        Ok(out) => Ok(String::from_utf8_lossy(&out).trim().to_string()),
        Err(TurnError::Git(why)) => Err(ClockError::Git(why)),
        Err(e) => Err(ClockError::Git(e.to_string())),
    }
}

/// `path` with the directory it is in resolved and its own name kept as it is, so that two spellings of one
/// place compare equal, and a link found at that place is named and not followed.
fn placed(path: &Path) -> PathBuf {
    match (path.parent().map(fs::canonicalize), path.file_name()) {
        (Some(Ok(dir)), Some(name)) => dir.join(name),
        _ => path.to_path_buf(),
    }
}

/// Every name `path` goes by in the directory it is in, as the disk spells them, with the directory resolved.
/// The entries are found by which file they are, not by their letters: on a disk where capital and small
/// letters name the same file, `a.scratch` may be kept as `a.SCRATCH`. And a file can have more than one name
/// in a directory, so all of them are kept, and the name as it was given with them: picking one could pick the
/// wrong one. A link at that place is named and not followed.
fn spelled(path: &Path) -> Vec<PathBuf> {
    use std::os::unix::fs::MetadataExt;
    let (Some(Ok(dir)), Ok(this)) = (
        path.parent().map(fs::canonicalize),
        fs::symlink_metadata(path),
    ) else {
        return vec![placed(path)];
    };
    let listed = fs::read_dir(&dir)
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|entry| {
            let other = entry.metadata().ok()?;
            Some((entry.path(), (other.dev(), other.ino())))
        });
    spellings(placed(path), (this.dev(), this.ino()), listed)
}

/// `given`, and every listed name of the same file. Kept apart from the listing so that it can be tried with a
/// listing in any order.
fn spellings(
    given: PathBuf,
    file: (u64, u64),
    listed: impl Iterator<Item = (PathBuf, (u64, u64))>,
) -> Vec<PathBuf> {
    let mut names = vec![given];
    for (name, other) in listed {
        if other == file && !names.contains(&name) {
            names.push(name);
        }
    }
    names
}

/// Whether `path` is a pid file a turn left: a plain file named `<attempt>.pid`. A link is never one.
fn is_pid_file(path: &Path) -> bool {
    path.extension().is_some_and(|x| x == "pid")
        && fs::symlink_metadata(path).is_ok_and(|m| m.is_file())
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

    /// A kept file is remembered by the name it was given and by every other name it has, whichever comes
    /// first in the listing.
    #[test]
    fn a_kept_file_is_remembered_by_every_name_it_has() {
        let name = |text: &str| PathBuf::from(text);
        let (kept, other) = ((1, 7), (1, 8));
        let both_ways = [
            vec![
                (name("/t/other-name"), kept),
                (name("/t/a.scratch"), kept),
                (name("/t/b"), other),
            ],
            vec![
                (name("/t/b"), other),
                (name("/t/a.scratch"), kept),
                (name("/t/other-name"), kept),
            ],
        ];
        for listing in both_ways {
            let names = spellings(name("/t/a.scratch"), kept, listing.into_iter());
            assert!(names.contains(&name("/t/a.scratch")), "{names:?}");
            assert!(names.contains(&name("/t/other-name")), "{names:?}");
            assert!(!names.contains(&name("/t/b")), "{names:?}");
            assert_eq!(names.len(), 2, "{names:?}");
        }
        // Three names for one file: all three, and not only the first other one met.
        let listing = [
            (name("/t/0-other"), kept),
            (name("/t/a.scratch"), kept),
            (name("/t/zz-other"), kept),
        ];
        let names = spellings(name("/t/a.scratch"), kept, listing.into_iter());
        assert_eq!(names.len(), 3, "{names:?}");
        // Kept in other letters than it was given: both spellings, so whichever tidying meets is left.
        let names = spellings(
            name("/t/a.scratch"),
            kept,
            [(name("/t/a.SCRATCH"), kept)].into_iter(),
        );
        assert_eq!(names, [name("/t/a.scratch"), name("/t/a.SCRATCH")]);
        // Not listed at all: the name as given.
        assert_eq!(
            spellings(name("/t/gone"), kept, std::iter::empty()),
            [name("/t/gone")]
        );
    }

    #[test]
    fn a_pid_file_is_a_plain_file_with_that_ending_and_never_a_link() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("a1.pid");
        fs::write(&file, "4242\nstart\n").unwrap();
        assert!(is_pid_file(&file));
        let other = dir.path().join("a1.check");
        fs::write(&other, "").unwrap();
        assert!(!is_pid_file(&other));
        let link = dir.path().join("a2.pid");
        std::os::unix::fs::symlink(&file, &link).unwrap();
        assert!(!is_pid_file(&link));
        let folder = dir.path().join("a3.pid");
        fs::create_dir(&folder).unwrap();
        assert!(!is_pid_file(&folder));
        assert!(!is_pid_file(&dir.path().join("missing.pid")));
    }

    #[test]
    fn a_model_worker_needs_both_protections_and_a_script_worker_neither() {
        let names =
            |workers: &[&str]| -> Vec<String> { workers.iter().map(|w| w.to_string()).collect() };
        let models = names(&["script:/x", "codex:gpt-6.1-sol"]);
        let scripts = names(&["script:/x", "script:/y"]);
        assert!(protected(&models, true, true).is_ok());
        for (jailed, watched, switch) in [
            (false, true, "YAK_JAIL=off"),
            (true, false, "YAK_SUPERVISION=best-effort"),
            (false, false, "YAK_JAIL=off"),
        ] {
            assert!(protected(&scripts, jailed, watched).is_ok());
            let refused = protected(&models, jailed, watched);
            assert!(
                matches!(&refused, Err(ClockError::Unprotected { switch: s, worker })
                    if *s == switch && worker == "codex:gpt-6.1-sol"),
                "{refused:?}"
            );
        }
        // A name that is not a script is treated as a model, whatever it says.
        assert!(protected(&names(&["scripts:/x"]), false, true).is_err());
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
