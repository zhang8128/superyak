use crate::{
    AttemptId, Named, Room, RoomError, Step, Target,
    item::{from_key, hex_hash, key},
    store::db,
};

impl Room {
    /// Admit a batch atomically, omitting unplain names and returning the number omitted: each path left out of a
    /// step once for that step, though it was its target and a name both.
    pub fn record_walk(&mut self, attempt: &AttemptId, steps: &[Step]) -> Result<usize, RoomError> {
        let tx = self.conn.transaction().map_err(db)?;
        let exists: bool = tx
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM attempts WHERE id=?1)",
                [&attempt.0],
                |r| r.get(0),
            )
            .map_err(db)?;
        if !exists {
            return Err(RoomError::Refused("unknown attempt".into()));
        }
        let mut omitted = 0;
        for step in steps {
            let mut left_out: Vec<&str> = Vec::new();
            if let Target::TrackedFile { blob, .. } = &step.target
                && !hex_hash(blob, &[40, 64])
            {
                return Err(RoomError::Refused(
                    "walk target must be a plain relative path and a Git blob hash".into(),
                ));
            }
            let (target, path, blob) = match &step.target {
                Target::TrackedFile { path, blob } if plain_path(path) => {
                    ("tracked_file", Some(path.as_str()), Some(blob.as_str()))
                }
                Target::Outside => ("outside", None, None),
                Target::TrackedFile { path, .. } => {
                    left_out.push(path);
                    ("outside", None, None)
                }
            };
            tx.execute("INSERT INTO steps (attempt,seq,tool,target,path,blob,ok,tokens_in,tokens_out,seen_ms,result_ms) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
                (&attempt.0, step.seq, key(&step.tool)?, target, path, blob, step.ok, step.tokens_in, step.tokens_out, step.seen_ms, step.result_ms)).map_err(db)?;
            for (ordinal, name) in step.named.iter().enumerate() {
                if !hex_hash(&name.blob, &[40, 64]) {
                    return Err(RoomError::Refused(
                        "named file must have a Git blob hash".into(),
                    ));
                }
                if !plain_path(&name.path) {
                    if !left_out.contains(&name.path.as_str()) {
                        left_out.push(&name.path);
                    }
                    continue;
                }
                tx.execute(
                    "INSERT INTO step_files VALUES (?1,?2,?3,?4,?5)",
                    (&attempt.0, step.seq, ordinal as i64, &name.path, &name.blob),
                )
                .map_err(db)?;
            }
            omitted += left_out.len();
        }
        tx.commit().map_err(db)?;
        Ok(omitted)
    }

    pub fn walk(&self, attempt: &AttemptId) -> Result<Vec<Step>, RoomError> {
        let mut q = self.conn.prepare("SELECT seq,tool,target,path,blob,ok,tokens_in,tokens_out,seen_ms,result_ms FROM steps WHERE attempt=?1 ORDER BY seq").map_err(db)?;
        let rows = q
            .query_map([&attempt.0], |r| {
                Ok(StoredStep {
                    seq: r.get(0)?,
                    tool: r.get(1)?,
                    target: r.get(2)?,
                    path: r.get(3)?,
                    blob: r.get(4)?,
                    ok: r.get(5)?,
                    tokens_in: r.get(6)?,
                    tokens_out: r.get(7)?,
                    seen_ms: r.get(8)?,
                    result_ms: r.get(9)?,
                })
            })
            .map_err(db)?;
        rows.map(|row| {
            let s = row.map_err(db)?;
            let target = match s.target.as_str() {
                "outside" => Target::Outside,
                "tracked_file" => Target::TrackedFile {
                    path: s
                        .path
                        .ok_or_else(|| RoomError::Damaged("tracked step has no path".into()))?,
                    blob: s
                        .blob
                        .ok_or_else(|| RoomError::Damaged("tracked step has no blob".into()))?,
                },
                _ => return Err(RoomError::Damaged("unknown walk target".into())),
            };
            let mut names = self
                .conn
                .prepare(
                    "SELECT path,blob FROM step_files WHERE attempt=?1 AND seq=?2 ORDER BY ordinal",
                )
                .map_err(db)?;
            let named = names
                .query_map((&attempt.0, s.seq), |r| {
                    Ok(Named {
                        path: r.get(0)?,
                        blob: r.get(1)?,
                    })
                })
                .map_err(db)?
                .collect::<Result<Vec<_>, _>>()
                .map_err(db)?;
            Ok(Step {
                seq: s.seq,
                tool: from_key(&s.tool)?,
                target,
                ok: s.ok,
                tokens_in: s.tokens_in,
                tokens_out: s.tokens_out,
                named,
                seen_ms: s.seen_ms,
                result_ms: s.result_ms,
            })
        })
        .collect()
    }
}

pub(crate) fn plain_path(path: &str) -> bool {
    !path.is_empty()
        && path.len() <= 512
        && !path.starts_with('/')
        && path
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_./-".contains(&b))
        && path.split('/').all(|part| !matches!(part, "" | "." | ".."))
}

struct StoredStep {
    seq: u32,
    tool: String,
    target: String,
    path: Option<String>,
    blob: Option<String>,
    ok: bool,
    tokens_in: Option<u32>,
    tokens_out: Option<u32>,
    seen_ms: Option<u32>,
    result_ms: Option<u32>,
}
