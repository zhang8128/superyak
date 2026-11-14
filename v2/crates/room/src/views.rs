use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::{Disagreement, ItemId, ItemState, Room, RoomError, Ts, item::from_key, store::db};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Status {
    pub counts: HashMap<ItemState, u32>,
    pub verified_passes_last_day: u32,
    pub turns_today: u32,
    pub daily_ceiling: u32,
    pub stopped: bool,
}

impl Room {
    pub fn status(&self, now: Ts) -> Result<Status, RoomError> {
        let tx = self.conn.unchecked_transaction().map_err(db)?;
        let mut counts = [
            ItemState::Draft,
            ItemState::Open,
            ItemState::Leased,
            ItemState::Checking,
            ItemState::PassedVerified,
            ItemState::PassedUnverified,
            ItemState::Failed,
            ItemState::Blocked,
            ItemState::Abandoned,
        ]
        .into_iter()
        .map(|state| (state, 0))
        .collect::<HashMap<_, _>>();
        {
            let mut q = tx
                .prepare("SELECT state,count(*) FROM items GROUP BY state")
                .map_err(db)?;
            let rows = q
                .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, u32>(1)?)))
                .map_err(db)?;
            for row in rows {
                let (state, count) = row.map_err(db)?;
                counts.insert(from_key(&state)?, count);
            }
        }
        let verified_passes_last_day = tx.query_row("SELECT count(*) FROM verdicts v JOIN attempts a ON a.id=v.attempt JOIN items i ON i.id=a.item AND i.lease_no=a.lease_no WHERE i.state='passed_verified' AND v.recorded > ?1 AND v.recorded <= ?2", (now.saturating_sub(86_400), now), |r| r.get(0)).map_err(db)?;
        let turns_today = crate::budget::used(&tx, now)?;
        let daily_ceiling = tx
            .query_row("SELECT daily_turns FROM meta", [], |r| r.get(0))
            .map_err(db)?;
        tx.commit().map_err(db)?;
        Ok(Status {
            counts,
            verified_passes_last_day,
            turns_today,
            daily_ceiling,
            stopped: self.stopped(),
        })
    }

    pub fn disagreements(&self) -> Result<Vec<Disagreement>, RoomError> {
        let mut query = self
            .conn
            .prepare("SELECT kind,item,detail FROM disagreements ORDER BY ordinal")
            .map_err(db)?;
        let rows = query
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })
            .map_err(db)?;
        let mut out = Vec::new();
        for row in rows {
            let (kind, item, detail) = row.map_err(db)?;
            out.push(Disagreement {
                kind: from_key(&kind)?,
                item: ItemId(item),
                detail,
            });
        }
        Ok(out)
    }
}
