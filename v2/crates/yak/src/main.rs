//! `yak`: the command line and the read-only stdio MCP server. Stage 1, task 10.

use std::error::Error;
use std::fs;
use std::io::{self, Write};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use clap::{Args, Parser, Subcommand, ValueEnum};
use room::{CheckOrigin, CheckSpec, ItemId, NewItem, Room, RoomError, limits};
use yak::clock::{self, Event, Mode, Options, Outcome};
use yak::{View, one_line, read_view};

type Result<T> = std::result::Result<T, Box<dyn Error>>;

#[derive(Parser)]
#[command(version, about = "A room for work with frozen checks")]
struct Cli {
    #[arg(long, global = true)]
    room: Option<PathBuf>,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    Init,
    Item {
        #[command(subcommand)]
        command: ItemCommand,
    },
    History {
        #[command(subcommand)]
        command: HistoryCommand,
    },
    Offer {
        #[command(subcommand)]
        command: OfferCommand,
    },
    Clock {
        #[command(subcommand)]
        command: ClockCommand,
    },
    Stop,
    Resume,
    Status(Json),
    Disagreements(Json),
    Mcp,
}

#[derive(Args)]
struct Json {
    #[arg(long)]
    json: bool,
}

#[derive(Subcommand)]
enum ItemCommand {
    Add(Add),
    List(Json),
    Show {
        id: String,
        #[arg(long)]
        json: bool,
    },
    Turns {
        id: String,
        #[arg(long)]
        json: bool,
    },
    Walks {
        id: String,
        #[arg(long, required = true)]
        json: bool,
        #[arg(long)]
        out: Option<PathBuf>,
    },
    Erase {
        id: String,
    },
}

#[derive(Subcommand)]
enum HistoryCommand {
    Make {
        #[arg(long)]
        plan: PathBuf,
        #[arg(long)]
        measure: String,
        #[arg(long)]
        out: PathBuf,
    },
    Check {
        #[arg(long)]
        plan: PathBuf,
        #[arg(long)]
        list: PathBuf,
        #[arg(long)]
        walks: PathBuf,
    },
}

#[derive(Subcommand)]
enum OfferCommand {
    Make {
        #[arg(long)]
        goals: PathBuf,
        #[arg(long)]
        answer: PathBuf,
        #[arg(long)]
        repo: PathBuf,
        #[arg(long)]
        base: String,
        #[arg(long)]
        out: PathBuf,
    },
    Goals {
        #[arg(long)]
        plan: PathBuf,
        #[arg(long)]
        list: PathBuf,
        #[arg(long)]
        title: String,
    },
}

#[derive(Args)]
struct Add {
    #[arg(long)]
    title: String,
    #[arg(long)]
    repo: PathBuf,
    #[arg(long)]
    base: String,
    #[arg(long)]
    check: String,
    /// The check's own files, frozen with it. A check that is a command alone has none.
    #[arg(long, num_args = 1..)]
    file: Vec<String>,
    #[arg(long, num_args = 1..)]
    wrong: Vec<String>,
    #[arg(long, value_enum)]
    origin: Origin,
    #[arg(long)]
    by: String,
    #[arg(long, num_args = 1..)]
    after: Vec<String>,
}

#[derive(Clone, Copy, ValueEnum)]
enum Origin {
    Outside,
    Observed,
    Model,
}

#[derive(Subcommand)]
enum ClockCommand {
    Run(Run),
}

#[derive(Args)]
struct Run {
    // Each of the four numbers may be given more than once; the last one counts.
    #[arg(long)]
    once_through: bool,
    #[arg(long, num_args = 1.., required = true)]
    worker: Vec<String>,
    #[arg(long, default_value_t = limits::LEASE_SECS, overrides_with = "lease_secs")]
    lease_secs: i64,
    #[arg(long, default_value_t = limits::TURN_SECS, value_parser = clap::value_parser!(u32).range(1..), overrides_with = "turn_secs")]
    turn_secs: u32,
    #[arg(long, default_value_t = limits::DAILY_TURNS, overrides_with = "daily_turns")]
    daily_turns: u32,
    #[arg(long, default_value_t = limits::CONCURRENT_TURNS, overrides_with = "concurrent")]
    concurrent: u32,
    /// Begin each turn's prompt with a line of that turn's own, so that two turns at one item do not begin
    /// alike. For measuring what a worker's program keeps of a prompt it has seen before.
    #[arg(long)]
    own_prompts: bool,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> ExitCode {
    let cli = match Cli::try_parse() {
        Ok(cli) => cli,
        Err(error) => {
            if matches!(
                error.kind(),
                clap::error::ErrorKind::DisplayHelp | clap::error::ErrorKind::DisplayVersion
            ) {
                print!("{error}");
                return ExitCode::SUCCESS;
            }
            eprintln!("{}", one_line(&error.to_string()));
            return ExitCode::FAILURE;
        }
    };
    match execute(cli).await {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{}", one_line(&error.to_string()));
            ExitCode::FAILURE
        }
    }
}

