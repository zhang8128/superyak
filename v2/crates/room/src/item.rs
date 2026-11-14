use rusqlite::{Connection, OptionalExtension};
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use sha2::{Digest, Sha256};

use crate::{
    CheckOrigin, CheckSpec, Frozen, ItemId, ItemState, NewItem, Room, RoomError, Verdict,
    store::db, types::family,
};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ItemView {
    pub id: ItemId,
    pub title: String,
    pub state: ItemState,
    pub lease_no: u32,
    pub attempts: u32,
    pub written_by: String,
    pub origin: CheckOrigin,
    pub after: Vec<ItemId>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ItemSpec {
    pub repo: std::path::PathBuf,
    pub base_commit: String,
    pub check: CheckSpec,
    pub frozen: Option<Frozen>,
}

impl Room {
    pub fn add_item(&mut self, n: NewItem) -> Result<ItemId, RoomError> {
        let repo = n
            .repo
            .to_str()
            .ok_or_else(|| RoomError::Refused("repository path is not UTF-8".into()))?;
        let tx = self.conn.transaction().map_err(db)?;
        for parent in &n.after {
            if !tx
                .query_row(
                    "SELECT EXISTS(SELECT 1 FROM items WHERE id=?1)",
                    [&parent.0],
                    |r| r.get::<_, bool>(0),
                )
                .map_err(db)?
            {
                return Err(RoomError::Refused("dependency does not exist".into()));
            }
        }
        let id = ItemId(new_id(&tx, 'i')?);
        tx.execute("INSERT INTO items (id,title,repo,base_commit,after_ids,state) VALUES (?1,?2,?3,?4,?5,'draft')",
            (&id.0, &n.title, repo, &n.base_commit, json(&n.after)?)).map_err(db)?;
        tx.execute(
            "INSERT INTO checks (item,spec) VALUES (?1,?2)",
            (&id.0, json(&n.check)?),
        )
        .map_err(db)?;
        tx.commit().map_err(db)?;
        Ok(id)
    }

    pub fn record_frozen(&mut self, id: &ItemId, f: Frozen) -> Result<ItemState, RoomError> {
        if !hex_hash(&f.check_hash, &[64]) {
            return Err(RoomError::Refused(
                "frozen check must have a SHA-256 hash".into(),
            ));
        }
        let tx = self.conn.transaction().map_err(db)?;
        let view = item_view(&tx, id)?;
        let (spec, old): (String, Option<String>) = tx
            .query_row(
                "SELECT spec,frozen FROM checks WHERE item=?1",
                [&id.0],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .map_err(db)?;
        let spec: CheckSpec = parse(&spec)?;
        if let Some(old) = old
            && parse::<Frozen>(&old)? != f
        {
            return Err(RoomError::Refused(
                "a frozen check cannot be replaced".into(),
            ));
        }
        if !matches!(
            view.state,
            ItemState::Draft | ItemState::Blocked | ItemState::Open
        ) {
            return Err(RoomError::Refused(
                "the item has already been attempted".into(),
            ));
        }
        if view.attempts != 0 {
            return Err(RoomError::Refused(
                "the item has already been attempted".into(),
            ));
        }
        let strong = f.red_on_base
            && f.red_on_wrong.len() == spec.wrong_artifacts.len()
            && f.red_on_wrong.iter().all(|red| *red);
        let state = if !strong {
            tx.execute("INSERT OR IGNORE INTO disagreements (kind,item,detail) VALUES ('weak_check',?1,'check did not reject the supplied baseline or wrong artifacts')", [&id.0]).map_err(db)?;
            ItemState::Draft
        } else if dependencies_ready(&tx, &view.after)? {
            ItemState::Open
        } else {
            ItemState::Blocked
        };
        tx.execute(
            "UPDATE checks SET frozen=?1 WHERE item=?2",
            (json(&f)?, &id.0),
        )
        .map_err(db)?;
        tx.execute(
            "UPDATE items SET state=?1 WHERE id=?2",
            (key(&state)?, &id.0),
        )
        .map_err(db)?;
        tx.commit().map_err(db)?;
        Ok(state)
    }

    pub fn item(&self, id: &ItemId) -> Result<ItemView, RoomError> {
        item_view(&self.conn, id)
    }

    pub fn items(&self) -> Result<Vec<ItemView>, RoomError> {
        let tx = self.conn.unchecked_transaction().map_err(db)?;
        let ids = {
            let mut q = tx
                .prepare("SELECT id FROM items ORDER BY ordinal")
                .map_err(db)?;
            q.query_map([], |r| r.get::<_, String>(0))
                .map_err(db)?
                .collect::<Result<Vec<_>, _>>()
                .map_err(db)?
        };
        let views = ids
            .into_iter()
            .map(|id| item_view(&tx, &ItemId(id)))
            .collect::<Result<Vec<_>, _>>()?;
        tx.commit().map_err(db)?;
        Ok(views)
    }

    pub fn drafts(&self) -> Result<Vec<ItemId>, RoomError> {
        let mut q = self.conn.prepare("SELECT i.id FROM items i JOIN checks c ON c.item=i.id WHERE i.state='draft' AND c.frozen IS NULL ORDER BY i.ordinal").map_err(db)?;
        q.query_map([], |r| r.get::<_, String>(0))
            .map_err(db)?
            .map(|id| id.map(ItemId).map_err(db))
            .collect()
    }

    pub fn item_spec(&self, id: &ItemId) -> Result<ItemSpec, RoomError> {
        let raw = self.conn.query_row("SELECT i.repo,i.base_commit,c.spec,c.frozen FROM items i JOIN checks c ON c.item=i.id WHERE i.id=?1", [&id.0], |r| {
            Ok((r.get::<_, String>(0)?,r.get::<_, String>(1)?,r.get::<_, String>(2)?,r.get::<_, Option<String>>(3)?))
        }).optional().map_err(db)?.ok_or_else(|| RoomError::NotTakeable("unknown item".into()))?;
        Ok(ItemSpec {
            repo: raw.0.into(),
            base_commit: raw.1,
            check: parse(&raw.2)?,
            frozen: raw.3.as_deref().map(parse).transpose()?,
        })
    }
}

/// Classify the mechanical result using the frozen evidence, never a worker's account.
pub fn classify(check: &CheckSpec, frozen: &Frozen, verdict: &Verdict, worker: &str) -> ItemState {
    if !verdict.passed
        || verdict.exit_code != 0
        || verdict.timed_out
        || verdict.check_hash != frozen.check_hash
    {
        return ItemState::Failed;
    }
    if matches!(
        check.origin,
        CheckOrigin::Outside | CheckOrigin::ObservedFailure
    ) && family(&check.written_by) != family(worker)
        && frozen.red_on_base
        && !check.wrong_artifacts.is_empty()
        && frozen.red_on_wrong.len() == check.wrong_artifacts.len()
        && frozen.red_on_wrong.iter().all(|red| *red)
    {
        ItemState::PassedVerified
    } else {
        ItemState::PassedUnverified
    }
}

pub(crate) fn item_view(conn: &Connection, id: &ItemId) -> Result<ItemView, RoomError> {
    let raw = conn.query_row("SELECT i.title,i.state,i.lease_no,i.attempts,i.after_ids,c.spec FROM items i JOIN checks c ON c.item=i.id WHERE i.id=?1", [&id.0], |r| {
        Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,u32>(2)?,r.get::<_,u32>(3)?,r.get::<_,String>(4)?,r.get::<_,String>(5)?))
    }).optional().map_err(db)?.ok_or_else(|| RoomError::NotTakeable("unknown item".into()))?;
    let spec: CheckSpec = parse(&raw.5)?;
    Ok(ItemView {
        id: id.clone(),
        title: raw.0,
        state: from_key(&raw.1)?,
        lease_no: raw.2,
        attempts: raw.3,
        written_by: spec.written_by,
        origin: spec.origin,
        after: parse(&raw.4)?,
    })
}

