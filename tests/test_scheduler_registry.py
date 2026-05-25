from contentflow.admin.scheduler_registry import get_known_scheduler_jobs, get_scheduler_job_map
from contentflow.agents.chat_agent import TOOLS
from contentflow.scheduler_job_registry import SCHEDULER_JOB_SPECS


def test_scheduler_registry_includes_operations_snapshot():
    jobs = get_known_scheduler_jobs()
    job_ids = {job["id"] for job in jobs}

    assert "persist_operations_health_snapshot" in job_ids
    assert len(job_ids) == len(jobs)


def test_chat_tool_scheduler_enum_matches_registry():
    registry_ids = [job["id"] for job in get_known_scheduler_jobs()]
    tool = next(item for item in TOOLS if item["function"]["name"] == "trigger_scheduler_job")

    assert tool["function"]["parameters"]["properties"]["job_id"]["enum"] == registry_ids


def test_scheduler_job_map_resolves_operations_snapshot():
    job_map = get_scheduler_job_map()

    assert "persist_operations_health_snapshot" in job_map
    assert callable(job_map["persist_operations_health_snapshot"])


def test_scheduler_runtime_registry_contains_all_job_ids():
    scheduler_ids = {job["scheduler_id"] for job in SCHEDULER_JOB_SPECS}

    assert len(SCHEDULER_JOB_SPECS) == 27
    assert "operations_snapshot" in scheduler_ids
    assert "scheduler_heartbeat" in scheduler_ids