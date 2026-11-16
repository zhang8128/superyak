//! Convert the store's typed answer to the room's offer format. No text from an answer reaches an error.

use crate::history::{self, Goals, Result, refuse};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::io::Read;
use std::path::Path;

pub const MAX_ANSWER_BYTES: usize = 1024 * 1024;
pub const MAX_GOALS: usize = 64;
pub const MAX_ROADS: usize = 256;
pub const MAX_VERSION_BYTES: usize = 64;

/// Read only a bounded number of bytes before parsing. Parser diagnostics may contain input data and
/// therefore become a fixed field name here. Schema validation belongs to the single answer adapter.
#[cfg(test)]
fn read_answer_json(path: &Path) -> Result<serde_json::Value> {
    let bytes = read_answer_bytes(path)?;
    serde_json::from_slice(&bytes).map_err(|_| refuse("answer.json"))
}

fn read_answer_bytes(path: &Path) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    crate::history::io(std::fs::File::open(path), "answer.read")?
        .take((MAX_ANSWER_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| refuse("answer.read"))?;
    if bytes.len() > MAX_ANSWER_BYTES {
        return Err(refuse("answer.size"));
    }
    Ok(bytes)
}

fn object<'a>(value: &'a Value, required: &[&str], at: &str) -> Result<&'a Map<String, Value>> {
    let object = value.as_object().ok_or_else(|| refuse(at))?;
    for field in required {
        if !object.contains_key(*field) {
            return Err(refuse(&format!("{at}.{field}.missing")));
        }
    }
    if object.keys().any(|key| !required.contains(&key.as_str())) {
        return Err(refuse(&format!("{at}.unknown_field")));
    }
    Ok(object)
}

fn string<'a>(value: &'a Value, at: &str) -> Result<&'a str> {
    value.as_str().ok_or_else(|| refuse(at))
}

fn whole(value: &Value, at: &str) -> Result<u64> {
    value.as_u64().ok_or_else(|| refuse(at))
}

fn array<'a>(value: &'a Value, at: &str) -> Result<&'a [Value]> {
    value
        .as_array()
        .map(Vec::as_slice)
        .ok_or_else(|| refuse(at))
}

fn path<'a>(value: &'a Value, at: &str) -> Result<&'a str> {
    let path = string(value, at)?;
    if !room::plain_path(path) {
        return Err(refuse(at));
    }
    Ok(path)
}

fn version(value: &str, at: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > MAX_VERSION_BYTES
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
    {
        return Err(refuse(at));
    }
    Ok(())
}

fn store_id(value: &Value, at: &str) -> Result<String> {
    // Store witnesses/detours carry opaque IDs; the normative fixture uses attempt-1 and item-1.
    let value = string(value, at)?;
    if value.is_empty() {
        return Err(refuse(at));
    }
    Ok(value.into())
}

fn fraction_integer(value: &Value, at: &str) -> Result<String> {
    let digits = string(value, at)?;
    if digits.is_empty() || digits.starts_with('0') || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return Err(refuse(at));
    }
    Ok(digits.into())
}

fn cost(value: &Value, at: &str) -> Result<u64> {
    let fields = object(value, &["num", "den", "nats"], at)?;
    let num = fraction_integer(&fields["num"], &format!("{at}.num"))?;
    let den = fraction_integer(&fields["den"], &format!("{at}.den"))?;
    if (num.len(), &num) > (den.len(), &den) {
        return Err(refuse(at));
    }
    cost_millis(string(&fields["nats"], &format!("{at}.nats"))?)
        .map_err(|_| refuse(&format!("{at}.nats")))
}

#[derive(Debug)]
struct ParsedRoad {
    to: String,
    turns: u64,
}

#[derive(Debug)]
struct ParsedRoute {
    roads: Vec<ParsedRoad>,
    blobs: BTreeMap<String, BTreeSet<String>>,
    cost_millis: u64,
    dearer_ways: usize,
}

#[derive(Debug)]
struct ParsedGoal {
    goal: String,
    route: Option<ParsedRoute>,
    none: Option<String>,
}

#[derive(Debug)]
pub struct Answer {
    store: String,
    kernel: String,
    goals: Vec<ParsedGoal>,
}

fn read_paths(value: &Value, at: &str, simple: bool, goal: &str) -> Result<Vec<String>> {
    let values = array(value, at)?;
    if values.is_empty() {
        return Err(refuse(at));
    }
    let mut paths = Vec::new();
    let mut seen = BTreeSet::new();
    for (n, value) in values.iter().enumerate() {
        let path = path(value, &format!("{at}[{n}]"))?;
        if simple && !seen.insert(path.to_owned()) {
            return Err(refuse(&format!("{at}.repeated")));
        }
        paths.push(path.to_owned());
    }
    if paths.last().map(String::as_str) != Some(goal) {
        return Err(refuse(&format!("{at}.end")));
    }
    Ok(paths)
}

