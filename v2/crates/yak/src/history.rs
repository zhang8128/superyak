//! The room's canonical walk files, admission list, and unchanged title-word ranker.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use room::{ArrivedTurn, ItemId, Room, Standing, plain_path};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

pub type Result<T> = std::result::Result<T, HistoryError>;

#[derive(Debug, thiserror::Error)]
#[error("refused: {0}")]
pub struct HistoryError(pub String);

pub(crate) fn refuse(field: &str) -> HistoryError {
    HistoryError(field.into())
}

pub(crate) fn io<T>(result: std::io::Result<T>, field: &str) -> Result<T> {
    result.map_err(|_| refuse(field))
}

pub fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

pub(crate) fn canonical(value: &impl Serialize) -> Result<Vec<u8>> {
    let mut value = serde_json::to_value(value).map_err(|_| refuse("json"))?;
    value.sort_all_objects();
    serde_json::to_vec(&value).map_err(|_| refuse("json"))
}

pub(crate) fn hash(value: &str, lengths: &[usize]) -> bool {
    lengths.contains(&value.len())
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

pub(crate) fn id(value: &str, prefix: char) -> bool {
    value.starts_with(prefix) && hash(&value[1..], &[12])
}

/// Rooms are absolute paths; no working directory or plan location can change their meaning.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Plan {
    pub items: Vec<PlanItem>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlanItem {
    pub room: PathBuf,
    pub item: ItemId,
}

pub fn read_plan(path: &Path) -> Result<Plan> {
    let mut plan: Plan = serde_json::from_slice(&io(fs::read(path), "plan.read")?)
        .map_err(|_| refuse("plan.format"))?;
    for entry in &mut plan.items {
        if !id(&entry.item.0, 'i') {
            return Err(refuse("plan.item"));
        }
        if !entry.room.is_absolute() {
            return Err(refuse("plan.room_absolute"));
        }
    }
    Ok(plan)
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Measure {
    pub name: String,
    pub version: u64,
}

impl Measure {
    pub fn parse(text: &str) -> Result<Self> {
        let (name, version) = text.split_once(':').ok_or_else(|| refuse("measure"))?;
        let measure = Self {
            name: name.into(),
            version: version.parse().map_err(|_| refuse("measure"))?,
        };
        measure.check()?;
        Ok(measure)
    }

    pub fn check(&self) -> Result<()> {
        if self.name != "share" || self.version != 1 {
            return Err(refuse("measure"));
        }
        Ok(())
    }

    fn teaches(&self, standing: Standing) -> bool {
        standing == Standing::PassedVerified
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HistoryList {
    pub v: u32,
    pub repo: String,
    pub measure: Measure,
    pub turns: Vec<ListTurn>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ListTurn {
    pub attempt: String,
    pub item: String,
    pub base: String,
    pub standing: Standing,
    pub sha256: String,
}

impl HistoryList {
    pub fn read(path: &Path) -> Result<(Self, String)> {
        let bytes = io(fs::read(path), "list.read")?;
        let list: Self = serde_json::from_slice(&bytes).map_err(|_| refuse("list.format"))?;
        list.check()?;
        if canonical(&list)? != bytes {
            return Err(refuse("list.canonical"));
        }
        Ok((list, sha256(&bytes)))
    }

    fn check(&self) -> Result<()> {
        if self.v != 1 {
            return Err(refuse("list.v"));
        }
        if !hash(&self.repo, &[40, 64]) {
            return Err(refuse("list.repo"));
        }
        self.measure.check()?;
        let mut seen = BTreeSet::new();
        for turn in &self.turns {
            if !seen.insert(&turn.attempt) {
                return Err(refuse("duplicate_attempt"));
            }
            if !id(&turn.attempt, 'a') {
                return Err(refuse("list.attempt"));
            }
            if !id(&turn.item, 'i') {
                return Err(refuse("list.item"));
            }
            if !hash(&turn.base, &[40, 64]) {
                return Err(refuse("list.base"));
            }
            if !hash(&turn.sha256, &[64]) {
                return Err(refuse("list.sha256"));
            }
        }
        if self
            .turns
            .windows(2)
            .any(|pair| pair[0].attempt >= pair[1].attempt)
        {
            return Err(refuse("list.order"));
        }
        Ok(())
    }
}

/// Git reads share the room's environment, timeout, process-group and output limits. Git diagnostics can
/// contain repository data, so only the fixed operation name crosses this API on failure.
fn git(repo: &Path, args: &[&str], field: &str) -> Result<Vec<u8>> {
    let mut cmd = turn::sandbox::safe_git();
    cmd.arg("--no-replace-objects")
        .arg("-C")
        .arg(repo)
        .args(args);
    turn::sandbox::safe_git_output(cmd, field).map_err(|_| refuse(field))
}

pub fn repository_id(repo: &Path, base: &str) -> Result<String> {
    if !hash(base, &[40, 64]) {
        return Err(refuse("base"));
    }
    let roots = git(
        repo,
        &["rev-list", "--max-parents=0", base, "--"],
        "repo.roots",
    )?;
    let roots = std::str::from_utf8(&roots).map_err(|_| refuse("repo.roots"))?;
    let root = roots.lines().min().ok_or_else(|| refuse("repo.roots"))?;
    if !hash(root, &[40, 64]) {
        return Err(refuse("repo.roots"));
    }
    Ok(root.into())
}

pub(crate) fn tree(repo: &Path, base: &str) -> Result<BTreeMap<String, String>> {
    if !hash(base, &[40, 64]) {
        return Err(refuse("base"));
    }
    let bytes = git(
        repo,
        &["ls-tree", "-rz", "--full-tree", base, "--"],
        "base.tree",
    )?;
    let mut files = BTreeMap::new();
    for entry in bytes.split(|b| *b == 0).filter(|e| !e.is_empty()) {
        let tab = entry
            .iter()
            .position(|b| *b == b'\t')
            .ok_or_else(|| refuse("base.tree"))?;
        let head = std::str::from_utf8(&entry[..tab]).map_err(|_| refuse("base.tree"))?;
        let fields = head.split(' ').collect::<Vec<_>>();
        if fields.len() != 3 {
            return Err(refuse("base.tree"));
        }
        if matches!(fields[0], "100644" | "100755")
            && fields[1] == "blob"
            && let Ok(path) = std::str::from_utf8(&entry[tab + 1..])
        {
            files.insert(path.into(), fields[2].into());
        }
    }
    Ok(files)
}

#[derive(Debug)]
struct HistoryItem {
    id: ItemId,
    title: String,
    repo_path: PathBuf,
    repo: String,
    base: String,
    turns: Vec<ArrivedTurn>,
}

fn load(plan: &Plan, need_arrival: bool) -> Result<Vec<HistoryItem>> {
    let mut items = Vec::new();
    let mut attempts = BTreeSet::new();
    for entry in &plan.items {
        let room = Room::open_read_only(&entry.room).map_err(|_| refuse("plan.room"))?;
        let view = room.item(&entry.item).map_err(|_| refuse("plan.item"))?;
        let spec = room
            .item_spec(&entry.item)
            .map_err(|_| refuse("plan.item"))?;
        let turns = room
            .arrived_turns(&entry.item)
            .map_err(|_| refuse("plan.turns"))?;
        if need_arrival && turns.is_empty() {
            return Err(refuse("no_arrived_turn"));
        }
        for turn in &turns {
            if !attempts.insert(turn.attempt.clone()) {
                return Err(refuse("duplicate_attempt"));
            }
        }
        let repo = repository_id(&spec.repo, &spec.base_commit)?;
        if items
            .first()
            .is_some_and(|first: &HistoryItem| first.repo != repo)
        {
            return Err(refuse("another_repository"));
        }
        items.push(HistoryItem {
            id: entry.item.clone(),
            title: view.title,
            repo_path: spec.repo,
            repo,
            base: spec.base_commit,
            turns,
        });
    }
    Ok(items)
}

fn walk_value(repo: &str, base: &str, item: &ItemId, turn: &ArrivedTurn) -> Result<Value> {
    // The room numbers a turn's steps from nought, in every store there is. A walk is written as it was
    // recorded, so the first step may be numbered nought; each one after it has a greater number.
    let mut previous = None;
    for step in &turn.steps {
        if previous.is_some_and(|before| step.seq <= before) {
            return Err(refuse("walk.steps.seq"));
        }
        previous = Some(step.seq);
        for name in &step.named {
            if !plain_path(&name.path) {
                return Err(refuse("walk.steps.named.path"));
            }
            if !hash(&name.blob, &[40, 64]) {
                return Err(refuse("walk.steps.named.blob"));
            }
        }
    }
    if turn.changed.iter().any(|file| !plain_path(&file.path)) {
        return Err(refuse("walk.changed.path"));
    }
    Ok(
        json!({"v":1,"source":"room","repo":repo,"base":base,"item":item,"attempt":turn.attempt,
            "family":turn.family,"verdict":turn.verdict.map(|passed| if passed {"passed"} else {"failed"}),
            "standing":turn.standing,
            "steps":turn.steps.iter().map(|step| json!({"seq":step.seq,"tool":step.tool,"ok":step.ok,
                "named":step.named.iter().map(|name| json!([name.path,name.blob])).collect::<Vec<_>>(),
                "seen_ms":step.seen_ms,"result_ms":step.result_ms,"tokens_in":step.tokens_in,"tokens_out":step.tokens_out
            })).collect::<Vec<_>>(),
            "changed":turn.changed.iter().map(|file| json!([file.path,file.change])).collect::<Vec<_>>()
        }),
    )
}

fn walk_bytes(repo: &str, base: &str, item: &ItemId, turn: &ArrivedTurn) -> Result<Vec<u8>> {
    let mut bytes = canonical(&walk_value(repo, base, item, turn)?)?;
    if bytes.len() > 1024 * 1024 {
        return Err(refuse("walk.line_size"));
    }
    bytes.push(b'\n');
    Ok(bytes)
}

pub fn walk_filename(attempt: &str) -> String {
    format!("{attempt}.jsonl")
}

/// Returns canonical JSON Lines to stdout, or writes one line to each attempt's file.
pub fn item_walks(dir: &Path, item: &ItemId, out: Option<&Path>) -> Result<Vec<u8>> {
    let items = load(
        &Plan {
            items: vec![PlanItem {
                room: dir.into(),
                item: item.clone(),
            }],
        },
        false,
    )?;
    let item = &items[0];
    let files = item
        .turns
        .iter()
        .map(|turn| {
            Ok((
                walk_filename(&turn.attempt.0),
                walk_bytes(&item.repo, &item.base, &item.id, turn)?,
            ))
        })
        .collect::<Result<Vec<_>>>()?;
    if let Some(out) = out {
        write_files(out, &files)?;
        return Ok(Vec::new());
    }
    Ok(files.into_iter().flat_map(|(_, bytes)| bytes).collect())
}

fn write_files(out: &Path, files: &[(String, Vec<u8>)]) -> Result<()> {
    io(fs::create_dir_all(out), "out.directory")?;
    if io(fs::read_dir(out), "out.directory")?.next().is_some() {
        return Err(refuse("out.not_empty"));
    }
    for (name, bytes) in files {
        io(fs::write(out.join(name), bytes), "out.write")?;
    }
    Ok(())
}

pub fn make(plan: &Plan, measure: Measure, out: &Path) -> Result<String> {
    measure.check()?;
    let items = load(plan, true)?;
    let repo = items
        .first()
        .ok_or_else(|| refuse("plan.empty"))?
        .repo
        .clone();
    let mut turns = Vec::new();
    let mut files = Vec::new();
    for item in &items {
        for turn in &item.turns {
            let bytes = walk_bytes(&repo, &item.base, &item.id, turn)?;
            turns.push(ListTurn {
                attempt: turn.attempt.0.clone(),
                item: item.id.0.clone(),
                base: item.base.clone(),
                standing: turn.standing,
                sha256: sha256(&bytes),
            });
            files.push((walk_filename(&turn.attempt.0), bytes));
        }
    }
    turns.sort_by(|a, b| a.attempt.cmp(&b.attempt));
    let bytes = canonical(&HistoryList {
        v: 1,
        repo,
        measure,
        turns,
    })?;
    let digest = sha256(&bytes);
    files.push(("history.json".into(), bytes));
    write_files(out, &files)?;
    Ok(digest)
}

fn listed<'a>(
    entry: &ListTurn,
    items: &'a [HistoryItem],
) -> Result<(&'a HistoryItem, &'a ArrivedTurn)> {
    let candidates = items
        .iter()
        .filter(|item| item.id.0 == entry.item)
        .collect::<Vec<_>>();
    if candidates.is_empty() {
        return Err(refuse("not_planned_item"));
    }
    for item in candidates {
        if let Some(turn) = item
            .turns
            .iter()
            .find(|turn| turn.attempt.0 == entry.attempt)
        {
            if item.base != entry.base {
                return Err(refuse("base_mismatch"));
            }
            if turn.standing != entry.standing {
                return Err(refuse("standing_changed"));
            }
            return Ok((item, turn));
        }
    }
    Err(refuse("not_arrived"))
}

pub fn check(plan: &Plan, list_path: &Path, walks: &Path) -> Result<()> {
    let (list, _) = HistoryList::read(list_path)?;
    let items = load(plan, false)?;
    if items.iter().any(|item| item.repo != list.repo) {
        return Err(refuse("another_repository"));
    }
    let mut expected = BTreeSet::new();
    for entry in &list.turns {
        let (item, turn) = listed(entry, &items)?;
        let filename = walk_filename(&entry.attempt);
        expected.insert(filename.clone());
        let file = walks.join(filename);
        if !io(fs::symlink_metadata(&file), "missing_walk")?.is_file() {
            return Err(refuse("walk.not_file"));
        }
        let bytes = io(fs::read(&file), "walk.read")?;
        if sha256(&bytes) != entry.sha256 {
            return Err(refuse("wrong_hash"));
        }
        let value: Value = serde_json::from_slice(&bytes).map_err(|_| refuse("walk.format"))?;
        if value.get("source") != Some(&json!("room")) {
            return Err(refuse("ship_walk"));
        }
        if value.get("repo") != Some(&json!(list.repo)) {
            return Err(refuse("another_repository"));
        }
        if bytes != walk_bytes(&list.repo, &item.base, &item.id, turn)? {
            return Err(refuse("walk.store_mismatch"));
        }
        let tree = tree(&item.repo_path, &item.base)?;
        for name in turn.steps.iter().flat_map(|step| &step.named) {
            if tree.get(&name.path) != Some(&name.blob) {
                return Err(refuse("path_or_blob_not_in_base"));
            }
        }
    }
    for file in io(fs::read_dir(walks), "walks.directory")? {
        let file = io(file, "walks.directory")?;
        let name = file.file_name();
        if name == "history.json" && file.path() == list_path {
            continue;
        }
        if name == "history.json"
            && io(fs::read(file.path()), "list.read")? == io(fs::read(list_path), "list.read")?
        {
            continue;
        }
        if !name.to_str().is_some_and(|name| expected.contains(name)) {
            if io(file.file_type(), "walks.directory")?.is_file() {
                let digest = sha256(&io(fs::read(file.path()), "walk.read")?);
                if list.turns.iter().any(|turn| turn.sha256 == digest) {
                    return Err(refuse("duplicate_attempt"));
                }
            }
            return Err(refuse("unlisted_file"));
        }
    }
    Ok(())
}

/// Version 1 ranks distinct lowercase title words, excluding words in over half the listed items.
/// Equal scores prefer later verdict arrival time, then the bytewise greater attempt id.
pub const RANKER_VERSION: &str = "title-words-1";
pub const MAX_CHOSEN: usize = 3;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Chosen {
    pub attempt: String,
    pub score: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Question {
    pub v: u32,
    pub repo: String,
    pub list: String,
    pub measure: Measure,
    pub goals: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Goals {
    pub ranker: String,
    pub history: String,
    pub measure: Measure,
    pub chosen: Vec<Chosen>,
    pub goals: Vec<String>,
    pub question: Question,
}

fn words(title: &str) -> BTreeSet<String> {
    title
        .split(|ch: char| !ch.is_alphanumeric())
        .filter(|word| !word.is_empty())
        .map(str::to_lowercase)
        .collect()
}

pub fn goals(plan: &Plan, list_path: &Path, title: &str) -> Result<Goals> {
    let (list, history) = HistoryList::read(list_path)?;
    let items = load(plan, false)?;
    if items.iter().any(|item| item.repo != list.repo) {
        return Err(refuse("another_repository"));
    }
    let mut item_words = BTreeMap::new();
    let mut candidates = Vec::new();
    for entry in &list.turns {
        let (item, turn) = listed(entry, &items)?;
        item_words.insert(item.id.clone(), words(&item.title));
        if list.measure.teaches(turn.standing) {
            candidates.push((item, turn));
        }
    }
    let mut counts = BTreeMap::<String, usize>::new();
    for words in item_words.values() {
        for word in words {
            *counts.entry(word.clone()).or_default() += 1;
        }
    }
    let query = words(title);
    let mut scored = candidates
        .into_iter()
        .map(|(item, turn)| {
            let score = item_words[&item.id]
                .intersection(&query)
                .filter(|word| counts[*word] * 2 <= item_words.len())
                .count();
            (score, item, turn)
        })
        .filter(|(score, _, _)| *score > 0)
        .collect::<Vec<_>>();
    scored.sort_by(|a, b| {
        b.0.cmp(&a.0)
            .then_with(|| b.2.recorded.cmp(&a.2.recorded))
            .then_with(|| b.2.attempt.cmp(&a.2.attempt))
    });
    scored.truncate(MAX_CHOSEN);
    let chosen = scored
        .iter()
        .map(|(score, _, turn)| Chosen {
            attempt: turn.attempt.0.clone(),
            score: *score,
        })
        .collect();
    let mut seen = BTreeSet::new();
    let goals = scored
        .iter()
        .flat_map(|(_, _, turn)| &turn.changed)
        .filter(|file| seen.insert(file.path.clone()))
        .map(|file| file.path.clone())
        .collect::<Vec<_>>();
    let question = Question {
        v: 1,
        repo: list.repo,
        list: history.clone(),
        measure: list.measure.clone(),
        goals: goals.clone(),
    };
    Ok(Goals {
        ranker: RANKER_VERSION.into(),
        history,
        measure: list.measure,
        chosen,
        goals,
        question,
    })
}

pub fn goals_json(plan: &Plan, list: &Path, title: &str) -> Result<Vec<u8>> {
    canonical(&goals(plan, list, title)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use room::{AttemptId, Change, ChangedFile, Named, Step, Target, Tool};

    #[test]
    fn hashes_are_of_exact_bytes_and_git_ids_accept_only_the_two_full_lowercase_lengths() {
        assert_eq!(
            sha256(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_ne!(sha256(b"abc\n"), sha256(b"abc"));
        for size in [40, 64] {
            assert!(hash(&"a".repeat(size), &[40, 64]));
        }
        for size in [0, 39, 41, 63, 65] {
            assert!(!hash(&"a".repeat(size), &[40, 64]));
        }
        assert!(!hash(&"A".repeat(40), &[40, 64]));
        assert!(!hash(&"g".repeat(40), &[40, 64]));
        assert!(id("a0123456789ab", 'a'));
        for value in [
            "",
            "a0123456789a",
            "a0123456789abc",
            "i0123456789ab",
            "a0123456789AB",
        ] {
            assert!(!id(value, 'a'));
        }
    }

    #[test]
    fn base_identity_is_full_lowercase_before_any_git_read() {
        let absent = tempfile::tempdir().unwrap().path().join("absent");
        for base in ["HEAD", "--all", "", &"A".repeat(40), &"a".repeat(39)] {
            assert_eq!(repository_id(&absent, base).unwrap_err().0, "base");
            assert_eq!(tree(&absent, base).unwrap_err().0, "base");
        }
    }

    #[test]
    fn walk_list_and_question_bytes_match_the_normative_revision_three_fixture() {
        let walks = [
            include_bytes!("../tests/fixtures/store-route-r3/walk-attempt-1.jsonl").as_slice(),
            include_bytes!("../tests/fixtures/store-route-r3/walk-attempt-2.jsonl").as_slice(),
            include_bytes!("../tests/fixtures/store-route-r3/walk-attempt-3.jsonl").as_slice(),
        ];
        for bytes in walks {
            let v: Value = serde_json::from_slice(bytes).unwrap();
            let number = |value: &Value| value.as_u64().map(|n| u32::try_from(n).unwrap());
            let turn = ArrivedTurn {
                attempt: AttemptId(v["attempt"].as_str().unwrap().into()),
                family: v["family"].as_str().unwrap().into(),
                verdict: Some(v["verdict"] == "passed"),
                standing: serde_json::from_value(v["standing"].clone()).unwrap(),
                recorded: 0,
                changed: v["changed"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|pair| ChangedFile {
                        path: pair[0].as_str().unwrap().into(),
                        change: serde_json::from_value(pair[1].clone()).unwrap(),
                    })
                    .collect(),
                steps: v["steps"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|s| Step {
                        seq: number(&s["seq"]).unwrap(),
                        tool: serde_json::from_value(s["tool"].clone()).unwrap(),
                        target: Target::Outside,
                        ok: s["ok"].as_bool().unwrap(),
                        named: s["named"]
                            .as_array()
                            .unwrap()
                            .iter()
                            .map(|pair| Named {
                                path: pair[0].as_str().unwrap().into(),
                                blob: pair[1].as_str().unwrap().into(),
                            })
                            .collect(),
                        tokens_in: number(&s["tokens_in"]),
                        tokens_out: number(&s["tokens_out"]),
                        seen_ms: number(&s["seen_ms"]),
                        result_ms: number(&s["result_ms"]),
                    })
                    .collect(),
            };
            assert_eq!(
                walk_bytes(
                    v["repo"].as_str().unwrap(),
                    v["base"].as_str().unwrap(),
                    &ItemId(v["item"].as_str().unwrap().into()),
                    &turn
                )
                .unwrap(),
                bytes
            );
        }
        let bytes = include_bytes!("../tests/fixtures/store-route-r3/list.json");
        let list: HistoryList = serde_json::from_slice(bytes).unwrap();
        assert_eq!(canonical(&list).unwrap(), bytes);
        assert_eq!(
            sha256(bytes),
            "c832cbbe1c45567ed754f47516c2eabcc67ae54dbb47de76a5d3d134ab05f407"
        );
        for (turn, bytes) in list.turns.iter().zip(walks) {
            assert_eq!(turn.sha256, sha256(bytes));
        }
        let bytes = include_bytes!("../tests/fixtures/store-route-r3/question.json");
        let question: Question = serde_json::from_slice(bytes).unwrap();
        let mut written = canonical(&question).unwrap();
        written.push(b'\n');
        assert_eq!(written, bytes);
    }

    fn turn() -> ArrivedTurn {
        ArrivedTurn {
            attempt: AttemptId("a0123456789ab".into()),
            family: "codex".into(),
            verdict: Some(true),
            standing: Standing::PassedVerified,
            recorded: 1,
            changed: vec![],
            steps: vec![Step {
                seq: 1,
                tool: Tool::Read,
                target: Target::Outside,
                ok: true,
                named: vec![Named {
                    path: "a.txt".into(),
                    blob: "a".repeat(40),
                }],
                tokens_in: None,
                tokens_out: None,
                seen_ms: None,
                result_ms: None,
            }],
        }
    }

    #[test]
    fn walks_refuse_nonincreasing_sequences_and_invalid_paths_or_blobs() {
        let value = |turn: &ArrivedTurn| {
            walk_value(
                &"a".repeat(40),
                &"a".repeat(40),
                &ItemId("i0123456789ab".into()),
                turn,
            )
        };
        // A real turn's first step is numbered nought, and is written so.
        let mut t = turn();
        t.steps[0].seq = 0;
        t.steps.push(t.steps[0].clone());
        t.steps[1].seq = 1;
        let written = value(&t).unwrap();
        assert_eq!(written["steps"][0]["seq"], 0);
        assert_eq!(written["steps"][1]["seq"], 1);
        // A number that does not rise is refused: the same again, at nought and above it, and a lesser one.
        for (first, second) in [(0, 0), (1, 1), (2, 1)] {
            let mut t = turn();
            t.steps[0].seq = first;
            t.steps.push(t.steps[0].clone());
            t.steps[1].seq = second;
            assert_eq!(value(&t).unwrap_err().0, "walk.steps.seq");
        }
        let mut t = turn();
        t.steps[0].named[0].path = "../MARKER".into();
        assert_eq!(value(&t).unwrap_err().0, "walk.steps.named.path");
        for blob in ["a".repeat(39), "A".repeat(40)] {
            let mut t = turn();
            t.steps[0].named[0].blob = blob;
            assert_eq!(value(&t).unwrap_err().0, "walk.steps.named.blob");
        }
        let mut t = turn();
        t.changed.push(ChangedFile {
            path: "a b".into(),
            change: Change::Added,
        });
        assert_eq!(value(&t).unwrap_err().0, "walk.changed.path");
    }

    #[test]
    fn a_walk_line_at_one_mib_is_written_and_one_byte_more_is_refused() {
        let mut t = turn();
        t.steps[0].named = vec![
            Named {
                path: "x".into(),
                blob: "a".repeat(40)
            };
            2000
        ];
        let item = ItemId("i0123456789ab".into());
        let repo = "a".repeat(40);
        let minimum = canonical(&walk_value(&repo, &repo, &item, &t).unwrap())
            .unwrap()
            .len();
        let mut more = 1024 * 1024 - minimum;
        for name in &mut t.steps[0].named {
            let add = more.min(511);
            name.path.push_str(&"x".repeat(add));
            more -= add;
        }
        assert_eq!(more, 0);
        let bytes = walk_bytes(&repo, &repo, &item, &t).unwrap();
        assert_eq!(bytes.len(), 1024 * 1024 + 1);
        let name = t.steps[0]
            .named
            .iter_mut()
            .find(|name| name.path.len() < 512)
            .unwrap();
        name.path.push('x');
        assert_eq!(
            walk_bytes(&repo, &repo, &item, &t).unwrap_err().0,
            "walk.line_size"
        );
    }
}
