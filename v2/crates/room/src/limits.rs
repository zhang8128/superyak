//! The numbers the stage 1 plan fixes. Change them there first.

/// How long a lease lasts without a renewal, in seconds.
pub const LEASE_SECS: i64 = 1800;
/// The wall-clock limit of one turn, in seconds.
pub const TURN_SECS: u32 = 1200;
/// How long a process group gets between SIGTERM and SIGKILL, in seconds.
pub const TERM_GRACE_SECS: u32 = 10;
/// After this many failed or expired attempts an item is abandoned.
pub const MAX_ATTEMPTS: u32 = 3;
/// The default ceiling on turns dispatched in one UTC day.
pub const DAILY_TURNS: u32 = 40;
/// The default number of turns that may run at once.
pub const CONCURRENT_TURNS: u32 = 1;
/// The default time limit of a check, in seconds.
pub const CHECK_TIMEOUT_SECS: u32 = 900;
/// One verified pass in this many is checked again.
pub const RECHECK_ONE_IN: u32 = 5;
/// How often the clock looks at the room, in seconds.
pub const CLOCK_POLL_SECS: u32 = 5;
/// The store's schema version.
pub const SCHEMA_VERSION: u32 = 1;
