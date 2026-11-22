"""GhostMCP client engine: config loading plus the stdio and
HTTP transports for one MCP session.

A session is one ``initialize`` handshake
(``notifications/initialized`` right behind it) followed by the
caller's requests. Sessions are opened per CLI invocation and
always closed: a stdio child is terminated even on error or
timeout, and an HTTP session id lives only for the invocation.

Security rules held here: config env values are passed to stdio
children but never returned or printed anywhere (only env names
leave this module), and tool arguments are passed to the server
and never logged.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "ghostmcp", "version": __version__}
TEXT_CAP = 60000
DEFAULT_TIMEOUT = 30.0


class McpError(Exception):
    """A plain, user-facing failure; the CLI prints it as
    ``{"error": ...}`` and exits 2."""


# ----------------------------------------------------------------
# Config

def load_config(config_path):
    """Return the ``mcpServers`` mapping from a config file."""
    path = Path(config_path)
    if not path.is_file():
        raise McpError(f"config file not found: {config_path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise McpError(f"config file is unreadable: {e.strerror or e}")
    try:
        data = json.loads(raw)
    except ValueError:
        raise McpError(f"config file is not valid JSON: {config_path}")
    if not isinstance(data, dict) or \
            not isinstance(data.get("mcpServers"), dict):
        raise McpError('config has no "mcpServers" object')
    return data["mcpServers"]


def _entry_parts(name, entry):
    """(transport, target, env_names, header_names) for one
    server entry.

    Env and header values are deliberately never part of
    the result - only their names leave this module.
    """
    if not isinstance(entry, dict):
        raise McpError(f"server '{name}' is not a config object")
    env = entry.get("env") or {}
    if not isinstance(env, dict):
        raise McpError(f"server '{name}' has a non-object env")
    env_names = sorted(str(k) for k in env)
    headers = entry.get("headers") or {}
    if not isinstance(headers, dict):
        raise McpError(f"server '{name}' has a non-object headers")
    header_names = sorted(str(k) for k in headers)
    url = entry.get("url")
    if url:
        return "http", str(url), env_names, header_names
    command = entry.get("command")
    if command:
        args = entry.get("args") or []
        if not isinstance(args, list):
            raise McpError(f"server '{name}' has a non-list args")
        target = " ".join([str(command)] + [str(a) for a in args])
        return "stdio", target, env_names, header_names
    raise McpError(
        f"server '{name}' has neither a command (stdio) nor a "
        "url (http)")


def describe_servers(config_path):
    """The ``servers`` verb: list entries without connecting."""
    servers = load_config(config_path)
    out = []
    for name in sorted(servers):
        transport, target, env_names, header_names = \
            _entry_parts(name, servers[name])
        out.append({"name": name, "transport": transport,
                    "target": target, "env_names": env_names,
                    "header_names": header_names})
    return out


def _get_entry(servers, name):
    if name not in servers:
        known = ", ".join(sorted(servers)) or "(none)"
        raise McpError(
            f"no server named '{name}' in the config "
            f"(servers: {known})")
    return servers[name]


# ----------------------------------------------------------------
# Sessions

class _Session:
    """Shared handshake + request plumbing over a transport."""

    def __init__(self, name, timeout):
        self.name = name
        self.timeout = float(timeout)
        self.deadline = time.monotonic() + self.timeout
        self._next_id = 0

    def _remaining(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise McpError(
                f"timed out after {self.timeout:g} seconds "
                f"waiting for server '{self.name}'")
        return left

    def _result_of(self, msg):
        if not isinstance(msg, dict):
            raise McpError(
                f"server '{self.name}' sent a non-object reply")
        err = msg.get("error")
        if err:
            if isinstance(err, dict):
                raise McpError(
                    f"server '{self.name}' returned error "
                    f"{err.get('code')}: {err.get('message')}")
            raise McpError(f"server '{self.name}' returned an error")
        return msg.get("result")

    def handshake(self):
        self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": dict(CLIENT_INFO),
        })
        self.notify("notifications/initialized", {})

    def request(self, method, params):
        raise NotImplementedError

    def notify(self, method, params):
        raise NotImplementedError

    def close(self):
        pass


class StdioSession(_Session):
    """One MCP server as a child process, newline-delimited
    JSON-RPC over its stdin/stdout."""

    def __enter__(self):
        entry = self._entry
        command = str(entry["command"])
        args = [str(a) for a in (entry.get("args") or [])]
        env = dict(os.environ)
        for k, v in (entry.get("env") or {}).items():
            env[str(k)] = str(v)
        try:
            self.proc = subprocess.Popen(
                [command] + args, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env)
        except OSError as e:
            raise McpError(
                f"could not start server '{self.name}' "
                f"({command}): {e.strerror or e}")
        self._lines = queue.Queue()
        threading.Thread(target=self._pump_stdout,
                         daemon=True).start()
        # stderr is drained and discarded so a chatty server
        # cannot fill the pipe and deadlock; its content is
        # never surfaced (it could contain env values).
        threading.Thread(target=self._pump_discard,
                         args=(self.proc.stderr,), daemon=True).start()
        try:
            self.handshake()
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __init__(self, name, entry, timeout):
        super().__init__(name, timeout)
        self._entry = entry
        self.proc = None

    def _pump_stdout(self):
        try:
            for line in self.proc.stdout:
                self._lines.put(line)
        except Exception:
            pass
        self._lines.put(None)  # EOF sentinel

    @staticmethod
    def _pump_discard(stream):
        try:
            for _ in stream:
                pass
        except Exception:
            pass

    def _send(self, payload):
        try:
            self.proc.stdin.write(
                (json.dumps(payload) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise McpError(
                f"server '{self.name}' closed the connection")

    def request(self, method, params):
        self._next_id += 1
        rid = self._next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                    "params": params})
        while True:
            try:
                line = self._lines.get(timeout=self._remaining())
            except queue.Empty:
                raise McpError(
                    f"timed out after {self.timeout:g} seconds "
                    f"waiting for server '{self.name}'")
            if line is None:
                raise McpError(
                    f"server '{self.name}' exited before replying "
                    f"(exit code {self.proc.poll()})")
            try:
                msg = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue  # not JSON-RPC; ignore the noise line
            if not isinstance(msg, dict):
                continue
            if msg.get("id") == rid and \
                    ("result" in msg or "error" in msg):
                return self._result_of(msg)
            if "method" in msg and "id" in msg:
                self._answer_server_request(msg)
            # anything else is a notification; ignore it

    def _answer_server_request(self, msg):
        if msg.get("method") == "ping":
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
        else:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {
                "code": -32601,
                "message": "ghostmcp 0.1.0 does not handle "
                           "server-initiated requests"}}
        try:
            self._send(reply)
        except McpError:
            pass

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method,
                    "params": params})

    def close(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass


class HttpSession(_Session):
    """Streamable-HTTP-style POSTs of JSON-RPC to one url."""

    def __init__(self, name, entry, timeout):
        super().__init__(name, timeout)
        self.url = str(entry["url"])
        # Static per-server headers from the config (the
        # usual case is an Authorization bearer token). The
        # values ride every request and are never returned
        # or printed anywhere, like env values.
        raw_headers = entry.get("headers") or {}
        if not isinstance(raw_headers, dict):
            raise McpError(
                f"server '{name}' has a non-object headers")
        self.headers = {str(k): str(v)
                        for k, v in raw_headers.items()}
        self.session_id = None

    def __enter__(self):
        try:
            self.handshake()
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def _post(self, payload, expect_reply):
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        headers.update(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=body, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(
                req, timeout=self._remaining())
        except urllib.error.HTTPError as e:
            raise McpError(
                f"server '{self.name}' answered HTTP {e.code}")
        except (urllib.error.URLError, TimeoutError,
                OSError) as e:
            if time.monotonic() >= self.deadline:
                raise McpError(
                    f"timed out after {self.timeout:g} seconds "
                    f"waiting for server '{self.name}'")
            reason = getattr(e, "reason", e)
            raise McpError(
                f"could not reach server '{self.name}': {reason}")
        with resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session_id = sid
            raw = resp.read()
            ctype = resp.headers.get("Content-Type") or ""
        if not expect_reply:
            return None
        return self._parse_body(raw, ctype, payload.get("id"))

    def _parse_body(self, raw, ctype, rid):
        text = raw.decode("utf-8", "replace").strip()
        if not text:
            raise McpError(
                f"server '{self.name}' sent an empty reply")
        if "text/event-stream" in ctype:
            messages = []
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    try:
                        messages.append(json.loads(line[5:]))
                    except ValueError:
                        continue
            for msg in messages:
                if isinstance(msg, dict) and \
                        msg.get("id") == rid:
                    return msg
            for msg in messages:
                if isinstance(msg, dict) and \
                        ("result" in msg or "error" in msg):
                    return msg
            raise McpError(
                f"server '{self.name}' sent an event stream "
                "with no reply in it")
        try:
            return json.loads(text)
        except ValueError:
            raise McpError(
                f"server '{self.name}' sent a reply that is "
                "not JSON")

    def request(self, method, params):
        self._next_id += 1
        rid = self._next_id
        msg = self._post({"jsonrpc": "2.0", "id": rid,
                          "method": method, "params": params},
                         expect_reply=True)
        return self._result_of(msg)

    def notify(self, method, params):
        self._post({"jsonrpc": "2.0", "method": method,
                    "params": params}, expect_reply=False)


def open_session(config_path, server_name, timeout):
    """A context manager yielding a handshaken session."""
    servers = load_config(config_path)
    entry = _get_entry(servers, server_name)
    transport, _, _, _ = _entry_parts(server_name, entry)
    if transport == "http":
        return HttpSession(server_name, entry, timeout)
    return StdioSession(server_name, entry, timeout)


# ----------------------------------------------------------------
# Verbs that need a session

def list_tools(config_path, server_name, timeout=DEFAULT_TIMEOUT):
    with open_session(config_path, server_name, timeout) as s:
        tools, cursor = [], None
        while True:
            params = {} if cursor is None else {"cursor": cursor}
            result = s.request("tools/list", params)
            if not isinstance(result, dict):
                raise McpError(
                    f"server '{server_name}' sent a malformed "
                    "tools/list result")
            for t in result.get("tools") or []:
                if not isinstance(t, dict):
                    continue
                tools.append({
                    "name": t.get("name"),
                    "description": t.get("description") or "",
                    "inputSchema": t.get("inputSchema") or {},
                    "annotations": t.get("annotations") or {},
                })
            cursor = result.get("nextCursor")
            if not cursor:
                break
    return {"server": server_name, "tools": tools}


def summarize_result(result):
    """(isError, text) for a tools/call result: text blocks
    joined with newlines, other blocks as ``[type: ...]``."""
    if not isinstance(result, dict):
        result = {}
    parts = []
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif isinstance(block, dict):
            parts.append(f"[type: {block.get('type', 'unknown')}]")
        else:
            parts.append("[type: unknown]")
    text = "\n".join(parts)
    if len(text) > TEXT_CAP:
        text = text[:TEXT_CAP]
    return bool(result.get("isError")), text


def _list_all(session, method, key, server_name):
    """One paged list call, following nextCursor."""
    items, cursor = [], None
    while True:
        params = {} if cursor is None else {"cursor": cursor}
        result = session.request(method, params)
        if not isinstance(result, dict):
            raise McpError(
                f"server '{server_name}' sent a malformed "
                f"{method} result")
        for it in result.get(key) or []:
            if isinstance(it, dict):
                items.append(it)
        cursor = result.get("nextCursor")
        if not cursor:
            break
    return items


def list_resources(config_path, server_name,
                   timeout=DEFAULT_TIMEOUT):
    with open_session(config_path, server_name, timeout) as s:
        found = _list_all(s, "resources/list", "resources",
                          server_name)
    return {"server": server_name, "resources": [{
        "uri": r.get("uri"),
        "name": r.get("name") or "",
        "mimeType": r.get("mimeType") or "",
        "description": r.get("description") or "",
    } for r in found]}


def read_resource(config_path, server_name, uri,
                  timeout=DEFAULT_TIMEOUT):
    """One resource's contents. Text comes back capped;
    binary (blob) contents are reported by size only -
    their bytes are never dumped into the output."""
    with open_session(config_path, server_name, timeout) as s:
        result = s.request("resources/read", {"uri": uri})
    if not isinstance(result, dict):
        raise McpError(
            f"server '{server_name}' sent a malformed "
            "resources/read result")
    contents = []
    for c in result.get("contents") or []:
        if not isinstance(c, dict):
            continue
        entry = {"uri": c.get("uri") or uri,
                 "mimeType": c.get("mimeType") or ""}
        if isinstance(c.get("text"), str):
            text = c["text"]
            if len(text) > TEXT_CAP:
                text = text[:TEXT_CAP]
            entry["text"] = text
        elif isinstance(c.get("blob"), str):
            entry["blob_base64_chars"] = len(c["blob"])
        else:
            entry["text"] = ""
        contents.append(entry)
    return {"server": server_name, "uri": uri,
            "contents": contents}


def list_prompts(config_path, server_name,
                 timeout=DEFAULT_TIMEOUT):
    with open_session(config_path, server_name, timeout) as s:
        found = _list_all(s, "prompts/list", "prompts",
                          server_name)
    return {"server": server_name, "prompts": [{
        "name": p.get("name"),
        "description": p.get("description") or "",
        "arguments": [{
            "name": a.get("name"),
            "required": bool(a.get("required")),
        } for a in p.get("arguments") or []
            if isinstance(a, dict)],
    } for p in found]}


def get_prompt(config_path, server_name, prompt_name, args_json,
               timeout=DEFAULT_TIMEOUT):
    try:
        arguments = json.loads(args_json)
    except ValueError:
        raise McpError("--args is not valid JSON")
    if not isinstance(arguments, dict):
        raise McpError("--args must be a JSON object")
    with open_session(config_path, server_name, timeout) as s:
        result = s.request("prompts/get", {
            "name": prompt_name, "arguments": arguments})
    if not isinstance(result, dict):
        raise McpError(
            f"server '{server_name}' sent a malformed "
            "prompts/get result")
    messages = []
    for m in result.get("messages") or []:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, dict):
            _, text = summarize_result({"content": [content]})
        elif isinstance(content, str):
            text = content
        else:
            text = ""
        messages.append({"role": m.get("role") or "",
                         "text": text})
    return {"server": server_name, "prompt": prompt_name,
            "description": result.get("description") or "",
            "messages": messages}


def call_tool(config_path, server_name, tool_name, args_json,
              timeout=DEFAULT_TIMEOUT):
    try:
        arguments = json.loads(args_json)
    except ValueError:
        raise McpError("--args is not valid JSON")
    if not isinstance(arguments, dict):
        raise McpError("--args must be a JSON object")
    with open_session(config_path, server_name, timeout) as s:
        result = s.request("tools/call", {
            "name": tool_name, "arguments": arguments})
    is_error, text = summarize_result(result)
    return {"server": server_name, "tool": tool_name,
            "isError": is_error, "text": text}


__all__ = ["McpError", "load_config", "describe_servers",
           "list_tools", "call_tool", "summarize_result",
           "list_resources", "read_resource", "list_prompts",
           "get_prompt",
           "open_session", "PROTOCOL_VERSION", "CLIENT_INFO",
           "DEFAULT_TIMEOUT", "TEXT_CAP"]
