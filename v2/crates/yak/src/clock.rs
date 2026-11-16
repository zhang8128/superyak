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

use std::collections::{BTreeMap, HashMap};
use std::ffi::OsStr;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use rand::Rng;
use room::limits::{CLOCK_POLL_SECS, RECHECK_ONE_IN, TURN_SECS};
use room::offer::{Arm, Block, Offer, Offered};
use room::{
    AttemptId, Change, ChangedFile, Ended, Frozen, ItemId, ItemSpec, ItemState, Lease, Measured,
    Room, RoomError, Tokens, Ts,
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

#[derive(Clone, Copy)]
enum Phase {
    Sandbox,
    Worker,
    Seal,
    Bring,
    Check,
}

/// All phase boundaries use one monotonic origin. Round the cumulative time, so the parts add up.
struct Phases {
    start: Instant,
    last_ms: u64,
    phase: Phase,
}

impl Phases {
    fn at(start: Instant) -> Self {
        Self {
            start,
            last_ms: 0,
            phase: Phase::Sandbox,
        }
    }

    fn close_at(&mut self, at: Instant, m: &mut Measured) {
        let total = millis(at.duration_since(self.start));
        let elapsed = total - self.last_ms;
        match self.phase {
            Phase::Sandbox => m.sandbox_ms += elapsed,
            Phase::Worker => m.worker_ms += elapsed,
            Phase::Seal => m.seal_ms += elapsed,
            Phase::Bring => m.bring_ms += elapsed,
            Phase::Check => m.check_ms = Some(m.check_ms.unwrap_or(0) + elapsed),
        }
        self.last_ms = total;
        m.active_ms = total;
    }

    fn advance_to(&mut self, phase: Phase, at: Instant, m: &mut Measured) {
        self.close_at(at, m);
        self.phase = phase;
    }
}

fn millis(duration: Duration) -> u64 {
    duration.as_millis().try_into().unwrap_or(u64::MAX)
}

fn empty_measured() -> Measured {
    Measured {
        ended: Ended::NotRun,
        exit_code: None,
        tokens: Tokens::none(),
        steps_seen: 0,
        unknown_steps: 0,
        unknown_changes: 0,
        sandbox_ms: 0,
        worker_ms: 0,
        seal_ms: 0,
        bring_ms: 0,
        check_ms: None,
        recheck_ms: None,
        active_ms: 0,
    }
}

struct TurnRecord {
    timer: Option<Phases>,
    seen: Seen,
    measured: Measured,
    /// What came of writing the record, once `work` has written it, before it removes the sandbox.
    saved: Option<Result<(), RoomError>>,
}

impl TurnRecord {
    fn new() -> Self {
        Self {
            timer: None,
            seen: Seen {
                steps: Vec::new(),
                tokens: Tokens::none(),
                steps_seen: 0,
                started: Instant::now(),
                seal_ms: 0,
                status: None,
            },
            measured: empty_measured(),
            saved: None,
        }
    }

    /// The turn starts at `at`, the moment before its sandbox is made: its phases and its steps' times count
    /// from that one moment.
    fn start(&mut self, at: Instant) {
        self.timer = Some(Phases::at(at));
        self.seen.started = at;
    }

    fn advance(&mut self, phase: Phase) {
        if let Some(timer) = &mut self.timer {
            timer.advance_to(phase, Instant::now(), &mut self.measured);
        }
    }

    /// Ends the worker's phase. The room's commit on the worker's behalf ran inside it, and the worker timed
    /// that commit (`Seen::seal_ms`), so its time goes to the seal: the parts still add up.
    fn worker_done(&mut self) {
        self.worker_done_at(Instant::now());
    }

    fn worker_done_at(&mut self, at: Instant) {
        if let Some(timer) = &mut self.timer {
            timer.advance_to(Phase::Seal, at, &mut self.measured);
        }
        let sealed = self.seen.seal_ms.min(self.measured.worker_ms);
        self.measured.worker_ms -= sealed;
        self.measured.seal_ms += sealed;
    }

    fn close(&mut self) {
        if let Some(mut timer) = self.timer.take() {
            timer.close_at(Instant::now(), &mut self.measured);
        }
    }

    /// Closes the timer and takes what the worker's program reported. How the worker ended was set where it
    /// ended: what became of the turn after that does not change it.
    fn finish(&mut self) {
        self.close();
        self.measured.tokens = self.seen.tokens.clone();
        self.measured.steps_seen = self.seen.steps_seen;
    }
}

/// Writes a turn's walk and its measured record. A store that fails is the caller's error. A walk the room
/// refuses for what is in it is not: it is returned for the caller to say, and the measured record is written
/// all the same, with every step it saw unknown, since none was kept.
fn persist_turn(
    room: &mut Room,
    attempt: &AttemptId,
    record: &mut TurnRecord,
) -> Result<Option<RoomError>, RoomError> {
    let refused = match room.record_walk(attempt, &record.seen.steps) {
        Ok(_) => None,
        Err(e) if fatal(&e) => return Err(e),
        Err(e) => Some(e),
    };
    let kept = room.walk(attempt)?;
    let by_seq: HashMap<_, _> = kept.iter().map(|step| (step.seq, step)).collect();
    // A step is unknown if any of its names was omitted, or if it has no known file. Include dropped steps.
    let known = record
        .seen
        .steps
        .iter()
        .filter(|seen| {
            by_seq.get(&seen.seq).is_some_and(|kept| {
                seen.named.len() == kept.named.len()
                    && seen.target == kept.target
                    && (!kept.named.is_empty()
                        || matches!(kept.target, room::Target::TrackedFile { .. }))
            })
        })
        .count() as u64;
    record.measured.unknown_steps = record.seen.steps_seen.saturating_sub(known);
    room.record_measured(attempt, &record.measured)?;
    Ok(refused)
}

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
    /// The offer could not be made into a block for every item a turn may still be given. No turn was started.
    #[error("{0}; the clock started no turn")]
    Offer(String),
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
    /// Whether each turn's prompt begins with a line of that turn's own (its attempt's id). Off unless asked
    /// for: it is there to measure what a worker's program keeps of a prompt it has seen before.
    pub own_prompts: bool,
    /// The experiment's arm for every turn of this clock, and what is kept with each. None: the clock is as it
    /// was, and its turns keep nothing of an offer.
    pub offer: Option<Offering>,
}