fn route(value: &Value, goal: &str, taught: u64, at: &str) -> Result<ParsedRoute> {
    let fields = object(
        value,
        &["paths", "roads", "cost", "roads_n", "blobs", "detours"],
        at,
    )?;
    let paths = read_paths(&fields["paths"], &format!("{at}.paths"), true, goal)?;
    if paths.len() > MAX_ROADS {
        return Err(refuse(&format!("{at}.roads.limit")));
    }
    let roads = array(&fields["roads"], &format!("{at}.roads"))?;
    if roads.len() != paths.len()
        || whole(&fields["roads_n"], &format!("{at}.roads_n"))? != paths.len() as u64
    {
        return Err(refuse(&format!("{at}.roads_n")));
    }
    let mut parsed = Vec::new();
    for (n, road) in roads.iter().enumerate() {
        let at = format!("{at}.roads[{n}]");
        let road = object(road, &["from", "to", "turns", "witness"], &at)?;
        let from = &road["from"];
        if (n == 0 && !from.is_null())
            || (n > 0 && path(from, &format!("{at}.from"))? != paths[n - 1])
        {
            return Err(refuse(&format!("{at}.from")));
        }
        if path(&road["to"], &format!("{at}.to"))? != paths[n] {
            return Err(refuse(&format!("{at}.to")));
        }
        let turns = whole(&road["turns"], &format!("{at}.turns"))?;
        if turns == 0 || turns > taught {
            return Err(refuse(&format!("{at}.turns")));
        }
        store_id(&road["witness"], &format!("{at}.witness"))?;
        parsed.push(ParsedRoad {
            to: paths[n].clone(),
            turns,
        });
    }
    let raw_blobs = fields["blobs"]
        .as_object()
        .ok_or_else(|| refuse(&format!("{at}.blobs")))?;
    if raw_blobs.len() != paths.len() || raw_blobs.keys().any(|name| !paths.contains(name)) {
        return Err(refuse(&format!("{at}.blobs")));
    }
    let mut blobs = BTreeMap::new();
    for name in &paths {
        let values = array(&raw_blobs[name], &format!("{at}.blobs"))?;
        if values.is_empty() {
            return Err(refuse(&format!("{at}.blobs")));
        }
        let mut previous = "";
        let mut set = BTreeSet::new();
        for value in values {
            let blob = string(value, &format!("{at}.blobs"))?;
            if !history::hash(blob, &[40, 64]) || blob <= previous {
                return Err(refuse(&format!("{at}.blobs")));
            }
            previous = blob;
            set.insert(blob.into());
        }
        blobs.insert(name.clone(), set);
    }
    let detours = array(&fields["detours"], &format!("{at}.detours"))?;
    let mut previous = String::new();
    for (n, detour) in detours.iter().enumerate() {
        let at = format!("{at}.detours[{n}]");
        let detour = object(
            detour,
            &[
                "attempt", "item", "family", "visit", "seq", "paths", "cost", "roads_n",
            ],
            &at,
        )?;
        let attempt = store_id(&detour["attempt"], &format!("{at}.attempt"))?;
        if attempt <= previous {
            return Err(refuse(&format!("{at}.attempt.order")));
        }
        previous = attempt;
        store_id(&detour["item"], &format!("{at}.item"))?;
        if !matches!(
            string(&detour["family"], &format!("{at}.family"))?,
            "claude" | "codex" | "script"
        ) {
            return Err(refuse(&format!("{at}.family")));
        }
        let detour_paths = read_paths(&detour["paths"], &format!("{at}.paths"), false, goal)?;
        if whole(&detour["visit"], &format!("{at}.visit"))? != detour_paths.len() as u64
            || detour_paths[..detour_paths.len() - 1]
                .iter()
                .any(|name| name == goal)
        {
            return Err(refuse(&format!("{at}.visit")));
        }
        // A step's number in its walk, which the room counts from nought: any whole number.
        whole(&detour["seq"], &format!("{at}.seq"))?;
        if whole(&detour["roads_n"], &format!("{at}.roads_n"))? != detour_paths.len() as u64 {
            return Err(refuse(&format!("{at}.roads_n")));
        }
        cost(&detour["cost"], &format!("{at}.cost"))?;
    }
    Ok(ParsedRoute {
        roads: parsed,
        blobs,
        cost_millis: cost(&fields["cost"], &format!("{at}.cost"))?,
        dearer_ways: detours.len(),
    })
}

/// Python's `ensure_ascii=True` canonical form, including the single final newline fixed by store rev 2.
fn answer_canonical(value: &Value) -> Result<Vec<u8>> {
    let json = String::from_utf8(history::canonical(value)?).map_err(|_| refuse("answer.json"))?;
    let mut ascii = String::new();
    for ch in json.chars() {
        if ch.is_ascii() && ch != '\u{7f}' {
            ascii.push(ch);
        } else {
            for unit in ch.encode_utf16(&mut [0; 2]) {
                ascii.push_str(&format!("\\u{unit:04x}"));
            }
        }
    }
    ascii.push('\n');
    Ok(ascii.into_bytes())
}

/// The one strict reader of the store's answer. Revision 3 fixes these containers:
/// blobs are an object of sorted hash arrays, and each detour is a flat object.
pub fn read_answer(answer_path: &Path, goals: &Goals, repo: &str) -> Result<Answer> {
    let bytes = read_answer_bytes(answer_path)?;
    let value: Value = serde_json::from_slice(&bytes).map_err(|_| refuse("answer.json"))?;
    // The owner confirmed both provenance fields after publishing the original rev 3 fixture.
    let fields = object(
        &value,
        &[
            "v",
            "store",
            "kernel",
            "repo",
            "list",
            "for_experiment",
            "measure",
            "path_rule",
            "taught",
            "answers",
        ],
        "answer",
    )?;
    if whole(&fields["v"], "answer.v")? != 1 {
        return Err(refuse("answer.v"));
    }
    if string(&fields["repo"], "answer.repo")? != repo {
        return Err(refuse("answer.repo"));
    }
    if string(&fields["list"], "answer.list")? != goals.history {
        return Err(refuse("answer.list"));
    }
    if fields["for_experiment"].as_bool() != Some(true) {
        return Err(refuse("answer.for_experiment"));
    }
    if whole(&fields["path_rule"], "answer.path_rule")? != 1 {
        return Err(refuse("answer.path_rule"));
    }
    let measure = object(
        &fields["measure"],
        &["name", "version", "teaches"],
        "answer.measure",
    )?;
    if string(&measure["name"], "answer.measure.name")? != goals.measure.name {
        return Err(refuse("answer.measure.name"));
    }
    if whole(&measure["version"], "answer.measure.version")? != goals.measure.version {
        return Err(refuse("answer.measure.version"));
    }
    if measure["teaches"] != json!(["passed_verified"]) {
        return Err(refuse("answer.measure.teaches"));
    }
    let taught = whole(&fields["taught"], "answer.taught")?;
    let answers = array(&fields["answers"], "answer.answers")?;
    if answers.len() != goals.goals.len() {
        return Err(refuse("answer.answers.order"));
    }
    let mut parsed = Vec::new();
    for (n, value) in answers.iter().enumerate() {
        let at = format!("answer.answers[{n}]");
        let map = value.as_object().ok_or_else(|| refuse(&at))?;
        let goal = path(
            map.get("goal")
                .ok_or_else(|| refuse(&format!("{at}.goal.missing")))?,
            &format!("{at}.goal"),
        )?;
        if goal != goals.goals[n] {
            return Err(refuse(&format!("{at}.goal.order")));
        }
        if let Some(none) = map.get("none") {
            let none = string(none, &format!("{at}.none"))?;
            if !matches!(
                none,
                "no_history" | "never_named" | "not_taught" | "refused"
            ) {
                return Err(refuse(&format!("{at}.none")));
            }
            let required = if none == "refused" {
                &["goal", "none", "code", "reason"][..]
            } else {
                &["goal", "none"][..]
            };
            let fields = object(value, required, &at)?;
            if (taught == 0) != (none == "no_history") {
                return Err(refuse(&format!("{at}.none.precedence")));
            }
            if none == "refused" {
                fields["code"]
                    .as_i64()
                    .ok_or_else(|| refuse(&format!("{at}.code")))?;
                string(&fields["reason"], &format!("{at}.reason"))?;
            }
            parsed.push(ParsedGoal {
                goal: goal.into(),
                route: None,
                none: Some(none.into()),
            });
        } else {
            let fields = object(value, &["goal", "route"], &at)?;
            if taught == 0 {
                return Err(refuse(&format!("{at}.none.precedence")));
            }
            parsed.push(ParsedGoal {
                goal: goal.into(),
                route: Some(route(
                    &fields["route"],
                    goal,
                    taught,
                    &format!("{at}.route"),
                )?),
                none: None,
            });
        }
    }
    if answer_canonical(&value)? != bytes {
        return Err(refuse("answer.canonical"));
    }
    let store = string(&fields["store"], "answer.store")?;
    let kernel = string(&fields["kernel"], "answer.kernel")?;
    version(store, "answer.store")?;
    version(kernel, "answer.kernel")?;
    Ok(Answer {
        store: store.into(),
        kernel: kernel.into(),
        goals: parsed,
    })
}

