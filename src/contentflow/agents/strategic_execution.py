from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from contentflow.models.database import StrategicPlan


async def run_strategic_agent_impl(
    project_id: int,
    *,
    session_factory,
    logger,
    collect_project_context,
    summarize_planning_recommendations,
    call_strategic_llm,
    fallback_plan,
    normalize_plan_result,
    attach_action_evidence,
    attach_action_controls,
) -> StrategicPlan:
    today = date.today()
    logger.info(f"[StrategicAgent] 啟動 project={project_id} date={today}")

    with session_factory() as session:
        existing = (
            session.query(StrategicPlan)
            .filter(
                StrategicPlan.project_id == project_id,
                StrategicPlan.plan_date == today,
                StrategicPlan.plan_type == "daily",
            )
            .first()
        )
        if existing and existing.status != "pending":
            logger.info(f"[StrategicAgent] 今日計畫已存在且狀態={existing.status}，跳過")
            return existing

        planning_recommendations: list[dict[str, Any]] = []
        try:
            from .planning_agent import generate_content_plan

            planning_plan = await generate_content_plan(project_id, session)
            planning_recommendations = summarize_planning_recommendations(planning_plan)
        except Exception as exc:
            logger.warning(f"[StrategicAgent] Planning Agent 失敗（降級繼續）：{exc}")

        context_snapshot = collect_project_context(project_id, session)
        if planning_recommendations:
            context_snapshot["planning_recommendations"] = planning_recommendations

    try:
        plan_result = await call_strategic_llm(context_snapshot)
    except Exception as exc:
        logger.error(f"[StrategicAgent] LLM 決策失敗：{exc}")
        plan_result = fallback_plan(context_snapshot)

    plan_result = normalize_plan_result(plan_result, context_snapshot)
    plan_result = attach_action_evidence(plan_result, context_snapshot)
    plan_result = attach_action_controls(plan_result, context_snapshot)
    actions = plan_result.get("actions", [])
    summary = plan_result.get("summary", "")

    with session_factory() as session:
        plan = StrategicPlan(
            project_id=project_id,
            plan_date=today,
            plan_type="daily",
            actions_json=json.dumps(actions, ensure_ascii=False),
            summary=summary,
            context_snapshot=json.dumps(context_snapshot, ensure_ascii=False),
            total_count=len(actions),
            executed_count=0,
            status="pending",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)
        logger.info(f"[StrategicAgent] 計畫產出完成：{len(actions)} 項 action | {summary[:80]}")
        return plan


async def execute_strategic_plan_impl(
    plan_id: int,
    *,
    session_factory,
    logger,
    can_execute_action,
    execute_generate,
    execute_refresh,
    execute_alert,
    execute_optimize_meta,
    execute_inject_internal_links,
    execute_resolve_cannibalization=None,
) -> None:
    with session_factory() as session:
        plan = session.get(StrategicPlan, plan_id)
        if not plan:
            logger.error(f"[StrategicExecutor] Plan #{plan_id} 不存在")
            return
        plan.status = "executing"
        session.commit()

        actions = json.loads(plan.actions_json or "[]")
        project_id = plan.project_id

    executed = 0
    failed = 0
    skipped = 0
    updated_actions: list[dict[str, Any]] = []

    for raw_action in sorted(actions, key=lambda item: item.get("priority", 99)):
        action = dict(raw_action)
        action_type = action.get("action")
        can_execute, skip_reason = can_execute_action(action)
        if not can_execute:
            skipped += 1
            action["execution_status"] = "skipped"
            action["execution_note"] = skip_reason
            updated_actions.append(action)
            continue

        try:
            if action_type == "generate":
                await execute_generate(action, project_id, plan_id=plan_id)
            elif action_type == "refresh":
                await execute_refresh(action, project_id, plan_id=plan_id)
            elif action_type == "alert":
                await execute_alert(action, project_id)
            elif action_type == "optimize_meta":
                await execute_optimize_meta(action, project_id)
            elif action_type == "inject_internal_links":
                await execute_inject_internal_links(action, project_id)
            elif action_type == "resolve_cannibalization" and execute_resolve_cannibalization:
                await execute_resolve_cannibalization(action, project_id)
            else:
                logger.warning(f"[StrategicExecutor] 未知 action 類型：{action_type}")
                action["execution_status"] = "skipped"
                action["execution_note"] = f"unknown_action={action_type}"
                skipped += 1
                updated_actions.append(action)
                continue

            executed += 1
            action["execution_status"] = "executed"
            action["executed_at"] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            logger.error(f"[StrategicExecutor] action={action_type} 失敗：{exc}")
            failed += 1
            action["execution_status"] = "failed"
            action["execution_error"] = str(exc)
        updated_actions.append(action)

    with session_factory() as session:
        plan = session.get(StrategicPlan, plan_id)
        if plan:
            plan.executed_count = executed
            plan.actions_json = json.dumps(updated_actions, ensure_ascii=False)
            plan.status = "partial" if (failed or skipped) else "completed"
            session.commit()

    logger.info(
        f"[StrategicExecutor] Plan #{plan_id} 完成，{executed}/{len(actions)} 項 "
        f"(skipped={skipped}, failed={failed})"
    )