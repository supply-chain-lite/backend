"""Per-task log capture for Celery tasks.

Each task execution is given its own log file at ``CELERY_LOG_FOLDER/<task_id>.log``
that records everything the task writes to ``stdout``/``stderr`` as well as any
output emitted through the standard :mod:`logging` machinery while the task runs.

NOTE: :func:`capture_task_logs` redirects the process-wide ``sys.stdout`` /
``sys.stderr`` and attaches a handler to the root logger for the duration of the
task. This assumes only one task runs per process at a time, which is true for the
``solo`` (Windows dev) and ``prefork`` pools. It is **not** safe for the
``threads``/``gevent``/``eventlet`` pools, where tasks share a single process and
their output would bleed across each other.
"""

import logging
import sys
from contextlib import contextmanager
from pathlib import Path

from app.config import CELERY_LOG_FOLDER, LOG_LEVEL

# Keep the per-task log format consistent with app/logging_config.py.
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

logger = logging.getLogger(__name__)


class _StreamTee:
    """A writable stream that fans writes out to several underlying streams.

    Used to send ``stdout``/``stderr`` to both the original stream (so the worker
    console still shows output) and the per-task log file.
    """

    def __init__(self, *streams):
        self._streams = [stream for stream in streams if stream is not None]
        self._primary = self._streams[0] if self._streams else None

    def write(self, data):
        for stream in self._streams:
            try:
                stream.write(data)
            except Exception:
                pass
        return len(data)

    def flush(self):
        for stream in self._streams:
            try:
                stream.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    def writable(self):
        return True

    def fileno(self):
        # Delegate to a real underlying stream so code that needs a file
        # descriptor (e.g. subprocess) keeps working. Such output bypasses the
        # tee and is therefore not captured into the per-task log file.
        for stream in self._streams:
            try:
                return stream.fileno()
            except Exception:
                continue
        raise OSError("no underlying fileno available")

    def __getattr__(self, name):
        # Delegate any other attribute access (e.g. ``encoding``, ``buffer``) to
        # the primary underlying stream so the tee behaves like a normal stream.
        if name.startswith("_"):
            raise AttributeError(name)
        primary = self.__dict__.get("_primary")
        if primary is None:
            raise AttributeError(name)
        return getattr(primary, name)


@contextmanager
def capture_task_logs(task_uid):
    """Capture all ``stdout``/``stderr`` and logging output for the duration of a task.

    Everything emitted inside the ``with`` block is written to
    ``CELERY_LOG_FOLDER/<task_uid>.log`` in addition to the worker console and the
    shared ``celery.log``. If the log file cannot be opened, task execution
    continues without per-task capture.
    """
    if not task_uid:
        # Without a task UID we cannot name the file; run without capturing.
        yield
        return

    try:
        log_path = Path(CELERY_LOG_FOLDER) / f"{task_uid}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8")
    except Exception:
        logger.warning("Could not open per-task log file for task %s", task_uid, exc_info=True)
        yield
        return

    handler = logging.StreamHandler(log_file)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.setLevel(LOG_LEVEL)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = _StreamTee(original_stdout, log_file)
    sys.stderr = _StreamTee(original_stderr, log_file)

    try:
        yield
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        root_logger.removeHandler(handler)
        try:
            handler.close()
        finally:
            log_file.close()
