import os
import traceback as traceback_module

from celery import Celery
from celery.app.task import Task
from celery.exceptions import Ignore, Reject, Retry
from celery.signals import setup_logging, task_failure, task_postrun, worker_ready

from app.config import BROKER_URL
from app.logging_config import configure_logging, get_logger

from . import methods as celery_methods
from .database import init_celery_db
from .task_logging import capture_task_logs

logger = get_logger(__name__)


class TrackedTask(Task):
    """Task base class that records task lifecycle events before execution."""

    abstract = True

    def __call__(self, *args, **kwargs):
        task_id = self.request.id
        task_name = self.name
        status = celery_methods.record_task_received(task_id, task_name, args, kwargs)
        self.update_state(task_id=task_id, state=status)
        if status != "RECEIVED":
            logger.info("Task execution skipped | id=%s | name=%s | status=%s", task_id, task_name, status)
            raise Ignore()

        process_id = os.getpid()
        worker_name = self.request.hostname or "unknown"
        self.update_state(task_id=task_id, state="STARTED")
        celery_methods.record_task_started(task_id, process_id, worker_name)

        # Capture everything the task writes to stdout/stderr (and logging) into
        # CELERY_LOG_FOLDER/<task_id>.log for the duration of this execution.
        with capture_task_logs(task_id):
            logger.info("Task starting | id=%s | name=%s | args=%s | kwargs=%s", task_id, task_name, args, kwargs)
            try:
                return super().__call__(*args, **kwargs)
            except (Retry, Ignore, Reject):
                # Celery control-flow signals, not real failures.
                raise
            except Exception:
                # sys.stderr is tee'd into the per-task log file here, so this records
                # the full traceback in <task_id>.log (Celery only logs it after __call__).
                traceback_module.print_exc()
                raise


app = Celery(
    "celery_app",
    broker=BROKER_URL,
    backend=BROKER_URL,
    include=["celery_app.tasks"],
    task_cls=TrackedTask,
)

app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # We capture stdout/stderr per task ourselves (see TrackedTask / task_logging),
    # so disable Celery's global stdout->logging redirection to avoid double output.
    worker_redirect_stdouts=False,
)


@worker_ready.connect
def on_worker_ready(**kwargs):
    """Initialise the master database when the worker starts."""
    init_celery_db()


@setup_logging.connect
def configure_celery_logging(**_kwargs) -> None:
    """Use the project's logging configuration instead of Celery's default."""
    configure_logging(file_name="celery.log")


@task_postrun.connect
def on_task_postrun(task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **_extra) -> None:
    """Post-run hook: fires right after a task finishes (success or failure)."""
    task_name = getattr(task, "name", task)
    # Outcome persistence lives in SC_TaskWorker (record_task_*). Don't call
    # task.update_state here: with no meta it overwrites the result metadata
    # Celery already stored in the result backend for this task.
    if task is not None and state is not None:
        if state == "SUCCESS":
            celery_methods.record_task_success(task_id, retval)
        elif state == "REVOKED":
            celery_methods.record_task_cancelled(task_id)
    logger.info("Task finished | id=%s | name=%s | state=%s | result=%s", task_id, task_name, state, retval)


@task_failure.connect
def on_task_failure(task_id=None, exception=None, traceback=None, task=None, args=None, kwargs=None, **_extra) -> None:
    """Failure hook: fires when a task raises an exception."""
    task_name = getattr(task, "name", task)
    traceback_str = (
        "".join(traceback_module.format_exception(type(exception), exception, traceback)) if traceback else ""
    )
    celery_methods.record_task_failure(task_id, exception, traceback_str)
    logger.error(
        "Task failed | id=%s | name=%s | exception=%s | traceback=%s", task_id, task_name, exception, traceback_str
    )
