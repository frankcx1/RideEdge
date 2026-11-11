"""One bounded FIFO admission queue for all app-local model sessions."""
import threading
import time
from collections import deque
from datetime import UTC, datetime
from contextlib import contextmanager

from farol.adapters.base import FeedError


class QueueBusy(FeedError):
    code = "model_queue_busy"


class ObsoleteRequest(FeedError):
    code = "model_request_obsolete"


class ModelQueue:
    def __init__(self, pending_limit=2, wait_seconds=180):
        self.pending_limit, self.wait_seconds = pending_limit, wait_seconds
        self.condition = threading.Condition()
        self.active = None
        self.pending = []
        self.accepting = True
        self.active_since = None
        self.completed = 0
        self.failed = 0
        self.recent = deque(maxlen=12)

    def status(self):
        with self.condition:
            return {"active": self.active, "queued": len(self.pending),
                    "pending_limit": self.pending_limit, "accepting": self.accepting,
                    "active_since": self.active_since, "completed": self.completed, "failed": self.failed,
                    "recent": [dict(row) for row in self.recent]}

    def close(self):
        with self.condition:
            self.accepting = False
            self.condition.notify_all()

    def open(self):
        with self.condition:
            if self.active is not None or self.pending:
                raise RuntimeError("Cannot reopen a model queue with unfinished work")
            self.accepting = True

    @contextmanager
    def admit(self, kind="local-qwen", valid=None):
        if kind not in {"local-qwen", "radar-plan", "radar-question", "brief", "comparison-question"}:
            raise ValueError("Unknown model job kind")
        ticket = object()
        deadline = time.monotonic() + self.wait_seconds
        with self.condition:
            if not self.accepting or len(self.pending) >= self.pending_limit:
                raise QueueBusy("The local model queue is full or shutting down; retry later")
            self.pending.append(ticket)
            try:
                while self.active is not None or self.pending[0] is not ticket:
                    remaining = deadline - time.monotonic()
                    if not self.accepting or remaining <= 0:
                        raise QueueBusy("The local model queue wait expired; evidence ranking remains available")
                    self.condition.wait(min(remaining, 1))
                if not self.accepting:
                    raise QueueBusy("The local model queue is shutting down")
                if valid is not None and not valid():
                    raise ObsoleteRequest("Location or evidence changed before this AI request could start")
                self.pending.pop(0)
                self.active = kind
                self.active_since = datetime.now(UTC).isoformat()
            except BaseException:
                if ticket in self.pending:
                    self.pending.remove(ticket)
                self.condition.notify_all()
                raise
        began = time.monotonic()
        outcome = "completed"
        try:
            yield
        except BaseException:
            outcome = "failed"
            raise
        finally:
            with self.condition:
                self.completed += outcome == "completed"
                self.failed += outcome == "failed"
                self.recent.appendleft({"kind": kind, "state": outcome, "started_at": self.active_since,
                                        "finished_at": datetime.now(UTC).isoformat(),
                                        "duration_seconds": round(time.monotonic() - began, 2)})
                self.active = None
                self.active_since = None
                self.condition.notify_all()


queue = ModelQueue()
