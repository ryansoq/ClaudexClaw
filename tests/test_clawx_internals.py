"""Tests for ClawX scheduler internals: misfire grace, watchdog, listener, SIGHUP reload.

These exercise the regression-prone code paths that caused the
2026-04-09→10 silent-scheduler incident. We mock the apscheduler
BackgroundScheduler so tests stay fast and don't actually start threads.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import clawx
from clawx import ClawX


@pytest.fixture
def stub_clawx(tmp_path):
    """Build a ClawX instance with config patched in, no real I/O.

    We construct under a patch context, then *replace* self.logger with
    a fresh MagicMock so log assertions work even after the context
    exits. (The original setup_logging may have been called by sibling
    test modules and bound a real FileHandler to the "ClawX" logger;
    patching the function alone isn't enough — the instance attribute
    needs to be a Mock for assert_called to work.)
    """
    cfg = {
        "claude": {
            "command": "echo",
            "project_dir": str(tmp_path),
            "resume_last": False,
        },
        "session": {
            "auto_restart": False,
            "max_restart_attempts": 0,
            "health_check_interval": 1,
        },
        "schedule": {
            "heartbeat": {
                "enabled": True,
                "cron": "*/30 * * * *",
                "prompt": "ping",
            },
            "weekly": {
                "enabled": True,
                "cron": "0 22 * * 0",
                "prompt": "weekly",
            },
            "off": {
                "enabled": False,
                "cron": "0 0 * * *",
                "prompt": "nope",
            },
        },
        "logging": {"dir": str(tmp_path / "logs")},
    }
    with patch.object(clawx, "load_config", return_value=cfg), \
         patch.object(clawx, "setup_logging", return_value=MagicMock()):
        cx = ClawX()
    cx.logger = MagicMock()
    return cx


def test_load_schedule_jobs_uses_generous_misfire_and_coalesce(stub_clawx):
    """Regression: misfire_grace_time MUST be generous and coalesce MUST be on.

    The 2026-04-09 outage was caused by APScheduler's 1-second default
    silently dropping jobs under GIL contention. After Ryan asked us to
    drop the external sentinel and rely on the internal watchdog only,
    we bumped the grace to 1200s (20 minutes) so the in-process recovery
    has plenty of headroom. If anyone reverts these args this test fails.
    """
    stub_clawx.scheduler = MagicMock()
    stub_clawx._load_schedule_jobs()

    # Two enabled jobs, one disabled (skipped).
    assert stub_clawx.scheduler.add_job.call_count == 2
    for call in stub_clawx.scheduler.add_job.call_args_list:
        kwargs = call.kwargs
        assert kwargs["misfire_grace_time"] >= 600, (
            "misfire_grace_time must be >= 600s — see clawx.py comment "
            "for incident history"
        )
        assert kwargs["coalesce"] is True


def test_on_job_event_updates_liveness(stub_clawx):
    stub_clawx.last_job_event_at = None
    fake_event = SimpleNamespace(
        code=clawx.EVENT_JOB_EXECUTED, job_id="heartbeat", exception=None
    )
    stub_clawx._on_job_event(fake_event)
    assert stub_clawx.last_job_event_at is not None
    assert isinstance(stub_clawx.last_job_event_at, datetime)


def test_on_job_event_logs_errors(stub_clawx):
    fake_event = SimpleNamespace(
        code=clawx.EVENT_JOB_ERROR, job_id="heartbeat", exception=RuntimeError("boom")
    )
    stub_clawx._on_job_event(fake_event)
    stub_clawx.logger.error.assert_called_once()
    assert stub_clawx.last_job_event_at is not None


def test_on_job_event_logs_missed(stub_clawx):
    fake_event = SimpleNamespace(
        code=clawx.EVENT_JOB_MISSED, job_id="heartbeat", exception=None
    )
    stub_clawx._on_job_event(fake_event)
    stub_clawx.logger.warning.assert_called_once()


def test_watchdog_noop_when_no_scheduler(stub_clawx):
    stub_clawx.scheduler = None
    stub_clawx.last_job_event_at = datetime.now() - timedelta(hours=10)
    # Should not raise.
    stub_clawx._scheduler_watchdog()


def test_watchdog_noop_when_recent_event(stub_clawx):
    stub_clawx.scheduler = MagicMock()
    stub_clawx.last_job_event_at = datetime.now() - timedelta(minutes=5)
    with patch.object(stub_clawx, "_reload_schedules") as reload_mock:
        stub_clawx._scheduler_watchdog()
    reload_mock.assert_not_called()


def test_watchdog_reloads_when_stale(stub_clawx):
    stub_clawx.scheduler = MagicMock()
    stub_clawx.last_job_event_at = datetime.now() - timedelta(minutes=120)
    with patch.object(stub_clawx, "_reload_schedules") as reload_mock:
        stub_clawx._scheduler_watchdog()
    reload_mock.assert_called_once()


def test_watchdog_idle_threshold_is_generous():
    """Regression: the idle threshold must be ≥ one full heartbeat cycle
    plus the misfire grace, so a single delayed tick never trips a false
    self-heal. We dropped the external sentinel — this is the only line
    of defense, so it has to be conservative.
    """
    assert ClawX.SCHEDULER_WATCHDOG_IDLE_SECONDS >= 60 * 60


def test_watchdog_skips_when_no_frequent_jobs(stub_clawx):
    """Long-gap-only schedules (e.g. weekly) should not trip the watchdog."""
    stub_clawx.config["schedule"] = {
        "weekly": {"enabled": True, "cron": "0 22 * * 0", "prompt": "weekly"}
    }
    stub_clawx.scheduler = MagicMock()
    stub_clawx.last_job_event_at = datetime.now() - timedelta(days=2)
    with patch.object(stub_clawx, "_reload_schedules") as reload_mock:
        stub_clawx._scheduler_watchdog()
    reload_mock.assert_not_called()


def test_watchdog_survives_enabled_job_with_empty_cron(stub_clawx):
    """Regression: an enabled schedule entry with an empty/missing cron must
    not crash the watchdog. `"".split()[0]` raised IndexError, which—running
    unguarded inside _health_loop—killed the whole health thread and silently
    disabled crash recovery + SIGHUP reload for the rest of the session.
    """
    stub_clawx.config["schedule"] = {
        "broken": {"enabled": True, "cron": "", "prompt": "x"},
        "alsobroken": {"enabled": True, "prompt": "y"},  # cron key missing
    }
    stub_clawx.scheduler = MagicMock()
    stub_clawx.last_job_event_at = datetime.now() - timedelta(minutes=5)
    # Must not raise (previously IndexError on "".split()[0]).
    stub_clawx._scheduler_watchdog()


def test_is_alive_true_while_running(stub_clawx):
    """waitpid returning (0, 0) means still running — not cached as exited."""
    stub_clawx.child_pid = 4321
    stub_clawx._child_exited = False
    with patch.object(clawx.os, "waitpid", return_value=(0, 0)):
        assert stub_clawx._is_alive() is True
        assert stub_clawx._is_alive() is True


def test_is_alive_memoizes_exit_single_reaper(stub_clawx):
    """Single-reaper (option-A): once the child is reaped, _is_alive caches the
    exit and never calls waitpid again. This is what stops the three threads
    (main loop / health / scheduler) from double-reaping or waitpid-ing a
    recycled PID.
    """
    stub_clawx.child_pid = 4321
    stub_clawx._child_exited = False
    calls = []

    def fake_waitpid(pid, flags):
        calls.append(pid)
        return (pid, 0)  # reaped — child has exited

    with patch.object(clawx.os, "waitpid", side_effect=fake_waitpid):
        assert stub_clawx._is_alive() is False  # first call reaps
        assert stub_clawx._is_alive() is False  # cached
        assert stub_clawx._is_alive() is False  # cached
    assert len(calls) == 1  # waitpid invoked exactly once


def test_is_alive_memoizes_childprocesserror(stub_clawx):
    """A ChildProcessError (already reaped elsewhere) is cached too, so we
    never waitpid a PID that may have been recycled by the OS."""
    stub_clawx.child_pid = 4321
    stub_clawx._child_exited = False
    calls = []

    def fake_waitpid(pid, flags):
        calls.append(pid)
        raise ChildProcessError()

    with patch.object(clawx.os, "waitpid", side_effect=fake_waitpid):
        assert stub_clawx._is_alive() is False
        assert stub_clawx._is_alive() is False
    assert len(calls) == 1


def test_reload_schedules_clears_then_reloads(stub_clawx):
    stub_clawx.scheduler = MagicMock()
    stub_clawx.scheduler.get_jobs.return_value = ["a", "b"]
    with patch.object(stub_clawx, "_load_schedule_jobs") as load_mock:
        stub_clawx._reload_schedules()
    stub_clawx.scheduler.remove_all_jobs.assert_called_once()
    load_mock.assert_called_once()


def test_reload_schedules_survives_bad_config(stub_clawx):
    """If config.json has invalid JSON the reload must not crash ClawX."""
    stub_clawx.scheduler = MagicMock()
    with patch.object(clawx, "load_config", side_effect=ValueError("bad json")):
        stub_clawx._reload_schedules()  # Must not raise.
    stub_clawx.logger.error.assert_called()


def test_reload_schedules_handles_uninitialized_scheduler(stub_clawx):
    stub_clawx.scheduler = None
    # Should log a warning and return cleanly.
    stub_clawx._reload_schedules()
    stub_clawx.logger.warning.assert_called()


class _FakeOS:
    """Capture os.write calls so we can assert what was sent to the PTY."""
    def __init__(self):
        self.writes = []

    def write(self, fd, data):
        self.writes.append((fd, data))
        return len(data)


def test_maybe_handle_startup_modal_writes_choice(stub_clawx):
    stub_clawx.master_fd = 99
    stub_clawx.started_at = datetime.now()
    stub_clawx._startup_modal_active = True
    stub_clawx._startup_modal_handled = False
    stub_clawx._startup_buffer = bytearray()

    fake_os = _FakeOS()
    chunk = (
        b"Auto-compact prompt:\n"
        b"  1. compact\n"
        b"  2. summarize\n"
        b"  3. skip\n"
    )
    with patch.object(clawx.os, "write", side_effect=fake_os.write):
        stub_clawx._maybe_handle_startup_modal(chunk)

    assert stub_clawx._startup_modal_handled is True
    assert stub_clawx._startup_modal_active is False
    assert fake_os.writes == [(99, b"3\r")]


def test_maybe_handle_startup_modal_inactive_is_noop(stub_clawx):
    stub_clawx.master_fd = 99
    stub_clawx.started_at = datetime.now()
    stub_clawx._startup_modal_active = False
    fake_os = _FakeOS()
    with patch.object(clawx.os, "write", side_effect=fake_os.write):
        stub_clawx._maybe_handle_startup_modal(
            b"compact?\n  1. a\n  2. b\n"
        )
    assert fake_os.writes == []


def test_maybe_handle_startup_modal_window_expires(stub_clawx):
    stub_clawx.master_fd = 99
    stub_clawx.started_at = datetime.now() - timedelta(
        seconds=clawx.STARTUP_MODAL_WINDOW_SECONDS + 5
    )
    stub_clawx._startup_modal_active = True
    stub_clawx._startup_buffer = bytearray()
    fake_os = _FakeOS()
    with patch.object(clawx.os, "write", side_effect=fake_os.write):
        stub_clawx._maybe_handle_startup_modal(
            b"compact?\n  1. a\n  2. b\n"
        )
    assert stub_clawx._startup_modal_active is False
    assert fake_os.writes == []


def test_maybe_handle_startup_modal_caps_buffer(stub_clawx):
    stub_clawx.master_fd = 99
    stub_clawx.started_at = datetime.now()
    stub_clawx._startup_modal_active = True
    stub_clawx._startup_buffer = bytearray()
    fake_os = _FakeOS()
    with patch.object(clawx.os, "write", side_effect=fake_os.write):
        # Feed lots of irrelevant data so the buffer would overflow.
        stub_clawx._maybe_handle_startup_modal(b"x" * (clawx.STARTUP_MODAL_BUFFER_LIMIT + 1024))
    assert len(stub_clawx._startup_buffer) <= clawx.STARTUP_MODAL_BUFFER_LIMIT
    # No false positive.
    assert fake_os.writes == []


def test_inject_debounces_back_to_back_calls(stub_clawx):
    """Regression: at 0 8 sharp on 2026-05-09, three apscheduler jobs
    (ema530-morning-report + heartbeat + nami-lm-loop) fired within
    305ms of each other. Each inject() did Ctrl+U + text + \\r — the
    second prompt arriving 153ms later wiped Claude's input box and
    interrupted the first response. Past-Nami inferred Ryan cancelled
    the morning report from the cascade.

    Fix: inject() must enforce a minimum gap (INJECT_GAP_SECONDS)
    between back-to-back calls. Three rapid injects on a fresh ClawX
    must serialize, with sleep called at least twice, each for at
    least most of INJECT_GAP_SECONDS.
    """
    stub_clawx.master_fd = 99
    stub_clawx._last_inject_ts = 0.0  # force gap on the very first call
    fake_os = _FakeOS()
    sleeps = []

    # Use a controllable clock so we don't depend on wallclock drift.
    fake_now = [1000.0]

    def fake_monotonic():
        return fake_now[0]

    def fake_sleep(seconds):
        sleeps.append(seconds)
        # Advance the fake clock so the next inject sees the gap as already
        # consumed. Without this every inject would queue forever.
        fake_now[0] += seconds

    with patch.object(clawx.os, "write", side_effect=fake_os.write), \
         patch.object(clawx.time, "sleep", side_effect=fake_sleep), \
         patch.object(clawx.time, "monotonic", side_effect=fake_monotonic):
        # Two of the inject's own internal sleeps are ~0.05/0.1s for Ink
        # paste-heuristic, NOT debounce. Filter those out when asserting
        # by checking only sleeps >= 1s.
        stub_clawx.inject("first prompt")
        stub_clawx.inject("second prompt")
        stub_clawx.inject("third prompt")

    # All three writes hit the PTY (3 injects × 3 writes each = 9).
    assert len(fake_os.writes) == 9

    # Filter inject's own paste-heuristic sleeps (sub-second). What remains
    # must be the debounce gaps — at least 2 of them, each >= INJECT_GAP_SECONDS.
    debounce_sleeps = [s for s in sleeps if s >= 1.0]
    assert len(debounce_sleeps) >= 2, (
        f"expected >= 2 debounce sleeps, got {debounce_sleeps} (all sleeps: {sleeps})"
    )
    for s in debounce_sleeps:
        assert s >= clawx.INJECT_GAP_SECONDS - 0.01, (
            f"debounce sleep {s}s shorter than INJECT_GAP_SECONDS={clawx.INJECT_GAP_SECONDS}"
        )


def test_inject_gap_seconds_is_meaningful():
    """The debounce window must be wide enough that Claude has time to
    start processing one prompt before the next lands. 153ms (the actual
    failure case from 2026-05-09) is too short; anything under ~5s leaves
    little margin. Keep at least 10s so a short reply has elbow room.
    """
    assert clawx.INJECT_GAP_SECONDS >= 10


def test_inject_no_debounce_when_idle_long_enough(stub_clawx):
    """If the last inject was already >= INJECT_GAP_SECONDS ago, inject()
    must NOT sleep. Otherwise quiet-cadence schedules (e.g. weekly cron)
    would pay an unnecessary 10s+ stall.
    """
    stub_clawx.master_fd = 99
    fake_os = _FakeOS()
    sleeps = []
    fake_now = [1000.0]

    # Pretend last inject was 1 hour ago.
    stub_clawx._last_inject_ts = fake_now[0] - 3600.0

    def fake_monotonic():
        return fake_now[0]

    with patch.object(clawx.os, "write", side_effect=fake_os.write), \
         patch.object(clawx.time, "sleep", side_effect=lambda s: sleeps.append(s)), \
         patch.object(clawx.time, "monotonic", side_effect=fake_monotonic):
        stub_clawx.inject("solo prompt")

    # Only the inject's own paste-heuristic sleep (sub-second) — no debounce.
    debounce_sleeps = [s for s in sleeps if s >= 1.0]
    assert debounce_sleeps == [], f"unexpected debounce sleeps when idle: {debounce_sleeps}"


# --- HYP #3 busy-marker queue gate (2026-05-22) -----------------------------

def test_busy_marker_tracking_sets_timestamp(stub_clawx):
    """_maybe_track_busy_marker bumps _pty_busy_at when Claude's
    'esc to interrupt' marker appears (even buried in ANSI), and leaves it
    untouched for ordinary output.
    """
    stub_clawx._pty_busy_at = 0.0
    # ANSI-wrapped busy marker — the regex must see it after stripping.
    stub_clawx._maybe_track_busy_marker(b"\x1b[2m\x1b[38;5;244m(esc to interrupt)\x1b[0m")
    assert stub_clawx._pty_busy_at > 0.0

    # Plain output without the marker must NOT bump it.
    stub_clawx._pty_busy_at = 0.0
    stub_clawx._maybe_track_busy_marker(b"some ordinary tool output line\n")
    assert stub_clawx._pty_busy_at == 0.0


def test_queue_gate_defers_during_silent_bash(stub_clawx):
    """The bug this fixes: a quiet long bash produces no PTY output for a
    few seconds, but Claude IS busy (spinner + 'esc to interrupt' animating).
    The busy marker is fresh, so the gate must return None (do not inject)
    even though output has been idle past the short ready-idle window.
    """
    now = 10_000.0
    # No output for 5s (> QUEUE_READY_IDLE_SECONDS) ...
    stub_clawx._pty_last_output_at = now - 5.0
    # ... but busy marker seen 0.5s ago (spinner still animating).
    stub_clawx._pty_busy_at = now - 0.5
    assert stub_clawx._queue_inject_gate(now) is None


def test_queue_gate_ready_after_busy_clears(stub_clawx):
    """Once the busy marker has been gone QUEUE_BUSY_CLEAR_SECONDS and output
    is also quiet QUEUE_READY_IDLE_SECONDS, the 'ready' gate opens.
    """
    now = 10_000.0
    stub_clawx._pty_last_output_at = now - (clawx.QUEUE_READY_IDLE_SECONDS + 1)
    stub_clawx._pty_busy_at = now - (clawx.QUEUE_BUSY_CLEAR_SECONDS + 1)
    assert stub_clawx._queue_inject_gate(now) == "ready"


def test_queue_gate_idle_fallback_when_busy_marker_stuck(stub_clawx):
    """Fallback path: if the busy marker stays fresh (e.g. a hung spinner or
    a UI quirk that keeps redrawing 'esc to interrupt') but there has been NO
    output for the full 60s window, the idle-fallback still releases the
    prompt so the queue can never wedge permanently.
    """
    now = 10_000.0
    # Busy marker seen recently (busy-clear gate NOT satisfied) ...
    stub_clawx._pty_busy_at = now - 1.0
    # ... yet no actual output for > QUEUE_IDLE_SECONDS.
    stub_clawx._pty_last_output_at = now - (clawx.QUEUE_IDLE_SECONDS + 1)
    assert stub_clawx._queue_inject_gate(now) == "idle-fallback"


def test_queue_gate_nothing_when_streaming(stub_clawx):
    """Active streaming: fresh output AND fresh busy marker → no inject."""
    now = 10_000.0
    stub_clawx._pty_busy_at = now - 0.2
    stub_clawx._pty_last_output_at = now - 0.2
    assert stub_clawx._queue_inject_gate(now) is None


# ── 2026-07-04 review fixes: clean-exit, backoff, queue-while-dead, ──
# ── double-start guard, transcript prune                            ──

def test_is_clean_exit_zero_status():
    """waitpid status 0 == WIFEXITED + code 0 → deliberate user quit."""
    assert ClawX._is_clean_exit(0) is True


def test_is_clean_exit_nonzero_and_signal_are_crashes():
    # exit(1) → status 1<<8; SIGKILL → status 9 (signal bits, WIFEXITED False)
    assert ClawX._is_clean_exit(1 << 8) is False
    assert ClawX._is_clean_exit(9) is False


def test_is_clean_exit_unknown_status_is_crash():
    """None (reaped elsewhere, status lost) must default to crash so the
    respawn path stays the fallback."""
    assert ClawX._is_clean_exit(None) is False


def test_is_alive_records_exit_status(stub_clawx):
    """The reaper must capture waitpid's status so run() can distinguish a
    user quit from a crash (2026-07-04: status was discarded, auto-restart
    fought the user's Ctrl+C quits)."""
    stub_clawx.child_pid = 4321
    stub_clawx._child_exited = False
    with patch.object(clawx.os, "waitpid", return_value=(4321, 0)):
        assert stub_clawx._is_alive() is False
    assert stub_clawx._child_exit_status == 0
    assert ClawX._is_clean_exit(stub_clawx._child_exit_status) is True


def test_is_alive_childprocesserror_clears_status(stub_clawx):
    stub_clawx.child_pid = 4321
    stub_clawx._child_exited = False
    stub_clawx._child_exit_status = 0  # stale from a previous child
    with patch.object(clawx.os, "waitpid", side_effect=ChildProcessError()):
        assert stub_clawx._is_alive() is False
    assert stub_clawx._child_exit_status is None


def test_restart_backoff_escalates_and_caps():
    """5s base → 5, 30, 120 (capped): three attempts span ~2.5min instead of
    the 15s that burned all attempts during transient boot failures."""
    assert ClawX._restart_backoff(0, 5) == 5
    assert ClawX._restart_backoff(1, 5) == 30
    assert ClawX._restart_backoff(2, 5) == 120  # 180 capped
    assert ClawX._restart_backoff(5, 5) == 120


def test_run_scheduled_queues_when_child_dead(stub_clawx):
    """Queue mode: a cron firing inside a crash window must be queued for
    post-respawn delivery, not dropped (a dropped 8:20 morning report is
    lost for the whole day)."""
    stub_clawx.child_pid = None  # dead
    with patch.object(clawx, "QUEUE_ENABLED", True):
        stub_clawx._run_scheduled("morning-report", "run it")
    assert len(stub_clawx._inject_queue) == 1
    assert stub_clawx._inject_queue[0][1] == "morning-report"


def test_run_scheduled_direct_mode_still_drops_when_dead(stub_clawx):
    """Legacy non-queue mode keeps the old drop-with-warning behavior."""
    stub_clawx.child_pid = None
    stub_clawx.inject = MagicMock()
    with patch.object(clawx, "QUEUE_ENABLED", False):
        stub_clawx._run_scheduled("hb", "ping")
    stub_clawx.inject.assert_not_called()
    assert len(stub_clawx._inject_queue) == 0


def test_other_clawx_pid_detects_live_instance(tmp_path):
    pid_file = tmp_path / "mono.pid"
    pid_file.write_text("54321")
    proc = tmp_path / "proc" / "54321"
    proc.mkdir(parents=True)
    (proc / "cmdline").write_bytes(b"python3\x00clawx.py\x00")
    assert clawx._other_clawx_pid(pid_file, tmp_path / "proc") == 54321


def test_other_clawx_pid_ignores_stale_and_foreign(tmp_path):
    pid_file = tmp_path / "mono.pid"
    proc_root = tmp_path / "proc"
    # No pid file at all
    assert clawx._other_clawx_pid(pid_file, proc_root) is None
    # Dead PID (no /proc entry)
    pid_file.write_text("54321")
    assert clawx._other_clawx_pid(pid_file, proc_root) is None
    # PID recycled by an unrelated process
    proc = proc_root / "54321"
    proc.mkdir(parents=True)
    (proc / "cmdline").write_bytes(b"nginx\x00-g\x00daemon off;\x00")
    assert clawx._other_clawx_pid(pid_file, proc_root) is None
    # Garbage pid file
    pid_file.write_text("not-a-pid")
    assert clawx._other_clawx_pid(pid_file, proc_root) is None


def test_other_clawx_pid_ignores_own_pid(tmp_path):
    """The SIGUSR1 re-exec path re-runs main() under the SAME pid — the
    guard must not lock ClawX out of its own restart."""
    import os as real_os
    pid_file = tmp_path / "mono.pid"
    pid_file.write_text(str(real_os.getpid()))
    assert clawx._other_clawx_pid(pid_file, "/proc") is None


def test_prune_old_transcripts(stub_clawx, tmp_path, monkeypatch):
    import os as real_os
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(clawx, "LOG_DIR", log_dir)
    old = log_dir / "transcript-20260101-000000.log"
    new = log_dir / "transcript-20260704-120000.log"
    other = log_dir / "clawx-20260101.log"  # rotated separately — untouched
    for f in (old, new, other):
        f.write_text("x")
    stale = clawx.time.time() - 30 * 86400
    real_os.utime(old, (stale, stale))
    real_os.utime(other, (stale, stale))
    stub_clawx.config["logging"] = {"transcript_keep_days": 14}
    stub_clawx._prune_old_transcripts()
    assert not old.exists()          # stale transcript pruned
    assert new.exists()              # fresh transcript kept
    assert other.exists()            # non-transcript logs never touched


def test_prune_disabled_with_zero_keep_days(stub_clawx, tmp_path, monkeypatch):
    import os as real_os
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(clawx, "LOG_DIR", log_dir)
    old = log_dir / "transcript-20250101-000000.log"
    old.write_text("x")
    stale = clawx.time.time() - 365 * 86400
    real_os.utime(old, (stale, stale))
    stub_clawx.config["logging"] = {"transcript_keep_days": 0}
    stub_clawx._prune_old_transcripts()
    assert old.exists()


# ── 2026-07-05: busy-marker UI-change fix + jsonl turn gate ──
# (queued prompts were interrupting in-flight turns: the v2.1.x status
#  line renders with cursor moves, not spaces — "esctointerrupt" after
#  ANSI strip — so the spaced regex never matched all session.)

def test_busy_marker_matches_new_cursor_move_rendering(stub_clawx):
    """v2.1.x: words separated by cursor-forward ANSI, not spaces."""
    stub_clawx._pty_busy_at = 0.0
    chunk = b"(shift+tab \x1b[1mto\x1b[0m cycle) \xc2\xb7 esc\x1b[1Cto\x1b[1Cinterrupt \xc2\xb7 \xe2\x86\x90 for agents"
    stub_clawx._maybe_track_busy_marker(chunk)
    assert stub_clawx._pty_busy_at > 0.0


def test_busy_marker_still_matches_old_spaced_rendering(stub_clawx):
    stub_clawx._pty_busy_at = 0.0
    stub_clawx._maybe_track_busy_marker(b"spinner... esc to interrupt)")
    assert stub_clawx._pty_busy_at > 0.0


def test_busy_marker_survives_chunk_split(stub_clawx):
    """The marker arriving across two 4096-byte PTY reads must still match
    (rolling buffer)."""
    stub_clawx._pty_busy_at = 0.0
    stub_clawx._maybe_track_busy_marker(b"... esc to inter")
    assert stub_clawx._pty_busy_at == 0.0  # incomplete: no match yet
    stub_clawx._maybe_track_busy_marker(b"rupt \xc2\xb7 more ui")
    assert stub_clawx._pty_busy_at > 0.0


def test_busy_marker_buffer_cleared_after_match(stub_clawx):
    """One old marker must not keep re-matching forever and pin us busy."""
    stub_clawx._maybe_track_busy_marker(b"esc to interrupt")
    stub_clawx._pty_busy_at = 0.0
    stub_clawx._maybe_track_busy_marker(b"plain output, no marker")
    assert stub_clawx._pty_busy_at == 0.0


def _write_jsonl(tmp_path, entries):
    import json as _json
    p = tmp_path / "session.jsonl"
    p.write_text("\n".join(_json.dumps(e) for e in entries))
    return p


def test_turn_complete_true_on_final_assistant_text(stub_clawx, tmp_path):
    p = _write_jsonl(tmp_path, [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
        {"type": "queue-operation"},   # meta rows after the turn are skipped
        {"type": "last-prompt"},
    ])
    assert stub_clawx._jsonl_turn_complete(p) is True


def test_turn_complete_false_on_pending_tool_use(stub_clawx, tmp_path):
    """The silent-bash case: assistant issued a tool_use, result not back."""
    p = _write_jsonl(tmp_path, [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1"}]}},
    ])
    assert stub_clawx._jsonl_turn_complete(p) is False


def test_turn_complete_false_on_user_entry(stub_clawx, tmp_path):
    """Fresh user message / tool_result → Claude is (about to be) responding."""
    p = _write_jsonl(tmp_path, [
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}]}},
    ])
    assert stub_clawx._jsonl_turn_complete(p) is False
    p2 = _write_jsonl(tmp_path, [
        {"type": "user", "message": {"content": "hello"}},
    ])
    assert stub_clawx._jsonl_turn_complete(p2) is False


