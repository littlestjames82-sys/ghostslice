#!/usr/bin/env python3
"""A fake Anthropic-shaped upstream for trying GhostProxy safely.

Binds 127.0.0.1 only, records nothing to disk, and replies with a
small canned Messages-shaped JSON that echoes the model name it
received. Use it to watch the proxy transform a request end to end
without an API key and without spending anything:

    python3 examples/fake_upstream.py 9999
    # then start the proxy with --upstream http://127.0.0.1:9999

Anything you send it is answered locally. It is a demo stand-in,
not a model.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("fake-upstream: %s\n" % (fmt % args))

    def do_GET(self):
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            parsed = json.loads(raw.decode("utf-8"))
            model = parsed.get("model", "unknown")
        except (ValueError, UnicodeDecodeError):
            model = "unparseable-body"
        body = json.dumps({
            "id": "msg_fake_upstream",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [{"type": "text",
                         "text": "Fake upstream reply: your request arrived locally."}],
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"fake upstream listening on http://127.0.0.1:{port} (Ctrl-C to stop)")
    server.serve_forever()
