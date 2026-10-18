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
    parser.add_argument("--grandchild-setsid", action="store_true", help="Start grandchild in a new session (setsid)")
    parser.add_argument("--grandchild", action="store_true", help="Internal flag for grandchild process")

    # 07.4 extensions
    parser.add_argument("--commit", action="store_true", help="Make a git commit in cwd")
    parser.add_argument("--final-report", action="store_true", help="Print a Final Report block")
    parser.add_argument("--verdict", choices=("verified", "bounced"), default=None, help="Verdict in assistant message")
    parser.add_argument("--verdict-finding", action="append", default=None, help="Add finding to verdict (ID:severity:text)")
    parser.add_argument("--earlier-verdict", choices=("verified", "bounced"), default=None, help="Emit verdict in earlier message")
    parser.add_argument("--session-id", type=str, default=None, help="Emit session_id event")
    parser.add_argument("--switch-branch", type=str, default=None, help="Switch git branch in cwd before exiting")
    parser.add_argument("--dirty-tree", action="store_true", help="Create uncommitted dirty file in cwd")

    # 07.10 extensions
    parser.add_argument("--question", action="append", default=None, help="Print a ```ai-orch-question block with JSON in the final message")
    parser.add_argument("--earlier-question", action="append", default=None, help="Print a ```ai-orch-question block with JSON in an earlier message")

    # 07.11 extensions (batch runs: custom commits per microtask)
    parser.add_argument("--commit-msg", action="append", default=None, help="Make git commit(s) with custom message(s)")

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
            start_new_session=bool(args.grandchild_setsid),
        )
        pid_file = pathlib.Path(args.grandchild_pid_file)
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(grandchild_proc.pid), encoding="utf-8")

    # Emit session_id event if requested
    if args.session_id:
        sess_evt = {
            "type": "session",
            "session_id": args.session_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        sys.stdout.write(json.dumps(sess_evt) + "\n")
        sys.stdout.flush()

    # Git operations in cwd if requested
    if args.commit_msg:
        for idx, msg in enumerate(args.commit_msg):
            artifact = pathlib.Path(f"stub_artifact_{idx}.txt")
            artifact.write_text(f"Stub work for {msg} at {time.time()}\n", encoding="utf-8")
            subprocess.run(["git", "add", str(artifact)], check=True)
            subprocess.run(
                ["git", "-c", "user.name=StubAgent", "-c", "user.email=stub@test.com", "commit", "-m", msg],
                check=True,
            )
    elif args.commit:
        artifact = pathlib.Path("stub_artifact.txt")
        artifact.write_text(f"Stub agent work at {time.time()}\n", encoding="utf-8")
        subprocess.run(["git", "add", "stub_artifact.txt"], check=True)
        subprocess.run(
            ["git", "-c", "user.name=StubAgent", "-c", "user.email=stub@test.com", "commit", "-m", "Stub commit from agent"],
            check=True,
        )

    if args.switch_branch:
        subprocess.run(["git", "checkout", "-b", args.switch_branch], check=True)

    if args.dirty_tree:
        dirty_file = pathlib.Path("dirty_file.txt")
        dirty_file.write_text("uncommitted dirty file\n", encoding="utf-8")

    # Emit earlier verdict if requested (to test that earlier verdicts are ignored)
    if args.earlier_verdict:
        earlier_verdict_obj = {
            "verdict": args.earlier_verdict,
            "findings": [{"id": "E1", "severity": "minor", "text": "earlier finding"}],
            "checks": [{"step": "pre-check", "result": "pass", "evidence": "preliminary"}],
        }
        early_content = f"Draft analysis:\n```ai-orch-verdict\n{json.dumps(earlier_verdict_obj, indent=2)}\n```"
        evt_early = {
            "type": "message",
            "index": 0,
            "role": "assistant",
            "content": early_content,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        sys.stdout.write(json.dumps(evt_early) + "\n")
        sys.stdout.flush()

    # Emit earlier question if requested (to test that earlier question blocks are ignored)
    if args.earlier_question:
        for eq_str in args.earlier_question:
            early_q_content = f"Draft question:\n```ai-orch-question\n{eq_str}\n```"
            evt_early_q = {
                "type": "message",
                "index": 0,
                "role": "assistant",
                "content": early_q_content,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            sys.stdout.write(json.dumps(evt_early_q) + "\n")
            sys.stdout.flush()

    # Emit JSON lines
    if args.lines > 0:
        for i in range(args.lines):
            event = {
                "type": "message",
                "index": i + 1,
                "role": "assistant",
                "content": f"stub message {i}",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            sys.stdout.write(json.dumps(event) + "\n")
            sys.stdout.flush()

    # Build final assistant message
    final_parts = []
    if args.final_report:
        final_parts.append("""## Final Report

- **Outcome:** `success`
- **Files changed:**
  - `stub_artifact.txt` — stub changes
- **Verification:**
  - Command: `pytest`
  - Output: `1 passed`
- **Issues:**
  - `None`""")

    if args.verdict:
        findings = []
        if args.verdict_finding:
            for f in args.verdict_finding:
                parts = f.split(":", 2)
                if len(parts) == 3:
                    findings.append({"id": parts[0], "severity": parts[1], "text": parts[2]})
                else:
                    findings.append({"id": "B1", "severity": "major", "text": f})
        elif args.verdict == "bounced":
            findings.append({"id": "B1", "severity": "blocker", "text": "Verification check failed"})

        verdict_obj = {
            "verdict": args.verdict,
            "findings": findings,
            "checks": [
                {
                    "step": "verification-suite",
                    "result": "pass" if args.verdict == "verified" else "fail",
                    "evidence": "executed checks",
                }
            ],
        }
        final_parts.append(f"```ai-orch-verdict\n{json.dumps(verdict_obj, indent=2)}\n```")

    if args.question:
        for q_str in args.question:
            final_parts.append(f"```ai-orch-question\n{q_str}\n```")

    if final_parts:
        evt_final = {
            "type": "message",
            "index": 999,
            "role": "assistant",
            "content": "\n\n".join(final_parts),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        sys.stdout.write(json.dumps(evt_final) + "\n")
        sys.stdout.flush()
    elif args.earlier_verdict or args.earlier_question or args.lines == 0:
        evt_final = {
            "type": "message",
            "index": 999,
            "role": "assistant",
            "content": "Work completed.",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        sys.stdout.write(json.dumps(evt_final) + "\n")
        sys.stdout.flush()

    # Sleep
    if args.sleep > 0:
        time.sleep(args.sleep)

    return args.exit_code


if __name__ == "__main__":
    sys.exit(main())
