use rusqlite::{Connection, OptionalExtension};

use crate::{Room, RoomError, Ts, store::db};

impl Room {
    pub fn set_ceiling(&mut self, daily_turns: u32, concurrent: u32) -> Result<(), RoomError> {
        let tx = self.conn.transaction().map_err(db)?;
        tx.execute(
            "UPDATE meta SET daily_turns=?1,concurrent=?2",
            (daily_turns, concurrent),
        )
        .map_err(db)?;
        tx.commit().map_err(db)?;
        Ok(())
    }

    pub fn stopped(&self) -> bool {
        self.dir.join("STOP").exists()
    }

    pub fn turns_today(&self, now: Ts) -> Result<u32, RoomError> {
        used(&self.conn, now)
    }
}

pub(crate) fn used(conn: &Connection, now: Ts) -> Result<u32, RoomError> {
    Ok(conn
        .query_row(
            "SELECT used FROM budget_days WHERE day=?1",
            [now.div_euclid(86_400)],
            |r| r.get(0),
        )
        .optional()
        .map_err(db)?
        .unwrap_or(0))
}

/// Called only inside the same transaction that creates an eligible lease.
pub(crate) fn reserve(conn: &Connection, now: Ts) -> Result<bool, RoomError> {
    let (daily, concurrent): (u32, u32) = conn
        .query_row("SELECT daily_turns,concurrent FROM meta", [], |r| {
            Ok((r.get(0)?, r.get(1)?))
        })
        .map_err(db)?;
    let used = used(conn, now)?;
    if used >= daily {
        return Err(RoomError::Ceiling { used, limit: daily });
    }
    let running: u32 = conn
        .query_row(
            "SELECT count(*) FROM attempts WHERE state IN ('leased','checking')",
            [],
            |r| r.get(0),
        )
        .map_err(db)?;
    if running >= concurrent {
        return Ok(false);
    }
    conn.execute("INSERT INTO budget_days (day,used) VALUES (?1,1) ON CONFLICT(day) DO UPDATE SET used=used+1", [now.div_euclid(86_400)]).map_err(db)?;
    Ok(true)
}