async fn execute(cli: Cli) -> Result<()> {
    let dir = match cli.room {
        Some(dir) => dir,
        None => {
            PathBuf::from(std::env::var_os("HOME").ok_or("HOME is not set: pass --room <dir>")?)
                .join(".superyak/v2/room")
        }
    };
    match cli.command {
        Command::Init => {
            Room::init(&dir)?;
        }
        Command::Item { command } => match command {
            ItemCommand::Add(add) => add_item(&dir, add)?,
            ItemCommand::List(format) => print_view(&dir, View::ItemList, format.json)?,
            ItemCommand::Show { id, json } => print_view(&dir, View::ItemShow(ItemId(id)), json)?,
            ItemCommand::Turns { id, json } => print_view(&dir, View::ItemTurns(ItemId(id)), json)?,
            ItemCommand::Walks { id, out, .. } => {
                io::stdout().write_all(&yak::history::item_walks(
                    &dir,
                    &ItemId(id),
                    out.as_deref(),
                )?)?;
            }
            ItemCommand::Erase { id } => Room::open(&dir)?.erase_item(&ItemId(id))?,
        },
        Command::History { command } => match command {
            HistoryCommand::Make { plan, measure, out } => {
                println!(
                    "{}",
                    yak::history::make(
                        &yak::history::read_plan(&plan)?,
                        yak::history::Measure::parse(&measure)?,
                        &out
                    )?
                );
            }
            HistoryCommand::Check { plan, list, walks } => {
                yak::history::check(&yak::history::read_plan(&plan)?, &list, &walks)?;
            }
        },
        Command::Offer {
            command:
                OfferCommand::Make {
                    goals,
                    answer,
                    repo,
                    base,
                    out,
                },
        } => {
            yak::route_offer::make(&goals, &answer, &repo, &base, &out)?;
        }
        Command::Offer {
            command: OfferCommand::Goals { plan, list, title },
        } => {
            let bytes = yak::history::goals_json(&yak::history::read_plan(&plan)?, &list, &title)?;
            io::stdout().write_all(&bytes)?;
            println!();
        }
        Command::Status(format) => print_view(&dir, View::Status, format.json)?,
        Command::Disagreements(format) => print_view(&dir, View::Disagreements, format.json)?,
        Command::Stop | Command::Resume => {
            // STOP is outside the database lock, so it works while the clock owns the writer.
            Room::open_read_only(&dir)?;
            let stop = dir.join("STOP");
            if matches!(cli.command, Command::Stop) {
                make_stop_file(&stop)?;
            } else if let Err(error) = fs::remove_file(stop)
                && error.kind() != io::ErrorKind::NotFound
            {
                return Err(error.into());
            }
        }
        Command::Clock {
            command: ClockCommand::Run(run),
        } => run_clock(&dir, run)?,
        Command::Mcp => yak::mcp::serve(&dir).await?,
    }
    Ok(())
}

/// Makes the file that stops the room, new, or finds the one already there. Anything else at that name is
/// refused and nothing is written: a link would have the file it names emptied, and a link to nowhere would
/// leave the room running after this command said it had stopped.
fn make_stop_file(stop: &Path) -> Result<()> {
    match fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(stop)
    {
        Ok(_) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
            if fs::symlink_metadata(stop).is_ok_and(|meta| meta.is_file()) {
                Ok(())
            } else {
                Err(RoomError::Refused(format!(
                    "{} is there and is not a file, so the room is not stopped: remove it and stop again",
                    stop.display()
                ))
                .into())
            }
        }
        Err(error) => Err(error.into()),
    }
}

