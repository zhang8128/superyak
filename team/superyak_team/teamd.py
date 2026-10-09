#!/usr/bin/env python3
"""teamd: the one daemon per team. Owns the worker registry, worker processes,
Slack polling and message routing. Agents never talk to Slack or spawn workers
directly; they call this daemon through the team MCP/CLI (mcp.py) over a unix socket.

Usage: run_team.py teamd --team <id> --repo <root> --goal <text>
"""
import argparse
import json
import os
import signal
import stat
import socketserver
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from . import lane, teamlib, workers
from .slack import Slack, SlackError

ACTIVE = ("running",)
LIVE = lane.LIVE_STATES   # with "waiting": a browser lane's listener check failed
LANE_RETRY_S = 30


class Team:
    def __init__(self, team_id, repo, goal, cfg, slack=None, lead_kind="claude"):
        self.team_id, self.repo, self.cfg, self.slack = team_id, str(repo), cfg, slack
        self.dir = teamlib.team_dir(team_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.procs = {}
        self.prepare_procs = {}
        self.stopping = threading.Event()
        # Browser lanes (lane.py). Brokers and their secrets live only in memory: a secret is never written to disk.
        self.brokers, self.lane_secrets, self.lane_checked = {}, set(), {}
        self.lane_stopped_at = {}
        self.turn_instructions = {}         # wid -> its instruction files as its browser turn started (or the error)
        self.clock = time.time
        if not teamlib.get_token(team_id, "lead"):
            teamlib.issue_token(team_id, "lead")
        state_file = self.dir / "state.json"
        if state_file.exists():
            self.state = json.loads(state_file.read_text())
        else:
            self.state = {"team_id": team_id, "goal": goal, "repo": self.repo,
                          "created": time.time(), "kickoff_ts": None, "workers": {},
                          "lead_inbox": [], "lead_cursor": 0, "slack_seen": {},
                          "lead_kind": lead_kind, "config": cfg}
        self.save()

    # ---------- persistence / messaging ----------
    def save(self):
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps(self.state, indent=1))
        os.replace(tmp, self.dir / "state.json")

    def log(self, msg):
        with open(self.dir / "teamd.log", "a") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), self._scrub(msg)))

    def display_name(self, who):
        if who == "lead":
            return "Mal (lead) · %s" % ("Codex" if self.state.get("lead_kind") == "codex" else "Claude")
        w = self.state["workers"].get(who, {})
        return "%s · %s" % (who.capitalize(), "Codex Sol" if w.get("kind") == "codex" else "Claude")

    def say(self, who, text, thread_ts=None):
        """Record locally, then post to Slack (best effort). Returns Slack ts or None.
        Everything outbound is redacted: agent output and stderr are not sanitized at the source.
        A browser lane's secret is scrubbed too (teamlib.redact doesn't know it)."""
        text = self._scrub(teamlib.redact(text))
        teamlib.append_record(self.team_id, {"from": who, "type": "post", "message": text,
                                             "thread_ts": thread_ts})
        if not self.slack:
            return None
        kind = ("lead" if who == "lead" else self.state["workers"].get(who, {}).get("kind", "codex"))
        try:
            return self.slack.post(text, self.display_name(who), kind, thread_ts)
        except SlackError as e:
            self.log("slack post failed: %s" % e)
            return None

    def kickoff(self):
        if self.state["kickoff_ts"] or not self.slack:
            return
        ts = self.say("lead", ":rocket: *Team `%s` started*\n*Goal:* %s\nRepo: `%s`\n"
                              "Reply in a task's thread to talk to that agent; reply here to talk to the lead."
                      % (self.team_id, self.state["goal"], Path(self.repo).name))
        if ts:
            self.state["kickoff_ts"] = ts
            self.state["slack_seen"][ts] = ts
            self.save()

    # ---------- workers ----------
    # Workers are named for Serenity's crew (the lead is Mal); past eight, w9, w10, ...
    CREW = ("kaylee", "wash", "zoe", "simon", "river", "jayne", "inara", "book")

    def _new_worker_id(self):
        for name in self.CREW:
            if name not in self.state["workers"]:
                return name
        n = len(self.state["workers"]) + 1
        while "w%d" % n in self.state["workers"]:
            n += 1
        return "w%d" % n

    def spawn(self, task, kind="codex", context="", mode="build", base=None, prepare=None, browser=False):
        if type(browser) is not bool:
            raise teamlib.RejectedMessage("browser must be true or false")
        if prepare and prepare not in workers.PREPARE_COMMANDS:
            raise teamlib.RejectedMessage("prepare must be one of: %s" % ", ".join(sorted(workers.PREPARE_COMMANDS)))
        if prepare and mode != "build":
            raise teamlib.RejectedMessage("prepare is for build workers (collaborators are read-only)")
        if kind not in ("codex", "claude"):
            raise teamlib.RejectedMessage("kind must be 'codex' or 'claude'")
        if mode not in ("build", "collab"):
            raise teamlib.RejectedMessage("mode must be 'build' or 'collab'")
        if browser:
            lane.check_spawn(self.cfg, kind, mode)
            # The base is resolved once: the commit the broker's Playwright is pinned from is the commit the worktree
            # is made from, even if the branch the lead named moves meanwhile.
            base = workers.resolve_base(self.repo, base)
            # The install and the manifest check, before teamd's lock: a first install can take minutes, and it has
            # its own lock (.install.lock). The lane's first turn checks them again, quickly.
            try:
                lane.prepare_broker(self.repo, base, self._worktrees())
            except lane.LaneRefused as e:
                if e.log:
                    self.log(e.log)
                raise
        with self.lock:
            wid = self._new_worker_id()
            if mode == "build":
                wt = workers.create_worktree(self.repo, self.team_id, wid, base)
                self._seed_engram_config(wt["path"])
            else:   # read-only collaborator: works from the main checkout, never writes or commits
                # Runs from a private scratch room, not the repo: the (unsandboxed) engram MCP
                # server sets itself up in the agent's cwd and would write .engram/ into the repo.
                # The repo stays readable for context. Rooms live outside the teams root, which
                # Claude workers cannot read.
                room = teamlib.rooms_root() / self.team_id / wid
                room.mkdir(parents=True, exist_ok=True)
                wt = {"branch": None, "path": str(room), "base": None}
                self._seed_engram_config(room)
            teamlib.issue_token(self.team_id, wid)    # only once the worktree/room exists
            w = {"kind": kind, "mode": mode, "browser": browser, "task": task, "context": context, "state": "queued",
                 "ident": None, "pid": None, "inbox": [], "turns": 0,
                 "started_at": None, "commit": None, "summary": None, "last_message": "",
                 "thread_ts": None, **wt}
            self.state["workers"][wid] = w
            self.save()
            ts = self.say("lead", "%s *%s* (%s, %s) assigned:\n%s"
                          % (":hammer_and_wrench:" if mode == "build" else ":thought_balloon:",
                             wid.capitalize(), "Codex Sol" if kind == "codex" else "Claude",
                             "builder" if mode == "build" else "collaborator", task))
            if ts:
                w["thread_ts"] = ts
                self.state["slack_seen"][ts] = ts
            self.save()
            if prepare:
                w["state"] = "preparing"
                self.save()
                threading.Thread(target=self._prepare, args=(wid, prepare), daemon=True).start()
            else:
                self._fill_slots()
            return {"worker": wid, "mode": mode, "state": w["state"], "branch": w["branch"],
                    "worktree": w["path"] if mode == "build" else None}

    PREPARE_TIMEOUT_S = 1800

    def _prepare(self, wid, prepare):
        """Install dependencies for a builder before its first turn. Runs outside the sandbox
        because workers have no network; only commands from workers.PREPARE_COMMANDS, no
        lifecycle scripts, killed with the worker on stop/end, log kept local (not posted)."""
        w = self.state["workers"][wid]
        log = self.dir / "workers" / wid / "prepare.log"
        with self.lock:
            if w["state"] != "preparing":
                return
            try:
                proc = workers.start_prepare(prepare, w["path"], log)
            except (OSError, ValueError) as e:
                w["state"] = "failed"
                self.say(wid, ":x: prepare `%s` refused: %s" % (prepare, e), w["thread_ts"])
                self._to_lead(wid, "PREPARE FAILED:", "%s: %s" % (prepare, e))
                self.save()
                return
            self.prepare_procs[wid] = proc
        try:
            rc = proc.wait(timeout=self.PREPARE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self._kill_group(proc)
            rc = "timeout"
        with self.lock:
            self.prepare_procs.pop(wid, None)
            if w["state"] != "preparing":          # stopped meanwhile
                return
            if rc == 0:
                w["state"] = "queued"
                self.log("%s prepared (%s)" % (wid, prepare))
                self._fill_slots()
            else:
                w["state"] = "failed"
                self.say(wid, ":x: prepare `%s` failed (rc=%s); log kept locally for the lead."
                         % (prepare, rc), w["thread_ts"])
                self._to_lead(wid, "PREPARE FAILED:", "%s rc=%s, see %s" % (prepare, rc, log))
            self.save()

    @staticmethod
    def _kill_group(proc):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass

    def _running_count(self):
        return sum(1 for w in self.state["workers"].values() if w["state"] in ACTIVE)

    def _fill_slots(self):
        for wid, w in self.state["workers"].items():
            if self._running_count() >= int(self.cfg["max_workers"]):
                return
            if w["state"] == "queued":
                self._start_turn(wid, self._initial_prompt(wid))

    def _initial_prompt(self, wid):
        w = self.state["workers"][wid]
        brief_name = "collaborator.md" if w.get("mode") == "collab" else "worker.md"
        brief = (teamlib.package_dir() / "roles" / brief_name).read_text()
        lane_brief = ""
        if w.get("browser"):
            lane_brief = ("\n---\n%s\nYour base commit (the advisory set is its @lane-advisory tags): %s\n"
                          % ((teamlib.package_dir() / "roles" / "browser-lane.md").read_text(), w["base"]))
        return ("%s\n\n---\nTeam: %s\nYou are: %s\nTeam goal: %s\nYour worktree (cwd): %s\n"
                "Your branch: %s\nRepository (read for context): %s\nTeammates: %s\n\nYOUR TASK:\n%s\n\n"
                "Context from the lead:\n%s\n"
                % (brief, self.team_id, wid, self.state["goal"], w["path"],
                   w["branch"] or "(none: read-only collaborator)", self.repo,
                   ", ".join("%s (%s, %s)" % (k, v["kind"], v.get("mode", "build"))
                             for k, v in self.state["workers"].items() if k != wid) or "(none yet)",
                   w["task"], w["context"] or "(none)")) + lane_brief

    def _seed_engram_config(self, folder):
        """Engram creates .engram/config.toml in its project root when missing, so the root is
        the worker's own folder (worktree or room), never the repo; copying the repo's config
        keeps the worker on the repo's memory instance.
        Runs once at spawn, before any agent has touched the folder, and never follows
        symlinks: teamd is unsandboxed, so a worker-planted link must not redirect this write."""
        src = Path(self.repo) / ".engram" / "config.toml"
        folder = Path(folder)
        if not src.is_file() or folder == Path(self.repo):
            return
        cfg_dir = folder / ".engram"
        try:
            os.mkdir(cfg_dir, 0o700)
        except FileExistsError:
            pass
        st = os.lstat(cfg_dir)
        if not stat.S_ISDIR(st.st_mode):       # a symlink or file: refuse
            raise teamlib.RejectedMessage("refusing to seed engram config through %s" % cfg_dir)
        data = src.read_bytes()[:65536]
        try:
            fd = os.open(str(cfg_dir / "config.toml"),
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            return                               # already seeded (e.g. a tracked config)
        with os.fdopen(fd, "wb") as f:
            f.write(data)

    def _engram_env(self, w):
        return {"ENGRAM_PROJECT_ROOT": w["path"]}

    def _start_turn(self, wid, prompt):
        """Start a turn. A browser worker's turn first needs its lane (_lane_turn): when the listener check fails it
        waits (False), and when the lane is refused the worker fails (False)."""
        w = self.state["workers"][wid]
        lane_env = None
        if w.get("browser"):
            try:
                lane_env = self._lane_turn(wid)
            except lane.LaneWait as e:
                self._lane_wait(wid, prompt, str(e))
                return False
            except lane.LaneRefused as e:
                self._lane_refused(wid, e)
                return False
            except Exception as e:                       # the registry, the broker's folders, a manifest, a stamp, a bug
                self._lane_refused(wid, lane.LaneRefused("the lane's setup failed (%r)" % e))
                return False
        try:
            return self._launch_turn(wid, prompt, lane_env)
        except Exception as e:
            if not w.get("browser"):
                raise
            proc = self.procs.pop(wid, None)
            if proc is not None and proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
            # a refusal (lane.lane_plugins: a settings file that can't be fully read) says its own reason
            self._lane_refused(wid, e if isinstance(e, lane.LaneRefused)
                               else lane.LaneRefused("the turn couldn't start (%r)" % e))   # ends the broker too
            return False

    def _launch_turn(self, wid, prompt, lane_env):
        w = self.state["workers"][wid]
        wdir = self.dir / "workers" / wid
        if w["kind"] == "codex":
            cmd = workers.codex_command(self.cfg, self.team_id, wid, w["path"], prompt, w["ident"],
                                        w.get("mode", "build"))
            env = self._engram_env(w)
        else:
            cmd = workers.claude_command(self.cfg, self.team_id, wid, w["path"], prompt, w["ident"],
                                         w.get("mode", "build"), self.repo,
                                         lane=w["lane"]["path"] if lane_env else None,
                                         preload=w["lane"]["preload"] if lane_env else None,
                                         plugins_off=lane.lane_plugins(w["path"]) if lane_env else ())
            env = self._engram_env(w)
        if lane_env:
            env.update(lane_env)
            self._instructions_at_start(wid)
            self.procs[wid] = workers.launch(cmd, w["path"], wdir, env, drop_env=lane.DROP_ENV)
        else:
            self.procs[wid] = workers.launch(cmd, w["path"], wdir, env)
        w.pop("lane_wait", None)
        w.update(state="running", pid=self.procs[wid].pid, turns=w["turns"] + 1)
        w["started_at"] = w["started_at"] or time.time()
        w["turn_started"] = time.time()
        self.save()
        self.log("%s turn %d started pid=%s" % (wid, w["turns"], w["pid"]))
        return True

    # ---------- browser lanes (lane.py; docs/superpowers/specs/2026-10-08-browser-lane-design.md) ----------
    def _scrub(self, text):
        return lane.scrub(text, self.lane_secrets)

    def _scrub_files(self, wid, shaped=False):
        """events.jsonl and stderr.log without the secret, once the turn has exited. A write failure is logged: the
        lane's cleanup and the turn's bookkeeping carry on. shaped: the sweep, which doesn't know a dead teamd's
        secrets, removes anything of an endpoint's shape."""
        for name in ("events.jsonl", "stderr.log", "broker-stderr.log"):
            try:
                lane.scrub_file(self.dir / "workers" / wid / name, self.lane_secrets, shaped=shaped)
            except (lane.LaneRefused, OSError) as e:
                self.log("%s" % e)

    def _worktrees(self):
        out = workers.git(self.repo, "worktree", "list", "--porcelain", check=False).stdout
        return [self.repo] + [line[len("worktree "):] for line in out.splitlines() if line.startswith("worktree ")]

    def _lane_turn(self, wid):
        """What a browser worker's turn needs, in the spec's order: the lane folder and teamd's own preload (both checked
        every turn), its port block, the listener check, and at the lane's first turn (or once its broker has died) the
        broker. Returns the turn's environment."""
        w = self.state["workers"][wid]
        try:
            widened = lane.settings_widenings()           # the person's settings may have changed since the spawn
        except lane.LaneRefused:
            raise
        except Exception as e:                            # a check that errs has failed: never swallowed
            raise lane.LaneRefused("the settings check failed (%r)" % e)
        if widened:
            raise lane.LaneRefused("settings outside the lane now widen its sandbox: " + "; ".join(widened))
        path = lane.ensure_lane(self.team_id, wid)
        preload = lane.ensure_preload(self.team_id, wid)
        base = lane.allocate_block(self.team_id, wid)
        w["lane"] = {"hash": path.name, "path": str(path), "base": base, "preload": str(preload)}
        self.save()
        broker = self.brokers.get(wid)
        prepared = None
        if broker is None or not broker.alive():       # the install comes before the listener check, unhashed: a
            prepared = lane.prepare_broker(self.repo, w["base"], self._worktrees(), verify=False)   # wait retries it
        checked = self.clock()                         # the next 60 s are counted from when the check began
        try:
            ok, problems = lane.listeners_ok()
        except lane.LaneRefused:
            raise
        except Exception as e:
            raise lane.LaneRefused("the listener check failed (%r)" % e)
        if not ok:
            raise lane.LaneWait("; ".join(problems))
        if prepared is not None:
            # The manifest hashes run once the check has passed, just before the broker starts.
            prepared = lane.prepare_broker(self.repo, w["base"], self._worktrees())
            if broker is not None:
                lane.stop_broker(self.brokers.pop(wid))
            node_bin, pw_dir, shell_dir = prepared
            broker = lane.start_broker(path, base, node_bin, pw_dir, shell_dir,
                                       self.dir / "workers" / wid / "broker-stderr.log")
            self.brokers[wid] = broker
            self.lane_secrets.add(broker.secret)
        self.lane_checked[wid] = checked
        return lane.worker_env(path, base, broker.endpoint, preload)

    def _lane_wait(self, wid, prompt, reason):
        """D9: the turn doesn't start; the worker waits and _lane_watch tries again every LANE_RETRY_S. The lead hears
        once per distinct reason, naming each unapproved listener; Slack gets no process names."""
        w = self.state["workers"][wid]
        before = (w.get("lane_wait") or {}).get("reason")
        w["state"] = "waiting"
        w["lane_wait"] = {"prompt": prompt, "reason": reason, "at": self.clock()}
        if reason != before:
            if reason.startswith("one browser lane per machine"):
                preface = "%s waits for its browser lane, which starts by itself once the other lane has ended: %s"
            else:
                preface = ("%s waits for its browser lane, which starts by itself once every listener is in a lane's "
                           "ports or approved (only macOS's own services, in ~/.superyak/team/lane-listeners.json): "
                           "%s")
            self._to_lead("teamd", "LANE WAITING:", preface % (wid, reason))
            self.say(wid, ":hourglass: waiting for the browser lane (the lead has the details).", w["thread_ts"])
        self.save()

    def _lane_refused(self, wid, error):
        w = self.state["workers"][wid]
        w["state"] = "failed"
        w.pop("lane_wait", None)
        if getattr(error, "log", None):              # for Andy (a manifest hash to record), never the lead
            self.log("%s: %s" % (wid, error.log))
        if error.details:
            log = self.dir / "workers" / wid / "lane-diagnostics.log"
            try:
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text(self._scrub("\n".join(error.details)) + "\n")
            except OSError as e:
                self.log("writing %s's lane diagnostics: %r" % (wid, e))
        self._to_lead("teamd", "LANE REFUSED:", "%s: %s" % (wid, error))
        self.say(wid, ":x: browser lane refused (the lead has the details).", w["thread_ts"])
        self._lane_end(wid)
        self.save()

    def _lane_watch(self):
        """Every CHECK_EVERY_S during a browser turn, the listener check and the settings check again: a failure
        stops the turn and the broker (the turn then fails and its lane ends). Waiting workers are tried again every
        LANE_RETRY_S. Nothing here may stop monitor_once: an error is logged, and a check that errs has failed."""
        now = self.clock()
        due = [wid for wid in self.procs if self.state["workers"][wid].get("browser")
               and not self.state["workers"][wid].get("lane_stopped")
               and now - self.lane_checked.get(wid, 0) >= lane.CHECK_EVERY_S]
        if due:
            try:
                ok, problems = lane.listeners_ok()
                widened = lane.settings_widenings()
                what = [name for name, failed in (("listener", not ok), ("settings", widened)) if failed]
            except Exception as e:                       # fails closed: a check that errs has failed
                ok, problems, widened = False, ["the listener or settings check failed (%r)" % e], []
                what = ["listener", "settings"]
            if widened:
                ok, problems = False, problems + ["settings outside the lane now widen its sandbox: "
                                                  + "; ".join(widened)]
            for wid in due:
                self.lane_checked[wid] = now
                if not ok:
                    try:
                        self._lane_stop_turn(wid, problems, what)
                    except Exception as e:
                        self.log("stopping %s's lane turn: %r" % (wid, e))
        for wid, at in list(self.lane_stopped_at.items()):       # a stopped turn that ignored SIGTERM
            proc = self.procs.get(wid)
            if proc is None or proc.poll() is not None:
                self.lane_stopped_at.pop(wid, None)
            elif now - at >= lane.KILL_GRACE_S:
                self.lane_stopped_at.pop(wid, None)
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                    self._lane_env_cleanup(wid)
                    self.log("%s's stopped turn ignored SIGTERM and was killed" % wid)
                except Exception as e:
                    self.log("killing %s's stopped turn: %r" % (wid, e))
        for wid, w in self.state["workers"].items():
            if (w["state"] == "waiting" and now - w["lane_wait"]["at"] >= LANE_RETRY_S
                    and self._running_count() < int(self.cfg["max_workers"])):
                try:
                    self._start_turn(wid, w["lane_wait"]["prompt"])
                except Exception as e:
                    self.log("retrying %s's lane: %r" % (wid, e))

    def _lane_stop_turn(self, wid, problems, what=("listener",)):
        """The turn counts as failed however claude exits, and the lead hears once while it exits. `what` names the
        checks that failed ("listener", "settings"); Slack is told which, never by reading the problems' text."""
        w = self.state["workers"][wid]
        w["lane_stopped"] = True
        self.lane_stopped_at[wid] = self.clock()
        proc = self.procs.get(wid)
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        broker = self.brokers.pop(wid, None)
        if broker is not None:
            lane.stop_broker(broker)
        self._to_lead("teamd", "LANE STOPPED:", "%s's turn and its browser were stopped because the lane's check "
                                               "failed: %s" % (wid, "; ".join(problems)))
        which = ("listener and settings checks" if set(what) >= {"listener", "settings"} else
                 "settings check" if "settings" in what else "listener check")
        self.say(wid, ":no_entry: lane turn stopped: the %s failed (the lead has the details)." % which,
                 w["thread_ts"])
        self.save()

    def _instructions_at_start(self, wid):
        """A browser turn's instruction-bearing files (CLAUDE.md, AGENTS.md, .claude/) as it starts. Never raises: a
        snapshot that fails is told to the lead when the turn ends."""
        w = self.state["workers"][wid]
        try:
            self.turn_instructions[wid] = lane.instruction_snapshot(w["path"])
        except Exception as e:
            self.turn_instructions[wid] = RuntimeError("at the turn's start: %s" % e)

    def _instructions_at_end(self, wid):
        """A turn page content took over can leave instructions for the next turn, which reads them at startup. The
        lead hears which instruction-bearing paths the turn changed, fenced as data and scrubbed; nothing is blocked,
        since a task may edit them on purpose. Never raises."""
        w = self.state["workers"][wid]
        before = self.turn_instructions.pop(wid, None)
        try:
            if before is None:
                raise RuntimeError("no snapshot was taken as the turn started")
            if isinstance(before, Exception):
                raise before
            listed = lane.describe_instruction_changes(before, lane.instruction_snapshot(w["path"]))
        except Exception as e:
            self._to_lead(wid, "INSTRUCTION FILE CHECK FAILED for %s:" % wid,
                          "%s; check CLAUDE.md, AGENTS.md and .claude/ by hand in its worktree before continuing" % e)
            return
        if listed:
            self._to_lead(wid, "INSTRUCTION FILES CHANGED by %s this turn:" % wid,
                          "%s; the next turn reads them at startup — check them before continuing" % ", ".join(listed))

    def _lane_env_cleanup(self, wid):
        """Whatever carries this lane's CLAUDE_CODE_TMPDIR (a turn's setsid leftovers), never ports or files, so never
        the broker. Logged, never raised."""
        try:
            path = lane.lane_path(self.team_id, wid)
            if not lane.cleanup_env(("CLAUDE_CODE_TMPDIR", str(path / "tmp"))):
                self.log("%s's lane processes couldn't be listed" % wid)
        except Exception as e:
            self.log("ending %s's turn leftovers: %r" % (wid, e))

    def _lane_end(self, wid):
        """The lane ends: its broker and every process using it (cleanup_processes), the files teamd keeps are
        scrubbed, the folder goes, and only then its block returns to the pool. Runs from worker_done (once the turn
        has exited), stop_worker, a failed turn, end, and a refused lane; idempotent."""
        w = self.state["workers"][wid]
        w.pop("lane_end", None)
        w.pop("lane_stopped", None)
        self.lane_stopped_at.pop(wid, None)
        broker = self.brokers.pop(wid, None)
        path = lane.lane_path(self.team_id, wid)                    # by exact hash, never a stored path
        # The block comes from the registry, keyed by this lane's hash, never from state.json: after a crash another
        # team may hold that number now. With none, the cleanup matches by folder and environment only.
        base = lane.block_of(self.team_id, wid)
        if broker is None and base is None and not os.path.lexists(path):
            return
        # Also whatever still carries this lane's CLAUDE_CODE_TMPDIR: a turn's setsid child, which neither the
        # worker's group nor the lane's files would find.
        try:
            finished = lane.cleanup_processes(path, base, broker, env=("CLAUDE_CODE_TMPDIR", str(path / "tmp")))
        except OSError as e:
            finished = False
            self.log("cleaning up %s's lane processes: %r" % (wid, e))
        self._scrub_files(wid)
        try:
            lane.remove_lane(path)
        except (lane.LaneRefused, OSError) as e:
            self._to_lead("teamd", "LANE LEFT BEHIND:", "%s: %s" % (wid, e))
        if finished:
            try:
                if lane.release_block(self.team_id, wid):
                    w["lane"] = None
                else:
                    finished = False
            except (lane.LaneRefused, OSError) as e:
                finished = False
                self.log("releasing %s's block: %r" % (wid, e))
        if not finished:
            self._to_lead("teamd", "LANE CLEANUP UNFINISHED:", "%s: lsof or ps couldn't list the lane's processes, "
                                                               "or its block couldn't be released, so its ports stay "
                                                               "held until the next cleanup" % wid)
        self.lane_checked.pop(wid, None)
        self.save()

    def _kill_lost_turn(self, w):
        """A turn the previous teamd started, only if that process is still the claude it launched (lane.lost_turn).
        Returns whether it was stopped."""
        if lane.lost_turn(w.get("pid"), w["path"], w.get("turn_started")):
            try:
                os.killpg(w["pid"], signal.SIGTERM)
                return True
            except OSError:
                pass
        return False

    def sweep_lanes(self):
        """When teamd starts. Lanes of this team's workers that state.json shows as not alive are ended (by exact
        hash). A browser turn the old teamd was running is no longer watched by the 60 s check, so it is stopped and
        fails, and its lane ends too. A live lane keeps its folder and block, but whatever the old teamd left running
        in it (its broker, servers) ends; its next turn starts a new broker."""
        for wid, w in self.state["workers"].items():
            if w.get("browser") and w["state"] == "running":
                stopped = self._kill_lost_turn(w)
                w["state"] = "failed"
                self._to_lead("teamd", "LANE TURN LOST:", "teamd restarted during %s's browser-lane turn; %s, and its "
                              "lane was removed" % (wid, "the turn was stopped" if stopped else
                                                    "its process couldn't be confirmed as that turn, so only what "
                                                    "carries the lane's environment or files was stopped"))
        for wid, _ in lane.leftover_lanes(self.team_id, self.state["workers"], LIVE):
            self._lane_end(wid)
        for wid, w in self.state["workers"].items():
            if w.get("browser") and w["state"] in LIVE and w.get("lane"):
                path = lane.lane_path(self.team_id, wid)
                try:
                    done = lane.cleanup_processes(path, lane.block_of(self.team_id, wid),
                                                  env=("CLAUDE_CODE_TMPDIR", str(path / "tmp")))
                except Exception as e:
                    done = repr(e)
                self.log("%s's live lane cleanup at teamd start: %s" % (wid, done))
        for wid, w in self.state["workers"].items():
            if w.get("browser"):             # a crash mid-turn can leave a dead teamd's secret in what it wrote
                self._scrub_files(wid, shaped=True)
        self.save()

    def deliver(self, wid, text, sender, push=True):
        """Queue a message for a worker. push=True (lead, Kairos) also delivers it into a running
        turn or resumes an idle worker. push=False (another worker) is pull-only: it waits for
        the recipient's team_read and never starts or steers a turn (lateral-injection guard)."""
        with self.lock:
            w = self.state["workers"].get(wid)
            if not w:
                raise teamlib.RejectedMessage("no worker %r" % wid)
            text = self._scrub(text)
            item = {"from": sender, "message": text, "ts": time.time(), "pushed": False,
                    "read": False, "pull_only": not push}
            w["inbox"].append(item)
            teamlib.append_record(self.team_id, {"from": sender, "to": wid, "type": "message",
                                                 "message": text, "pull_only": not push})
            if not push:
                pass
            elif w["state"] == "running" and w["kind"] == "codex" and w["ident"]:
                # `codex queue` only lands at a turn boundary, so a queued message stays unread:
                # team_read returns it now and the next resume repeats it if still unread.
                item["pushed"] = workers.queue_message(w["ident"], teamlib.fence_external(sender, text))
            elif w["state"] == "idle" or (w["state"] == "done" and w.get("mode") == "collab"):
                # a collaborator that already concluded can still be asked to respond
                self._resume_with_inbox(wid)
            self.save()
            return {"worker": wid, "state": w["state"], "pushed": item["pushed"]}

    def _resume_with_inbox(self, wid):
        w = self.state["workers"][wid]
        pending = [m for m in w["inbox"] if not m.get("read") and not m.get("pull_only")]
        if not pending:
            return False
        peer_only = all(m["from"] in self.state["workers"] for m in pending)
        budget = int(self.cfg.get("collab_max_turns", 12))
        if peer_only and w["turns"] >= budget:
            # Teammates can't keep a collaborator talking forever; the lead or Kairos can.
            if not w.get("budget_noted"):
                w["budget_noted"] = True
                self.state["lead_inbox"].append({"from": "teamd", "ts": time.time(), "message":
                    "%s reached its %d-turn budget; %d teammate message(s) are waiting. "
                    "team_message it to continue, or team_done/stop it." % (wid, budget, len(pending))})
                self.say(wid, ":hourglass_flowing_sand: turn budget reached; waiting for the lead.",
                         w["thread_ts"])
            return False
        for m in pending:
            m["pushed"] = m["read"] = True
        body = "\n\n".join(teamlib.fence_external(m["from"], m["message"]) for m in pending)
        peers = sum(1 for m in w["inbox"] if m.get("pull_only") and not m.get("read"))
        hint = (" %d teammate message(s) are waiting: call team_read." % peers) if peers else ""
        self._start_turn(wid, body + "\n\n(Continue your task. Use team_post for progress, "
                                     "team_done when finished.%s)" % hint)
        return True

    def monitor_once(self):
        with self.lock:
            changed = False
            for wid, proc in list(self.procs.items()):
                w = self.state["workers"][wid]
                ident, last = workers.parse_events(self.dir / "workers" / wid, w["kind"])
                if ident and ident != w["ident"]:
                    w["ident"], changed = ident, True
                rc = proc.poll()
                if rc is None:
                    if time.time() - w.get("turn_started", time.time()) > int(self.cfg["worker_timeout_s"]):
                        os.killpg(proc.pid, signal.SIGTERM)
                        self.say(wid, ":hourglass: turn timed out; stopped.", w["thread_ts"])
                    continue
                del self.procs[wid]
                changed = True
                if w.get("browser"):
                    self._lane_env_cleanup(wid)       # before the scrub: the turn's leftovers may still be writing
                    self._scrub_files(wid)
                    self._instructions_at_end(wid)
                last = self._scrub(last)
                if last and last != w["last_message"]:
                    w["last_message"] = last
                    self.say(wid, ":speech_balloon: %s" % last[:1500], w["thread_ts"])
                if w["state"] == "running":
                    stopped = w.pop("lane_stopped", False)   # stopped by the listener check: failed, whatever rc says
                    w["state"] = "idle" if rc == 0 and not stopped else "failed"
                    if w["state"] == "failed":
                        err = (self.dir / "workers" / wid / "stderr.log")
                        tail = err.read_text(errors="replace")[-400:] if err.exists() else ""
                        self.say(wid, ":x: turn exited %s\n```%s```" % (rc, tail), w["thread_ts"])
                        if w.get("browser"):
                            self._lane_end(wid)
                    elif not self._resume_with_inbox(wid):
                        self._to_lead(wid, "turn ended (idle):", last[:300])
                elif w.get("lane_end"):
                    self._lane_end(wid)
            self._lane_watch()
            if changed:
                self._fill_slots()
                self.save()

    def _to_lead(self, sender, label, text):
        """Worker-originated text reaches the lead (also an LLM) only as fenced, quoted data."""
        body = teamlib.fence_external(sender, self._scrub(text), 1500)
        self.state["lead_inbox"].append({"from": sender, "message": "%s %s" % (label, body),
                                         "ts": time.time()})

    PEER_WINDOW = 1800.0

    def _peer_guard(self, sender, to):
        """codex-team-style loop guard for worker<->worker traffic; escalates to the lead.
        Collaborator pairs get a higher limit: conversation is their work."""
        now = time.time()
        both_collab = all(self.state["workers"][x].get("mode") == "collab" for x in (sender, to))
        limit = int(self.cfg.get("peer_limit_collab" if both_collab else "peer_limit_build",
                                 40 if both_collab else 10))
        pair = "|".join(sorted((sender, to)))
        guard = self.state.setdefault("peer_guard", {"pairs": {}, "escalated": []})
        if pair in guard["escalated"]:
            raise teamlib.RejectedMessage("pair %s is escalated; wait for the lead" % pair)
        times = [t for t in guard["pairs"].get(pair, []) if now - t < self.PEER_WINDOW]
        if len(times) >= limit:
            guard["escalated"].append(pair)
            self.state["lead_inbox"].append({"from": "teamd", "ts": now, "message":
                "ESCALATED: %s exchanged %d messages in %d min; peer messages between them are "
                "blocked. Review their threads and team_message them directly." %
                (pair, limit, int(self.PEER_WINDOW // 60))})
            self.save()
            raise teamlib.RejectedMessage("loop guard: pair %s escalated to the lead" % pair)
        times.append(now)
        guard["pairs"][pair] = times

    # ---------- plans and agent-to-agent messages ----------
    def publish_plan(self, who, title, markdown):
        """Publish (or update) who's plan as a Slack canvas in the team channel and link it in
        their thread; always keep a local copy so plans survive without Slack."""
        with self.lock:
            title = self._scrub(teamlib.sanitize(title, 200).strip())
            markdown = self._scrub(markdown)
            plans = self.state.setdefault("plans", {})
            key = "%s:%s" % (who, teamlib.slugify(title, 40))
            local = self.dir / "plans" / (key.replace(":", "-") + ".md")
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text("# %s\n\n%s\n" % (title, markdown))
            entry = plans.get(key, {})
            link, updated = "", bool(entry)
            if self.slack:
                try:
                    if entry.get("canvas_id"):
                        link = self.slack.update_canvas(entry["canvas_id"], markdown)
                    else:
                        cid, link = self.slack.create_canvas(
                            "%s · %s · %s" % (self.team_id, self.display_name(who), title), markdown)
                        entry["canvas_id"] = cid
                except Exception as e:   # SlackError or missing scope: fall back to local copy
                    self.log("canvas publish failed: %s" % e)
            entry.update(title=title, path=str(local), link=link or entry.get("link", ""),
                         updated_at=time.time(), author=who)
            plans[key] = entry
            thread = self.state["kickoff_ts"] if who == "lead" else self.state["workers"][who]["thread_ts"]
            self.say(who, ":memo: *Plan %s:* %s%s" % ("updated" if updated else "published", title,
                                                      "\n%s" % entry["link"] if entry["link"] else ""),
                     thread)
            if who != "lead":
                self._to_lead(who, "PLAN:", "%s %s" % (title, entry["link"] or local))
            self.save()
            return {"title": title, "link": entry["link"], "local_path": str(local), "updated": updated}

    def worker_message(self, sender, to, text):
        """A worker messages the lead or another worker; shown in the recipient's thread."""
        if to == sender:
            raise teamlib.RejectedMessage("cannot message yourself")
        if to == "lead":
            self._to_lead(sender, "MESSAGE:", text)
            self.save()
            ts = self.say(sender, ":speech_balloon: *→ lead:* %s" % text, self.state["kickoff_ts"])
            return {"to": "lead", "ts": ts}
        if to == "all":
            out = {}
            for other, ow in self.state["workers"].items():
                if other != sender and ow["state"] in LIVE:
                    try:
                        out[other] = self.worker_message(sender, other, text)
                    except teamlib.RejectedMessage as e:
                        out[other] = {"refused": str(e)}
            self._to_lead(sender, "TO ALL:", text)
            self.save()
            return {"to": "all", "results": out}
        if to not in self.state["workers"]:
            raise teamlib.RejectedMessage("no teammate %r (use team_status to see the team)" % to)
        self._peer_guard(sender, to)
        self.say(sender, ":speech_balloon: *→ %s:* %s" % (("Mal" if to == "lead" else to.capitalize()), text),
                 self.state["workers"][to]["thread_ts"])
        # Live delivery only to read-only collaborators: a steered collaborator can only say
        # things. Builders (who can write code) keep peer messages pull-only.
        return self.deliver(to, text, sender, push=self.state["workers"][to].get("mode") == "collab")

    # ---------- worker-initiated ----------
    def worker_done(self, wid, summary, tests):
        with self.lock:
            summary, tests = self._scrub(summary), self._scrub(tests)
            w = self.state["workers"][wid]
            if w.get("mode") == "collab":
                sha = None
                w.update(state="done", commit=None, summary=summary, tests=tests)
                msg = ":white_check_mark: *done* — %s%s" % (summary, "\nEvidence: %s" % tests if tests else "")
            else:
                sha = workers.commit_for_worker(w["path"], wid, w["kind"], summary, w["gitdir"])
                w.update(state="done", commit=sha, summary=summary, tests=tests)
                msg = ":white_check_mark: *done* — %s\nCommit: `%s`\nTests: %s" % (
                    summary, (sha or "no changes")[:10], tests or "(not reported)")
            self.say(wid, msg, w["thread_ts"])
            self._to_lead(wid, "DONE:", summary)
            # The advisory set matters only where lanes run: a team without browser_lane runs no advisory git (I2).
            if self.cfg.get("browser_lane") is True and w.get("mode") != "collab" and w.get("base"):
                try:
                    tagged = lane.advisory_added(w["path"], w["base"], w["gitdir"])
                except Exception as e:
                    self._to_lead(wid, "@lane-advisory CHECK FAILED:", "the advisory check failed: %s; review the "
                                  "branch for added @lane-advisory tags by hand before merging" % e)
                else:
                    if tagged:
                        self._to_lead(wid, "@lane-advisory ADDED:", "this branch tags tests as advisory, but lane "
                                      "runs take the advisory set from the base commit; review before merging:\n"
                                      + "\n".join(tagged))
            if w.get("browser"):
                proc = self.procs.get(wid)
                if proc is not None and proc.poll() is None:
                    w["lane_end"] = True      # the worker is still answering this call: end its lane when it exits
                else:
                    self._lane_end(wid)
            self.save()
            return {"commit": sha}

    # ---------- Slack polling ----------
    def poll_slack_once(self):
        if not self.slack:
            return
        allowed = set(self.cfg.get("allowed_user_ids") or [])
        threads = {}
        if self.state["kickoff_ts"]:
            threads[self.state["kickoff_ts"]] = "lead"
        for wid, w in self.state["workers"].items():
            if w.get("thread_ts") and w["state"] in LIVE + ("done",):
                threads[w["thread_ts"]] = wid
        for ts, target in threads.items():
            try:
                msgs = self.slack.replies(ts, self.state["slack_seen"].get(ts, ts))
            except SlackError as e:
                self.log("slack poll failed: %s" % e)
                return
            for m in msgs:
                self.state["slack_seen"][ts] = m["ts"]
                if m.get("bot_id") or m.get("subtype"):
                    continue
                text, user = m.get("text", ""), m.get("user", "?")
                if user not in allowed:
                    self.state["lead_inbox"].append({
                        "from": "slack:%s (UNTRUSTED, not forwarded)" % user,
                        "message": teamlib.fence_external("unknown Slack user %s" % user, text, 500),
                        "ts": time.time()})
                    continue
                if target == "lead":
                    self.state["lead_inbox"].append({"from": "kairos (slack)", "message": text, "ts": time.time()})
                    # Also in the append-only transcript, so a lead can watch it without
                    # consuming the inbox cursor.
                    teamlib.append_record(self.team_id, {"from": "kairos (slack)", "to": "lead",
                                                         "type": "message", "message": text})
                else:
                    self.deliver(target, text, "kairos (slack)")
            self.save()

    # ---------- request dispatch ----------
    def handle(self, req):
        op, caller, a = req.get("op"), req.get("caller", ""), req.get("args") or {}
        is_lead = caller == "lead"
        w = self.state["workers"].get(caller)
        text = None
        if not is_lead and not w:
            raise teamlib.RejectedMessage("unknown caller %r" % caller)
        # Callers prove identity with a per-caller token (Keychain by default; see teamlib);
        # the caller name alone is only a claim.
        expected = teamlib.get_token(self.team_id, caller)
        if not teamlib.tokens_match(req.get("token"), expected):
            raise teamlib.RejectedMessage("authentication failed for caller %r" % caller)
        if op in ("post", "ask_lead", "message", "plan"):
            limit = teamlib.PLAN_MAX_BYTES if op == "plan" else teamlib.MAX_BYTES
            text = teamlib.sanitize(a.get("markdown" if op == "plan" else "text", ""), limit)
            reason = teamlib.check_rate(self.team_id, caller)
            if reason:
                raise teamlib.RejectedMessage(reason)
        if op == "plan":
            return self.publish_plan(caller, a.get("title") or "Plan", text)
        if is_lead:
            if op == "spawn":
                return self.spawn(a.get("task", ""), a.get("kind") or self.cfg.get("default_kind", "codex"),
                                  a.get("context", ""), a.get("mode") or self.cfg.get("default_mode", "build"),
                                  a.get("base") or None, a.get("prepare") or None, a.get("browser", False))
            if op == "message":
                return self.deliver(a["worker"], text, "lead")
            if op == "post":
                return {"ts": self.say("lead", text, self.state["kickoff_ts"])}
            if op == "status":
                return self.status()
            if op == "collect":
                return self.collect(a["worker"])
            if op == "stop":
                return self.stop_worker(a["worker"])
            if op == "end":
                return self.end(a.get("summary", ""), bool(a.get("keep_worktrees")))
        else:
            if op == "post":
                return {"ts": self.say(caller, text, w["thread_ts"])}
            if op == "message":
                return self.worker_message(caller, a.get("to", ""), text)
            if op == "ask_lead":
                self._to_lead(caller, "QUESTION:", text)
                self.save()
                return {"ts": self.say(caller, ":raising_hand: *Question for the lead:* " + text, w["thread_ts"])}
            if op == "read":
                with self.lock:
                    items = [m for m in w["inbox"] if not m.get("read")]
                    for m in items:
                        m["read"] = m["pushed"] = True
                    self.save()
                return {"messages": [{"from": m["from"],
                                      "message": teamlib.fence_external(m["from"], m["message"])}
                                     for m in items]}
            if op == "done":
                return self.worker_done(caller, a.get("summary", ""), a.get("tests", ""))
            if op == "status":
                return {"you": caller, "task": w["task"], "branch": w["branch"], "goal": self.state["goal"],
                        "teammates": {k: {"kind": v["kind"], "state": v["state"], "task": v["task"][:120]}
                                      for k, v in self.state["workers"].items() if k != caller}}
        raise teamlib.RejectedMessage("op %r not allowed for %s" % (op, caller))

    def respond(self, line):
        """One request line in, one JSON answer out (serve's handler). A request that raised is answered with the
        error, scrubbed of a lane's secret like everything else teamd sends."""
        try:
            resp = {"ok": True, "result": self.handle(json.loads(line))}
        except teamlib.RejectedMessage as e:
            resp = {"ok": False, "error": self._scrub(str(e))}
        except Exception as e:  # never kill the daemon on one bad request
            self.log("error: %r\n%s" % (e, traceback.format_exc()))
            resp = {"ok": False, "error": self._scrub("teamd error: %r" % e)}
        return json.dumps(resp) + "\n"

    def status(self):
        with self.lock:
            unread = self.state["lead_inbox"][self.state["lead_cursor"]:]
            self.state["lead_cursor"] = len(self.state["lead_inbox"])
            self.save()
            return {"team": self.team_id, "goal": self.state["goal"], "slack": bool(self.slack),
                    "preset": self.cfg.get("preset", ""),
                    "config": {k: self.cfg.get(k) for k in sorted(teamlib.PRESET_KEYS) if k in self.cfg},
                    "workers": {k: {"kind": v["kind"], "mode": v.get("mode", "build"),
                                    "state": v["state"], "turns": v["turns"],
                                    "branch": v["branch"], "commit": v["commit"],
                                    "last_message": v["last_message"][-300:], "task": v["task"][:160]}
                                for k, v in self.state["workers"].items()},
                    "plans": {k: {"title": v["title"], "link": v["link"], "author": v["author"]}
                              for k, v in self.state.get("plans", {}).items()},
                    "inbox": unread}

    def collect(self, wid):
        w = self.state["workers"][wid]
        return {k: (self._scrub(v) if isinstance(v, str) else v) for k, v in self._collected(wid, w).items()}

    def _collected(self, wid, w):
        return {"worker": wid, "state": w["state"], "branch": w["branch"], "base": w["base"],
                "commit": w["commit"], "summary": w["summary"], "tests": w.get("tests"),
                "mode": w.get("mode", "build"),
                "diff_stat": (workers.diff_stat(w["path"], w["base"], w["gitdir"])
                              if w.get("base") and w.get("gitdir") else None),
                "worktree": w["path"] if w.get("branch") else None,
                "last_message": w["last_message"][-2000:]}

    def stop_worker(self, wid):
        with self.lock:
            prep = self.prepare_procs.pop(wid, None)
            if prep and prep.poll() is None:
                self._kill_group(prep)
            proc = self.procs.pop(wid, None)
            if proc and proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
            w = self.state["workers"][wid]
            if w["state"] in LIVE:
                w["state"] = "stopped"
            if w.get("browser"):
                self._lane_end(wid)
            self.save()
            self._fill_slots()
            return {"worker": wid, "state": w["state"]}

    def end(self, summary, keep_worktrees):
        for wid in list(self.state["workers"]):
            self.stop_worker(wid)
        if not keep_worktrees:
            for w in self.state["workers"].values():
                if w.get("branch") and w["path"] != self.repo:   # collaborators have no worktree
                    workers.remove_worktree(self.repo, w["path"], w["branch"], keep_branch=True)
        rooms = teamlib.rooms_root() / self.team_id
        if rooms.is_dir():
            import shutil
            shutil.rmtree(rooms, ignore_errors=True)
        self.say("lead", ":checkered_flag: *Team ended.* %s" % summary, self.state["kickoff_ts"])
        for caller in ["lead"] + list(self.state["workers"]):
            teamlib.revoke_token(self.team_id, caller)
        self.stopping.set()
        return {"ended": True, "branches_kept": [w["branch"] for w in self.state["workers"].values()
                                                 if w.get("branch")]}


def serve(team):
    sock_path = teamlib.sock_path(team.team_id)
    if sock_path.exists():
        sock_path.unlink()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(team.respond(self.rfile.readline()).encode())

    server = socketserver.ThreadingUnixStreamServer(str(sock_path), Handler)
    os.chmod(sock_path, 0o600)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main(argv=None):
    ap = argparse.ArgumentParser(prog="superyak-team teamd")
    ap.add_argument("--team", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--goal", default="")
    ap.add_argument("--lead-kind", default="claude", choices=["claude", "codex"])
    ap.add_argument("--preset", default="")
    ap.add_argument("--config-json", default="{}")
    args = ap.parse_args(argv)
    state_file = teamlib.team_dir(args.team) / "state.json"
    if state_file.exists() and json.loads(state_file.read_text()).get("config"):
        cfg = json.loads(state_file.read_text())["config"]          # restart keeps the team's config
    else:
        cfg = teamlib.team_config(args.preset or None, json.loads(args.config_json))
    slack = None
    token = teamlib.keychain_secret(cfg["keychain_service"])
    if token and cfg.get("slack_channel") and teamlib.slack_allowed_for_repo(args.repo):
        slack = Slack(token, cfg["slack_channel"])
    if cfg.get("browser_lane") and not lane.python_ok():
        sys.exit("this team has browser lanes, which need Python 3.11.4 or later (tarfile's data filter); this is %s. "
                 "Run team mode from uv's Python: cd team && uv sync --locked --python 3.13" % sys.version.split()[0])
    try:
        lane_lock = lane.hold_team(args.team)          # held for teamd's whole life: its lanes' blocks are live
    except lane.LaneRefused as e:
        sys.exit(str(e))
    team = Team(args.team, args.repo, args.goal, cfg, slack, args.lead_kind)
    team.lane_lock = lane_lock
    (team.dir / "teamd.pid").write_text(str(os.getpid()))
    team.sweep_lanes()
    team.log("teamd up (slack=%s)" % bool(slack))
    team.kickoff()
    server = serve(team)
    last_poll = 0.0
    while not team.stopping.is_set():
        try:
            team.monitor_once()
            if time.time() - last_poll >= int(cfg["poll_interval_s"]):
                last_poll = time.time()
                team.poll_slack_once()
        except Exception as e:
            team.log("loop error: %r\n%s" % (e, traceback.format_exc()))
        team.stopping.wait(2)
    server.shutdown()
    sock = teamlib.sock_path(team.team_id)
    if sock.exists():
        sock.unlink()
    team.log("teamd down")


if __name__ == "__main__":
    main()
