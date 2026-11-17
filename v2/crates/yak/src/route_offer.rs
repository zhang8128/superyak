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
/// The one version of the store's answer the room reads. Its limit on detours is a constant of it.
pub const STORE_VERSION: &str = "3";
/// The most detours a route of `STORE_VERSION` carries; the dearer ways past them are counted.
pub const MAX_DETOURS: usize = 16;
/// The most digits in a route's own cost. The comparing of each kept detour's cost with the route's takes
/// time of the route's digits times the detour's, and the answer's size bounds the detour's.
pub const MAX_COST_DIGITS: usize = 8192;

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

/// A cost as the answer gives it: the share of turns `num/den`, whole numbers of any length with `num` at
/// most `den`, so the dearer way has the smaller fraction; and its negative logarithm in thousandths,
/// which is shown and decides nothing.
#[derive(Debug)]
struct Cost {
    num: String,
    den: String,
    millis: u64,
}

fn cost(value: &Value, at: &str) -> Result<Cost> {
    let fields = object(value, &["num", "den", "nats"], at)?;
    let num = fraction_integer(&fields["num"], &format!("{at}.num"))?;
    let den = fraction_integer(&fields["den"], &format!("{at}.den"))?;
    if (num.len(), &num) > (den.len(), &den) {
        return Err(refuse(at));
    }
    let millis = cost_millis(string(&fields["nats"], &format!("{at}.nats"))?)
        .map_err(|_| refuse(&format!("{at}.nats")))?;
    Ok(Cost { num, den, millis })
}

/// Whole numbers are worked in limbs of nine decimal digits, least significant first: a product of two
/// limbs, a limb and a carry together stay below 2^64.
const LIMB: u64 = 1_000_000_000;
const LIMB_DIGITS: usize = 9;

/// The limbs of a whole number written in decimal digits.
fn limbs(digits: &str) -> Vec<u64> {
    digits
        .as_bytes()
        .rchunks(LIMB_DIGITS)
        .map(|chunk| {
            chunk
                .iter()
                .fold(0, |limb, digit| limb * 10 + u64::from(digit - b'0'))
        })
        .collect()
}

/// The exact product of two whole numbers in limbs, by the schoolbook method.
fn product(a: &[u64], b: &[u64]) -> Vec<u64> {
    let mut out = vec![0; a.len() + b.len()];
    for (i, &x) in a.iter().enumerate() {
        let mut carry = 0;
        for (j, &y) in b.iter().enumerate() {
            let sum = out[i + j] + x * y + carry;
            out[i + j] = sum % LIMB;
            carry = sum / LIMB;
        }
        out[i + b.len()] = carry;
    }
    out
}

/// Two whole numbers in limbs, compared: below any nought limbs at the top, the one with more limbs is the
/// greater, and of two as long, the first limb from the top that differs decides.
fn compare_whole(a: &[u64], b: &[u64]) -> std::cmp::Ordering {
    let trim = |n: &[u64]| n.len() - n.iter().rev().take_while(|&&limb| limb == 0).count();
    let (a, b) = (&a[..trim(a)], &b[..trim(b)]);
    a.len()
        .cmp(&b.len())
        .then_with(|| a.iter().rev().cmp(b.iter().rev()))
}

