#!/usr/bin/env python3
"""test_orchestration_invoke.py — Unit tests for the supervised-invocation primitive (Spec §0c E4, E5)."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import pytest

from orchestration_invoke import (
    get_process_start_time,
    is_process_alive,
    get_process_descendants,
    kill_process_group,
    SupervisedInvocation,
    invoke_supervised,
    InvocationResult,
)


def test_process_lifecycle_helpers():
    pid = os.getpid()
    st = get_process_start_time(pid)
    assert st is not None and len(st) > 0

    assert is_process_alive(pid, st) is True
    assert is_process_alive(pid, "bogus-start-time") is False
    assert is_process_alive(99999999) is False


def test_get_process_descendants_and_kill(tmp_path: pathlib.Path):
    # Spawn a Python script that creates a child process and sleeps
    child_script = (
        "import subprocess, time, sys\n"
        "sub = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "print(sub.pid, flush=True)\n"
        "time.sleep(30)\n"
    )
    script_file = tmp_path / "tree.py"
    script_file.write_text(child_script, encoding="utf-8")

    inv = SupervisedInvocation(
        argv=[sys.executable, str(script_file)],
        cwd=tmp_path,
        log_dir=tmp_path / "logs",
    )
    inv.start()

    # Poll for child to spawn
    assert inv.pid is not None
    descendants: list[int] = []
    deadline = time.time() + 10.0
    while time.time() < deadline:
        descendants = get_process_descendants(inv.pid)
        if descendants:
            break
        time.sleep(0.05)
    assert len(descendants) >= 1
    child_pid = descendants[0]
    assert is_process_alive(child_pid) is True

    # Cancel invocation and verify both leader and descendant are killed
    ok = inv.cancel(timeout=5.0)
    assert ok is True
    assert is_process_alive(inv.pid) is False
    assert is_process_alive(child_pid) is False


def test_supervised_invocation_basic(tmp_path: pathlib.Path):
    script = (
        "import sys\n"
        "print('line 1')\n"
        "print('line 2')\n"
        "sys.stderr.write('err 1\\n')\n"
        "sys.exit(0)\n"
    )
    script_file = tmp_path / "basic.py"
    script_file.write_text(script, encoding="utf-8")

    logs_dir = tmp_path / "logs"
    on_started_called = []

    def on_started(inv: SupervisedInvocation):
        on_started_called.append((inv.pid, inv.pgid))

    res = invoke_supervised(
        argv=[sys.executable, str(script_file)],
        cwd=tmp_path,
        log_dir=logs_dir,
        on_started=on_started,
    )

    assert len(on_started_called) == 1
    assert res.exit_code == 0
    assert res.timed_out is False
    assert res.cancelled is False

    # Check chunks.json
    manifest_file = logs_dir / "chunks.json"
    assert manifest_file.is_file()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert len(manifest) >= 1
    chunk_file = logs_dir / manifest[0]["file"]
    assert "line 1\nline 2\n" in chunk_file.read_text(encoding="utf-8")

    # Check stderr.log
    stderr_file = logs_dir / "stderr.log"
    assert stderr_file.is_file()
    assert "err 1\n" in stderr_file.read_text(encoding="utf-8")


def test_supervised_invocation_stdin_prompt(tmp_path: pathlib.Path):
    script = (
        "import sys\n"
        "data = sys.stdin.read()\n"
        "print(f'ECHO: {data}')\n"
    )
    script_file = tmp_path / "stdin_echo.py"
    script_file.write_text(script, encoding="utf-8")

    logs_dir = tmp_path / "logs"
    res = invoke_supervised(
        argv=[sys.executable, str(script_file)],
        cwd=tmp_path,
        prompt_text="Hello via Stdin!",
        prompt_via="stdin",
        log_dir=logs_dir,
    )

    assert res.exit_code == 0
    chunk_file = logs_dir / "events.000.jsonl"
    assert "ECHO: Hello via Stdin!" in chunk_file.read_text(encoding="utf-8")


def test_supervised_invocation_timeout(tmp_path: pathlib.Path):
    script = (
        "import time\n"
        "time.sleep(30)\n"
    )
    script_file = tmp_path / "sleep.py"
    script_file.write_text(script, encoding="utf-8")

    res = invoke_supervised(
        argv=[sys.executable, str(script_file)],
        cwd=tmp_path,
        log_dir=tmp_path / "logs",
        timeout=0.3,
    )

    assert res.timed_out is True
    assert res.cancelled is True
    assert res.duration_seconds < 3.0


@pytest.mark.parametrize("use_procfs", [True, False])
def test_kill_process_group_unreaped_zombie_leader_procfs_and_ps_fallback(
    monkeypatch: pytest.MonkeyPatch, use_procfs: bool
):
    """T088: kill_process_group and is_process_alive treat unreaped zombie leaders as dead
    on both Linux (/proc/<pid>/stat) and macOS (ps -o stat= / ps -A -o pid= -o pgid= -o stat=).
    """
    import orchestration_invoke as oi
    import subprocess

    monkeypatch.setattr(oi, "_USE_PROCFS", use_procfs)

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    try:
        pgid = os.getpgid(proc.pid)
        st = get_process_start_time(proc.pid)
        assert st is not None
        assert is_process_alive(proc.pid, st) is True

        t0 = time.time()
        # Call kill_process_group WITHOUT reap_fn so proc stays an unreaped zombie of this test process
        ok = kill_process_group(
            pgid=pgid,
            leader_pid=proc.pid,
            expected_leader_start_time=st,
            timeout=2.0,
        )
        elapsed = time.time() - t0
        assert ok is True
        assert elapsed < 1.8
        assert is_process_alive(proc.pid, st) is False
    finally:
        try:
            proc.wait(timeout=1.0)
        except Exception:
            pass

