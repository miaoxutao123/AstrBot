#!/usr/bin/env python3
"""Reference wrapper: replace the TODO with your own Agent Harness invocation."""

import json
import sys

invoke = json.load(sys.stdin)
assert invoke["schema"] == "astrbot.agent.invoke.v1"
# TODO: call your Harness with invoke["input"]["text"] and preserve session state.
json.dump({"schema": "astrbot.agent.result.v1", "session": {"external_session_id": invoke["session"].get("external_session_id") or "example-session"}, "reply": {"text": f"echo: {invoke['input']['text']}"}}, sys.stdout)