/// Two costs' fractions, compared exactly: `a.num/a.den` against `b.num/b.den` is `a.num * b.den` against
/// `b.num * a.den`, the products worked as whole numbers of any length.
fn compare_shares(a: &Cost, b: &Cost) -> std::cmp::Ordering {
    compare_whole(
        &product(&limbs(&a.num), &limbs(&b.den)),
        &product(&limbs(&b.num), &limbs(&a.den)),
    )
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
    dearer_ways: u64,
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
        &[
            "paths",
            "roads",
            "cost",
            "roads_n",
            "blobs",
            "detours",
            "detours_more",
        ],
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
    let route_cost = cost(&fields["cost"], &format!("{at}.cost"))?;
    // Its `num` is at most its `den`, and neither has a leading zero, so the den's digits bound both.
    if route_cost.den.len() > MAX_COST_DIGITS {
        return Err(refuse(&format!("{at}.cost.limit")));
    }
    let detours = array(&fields["detours"], &format!("{at}.detours"))?;
    if detours.len() > MAX_DETOURS {
        return Err(refuse(&format!("{at}.detours.limit")));
    }
    let more = whole(&fields["detours_more"], &format!("{at}.detours_more"))?;
    // The store leaves dearer ways out only once it has kept as many as it carries.
    if more > 0 && detours.len() < MAX_DETOURS {
        return Err(refuse(&format!("{at}.detours_more.kept")));
    }
    // A turn goes one way to a file, so the dearer ways, kept and counted, are at most the turns let teach.
    // A sum past the largest whole number is past any count of turns, and refused as that.
    let dearer_ways = (detours.len() as u64)
        .checked_add(more)
        .ok_or_else(|| refuse(&format!("{at}.detours_more.taught")))?;
    if dearer_ways > taught {
        return Err(refuse(&format!("{at}.detours_more.taught")));
    }
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
        let detour_cost = cost(&detour["cost"], &format!("{at}.cost"))?;
        // A kept detour costs more than the route: its share is the smaller. The same share, or a greater
        // one, is not a dearer way, however the two are written.
        if compare_shares(&detour_cost, &route_cost).is_ge() {
            return Err(refuse(&format!("{at}.cost.order")));
        }
    }
    Ok(ParsedRoute {
        roads: parsed,
        blobs,
        cost_millis: route_cost.millis,
        dearer_ways,
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
    // Before anything the store's version shapes: an answer of another version is to be made again, and is
    // refused as that, not by the first field its shape lacks.
    let store = string(&fields["store"], "answer.store")?;
    version(store, "answer.store")?;
    if store != STORE_VERSION {
        return Err(refuse("answer.store.version"));
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
    let kernel = string(&fields["kernel"], "answer.kernel")?;
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
        json!({"v":1,"store":"3","kernel":"kernel-1","repo":"b".repeat(40),"list":"a".repeat(64),"for_experiment":true,
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
                "cost":{"num":"1","den":"8","nats":"2.079441542"},"roads_n":4}],
            "detours_more":0
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
            json!({"offer":1,"history":"a".repeat(64),"ranker":"title-words-1","store":"3","kernel":"kernel-1",
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
        // The store's owner's own file, revision 7 of its spec, byte for byte: nothing is added to it here.
        let bytes = include_bytes!("../tests/fixtures/store-route-r7/answer.json");
        assert_eq!(
            history::sha256(bytes),
            "bb7e7d0a2d86a2d798ab378bb79d54d372e70bf600ea6422fe3dd1aa3b44dde8"
        );
        let question: history::Question = serde_json::from_slice(include_bytes!(
            "../tests/fixtures/store-route-r7/question.json"
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
        assert_eq!(offer["store"], "3");
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
        // The route arm's block says each road's count and the dearer ways' count, in its own sentences.
        let text = room::offer::render(&read, room::offer::Arm::Route, 17)
            .unwrap()
            .text()
            .to_owned();
        for line in [
            "   from where every turn starts to b.txt: walked by 1 earlier turn\n",
            "   then to target.txt (changed since): walked by 2 earlier turns\n",
            "   2 earlier turns went a dearer way to it\n",
        ] {
            assert!(text.contains(line), "{line:?} in {text:?}");
        }
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
            ("/store".into(), json!("2")),
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
            (format!("{prefix}/detours_more"), json!(1)),
            (format!("{prefix}/detours_more"), json!(-1)),
            (format!("{prefix}/detours_more"), json!("MARKER")),
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
        // One road more than the way has places, and one fewer: each refused by the count's name. That
        // comparison is all that stands between a store's answer and an index past the end of the way.
        for more in [true, false] {
            let mut bad = answer();
            let roads = bad["answers"][0]["route"]["roads"].as_array_mut().unwrap();
            if more {
                let extra = roads.last().unwrap().clone();
                roads.push(extra);
            } else {
                roads.pop();
            }
            assert_eq!(
                parse_fixture(&bad, &["gone.txt"]).unwrap_err().0,
                "answer.answers[0].route.roads_n"
            );
        }
        // A route where no turn taught is refused as that, before any road's count is looked at.
        let mut bad = answer();
        bad["taught"] = json!(0);
        assert_eq!(
            parse_fixture(&bad, &["gone.txt"]).unwrap_err().0,
            "answer.answers[0].none.precedence"
        );
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
        // A goal that is not a plain path is refused as that, and not only because the question's goals
        // differ: here the question names the same goal.
        let mut bad = valid.clone();
        bad["goals"] = json!(["../MARKER"]);
        bad["question"]["goals"] = json!(["../MARKER"]);
        std::fs::write(&path, bad.to_string()).unwrap();
        assert_eq!(read_goals(&path).unwrap_err().0, "goals.path");
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

    const ROUTE: &str = "answer.answers[0].route";

    /// The test answer with `kept` detours in rising order of attempt, `more` counted beside them, and
    /// `taught` turns let teach. Every road's count stays within a `taught` of 3 or more.
    fn with_detours(kept: usize, more: Value, taught: u64) -> Value {
        let mut value = answer();
        value["taught"] = json!(taught);
        let route = &mut value["answers"][0]["route"];
        let detour = route["detours"][0].clone();
        route["detours"] = (1..=kept)
            .map(|n| {
                let mut detour = detour.clone();
                detour["attempt"] = json!(format!("a{n:012x}"));
                detour
            })
            .collect();
        route["detours_more"] = more;
        value
    }

    /// The offer made of the test answer with its one goal, `gone.txt`, at a base that holds no file.
    fn offer_of(value: &Value) -> Result<Value> {
        let answer = parse_fixture(value, &["gone.txt"])?;
        offer_value(&goals(&["gone.txt"]), &answer, &BTreeMap::new())
    }

    /// What the offer file's `dearer_ways` carries for the answer's one route, read as a plain whole number.
    fn dearer_ways(value: &Value) -> Result<u64> {
        Ok(offer_of(value)?["goals"][0]["route"]["dearer_ways"]
            .as_u64()
            .unwrap())
    }

    /// The block the room's own reader and renderer make of an offer's canonical bytes, under the route arm.
    fn route_block(offer: &Value) -> String {
        let read = room::offer::read(&history::canonical(offer).unwrap()).unwrap();
        room::offer::render(&read, room::offer::Arm::Route, 17)
            .unwrap()
            .text()
            .to_owned()
    }

    /// Read the answer's canonical bytes with `detours_more` written as `literal`, which may be a number
    /// serde's own writer never makes (`1.0`, `1e3`, 2^64), so the reader meets the literal itself.
    fn parse_with_more(value: &Value, literal: &str) -> Result<Answer> {
        let mut value = value.clone();
        value["answers"][0]["route"]["detours_more"] = json!(424_242);
        let text = String::from_utf8(fixture_bytes(&value)).unwrap();
        let field = "\"detours_more\":424242";
        assert_eq!(text.matches(field).count(), 1);
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("answer.json");
        std::fs::write(
            &path,
            text.replace(field, &format!("\"detours_more\":{literal}")),
        )
        .unwrap();
        read_answer(&path, &goals(&["gone.txt"]), &"b".repeat(40))
    }

    #[test]
    fn only_the_stores_version_3_is_read_and_another_is_refused_by_its_version() {
        parse_fixture(&answer(), &["gone.txt"]).unwrap();
        for (store, refusal) in [
            ("2", "answer.store.version"),
            ("4", "answer.store.version"),
            ("03", "answer.store.version"),
            // Words that begin with the version are not it: the version is the whole word.
            ("30", "answer.store.version"),
            ("33", "answer.store.version"),
            ("3.0", "answer.store.version"),
            ("3 ", "answer.store"),
            ("", "answer.store"),
        ] {
            let mut bad = answer();
            bad["store"] = json!(store);
            assert_eq!(
                parse_fixture(&bad, &["gone.txt"]).unwrap_err().0,
                refusal,
                "{store:?}"
            );
        }
        // An answer of the version before, without the counted field, is refused by its version and not by
        // the first field its shape lacks.
        let mut old = answer();
        old["store"] = json!("2");
        old["answers"][0]["route"]
            .as_object_mut()
            .unwrap()
            .remove("detours_more");
        assert_eq!(
            parse_fixture(&old, &["gone.txt"]).unwrap_err().0,
            "answer.store.version"
        );
    }

    #[test]
    fn sixteen_detours_convert_and_the_block_says_the_kept_and_the_counted_together() {
        for (more, ways) in [(0, 16), (3, 19)] {
            let value = with_detours(16, json!(more), 19);
            assert_eq!(dearer_ways(&value).unwrap(), ways);
            // The block says the one number, kept and counted together, in its own sentence, once.
            let text = route_block(&offer_of(&value).unwrap());
            let line = format!("   {ways} earlier turns went a dearer way to it\n");
            assert!(text.contains(&line), "{line:?} in {text:?}");
            assert_eq!(text.matches("went a dearer way").count(), 1, "{text:?}");
        }
    }

    #[test]
    fn seventeen_detours_are_refused_whatever_detours_more_is() {
        assert_eq!(dearer_ways(&with_detours(16, json!(0), 30)).unwrap(), 16);
        for more in [json!(0), json!(1), json!(3), json!("MARKER")] {
            assert_eq!(
                parse_fixture(&with_detours(17, more, 30), &["gone.txt"])
                    .unwrap_err()
                    .0,
                format!("{ROUTE}.detours.limit")
            );
        }
    }

    #[test]
    fn a_count_above_nought_is_refused_beside_fewer_than_16_detours() {
        for kept in [0, 1, 15] {
            assert_eq!(
                dearer_ways(&with_detours(kept, json!(0), 19)).unwrap(),
                kept as u64
            );
            assert_eq!(
                parse_fixture(&with_detours(kept, json!(1), 19), &["gone.txt"])
                    .unwrap_err()
                    .0,
                format!("{ROUTE}.detours_more.kept"),
                "{kept}"
            );
        }
    }

    #[test]
    fn the_kept_and_the_counted_together_are_at_most_the_turns_let_teach() {
        let taught = format!("{ROUTE}.detours_more.taught");
        // By way of the count: 16 kept and 3 counted are the 19 turns let teach, and 4 counted are one more.
        assert_eq!(dearer_ways(&with_detours(16, json!(3), 19)).unwrap(), 19);
        assert_eq!(
            parse_fixture(&with_detours(16, json!(4), 19), &["gone.txt"])
                .unwrap_err()
                .0,
            taught
        );
        // By way of the kept ones alone: none counted, and one kept more than the 5 turns let teach.
        assert_eq!(dearer_ways(&with_detours(5, json!(0), 5)).unwrap(), 5);
        assert_eq!(
            parse_fixture(&with_detours(6, json!(0), 5), &["gone.txt"])
                .unwrap_err()
                .0,
            taught
        );
        // At the top of the number's range: a sum of exactly 2^64 - 1 converts, and a count of 2^64 - 1
        // beside 16 is refused by the sum, without a panic or a wrap.
        assert_eq!(
            dearer_ways(&with_detours(16, json!(u64::MAX - 16), u64::MAX)).unwrap(),
            u64::MAX
        );
        for taught_n in [19, u64::MAX] {
            assert_eq!(
                parse_fixture(&with_detours(16, json!(u64::MAX), taught_n), &["gone.txt"])
                    .unwrap_err()
                    .0,
                taught
            );
        }
    }

    #[test]
    fn detours_more_must_be_a_whole_number_and_is_never_echoed() {
        let sixteen = with_detours(16, json!(0), 19);
        // The written literal reaches the reader: a plain 1 converts, and 2^64 - 1 is read as a number.
        let read = parse_with_more(&sixteen, "1").unwrap();
        assert_eq!(read.goals[0].route.as_ref().unwrap().dearer_ways, 17);
        assert_eq!(
            parse_with_more(&sixteen, "18446744073709551615")
                .unwrap_err()
                .0,
            format!("{ROUTE}.detours_more.taught")
        );
        let mut missing = sixteen.clone();
        missing["answers"][0]["route"]
            .as_object_mut()
            .unwrap()
            .remove("detours_more");
        assert_eq!(
            parse_fixture(&missing, &["gone.txt"])
                .unwrap_err()
                .to_string(),
            format!("refused: {ROUTE}.detours_more.missing")
        );
        for literal in [
            "true",
            "1.0",
            "-1",
            "\"1\"",
            "null",
            "[]",
            "18446744073709551616",
            "1e3",
        ] {
            assert_eq!(
                parse_with_more(&sixteen, literal).unwrap_err().to_string(),
                format!("refused: {ROUTE}.detours_more"),
                "{literal}"
            );
        }
    }

    #[test]
    fn sixteen_detours_are_still_in_strictly_rising_order_of_attempt() {
        let value = with_detours(16, json!(0), 19);
        assert_eq!(dearer_ways(&value).unwrap(), 16);
        let mut swapped = value.clone();
        swapped["answers"][0]["route"]["detours"]
            .as_array_mut()
            .unwrap()
            .swap(7, 8);
        assert_eq!(
            parse_fixture(&swapped, &["gone.txt"]).unwrap_err().0,
            format!("{ROUTE}.detours[8].attempt.order")
        );
    }

    /// A cost of the share `num/den`, with no thousandths: the comparing reads the fraction only.
    fn share(num: &str, den: &str) -> Cost {
        Cost {
            num: num.into(),
            den: den.into(),
            millis: 0,
        }
    }

    /// A whole number in limbs, written back in decimal digits: the tests' own reading of a product.
    fn decimal(n: &[u64]) -> String {
        let mut limbs = n.iter().rev().skip_while(|&&limb| limb == 0);
        match limbs.next() {
            None => "0".into(),
            Some(top) => limbs.fold(top.to_string(), |out, limb| out + &format!("{limb:09}")),
        }
    }

    /// `n` noughts.
    fn zeros(n: usize) -> String {
        "0".repeat(n)
    }

    #[test]
    fn whole_number_products_are_exact_past_any_machine_word() {
        // Worked by hand: (10^k - 1)^2 = 10^2k - 2 * 10^k + 1, which is k - 1 nines, an 8, k - 1 noughts
        // and a 1; every limb of it is made by carrying.
        for k in [1, 2, 8, 9, 10, 17, 18, 19, 20, 50, 300] {
            let nines = "9".repeat(k);
            let square = format!("{}8{}1", "9".repeat(k - 1), zeros(k - 1));
            assert_eq!(
                decimal(&product(&limbs(&nines), &limbs(&nines))),
                square,
                "{k}"
            );
        }
        // Worked by hand: 10^a * 10^b = 10^(a + b), on and across the limbs' edges.
        for (a, b) in [(0, 0), (1, 8), (8, 1), (9, 9), (40, 45), (8191, 299)] {
            assert_eq!(
                decimal(&product(
                    &limbs(&format!("1{}", zeros(a))),
                    &limbs(&format!("1{}", zeros(b)))
                )),
                format!("1{}", zeros(a + b)),
                "{a} {b}"
            );
        }
        // Against u128 arithmetic, on numbers whose product it holds.
        let small = [
            1u64,
            2,
            9,
            10,
            999_999_999,
            1_000_000_000,
            1_000_000_001,
            123_456_789,
            987_654_321,
            123_456_789_012_345_678,
            999_999_999_999_999_999,
            1_000_000_000_000_000_000,
            u64::MAX,
        ];
        for a in small {
            for b in small {
                assert_eq!(
                    decimal(&product(&limbs(&a.to_string()), &limbs(&b.to_string()))),
                    (u128::from(a) * u128::from(b)).to_string(),
                    "{a} {b}"
                );
            }
        }
    }

    #[test]
    fn whole_numbers_compare_by_their_limbs_below_any_noughts_from_the_top() {
        use std::cmp::Ordering::{Equal, Greater, Less};
        for (a, b, order) in [
            // A product's top limb may be nought, and is then no length.
            (&[5, 0][..], &[7][..], Less),
            (&[0, 1][..], &[999_999_999][..], Greater),
            (&[3, 4][..], &[3, 4, 0][..], Equal),
            (&[][..], &[0, 0][..], Equal),
            // Of two as long, the top limb decides before the bottom one.
            (&[1, 2][..], &[2, 1][..], Greater),
            (&[9, 1, 5][..], &[1, 2, 5][..], Less),
        ] {
            assert_eq!(compare_whole(a, b), order, "{a:?} {b:?}");
            assert_eq!(compare_whole(b, a), order.reverse(), "{b:?} {a:?}");
        }
    }

    #[test]
    fn shares_compare_exactly_as_their_cross_products() {
        use std::cmp::Ordering::{Equal, Greater, Less};
        // Against u128 arithmetic: shares whose parts lie on and across the limbs' edges, each against
        // every other, so that products of one, two and three limbs meet.
        let parts = [
            1u64,
            2,
            3,
            999_999_999,
            1_000_000_000,
            1_000_000_001,
            999_999_999_999_999_999,
            1_000_000_000_000_000_000,
            u64::MAX,
        ];
        let edges: Vec<(u128, u128)> = parts
            .iter()
            .flat_map(|&d| {
                parts
                    .iter()
                    .filter(move |&&n| n <= d)
                    .map(move |&n| (u128::from(n), u128::from(d)))
            })
            .collect();
        for &(an, ad) in &edges {
            for &(bn, bd) in &edges {
                assert_eq!(
                    compare_shares(
                        &share(&an.to_string(), &ad.to_string()),
                        &share(&bn.to_string(), &bd.to_string())
                    ),
                    (an * bd).cmp(&(bn * ad)),
                    "{an}/{ad} {bn}/{bd}"
                );
            }
        }
        // Against u128 arithmetic: every share n/d with 1 <= n <= d <= 24, against every other.
        let fractions: Vec<(u128, u128)> = (1..=24u128)
            .flat_map(|d| (1..=d).map(move |n| (n, d)))
            .collect();
        for &(an, ad) in &fractions {
            for &(bn, bd) in &fractions {
                assert_eq!(
                    compare_shares(
                        &share(&an.to_string(), &ad.to_string()),
                        &share(&bn.to_string(), &bd.to_string())
                    ),
                    (an * bd).cmp(&(bn * ad)),
                    "{an}/{ad} {bn}/{bd}"
                );
            }
        }
        // Worked by hand, past u128: with N = 10^50, (N - 1)^2 = N(N - 2) + 1, so (N - 1)/N is the greater
        // share than (N - 2)/(N - 1) by 1/(N(N - 1)). The two products are as long and differ in the last
        // limb alone.
        let n = format!("1{}", zeros(50));
        let n_1 = "9".repeat(50);
        let n_2 = format!("{}8", "9".repeat(49));
        assert_eq!(
            compare_shares(&share(&n_1, &n), &share(&n_2, &n_1)),
            Greater
        );
        assert_eq!(compare_shares(&share(&n_2, &n_1), &share(&n_1, &n)), Less);
        // 1/10^200 is the smaller share than 1/4, though 10^200 is nought modulo 2^128.
        let tiny = share("1", &format!("1{}", zeros(200)));
        assert_eq!(compare_shares(&tiny, &share("1", "4")), Less);
        assert_eq!(compare_shares(&share("1", "4"), &tiny), Greater);
        // One share written in two ways is equal to itself, at any length.
        assert_eq!(compare_shares(&share("1", "2"), &share("2", "4")), Equal);
        assert_eq!(
            compare_shares(
                &share(&format!("1{}", zeros(8191)), &format!("4{}", zeros(8191))),
                &share("1", "4")
            ),
            Equal
        );
    }

    /// The owner's normative answer as a value, and the goals its question names. Its bytes are what
    /// `fixture_bytes` writes of it, so a changed copy is read as the owner's own would be.
    fn normative() -> (Value, Goals) {
        let bytes = include_bytes!("../tests/fixtures/store-route-r7/answer.json");
        let value: Value = serde_json::from_slice(bytes).unwrap();
        assert_eq!(fixture_bytes(&value), bytes);
        let question: history::Question = serde_json::from_slice(include_bytes!(
            "../tests/fixtures/store-route-r7/question.json"
        ))
        .unwrap();
        let mut goals = goals(&["target.txt", "added.txt"]);
        goals.history = question.list.clone();
        goals.question = question;
        (value, goals)
    }

    fn parse_normative(value: &Value, goals: &Goals) -> Result<Answer> {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("answer.json");
        std::fs::write(&path, fixture_bytes(value)).unwrap();
        read_answer(&path, goals, &goals.question.repo)
    }

    #[test]
    fn a_kept_detour_that_costs_the_route_or_nought_is_refused_in_the_owners_answer() {
        let (value, goals) = normative();
        // As the owner wrote it: each detour's share, 2/27, is the smaller than the route's 2/9.
        let answer = parse_normative(&value, &goals).unwrap();
        assert_eq!(answer.goals[0].route.as_ref().unwrap().dearer_ways, 2);
        let route_cost = value["answers"][0]["route"]["cost"].clone();
        let nought = json!({"num":"1","den":"1","nats":"0.000000000"});
        for n in [0, 1] {
            for cost in [&route_cost, &nought] {
                let mut bad = value.clone();
                bad["answers"][0]["route"]["detours"][n]["cost"] = cost.clone();
                assert_eq!(
                    parse_normative(&bad, &goals).unwrap_err().0,
                    format!("{ROUTE}.detours[{n}].cost.order"),
                    "{n} {cost}"
                );
            }
        }
    }

    #[test]
    fn a_detour_one_least_step_either_side_of_the_routes_share_is_told_apart_exactly() {
        // The route's share is 1/4. Over a denominator of 4 * 10^12 the least steps either side of it are
        // (10^12 + 1)/(4 * 10^12), a greater share, and (10^12 - 1)/(4 * 10^12), a smaller one. Their
        // negative logarithms are 1.38629436111889..., 1.38629436112089... and the route's
        // 1.38629436111989...: to nine places all three are 1.386294361, and so are their thousandths.
        let nats = "1.386294361";
        let mut value = answer();
        assert_eq!(
            value["answers"][0]["route"]["cost"],
            json!({"num":"1","den":"4","nats":nats})
        );
        for (num, refused) in [("1000000000001", true), ("999999999999", false)] {
            value["answers"][0]["route"]["detours"][0]["cost"] =
                json!({"num":num,"den":"4000000000000","nats":nats});
            let result = parse_fixture(&value, &["gone.txt"]);
            if refused {
                assert_eq!(
                    result.unwrap_err().0,
                    format!("{ROUTE}.detours[0].cost.order")
                );
            } else {
                assert_eq!(
                    result.unwrap().goals[0].route.as_ref().unwrap().cost_millis,
                    1386
                );
            }
        }
    }

    #[test]
    fn equal_shares_written_differently_are_one_share_and_refused() {
        // The file asks no fraction in its lowest terms, so 1/2 and 2/4 are both readable, as one share.
        let half = |num: &str, den: &str| json!({"num":num,"den":den,"nats":"0.693147181"});
        let quarter = json!({"num":"2","den":"8","nats":"1.386294361"});
        for (route, detour) in [
            (half("1", "2"), half("2", "4")),
            (half("2", "4"), half("1", "2")),
        ] {
            let mut value = answer();
            value["answers"][0]["route"]["cost"] = route;
            value["answers"][0]["route"]["detours"][0]["cost"] = detour;
            assert_eq!(
                parse_fixture(&value, &["gone.txt"]).unwrap_err().0,
                format!("{ROUTE}.detours[0].cost.order")
            );
            // Beside it, a quarter is the smaller share than the route's half, however the half is written.
            value["answers"][0]["route"]["detours"][0]["cost"] = quarter.clone();
            parse_fixture(&value, &["gone.txt"]).unwrap();
        }
    }

    #[test]
    fn of_sixteen_kept_detours_the_last_alone_costing_the_route_is_refused_by_its_index() {
        let value = with_detours(16, json!(0), 19);
        assert_eq!(dearer_ways(&value).unwrap(), 16);
        let mut bad = value.clone();
        let route = &mut bad["answers"][0]["route"];
        route["detours"][15]["cost"] = route["cost"].clone();
        assert_eq!(
            parse_fixture(&bad, &["gone.txt"]).unwrap_err().0,
            format!("{ROUTE}.detours[15].cost.order")
        );
    }

    #[test]
    fn a_route_cost_of_8192_digits_converts_and_of_8193_is_refused_before_any_comparing() {
        let limit = format!("{ROUTE}.cost.limit");
        // The spec's numbers, written here and not read from the constant, so that a changed constant fails.
        for digits in [8192, 8193] {
            // A quarter written over 10^(digits - 1): the one detour's 1/8 is still the smaller share.
            let mut quarter = answer();
            quarter["answers"][0]["route"]["cost"] = json!({"num":format!("1{}", zeros(digits - 1)),
                "den":format!("4{}", zeros(digits - 1)),"nats":"1.386294361"});
            // A share of 1/10^(digits - 1), with no detour: only the den is long.
            let mut tiny = answer();
            let nats = if digits == 8192 {
                "18860.474496714"
            } else {
                "18862.777081807"
            };
            tiny["answers"][0]["route"]["cost"] =
                json!({"num":"1","den":format!("1{}", zeros(digits - 1)),"nats":nats});
            tiny["answers"][0]["route"]["detours"] = json!([]);
            for value in [quarter, tiny] {
                let result = parse_fixture(&value, &["gone.txt"]);
                if digits == 8192 {
                    result.unwrap();
                } else {
                    assert_eq!(result.unwrap_err().0, limit);
                }
            }
        }
        // A detour's cost has no such limit: the answer's size bounds it.
        let mut long_detour = answer();
        long_detour["answers"][0]["route"]["detours"][0]["cost"] = json!({"num":"1",
            "den":format!("1{}", zeros(8192)),"nats":"18862.777081807"});
        parse_fixture(&long_detour, &["gone.txt"]).unwrap();
    }

    #[test]
    fn a_detour_cost_of_300000_digits_is_compared_with_a_route_cost_of_8192_without_a_panic() {
        // The route's share is a quarter written over 10^8191, as long as its cost may be. The detours' are
        // written over 10^299999: 1/10^299999, a den of 300,000 digits; an eighth, with num and den as long,
        // the most work of the three; and a quarter, the route's share again, refused only once both
        // products are worked to their last limb.
        let route = json!({"num":format!("1{}", zeros(8191)),"den":format!("4{}", zeros(8191)),
            "nats":"1.386294361"});
        for (num, den, nats, refused) in [
            ("1".to_owned(), "1", "690773.225313121", false),
            (format!("1{}", zeros(299_999)), "8", "2.079441542", false),
            (format!("1{}", zeros(299_999)), "4", "1.386294361", true),
        ] {
            let mut value = answer();
            value["answers"][0]["route"]["cost"] = route.clone();
            value["answers"][0]["route"]["detours"][0]["cost"] =
                json!({"num":num,"den":format!("{den}{}", zeros(299_999)),"nats":nats});
            let result = parse_fixture(&value, &["gone.txt"]);
            if refused {
                assert_eq!(
                    result.unwrap_err().0,
                    format!("{ROUTE}.detours[0].cost.order")
                );
            } else {
                result.unwrap();
            }
        }
    }

    #[test]
    fn a_cost_of_no_whole_number_is_refused_by_its_shape_and_not_by_the_comparing() {
        parse_fixture(&answer(), &["gone.txt"]).unwrap();
        for field in ["num", "den"] {
            for bad in ["0", "", "-1", "+1", " 1", "1 ", "01", "1.0"] {
                for (pointer, at) in [
                    (
                        "/answers/0/route/detours/0/cost",
                        format!("{ROUTE}.detours[0].cost"),
                    ),
                    ("/answers/0/route/cost", format!("{ROUTE}.cost")),
                ] {
                    let mut value = answer();
                    value.pointer_mut(pointer).unwrap()[field] = json!(bad);
                    assert_eq!(
                        parse_fixture(&value, &["gone.txt"]).unwrap_err().0,
                        format!("{at}.{field}"),
                        "{pointer} {field} {bad:?}"
                    );
                }
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
