"""Generic persistent HTTP Agent adapter example.

POST an ``astrbot.agent.invoke.v1`` object to ``/invoke``. This example uses
only the standard library; production Agents should replace ``handle`` with an
Agent-owned server or sidecar while retaining the same boundary.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from command_adapter import handle


class InvokeHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - HTTP handler API spelling
        if self.path != "/invoke":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict):
                raise ValueError("invoke must be a JSON object")
            body = json.dumps(handle(request)).encode()
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error(400, str(exc))
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        """Keep the example protocol-focused."""


def main() -> None:
    ThreadingHTTPServer(("127.0.0.1", 8766), InvokeHandler).serve_forever()


if __name__ == "__main__":
    main()
