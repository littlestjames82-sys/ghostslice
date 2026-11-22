"""GhostMCP persistent session daemon (0.3.0).

    python -m ghostmcp serve --config <path>

Reads JSON-line requests on stdin, writes one JSON-line
reply per request on stdout, and keeps one handshaken
session per configured server alive across requests -
the per-call CLI verbs spawn a fresh server process for
every list/call; the daemon removes that cost for the
IDE's interactive use.

Request:  {"id": 1, "verb": "tools", "server": "fx"}
          verbs: servers | tools | call | resources |
          resource | prompts | prompt | sessions |
          shutdown
          call takes "tool" + "args" (an object);
          resource takes "uri"; prompt takes "name" +
          "args". Any verb may carry "timeout" (seconds,
          per request).
Reply:    the verb's usual object plus "id", or
          {"id": n, "error": "..."}.

Sessions are dropped and reopened when the config
file's mtime changes, and a request that fails on a
dead session is retried once on a fresh session.
Session deadlines are refreshed per request (the
client's timeout is a whole-session budget by design).
"""
from __future__ import annotations

import json
import os
import sys
import time

from .client import (DEFAULT_TIMEOUT, McpError, _list_all,
                     describe_servers, open_session,
                     summarize_result, TEXT_CAP)


IDLE_LIMIT_S = 1800.0  # Cycle 3 I13: reap idle sessions


