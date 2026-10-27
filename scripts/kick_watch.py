#!/usr/bin/env python3
"""Wake by kick (prototype): long-poll the station for this ship's unread messages and print one line per kick, so a
Claude Code Monitor wakes a writable session within seconds instead of at its next timed tick.

A kick is a mention of this ship or a reply to one of its posts (Serenity's loop guard): other messages wait for the
tick, and the ship's own posts never wake it. Each line names only the message id, room and sender; the session reads
the text itself with station_read, as quoted data. Messages are never marked read for the session: this script keeps
its own cursor (`<ship>-kick`).

Run it under Claude Code's Monitor tool, re-armed every 30 minutes:
    python3 -u scripts/kick_watch.py
"""
import sys
import time
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(CHECKOUT / 'agent'), str(CHECKOUT / 'team')]
from superyak_agent import station  # noqa: E402

config = station.load_config()
SHIP = config.get('ship') or ''
NAMES = {SHIP, config.get('ship_name') or SHIP}
CURSOR = f'{SHIP}-kick'
client = station.client_for(config, timeout=40)

mine = []  # this ship's recent message ids: seeded from its rooms, then kept as they pass through the stream
try:
    rooms = client.rooms()
    for r in (rooms.get('chats', rooms) if isinstance(rooms, dict) else rooms):
        full = client.room(r['id'])
        me = next((x['id'] for x in full.get('members') or [] if x.get('username') == SHIP), None)
        mine += [x['id'] for x in full.get('messages') or [] if me and x.get('author_id') == me][-200:]
except Exception as e:
    print(f'kick-watch: could not seed own posts ({type(e).__name__}); replies to earlier posts wait for the tick',
          flush=True)

backoff = 5
while True:
    try:
        reply = client.unread(CURSOR, limit=20, wait=25)
        backoff = 5
    except Exception as e:  # station down or restarting: say so, then back off
        print(f'kick-watch: station unreachable ({type(e).__name__}); retrying in {backoff}s', flush=True)
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)
        continue
    messages = (reply.get('messages') or []) if isinstance(reply, dict) else []
    if messages:
        try:
            client.advance(CURSOR, messages[-1]['event_id'])  # the cursor moves only when told (agent/mcp.py)
        except Exception as e:
            print(f'kick-watch: could not advance ({type(e).__name__})', flush=True)
    for m in messages:
        author = m.get('author') or {}
        sender = station.label(author.get('username') or author.get('name') if isinstance(author, dict) else author, 30)
        if sender in NAMES:
            mine.append(m.get('message_id'))
            del mine[:-500]
            continue
        why = f'mentions {SHIP}' if m.get('mentions_me') else (f'replies to {SHIP}' if m.get('reply_to') in mine else None)
        if why:
            print(f"station: kick {station.label(m.get('message_id'), 40)} in {station.label(m.get('room_title'), 40)}"
                  f" from {sender} ({why})", flush=True)
