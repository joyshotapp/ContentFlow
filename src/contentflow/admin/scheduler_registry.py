from __future__ import annotations

from contentflow.scheduler_job_registry import SCHEDULER_JOB_SPECS

def get_scheduler_job_map():
    from contentflow import scheduler as sched_mod

    return {
        job["id"]: getattr(sched_mod, job["callable_name"])
        for job in SCHEDULER_JOB_SPECS
        if job.get("admin_visible")
    }


def get_known_scheduler_jobs():
    return [
        {
            "id": job["id"],
            "name": job["name"],
            "schedule": job["schedule"],
            "icon": job["icon"],
        }
        for job in SCHEDULER_JOB_SPECS
        if job.get("admin_visible")
    ]