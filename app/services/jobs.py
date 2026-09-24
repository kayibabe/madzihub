from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import logging

log = logging.getLogger("opsapp.jobs")
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="srwb-job")


def run_async(func, *args, **kwargs) -> Future:
    future = executor.submit(func, *args, **kwargs)

    def _callback(done: Future) -> None:
        exc = done.exception()
        if exc is not None:
            log.exception("background_job_failed", exc_info=exc)

    future.add_done_callback(_callback)
    return future