pub fn read_goals(path: &Path) -> Result<Goals> {
    let bytes = history::io(std::fs::read(path), "goals.read")?;
    let goals: Goals = serde_json::from_slice(&bytes).map_err(|_| refuse("goals.format"))?;
    goals.measure.check()?;
    version(&goals.ranker, "goals.ranker")?;
    if !history::hash(&goals.history, &[64]) {
        return Err(refuse("goals.history"));
    }
    if goals.chosen.len() > history::MAX_CHOSEN {
        return Err(refuse("goals.chosen.limit"));
    }
    let mut seen = BTreeSet::new();
    for chosen in &goals.chosen {
        if !history::id(&chosen.attempt, 'a') || chosen.score == 0 || !seen.insert(&chosen.attempt)
        {
            return Err(refuse("goals.chosen"));
        }
    }
    if goals.goals.len() > MAX_GOALS {
        return Err(refuse("goals.limit"));
    }
    let mut seen = BTreeSet::new();
    for name in &goals.goals {
        if !room::plain_path(name) || !seen.insert(name) {
            return Err(refuse("goals.path"));
        }
    }
    if goals.question.v != 1
        || goals.question.list != goals.history
        || goals.question.goals != goals.goals
        || goals.question.measure != goals.measure
        || !history::hash(&goals.question.repo, &[40, 64])
    {
        return Err(refuse("goals.question"));
    }
    Ok(goals)
}

/// Project only typed paths and numbers into the renderer's format. Store/kernel version words are
/// supplied by the pinned store protocol; no kernel reason or arbitrary answer field is copied.
pub fn offer_value(
    goals: &Goals,
    answer: &Answer,
    base_tree: &BTreeMap<String, String>,
) -> Result<Value> {
    let mut historical = BTreeMap::<String, BTreeSet<String>>::new();
    for route in answer.goals.iter().filter_map(|goal| goal.route.as_ref()) {
        for (path, blobs) in &route.blobs {
            historical
                .entry(path.clone())
                .or_default()
                .extend(blobs.iter().cloned());
        }
    }
    let mut output = Vec::new();
    for goal in &answer.goals {
        let empty = BTreeSet::new();
        let state = file_state(
            &goal.goal,
            base_tree,
            historical.get(&goal.goal).unwrap_or(&empty),
        )?;
        let value = if let Some(route) = &goal.route {
            let mut roads = Vec::new();
            for road in &route.roads {
                roads.push(json!({"to":road.to,"walked_by":road.turns,
                "state":file_state(&road.to,base_tree,&historical[&road.to])?}));
            }
            json!({"path":goal.goal,"state":state,"route":{"roads":roads,"cost_millis":route.cost_millis,"dearer_ways":route.dearer_ways}})
        } else {
            json!({"path":goal.goal,"state":state,"route":null,"none":goal.none})
        };
        output.push(value);
    }
    Ok(
        json!({"offer":1,"history":goals.history,"ranker":goals.ranker,"store":answer.store,"kernel":answer.kernel,
        "measure":{"name":goals.measure.name,"version":goals.measure.version.to_string()},"chosen":goals.chosen,"goals":output}),
    )
}

/// Validate both files and the real scored base before writing anything.
pub fn make(
    goals_path: &Path,
    answer_path: &Path,
    repo: &Path,
    base: &str,
    out: &Path,
) -> Result<()> {
    let goals = read_goals(goals_path)?;
    let repo_id = history::repository_id(repo, base)?;
    if goals.question.repo != repo_id {
        return Err(refuse("goals.repo"));
    }
    let answer = read_answer(answer_path, &goals, &repo_id)?;
    let tree = history::tree(repo, base)?;
    let bytes = offer_bytes(&offer_value(&goals, &answer, &tree)?)?;
    history::io(std::fs::write(out, bytes), "out.write")
}

