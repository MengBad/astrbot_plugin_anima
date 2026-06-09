"""Background Task Observatory tests."""

import asyncio
import json
import sys
import types
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANIMA_DIR = ROOT / "anima"
if str(ANIMA_DIR) not in sys.path:
    sys.path.insert(0, str(ANIMA_DIR))


from sylanne_alpha.background_task_observer import build_background_task_observer_snapshot  # noqa: E402
from sylanne_alpha.task_registry import BackgroundTaskSet, ensure_background_tasks  # noqa: E402


class Job:
    def __init__(self, sequence=1, reply_text="secret reply", context_key="secret context"):
        self.sequence = sequence
        self.reply_text = reply_text
        self.context_key = context_key
        self.enqueued_at = 10.0
        self.attempts = 1
        self.next_retry_at = 20.0
        self.last_error_type = "TimeoutError"
        self.last_error_message = "secret error body"
        self.dead_lettered_at = 0.0
        self.lease_until = 0.0


def test_background_task_observer_snapshot_is_redacted():
    secret_reply = "private background reply should not leak"
    secret_context = "private context key should not leak"
    job = Job(reply_text=secret_reply, context_key=secret_context)
    dead = Job(sequence=2, reply_text=secret_reply, context_key=secret_context)
    dead.dead_lettered_at = 30.0
    plugin = types.SimpleNamespace(
        config={
            "background_post_assessment": True,
            "background_post_queue_checkpoint_enabled": True,
            "background_post_diagnostics_warn_lag_count": 1,
        },
        _background_tasks=set(),
        _fragment_timers={},
        _segmented_tasks={},
        _background_post_checkpoint_tasks={},
        _background_post_queues={"session-a": deque([job])},
        _background_post_active={"session-a": {}},
        _background_post_dead_letters={"session-a": deque([dead])},
        _background_post_latest_enqueued={"session-a": 3},
        _background_post_last_committed={"session-a": 1},
        _background_post_worker_state={"session-a": {"current_level": 2, "committed": True}},
        _background_post_recovered_sessions={"session-a"},
    )

    snapshot = build_background_task_observer_snapshot(plugin)
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["schema"] == "anima.background_task_observer.v1"
    assert snapshot["summary"]["background_post_sessions"] == 1
    assert snapshot["summary"]["background_post_queued"] == 1
    assert snapshot["summary"]["background_post_dead_letters"] == 1
    session = snapshot["background_post"]["sessions"][0]
    assert session["warning_level"] == "error"
    assert session["queued_jobs"][0]["last_error_type"] == "TimeoutError"
    assert secret_reply not in encoded
    assert secret_context not in encoded
    assert "secret error body" not in encoded


def test_background_task_observer_records_managed_task_state():
    async def sleeper():
        await asyncio.sleep(0.01)

    async def run():
        task = asyncio.create_task(sleeper(), name="observer-test-task")
        plugin = types.SimpleNamespace(
            config={},
            _background_tasks={task},
            _fragment_timers={},
            _segmented_tasks={},
            _background_post_checkpoint_tasks={},
            _background_post_queues={},
            _background_post_active={},
            _background_post_dead_letters={},
            _background_post_latest_enqueued={},
            _background_post_last_committed={},
            _background_post_worker_state={},
            _background_post_recovered_sessions=set(),
        )
        snapshot = build_background_task_observer_snapshot(plugin)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return snapshot

    snapshot = asyncio.run(run())

    assert snapshot["summary"]["managed_tasks"] == 1
    assert snapshot["managed_tasks"]["tasks"][0]["name"] == "observer-test-task"
    assert snapshot["managed_tasks"]["tasks"][0]["state"] in {"pending", "done", "cancelled"}


def test_background_task_registry_migrates_legacy_list_without_dropping_tasks():
    async def sleeper():
        await asyncio.sleep(0.01)

    async def run():
        first = asyncio.create_task(sleeper(), name="legacy-list-task")
        second = asyncio.create_task(sleeper(), name="append-task")
        third = asyncio.create_task(sleeper(), name="extend-task")
        plugin = types.SimpleNamespace(_background_tasks=[first])

        registry = ensure_background_tasks(plugin)
        registry.append(second)
        registry.extend([third])
        registry.add(first)
        registry.remove(second)
        registry.discard(third)

        for task in (first, second, third):
            task.cancel()
        await asyncio.gather(first, second, third, return_exceptions=True)
        return plugin._background_tasks, first

    registry, first = asyncio.run(run())

    assert isinstance(registry, BackgroundTaskSet)
    assert first in registry
    assert len(registry) == 1


def test_background_task_registry_preserves_existing_compatible_container():
    registry = BackgroundTaskSet()
    plugin = types.SimpleNamespace(_background_tasks=registry)

    assert ensure_background_tasks(plugin) is registry
