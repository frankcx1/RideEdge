import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from farol.model_queue import ModelQueue, ObsoleteRequest, QueueBusy


def wait_queued(queue, size):
    deadline = time.monotonic() + 2
    while queue.status()["queued"] != size and time.monotonic() < deadline:
        time.sleep(.005)
    assert queue.status()["queued"] == size


def test_queue_is_bounded_fifo_and_releases_after_failure():
    queue = ModelQueue(pending_limit=2)
    order = []

    def run(index):
        with queue.admit():
            order.append(index)

    with ThreadPoolExecutor(max_workers=2) as pool:
        with queue.admit("radar-plan"):
            first = pool.submit(run, 1)
            wait_queued(queue, 1)
            second = pool.submit(run, 2)
            wait_queued(queue, 2)
            with pytest.raises(QueueBusy), queue.admit():
                pytest.fail("Queue overflow")
        first.result(timeout=2)
        second.result(timeout=2)
    assert order == [1, 2]
    with pytest.raises(ValueError), queue.admit():
        raise ValueError("Model failure")
    assert queue.status()["active"] is None and queue.status()["queued"] == 0


def test_obsolete_waiting_job_never_starts_and_next_job_can_run():
    queue = ModelQueue()
    valid = threading.Event()
    valid.set()

    def run():
        with pytest.raises(ObsoleteRequest), queue.admit(valid=valid.is_set):
            pytest.fail("Obsolete work started")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with queue.admit():
            pending = pool.submit(run)
            wait_queued(queue, 1)
            valid.clear()
        pending.result(timeout=2)
    with queue.admit():
        assert queue.status()["active"] == "local-qwen"


def test_wait_timeout_removes_ticket_without_interrupting_active_work():
    queue = ModelQueue(wait_seconds=.02)

    def run():
        with pytest.raises(QueueBusy), queue.admit():
            pytest.fail("Expired request started")

    with ThreadPoolExecutor(max_workers=1) as pool, queue.admit("radar-plan"):
        pool.submit(run).result(timeout=2)
        assert queue.status()["queued"] == 0
        assert queue.status()["active"] == "radar-plan"