def test_turn_complete_none_on_garbage_or_missing(stub_clawx, tmp_path):
    p = tmp_path / "session.jsonl"
    p.write_text("not json\nalso not json")
    assert stub_clawx._jsonl_turn_complete(p) is None
    assert stub_clawx._jsonl_turn_complete(tmp_path / "nope.jsonl") is None


def test_gate_blocked_by_turn_in_flight_despite_idle(stub_clawx):
    """THE fix: hours of PTY silence must not open the gate while the jsonl
    says a turn is in flight."""
    now = 10_000.0
    stub_clawx._pty_busy_at = now - 50_000
    stub_clawx._pty_last_output_at = now - 50_000
    assert stub_clawx._queue_inject_gate(now, turn_complete=False) is None


def test_gate_open_when_turn_complete_and_idle(stub_clawx):
    now = 10_000.0
    stub_clawx._pty_busy_at = now - 100
    stub_clawx._pty_last_output_at = now - 100
    assert stub_clawx._queue_inject_gate(now, turn_complete=True) == "ready"


def test_gate_unknown_turn_state_keeps_legacy_behavior(stub_clawx):
    now = 10_000.0
    stub_clawx._pty_busy_at = now - 100
    stub_clawx._pty_last_output_at = now - 100
    assert stub_clawx._queue_inject_gate(now, turn_complete=None) == "ready"


def test_find_active_session_jsonl_prefers_project_dir(tmp_path, monkeypatch):
    """A fresher session in ANOTHER project (the user's own terminal) must
    not shadow ClawX's session when a project dir is preferred."""
    import os as real_os, time as real_time
    proj_root = tmp_path / ".claude" / "projects"
    ours = proj_root / "-home-ymchang-clawd"
    theirs = proj_root / "-home-ymchang-other"
    ours.mkdir(parents=True); theirs.mkdir(parents=True)
    mine = ours / "aaa.jsonl"; other = theirs / "bbb.jsonl"
    mine.write_text("{}"); other.write_text("{}")
    old = real_time.time() - 3600
    real_os.utime(mine, (old, old))  # ours is OLDER
    monkeypatch.setattr(clawx.Path, "home", classmethod(lambda cls: tmp_path))
    got = clawx._find_active_session_jsonl(prefer_project_dir="/home/ymchang/clawd")
    assert got == mine
    # without preference, the global most-recent wins
    assert clawx._find_active_session_jsonl() == other