fn add_item(dir: &Path, add: Add) -> Result<()> {
    let mut room = Room::open(dir)?;
    if !add
        .by
        .split_once(':')
        .is_some_and(|(family, name)| !family.is_empty() && !name.is_empty())
    {
        return Err(RoomError::Refused("--by must be <family>:<name>".into()).into());
    }
    let repo = add.repo.canonicalize()?;
    let base_commit = resolve_commit(&repo, &add.base)
        .ok_or_else(|| RoomError::Refused(format!("unknown base commit: {}", add.base)))?;
    // Every wrong commit must be a commit of the repository, or nothing is added; the refusal names the first
    // value that is not one.
    let mut wrong_artifacts = Vec::with_capacity(add.wrong.len());
    for wrong in &add.wrong {
        let commit = resolve_commit(&repo, wrong).ok_or_else(|| {
            RoomError::Refused(format!(
                "--wrong {wrong} is not a commit of the repository {}",
                repo.display()
            ))
        })?;
        wrong_artifacts.push(commit);
    }
    let check = CheckSpec {
        command: add.check,
        files: add.file,
        timeout_secs: limits::CHECK_TIMEOUT_SECS,
        origin: match add.origin {
            Origin::Outside => CheckOrigin::Outside,
            Origin::Observed => CheckOrigin::ObservedFailure,
            Origin::Model => CheckOrigin::Model,
        },
        wrong_artifacts,
        written_by: add.by,
    };
    // A check that could never be frozen would only fail later, at the clock: refuse it now.
    turn::check::freezable(&repo, &base_commit, &check)?;
    let id = room.add_item(NewItem {
        title: add.title,
        repo,
        base_commit,
        after: add.after.into_iter().map(ItemId).collect(),
        check,
    })?;
    println!("{}", id.0);
    Ok(())
}

/// The full id of the commit `name` names in `repo`, or `None` when it names no commit there: no object, a tree,
/// a blob, or nothing at all.
fn resolve_commit(repo: &Path, name: &str) -> Option<String> {
    let output = turn::sandbox::safe_git()
        .arg("-C")
        .arg(repo)
        .args([
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            &format!("{name}^{{commit}}"),
        ])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let commit = String::from_utf8(output.stdout).ok()?.trim().to_owned();
    (!commit.is_empty()).then_some(commit)
}

fn print_view(dir: &Path, view: View, json: bool) -> Result<()> {
    let value = read_view(dir, &view)?;
    if json {
        println!("{value}");
    } else {
        println!("{}", serde_json::to_string_pretty(&value)?);
    }
    Ok(())
}

fn run_clock(dir: &Path, run: Run) -> Result<()> {
    clean_clock_environment()?;
    // This gate precedes all worker parsing, executable lookup, and jail setup.
    if run
        .worker
        .iter()
        .any(|worker| !worker.starts_with("script:"))
    {
        for (name, unsafe_value) in [("YAK_JAIL", "off"), ("YAK_SUPERVISION", "best-effort")] {
            if std::env::var(name).as_deref() == Ok(unsafe_value) {
                return Err(RoomError::Refused(format!(
                    "{name}={unsafe_value} permits only script: workers"
                ))
                .into());
            }
        }
    }
    let mut room = Room::open(dir)?;
    // Said at the start, and nothing is made to say it.
    if turn::jail::wanted() {
        turn::jail::check_settings()?;
    }
    room.set_lease_secs(run.lease_secs)?;
    room.set_ceiling(run.daily_turns, run.concurrent)?;
    let mut stdout = io::stdout().lock();
    let mut report = |event: &Event| {
        // The clock's result determines its exit code, including when its output pipe closes.
        let _ = writeln!(stdout, "{}", one_line(&event_line(event))).and_then(|()| stdout.flush());
    };
    let mode = if run.once_through {
        Mode::OnceThrough
    } else {
        Mode::Forever
    };
    clock::run_with(
        &mut room,
        &run.worker,
        mode,
        &mut rand::rng(),
        Options {
            turn_secs: run.turn_secs,
            report: Some(&mut report),
            own_prompts: run.own_prompts,
            ..Options::default()
        },
    )?;
    Ok(())
}