fn offer_bytes(offer: &Value) -> Result<Vec<u8>> {
    let bytes = history::canonical(offer)?;
    if bytes.len() > MAX_ANSWER_BYTES {
        return Err(refuse("offer.size"));
    }
    Ok(bytes)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FileState {
    Same,
    Changed,
    Gone,
}

/// A blob is evidence of the historical contents of this path. A name missing at the scored base is
/// still a goal or a road, with the explicit `gone` mark.
pub fn file_state(
    path: &str,
    base_tree: &BTreeMap<String, String>,
    historical_blobs: &BTreeSet<String>,
) -> Result<FileState> {
    if !room::plain_path(path) {
        return Err(refuse("answer.path"));
    }
    Ok(match base_tree.get(path) {
        None => FileState::Gone,
        Some(blob) if historical_blobs.contains(blob) => FileState::Same,
        Some(_) => FileState::Changed,
    })
}

/// The store's display cost has exactly nine decimal places. Round thousandths half to even using
/// integers; parsing a binary floating point approximation would change boundary cases.
pub fn cost_millis(nats: &str) -> Result<u64> {
    let (whole, fraction) = nats
        .split_once('.')
        .ok_or_else(|| refuse("answer.cost.nats"))?;
    if (whole.len() > 1 && whole.starts_with('0'))
        || !whole.bytes().all(|b| b.is_ascii_digit())
        || fraction.len() != 9
        || !fraction.bytes().all(|b| b.is_ascii_digit())
    {
        return Err(refuse("answer.cost.nats"));
    }
    let whole: u64 = whole.parse().map_err(|_| refuse("answer.cost.nats"))?;
    let fraction: u64 = fraction.parse().map_err(|_| refuse("answer.cost.nats"))?;
    let millis = whole
        .checked_mul(1000)
        .and_then(|whole| whole.checked_add(fraction / 1_000_000))
        .ok_or_else(|| refuse("answer.cost.nats"))?;
    let tail = fraction % 1_000_000;
    let round_up = tail > 500_000 || (tail == 500_000 && millis % 2 == 1);
    millis
        .checked_add(u64::from(round_up))
        .ok_or_else(|| refuse("answer.cost.nats"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn goals(names: &[&str]) -> Goals {
        serde_json::from_value(json!({"ranker":"title-words-1","history":"a".repeat(64),
            "measure":{"name":"share","version":1},"chosen":[{"attempt":"a000000000001","score":2}],
            "goals":names,"question":{"v":1,"repo":"b".repeat(40),"list":"a".repeat(64),
                "measure":{"name":"share","version":1},"goals":names}}))
        .unwrap()
    }

    fn answer() -> Value {
        json!({"v":1,"store":"store-1","kernel":"kernel-1","repo":"b".repeat(40),"list":"a".repeat(64),"for_experiment":true,
        "measure":{"name":"share","version":1,"teaches":["passed_verified"]},"path_rule":1,"taught":5,
        "answers":[{"goal":"gone.txt","route":{
            "paths":["same.txt","changed.txt","gone.txt"],
            "roads":[{"from":null,"to":"same.txt","turns":3,"witness":"a000000000001"},
                {"from":"same.txt","to":"changed.txt","turns":2,"witness":"a000000000002"},
                {"from":"changed.txt","to":"gone.txt","turns":1,"witness":"a000000000003"}],
            "cost":{"num":"1","den":"4","nats":"1.386294361"},"roads_n":3,
            "blobs":{"same.txt":["a".repeat(40),"c".repeat(40)],"changed.txt":["a".repeat(40)],"gone.txt":["a".repeat(40)]},
            "detours":[{"attempt":"a000000000001","item":"i000000000001","family":"codex","visit":4,"seq":7,
                "paths":["same.txt","changed.txt","same.txt","gone.txt"],
                "cost":{"num":"1","den":"8","nats":"2.079441542"},"roads_n":4}]
        }}]})
    }

    // This independent fixture writer handles the ASCII fixtures without using answer_canonical.
    fn fixture_bytes(value: &Value) -> Vec<u8> {
        let mut value = value.clone();
        value.sort_all_objects();
        let mut bytes = serde_json::to_vec(&value).unwrap();
        bytes.push(b'\n');
        bytes
    }

    fn parse_fixture(value: &Value, names: &[&str]) -> Result<Answer> {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("answer.json");
        std::fs::write(&path, fixture_bytes(value)).unwrap();
        read_answer(&path, &goals(names), &"b".repeat(40))
    }

    #[test]
    fn revision_two_answer_projects_the_exact_offer_fields_and_each_base_state() {
        let goals = goals(&["gone.txt"]);
        let answer = parse_fixture(&answer(), &["gone.txt"]).unwrap();
        let tree = BTreeMap::from([
            ("same.txt".into(), "c".repeat(40)),
            ("changed.txt".into(), "b".repeat(40)),
        ]);
        let offer = offer_value(&goals, &answer, &tree).unwrap();
        assert_eq!(
            offer,
            json!({"offer":1,"history":"a".repeat(64),"ranker":"title-words-1","store":"store-1","kernel":"kernel-1",
            "measure":{"name":"share","version":"1"},"chosen":[{"attempt":"a000000000001","score":2}],
            "goals":[{"path":"gone.txt","state":"gone","route":{"roads":[
                {"to":"same.txt","walked_by":3,"state":"same"},{"to":"changed.txt","walked_by":2,"state":"changed"},
                {"to":"gone.txt","walked_by":1,"state":"gone"}],"cost_millis":1386,"dearer_ways":1}}]})
        );
    }

    #[test]
    fn serialized_offer_is_bounded_at_one_mib() {
        let mut offer = json!({"payload":""});
        let overhead = history::canonical(&offer).unwrap().len();
        offer["payload"] = json!("a".repeat(MAX_ANSWER_BYTES - overhead));
        let bytes = offer_bytes(&offer).unwrap();
        assert_eq!(bytes.len(), MAX_ANSWER_BYTES);
        assert_eq!(bytes, history::canonical(&offer).unwrap());
        offer["payload"] = json!("a".repeat(MAX_ANSWER_BYTES - overhead + 1));
        assert_eq!(offer_bytes(&offer).unwrap_err().0, "offer.size");
    }

    #[test]
    fn the_owners_normative_answer_converts_as_it_is() {
        // The store's owner's own file, revision 4 of its spec, byte for byte: nothing is added to it here.
        let bytes = include_bytes!("../tests/fixtures/store-route-r4/answer.json");
        assert_eq!(
            history::sha256(bytes),
            "0acb4f88e9b4f814ed86af6b03e6f55436a7f691c26063269b18e95eda7b0b33"
        );
        let question: history::Question = serde_json::from_slice(include_bytes!(
            "../tests/fixtures/store-route-r4/question.json"
        ))
        .unwrap();
        let mut goals = goals(&["target.txt", "added.txt"]);
        goals.history = question.list.clone();
        goals.question = question;
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("answer.json");
        std::fs::write(&path, bytes).unwrap();
        let answer = read_answer(&path, &goals, &goals.question.repo).unwrap();
        let tree = BTreeMap::from([
            ("b.txt".into(), "5".repeat(40)),
            ("target.txt".into(), "7".repeat(40)),
        ]);
        let offer = offer_value(&goals, &answer, &tree).unwrap();
        assert_eq!(offer["store"], "1");
        assert_eq!(offer["kernel"], "511bacd017146586");
        assert_eq!(offer["measure"], json!({"name":"share","version":"1"}));
        assert_eq!(
            offer["goals"][0]["route"],
            json!({"roads":[{"to":"b.txt","walked_by":1,"state":"same"},
            {"to":"target.txt","walked_by":2,"state":"changed"}],"cost_millis":1504,"dearer_ways":2})
        );
        assert_eq!(
            offer["goals"][1],
            json!({"path":"added.txt","state":"gone","route":null,"none":"never_named"})
        );
        assert_eq!(
            offer["chosen"],
            json!([{"attempt":"a000000000001","score":2}])
        );
        let out = tmp.path().join("offer.json");
        std::fs::write(&out, history::canonical(&offer).unwrap()).unwrap();
        // The room's own reader takes these bytes, and its renderer makes a block of them under each arm that
        // offers. The two were built apart; this is where they meet.
        let read = room::offer::read(&std::fs::read(&out).unwrap()).unwrap();
        assert_eq!(read.goals(), ["target.txt", "added.txt"]);
        for arm in [room::offer::Arm::Route, room::offer::Arm::Shuffled] {
            let block = room::offer::render(&read, arm, 17).unwrap();
            assert!(block.text().contains("b.txt"));
            assert!(!block.is_empty_offer());
        }
        assert!(room::offer::render(&read, room::offer::Arm::Nothing, 17).is_none());
    }

    #[test]
    fn goals_as_well_as_roads_receive_same_changed_and_gone_states() {
        let original = answer();
        let route = &original["answers"][0]["route"];
        let mut value = original.clone();
        let mut answers = Vec::new();
        for (n, goal) in ["same.txt", "changed.txt", "gone.txt"].iter().enumerate() {
            let mut prefix = route.clone();
            prefix["paths"].as_array_mut().unwrap().truncate(n + 1);
            prefix["roads"].as_array_mut().unwrap().truncate(n + 1);
            prefix["roads_n"] = json!(n + 1);
            prefix["detours"] = json!([]);
            prefix["blobs"].as_object_mut().unwrap().retain(|path, _| {
                ["same.txt", "changed.txt", "gone.txt"][..n + 1].contains(&path.as_str())
            });
            answers.push(json!({"goal":goal,"route":prefix}));
        }
        value["answers"] = json!(answers);
        let names = ["same.txt", "changed.txt", "gone.txt"];
        let parsed = parse_fixture(&value, &names).unwrap();
        let tree = BTreeMap::from([
            ("same.txt".into(), "c".repeat(40)),
            ("changed.txt".into(), "b".repeat(40)),
        ]);
        let offer = offer_value(&goals(&names), &parsed, &tree).unwrap();
        assert_eq!(
            offer["goals"]
                .as_array()
                .unwrap()
                .iter()
                .map(|goal| goal["state"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["same", "changed", "gone"]
        );
    }

    #[test]
    fn each_none_shape_is_distinct_and_no_history_has_first_precedence() {
        for kind in ["no_history", "never_named", "not_taught", "refused"] {
            let mut value = answer();
            value["taught"] = json!(if kind == "no_history" { 0 } else { 5 });
            value["answers"][0] = if kind == "refused" {
                json!({"goal":"gone.txt","none":kind,"code":-11,"reason":"KERNEL_PRIVATE_MARKER"})
            } else {
                json!({"goal":"gone.txt","none":kind})
            };
            let parsed = parse_fixture(&value, &["gone.txt"]).unwrap();
            let offer = offer_value(&goals(&["gone.txt"]), &parsed, &BTreeMap::new()).unwrap();
            assert_eq!(
                offer["goals"][0],
                json!({"path":"gone.txt","state":"gone","route":null,"none":kind})
            );
            assert!(!offer.to_string().contains("KERNEL_PRIVATE_MARKER"));
            value["taught"] = json!(if kind == "no_history" { 5 } else { 0 });
            assert_eq!(
                parse_fixture(&value, &["gone.txt"]).unwrap_err().0,
                "answer.answers[0].none.precedence"
            );
        }
    }

    fn locations(
        value: &Value,
        pointer: &str,
        values: &mut Vec<String>,
        fields: &mut Vec<(String, String)>,
        objects: &mut Vec<String>,
    ) {
        values.push(pointer.into());
        if let Some(map) = value.as_object() {
            objects.push(pointer.into());
            for (key, value) in map {
                fields.push((pointer.into(), key.clone()));
                locations(
                    value,
                    &format!("{pointer}/{}", key.replace('~', "~0").replace('/', "~1")),
                    values,
                    fields,
                    objects,
                );
            }
        } else if let Some(array) = value.as_array() {
            for (n, value) in array.iter().enumerate() {
                locations(value, &format!("{pointer}/{n}"), values, fields, objects);
            }
        }
    }

    #[test]
    fn every_answer_field_rejects_wrong_type_missing_and_unknown_fields_without_echo() {
        let mut variants = vec![answer()];
        for kind in ["no_history", "never_named", "not_taught", "refused"] {
            let mut v = answer();
            v["taught"] = json!(if kind == "no_history" { 0 } else { 5 });
            v["answers"][0] = if kind == "refused" {
                json!({"goal":"gone.txt","none":kind,"code":-11,"reason":"reason"})
            } else {
                json!({"goal":"gone.txt","none":kind})
            };
            variants.push(v);
        }
        for valid in variants {
            let (mut values, mut fields, mut objects) = (Vec::new(), Vec::new(), Vec::new());
            locations(&valid, "", &mut values, &mut fields, &mut objects);
            for pointer in values {
                let mut bad = valid.clone();
                let value = bad.pointer_mut(&pointer).unwrap();
                if value.is_number() {
                    for number in [json!(-1), json!(0.5), json!(1e30)] {
                        let mut bad = valid.clone();
                        *bad.pointer_mut(&pointer).unwrap() = number;
                        // A kernel code is signed; -1 is a correctly typed refusal code.
                        if pointer.ends_with("/code") && bad.pointer(&pointer) == Some(&json!(-1)) {
                            continue;
                        }
                        assert!(
                            parse_fixture(&bad, &["gone.txt"]).is_err(),
                            "numeric type at {pointer}"
                        );
                    }
                }
                *value = match value {
                    Value::Null => json!(false),
                    Value::Bool(_) | Value::Number(_) => json!("INPUT_PRIVATE_MARKER"),
                    _ => json!(false),
                };
                let error = parse_fixture(&bad, &["gone.txt"]).unwrap_err().to_string();
                assert!(
                    !error.contains("INPUT_PRIVATE_MARKER"),
                    "{pointer}: {error}"
                );
            }
            for (parent, key) in fields {
                let mut bad = valid.clone();
                bad.pointer_mut(&parent)
                    .unwrap()
                    .as_object_mut()
                    .unwrap()
                    .remove(&key);
                assert!(
                    parse_fixture(&bad, &["gone.txt"]).is_err(),
                    "missing {parent}/{key}"
                );
            }
            for pointer in objects {
                let mut bad = valid.clone();
                bad.pointer_mut(&pointer).unwrap()["UNKNOWN_PRIVATE_MARKER"] = json!(true);
                let error = parse_fixture(&bad, &["gone.txt"]).unwrap_err().to_string();
                assert!(
                    !error.contains("UNKNOWN_PRIVATE_MARKER"),
                    "{pointer}: {error}"
                );
            }
        }
    }

    #[test]
    fn answer_semantic_guards_refuse_identity_order_counts_paths_blobs_and_detours() {
        let prefix = "/answers/0/route";
        let cases = vec![
            ("/store".into(), json!("")),
            ("/store".into(), json!("x".repeat(65))),
            ("/kernel".into(), json!("not a word")),
            ("/v".into(), json!(2)),
            ("/repo".into(), json!("c".repeat(40))),
            ("/list".into(), json!("c".repeat(64))),
            ("/for_experiment".into(), json!(false)),
            ("/path_rule".into(), json!(2)),
            ("/measure/name".into(), json!("ship-share")),
            ("/measure/version".into(), json!(2)),
            ("/measure/teaches".into(), json!(["failed"])),
            ("/answers/0/goal".into(), json!("other.txt")),
            ("/answers/0/goal".into(), json!("../bad")),
            (format!("{prefix}/paths"), json!([])),
            (
                format!("{prefix}/paths"),
                json!(["same.txt", "same.txt", "gone.txt"]),
            ),
            (
                format!("{prefix}/paths"),
                json!(["same.txt", "changed.txt", "wrong.txt"]),
            ),
            (format!("{prefix}/roads_n"), json!(2)),
            (format!("{prefix}/roads/0/from"), json!("same.txt")),
            (format!("{prefix}/roads/1/from"), Value::Null),
            (format!("{prefix}/roads/1/from"), json!("other.txt")),
            (format!("{prefix}/roads/0/to"), json!("other.txt")),
            (format!("{prefix}/roads/0/turns"), json!(0)),
            (format!("{prefix}/roads/0/turns"), json!(6)),
            (format!("{prefix}/roads/0/witness"), json!("")),
            (format!("{prefix}/blobs/same.txt"), json!([])),
            (
                format!("{prefix}/blobs/same.txt"),
                json!(["c".repeat(40), "a".repeat(40)]),
            ),
            (
                format!("{prefix}/blobs/same.txt"),
                json!(["a".repeat(40), "a".repeat(40)]),
            ),
            (format!("{prefix}/blobs/same.txt"), json!(["A".repeat(40)])),
            (format!("{prefix}/detours/0/attempt"), json!("")),
            (format!("{prefix}/detours/0/item"), json!("")),
            (format!("{prefix}/detours/0/family"), json!("MARKER")),
            (format!("{prefix}/detours/0/paths/0"), json!("../MARKER")),
            (format!("{prefix}/detours/0/visit"), json!(0)),
            (
                format!("{prefix}/detours/0/paths"),
                json!(["gone.txt", "same.txt", "gone.txt"]),
            ),
            (format!("{prefix}/detours/0/seq"), json!(-1)),
            (format!("{prefix}/detours/0/seq"), json!("0")),
            (format!("{prefix}/detours/0/roads_n"), json!(1)),
            (format!("{prefix}/cost/num"), json!("0")),
            (format!("{prefix}/cost/num"), json!("")),
            (format!("{prefix}/cost/num"), json!("01")),
            (format!("{prefix}/cost/num"), json!("MARKER")),
            (format!("{prefix}/cost/num"), json!("5")),
            (format!("{prefix}/cost/den"), json!("0")),
            (format!("{prefix}/cost/den"), json!("")),
            (format!("{prefix}/cost/den"), json!("MARKER")),
            (format!("{prefix}/cost/nats"), json!("-1.000000000")),
        ];
        for (pointer, bad_value) in cases {
            let mut bad = answer();
            *bad.pointer_mut(&pointer).unwrap() = bad_value;
            let error = parse_fixture(&bad, &["gone.txt"]).unwrap_err().to_string();
            assert!(!error.contains("MARKER"), "{pointer}");
        }
        // A detour that left its turn's way at the first step: the room numbers steps from nought.
        let mut first_step = answer();
        first_step["answers"][0]["route"]["detours"][0]["seq"] = json!(0);
        parse_fixture(&first_step, &["gone.txt"]).unwrap();
        for extra in [json!([]), json!([{"goal":"gone.txt","none":"unreached"}])] {
            let mut bad = answer();
            bad["answers"] = extra;
            assert!(parse_fixture(&bad, &["gone.txt"]).is_err());
        }
        let mut bad = answer();
        let duplicate = bad["answers"][0]["route"]["detours"][0].clone();
        bad["answers"][0]["route"]["detours"]
            .as_array_mut()
            .unwrap()
            .push(duplicate);
        assert!(parse_fixture(&bad, &["gone.txt"]).is_err());
        // Keep every other route field valid, so endpoint validation is the reason for refusal.
        let mut bad = answer();
        let route = &mut bad["answers"][0]["route"];
        route["paths"][2] = json!("wrong.txt");
        route["roads"][2]["to"] = json!("wrong.txt");
        let blobs = route["blobs"].as_object_mut().unwrap();
        let old = blobs.remove("gone.txt").unwrap();
        blobs.insert("wrong.txt".into(), old);
        route["detours"] = json!([]);
        assert_eq!(
            parse_fixture(&bad, &["gone.txt"]).unwrap_err().0,
            "answer.answers[0].route.paths.end"
        );
        let mut bad = answer();
        let route = &mut bad["answers"][0]["route"];
        route["paths"] = json!([]);
        route["roads"] = json!([]);
        route["roads_n"] = json!(0);
        route["blobs"] = json!({});
        route["detours"] = json!([]);
        assert_eq!(
            parse_fixture(&bad, &["gone.txt"]).unwrap_err().0,
            "answer.answers[0].route.paths"
        );
        let mut bad = answer();
        let detour = &mut bad["answers"][0]["route"]["detours"][0];
        detour["paths"] = json!(["gone.txt", "same.txt", "gone.txt"]);
        detour["visit"] = json!(3);
        detour["roads_n"] = json!(3);
        assert_eq!(
            parse_fixture(&bad, &["gone.txt"]).unwrap_err().0,
            "answer.answers[0].route.detours[0].visit"
        );
    }

    #[test]
    fn canonical_answer_requires_ascii_sorted_keys_one_newline_and_no_duplicate_keys() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("answer.json");
        let bytes = fixture_bytes(&answer());
        for bad in [
            bytes[..bytes.len() - 1].to_vec(),
            [bytes.clone(), vec![b'\n']].concat(),
            String::from_utf8(bytes.clone())
                .unwrap()
                .replacen('{', "{\"v\":1,", 1)
                .into_bytes(),
            serde_json::to_string_pretty(&answer())
                .unwrap()
                .into_bytes(),
        ] {
            std::fs::write(&path, bad).unwrap();
            assert_eq!(
                read_answer(&path, &goals(&["gone.txt"]), &"b".repeat(40))
                    .unwrap_err()
                    .0,
                "answer.canonical"
            );
        }
        assert_eq!(
            answer_canonical(&json!({"reason":"é😀\u{7f}"})).unwrap(),
            b"{\"reason\":\"\\u00e9\\ud83d\\ude00\\u007f\"}\n"
        );
    }

    #[test]
    fn a_path_uses_all_answer_blobs_and_keeps_one_state_even_when_its_goal_was_refused() {
        let mut value = answer();
        value["answers"]
            .as_array_mut()
            .unwrap()
            .push(json!({"goal":"same.txt","none":"refused","code":-11,"reason":"private"}));
        let names = ["gone.txt", "same.txt"];
        let parsed = parse_fixture(&value, &names).unwrap();
        let tree = BTreeMap::from([("same.txt".into(), "c".repeat(40))]);
        let offer = offer_value(&goals(&names), &parsed, &tree).unwrap();
        assert_eq!(offer["goals"][0]["route"]["roads"][0]["state"], "same");
        assert_eq!(offer["goals"][1]["state"], "same");
    }

    #[test]
    fn goals_and_version_words_enforce_the_renderer_limits_and_question_identity() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("goals.json");
        let valid = serde_json::to_value(goals(&["gone.txt"])).unwrap();
        std::fs::write(&path, serde_json::to_vec(&valid).unwrap()).unwrap();
        read_goals(&path).unwrap();
        let (mut values, mut fields, mut objects) = (Vec::new(), Vec::new(), Vec::new());
        locations(&valid, "", &mut values, &mut fields, &mut objects);
        for pointer in values {
            let mut bad = valid.clone();
            *bad.pointer_mut(&pointer).unwrap() = Value::Null;
            std::fs::write(&path, bad.to_string()).unwrap();
            assert!(read_goals(&path).is_err(), "type {pointer}");
        }
        for (parent, key) in fields {
            let mut bad = valid.clone();
            bad.pointer_mut(&parent)
                .unwrap()
                .as_object_mut()
                .unwrap()
                .remove(&key);
            std::fs::write(&path, bad.to_string()).unwrap();
            assert!(read_goals(&path).is_err(), "missing {parent}/{key}");
        }
        for pointer in objects {
            let mut bad = valid.clone();
            bad.pointer_mut(&pointer).unwrap()["UNKNOWN_PRIVATE_MARKER"] = json!(true);
            std::fs::write(&path, bad.to_string()).unwrap();
            assert_eq!(read_goals(&path).unwrap_err().0, "goals.format");
        }
        let mut cases = vec![
            ("/ranker", json!("")),
            ("/ranker", json!("x".repeat(65))),
            ("/ranker", json!("not a word")),
            ("/history", json!("MARKER")),
            ("/measure/name", json!("ship-share")),
            ("/chosen/0/attempt", json!("MARKER")),
            ("/chosen/0/score", json!(0)),
            ("/question/v", json!(2)),
            ("/question/repo", json!("MARKER")),
            ("/question/list", json!("b".repeat(64))),
            ("/question/measure/version", json!(2)),
            ("/question/goals", json!([])),
            ("/goals", json!(["../MARKER"])),
        ];
        cases.push((
            "/chosen",
            json!([{ "attempt":"a000000000001","score":1},{"attempt":"a000000000001","score":2}]),
        ));
        cases.push((
            "/chosen",
            json!(
                (1..=4)
                    .map(|n| json!({"attempt":format!("a{n:012x}"),"score":1}))
                    .collect::<Vec<_>>()
            ),
        ));
        cases.push(("/goals", json!(["gone.txt", "gone.txt"])));
        for (pointer, value) in cases {
            let mut bad = valid.clone();
            *bad.pointer_mut(pointer).unwrap() = value;
            std::fs::write(&path, bad.to_string()).unwrap();
            assert!(read_goals(&path).is_err(), "{pointer}");
        }
        let mut at_limit = valid.clone();
        at_limit["ranker"] = json!("x".repeat(64));
        at_limit["chosen"] = json!(
            (1..=3)
                .map(|n| json!({"attempt":format!("a{n:012x}"),"score":1}))
                .collect::<Vec<_>>()
        );
        let names = (0..64).map(|n| format!("goal{n}.txt")).collect::<Vec<_>>();
        at_limit["goals"] = json!(names);
        at_limit["question"]["goals"] = at_limit["goals"].clone();
        std::fs::write(&path, at_limit.to_string()).unwrap();
        read_goals(&path).unwrap();
        at_limit["goals"]
            .as_array_mut()
            .unwrap()
            .push(json!("goal64.txt"));
        at_limit["question"]["goals"] = at_limit["goals"].clone();
        std::fs::write(&path, at_limit.to_string()).unwrap();
        assert_eq!(read_goals(&path).unwrap_err().0, "goals.limit");
        for word in ["", "x y", "é", &"x".repeat(65)] {
            assert!(version(word, "version").is_err());
        }
        for word in ["a", "1.A-b_c", &"x".repeat(64)] {
            version(word, "version").unwrap();
        }
    }

    #[test]
    fn routes_accept_256_roads_and_refuse_257_and_big_fraction_strings_are_not_u64s() {
        for length in [256, 257] {
            let mut value = answer();
            let names = (0..length).map(|n| format!("p{n}.txt")).collect::<Vec<_>>();
            let goal = names.last().unwrap().clone();
            value["answers"][0]["goal"] = json!(goal);
            let route = &mut value["answers"][0]["route"];
            route["paths"] = json!(names);
            route["roads_n"] = json!(length);
            route["roads"] = json!(
                names
                    .iter()
                    .enumerate()
                    .map(
                        |(n, name)| json!({"from":if n==0 {None} else {Some(&names[n-1])},
                "to":name,"turns":1,"witness":"a000000000001"})
                    )
                    .collect::<Vec<_>>()
            );
            route["blobs"] = json!(
                names
                    .iter()
                    .map(|name| (name.clone(), json!(["a".repeat(40)])))
                    .collect::<Map<_, _>>()
            );
            route["detours"] = json!([]);
            route["cost"] = json!({"num":"1","den":"123456789012345678901234567890123456789","nats":"87.709663899"});
            let result = parse_fixture(&value, &[&goal]);
            if length == 256 {
                assert_eq!(
                    result.unwrap().goals[0].route.as_ref().unwrap().roads.len(),
                    256
                );
            } else {
                assert_eq!(result.unwrap_err().0, "answer.answers[0].route.roads.limit");
            }
        }
    }

    #[test]
    fn answer_bytes_refuse_empty_malformed_surrogate_and_over_one_mib_without_panic_or_echo() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("answer.json");
        for bytes in [
            b"".as_slice(),
            b"MARKER",
            br#"{"MARKER":"\ud800"}"#,
            b"{\"MARKER\":1e999}",
            b"\xff",
        ] {
            std::fs::write(&path, bytes).unwrap();
            assert_eq!(read_answer_json(&path).unwrap_err().0, "answer.json");
        }
        let mut bytes = b"{}".to_vec();
        bytes.resize(1_048_576, b' ');
        std::fs::write(&path, &bytes).unwrap();
        assert_eq!(read_answer_json(&path).unwrap(), serde_json::json!({}));
        bytes.push(b' ');
        std::fs::write(&path, &bytes).unwrap();
        assert_eq!(read_answer_json(&path).unwrap_err().0, "answer.size");
    }

    #[test]
    fn states_use_the_scored_base_and_every_historical_blob_and_refuse_unplain_paths() {
        let tree = BTreeMap::from([
            ("same.txt".into(), "c".repeat(40)),
            ("changed.txt".into(), "b".repeat(40)),
        ]);
        let seen = BTreeSet::from(["c".repeat(40), "a".repeat(40)]);
        assert_eq!(
            file_state("same.txt", &tree, &seen).unwrap(),
            FileState::Same
        );
        assert_eq!(
            file_state("changed.txt", &tree, &seen).unwrap(),
            FileState::Changed
        );
        assert_eq!(
            file_state("gone.txt", &tree, &seen).unwrap(),
            FileState::Gone
        );
        assert_eq!(
            file_state("same.txt", &tree, &BTreeSet::new()).unwrap(),
            FileState::Changed
        );
        for path in [
            "", "a space", "/abs", "a/../b", "a/./b", "a//b", "a\\b", "a\nb", "a\"b", "é",
        ] {
            assert_eq!(file_state(path, &tree, &seen).unwrap_err().0, "answer.path");
        }
    }

    #[test]
    fn decimal_cost_rounds_half_to_even_without_binary_float() {
        for (nats, millis) in [
            ("0.000000000", 0),
            ("0.000500000", 0),
            ("0.001500000", 2),
            ("1.386500000", 1386),
            ("1.387500000", 1388),
            ("1.386499999", 1386),
            ("1.386500001", 1387),
            ("9007199254740.992500000", 9_007_199_254_740_992),
            ("18446744073709551.615000000", u64::MAX),
        ] {
            assert_eq!(cost_millis(nats).unwrap(), millis, "{nats}");
        }
    }

    #[test]
    fn decimal_cost_refuses_noncanonical_or_overflowing_values_by_field_without_echo() {
        for nats in [
            "",
            "MARKER",
            "1",
            "01.000000000",
            ".000000000",
            "-1.000000000",
            "+1.000000000",
            "1.00000000",
            "1.0000000000",
            "1.00000000x",
            "1.+00000000",
            "1.000000000e0",
            " 1.000000000",
            "18446744073709551.615500000",
            "18446744073709551.616000000",
            "18446744073709552.000000000",
            "18446744073709551616.000000000",
        ] {
            assert_eq!(cost_millis(nats).unwrap_err().0, "answer.cost.nats");
        }
    }
}
