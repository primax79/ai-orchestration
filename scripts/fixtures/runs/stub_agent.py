#!/usr/bin/env python3
"""stub_agent.py — Test fixture simulating an agent CLI (Kilo, Claude, Codex).

Supports:
  - Sleeping for N seconds (--sleep)
  - Emitting K JSON lines to stdout (--lines)
  - Spawning a grandchild process that sleeps (--grandchild-pid-file, --grandchild-sleep)
  - Custom exit codes (--exit-code)
  - Accepting arbitrary unknown arguments from adapters
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys
import time


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stub Agent Fixture")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep before exiting")
    parser.add_argument("--lines", type=int, default=0, help="Number of JSON lines to emit")
    parser.add_argument("--exit-code", type=int, default=0, help="Exit code to return")
    parser.add_argument("--grandchild-pid-file", type=str, default=None, help="File to write grandchild PID to")
    parser.add_argument("--grandchild-sleep", type=float, default=60.0, help="Seconds for grandchild to sleep")
    parser.add_argument("--grandchild", action="store_true", help="Internal flag for grandchild process")

    # Consume known args, ignore all other adapter flags (-m, -C, -f, --dir, --output-format, etc.)
    args, unknown = parser.parse_known_args(argv)

    if args.grandchild:
        if args.sleep > 0:
            time.sleep(args.sleep)
        return 0

    # Read stdin if available and not a tty (e.g. prompt passed on stdin)
    try:
        if not sys.stdin.isatty():
            # Read all available stdin (non-blocking if closed, or read to EOF)
            _ = sys.stdin.read()
    except Exception:
        pass

    # Spawn grandchild if requested
    grandchild_proc = None
    if args.grandchild_pid_file:
        grandchild_cmd = [
            sys.executable,
            str(pathlib.Path(__file__).resolve()),
            "--grandchild",
            "--sleep",
            str(args.grandchild_sleep),
        ]
        grandchild_proc = subprocess.Popen(
            grandchild_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Do NOT start new session: grandchild MUST stay in the same process group!
        )
        pid_file = pathlib.Path(args.grandchild_pid_file)
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(grandchild_proc.pid), encoding="utf-8")

    # Emit JSON lines
    if args.lines > 0:
        for i in range(args.lines):
            event = {
                "type": "message",
                "index": i,
                "role": "assistant",
                "content": f"stub message {i}",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            sys.stdout.write(json.dumps(event) + "\n")
            sys.stdout.flush()

    # Sleep
    if args.sleep > 0:
        time.sleep(args.sleep)

    return args.exit_code


if __name__ == "__main__":
    sys.exit(main())
