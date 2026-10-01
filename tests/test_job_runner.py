from threading import Event, Thread

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