pub(crate) fn dependencies_ready(conn: &Connection, after: &[ItemId]) -> Result<bool, RoomError> {
    for id in after {
        let state: Option<String> = conn
            .query_row("SELECT state FROM items WHERE id=?1", [&id.0], |r| r.get(0))
            .optional()
            .map_err(db)?;
        if state.as_deref() != Some("passed_verified") {
            return Ok(false);
        }
    }
    Ok(true)
}

pub(crate) fn new_id(conn: &Connection, prefix: char) -> Result<String, RoomError> {
    let random: Vec<u8> = conn
        .query_row("SELECT randomblob(32)", [], |r| r.get(0))
        .map_err(db)?;
    let digest = Sha256::digest(random);
    let suffix: String = digest[..6].iter().map(|b| format!("{b:02x}")).collect();
    Ok(format!("{prefix}{suffix}"))
}

pub(crate) fn hex_hash(value: &str, lengths: &[usize]) -> bool {
    lengths.contains(&value.len()) && value.bytes().all(|b| b.is_ascii_hexdigit())
}

pub(crate) fn json(value: &impl Serialize) -> Result<String, RoomError> {
    serde_json::to_string(value).map_err(db)
}
pub(crate) fn parse<T: DeserializeOwned>(value: &str) -> Result<T, RoomError> {
    serde_json::from_str(value).map_err(db)
}
pub(crate) fn key(value: &impl Serialize) -> Result<String, RoomError> {
    serde_json::to_value(value)
        .map_err(db)?
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| RoomError::Db("expected an enum name".into()))
}
pub(crate) fn from_key<T: DeserializeOwned>(value: &str) -> Result<T, RoomError> {
    serde_json::from_value(serde_json::Value::String(value.into())).map_err(db)
}
