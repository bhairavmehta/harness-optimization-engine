"""Background jobs for optimizer and RL runs (polled by the UI)."""
import itertools
import threading
import time
import traceback

JOBS = {}
_ids = itertools.count(1)


class Job:
    def __init__(self, kind, params):
        self.id = f"job-{next(_ids)}"
        self.kind, self.params = kind, params
        self.status, self.progress, self.error = "running", 0.0, None
        self.logs, self.result, self.snapshot = [], None, None
        self.cancelled, self.t0 = False, time.time()

    def log(self, msg):
        self.logs.append({"t": round(time.time() - self.t0, 1), "msg": msg})

    def view(self, full=True):
        v = {"id": self.id, "kind": self.kind, "status": self.status, "progress": round(self.progress, 3),
             "params": self.params, "error": self.error, "elapsed": round(time.time() - self.t0, 1),
             "logs": self.logs[-200:] if full else self.logs[-3:]}
        if full:
            v["snapshot"] = self.snapshot
            v["result"] = self.result
        return v


def start(kind, params, fn):
    job = Job(kind, params)
    JOBS[job.id] = job

    def wrap():
        try:
            job.result = fn(job)
            job.status = "cancelled" if job.cancelled else "done"
            job.progress = 1.0
        except Exception as ex:  # surface errors to the UI
            job.status, job.error = "failed", f"{ex}"
            job.log(traceback.format_exc(limit=3))
    threading.Thread(target=wrap, daemon=True).start()
    return job
