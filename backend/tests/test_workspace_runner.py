from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.repositories.worker_queue import ReadyWorkspaceJob
from app.workers import workspace_runner as runner


class FakeStop:
    def __init__(self, clock, cycles=1):
        self.clock = clock
        self.cycles = cycles
        self.stopped = False
        self.waits = []

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        self.waits.append(seconds)
        self.clock.now += seconds
        if len(self.waits) >= self.cycles:
            self.stopped = True
        return self.stopped


@pytest.fixture
def worker_context(monkeypatch):
    clock = SimpleNamespace(now=0)
    discover = Mock(return_value=[])
    dispatch = Mock(return_value="processed")

    monkeypatch.setattr(runner.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(
        runner, "list_ready_workspace_jobs", discover
    )
    monkeypatch.setattr(
        runner, "dispatch_workspace_job", dispatch
    )

    return SimpleNamespace(
        clock=clock,
        discover=discover,
        dispatch=dispatch,
        candidate=ReadyWorkspaceJob(
            "embedding", "ws_owner", "test-job"
        ),
    )


def test_processes_discovered_job(worker_context):
    ctx = worker_context
    ctx.discover.return_value = [ctx.candidate]
    stop = FakeStop(ctx.clock)

    runner.run_worker(stop)

    ctx.dispatch.assert_called_once_with(ctx.candidate)
    ctx.discover.assert_called_once_with(limit=20, exclude=set())
    assert stop.waits == [2]


@pytest.mark.parametrize(
    "outcome",
    ["idle", "deferred", "configuration_mismatch"],
)
def test_cooldown_excludes_job_on_next_poll(worker_context, outcome):
    ctx = worker_context
    ctx.discover.side_effect = [[ctx.candidate], []]
    ctx.dispatch.return_value = outcome
    stop = FakeStop(ctx.clock, cycles=2)

    runner.run_worker(stop, poll_seconds=0.5)

    assert ctx.discover.call_args_list[1].kwargs["exclude"] == {
        ctx.candidate
    }
    ctx.dispatch.assert_called_once()


def test_expired_cooldown_allows_another_attempt(worker_context):
    ctx = worker_context
    ctx.discover.return_value = [ctx.candidate]
    ctx.dispatch.side_effect = ["deferred", "processed"]
    stop = FakeStop(ctx.clock, cycles=2)

    runner.run_worker(stop, poll_seconds=60)

    assert ctx.dispatch.call_count == 2
    assert ctx.discover.call_args_list[1].kwargs["exclude"] == set()


def test_dispatch_exception_is_delayed_and_loop_continues(
    worker_context, caplog
):
    ctx = worker_context
    ctx.discover.side_effect = [[ctx.candidate], []]
    ctx.dispatch.side_effect = RuntimeError("Synthetic failure")
    stop = FakeStop(ctx.clock, cycles=2)

    runner.run_worker(stop)

    assert ctx.discover.call_count == 2
    assert ctx.discover.call_args_list[1].kwargs["exclude"] == {
        ctx.candidate
    }
    assert "dispatch failed" in caplog.text


def test_discovery_exception_does_not_stop_worker(worker_context, caplog):
    ctx = worker_context
    ctx.discover.side_effect = [
        RuntimeError("Synthetic database outage"),
        [ctx.candidate],
    ]
    stop = FakeStop(ctx.clock, cycles=2)

    runner.run_worker(stop)

    ctx.dispatch.assert_called_once_with(ctx.candidate)
    assert stop.waits == [5, 2]
    assert "Queue discovery failed" in caplog.text


def test_already_stopped_worker_does_no_work(worker_context):
    ctx = worker_context
    stop = FakeStop(ctx.clock)
    stop.set()

    runner.run_worker(stop)

    ctx.discover.assert_not_called()
    ctx.dispatch.assert_not_called()
    assert stop.waits == []


def test_shutdown_skips_remaining_jobs(worker_context):
    ctx = worker_context
    other = ReadyWorkspaceJob("vision", "ws_other", "other-job")
    ctx.discover.return_value = [ctx.candidate, other]
    stop = FakeStop(ctx.clock)

    def finish_current(candidate):
        stop.set()
        return "processed"

    ctx.dispatch.side_effect = finish_current

    runner.run_worker(stop)

    ctx.dispatch.assert_called_once_with(ctx.candidate)


@pytest.mark.parametrize("seconds", [0, 61, float("nan")])
def test_invalid_poll_interval_is_rejected(worker_context, seconds):
    ctx = worker_context

    with pytest.raises(ValueError, match="poll_seconds"):
        runner.run_worker(
            FakeStop(ctx.clock),
            poll_seconds=seconds,
        )

    ctx.discover.assert_not_called()