"""Minimal Slack Web API client for team mode (urllib, no SDK).

Only teamd uses this. The bot token is read from the macOS Keychain and never
written to disk or logs. All calls fail soft: Slack being down must never stop
the team, because messages.jsonl is the source of truth.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://slack.com/api/"

AGENT_ICONS = {"lead": ":compass:", "codex": ":robot_face:", "claude": ":large_orange_diamond:"}


class SlackError(RuntimeError):
    pass


class Slack:
    def __init__(self, token, channel, api=API, timeout=15):
        self.token, self.channel, self.api, self.timeout = token, channel, api, timeout

    def _call(self, method, params, http_post=True):
        url = self.api + method
        headers = {"Authorization": "Bearer " + self.token}
        if http_post:
            data = json.dumps(params).encode()
            headers["Content-Type"] = "application/json; charset=utf-8"
            req = urllib.request.Request(url, data=data, headers=headers)
        else:
            req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=headers)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    time.sleep(float(e.headers.get("Retry-After", "2")))
                    continue
                raise SlackError("%s HTTP %s" % (method, e.code))
            except (urllib.error.URLError, OSError) as e:
                raise SlackError("%s unreachable: %s" % (method, e))
            if not body.get("ok"):
                raise SlackError("%s: %s" % (method, body.get("error", "unknown_error")))
            return body
        raise SlackError("%s: rate limited" % method)

    def post(self, text, username, kind="lead", thread_ts=None):
        params = {"channel": self.channel, "text": text, "username": username,
                  "icon_emoji": AGENT_ICONS.get(kind, ":robot_face:"),
                  "unfurl_links": False, "unfurl_media": False}
        if thread_ts:
            params["thread_ts"] = thread_ts
        return self._call("chat.postMessage", params)["ts"]

    def replies(self, thread_ts, oldest):
        """Messages in a thread strictly newer than `oldest` (a ts string)."""
        body = self._call("conversations.replies",
                          {"channel": self.channel, "ts": thread_ts, "oldest": oldest,
                           "inclusive": "false", "limit": 100}, http_post=False)
        return [m for m in body.get("messages", []) if float(m.get("ts", 0)) > float(oldest)]

    def auth_test(self):
        return self._call("auth.test", {})

    def create_canvas(self, title, markdown):
        """Create a canvas shared into the team channel; returns (canvas_id, permalink)."""
        body = self._call("canvases.create", {"title": title, "channel_id": self.channel,
                                              "document_content": {"type": "markdown",
                                                                   "markdown": markdown}})
        cid = body["canvas_id"]
        return cid, self.permalink(cid)

    def update_canvas(self, canvas_id, markdown):
        self._call("canvases.edit", {"canvas_id": canvas_id, "changes": [
            {"operation": "replace", "document_content": {"type": "markdown", "markdown": markdown}}]})
        return self.permalink(canvas_id)

    def permalink(self, file_id):
        try:
            return self._call("files.info", {"file": file_id}, http_post=False)["file"].get("permalink", "")
        except SlackError:
            return ""
