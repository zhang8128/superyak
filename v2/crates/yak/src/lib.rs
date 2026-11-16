//! The clock and the shared read-only views used by the CLI and MCP. Stage 1, tasks 9 and 10.

pub mod clock;
pub mod history;
pub mod mcp;
pub mod route_offer;

use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use room::{ItemId, Room, RoomError, Ts};
use serde_json::Value;

/// The room views shared by the read-only interfaces.
pub enum View {
    Status,
    ItemList,
    ItemShow(ItemId),
    ItemTurns(ItemId),
    Disagreements,
}

/// Every CLI and MCP read uses a read-only SQLite connection, without the clock's writer lock.
pub fn read_view(dir: &Path, view: &View) -> Result<Value, RoomError> {
    let room = Room::open_read_only(dir)?;
    let value = match view {
        View::Status => serde_json::to_value(room.status(now())?),
        View::ItemList => serde_json::to_value(room.items()?),
        View::ItemShow(id) => serde_json::to_value(room.item(id)?),
        View::ItemTurns(id) => serde_json::to_value(room.turns(id)?),
        View::Disagreements => serde_json::to_value(room.disagreements()?),
    };
    value.map_err(|e| RoomError::Db(e.to_string()))
}

pub fn now() -> Ts {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| i64::try_from(d.as_secs()).unwrap_or(i64::MAX))
        .unwrap_or(0)
}

/// Refusals and clock events each occupy one line, including errors quoting operator input.
pub fn one_line(text: &str) -> String {
    text.chars()
        .map(|c| {
            if c.is_control() || matches!(c, '\u{2028}' | '\u{2029}') {
                ' '
            } else {
                c
            }
        })
        .collect()
}