class _Daemon:
    def __init__(self, config_path):
        self.config = config_path
        self._mtime = None
        self._sessions = {}   # name -> session (entered)
        self._calls = {}      # name -> requests served
        self._born = {}       # name -> monotonic, created
        self._used = {}       # name -> monotonic, last use

    # -- session management --------------------------------
    def _sync_config(self):
        try:
            m = os.path.getmtime(self.config)
        except OSError:
            m = None
        if m != self._mtime:
            self._drop_all()
            self._mtime = m

    def _reap_idle(self, now):
        # Cycle 3 I13: lazily close sessions idle past
        # the limit whenever the daemon is touched, so a
        # forgotten server cannot hold a process forever.
        for name in list(self._sessions):
            if now - self._used.get(name, now) > IDLE_LIMIT_S:
                self._drop(name)
                self._calls.pop(name, None)

    def _drop_all(self):
        for s in self._sessions.values():
            try:
                s.__exit__()
            except Exception:
                pass
        self._sessions = {}
        self._born = {}
        self._used = {}

    def _drop(self, name):
        s = self._sessions.pop(name, None)
        self._born.pop(name, None)
        self._used.pop(name, None)
        if s is not None:
            try:
                s.__exit__()
            except Exception:
                pass

    def _session(self, name, timeout):
        self._sync_config()
        self._reap_idle(time.monotonic())
        s = self._sessions.get(name)
        if s is None:
            s = open_session(self.config, name, timeout)
            s.__enter__()
            self._sessions[name] = s
            self._calls.setdefault(name, 0)
            self._born[name] = time.monotonic()
        self._used[name] = time.monotonic()
        # the client budget is per-session; refresh it so
        # the timeout applies per request instead
        s.timeout = float(timeout)
        s.deadline = time.monotonic() + float(timeout)
        return s

    # -- verbs (session-level mirrors of client.py) --------
    def _tools(self, s, name):
        tools, cursor = [], None
        while True:
            params = {} if cursor is None else {"cursor": cursor}
            result = s.request("tools/list", params)
            if not isinstance(result, dict):
                raise McpError(
                    f"server '{name}' sent a malformed "
                    "tools/list result")
            for t in result.get("tools") or []:
                if isinstance(t, dict):
                    tools.append({
                        "name": t.get("name"),
                        "description": t.get("description") or "",
                        "inputSchema": t.get("inputSchema") or {},
                        "annotations": t.get("annotations") or {},
                    })
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return {"server": name, "tools": tools}

    def _call(self, s, name, req):
        arguments = req.get("args") or {}
        if not isinstance(arguments, dict):
            raise McpError("args must be a JSON object")
        result = s.request("tools/call", {
            "name": req.get("tool"), "arguments": arguments})
        is_error, text = summarize_result(result)
        return {"server": name, "tool": req.get("tool"),
                "isError": is_error, "text": text}

    def _resources(self, s, name):
        found = _list_all(s, "resources/list", "resources", name)
        return {"server": name, "resources": [{
            "uri": r.get("uri"),
            "name": r.get("name") or "",
            "mimeType": r.get("mimeType") or "",
            "description": r.get("description") or "",
        } for r in found]}

    def _resource(self, s, name, req):
        uri = req.get("uri") or ""
        result = s.request("resources/read", {"uri": uri})
        if not isinstance(result, dict):
            raise McpError(
                f"server '{name}' sent a malformed "
                "resources/read result")
        contents = []
        for c in result.get("contents") or []:
            if not isinstance(c, dict):
                continue
            entry = {"uri": c.get("uri") or uri,
                     "mimeType": c.get("mimeType") or ""}
            if isinstance(c.get("text"), str):
                entry["text"] = c["text"][:TEXT_CAP]
            elif isinstance(c.get("blob"), str):
                entry["blob_base64_chars"] = len(c["blob"])
            else:
                entry["text"] = ""
            contents.append(entry)
        return {"server": name, "uri": uri,
                "contents": contents}

    def _prompts(self, s, name):
        found = _list_all(s, "prompts/list", "prompts", name)
        return {"server": name, "prompts": [{
            "name": p.get("name"),
            "description": p.get("description") or "",
            "arguments": [{
                "name": a.get("name"),
                "required": bool(a.get("required")),
            } for a in p.get("arguments") or []
                if isinstance(a, dict)],
        } for p in found]}

    def _prompt(self, s, name, req):
        arguments = req.get("args") or {}
        if not isinstance(arguments, dict):
            raise McpError("args must be a JSON object")
        result = s.request("prompts/get", {
            "name": req.get("name"), "arguments": arguments})
        if not isinstance(result, dict):
            raise McpError(
                f"server '{name}' sent a malformed "
                "prompts/get result")
        messages = []
        for m in result.get("messages") or []:
            if not isinstance(m, dict):
                continue
            content = m.get("content")
            if isinstance(content, dict):
                _, text = summarize_result(
                    {"content": [content]})
            elif isinstance(content, str):
                text = content
            else:
                text = ""
            messages.append({"role": m.get("role") or "",
                             "text": text})
        return {"server": name, "prompt": req.get("name"),
                "description": result.get("description") or "",
                "messages": messages}

    # -- dispatch ------------------------------------------
    def handle(self, req):
        verb = req.get("verb")
        if verb == "servers":
            return {"config": self.config,
                    "servers": describe_servers(self.config)}
        if verb == "sessions":
            # Cycle 3 I15: age + idle per live session.
            now = time.monotonic()
            self._reap_idle(now)
            return {"sessions": [{
                "server": n,
                "calls": self._calls.get(n, 0),
                "age_s": int(now - self._born.get(n, now)),
                "idle_s": int(now - self._used.get(n, now)),
            } for n in sorted(self._sessions)]}
        if verb == "shutdown":
            self._drop_all()
            return {"ok": True}
        if verb == "drop":
            # Cycle 3 I1: restart ONE server's session;
            # its call count resets with the session.
            name = req.get("server")
            if not name:
                raise McpError("drop needs a server name")
            self._drop(name)
            self._calls.pop(name, None)
            return {"ok": True}
        name = req.get("server")
        if not name:
            raise McpError("request needs a server name")
        timeout = req.get("timeout") or DEFAULT_TIMEOUT
        dispatch = {"tools": self._tools, "call": self._call,
                    "resources": self._resources,
                    "resource": self._resource,
                    "prompts": self._prompts,
                    "prompt": self._prompt}
        fn = dispatch.get(verb)
        if fn is None:
            raise McpError(f"unknown verb: {verb}")
        for attempt in (1, 2):
            s = self._session(name, timeout)
            try:
                out = (fn(s, name) if verb in
                       ("tools", "resources", "prompts")
                       else fn(s, name, req))
                self._calls[name] = self._calls.get(name, 0) + 1
                return out
            except McpError as e:
                # A dead cached session gets one retry on a
                # fresh one; a live server's own protocol
                # error does not (it would fail identically).
                dead = ("closed the connection" in str(e)
                        or "exited before replying" in str(e))
                if dead and attempt == 1:
                    self._drop(name)
                    continue
                raise

    def run(self, instream, outstream):
        for line in instream:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except ValueError:
                req = None
            if not isinstance(req, dict):
                outstream.write(json.dumps(
                    {"id": None,
                     "error": "request is not a JSON object"})
                    + "\n")
                outstream.flush()
                continue
            rid = req.get("id")
            try:
                out = self.handle(req)
                out = dict(out)
                out["id"] = rid
            except McpError as e:
                out = {"id": rid, "error": str(e)}
            except Exception as e:  # never kill the daemon
                out = {"id": rid,
                       "error": f"daemon error: {e}"}
            outstream.write(json.dumps(out) + "\n")
            outstream.flush()
            if req.get("verb") == "shutdown":
                return 0
        self._drop_all()
        return 0


def serve(config_path, instream=None, outstream=None):
    daemon = _Daemon(config_path)
    return daemon.run(instream or sys.stdin,
                      outstream or sys.stdout)