/// What every turn of a clock is given beside its prompt, as asked for: an arm; for an arm that offers, the offer
/// read from its file; this clock's place in the experiment's order; and the seed of its draw.
pub struct Offering {
    pub arm: Arm,
    pub offer: Option<Offer>,
    pub order: u32,
    pub seed: u64,
}

/// What `Offering` came to, once, before any turn: the block every turn of the clock is given, when its arm
/// offers one, and the record kept with each turn.
struct Given {
    block: Option<Block>,
    offered: Offered,
}

impl Default for Options<'_> {
    fn default() -> Self {
        Options {
            turn_secs: TURN_SECS,
            poll: Duration::from_secs(u64::from(CLOCK_POLL_SECS)),
            report: None,
            git_secs: turn::sandbox::ROOM_GIT_SECS,
            own_prompts: false,
            offer: None,
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
    // The block is made here, once, before any turn: every turn of this clock is given the same one.
    let git_limit = Duration::from_secs(options.git_secs);
    let given = match &options.offer {
        Some(offering) => Some(give(room, offering, git_limit)?),
        None => None,
    };
    let mut clock = Clock {
        room,
        workers,
        turn_secs: options.turn_secs,
        poll: options.poll,
        report: options.report,
        git_limit,
        own_prompts: options.own_prompts,
        given,
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

/// Makes what every turn of the clock is given, or refuses it before any turn: the block, from the offer and the
/// arm, and the record of how it was made. Every path the offer names is checked at the base of each item a turn
/// may still be given (any item not passed and not abandoned), by the room's own listing of that base; a path
/// that fails refuses the whole offer.
fn give(room: &Room, offering: &Offering, git_limit: Duration) -> Result<Given, ClockError> {
    let (block, offered) = room::offer::give(
        offering.arm,
        offering.offer.as_ref(),
        offering.order,
        offering.seed,
    )
    .map_err(|e| ClockError::Offer(e.to_string()))?;
    if let Some(offer) = &offering.offer {
        // Each base once, named by the first item at it.
        let mut bases: BTreeMap<(PathBuf, String), ItemId> = BTreeMap::new();
        for item in room.items()? {
            if matches!(
                item.state,
                ItemState::PassedVerified | ItemState::PassedUnverified | ItemState::Abandoned
            ) {
                continue;
            }
            let spec = room.item_spec(&item.id)?;
            bases
                .entry((spec.repo, spec.base_commit))
                .or_insert(item.id);
        }
        for ((repo, base), item) in bases {
            let tracked = crate::offer::tracked_at(&repo, &base, git_limit).map_err(|e| {
                ClockError::Offer(format!(
                    "the files tracked at the base of {} could not be listed: {e}",
                    item.0
                ))
            })?;
            offer
                .check_tracked(&|path| tracked.contains(path))
                .map_err(|e| ClockError::Offer(format!("{e}, at the base of {}", item.0)))?;
        }
    }
    Ok(Given { block, offered })
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
            | RoomError::OlderSchema { .. }
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
    /// Whether each turn's prompt begins with a line of its own.
    own_prompts: bool,
    /// The block each turn is given and the record kept with each, when the clock was given an arm.
    given: Option<Given>,
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
    Named(Vec<ChangedFile>),
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
        let result = self.attempt(&lease, taken_at, rng, worker::from_name);
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
        make_worker: impl FnOnce(&str) -> Result<Box<dyn turn::Worker>, TurnError> + Send,
    ) -> Result<Outcome, ClockError> {
        // What the turn is given is kept before it is given.
        if let Some(given) = &self.given {
            self.room.record_offer(&lease.attempt, &given.offered)?;
        }
        let mut record = TurnRecord::new();
        let outcome = self.work(lease, taken_at, &mut record, make_worker);
        // `work` writes the record before it removes the sandbox; a turn that never had one is written here.
        let saved = match record.saved.take() {
            Some(saved) => saved,
            None => self.persist(lease, &mut record),
        };
        // An unended process remains the primary error, even if its store failed too.
        if let Err(error) = outcome {
            if let Err(store) = saved {
                self.tell(&Event::Problem {
                    item: Some(lease.item.clone()),
                    what: format!("the turn record could not be written: {store}"),
                });
            }
            return Err(error);
        }
        saved?;
        let outcome = outcome?;
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
            let start = Instant::now();
            let result = self.recheck(lease, &commit);
            self.room
                .record_recheck_ms(&lease.attempt, millis(start.elapsed()))?;
            result?
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

    /// Writes the turn's record (`persist_turn`), and says a walk the room refused.
    fn persist(&mut self, lease: &Lease, record: &mut TurnRecord) -> Result<(), RoomError> {
        record.finish();
        let refused = persist_turn(self.room, &lease.attempt, record)?;
        if let Some(e) = refused {
            self.tell(&Event::Problem {
                item: Some(lease.item.clone()),
                what: format!(
                    "the turn's walk was refused, and its record was written without it: {e}"
                ),
            });
        }
        Ok(())
    }

    /// Runs the worker and judges its commit. The record stays with the caller across every return, and once a
    /// sandbox was made it is written here, before the sandbox is removed.
    fn work(
        &mut self,
        lease: &Lease,
        taken_at: Ts,
        record: &mut TurnRecord,
        make_worker: impl FnOnce(&str) -> Result<Box<dyn turn::Worker>, TurnError> + Send,
    ) -> Result<Outcome, ClockError> {
        let title = self.room.item(&lease.item)?.title;
        let spec = self.room.item_spec(&lease.item)?;
        let Some(frozen) = spec.frozen.clone() else {
            // `take` never leases an item without a frozen check; this is not reached.
            return Ok(Outcome::NotRun {
                reason: "the item has no frozen check".into(),
            });
        };
        let turns = self.room.dir().join(TURNS);
        fs::create_dir_all(&turns)
            .map_err(|e| ClockError::Io(format!("make {}: {e}", turns.display())))?;
        let room_dir = fs::canonicalize(self.room.dir())
            .map_err(|e| ClockError::Io(format!("find {}: {e}", self.room.dir().display())))?;
        let branch = format!("room/{}/{}", lease.item.0, lease.lease_no);
        record.start(Instant::now());
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
                return Ok(Outcome::NotRun { reason });
            }
        };
        // The block this clock made before its first turn, the same for every turn of it.
        if let Some(block) = self.given.as_ref().and_then(|given| given.block.clone()) {
            sandbox.give_block(block);
        }
        // No worker's shell may read the room's own directory: the store, the other turns' directories, the
        // checks. It was found a moment ago, so this fails only if it went away since; then no worker runs.
        // And when the clock was asked for it, the turn is named by its attempt's id, for its prompt's first
        // line: the id is the room's own, so that does not fail.
        let prepared = sandbox.hide_from_worker(&room_dir).and_then(|()| {
            if self.own_prompts {
                sandbox.name_turn(&lease.attempt.0)
            } else {
                Ok(())
            }
        });
        if let Err(e) = prepared {
            if let Err(left) = sandbox.destroy() {
                self.keep(&left);
            }
            let reason = format!("no sandbox: {e}");
            return Ok(Outcome::NotRun { reason });
        }
        record.advance(Phase::Worker);
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
        let outcome = self.work_in(&turn, record, make_worker);
        // Written before the sandbox is removed, so that a clock that dies removing it leaves the record.
        record.saved = Some(self.persist(lease, record));
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
    fn work_in(
        &mut self,
        turn: &Turn<'_>,
        record: &mut TurnRecord,
        make_worker: impl FnOnce(&str) -> Result<Box<dyn turn::Worker>, TurnError> + Send,
    ) -> Result<Outcome, ClockError> {
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

        let ran = {
            let (name, limit) = (&lease.worker, self.turn_secs);
            let command = &spec.check.command;
            let seen = &mut record.seen;
            // A worker is not `Send`, so it is made where it runs.
            let job = move || -> Result<RunStatus, TurnError> {
                make_worker(name)?.run(sandbox, title, command, limit, seen)
            };
            self.watch(&mut keeper, Some(&stop), job)
        };
        record.worker_done();
        // How the worker's program ended, also when its run then failed (the room's commit for it, say).
        let status = match &ran.0 {
            Ok(status) => Some(*status),
            Err(_) => record.seen.status,
        };
        record.measured.exit_code = status.map(|status| status.exit_code);
        record.measured.ended = match status {
            Some(status) if status.timed_out => Ended::TimedOut,
            Some(status) if status.exit_code >= 128 => Ended::Signalled,
            Some(_) => Ended::Exited,
            // No status: the run failed. If nothing was ever started in the sandbox, no program ran (the worker
            // could not be made, or what it does before its program failed). Otherwise one did, and how it
            // ended is not known.
            None if sandbox.started_a_run() => Ended::Unknown,
            None => Ended::NotRun,
        };
        // Whether the room's switch ended the program: only then is how it ended a stop or a lost lease.
        let ended_by_the_room = status.is_some_and(|status| status.stopped);
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
        let (timed_out, failure) = match ran {
            Ok(status) => (status.timed_out, None),
            Err(e) => (false, Some(e.to_string())),
        };
        let failure_said = failure.clone();
        // Only where the watch over the worker ended its program is how it ended a stop or a lost lease. Either
        // coming later leaves the program's own end: while the room commits for the worker, while its commit is
        // brought in, at the hand-in, at the verdict.
        if watched.stopped {
            if ended_by_the_room {
                record.measured.ended = Ended::Stopped;
            }
            return self.stopped(lease);
        }
        if watched.lost {
            if ended_by_the_room {
                record.measured.ended = Ended::LeaseLost;
            }
            return Ok(Outcome::LeaseLost);
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
        record.advance(Phase::Bring);
        // The commit is brought into the item's repository before the hand-in, so that what is handed in is always
        // there for the check to clone; a commit that cannot be brought over is a turn that handed in nothing, and
        // fails. A renewal first makes sure the lease is still this turn's.
        if commit != base {
            match self.room.renew(lease, now()) {
                Ok(_) => keeper.last = now(),
                Err(e) if fatal(&e) => return Err(e.into()),
                Err(_) => return Ok(Outcome::LeaseLost),
            }
            match self.bring(&mut keeper, turn, &commit)? {
                Brought::Named(files) => {
                    let omitted = self.room.record_changes(&lease.attempt, &files)?;
                    record.measured.unknown_changes = u64::try_from(omitted).unwrap_or(u64::MAX);
                }
                Brought::Stopped => return self.stopped(lease),
                Brought::LeaseLost => return Ok(Outcome::LeaseLost),
                Brought::Failed(why) => {
                    nothing = Some(format!("its commit could not be fetched: {why}"));
                    commit = base.clone();
                }
            }
        }
        match self.room.hand_in(lease, &commit, now()) {
            Ok(()) => {}
            Err(e) if fatal(&e) => return Err(e.into()),
            Err(RoomError::Stale { .. }) => return Ok(Outcome::LeaseLost),
            Err(e) => {
                let reason = format!("the hand-in was refused: {e}");
                return Ok(Outcome::Unchecked { reason });
            }
        }

        let checks = self.room.dir().join(CHECKS);
        let scratch = turns.join(format!("{}.check", lease.attempt.0));
        record.advance(Phase::Check);
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
                return Ok(Outcome::Unchecked { reason });
            }
        };
        let state = match self
            .room
            .record_verdict(&lease.item, lease.lease_no, &verdict, now())
        {
            Ok(state) => state,
            Err(e) if fatal(&e) => return Err(e.into()),
            Err(RoomError::Stale { .. }) => return Ok(Outcome::LeaseLost),
            Err(e) => {
                let reason = format!("the verdict was refused: {e}");
                return Ok(Outcome::Unchecked { reason });
            }
        };
        Ok(Outcome::Judged {
            state,
            commit,
            nothing,
            timed_out,
            recheck: None,
        })
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
            let (halt, base) = (&halt, &turn.spec.base_commit);
            // Both reads finish before publishing a ref. A stop during either leaves no name behind.
            let job = move || {
                fetch(sandbox, repo, commit, limit, halt)
                    .and_then(|()| changed_files(repo, base, commit, limit, halt))
                    .map_err(|e| e.to_string())
            };
            self.watch(keeper, Some(halt), job)
        };
        // No ref yet, so nothing to take back.
        if let Some(e) = store_failed {
            return Err(e.into());
        }
        if let Some(ended) = self.no_longer_ours(keeper, lease)? {
            return Ok(ended);
        }
        let files = match fetched {
            Ok(files) => files,
            Err(why) => return Ok(Brought::Failed(why)),
        };

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
            Ok(()) => Brought::Named(files),
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
    fn stopped(&mut self, lease: &Lease) -> Result<Outcome, ClockError> {
        match self.room.release(lease, now()) {
            Err(e) if fatal(&e) => Err(e.into()),
            Ok(()) | Err(_) => Ok(Outcome::Stopped),
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

fn changed_files(
    repo: &Path,
    base: &str,
    commit: &str,
    limit: Duration,
    stop: &AtomicBool,
) -> Result<Vec<ChangedFile>, ClockError> {
    let mut command = turn::sandbox::safe_git();
    command
        .arg("-C")
        .arg(repo)
        .args(["diff", "--name-status", "-z", "--no-renames", base, commit]);
    let out =
        turn::sandbox::safe_git_output_until(command, "the turn's changed files", limit, stop)?;
    let mut fields = out.split(|b| *b == 0);
    let mut files = Vec::new();
    while let (Some(status), Some(path)) = (fields.next(), fields.next()) {
        let change = match status {
            b"A" => Change::Added,
            b"D" => Change::Removed,
            _ => Change::Changed,
        };
        files.push(ChangedFile {
            path: String::from_utf8_lossy(path).into_owned(),
            change,
        });
    }
    Ok(files)
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

#[cfg(test)]
mod measurement_tests {
    use super::*;

    #[test]
    fn durations_do_not_depend_on_the_wall_clock() {
        let start = Instant::now();
        let mut timer = Phases::at(start);
        let mut m = empty_measured();
        timer.advance_to(Phase::Worker, start + Duration::from_millis(11), &mut m);
        timer.advance_to(Phase::Seal, start + Duration::from_millis(34), &mut m);
        timer.advance_to(Phase::Bring, start + Duration::from_millis(39), &mut m);
        timer.advance_to(Phase::Check, start + Duration::from_millis(46), &mut m);
        timer.close_at(start + Duration::from_millis(63), &mut m);
        assert_eq!(
            (
                m.sandbox_ms,
                m.worker_ms,
                m.seal_ms,
                m.bring_ms,
                m.check_ms,
                m.active_ms
            ),
            (11, 23, 5, 7, Some(17), 63)
        );
        assert_eq!(m.recheck_ms, None);
        let mut timer = Phases::at(start);
        let mut m = empty_measured();
        timer.close_at(start + Duration::from_millis(2), &mut m);
        assert_eq!(
            (
                m.sandbox_ms,
                m.worker_ms,
                m.seal_ms,
                m.bring_ms,
                m.check_ms,
                m.active_ms
            ),
            (2, 0, 0, 0, None, 2)
        );
    }

    #[test]
    fn unknown_steps_count_an_omitted_name_once_and_include_unretained_steps() {
        let d = tempfile::tempdir().unwrap();
        let mut room = Room::init(d.path()).unwrap();
        let item = room
            .add_item(room::NewItem {
                title: "fixture".into(),
                repo: "/fixture".into(),
                base_commit: "a".repeat(40),
                after: vec![],
                check: room::CheckSpec {
                    command: "false".into(),
                    files: vec![],
                    timeout_secs: 1,
                    origin: room::CheckOrigin::Outside,
                    wrong_artifacts: vec!["b".repeat(40)],
                    written_by: "person:test".into(),
                },
            })
            .unwrap();
        room.record_frozen(
            &item,
            Frozen {
                check_hash: "c".repeat(64),
                red_on_base: true,
                red_on_wrong: vec![true],
            },
        )
        .unwrap();
        let lease = room.take("script:fixture", 100).unwrap().unwrap();
        let mut record = TurnRecord::new();
        let step = |seq, target, paths: &[&str]| room::Step {
            seq,
            target,
            tool: room::Tool::Shell,
            ok: true,
            tokens_in: None,
            tokens_out: None,
            named: paths
                .iter()
                .map(|p| room::Named {
                    path: (*p).into(),
                    blob: "b".repeat(40),
                })
                .collect(),
            seen_ms: None,
            result_ms: None,
        };
        record.seen.steps = vec![
            step(
                0,
                room::Target::TrackedFile {
                    path: "a.rs".into(),
                    blob: "b".repeat(40),
                },
                &[],
            ),
            step(1, room::Target::Outside, &["ok.rs", "a b.rs", "é.rs"]),
            step(2, room::Target::Outside, &[]),
            step(
                3,
                room::Target::TrackedFile {
                    path: "a b.rs".into(),
                    blob: "b".repeat(40),
                },
                &["ok.rs"],
            ),
            step(4, room::Target::Outside, &["known.rs"]),
        ];
        record.seen.steps_seen = 6;
        record.seen.steps.swap(0, 3);
        record.measured.ended = Ended::TimedOut;
        record.seen.tokens = Tokens {
            fresh_in: Some(1),
            cache_write: Some(2),
            cache_read: Some(3),
            output: Some(4),
            reasoning: None,
            complete: true,
        };
        record.finish();
        assert!(
            persist_turn(&mut room, &lease.attempt, &mut record)
                .unwrap()
                .is_none()
        );
        let m = room.measured(&lease.attempt).unwrap().unwrap();
        assert_eq!(m.unknown_steps, 4);
        assert_eq!(m.steps_seen, 6);
        assert_eq!(m.ended, Ended::TimedOut);
        assert!(m.tokens.complete);
        assert_eq!(m.tokens.total(), Some(10));
    }

    /// A room with one item whose check is frozen (by hand: nothing here runs it), at `repo` and `base`, and a
    /// lease of it for `worker`.
    fn leased(dir: &Path, repo: PathBuf, base: &str, worker: &str) -> (Room, Lease) {
        leased_in(dir, repo, base, worker, |_| {})
    }

    /// The same, in a room `prepare` has set up before the item is taken.
    fn leased_in(
        dir: &Path,
        repo: PathBuf,
        base: &str,
        worker: &str,
        prepare: impl FnOnce(&mut Room),
    ) -> (Room, Lease) {
        let mut room = Room::init(&dir.join("room")).unwrap();
        prepare(&mut room);
        let item = room
            .add_item(room::NewItem {
                title: "fixture".into(),
                repo,
                base_commit: base.into(),
                after: vec![],
                check: room::CheckSpec {
                    command: "false".into(),
                    files: vec![],
                    timeout_secs: 1,
                    origin: room::CheckOrigin::Outside,
                    wrong_artifacts: vec!["b".repeat(40)],
                    written_by: "person:test".into(),
                },
            })
            .unwrap();
        room.record_frozen(
            &item,
            Frozen {
                check_hash: "c".repeat(64),
                red_on_base: true,
                red_on_wrong: vec![true],
            },
        )
        .unwrap();
        let lease = room.take(worker, now()).unwrap().unwrap();
        (room, lease)
    }

    /// One step whose walk the room refuses, for what is in it (a named file's blob is not a blob id).
    fn refused_step() -> room::Step {
        room::Step {
            seq: 0,
            tool: room::Tool::Shell,
            target: room::Target::Outside,
            ok: true,
            tokens_in: None,
            tokens_out: None,
            named: vec![room::Named {
                path: "a.rs".into(),
                blob: "x".into(),
            }],
            seen_ms: None,
            result_ms: None,
        }
    }

    /// A walk the room refuses for what is in it does not lose the turn's measured record, and it does not stop
    /// the clock: it is said, and the record is written with every step unknown, since none was kept.
    #[test]
    fn a_refused_walk_keeps_the_measured_record_and_the_clock_going() {
        let d = tempfile::tempdir().unwrap();
        let (mut room, lease) = leased(d.path(), "/fixture".into(), &"a".repeat(40), "script:x");
        let mut record = TurnRecord::new();
        record.seen.steps = vec![refused_step()];
        record.seen.steps_seen = 3;
        record.measured.ended = Ended::Exited;
        // The control: the room does refuse this walk.
        assert!(matches!(
            room.record_walk(&lease.attempt, &record.seen.steps),
            Err(RoomError::Refused(_))
        ));
        let mut events = Vec::new();
        let mut report = |e: &Event| events.push(e.clone());
        let mut clock = test_clock(&mut room, 5, Some(&mut report));
        assert!(clock.persist(&lease, &mut record).is_ok());
        let m = clock
            .room
            .measured(&lease.attempt)
            .unwrap()
            .expect("measured");
        assert_eq!(m.unknown_steps, m.steps_seen);
        assert_eq!(m.steps_seen, 3);
        assert!(clock.room.walk(&lease.attempt).unwrap().is_empty());
        drop(clock);
        assert!(
            matches!(&events[..], [Event::Problem { what, .. }] if what.contains("walk was refused")),
            "{events:?}"
        );
    }

    /// A store that fails while the walk is written is still the clock's error, as it was: it is no walk the
    /// room refused for what is in it.
    #[test]
    fn a_store_that_fails_while_the_walk_is_written_stops_the_clock() {
        let d = tempfile::tempdir().unwrap();
        let (mut room, lease) = leased(d.path(), "/fixture".into(), &"a".repeat(40), "script:x");
        // Another program takes away a table the walk is written to, as a damaged store would lack it.
        let dropped = std::process::Command::new("python3")
            .args([
                "-I",
                "-c",
                "import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.execute('DROP TABLE step_files'); c.commit()",
            ])
            .arg(d.path().join("room").join("room.sqlite3"))
            .status()
            .unwrap();
        assert!(dropped.success());
        let mut record = TurnRecord::new();
        let mut step = refused_step();
        step.named[0].blob = "b".repeat(40);
        record.seen.steps = vec![step];
        record.seen.steps_seen = 1;
        record.finish();
        let saved = persist_turn(&mut room, &lease.attempt, &mut record);
        assert!(matches!(saved, Err(RoomError::Db(_))), "{saved:?}");
    }

    // The script streams two calls, then invalidates its clone. The wrapper performs the
    // same post-run inspection a model worker's seal does, and returns its real error.
    struct InspectAfterScript(Box<dyn turn::Worker>);
    impl turn::Worker for InspectAfterScript {
        fn name(&self) -> String {
            self.0.name()
        }
        fn run(
            &self,
            sandbox: &Sandbox,
            title: &str,
            command: &str,
            limit: u32,
            seen: &mut Seen,
        ) -> Result<RunStatus, TurnError> {
            let status = self.0.run(sandbox, title, command, limit, seen)?;
            sandbox.head()?;
            Ok(status)
        }
    }

    /// Random numbers that always give the same one: 1 never picks a recheck.
    struct Fixed(u32);
    impl rand::TryRng for Fixed {
        type Error = std::convert::Infallible;
        fn try_next_u32(&mut self) -> Result<u32, Self::Error> {
            Ok(self.0)
        }
        fn try_next_u64(&mut self) -> Result<u64, Self::Error> {
            Ok(u64::from(self.0))
        }
        fn try_fill_bytes(&mut self, dst: &mut [u8]) -> Result<(), Self::Error> {
            dst.fill(0);
            Ok(())
        }
    }

    fn test_clock<'r, 'o>(
        room: &'r mut Room,
        turn_secs: u32,
        report: Option<&'o mut dyn FnMut(&Event)>,
    ) -> Clock<'r, 'o> {
        Clock {
            room,
            workers: &[],
            turn_secs,
            poll: WATCH,
            report,
            git_limit: Duration::from_secs(5),
            own_prompts: false,
            given: None,
            next: 0,
            unfreezable: HashMap::new(),
            ceiling_day: None,
            kept: Vec::new(),
        }
    }

    /// A repository in `dir` with one commit, and that commit.
    fn base_repo(dir: &Path) -> (PathBuf, String) {
        let repo = dir.join("repo");
        fs::create_dir(&repo).unwrap();
        let git = |args: &[&str]| {
            let out = turn::sandbox::safe_git()
                .arg("-C")
                .arg(&repo)
                .args([
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                ])
                .args(args)
                .output()
                .unwrap();
            assert!(out.status.success(), "{:?}", out.stderr);
            String::from_utf8(out.stdout).unwrap().trim().to_string()
        };
        git(&["init", "-q", "-b", "main"]);
        fs::write(repo.join("a.rs"), "fixture").unwrap();
        git(&["add", "."]);
        git(&["commit", "-qm", "base"]);
        let base = git(&["rev-parse", "HEAD"]);
        (repo, base)
    }

    /// An executable script in `dir`, and its worker name.
    fn script_worker(dir: &Path, body: &str) -> String {
        let script = dir.join("worker.sh");
        fs::write(&script, body).unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();
        format!("script:{}", script.display())
    }

    /// A script worker whose run then fails as a model worker's does when the room's commit for it fails: after
    /// its program has ended. `seal` is how long that commit takes.
    struct FailsAfterScript {
        script: Box<dyn turn::Worker>,
        seal: Duration,
    }
    impl turn::Worker for FailsAfterScript {
        fn name(&self) -> String {
            self.script.name()
        }
        fn run(
            &self,
            sandbox: &Sandbox,
            title: &str,
            command: &str,
            limit: u32,
            seen: &mut Seen,
        ) -> Result<RunStatus, TurnError> {
            self.script.run(sandbox, title, command, limit, seen)?;
            let sealing = Instant::now();
            thread::sleep(self.seal);
            seen.seal_ms = millis(sealing.elapsed());
            Err(TurnError::Refused("the room's commit failed".into()))
        }
    }

    /// A program that ran out of time is recorded as having run out of time, with its exit code, though its run
    /// then returned an error: how it ended was kept before the room's commit was tried.
    #[test]
    #[ignore = "needs the room: a list of processes and a jail"]
    fn a_program_that_timed_out_is_recorded_so_though_its_run_then_fails() {
        let d = tempfile::tempdir().unwrap();
        let (repo, base) = base_repo(d.path());
        let worker = script_worker(d.path(), "#!/bin/sh\nsleep 600\n");
        let (mut room, lease) = leased(d.path(), repo, &base, &worker);
        let mut clock = test_clock(&mut room, 1, None);
        let outcome = clock.attempt(&lease, now(), &mut Fixed(1), |name| {
            Ok(Box::new(FailsAfterScript {
                script: worker::from_name(name)?,
                seal: Duration::ZERO,
            }))
        });
        assert!(outcome.is_ok(), "{outcome:?}");
        let m = clock.room.measured(&lease.attempt).unwrap().unwrap();
        assert_eq!(m.ended, Ended::TimedOut);
        assert!(matches!(m.exit_code, Some(code) if code != 0), "{m:?}");
        assert!(m.worker_ms >= 1000, "{m:?}");
    }

    /// The room's commit on a worker's behalf is timed by the worker, and that time is the seal's, not the
    /// worker's; the parts still add up.
    #[test]
    #[ignore = "needs the room: a list of processes and a jail"]
    fn the_rooms_commit_for_a_worker_is_in_the_seal_and_not_in_the_worker() {
        const SEAL: Duration = Duration::from_millis(2_000);
        let d = tempfile::tempdir().unwrap();
        let (repo, base) = base_repo(d.path());
        let worker = script_worker(d.path(), "#!/bin/sh\nexit 0\n");
        let (mut room, lease) = leased(d.path(), repo, &base, &worker);
        let mut clock = test_clock(&mut room, 60, None);
        clock
            .attempt(&lease, now(), &mut Fixed(1), |name| {
                Ok(Box::new(FailsAfterScript {
                    script: worker::from_name(name)?,
                    seal: SEAL,
                }))
            })
            .unwrap();
        let m = clock.room.measured(&lease.attempt).unwrap().unwrap();
        // The exact transfer is `the_seals_time_is_taken_out_of_the_workers_exactly`; here, that a real turn's
        // record has the commit's time in its seal.
        assert!(m.seal_ms >= 2_000, "{m:?}");
        assert_eq!(
            m.active_ms,
            m.sandbox_ms + m.worker_ms + m.seal_ms + m.bring_ms + m.check_ms.unwrap_or(0)
        );
    }

    /// A turn's start is one moment: its phases count from it, and so do its steps' times.
    #[test]
    fn a_turns_phases_and_its_steps_count_from_the_same_start() {
        let mut record = TurnRecord::new();
        let made = record.seen.started;
        let at = made.checked_sub(Duration::from_secs(5)).unwrap();
        record.start(at);
        // The worker is given the turn's start, not the moment the record was made.
        assert_eq!(record.seen.started, at);
        assert_ne!(record.seen.started, made);
        // And the phases count from it: a sandbox done one second after the start took one second.
        let timer = record.timer.as_mut().unwrap();
        timer.advance_to(
            Phase::Worker,
            at + Duration::from_secs(1),
            &mut record.measured,
        );
        assert_eq!(record.measured.sandbox_ms, 1_000);
    }

    /// The time of the room's commit for a worker moves from the worker's phase to the seal's, exactly, and
    /// never more than the worker's phase held.
    #[test]
    fn the_seals_time_is_taken_out_of_the_workers_exactly() {
        for (sealed, worker_ms, seal_ms) in [(700, 2_300, 700), (0, 3_000, 0), (5_000, 0, 3_000)] {
            let mut record = TurnRecord::new();
            let at = Instant::now();
            record.start(at);
            let worker_from = at + Duration::from_millis(100);
            record.timer.as_mut().unwrap().advance_to(
                Phase::Worker,
                worker_from,
                &mut record.measured,
            );
            record.seen.seal_ms = sealed;
            record.worker_done_at(worker_from + Duration::from_millis(3_000));
            assert_eq!(
                (record.measured.worker_ms, record.measured.seal_ms),
                (worker_ms, seal_ms),
                "a commit of {sealed} ms"
            );
            assert_eq!(record.measured.sandbox_ms, 100);
        }
    }

    /// A script worker that, once its program has ended, says so by making the file `entered` and then waits,
    /// as a model worker waits in the room's commit for it, until the sandbox's switch is set. Its run then
    /// fails, as that commit does in a sandbox that was stopped.
    struct WaitsInSeal {
        script: Box<dyn turn::Worker>,
        entered: PathBuf,
    }
    impl turn::Worker for WaitsInSeal {
        fn name(&self) -> String {
            self.script.name()
        }
        fn run(
            &self,
            sandbox: &Sandbox,
            title: &str,
            command: &str,
            limit: u32,
            seen: &mut Seen,
        ) -> Result<RunStatus, TurnError> {
            self.script.run(sandbox, title, command, limit, seen)?;
            fs::write(&self.entered, "").map_err(|e| TurnError::Io(e.to_string()))?;
            let switch = sandbox.stop_switch();
            let patience = Instant::now() + PATIENCE;
            while !switch.load(Ordering::Relaxed) {
                if Instant::now() > patience {
                    return Err(TurnError::Refused(
                        "the test never set the sandbox's switch".into(),
                    ));
                }
                thread::sleep(Duration::from_millis(20));
            }
            Err(TurnError::Refused(
                "this sandbox was stopped, and nothing more runs in it".into(),
            ))
        }
    }

    /// How long a test here waits for something that should come at once.
    const PATIENCE: Duration = Duration::from_secs(60);

    /// Does `act` once the file `path` is there, on a thread of its own. The thread gives whether it was.
    fn once_there(path: PathBuf, act: impl FnOnce() + Send + 'static) -> thread::JoinHandle<bool> {
        thread::spawn(move || {
            let patience = Instant::now() + PATIENCE;
            while !path.exists() {
                if Instant::now() > patience {
                    return false;
                }
                thread::sleep(Duration::from_millis(20));
            }
            act();
            true
        })
    }

    /// A stop that comes while the room commits for a worker, after its program ended by itself or at its
    /// limit, stops the turn and leaves how the program ended. A stop that comes while the program runs is how
    /// it ended.
    #[test]
    #[ignore = "needs the room: a list of processes and a jail"]
    fn a_stop_while_the_room_commits_for_a_worker_leaves_how_its_program_ended() {
        // (the script, the turn's limit, whether the stop waits for the program's end, how it ended)
        let cases: [(&str, u32, bool, Ended); 3] = [
            ("#!/bin/sh\nexit 3\n", 60, true, Ended::Exited),
            ("#!/bin/sh\nsleep 600\n", 1, true, Ended::TimedOut),
            // The control: the same stop, while the program still runs.
            ("#!/bin/sh\nsleep 600\n", 60, false, Ended::Stopped),
        ];
        for (body, limit, after_the_program, ended) in cases {
            let d = tempfile::tempdir().unwrap();
            let (repo, base) = base_repo(d.path());
            let worker = script_worker(d.path(), body);
            let (mut room, lease) = leased(d.path(), repo, &base, &worker);
            let entered = d.path().join("entered");
            let stop = room.dir().join("STOP");
            // The run's own record is there once its program has started.
            let running = room
                .dir()
                .join(TURNS)
                .join(format!("{}.pid", lease.attempt.0));
            let wait_for = if after_the_program {
                entered.clone()
            } else {
                running
            };
            let stopper = once_there(wait_for, move || fs::write(stop, "").unwrap());
            let mut clock = test_clock(&mut room, limit, None);
            let outcome = clock.attempt(&lease, now(), &mut Fixed(1), |name| {
                Ok(Box::new(WaitsInSeal {
                    script: worker::from_name(name)?,
                    entered,
                }))
            });
            assert!(stopper.join().unwrap(), "{body}: the stop never came");
            assert!(
                matches!(outcome, Ok(Outcome::Stopped)),
                "{body}: {outcome:?}"
            );
            let m = clock.room.measured(&lease.attempt).unwrap().unwrap();
            assert_eq!(m.ended, ended, "{body}: {m:?}");
            match ended {
                Ended::Exited => assert_eq!(m.exit_code, Some(3), "{m:?}"),
                _ => assert!(matches!(m.exit_code, Some(code) if code != 0), "{m:?}"),
            }
        }
    }

    /// The same for a lease that is lost while the room commits for a worker: the turn is lost, and how the
    /// program ended is kept. (A lease lost while the program runs is in the clock's own tests.)
    #[test]
    #[ignore = "needs the room: a list of processes and a jail"]
    fn a_lease_lost_while_the_room_commits_for_a_worker_leaves_how_its_program_ended() {
        let d = tempfile::tempdir().unwrap();
        let (repo, base) = base_repo(d.path());
        let worker = script_worker(d.path(), "#!/bin/sh\nexit 3\n");
        // A lease of three seconds is renewed every second, so a lease that has moved on is noticed within one.
        let (mut room, lease) = leased_in(d.path(), repo, &base, &worker, |room| {
            room.set_lease_secs(3).unwrap()
        });
        let entered = d.path().join("entered");
        let (store, item) = (room.dir().join("room.sqlite3"), lease.item.0.clone());
        let mover = once_there(entered.clone(), move || {
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
        });
        let mut clock = test_clock(&mut room, 60, None);
        let outcome = clock.attempt(&lease, now(), &mut Fixed(1), |name| {
            Ok(Box::new(WaitsInSeal {
                script: worker::from_name(name)?,
                entered,
            }))
        });
        assert!(mover.join().unwrap(), "the lease was never moved on");
        assert!(matches!(outcome, Ok(Outcome::LeaseLost)), "{outcome:?}");
        let m = clock.room.measured(&lease.attempt).unwrap().unwrap();
        assert_eq!(m.ended, Ended::Exited, "{m:?}");
        assert_eq!(m.exit_code, Some(3), "{m:?}");
    }

    /// A worker whose run fails. With `starts`, it has started something in the sandbox first and does not say
    /// how that ended; without, it has started nothing, as when what a worker does before its program fails.
    struct FailsWithNoStatus {
        starts: bool,
    }
    impl turn::Worker for FailsWithNoStatus {
        fn name(&self) -> String {
            "script:fails".into()
        }
        fn run(
            &self,
            sandbox: &Sandbox,
            _title: &str,
            _command: &str,
            limit: u32,
            _seen: &mut Seen,
        ) -> Result<RunStatus, TurnError> {
            if self.starts {
                sandbox.run_untrusted("true", &[], "", limit, &mut |_| {})?;
            }
            Err(TurnError::Refused("the worker's run failed".into()))
        }
    }

    /// A run that failed and gave no status is not recorded as a program that exited. If nothing was started in
    /// the sandbox, no program ran; if something was, how it ended is not known. Either way the turn has its
    /// record and the clock goes on.
    #[test]
    fn a_run_that_fails_with_no_status_is_not_recorded_as_exited() {
        for (starts, ended) in [(false, Ended::NotRun), (true, Ended::Unknown)] {
            let d = tempfile::tempdir().unwrap();
            let (repo, base) = base_repo(d.path());
            let worker = script_worker(d.path(), "#!/bin/sh\nexit 0\n");
            let (mut room, lease) = leased(d.path(), repo, &base, &worker);
            let mut clock = test_clock(&mut room, 60, None);
            let outcome = clock.attempt(&lease, now(), &mut Fixed(1), |_| {
                Ok(Box::new(FailsWithNoStatus { starts }))
            });
            assert!(outcome.is_ok(), "{outcome:?}");
            let m = clock.room.measured(&lease.attempt).unwrap().unwrap();
            assert_eq!(m.ended, ended, "starts {starts}: {m:?}");
            assert_eq!(m.exit_code, None, "{m:?}");
            assert_eq!(
                m.active_ms,
                m.sandbox_ms + m.worker_ms + m.seal_ms + m.bring_ms + m.check_ms.unwrap_or(0)
            );
        }
        // A worker that cannot be made started nothing either.
        let d = tempfile::tempdir().unwrap();
        let (repo, base) = base_repo(d.path());
        let worker = script_worker(d.path(), "#!/bin/sh\nexit 0\n");
        let (mut room, lease) = leased(d.path(), repo, &base, &worker);
        let mut clock = test_clock(&mut room, 60, None);
        let outcome = clock.attempt(&lease, now(), &mut Fixed(1), |name| {
            Err(TurnError::UnknownWorker(name.to_string()))
        });
        assert!(outcome.is_ok(), "{outcome:?}");
        let m = clock.room.measured(&lease.attempt).unwrap().unwrap();
        assert_eq!((m.ended, m.exit_code), (Ended::NotRun, None), "{m:?}");
    }

    #[test]
    #[ignore = "needs the room: a list of processes and a jail"]
    fn a_turns_steps_are_kept_when_its_worker_ends_in_an_error() {
        let d = tempfile::tempdir().unwrap();
        let repo = d.path().join("repo");
        fs::create_dir(&repo).unwrap();
        let git = |args: &[&str]| {
            let out = turn::sandbox::safe_git()
                .arg("-C")
                .arg(&repo)
                .args([
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                ])
                .args(args)
                .output()
                .unwrap();
            assert!(out.status.success(), "{:?}", out.stderr);
            String::from_utf8(out.stdout).unwrap().trim().to_string()
        };
        git(&["init", "-q", "-b", "main"]);
        fs::write(repo.join("a.rs"), "fixture").unwrap();
        git(&["add", "."]);
        git(&["commit", "-qm", "base"]);
        let base = git(&["rev-parse", "HEAD"]);
        let script = d.path().join("worker.sh");
        fs::write(&script, r#"#!/bin/sh
printf '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Read","input":{"file_path":"%s/a.rs"}},{"type":"tool_use","id":"t2","name":"Read","input":{"file_path":"%s/a.rs"}}]}}\n' "$PWD" "$PWD"
mv .git .git-old
ln -s .git-old .git
"#).unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();
        let mut room = Room::init(&d.path().join("room")).unwrap();
        let item = room
            .add_item(room::NewItem {
                title: "fixture".into(),
                repo,
                base_commit: base.clone(),
                after: vec![],
                check: room::CheckSpec {
                    command: "false".into(),
                    files: vec![],
                    timeout_secs: 1,
                    origin: room::CheckOrigin::Outside,
                    wrong_artifacts: vec![base],
                    written_by: "person:test".into(),
                },
            })
            .unwrap();
        room.record_frozen(
            &item,
            Frozen {
                check_hash: "c".repeat(64),
                red_on_base: true,
                red_on_wrong: vec![true],
            },
        )
        .unwrap();
        let lease = room
            .take(&format!("script:{}", script.display()), now())
            .unwrap()
            .unwrap();
        let mut clock = test_clock(&mut room, 5, None);
        // Through `attempt` itself, as a turn goes: the record is the one it wrote.
        let outcome = clock.attempt(&lease, now(), &mut Fixed(1), |name| {
            Ok(Box::new(InspectAfterScript(worker::from_name(name)?)))
        });
        assert!(outcome.is_ok(), "{outcome:?}");
        assert_eq!(clock.room.walk(&lease.attempt).unwrap().len(), 2);
        let m = clock.room.measured(&lease.attempt).unwrap().unwrap();
        assert_eq!(m.steps_seen, 2);
        assert_eq!(m.ended, Ended::Exited);
        // The script itself exited 0 before its run failed, and that is kept.
        assert_eq!(m.exit_code, Some(0));
        assert!(!m.tokens.complete);
        assert_eq!(
            m.active_ms,
            m.sandbox_ms + m.worker_ms + m.seal_ms + m.bring_ms + m.check_ms.unwrap_or(0)
        );
    }

    /// A worker that keeps what its sandbox hides from a model worker's shell, and does nothing else.
    struct KeepsWhatIsHidden(std::sync::Arc<std::sync::Mutex<Vec<PathBuf>>>);
    impl turn::Worker for KeepsWhatIsHidden {
        fn name(&self) -> String {
            "script:keeps".into()
        }
        fn run(
            &self,
            sandbox: &Sandbox,
            _title: &str,
            _command: &str,
            _limit: u32,
            _seen: &mut Seen,
        ) -> Result<RunStatus, TurnError> {
            *self.0.lock().unwrap() = sandbox.hidden_from_worker().to_vec();
            Ok(RunStatus {
                exit_code: 0,
                timed_out: false,
                stopped: false,
            })
        }
    }

    /// Every sandbox the clock makes for a turn hides the room's own directory from a worker's shell: its store,
    /// the other turns' directories and the checks. Here as a real path, beside the item's repository, which
    /// the sandbox hides by itself. A worker of a test's own sees the list, through `attempt` as a turn goes:
    /// from outside the clock only a model worker would, and with the jail off the clock runs none.
    #[test]
    fn the_clock_hides_its_room_from_a_worker() {
        let d = tempfile::tempdir().unwrap();
        let (repo, base) = base_repo(d.path());
        let (mut room, lease) = leased(d.path(), repo.clone(), &base, "script:keeps");
        let kept = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let given = std::sync::Arc::clone(&kept);
        let mut clock = test_clock(&mut room, 5, None);
        let outcome = clock.attempt(&lease, now(), &mut Fixed(1), move |_| {
            Ok(Box::new(KeepsWhatIsHidden(given)))
        });
        assert!(outcome.is_ok(), "{outcome:?}");
        let room_dir = d.path().join("room").canonicalize().unwrap();
        assert_eq!(
            *kept.lock().unwrap(),
            [repo.canonicalize().unwrap(), room_dir]
        );
    }
}
