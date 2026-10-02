from threading import Event, Lock, Thread

from app.workers.runner import BoundedJobRunner


class SequencedWorker:
    def __init__(self, jobs: list[object | None]) -> None:
        self.jobs = jobs

    def process_next(self) -> object | None:
        return self.jobs.pop(0) if self.jobs else None


class BlockingWorker:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def process_next(self) -> None:
        self.started.set()
        self.release.wait(timeout=2)
        return None


class ConcurrentWorker:
    def __init__(self) -> None:
        self._remaining_jobs = 2
        self._lock = Lock()
        self.active = 0
        self.maximum_active = 0
        self.both_started = Event()
        self.release = Event()

    def process_next(self) -> object | None:
        with self._lock:
            if not self._remaining_jobs:
                return None
            self._remaining_jobs -= 1
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            if self.active == 2:
                self.both_started.set()

        self.release.wait(timeout=2)
        with self._lock:
            self.active -= 1
        return object()


def test_runner_processes_all_available_jobs() -> None:
    runner = BoundedJobRunner(SequencedWorker([object(), object(), None]), 1)  # type: ignore[arg-type]

    assert runner.run_pending() == 2


def test_runner_returns_none_when_all_slots_are_busy() -> None:
    worker = BlockingWorker()
    runner = BoundedJobRunner(worker, 1)
    thread = Thread(target=runner.run_pending)
    thread.start()
    assert worker.started.wait(timeout=1)

    assert runner.run_pending() is None

    worker.release.set()
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_runner_uses_configured_parallelism_for_pending_jobs() -> None:
    worker = ConcurrentWorker()
    runner = BoundedJobRunner(worker, 2)
    result: list[int | None] = []

    thread = Thread(target=lambda: result.append(runner.run_pending()))
    thread.start()
    assert worker.both_started.wait(timeout=1)
    assert worker.maximum_active == 2

    worker.release.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert result == [2]