fn clean_clock_environment() -> Result<()> {
    const KEPT: &[&str] = &[
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TMPDIR",
        "TZ",
        "CODEX_HOME",
        "CLAUDE_CONFIG_DIR",
        // Where the system's compiler kit is, on macOS: a run keeps them too (`turn`'s `ENV_KEPT`).
        "SDKROOT",
        "DEVELOPER_DIR",
        "YAK_JAIL",
        "YAK_JAIL_READ",
        "YAK_SUPERVISION",
    ];
    let allowed = |name: &std::ffi::OsStr| name.to_str().is_some_and(|name| KEPT.contains(&name));
    if std::env::vars_os().any(|(name, _)| !allowed(&name)) {
        let executable = std::env::current_exe()?;
        let kept = std::env::vars_os().filter(|(name, _)| allowed(name));
        {
            let mut stdout = io::stdout().lock();
            writeln!(stdout, "starting again with a clean environment")?;
            stdout.flush()?;
        }
        let error = std::process::Command::new(executable)
            .args(std::env::args_os().skip(1))
            .env_clear()
            .envs(kept)
            .exec();
        return Err(format!("could not start the clock with a clean environment: {error}").into());
    }
    Ok(())
}

fn event_line(event: &Event) -> String {
    match event {
        Event::Cleared { name, ended } => format!("cleared {name}; running process ended: {ended}"),
        Event::Frozen { item, state } => format!("frozen {}; state {}", item.0, state_name(*state)),
        Event::NotFrozen { item, reason } => format!("not frozen {}: {reason}", item.0),
        Event::Started {
            item,
            attempt,
            lease_no,
            worker,
        } => format!(
            "started {} lease {lease_no}, attempt {}, worker {worker}",
            item.0, attempt.0
        ),
        Event::Ended {
            item,
            lease_no,
            outcome,
        } => {
            let result = match outcome {
                Outcome::Judged {
                    state,
                    commit,
                    nothing,
                    timed_out,
                    recheck,
                } => {
                    let mut result = format!("{}, commit {commit}", state_name(*state));
                    if *timed_out {
                        result.push_str("; timed out");
                    }
                    if let Some(why) = nothing {
                        result.push_str(&format!("; no new commit: {why}"));
                    }
                    if let Some(state) = recheck {
                        result.push_str(&format!("; rechecked: {}", state_name(*state)));
                    }
                    result
                }
                Outcome::Stopped => "stopped".into(),
                Outcome::LeaseLost => "lease lost".into(),
                Outcome::NotRun { reason } => format!("could not run: {reason}"),
                Outcome::Unchecked { reason } => format!("not checked: {reason}"),
            };
            format!("ended {} lease {lease_no}: {result}", item.0)
        }
        Event::Ceiling { used, limit } => format!("daily ceiling reached: {used} of {limit} turns"),
        Event::Problem { item, what } => match item {
            Some(item) => format!("problem with {}: {what}", item.0),
            None => format!("problem: {what}"),
        },
    }
}

fn state_name(state: room::ItemState) -> &'static str {
    use room::ItemState::*;
    match state {
        Draft => "draft",
        Open => "open",
        Leased => "leased",
        Checking => "checking",
        PassedVerified => "passed verified",
        PassedUnverified => "passed unverified",
        Failed => "failed",
        Blocked => "blocked",
        Abandoned => "abandoned",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn event_lines_include_optional_results_and_problem_ownership() {
        let item = ItemId("i0123456789ab".into());
        let judged = |nothing, timed_out, recheck| Event::Ended {
            item: item.clone(),
            lease_no: 2,
            outcome: Outcome::Judged {
                state: room::ItemState::PassedVerified,
                commit: "a".repeat(40),
                nothing,
                timed_out,
                recheck,
            },
        };
        let plain = event_line(&judged(None, false, None));
        assert!(plain.contains("ended i0123456789ab lease 2: passed verified"));
        assert!(
            !plain.contains("timed out")
                && !plain.contains("no new commit")
                && !plain.contains("rechecked")
        );
        let detailed = event_line(&judged(
            Some("unchanged".into()),
            true,
            Some(room::ItemState::PassedUnverified),
        ));
        assert!(detailed.contains("timed out"));
        assert!(detailed.contains("no new commit: unchanged"));
        assert!(detailed.contains("rechecked: passed unverified"));
        let problem = event_line(&Event::Problem {
            item: Some(item),
            what: "cleanup failed".into(),
        });
        assert!(problem.contains("i0123456789ab") && problem.contains("cleanup failed"));
        assert_eq!(
            event_line(&Event::Problem {
                item: None,
                what: "cleanup failed".into()
            }),
            "problem: cleanup failed"
        );
        assert_eq!(
            one_line("first\nsecond\rthird\u{2028}fourth"),
            "first second third fourth"
        );
    }
}
