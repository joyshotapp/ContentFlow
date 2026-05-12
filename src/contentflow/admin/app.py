"""ContentFlow Admin Dashboard — FastAPI 後台管理介面

完整 12 頁架構（對應系統所有模組）：

 儀表板          /
 ─── 內容管理 ────
 文章管理         /articles  (list + detail /{id})
 內容日曆         /calendar
 關鍵字庫         /keywords
 主題叢集         /clusters
 ─── SEO 分析 ───
 GSC 績效         /seo
 競品追蹤         /competitors
 ─── AI 引擎 ────
 Agent 執行中心   /agents
 知識庫           /knowledge
 ─── 系統 ───────
 排程監控         /scheduler
 系統健康         /health
 專案設定         /settings
"""
from __future__ import annotations

import asyncio
import difflib
import json
import secrets
import uuid
from collections import Counter, defaultdict
from types import SimpleNamespace
from datetime import date, datetime, timedelta, timezone

from fastapi import BackgroundTasks, FastAPI, Request, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
from pathlib import Path
from sqlalchemy import desc, func, inspect, literal
from typing import Any

from starlette.middleware.sessions import SessionMiddleware

from contentflow.config import settings
from contentflow.admin.article_ops import _mark_article_published, _native_blog_url, _submit_to_google_indexing
from contentflow.admin.health_ops import _build_operations_health, _get_agent_cost_metrics, _serialize_operations_health
from contentflow.admin.scheduler_registry import get_known_scheduler_jobs, get_scheduler_job_map
from contentflow.db import SessionLocal
from contentflow.models.database import (
    ActionOutcome,
    Article,
    AgentDecisionLog,
    Author,
    ContentCalendar,
    Competitor,
    CompetitorSnapshot,
    GAPageMetric,
    KnowledgeEntry,
    KnowledgeAuditLog,
    Keyword,
    LegalTerm,
    OperationsHealthSnapshot,
    PipelineRun,
    Product,
    Project,
    ProjectAuditLog,
    ProjectIntegration,
    ReflectionLog,
    SchedulerLog,
    SEORanking,
    StrategicFeedbackLog,
    StrategicPlan,
    TopicCluster,
    ClusterMember,
    WritingRule,
    ContentStrategy,
)
from contentflow.models.schemas import ArticleDraft, ResearchReport
from contentflow.policy_profiles import (
    COMPLIANCE_PROFILES,
    CONTENT_FORMAT_PROFILES,
    DOMAIN_PROFILES,
    SUPPORTED_COMPLIANCE_PROFILES,
    SUPPORTED_CONTENT_FORMAT_PROFILES,
    SUPPORTED_DOMAIN_PROFILES,
)
from contentflow.policy_resolver import resolve_policy
from contentflow.project_context import load_project_context
from contentflow.project_integrations import (
    build_wordpress_publisher,
    resolve_forgebase_settings,
    resolve_wordpress_settings,
    run_integration_diagnostic,
)
from contentflow.utils.secret_crypto import encrypt_secret_value
from contentflow.utils.topic_hygiene import is_viable_topic

# ── App ───────────────────────────────────────────────────────

admin_app = FastAPI(title="ContentFlow Admin", docs_url=None, redoc_url=None)
admin_app.add_middleware(
    SessionMiddleware,
    secret_key=settings.api_secret_key or secrets.token_urlsafe(32),
)

_here = Path(__file__).resolve().parent
_static_dir = _here / "static"
admin_app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
templates = Jinja2Templates(directory=str(_here / "templates"))
templates.env.filters["fromjson"] = json.loads
templates.env.globals["site_url"] = settings.site_url
templates.env.globals["site_name"] = settings.site_name
templates.env.globals["site_contact_email"] = settings.site_contact_email


def _db():
    return SessionLocal()


def _goal_config_for_template(raw_value: str | None) -> dict[str, Any]:
    from contentflow.agents.strategic_agent import _parse_business_goal_profile

    parsed = _parse_business_goal_profile(raw_value or "")
    raw_text = (raw_value or "").strip()
    config: dict[str, Any] = {}
    if raw_text.startswith("{"):
        try:
            maybe_json = json.loads(raw_text)
            if isinstance(maybe_json, dict):
                config = maybe_json
        except Exception:
            config = {}

    weights = parsed.get("weights", {})
    priority_topics = parsed.get("priority_topics", [])
    money_pages = parsed.get("money_pages", [])

    return {
        "raw": raw_text,
        "primary_goal": config.get("primary_goal") or parsed.get("primary_goal") or "awareness",
        "secondary_goal": config.get("secondary_goal") or parsed.get("secondary_goal") or "authority",
        "weights": weights,
        "priority_topics": priority_topics,
        "money_pages": money_pages,
    }


def _append_project_audit(
    db,
    *,
    project_id: int,
    action_type: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    actor: str = "admin",
) -> None:
    db.add(
        ProjectAuditLog(
            project_id=project_id,
            actor=actor,
            action_type=action_type,
            summary=summary,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
            created_at=datetime.now(timezone.utc),
        )
    )


def _build_onboarding_checklist(
    project: Project | None,
    *,
    wordpress_integration,
    forgebase_integration,
) -> list[SimpleNamespace]:
    if not project:
        return []

    return [
        SimpleNamespace(title="站點網址", done=bool(project.brand_url), detail=project.brand_url or "尚未設定 canonical base URL"),
        SimpleNamespace(title="聯絡信箱", done=bool(project.site_contact_email), detail=project.site_contact_email or "尚未設定站點聯絡信箱"),
        SimpleNamespace(title="文章路徑", done=bool(project.site_blog_path), detail=project.site_blog_path or "尚未設定文章 URL path"),
        SimpleNamespace(
            title="內容政策",
            done=bool(project.domain_profile and project.compliance_profile and project.default_content_format),
            detail=" / ".join(filter(None, [project.domain_profile or "—", project.compliance_profile or "—", project.default_content_format or "—"])),
        ),
        SimpleNamespace(
            title="WordPress Connector",
            done=bool(wordpress_integration and wordpress_integration.configured and wordpress_integration.is_enabled),
            detail=(wordpress_integration.base_url if wordpress_integration and wordpress_integration.base_url else "未啟用"),
        ),
        SimpleNamespace(
            title="ForgeBase Connector",
            done=bool(forgebase_integration and forgebase_integration.configured and forgebase_integration.is_enabled),
            detail=(forgebase_integration.base_url if forgebase_integration and forgebase_integration.base_url else "未啟用"),
        ),
    ]


def _build_onboarding_wizard(
    project: Project | None,
    *,
    wordpress_integration,
    forgebase_integration,
) -> list[SimpleNamespace]:
    if not project:
        return []

    has_site_profile = bool(project.brand_url and project.site_contact_email and project.site_blog_path)
    has_wordpress = bool(wordpress_integration and wordpress_integration.configured and wordpress_integration.is_enabled)
    has_forgebase = bool(forgebase_integration and forgebase_integration.configured and forgebase_integration.is_enabled)
    has_connector = has_wordpress or has_forgebase
    connector_target = "WordPress" if has_wordpress else "ForgeBase" if has_forgebase else "未設定"

    return [
        SimpleNamespace(
            step_key="profile",
            title="Step 1. 站點 Profile",
            done=has_site_profile,
            state_label="READY" if has_site_profile else "ACTION",
            detail="設定 canonical URL、聯絡信箱與原生文章路徑，讓 native publish 與 managed site 有一致輸出。",
            cta_label="前往站點設定",
            cta_href="#project-profile",
        ),
        SimpleNamespace(
            step_key="connector",
            title="Step 2. Connector 選型",
            done=has_connector,
            state_label="READY" if has_connector else "ACTION",
            detail=f"至少啟用一個發布目標。當前可用目標：{connector_target}。",
            cta_label="前往 Connector Wizard",
            cta_href="#connector-wizard",
        ),
        SimpleNamespace(
            step_key="diagnostic",
            title="Step 3. 連線診斷",
            done=bool(
                (wordpress_integration and wordpress_integration.is_enabled and wordpress_integration.configured)
                or (forgebase_integration and forgebase_integration.is_enabled and forgebase_integration.configured)
            ),
            state_label="READY" if has_connector else "ACTION",
            detail="完成儲存後執行 connector test，確認 health status 與 last diagnostic message。",
            cta_label="執行 Connector Test",
            cta_href="#integrations",
        ),
        SimpleNamespace(
            step_key="mode",
            title="Step 4. Delivery Mode",
            done=settings.platform_mode in {"hybrid", "managed-site", "control-plane"},
            state_label=settings.platform_mode.upper(),
            detail=(
                "目前為 Control Plane only，managed site 不會掛載。"
                if settings.platform_mode == "control-plane" or not settings.managed_site_enabled
                else "目前可同時作為 control plane 與 managed site delivery target。"
            ),
            cta_label="查看模式說明",
            cta_href="#platform-mode",
        ),
    ]


def _build_policy_setup_wizard(project: Project | None) -> list[SimpleNamespace]:
    if not project:
        return []

    domain_value = project.domain_profile or "general"
    compliance_value = project.compliance_profile or "general"
    format_value = project.default_content_format or "knowledge"

    return [
        SimpleNamespace(
            step_key="domain_policy",
            title="Step 1. Domain Profile",
            done=bool(domain_value),
            state_label=(DOMAIN_PROFILES.get(domain_value).label if domain_value in DOMAIN_PROFILES else "ACTION"),
            detail="決定知識來源、品牌語氣與圖片語境。正式上線專案不可省略。",
            current_value=domain_value,
            cta_label="前往 Policy Setup",
            cta_href="#policy-setup",
        ),
        SimpleNamespace(
            step_key="compliance_policy",
            title="Step 2. Compliance Profile",
            done=bool(compliance_value),
            state_label=(COMPLIANCE_PROFILES.get(compliance_value).label if compliance_value in COMPLIANCE_PROFILES else "ACTION"),
            detail="決定免責聲明、審閱需求與 fact check 強度。",
            current_value=compliance_value,
            cta_label="檢查合規設定",
            cta_href="#policy-setup",
        ),
        SimpleNamespace(
            step_key="format_policy",
            title="Step 3. Default Content Format",
            done=bool(format_value),
            state_label=(CONTENT_FORMAT_PROFILES.get(format_value).label if format_value in CONTENT_FORMAT_PROFILES else "ACTION"),
            detail="決定 schema 主型別、FAQ/HowTo 偏好與圖片構圖方向。",
            current_value=format_value,
            cta_label="檢查內容型態",
            cta_href="#policy-setup",
        ),
    ]


def _build_connector_wizard(
    *,
    wordpress_integration,
    forgebase_integration,
    integration_diagnostics: dict[str, dict[str, Any]],
) -> list[SimpleNamespace]:
    items = []
    connector_specs = [
        ("wordpress", "WordPress", wordpress_integration, ["Site URL", "Username", "Application Password", "SEO Plugin", "Publish Mode"]),
        ("forgebase", "ForgeBase", forgebase_integration, ["API Base URL", "API Token", "Publish Mode"]),
    ]
    for integration_type, label, cfg, fields in connector_specs:
        diagnostic = integration_diagnostics.get(integration_type, {}) if integration_diagnostics else {}
        status = diagnostic.get("status") or ("healthy" if cfg and cfg.is_enabled and cfg.configured else "pending")
        items.append(
            SimpleNamespace(
                integration_type=integration_type,
                label=label,
                configured=bool(cfg and cfg.configured),
                enabled=bool(cfg and cfg.is_enabled),
                status=status,
                required_fields=fields,
                summary=diagnostic.get("message") or ("Connector 已配置" if cfg and cfg.configured else "尚未完成必要欄位"),
                base_url=(cfg.base_url if cfg and cfg.base_url else ""),
                anchor="#integrations",
            )
        )
    return items


def _build_goal_weighted_monthly_report(db, project_id: int, goal_config: dict[str, Any]) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    plans = (
        db.query(StrategicPlan)
        .filter(StrategicPlan.project_id == project_id, StrategicPlan.created_at >= cutoff)
        .order_by(StrategicPlan.created_at.desc())
        .all()
    )

    reviewed = approved = executed = 0
    utility_sum = 0.0
    utility_count = 0
    by_action: dict[str, dict[str, Any]] = {}

    for plan in plans:
        try:
            actions = json.loads(plan.actions_json or "[]")
        except Exception:
            actions = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_type = action.get("action") or "unknown"
            bucket = by_action.setdefault(action_type, {
                "action_type": action_type,
                "count": 0,
                "approved": 0,
                "executed": 0,
                "avg_utility": 0.0,
                "utility_total": 0.0,
            })
            bucket["count"] += 1
            review_status = str(action.get("review_status") or "approved").lower()
            if action.get("review_required"):
                reviewed += 1
            if review_status == "approved":
                approved += 1
                bucket["approved"] += 1
            if str(action.get("execution_status") or "") == "executed":
                executed += 1
                bucket["executed"] += 1

            utility = action.get("goal_weighted_utility")
            if utility is not None:
                try:
                    utility_value = float(utility)
                    utility_sum += utility_value
                    utility_count += 1
                    bucket["utility_total"] += utility_value
                except (TypeError, ValueError):
                    pass

    for bucket in by_action.values():
        if bucket["count"]:
            bucket["approval_rate"] = round(bucket["approved"] / bucket["count"] * 100, 1)
            bucket["execution_rate"] = round(bucket["executed"] / bucket["count"] * 100, 1)
        else:
            bucket["approval_rate"] = 0.0
            bucket["execution_rate"] = 0.0
        bucket["avg_utility"] = round(bucket["utility_total"] / bucket["count"], 3) if bucket["count"] else 0.0

    top_goal = max(goal_config.get("weights", {"awareness": 1.0}), key=goal_config.get("weights", {"awareness": 1.0}).get)
    top_goal_weight = goal_config.get("weights", {}).get(top_goal, 0.0)
    return {
        "window_days": 30,
        "plan_count": len(plans),
        "reviewed_actions": reviewed,
        "approved_actions": approved,
        "executed_actions": executed,
        "avg_goal_weighted_utility": round(utility_sum / utility_count, 3) if utility_count else None,
        "top_goal": top_goal,
        "top_goal_weight": round(float(top_goal_weight), 3),
        "by_action": sorted(by_action.values(), key=lambda item: (item["avg_utility"], item["count"]), reverse=True),
    }


def _load_json_object(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        value = json.loads(raw_value)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _normalize_schema_types_input(raw_value: str | None) -> str:
    if not raw_value:
        return "[]"
    text = raw_value.strip()
    if not text:
        return "[]"
    try:
        parsed = json.loads(text)
        values = parsed if isinstance(parsed, list) else []
    except Exception:
        values = [item.strip() for item in text.replace("\n", ",").split(",")]

    cleaned: list[str] = []
    for value in values:
        if isinstance(value, str):
            item = value.strip()
            if item and item not in cleaned:
                cleaned.append(item)
    return json.dumps(cleaned, ensure_ascii=False)


def _build_policy_preview(project_id: int, *, db=None, article=None) -> tuple[dict[str, Any], list[str]]:
    ctx = load_project_context(project_id=project_id)
    preview_ctx = SimpleNamespace(**ctx.__dict__)
    article_type = getattr(article, "article_type", None) if article else None

    if article and article.content_format_override:
        preview_ctx.default_content_format = article.content_format_override
        article_type = None
    if article and article.custom_disclaimer:
        preview_ctx.disclaimer_template = article.custom_disclaimer
    if article and article.extra_schema_types_override_json:
        preview_ctx.extra_schema_types_json = article.extra_schema_types_override_json

    policy = resolve_policy(preview_ctx, article_type=article_type)
    effective_require_reviewer = policy.require_reviewer
    if article and article.reviewer_required_override is not None:
        effective_require_reviewer = bool(article.reviewer_required_override)

    warnings: list[str] = []
    if policy.compliance_profile.startswith("ymyl") and effective_require_reviewer:
        if not policy.reviewer_role_label:
            warnings.append("此 policy 需要專業審閱，但 reviewer_role_label 尚未設定。")
        if not policy.disclaimer_template:
            warnings.append("此 policy 需要免責聲明，但 disclaimer_template 尚未設定。")
        if db is not None:
            reviewer_role_candidates = []
            if policy.compliance_profile.startswith("ymyl_"):
                reviewer_role_candidates.append(policy.compliance_profile.split("_", 1)[1])
            if policy.reviewer_role_label == "專業審閱":
                reviewer_role_candidates.append("general")
            reviewer_exists = None
            if reviewer_role_candidates:
                candidates = (
                    db.query(Author)
                    .filter(Author.project_id == project_id)
                    .all()
                )
                reviewer_exists = next(
                    (
                        author for author in candidates
                        if (author.reviewer_role in reviewer_role_candidates)
                        or ("medical" in reviewer_role_candidates and author.is_medical_reviewer)
                    ),
                    None,
                )
            if reviewer_role_candidates and not reviewer_exists:
                warnings.append("此 policy 需要對應 reviewer，但目前專案尚未建立符合角色的審閱者。")
    if policy.evidence_policy == "pubmed" and policy.domain_profile != "health":
        warnings.append("目前使用 PubMed 作為證據來源，但 Domain Profile 不是 health，請確認這是刻意覆寫。")

    reviewer_role_key = ""
    if policy.compliance_profile.startswith("ymyl_"):
        reviewer_role_key = policy.compliance_profile.split("_", 1)[1]
    elif policy.compliance_profile == "regulated_soft":
        reviewer_role_key = "general"

    payload = {
        "domain_profile": policy.domain_profile,
        "domain_label": DOMAIN_PROFILES[policy.domain_profile].label,
        "compliance_profile": policy.compliance_profile,
        "compliance_label": COMPLIANCE_PROFILES[policy.compliance_profile].label,
        "content_format": policy.content_format,
        "content_format_label": CONTENT_FORMAT_PROFILES[policy.content_format].label,
        "use_pubmed": policy.use_pubmed,
        "evidence_policy": policy.evidence_policy,
        "require_reviewer": effective_require_reviewer,
        "reviewer_role_label": policy.reviewer_role_label,
        "reviewer_role_key": reviewer_role_key,
        "disclaimer_template": policy.disclaimer_template,
        "factcheck_mode": policy.factcheck_mode,
        "schema_types": list(policy.all_schema_types),
        "hero_image_style": policy.hero_image_style,
    }
    return payload, warnings


def _upsert_project_integration(
    db,
    *,
    project_id: int,
    integration_type: str,
    label: str,
    base_url: str,
    username: str,
    secret_value: str,
    seo_plugin: str,
    publish_mode: str,
    is_enabled: bool,
) -> ProjectIntegration:
    row = (
        db.query(ProjectIntegration)
        .filter(
            ProjectIntegration.project_id == project_id,
            ProjectIntegration.integration_type == integration_type,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = ProjectIntegration(
            project_id=project_id,
            integration_type=integration_type,
            created_at=now,
        )
        db.add(row)

    row.label = label.strip()
    row.base_url = base_url.strip()
    row.username = username.strip()
    if secret_value.strip() or row.id is None:
        row.secret_value = encrypt_secret_value(secret_value)
    row.seo_plugin = seo_plugin.strip() or "yoast"
    row.publish_mode = publish_mode.strip() or "publish"
    row.is_enabled = bool(is_enabled)
    row.updated_at = now
    return row


def _build_project_usage_report(db, project_id: int, window_days: int = 30) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    runs = (
        db.query(PipelineRun)
        .filter(PipelineRun.project_id == project_id, PipelineRun.started_at >= cutoff)
        .order_by(PipelineRun.started_at.desc())
        .all()
    )
    step_counts = dict(
        db.query(AgentDecisionLog.step, func.count(AgentDecisionLog.id))
        .filter(AgentDecisionLog.project_id == project_id, AgentDecisionLog.created_at >= cutoff)
        .group_by(AgentDecisionLog.step)
        .all()
    )
    feedback_counts = dict(
        db.query(StrategicFeedbackLog.review_status, func.count(StrategicFeedbackLog.id))
        .filter(StrategicFeedbackLog.project_id == project_id, StrategicFeedbackLog.created_at >= cutoff)
        .group_by(StrategicFeedbackLog.review_status)
        .all()
    )

    total_cost = round(sum(float(run.total_cost or 0.0) for run in runs), 4)
    total_llm_calls = sum(int(run.total_llm_calls or 0) for run in runs)
    completed_runs = sum(1 for run in runs if run.status == "completed")
    failed_runs = sum(1 for run in runs if run.status == "failed")
    avg_cost = round(total_cost / len(runs), 4) if runs else 0.0
    avg_seo_score = round(
        sum(int(run.seo_score) for run in runs if run.seo_score is not None) / max(1, sum(1 for run in runs if run.seo_score is not None)),
        1,
    ) if any(run.seo_score is not None for run in runs) else None
    projected_monthly_cost = round(total_cost * (30 / max(window_days, 1)), 4) if runs else 0.0
    billable_units = {
        "pipeline_runs": len(runs),
        "llm_calls": total_llm_calls,
        "review_events": sum(int(value or 0) for value in feedback_counts.values()),
    }
    billing_basis = [
        ("Pipeline Runs", billable_units["pipeline_runs"], "每次內容生產或 refresh 流程"),
        ("LLM Calls", billable_units["llm_calls"], "模型呼叫次數，可作為 usage tier 依據"),
        ("Review Events", billable_units["review_events"], "審核與覆核事件，可作為 service ops 成本基礎"),
    ]

    return {
        "window_days": window_days,
        "run_count": len(runs),
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
        "total_cost": total_cost,
        "avg_cost": avg_cost,
        "total_llm_calls": total_llm_calls,
        "avg_seo_score": avg_seo_score,
        "projected_monthly_cost": projected_monthly_cost,
        "billable_units": billable_units,
        "billing_basis": billing_basis,
        "step_counts": sorted(step_counts.items(), key=lambda item: item[1], reverse=True),
        "feedback_counts": feedback_counts,
    }


def _build_project_approval_history(db, project_id: int, window_days: int = 30) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    logs = (
        db.query(StrategicFeedbackLog)
        .filter(StrategicFeedbackLog.project_id == project_id, StrategicFeedbackLog.created_at >= cutoff)
        .order_by(StrategicFeedbackLog.created_at.desc())
        .limit(20)
        .all()
    )
    by_status = dict(
        db.query(StrategicFeedbackLog.review_status, func.count(StrategicFeedbackLog.id))
        .filter(StrategicFeedbackLog.project_id == project_id, StrategicFeedbackLog.created_at >= cutoff)
        .group_by(StrategicFeedbackLog.review_status)
        .all()
    )
    items = []
    for log in logs:
        payload = _load_json_object(log.payload_json)
        items.append(
            {
                "created_at": log.created_at,
                "action_type": log.action_type,
                "feedback_type": log.feedback_type,
                "review_status": log.review_status,
                "note": log.note,
                "article_id": log.article_id,
                "promoted_asset_type": log.promoted_asset_type,
                "reason": payload.get("reason") or payload.get("summary") or "",
            }
        )
    return {
        "window_days": window_days,
        "entries": items,
        "by_status": by_status,
        "total": len(items),
    }


def _build_project_audit_view(logs: list[ProjectAuditLog]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for log in logs:
        payload = _load_json_object(log.payload_json)
        payload_lines = []
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                rendered = json.dumps(value, ensure_ascii=False)
            else:
                rendered = str(value)
            payload_lines.append(f"{key}: {rendered}")
        items.append(
            {
                "summary": log.summary,
                "action_type": log.action_type,
                "actor": log.actor,
                "created_at": log.created_at,
                "payload_lines": payload_lines,
            }
        )
    return items


async def _generate_action_preview(db, plan: StrategicPlan, action: dict[str, Any], context_snapshot: dict[str, Any]) -> dict[str, Any]:
    action_type = action.get("action") or "unknown"
    if action_type == "refresh":
        from contentflow.agents.refresh_agent import FetchedArticle, RefreshDiffAnalyzer, apply_local_patches

        article = db.query(Article).filter(Article.id == action.get("article_id")).first()
        if not article:
            return {"preview_type": "refresh", "error": "找不到文章"}

        content = (article.draft_content or "").strip() or article.title or ""
        analyzer = RefreshDiffAnalyzer()
        fetched = FetchedArticle(
            url=article.publish_url or "",
            platform="native",
            post_id=str(article.id),
            title=article.title or "",
            content_html="",
            content_text=content,
            meta_title=article.meta_title or "",
            meta_description=article.meta_description or "",
            word_count=len(content),
        )
        serp_summary = action.get("reason") or ""
        plan_preview = analyzer.analyze(fetched, action.get("keyword") or article.primary_keyword or article.title or "", serp_summary)
        patched = apply_local_patches(
            fetched,
            plan_preview,
            action.get("keyword") or article.primary_keyword or article.title or "",
            generate_content=False,
            gsc_context={"low_ctr_queries": action.get("gsc_queries", [])},
        )
        diff_text = "\n".join(difflib.unified_diff(content.splitlines(), patched.splitlines(), fromfile="current", tofile="preview", lineterm=""))
        return {
            "preview_type": "refresh",
            "recommendation": plan_preview.recommendation,
            "freshness_score": plan_preview.overall_freshness_score,
            "gaps": [
                {
                    "gap_type": gap.gap_type,
                    "description": gap.description,
                    "heading": gap.suggested_heading,
                }
                for gap in plan_preview.gaps
            ],
            "competitor_advantages": plan_preview.competitor_advantages,
            "current_excerpt": content[:800],
            "preview_excerpt": patched[:1200],
            "diff": diff_text[:2400],
        }

    if action_type == "optimize_meta":
        from contentflow.agents.seo_qa_agent import run_seo_qa_agent

        article = db.query(Article).filter(Article.id == action.get("article_id")).first()
        if not article:
            return {"preview_type": "optimize_meta", "error": "找不到文章"}

        draft = ArticleDraft(
            title=article.title or "",
            meta_title=article.meta_title or article.title or "",
            meta_description=article.meta_description or "",
            content_markdown=article.draft_content or article.title or "",
            slug=article.slug or "",
        )
        report = ResearchReport(
            article_title=article.title or "",
            keywords=[article.primary_keyword or article.title or ""],
            suggested_keywords=[query.get("query", "") for query in action.get("gsc_queries", []) if query.get("query")],
        )
        optimized = await run_seo_qa_agent(
            draft,
            report,
            primary_keyword=article.primary_keyword or article.title or "",
            secondary_keywords=[query.get("query", "") for query in action.get("gsc_queries", []) if query.get("query")],
            failed_checks=[{"name": "gsc_query_gap", "detail": action.get("reason", ""), "passed": False}],
            project_id=plan.project_id,
        )
        return {
            "preview_type": "optimize_meta",
            "old_meta_title": article.meta_title or "",
            "new_meta_title": optimized.meta_title or "",
            "old_meta_description": article.meta_description or "",
            "new_meta_description": optimized.meta_description or "",
            "old_opening": (article.draft_content or "")[:280],
            "new_opening": (optimized.content_markdown or "")[:280],
        }

    if action_type == "inject_internal_links":
        article = db.query(Article).filter(Article.id == action.get("article_id")).first()
        suggestions = []
        if article and article.suggested_internal_links:
            try:
                suggestions = json.loads(article.suggested_internal_links or "[]")
            except Exception:
                suggestions = []
        return {
            "preview_type": "inject_internal_links",
            "suggestions": suggestions[:10],
        }

    return {
        "preview_type": action_type,
        "summary": action.get("reason") or action.get("message") or "尚無可用 preview",
    }


def _check_login(request: Request) -> bool:
    return bool(request.session.get("admin_logged_in"))


_ROLE_LEVELS = {
    "editor": 1,
    "reviewer": 2,
    "owner": 3,
}


def _get_session_role(request: Request) -> str:
    role = str(request.session.get("admin_role") or "").strip().lower()
    if role in _ROLE_LEVELS:
        return role
    if _check_login(request):
        return "owner"
    return ""


def _has_role(request: Request, minimum_role: str) -> bool:
    current_role = _get_session_role(request)
    if not current_role:
        return False
    return _ROLE_LEVELS.get(current_role, 0) >= _ROLE_LEVELS.get(minimum_role, 0)


def _require_role(request: Request, minimum_role: str) -> str:
    if not _check_login(request):
        raise HTTPException(status_code=403, detail="未登入")
    current_role = _get_session_role(request)
    if _ROLE_LEVELS.get(current_role, 0) < _ROLE_LEVELS.get(minimum_role, 0):
        raise HTTPException(status_code=403, detail="權限不足")
    return current_role


def _authenticate_admin_role(password: str) -> str | None:
    candidates = [
        ("owner", settings.api_secret_key),
        ("reviewer", settings.admin_reviewer_secret),
        ("editor", settings.admin_editor_secret),
    ]
    for role, secret_value in candidates:
        if secret_value and secrets.compare_digest(password, secret_value):
            return role
    return None


def _get_env_var_status() -> list:
    """回傳各整合功能的環境變數設定狀況。"""
    from types import SimpleNamespace as _SN
    checks = [
        ("OPENAI_API_KEY",       "OpenAI LLM（寫作 / 研究）",            bool(settings.openai_api_key if hasattr(settings, 'openai_api_key') else None)),
        ("GOOGLE_API_KEY",       "Google Gemini LLM",                    bool(settings.google_api_key if hasattr(settings, 'google_api_key') else None)),
        ("SERPER_API_KEY",       "Serper.dev SERP 搜尋",                  bool(settings.serper_api_key if hasattr(settings, 'serper_api_key') else None)),
        ("SERPAPI_KEY",          "SerpAPI 搜尋（備用）",                   bool(settings.serpapi_key if hasattr(settings, 'serpapi_key') else None)),
        ("GOOGLE_SERVICE_ACCOUNT", "Google Search Console",               bool(settings.google_service_account_file)),
        ("GA4_PROPERTY_ID",      "Google Analytics 4",                    bool(settings.ga4_property_id)),
        ("AGENTOPS_API_KEY",     "AgentOps 可觀測性追蹤",                  bool(settings.agentops_api_key if hasattr(settings, 'agentops_api_key') else None)),
        ("FORGEBASE_API_TOKEN",  "ForgeBase 發佈",                        bool(settings.forgebase_api_token)),
        ("SLACK_WEBHOOK_URL",    "Slack 告警通知",                        bool(settings.slack_webhook_url if hasattr(settings, 'slack_webhook_url') else None)),
        ("DATABASE_URL",         "PostgreSQL 資料庫",                    True),  # if app is running, DB is connected
    ]
    return [_SN(name=name, description=desc, set=status) for name, desc, status in checks]


# ── Label / color maps ────────────────────────────────────────

STATUS_LABELS = {
    "pending": "排程中",
    "planned": "規劃中",
    "researching": "研究中",
    "writing": "撰寫中",
    "fact_checking": "事實查核中",
    "generating_images": "生成圖片中",
    "review_required": "待審閱",
    "reviewing": "審閱中",
    "approved": "已核准",
    "published": "已發佈",
    "completed": "已完成",
    "failed": "失敗",
}
STATUS_COLORS = {
    "pending": "neutral",
    "planned": "neutral",
    "researching": "info",
    "writing": "warning",
    "fact_checking": "purple",
    "generating_images": "sky",
    "review_required": "amber",
    "reviewing": "purple",
    "approved": "success",
    "published": "success",
    "completed": "success",
    "failed": "danger",
}
CONFIDENCE_LABELS = {
    "unverified": "未驗證", "verified": "已驗證", "universal": "通用規則",
}
CONFIDENCE_COLORS = {
    "unverified": "warning", "verified": "success", "universal": "info",
}

PIPELINE_STEPS = [
    ("research",    "研究",   "#6366f1"),
    ("strategy",    "策略",   "#8b5cf6"),
    ("writing",     "撰文",   "#3b82f6"),
    ("seo_check",   "SEO 檢查", "#f59e0b"),
    ("seo_qa",      "SEO 修正", "#f97316"),
    ("factcheck",   "事實查核", "#10b981"),
    ("budget_guard","預算守衛", "#64748b"),
]


# ═══════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": None})


@admin_app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    if not any([settings.api_secret_key, settings.admin_reviewer_secret, settings.admin_editor_secret]):
        logger.error("[Admin] 管理登入 secret 未設定，拒絕登入")
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": "管理登入 secret 未設定，請先完成部署設定"},
            status_code=503,
        )

    role = _authenticate_admin_role(password)
    if role:
        request.session["admin_logged_in"] = True
        request.session["admin_role"] = role
        return RedirectResponse("/admin/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": "密碼錯誤"})


@admin_app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


# ═══════════════════════════════════════════════════════════════
# DASHBOARD  /
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        now = datetime.now(timezone.utc)

        # KPI
        total_articles = db.query(Article).count()
        published    = db.query(Article).filter(Article.status == "published").count()
        reviewing    = db.query(Article).filter(Article.status == "reviewing").count()
        total_kw     = db.query(Keyword).count()
        total_clusters = db.query(TopicCluster).count()
        knowledge_count = db.query(KnowledgeEntry).filter(KnowledgeEntry.is_active == True).count()

        # Article status dist
        raw_status = db.query(Article.status, func.count()).group_by(Article.status).all()
        status_counts = {s: c for s, c in raw_status}

        # GSC summary
        seo = db.query(
            func.avg(SEORanking.position),
            func.sum(SEORanking.clicks),
            func.sum(SEORanking.impressions),
        ).first()
        avg_position     = round(seo[0], 1) if seo[0] else 0
        total_clicks     = seo[1] or 0
        total_impressions = seo[2] or 0

        # Pipeline runs (last 8)
        runs_raw = (
            db.query(
                AgentDecisionLog.run_id,
                AgentDecisionLog.article_id,
                func.min(AgentDecisionLog.created_at).label("started"),
                func.max(AgentDecisionLog.created_at).label("ended"),
                func.count(AgentDecisionLog.id).label("steps"),
            )
            .group_by(AgentDecisionLog.run_id, AgentDecisionLog.article_id)
            .order_by(desc("started"))
            .limit(8)
            .all()
        )
        pipeline_runs = []
        for r in runs_raw:
            art = db.query(Article).filter(Article.id == r.article_id).first() if r.article_id else None
            steps = db.query(AgentDecisionLog).filter(AgentDecisionLog.run_id == r.run_id).all()
            over_budget = any("強制" in (d.decision or "") for d in steps if d.step == "budget_guard")
            last_step = steps[-1].step if steps else ""
            pipeline_runs.append({
                "run_id": r.run_id,
                "run_id_short": r.run_id[:8],
                "article_title": (art.title[:45] if art else "—"),
                "article_status": art.status if art else "",
                "started": r.started,
                "steps": r.steps,
                "is_complete": last_step in ("budget_guard", "factcheck"),
                "over_budget": over_budget,
            })

        total_runs = db.query(func.count(func.distinct(AgentDecisionLog.run_id))).scalar() or 0
        cost_metrics = _get_agent_cost_metrics(db)

        # Pending review
        pending_review = (
            db.query(Article).filter(Article.status == "reviewing")
            .order_by(desc(Article.updated_at)).limit(5).all()
        )

        # Calendar this month
        cm = now.month
        cal_total = db.query(ContentCalendar).filter(ContentCalendar.month == cm).count()
        cal_done  = db.query(ContentCalendar).filter(
            ContentCalendar.month == cm, ContentCalendar.status.in_(["published", "completed"])
        ).count()

        # Recent scheduler
        sched_success = db.query(SchedulerLog).filter(SchedulerLog.status == "success").count()
        sched_fail    = db.query(SchedulerLog).filter(SchedulerLog.status == "failed").count()
        recent_sched  = db.query(SchedulerLog).order_by(desc(SchedulerLog.started_at)).limit(5).all()

        return templates.TemplateResponse(request, "dashboard.html", {
            "request": request, "page": "dashboard", "now": now,
            "total_articles": total_articles, "published": published, "reviewing": reviewing,
            "total_kw": total_kw, "total_clusters": total_clusters, "knowledge_count": knowledge_count,
            "status_counts": json.dumps(status_counts),
            "avg_position": avg_position, "total_clicks": total_clicks, "total_impressions": total_impressions,
            "pipeline_runs": pipeline_runs, "total_runs": total_runs, "total_cost": cost_metrics["total_cost"],
            "pending_review": pending_review,
            "cal_total": cal_total, "cal_done": cal_done, "cal_month": cm,
            "sched_success": sched_success, "sched_fail": sched_fail, "recent_sched": recent_sched,
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# ARTICLES  /articles  /articles/{id}
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/articles", response_class=HTMLResponse)
async def articles_list(request: Request, status: str = "", q: str = "", page: int = 1):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        PAGE_SIZE = 20
        query = db.query(Article).order_by(desc(Article.updated_at))
        if status:
            query = query.filter(Article.status == status)
        if q:
            like = f"%{q}%"
            query = query.filter((Article.title.ilike(like)) | (Article.primary_keyword.ilike(like)))
        total = query.count()
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(page, total_pages))
        articles = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
        raw = db.query(Article.status, func.count()).group_by(Article.status).all()
        sc = {s: c for s, c in raw}
        return templates.TemplateResponse(request, "articles.html", {
            "request": request, "page": page, "page_size": PAGE_SIZE,
            "articles": articles, "status_filter": status, "search_q": q,
            "total": total, "total_pages": total_pages,
            "sc": sc, "status_counts": sc,
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.post("/articles/create")
async def create_article(
    request: Request,
    keyword: str = Form(...),
    title: str = Form(""),
    article_type: str = Form("知識"),
):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        ok, reason = is_viable_topic(title or keyword, keyword)
        if not ok:
            raise HTTPException(status_code=400, detail=f"無效的文章題目或關鍵字：{reason}")

        art = Article(
            title=title or keyword,
            primary_keyword=keyword,
            article_type=article_type,
            status="planned",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(art)
        db.commit()
        db.refresh(art)
        return RedirectResponse(f"/admin/articles/{art.id}", status_code=303)
    finally:
        db.close()


@admin_app.post("/articles/bulk-create")
async def bulk_create_articles(request: Request):
    """從 JSON body 批量建立 planned 文章（[{keyword, title, article_type}, ...]）"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    data = await request.json()
    db = _db()
    try:
        created = []
        for item in data:
            kw = item.get("keyword", "").strip()
            if not kw:
                continue
            ok, _ = is_viable_topic(item.get("title", kw), kw)
            if not ok:
                continue
            art = Article(
                title=item.get("title", kw),
                primary_keyword=kw,
                article_type=item.get("article_type", "知識"),
                status="planned",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(art)
            created.append(kw)
        db.commit()
        return {"created": len(created), "keywords": created}
    finally:
        db.close()


@admin_app.get("/articles/{article_id}", response_class=HTMLResponse)
async def article_detail(request: Request, article_id: int):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            raise HTTPException(status_code=404)

        # SEO ranking history for this keyword
        seo_history = []
        if article.primary_keyword:
            seo_history = [
                {"date": str(r.tracked_date), "position": round(float(r.position), 1) if r.position else 0,
                 "clicks": r.clicks or 0, "impressions": r.impressions or 0}
                for r in (
                    db.query(SEORanking)
                    .filter(SEORanking.keyword == article.primary_keyword)
                    .order_by(SEORanking.tracked_date).limit(30).all()
                )
            ]

        # Pipeline decision logs — convert ORM to dicts for template rendering
        _STEP_NAMES = {
            "research": "Research Agent", "strategy": "Strategy Agent",
            "writing": "Writing Agent", "seo_check": "SEO Check Agent",
            "seo_qa": "SEO QA", "factcheck": "FactCheck Agent",
            "budget_guard": "Budget Guard", "publish": "Publish Agent",
        }
        decisions = [
            {
                "agent_name": _STEP_NAMES.get(d.step, d.step),
                "step": d.step,
                "decision": d.decision,
                "reasoning": d.reason,          # model field is `reason`
                "confidence": d.confidence,
                "created_at": d.created_at,
            }
            for d in (
                db.query(AgentDecisionLog)
                .filter(AgentDecisionLog.article_id == article.id)
                .order_by(AgentDecisionLog.created_at).all()
            )
        ]

        # Group by run (for pipeline_runs reference — keep for backwards compat)
        runs_dict: dict = defaultdict(list)
        for d in (db.query(AgentDecisionLog).filter(AgentDecisionLog.article_id == article.id).all()):
            runs_dict[d.run_id].append(d)

        # Research JSON
        research_data = {}
        if article.research_report_json:
            try:
                research_data = json.loads(article.research_report_json)
            except Exception:
                pass

        policy_preview, policy_warnings = _build_policy_preview(article.project_id, db=db, article=article)

        return templates.TemplateResponse(request, "article_detail.html", {
            "request": request, "page": "articles",
            "site_name": settings.site_name,
            "art": article,                               # template uses `art`
            "decisions": decisions,
            "seo_history": seo_history,                  # list of dicts (JSON-serializable)
            "research_data": research_data,
            "PIPELINE_STEPS": PIPELINE_STEPS,
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
            "CONFIDENCE_LABELS": CONFIDENCE_LABELS, "CONFIDENCE_COLORS": CONFIDENCE_COLORS,
            # Internal link suggestions from AI
            "internal_links": json.loads(article.suggested_internal_links or "[]"),
            # Authors for E-E-A-T assignment
            "authors": db.query(Author).filter(Author.project_id == article.project_id).order_by(Author.name).all(),
            "policy_preview": policy_preview,
            "policy_warnings": policy_warnings,
            "content_format_profiles": CONTENT_FORMAT_PROFILES,
            # Fact-check issues parsed from JSON
            "fact_issues": json.loads(article.factcheck_flags_json) if article.factcheck_flags_json and article.factcheck_flags_json.strip() else [],
            # PAA questions for FAQ content ideas
            "paa_questions": json.loads(article.paa_questions_json or "[]"),
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.post("/articles/{article_id}/status")
async def update_article_status(request: Request, article_id: int, status: str = Form(...)):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        art = db.query(Article).filter(Article.id == article_id).first()
        if art:
            art.status = status
            art.updated_at = datetime.now(timezone.utc)
            # 發布到 goodbone.com.tw 時，記錄 publish_url 並提交 Google Indexing API
            if status == "published" and art.slug:
                publish_url = _native_blog_url(art.slug, art.project_id, db=db)
                _mark_article_published(art, publish_url=publish_url)
                db.commit()
                asyncio.create_task(_submit_to_google_indexing(publish_url))
            else:
                db.commit()
        return RedirectResponse(f"/admin/articles/{article_id}", status_code=303)
    finally:
        db.close()


@admin_app.post("/articles/{article_id}/save")
async def save_article(request: Request, article_id: int):
    """儲存文章內容（Markdown + meta 欄位）。"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    data = await request.json()
    db = _db()
    try:
        art = db.query(Article).filter(Article.id == article_id).first()
        if not art:
            raise HTTPException(status_code=404)
        if "draft_content" in data:
            art.draft_content = data["draft_content"]
        if "meta_title" in data:
            art.meta_title = data["meta_title"]
        if "meta_description" in data:
            art.meta_description = data["meta_description"]
        if "slug" in data:
            new_slug = (data["slug"] or "").strip()
            if new_slug and new_slug != art.slug:
                # 檢查 slug 是否已被其他文章使用
                duplicate = db.query(Article).filter(
                    Article.slug == new_slug,
                    Article.id != article_id,
                ).first()
                if duplicate:
                    return JSONResponse(
                        {"ok": False, "message": f"Slug「{new_slug}」已被文章 id={duplicate.id} 使用"},
                        status_code=409,
                    )
            if new_slug:
                art.slug = new_slug
        if "title" in data:
            art.title = data["title"]
        if "content_format_override" in data:
            value = (data["content_format_override"] or "").strip().lower()
            art.content_format_override = value if value in SUPPORTED_CONTENT_FORMAT_PROFILES else None
        if "reviewer_required_override" in data:
            raw_value = (data["reviewer_required_override"] or "").strip().lower()
            if raw_value in {"", "inherit"}:
                art.reviewer_required_override = None
            else:
                art.reviewer_required_override = raw_value in {"1", "true", "required", "yes", "on"}
        if "custom_disclaimer" in data:
            art.custom_disclaimer = (data["custom_disclaimer"] or "").strip() or None
        if "extra_schema_types_override" in data:
            art.extra_schema_types_override_json = _normalize_schema_types_input(data["extra_schema_types_override"])
        art.updated_at = datetime.now(timezone.utc)
        db.commit()
        return JSONResponse({"ok": True, "message": "已儲存"})
    finally:
        db.close()


@admin_app.post("/articles/{article_id}/publish-wp")
async def publish_to_wordpress(request: Request, article_id: int):
    """發布文章到 WordPress（建立草稿或更新既有文章）。"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        art = db.query(Article).filter(Article.id == article_id).first()
        if not art:
            raise HTTPException(status_code=404)
        if not art.draft_content:
            return JSONResponse({"ok": False, "error": "文章尚無內容，無法發布"}, status_code=400)

        from contentflow.models.schemas import ArticleDraft

        draft = ArticleDraft(
            title=art.title,
            meta_title=art.meta_title or art.title,
            meta_description=art.meta_description or "",
            content_markdown=art.draft_content,
            slug=art.slug or "",
            faq_schema_json=art.faq_schema_json or "",
            article_schema_json=art.article_schema_json or "",
        )

        wp = build_wordpress_publisher(db=db, project_id=art.project_id)
        result = await wp.publish_draft(draft)

        if result.success:
            _mark_article_published(art, publish_url=result.publish_url or "")
            db.commit()
            # Async: trigger Google Indexing API for faster crawl
            if art.publish_url:
                asyncio.create_task(_submit_to_google_indexing(art.publish_url))
            return JSONResponse({"ok": True, "post_id": result.post_id, "url": result.publish_url})
        else:
            return JSONResponse({"ok": False, "error": result.error}, status_code=502)
    finally:
        db.close()


@admin_app.post("/articles/{article_id}/set-author")
async def set_article_author(request: Request, article_id: int, author_id: int = Form(0)):
    """設定文章作者（E-E-A-T）。"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        art = db.query(Article).filter(Article.id == article_id).first()
        if art:
            art.author_id = author_id if author_id else None
            art.updated_at = datetime.now(timezone.utc)
            db.commit()
        return RedirectResponse(f"/admin/articles/{article_id}", status_code=303)
    finally:
        db.close()


@admin_app.post("/articles/{article_id}/set-reviewer")
async def set_article_reviewer(request: Request, article_id: int, reviewer_id: int = Form(0)):
    """設定文章審閱者（E-E-A-T）。"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        art = db.query(Article).filter(Article.id == article_id).first()
        if art:
            art.reviewer_id = reviewer_id if reviewer_id else None
            art.updated_at = datetime.now(timezone.utc)
            db.commit()
        return RedirectResponse(f"/admin/articles/{article_id}", status_code=303)
    finally:
        db.close()


@admin_app.post("/articles/{article_id}/refresh")
async def trigger_article_refresh(request: Request, article_id: int):
    """手動觸發單篇文章 Refresh Pipeline（分析模式，不自動發布）。"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        art = db.query(Article).filter(Article.id == article_id).first()
        if not art:
            raise HTTPException(status_code=404, detail="Article not found")

        from contentflow.agents.refresh_agent import run_refresh_pipeline
        result = await run_refresh_pipeline(
            article=art,
            keyword=art.primary_keyword or art.title,
            session=db,
            platform="url" if art.publish_url else "forgebase",
            generate_content=False,
            publish=False,
        )
        plan = result.get("plan")
        fetched = result.get("fetched")
        summary = {
            "freshness_score": getattr(plan, "overall_freshness_score", None),
            "recommendation": getattr(plan, "recommendation", "unknown"),
            "gaps_count": len(getattr(plan, "gaps", [])),
            "gaps": [
                {"type": g.gap_type, "desc": g.description}
                for g in getattr(plan, "gaps", [])
            ],
            "word_count": getattr(fetched, "word_count", 0),
        }
        # 回寫 last_refresh_date
        art.last_refresh_date = datetime.now(timezone.utc)
        db.commit()

        import urllib.parse
        qs = urllib.parse.urlencode({
            "refresh_score": summary["freshness_score"],
            "refresh_rec": summary["recommendation"],
            "refresh_gaps": summary["gaps_count"],
        })
        return RedirectResponse(f"/admin/articles/{article_id}?{qs}", status_code=303)
    except Exception as e:
        logger.error(f"[Refresh] article={article_id} 失敗: {e}")
        db.rollback()
        import urllib.parse as _up
        safe_err = _up.quote(str(e)[:100], safe="")
        return RedirectResponse(
            f"/admin/articles/{article_id}?refresh_error={safe_err}",
            status_code=303,
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# CONTENT CALENDAR  /calendar
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, month: int = 0):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        now = datetime.now(timezone.utc)
        # month=0 表示顯示所有月份（預設）

        all_entries = (
            db.query(ContentCalendar)
            .order_by(ContentCalendar.month, ContentCalendar.week)
            .all()
        )

        # Enrich entries with linked article data
        enriched = []
        for e in all_entries:
            art = db.query(Article).filter(Article.id == e.article_id).first() if e.article_id else None
            enriched.append({
                "id": e.article_id or e.id,
                "cal_id": e.id,
                "status": e.status,
                "title": (art.title if art else e.title) or "(未命名)",
                "primary_keyword": (art.primary_keyword if art else None) or (e.keywords.split(",")[0].strip() if e.keywords else ""),
                "seo_score": art.seo_score if art else None,
                "scheduled_date": None,
                "article_type": e.article_type,
                "month": e.month or 0,
                "week": e.week or 0,
            })

        # Status counts
        sc = {}
        for item in enriched:
            sc[item["status"]] = sc.get(item["status"], 0) + 1

        # Group by month → weeks → items, only show requested month (or all if month=0)
        months_map: dict = {}
        MONTH_NAMES = {1:"1月",2:"2月",3:"3月",4:"4月",5:"5月",6:"6月",7:"7月",8:"8月",9:"9月",10:"10月",11:"11月",12:"12月"}
        for item in enriched:
            m = item["month"]
            if m == 0: continue
            if month != 0 and m != month: continue
            if m not in months_map:
                months_map[m] = {}
            w = item["week"]
            if w not in months_map[m]:
                months_map[m][w] = []
            months_map[m][w].append(SimpleNamespace(**item))

        calendar = []
        for m in sorted(months_map.keys()):
            weeks = []
            for w in sorted(months_map[m].keys()):
                weeks.append(SimpleNamespace(
                    week_num=w,
                    date_range=f"第 {w} 週",
                    items=months_map[m][w],
                ))
            calendar.append((MONTH_NAMES.get(m, f"{m}月"), weeks))

        months_with_data = sorted(set(e["month"] for e in enriched if e["month"]))

        return templates.TemplateResponse(request, "calendar.html", {
            "request": request, "page": "calendar", "now": now,
            "calendar": calendar,
            "current_month": month, "months_with_data": months_with_data,
            "total": len(enriched),
            "sc": sc,
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
        })
    finally:
        db.close()


@admin_app.post("/calendar/new")
async def create_calendar_entry(
    request: Request,
    project_id: int = Form(0),
    title: str = Form(...),
    month: str = Form(""),
    week: int = Form(1),
    article_type: str = Form("知識"),
    keywords: str = Form(""),
    search_intent: str = Form(""),
    target_audience: str = Form(""),
    writing_architecture: str = Form("倒三角"),
    faq_questions: str = Form(""),
):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    # Parse month: accept "YYYY-MM" (from <input type="month">) or plain int string "4"
    now = datetime.now(timezone.utc)
    try:
        if "-" in month:
            month_int = int(month.split("-")[1])
        else:
            month_int = int(month) if month else now.month
        month_int = max(1, min(12, month_int))
    except (ValueError, IndexError):
        month_int = now.month
    db = _db()
    try:
        project = db.get(Project, project_id) if project_id else None
        ok, reason = is_viable_topic(title, keywords or title, project=project)
        if not ok:
            raise HTTPException(status_code=400, detail=f"無效的日曆題目或關鍵字：{reason}")

        entry = ContentCalendar(
            project_id=project_id or None,
            title=title.strip(),
            month=month_int,
            week=week,
            article_type=article_type,
            keywords=keywords.strip(),
            search_intent=search_intent.strip(),
            target_audience=target_audience.strip(),
            writing_architecture=writing_architecture,
            faq_questions=faq_questions.strip(),
            status="planned",
        )
        db.add(entry)
        db.commit()
    finally:
        db.close()
    return RedirectResponse(f"/admin/calendar?month={month_int}", status_code=303)


@admin_app.post("/calendar/{entry_id}/delete")
async def delete_calendar_entry(request: Request, entry_id: int, month: int = Form(0)):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        entry = db.query(ContentCalendar).filter(ContentCalendar.id == entry_id).first()
        if entry:
            month = month or entry.month or 0
            db.delete(entry)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(f"/admin/calendar?month={month}", status_code=303)


@admin_app.post("/calendar/{entry_id}/run")
async def run_calendar_pipeline(request: Request, entry_id: int, background_tasks: BackgroundTasks):
    """從內容日曆項目建立 Article 並觸發 AI Pipeline"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        entry = db.query(ContentCalendar).filter(ContentCalendar.id == entry_id).first()
        if not entry:
            raise HTTPException(status_code=404, detail="Calendar entry not found")

        # If already linked to an article, use it; otherwise create one
        if entry.article_id:
            article = db.query(Article).filter(Article.id == entry.article_id).first()
        else:
            article = None

        if not article:
            kw_list = [k.strip() for k in (entry.keywords or "").split(",") if k.strip()]
            article = Article(
                project_id=entry.project_id,
                title=entry.title or (kw_list[0] if kw_list else ""),
                primary_keyword=kw_list[0] if kw_list else "",
                secondary_keywords=",".join(kw_list[1:]) if len(kw_list) > 1 else "",
                article_type=entry.article_type or "",
                status="planned",
            )
            db.add(article)
            db.flush()
            entry.article_id = article.id

        entry.status = "researching"
        db.commit()

        article_id = article.id
        project_id = entry.project_id
        cal_month = entry.month or 0
    finally:
        db.close()

    import uuid
    run_id = str(uuid.uuid4())
    background_tasks.add_task(_background_pipeline, run_id, article_id, project_id)
    return RedirectResponse(f"/admin/calendar?month={cal_month}", status_code=303)


# ═══════════════════════════════════════════════════════════════
# KEYWORDS  /keywords
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/keywords", response_class=HTMLResponse)
async def keywords_page(request: Request, q: str = "", sort: str = "volume", intent_filter: str = "", funnel_filter: str = ""):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        query = db.query(Keyword)
        if q:
            query = query.filter(Keyword.keyword.ilike(f"%{q}%"))
        if intent_filter:
            query = query.filter(Keyword.intent == intent_filter)
        if funnel_filter:
            query = query.filter(Keyword.funnel_stage == funnel_filter)
        if sort == "difficulty":
            query = query.order_by(desc(Keyword.seo_difficulty))
        elif sort == "cpc":
            query = query.order_by(desc(Keyword.cpc))
        else:
            query = query.order_by(desc(Keyword.search_volume))
        kws = query.all()

        total = len(kws)
        avg_vol = round(sum(k.search_volume or 0 for k in kws) / max(total, 1))
        avg_diff = round(sum(k.seo_difficulty or 0 for k in kws) / max(total, 1), 1)
        high_vol = sum(1 for k in kws if (k.search_volume or 0) >= 1000)
        diff_low  = sum(1 for k in kws if (k.seo_difficulty or 0) <= 33)
        diff_mid  = sum(1 for k in kws if 33 < (k.seo_difficulty or 0) <= 66)
        diff_high = sum(1 for k in kws if (k.seo_difficulty or 0) > 66)
        vol_max   = max((k.search_volume or 0 for k in kws), default=1) or 1

        _vol_buckets = {"<100": 0, "100-500": 0, "500-1k": 0, "1k-5k": 0, "5k+": 0}
        for k in kws:
            v = k.search_volume or 0
            if v < 100: _vol_buckets["<100"] += 1
            elif v < 500: _vol_buckets["100-500"] += 1
            elif v < 1000: _vol_buckets["500-1k"] += 1
            elif v < 5000: _vol_buckets["1k-5k"] += 1
            else: _vol_buckets["5k+"] += 1
        vol_buckets = [{"label": lbl, "count": cnt} for lbl, cnt in _vol_buckets.items()]

        return templates.TemplateResponse(request, "keywords.html", {
            "request": request, "page": "keywords",
            "keywords": kws, "q": q, "search_q": q, "sort": sort,
            "intent_filter": intent_filter, "funnel_filter": funnel_filter,
            "total": total, "total_kw": total,
            "avg_volume": avg_vol, "avg_difficulty": avg_diff,
            "high_value_count": high_vol,
            "diff_low": diff_low, "diff_mid": diff_mid, "diff_high": diff_high,
            "vol_max": vol_max, "vol_buckets": vol_buckets,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.post("/keywords/new")
async def create_keyword(
    request: Request,
    project_id: int = Form(0),
    keyword: str = Form(...),
    search_volume: float = Form(0),
    seo_difficulty: float = Form(0),
    intent: str = Form(""),
    funnel_stage: str = Form(""),
    steve_note: str = Form(""),
):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        db.add(Keyword(
            project_id=project_id or None,
            keyword=keyword.strip(),
            search_volume=search_volume or 0,
            seo_difficulty=seo_difficulty or 0,
            intent=intent or None,
            funnel_stage=funnel_stage or None,
            steve_note=steve_note.strip(),
        ))
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin/keywords", status_code=303)


@admin_app.post("/keywords/{kw_id}/delete")
async def delete_keyword(request: Request, kw_id: int):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        kw = db.get(Keyword, kw_id)
        if kw:
            db.delete(kw)
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin/keywords", status_code=303)


@admin_app.post("/keywords/{kw_id}/intent")
async def update_keyword_intent(request: Request, kw_id: int, intent: str = Form("")):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        kw = db.get(Keyword, kw_id)
        if kw:
            kw.intent = intent or None
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin/keywords", status_code=303)


@admin_app.post("/keywords/{kw_id}/funnel")
async def update_keyword_funnel(request: Request, kw_id: int, funnel_stage: str = Form("")):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        kw = db.get(Keyword, kw_id)
        if kw:
            kw.funnel_stage = funnel_stage or None
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin/keywords", status_code=303)


@admin_app.post("/keywords/suggest", response_class=JSONResponse)
async def suggest_keywords(
    request: Request,
    topic: str = Form(...),
    project_id: int = Form(0),
):
    """
    根據種子主題呼叫 Serper.dev，整合 PAA + 相關搜尋，
    用 LLM 標記搜尋意圖，回傳批次候選關鍵字供用戶勾選匯入。
    """
    if not _check_login(request):
        return JSONResponse({"error": "未登入"}, status_code=403)

    candidates: list[dict] = []
    error_msg: str = ""

    try:
        from contentflow.tools.serp import search_serp
        serp = await search_serp(topic, num_results=10)

        seen: set[str] = set()

        # 1) PAA 問題（最高品質：真實用戶搜尋意圖）
        for paa in serp.people_also_ask:
            q = paa.question.strip()
            if q and q not in seen:
                seen.add(q)
                candidates.append({"keyword": q, "source": "PAA", "intent": ""})

        # 2) 相關搜尋（Google 演算法認定的語意相關詞）
        for rel in serp.related_searches:
            kw = rel.strip() if isinstance(rel, str) else rel.get("query", "").strip()
            if kw and kw not in seen and len(kw) >= 2:
                seen.add(kw)
                candidates.append({"keyword": kw, "source": "關聯搜尋", "intent": ""})

        # 注意：競品文章標題（serp.top_results title）不作為關鍵字候選匯入，
        # 因為標題是內容靈感而非可追蹤的 SEO 關鍵字，不應污染關鍵字庫。

    except Exception as e:
        error_msg = f"SERP 查詢失敗：{e}（請確認已設定 SERPER_API_KEY）"

    # LLM 意圖標記（批次，若有 API key 則執行）
    if candidates:
        try:
            from contentflow.tools.serp import search_serp  # noqa (already imported above if no error)
            import openai
            client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
            kw_list_text = "\n".join(
                f"{i+1}. {c['keyword']}" for i, c in enumerate(candidates[:30])
            )
            resp = await client.chat.completions.create(
                model=settings.llm_lite_model,
                max_tokens=600,
                messages=[{
                    "role": "user",
                    "content": (
                        "以下是一批中文 SEO 關鍵字候選，請為每個標記搜尋意圖。\n"
                        "意圖只能選：informational / commercial / transactional / navigational\n"
                        "回傳 JSON 陣列，格式：[{\"i\": 1, \"intent\": \"...\"}]\n"
                        "不要說明，只輸出 JSON。\n\n"
                        f"{kw_list_text}"
                    )
                }],
            )
            raw = resp.choices[0].message.content.strip()
            # Extract JSON array
            import re as _re
            m = _re.search(r'\[.*\]', raw, _re.DOTALL)
            if m:
                intent_data = json.loads(m.group())
                intent_map = {d["i"]: d.get("intent", "") for d in intent_data if isinstance(d, dict)}
                for i, c in enumerate(candidates[:30]):
                    c["intent"] = intent_map.get(i + 1, "")
        except Exception:
            pass  # Intent tagging is best-effort; silently skip if LLM unavailable

    # Check which keywords already exist in DB for this project
    db = _db()
    try:
        existing = db.query(Keyword.keyword).filter(
            Keyword.project_id == (project_id or None)
        ).all()
        existing_set = {row.keyword.strip().lower() for row in existing}
        for c in candidates:
            c["exists"] = c["keyword"].strip().lower() in existing_set
    finally:
        db.close()

    return JSONResponse({
        "topic": topic,
        "candidates": candidates[:30],
        "error": error_msg,
        "total": len(candidates),
    })


@admin_app.post("/keywords/bulk-import")
async def bulk_import_keywords(request: Request):
    """批次匯入使用者勾選的關鍵字候選。"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    body = await request.json()
    keywords_data = body.get("keywords", [])
    project_id = body.get("project_id", 0) or None

    db = _db()
    imported = 0
    try:
        for kw_item in keywords_data:
            text = (kw_item.get("keyword") or "").strip()
            if not text:
                continue
            # Skip duplicates
            existing = db.query(Keyword).filter(
                Keyword.project_id == project_id,
                Keyword.keyword == text
            ).first()
            if existing:
                continue
            db.add(Keyword(
                project_id=project_id,
                keyword=text,
                intent=kw_item.get("intent") or "",
                funnel_stage="",
                search_volume=0,
                seo_difficulty=0,
                steve_note=f"來源：{kw_item.get('source', 'AI 挖掘')}",
            ))
            imported += 1
        db.commit()
    finally:
        db.close()
    return JSONResponse({"imported": imported})


@admin_app.post("/keywords/enrich-trends", response_class=JSONResponse)
async def enrich_keywords_trends(request: Request):
    """
    為目前專案所有 trends_score 為 null 的關鍵字補充 Google Trends 相對熱度。
    每個關鍵字消耗 1 次 SerpAPI 額度。
    """
    if not _check_login(request):
        return JSONResponse({"error": "未登入"}, status_code=403)

    body = await request.json()
    project_id = body.get("project_id") or None
    kw_ids = body.get("kw_ids") or []  # 若為空則對所有未補充的關鍵字操作

    from contentflow.tools.serp import fetch_trends
    import asyncio

    db = _db()
    try:
        query = db.query(Keyword)
        if project_id:
            query = query.filter(Keyword.project_id == project_id)
        if kw_ids:
            query = query.filter(Keyword.id.in_(kw_ids))
        else:
            query = query.filter(Keyword.trends_score == None)  # noqa: E711
        keywords = query.all()
    finally:
        db.close()

    if not keywords:
        return JSONResponse({"enriched": 0, "skipped": 0, "details": []})

    results = []
    enriched_count = 0
    for kw in keywords:
        try:
            trend = await fetch_trends(kw.keyword)
            db2 = _db()
            try:
                obj = db2.query(Keyword).filter(Keyword.id == kw.id).first()
                if obj:
                    obj.trends_score = trend["score"]
                    obj.trend_direction = trend["direction"]
                    db2.commit()
                    enriched_count += 1
                    results.append({
                        "id": kw.id,
                        "keyword": kw.keyword,
                        "score": trend["score"],
                        "direction": trend["direction"],
                    })
            finally:
                db2.close()
            await asyncio.sleep(0.3)  # 避免 API rate limit
        except Exception as exc:
            results.append({"id": kw.id, "keyword": kw.keyword, "error": str(exc)})

    return JSONResponse({"enriched": enriched_count, "skipped": len(keywords) - enriched_count, "details": results})


@admin_app.post("/keywords/enrich-volume", response_class=JSONResponse)
async def enrich_keywords_volume(request: Request):
    """
    使用 DataForSEO 批次補充月搜尋量與競爭指數（search_volume / seo_difficulty）。
    """
    if not _check_login(request):
        return JSONResponse({"error": "未登入"}, status_code=403)

    body = await request.json()
    project_id = body.get("project_id") or None
    force = body.get("force", False)  # True 則覆蓋已有數據

    from contentflow.tools.serp import fetch_search_volume

    db = _db()
    try:
        query = db.query(Keyword)
        if project_id:
            query = query.filter(Keyword.project_id == project_id)
        if not force:
            query = query.filter(Keyword.search_volume == 0)
        keywords = query.all()
    finally:
        db.close()

    if not keywords:
        return JSONResponse({"enriched": 0, "skipped": 0, "details": []})

    kw_texts = [kw.keyword for kw in keywords]
    try:
        volume_map = await fetch_search_volume(kw_texts)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    enriched_count = 0
    details = []
    for kw in keywords:
        data = volume_map.get(kw.keyword, {})
        vol = data.get("search_volume")
        comp = data.get("competition_index")
        cpc = data.get("cpc")
        if vol is not None or comp is not None:
            db2 = _db()
            try:
                obj = db2.query(Keyword).filter(Keyword.id == kw.id).first()
                if obj:
                    if vol is not None:
                        obj.search_volume = vol
                    if comp is not None:
                        obj.seo_difficulty = comp
                    if cpc is not None:
                        obj.cpc = cpc
                    db2.commit()
                    enriched_count += 1
                    details.append({"id": kw.id, "keyword": kw.keyword, "volume": vol, "comp": comp})
            finally:
                db2.close()
        else:
            details.append({"id": kw.id, "keyword": kw.keyword, "volume": None, "comp": None})

    return JSONResponse({"enriched": enriched_count, "skipped": len(keywords) - enriched_count, "details": details})


# ═══════════════════════════════════════════════════════════════
# TOPIC CLUSTERS  /clusters
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/clusters", response_class=HTMLResponse)
async def clusters_page(request: Request):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        topic_clusters = db.query(TopicCluster).order_by(desc(TopicCluster.updated_at)).all()
        clusters = []
        for c in topic_clusters:
            members_orm = db.query(ClusterMember).filter(ClusterMember.cluster_id == c.id).all()
            # Enrich each member with article data
            enriched_members = []
            pub_cnt = rev_cnt = wri_cnt = res_cnt = 0
            for m in members_orm:
                art = db.query(Article).filter(Article.id == m.article_id).first() if m.article_id else None
                st = art.status if art else "planned"
                if st == "published": pub_cnt += 1
                elif st == "reviewing": rev_cnt += 1
                elif st == "writing": wri_cnt += 1
                elif st == "researching": res_cnt += 1
                enriched_members.append({
                    "article_id": m.article_id,
                    "article_title": art.title if art else m.keyword,
                    "article_status": st,
                    "article_seo_score": art.seo_score if art else None,
                    "keyword": m.keyword,
                    "link_to_pillar": m.link_to_pillar,
                })
            clusters.append({
                "id": c.id,
                "pillar_topic": c.pillar_keyword,     # model field is pillar_keyword
                "description": c.pillar_title or "",   # use pillar_title as description
                "status": c.status,
                "updated_at": c.updated_at,
                "member_count": len(members_orm),
                "published_count": pub_cnt,
                "reviewing_count": rev_cnt,
                "writing_count": wri_cnt,
                "members": enriched_members,
            })

        return templates.TemplateResponse(request, "clusters.html", {
            "request": request, "page": "clusters",
            "clusters": clusters,
            "total_clusters": len(topic_clusters),
            "total_members": sum(c["member_count"] for c in clusters),
            "completed_clusters": sum(1 for c in topic_clusters if c.status == "complete"),
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.post("/clusters/new")
async def create_cluster(
    request: Request,
    project_id: int = Form(0),
    pillar_keyword: str = Form(...),
    pillar_title: str = Form(""),
    satellite_keywords: str = Form(""),
):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        cluster = TopicCluster(
            project_id=project_id or None,
            pillar_keyword=pillar_keyword.strip(),
            pillar_title=pillar_title.strip(),
            status="building",
        )
        db.add(cluster)
        db.flush()
        # Add satellite keywords as ClusterMembers
        for kw in [k.strip() for k in satellite_keywords.split("\n") if k.strip()]:
            db.add(ClusterMember(cluster_id=cluster.id, keyword=kw))
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin/clusters", status_code=303)


@admin_app.post("/clusters/{cluster_id}/delete")
async def delete_cluster(request: Request, cluster_id: int):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        # Delete members first
        db.query(ClusterMember).filter(ClusterMember.cluster_id == cluster_id).delete()
        cluster = db.query(TopicCluster).filter(TopicCluster.id == cluster_id).first()
        if cluster:
            db.delete(cluster)
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/admin/clusters", status_code=303)


# ═══════════════════════════════════════════════════════════════
# SEO PERFORMANCE  /seo
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/seo", response_class=HTMLResponse)
async def seo_page(request: Request, days: int = 30):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        existing_ranking_cols = {
            col["name"] for col in inspect(db.get_bind()).get_columns(SEORanking.__tablename__)
        }
        has_clicks = "clicks" in existing_ranking_cols
        has_impressions = "impressions" in existing_ranking_cols
        has_ctr = "ctr" in existing_ranking_cols

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()

        daily_selects = [
            SEORanking.tracked_date,
            func.avg(SEORanking.position).label("avg_pos"),
        ]
        if has_clicks:
            daily_selects.insert(1, func.sum(SEORanking.clicks).label("clicks"))
        else:
            daily_selects.insert(1, literal(0).label("clicks"))
        if has_impressions:
            daily_selects.insert(2, func.sum(SEORanking.impressions).label("impressions"))
        else:
            daily_selects.insert(2, literal(0).label("impressions"))

        daily = (
            db.query(*daily_selects)
            .filter(SEORanking.tracked_date >= cutoff)
            .group_by(SEORanking.tracked_date)
            .order_by(SEORanking.tracked_date)
            .all()
        )

        top_selects = [
            SEORanking.keyword,
            func.avg(SEORanking.position).label("avg_position"),
        ]
        if has_clicks:
            top_selects.append(func.sum(SEORanking.clicks).label("total_clicks"))
        else:
            top_selects.append(literal(0).label("total_clicks"))
        if has_impressions:
            top_selects.append(func.sum(SEORanking.impressions).label("total_impressions"))
        else:
            top_selects.append(literal(0).label("total_impressions"))
        if has_ctr:
            top_selects.append(func.avg(SEORanking.ctr).label("avg_ctr"))
        else:
            top_selects.append(literal(0).label("avg_ctr"))

        top_keywords = (
            db.query(*top_selects)
            .group_by(SEORanking.keyword)
            .order_by(desc("total_clicks"))
            .limit(20).all()
        )

        if has_impressions:
            opportunities_raw = (
                db.query(SEORanking)
                .filter(SEORanking.position >= 3, SEORanking.position <= 15, SEORanking.impressions > 0)
                .order_by(desc(SEORanking.impressions))
                .limit(15).all()
            )
            opportunity_kws = [SimpleNamespace(
                query=r.keyword, position=r.position or 0,
                impressions=r.impressions or 0, page=r.landing_page,
                clicks=(r.clicks or 0) if has_clicks else 0,
            ) for r in opportunities_raw]
        else:
            opportunity_kws = []

        # Recent individual GSC rows for the table
        gsc_selects = [
            SEORanking.keyword.label("keyword"),
            SEORanking.landing_page.label("landing_page"),
            SEORanking.tracked_date.label("tracked_date"),
            SEORanking.position.label("position"),
        ]
        gsc_selects.append(SEORanking.clicks.label("clicks") if has_clicks else literal(0).label("clicks"))
        gsc_selects.append(SEORanking.impressions.label("impressions") if has_impressions else literal(0).label("impressions"))
        gsc_selects.append(SEORanking.ctr.label("ctr") if has_ctr else literal(0).label("ctr"))

        gsc_raw = (
            db.query(*gsc_selects)
            .order_by(desc(SEORanking.tracked_date), desc(SEORanking.position))
            .limit(30).all()
        )
        gsc_data = [SimpleNamespace(
            query=r.keyword, page=r.landing_page, ctr=r.ctr or 0,
            position=r.position or 0, date=r.tracked_date,
            clicks=r.clicks or 0, impressions=r.impressions or 0,
        ) for r in gsc_raw]

        gsc_trend = json.dumps([{
            "date": str(d.tracked_date), "clicks": int(d.clicks or 0),
            "impressions": int(d.impressions or 0),
            "avg_pos": round(float(d.avg_pos), 1) if d.avg_pos else 0,
        } for d in daily])

        total_clicks_sum = (db.query(func.sum(SEORanking.clicks)).scalar() or 0) if has_clicks else 0
        total_impressions_sum = (db.query(func.sum(SEORanking.impressions)).scalar() or 0) if has_impressions else 0
        avg_pos_overall = db.query(func.avg(SEORanking.position)).scalar() or 0
        avg_ctr_overall = (db.query(func.avg(SEORanking.ctr)).scalar() or 0) if has_ctr else 0

        # ── A-F 等級分布 ───────────────────────────────────────────
        # 取最近一筆各 keyword 的 position + ctr
        latest_subq = (
            db.query(
                SEORanking.keyword,
                func.max(SEORanking.tracked_date).label("max_date"),
            )
            .group_by(SEORanking.keyword)
            .subquery()
        )
        latest_cols = [SEORanking.keyword, SEORanking.position]
        if has_ctr:
            latest_cols.append(SEORanking.ctr)
        else:
            latest_cols.append(literal(0).label("ctr"))
        latest_rows = (
            db.query(*latest_cols)
            .join(latest_subq, (SEORanking.keyword == latest_subq.c.keyword) & (SEORanking.tracked_date == latest_subq.c.max_date))
            .all()
        )
        grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        for row in latest_rows:
            pos = row.position or 99
            ctr = (row.ctr or 0)
            if pos <= 3 and ctr > 0.08:
                grade_counts["A"] += 1
            elif pos <= 10:
                grade_counts["B"] += 1
            elif pos <= 20:
                grade_counts["C"] += 1
            elif pos <= 50:
                grade_counts["D"] += 1
            else:
                grade_counts["F"] += 1

        # ── 7 日排名變化（top keywords）──────────────────────────
        cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).date()
        enhanced_keywords = []
        for kw in top_keywords:
            # 7 天前的排名
            prev_row = (
                db.query(SEORanking.position)
                .filter(SEORanking.keyword == kw.keyword, SEORanking.tracked_date <= cutoff_7d)
                .order_by(desc(SEORanking.tracked_date))
                .first()
            )
            prev_pos = float(prev_row[0]) if prev_row and prev_row[0] else None
            curr_pos = float(kw.avg_position) if kw.avg_position else None
            rank_delta = None
            if prev_pos and curr_pos:
                rank_delta = prev_pos - curr_pos  # 正 = 進步（排名數字變小）
            enhanced_keywords.append(SimpleNamespace(
                keyword=kw.keyword,
                total_clicks=kw.total_clicks,
                total_impressions=kw.total_impressions,
                avg_position=curr_pos,
                avg_ctr=kw.avg_ctr,
                rank_delta=rank_delta,
            ))

        # ── 自蝕警告 ──────────────────────────────────────────────
        from contentflow.models.database import KnowledgeEntry
        cannibal_alerts = (
            db.query(KnowledgeEntry)
            .filter(KnowledgeEntry.category == "cannibalization")
            .order_by(desc(KnowledgeEntry.created_at))
            .limit(5)
            .all()
        )

        # ── Refresh 待辦 ──────────────────────────────────────────
        refresh_queue = (
            db.query(KnowledgeEntry)
            .filter(KnowledgeEntry.category == "refresh_priority")
            .order_by(desc(KnowledgeEntry.evidence_count))
            .limit(8)
            .all()
        )

        # ── Index Coverage 最新一筆 ───────────────────────────────
        index_coverage_alerts = (
            db.query(KnowledgeEntry)
            .filter(KnowledgeEntry.category == "index_coverage")
            .order_by(desc(KnowledgeEntry.created_at))
            .limit(6)
            .all()
        )

        return templates.TemplateResponse(request, "seo.html", {
            "request": request, "page": "seo", "now": datetime.now(timezone.utc), "days": days,
            "top_keywords": enhanced_keywords, "opportunity_kws": opportunity_kws,
            "gsc_data": gsc_data, "gsc_trend": gsc_trend,
            "chart_labels":      json.dumps([str(d.tracked_date) if d.tracked_date else "" for d in daily]),
            "chart_clicks":      json.dumps([int(d.clicks or 0) for d in daily]),
            "chart_impressions": json.dumps([int(d.impressions or 0) for d in daily]),
            "chart_positions":   json.dumps([round(float(d.avg_pos), 1) if d.avg_pos else 0 for d in daily]),
            "total_records":     db.query(SEORanking).count(),
            "total_clicks":      total_clicks_sum,
            "total_impressions": total_impressions_sum,
            "avg_position":      round(float(avg_pos_overall), 1) if avg_pos_overall else 0,
            "avg_ctr":           round(float(avg_ctr_overall), 4),
            "grade_counts":      grade_counts,
            "grade_json":        json.dumps(grade_counts),
            "cannibal_alerts":   cannibal_alerts,
            "refresh_queue":     refresh_queue,
            "index_coverage_alerts": index_coverage_alerts,
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# COMPETITORS  /competitors
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/competitors", response_class=HTMLResponse)
async def competitors_page(request: Request, project_id: int = 0):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        projects    = db.query(Project).order_by(Project.name).all()
        if project_id == 0 and projects:
            project_id = projects[0].id

        competitors = db.query(Competitor).order_by(Competitor.brand_name).all()
        products    = db.query(Product).all()

        # CompetitorSnapshot history – last 30 days, grouped per competitor
        from datetime import date, timedelta
        snapshot_cutoff = date.today() - timedelta(days=30)
        snapshots_raw = (
            db.query(CompetitorSnapshot)
            .filter(
                CompetitorSnapshot.project_id == project_id,
                CompetitorSnapshot.tracked_date >= snapshot_cutoff,
            )
            .order_by(CompetitorSnapshot.competitor_id, CompetitorSnapshot.tracked_date)
            .all()
        )

        # Build per-competitor snapshot summary: {competitor_id: {keyword: [(date, pos), ...]}}
        from collections import defaultdict
        snap_by_comp: dict[int, dict] = defaultdict(lambda: defaultdict(list))
        for s in snapshots_raw:
            if s.competitor_id and s.keyword:
                snap_by_comp[s.competitor_id][s.keyword].append({
                    "date": s.tracked_date.isoformat() if s.tracked_date else None,
                    "pos": round(s.position, 1) if s.position else None,
                    "our": round(s.our_position, 1) if s.our_position else None,
                })

        # Flatten for template: per competitor, pick top-3 most-tracked keywords
        import json as _json
        snap_chart_data = {}
        for comp_id, kw_dict in snap_by_comp.items():
            top_kws = sorted(kw_dict.items(), key=lambda x: -len(x[1]))[:3]
            snap_chart_data[comp_id] = _json.dumps([
                {"kw": kw, "points": pts} for kw, pts in top_kws
            ])

        return templates.TemplateResponse(request, "competitors.html", {
            "request": request, "page": "competitors",
            "projects": projects, "project_id": project_id,
            "competitors": competitors, "products": products,
            "total": len(competitors),
            "snap_chart_data": snap_chart_data,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.post("/competitors/new")
async def create_competitor(
    request: Request,
    project_id: int = Form(0),
    brand_name: str = Form(...),
    website: str = Form(""),
    features: str = Form(""),
    sells_products: str = Form(""),
    recommendation: str = Form(""),
):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        db.add(Competitor(
            project_id=project_id or None,
            brand_name=brand_name.strip(),
            website=website.strip(),
            features=features.strip(),
            sells_products=sells_products.strip(),
            recommendation=recommendation.strip(),
        ))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(f"/admin/competitors?project_id={project_id}", status_code=303)


@admin_app.post("/competitors/{comp_id}/delete")
async def delete_competitor(request: Request, comp_id: int, project_id: int = Form(0)):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        comp = db.query(Competitor).filter(Competitor.id == comp_id).first()
        if comp:
            project_id = project_id or comp.project_id or 0
            db.delete(comp)
            db.commit()
    finally:
        db.close()
    return RedirectResponse(f"/admin/competitors?project_id={project_id}", status_code=303)


# ═══════════════════════════════════════════════════════════════
# AGENT PIPELINE  /agents
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/agents", response_class=HTMLResponse)
async def agents_page(request: Request, run_id: str = ""):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        _STEP_NAMES = {
            "research": "Research Agent", "strategy": "Strategy Agent",
            "writing": "Writing Agent", "seo_check": "SEO Check Agent",
            "seo_qa": "SEO QA", "factcheck": "FactCheck Agent",
            "budget_guard": "Budget Guard", "publish": "Publish Agent",
        }

        runs_raw = (
            db.query(
                AgentDecisionLog.run_id,
                AgentDecisionLog.article_id,
                func.min(AgentDecisionLog.created_at).label("started"),
                func.max(AgentDecisionLog.created_at).label("ended"),
                func.count(AgentDecisionLog.id).label("step_count"),
            )
            .group_by(AgentDecisionLog.run_id, AgentDecisionLog.article_id)
            .order_by(desc("started"))
            .limit(20).all()
        )

        cost_metrics = _get_agent_cost_metrics(db)
        run_costs = cost_metrics["run_costs"]
        runs = []
        for r in runs_raw:
            art = db.query(Article).filter(Article.id == r.article_id).first() if r.article_id else None
            steps_orm = (
                db.query(AgentDecisionLog)
                .filter(AgentDecisionLog.run_id == r.run_id)
                .order_by(AgentDecisionLog.created_at).all()
            )
            steps = [
                {
                    "agent_name": _STEP_NAMES.get(d.step, d.step),
                    "step": d.step,
                    "decision": d.decision,
                    "reasoning": d.reason,
                    "confidence": d.confidence,
                    "created_at": d.created_at,
                }
                for d in steps_orm
            ]
            over_budget = any("強制" in (d["decision"] or "") for d in steps if d["step"] == "budget_guard")
            last_step = steps[-1]["step"] if steps else ""
            is_complete = last_step in ("budget_guard", "factcheck", "publish")
            duration = None
            if r.started and r.ended and r.ended > r.started:
                dur = (r.ended - r.started).total_seconds()
                duration = f"{int(dur // 60)}m {int(dur % 60)}s"
            completed_step_names = [d["step"] for d in steps]

            runs.append({
                "run_id": r.run_id, "run_id_short": r.run_id[:8],
                "article_id": r.article_id,
                "article_title": (art.title[:50] if art else "—"),
                "article_status": art.status if art else "",
                "started_at": r.started, "ended": r.ended,
                "step_count": r.step_count, "duration": duration,
                "is_complete": is_complete,
                "over_budget": over_budget,
                "cost": run_costs.get(r.run_id),
                "completed_steps": completed_step_names,
                "steps": steps,
            })

        selected_run = next((r for r in runs if r["run_id"] == run_id), None) if run_id else None

        runnable = (
            db.query(Article)
            .filter(Article.status.in_(["planned", "researching", "writing", "reviewing"]))
            .order_by(desc(Article.updated_at)).limit(30).all()
        )

        # Step frequency
        recent_decisions = db.query(AgentDecisionLog).order_by(desc(AgentDecisionLog.created_at)).limit(200).all()
        step_counts = Counter(d.step for d in recent_decisions)
        confidence_counts = Counter(d.confidence for d in recent_decisions)

        total_runs = db.query(func.count(func.distinct(AgentDecisionLog.run_id))).scalar() or 0
        success_runs = sum(1 for r in runs if r["is_complete"])

        return templates.TemplateResponse(request, "agents.html", {
            "request": request, "page": "agents",
            "runs": runs, "selected_run": selected_run,
            "trigger_articles": runnable,
            "projects": db.query(Project).order_by(Project.id).all(),
            "run_id": run_id,
            "total_runs": total_runs,
            "success_runs": success_runs,
            "budget_exceeded": sum(1 for r in runs if r["over_budget"]),
            "total_cost": cost_metrics["total_cost"],
            "step_counts_json": json.dumps(dict(step_counts.most_common(8))),
            "confidence_counts": dict(confidence_counts),
            "PIPELINE_STEPS": [step for step, _, _ in PIPELINE_STEPS],
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
            "CONFIDENCE_LABELS": CONFIDENCE_LABELS, "CONFIDENCE_COLORS": CONFIDENCE_COLORS,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()



# ── In-memory pipeline run state ─────────────────────────────
_pipeline_runs: dict[str, dict] = {}  # run_id -> {status, article_id, log, started_at}


async def _background_pipeline(run_id: str, article_id: int, project_id: int | None) -> None:
    """在背景執行 orchestrator 並回寫 DB。"""
    from contentflow.agents.orchestrator import run_orchestrator
    from contentflow.models import ArticleStatus, ArticleTask

    _pipeline_runs[run_id] = {
        "status": "running", "article_id": article_id,
        "log": ["✅ Pipeline 啟動…"], "started_at": datetime.now(timezone.utc).isoformat()
    }

    db = _db()
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            _pipeline_runs[run_id]["status"] = "error"
            _pipeline_runs[run_id]["log"].append(f"❌ Article id={article_id} 不存在")
            return

        keyword = article.primary_keyword or article.title or "untitled"
        title = article.title or keyword
        article.status = "researching"
        db.commit()
    finally:
        db.close()

    _pipeline_runs[run_id]["log"].append(f"📖 開始研究：{title}")

    task = ArticleTask(
        task_id=run_id,
        title=title,
        keywords=[keyword],
    )

    try:
        result = await run_orchestrator(task, project_id=project_id, article_id=article_id)
        _pipeline_runs[run_id]["log"].append("✍️  草稿生成完成")

        db2 = _db()
        try:
            article2 = db2.query(Article).filter(Article.id == article_id).first()
            if article2:
                draft = result.draft
                if draft:
                    article2.draft_content = draft.content_markdown
                    article2.meta_title = draft.meta_title
                    article2.meta_description = draft.meta_description
                    article2.slug = draft.slug
                    article2.faq_schema_json = draft.faq_schema_json
                    article2.howto_schema_json = draft.howto_schema_json
                    article2.article_schema_json = draft.article_schema_json
                    article2.paa_questions_json = draft.paa_questions_json
                    article2.seo_score = draft.seo_score or None
                article2.status = result.status or "reviewing"
                article2.updated_at = datetime.now(timezone.utc)
                # ── 同步更新 ContentCalendar 狀態 ──
                _ARTICLE_TO_CAL_STATUS = {
                    "published": "published",
                    "review_required": "reviewing",
                    "reviewing": "reviewing",
                    "approved": "reviewing",
                    "failed": "planned",
                }
                cal_new_status = _ARTICLE_TO_CAL_STATUS.get(article2.status, "reviewing")
                cal_entry = db2.query(ContentCalendar).filter(ContentCalendar.article_id == article_id).first()
                if cal_entry:
                    cal_entry.status = cal_new_status
                db2.commit()
        finally:
            db2.close()

        _pipeline_runs[run_id]["status"] = "done"
        _pipeline_runs[run_id]["log"].append(f"🎉 完成！狀態：{result.status}")

    except Exception as exc:
        _pipeline_runs[run_id]["status"] = "error"
        _pipeline_runs[run_id]["log"].append(f"❌ 失敗：{exc}")
        db3 = _db()
        try:
            a3 = db3.query(Article).filter(Article.id == article_id).first()
            if a3:
                a3.status = "failed"
                db3.commit()
            cal3 = db3.query(ContentCalendar).filter(ContentCalendar.article_id == article_id).first()
            if cal3:
                cal3.status = "planned"
                db3.commit()
        finally:
            db3.close()


@admin_app.post("/agents/trigger")
async def trigger_agent(
    request: Request,
    background_tasks: BackgroundTasks,
    article_id: int = Form(0),
    project_id: int = Form(0),
    start_step: str = Form("research"),
):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    if not article_id:
        return RedirectResponse("/admin/agents?error=no_article", status_code=303)
    run_id = str(uuid.uuid4())
    background_tasks.add_task(
        _background_pipeline, run_id, article_id, project_id or None
    )
    return RedirectResponse(f"/admin/agents?run_id={run_id}&triggered={article_id}", status_code=303)


@admin_app.get("/agents/run-status/{run_id}")
async def run_status(request: Request, run_id: str):
    """輪詢 pipeline 執行狀態（JSON）"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    info = _pipeline_runs.get(run_id, {"status": "unknown", "log": []})
    return JSONResponse(info)



# ═══════════════════════════════════════════════════════════════
# KNOWLEDGE BASE  /knowledge
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request, cat: str = "", confidence: str = "", q: str = "", page: int = 1):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        query = db.query(KnowledgeEntry).order_by(desc(KnowledgeEntry.evidence_count), desc(KnowledgeEntry.updated_at))
        if cat:
            query = query.filter(KnowledgeEntry.category == cat)
        if confidence:
            query = query.filter(KnowledgeEntry.confidence_level == confidence)
        if q:
            query = query.filter(KnowledgeEntry.pattern.ilike(f"%{q}%"))
        all_entries = query.all()

        # Pagination
        per_page = 30
        total = len(all_entries)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        entries = all_entries[(page - 1) * per_page : page * per_page]

        all_cats = [r[0] for r in db.query(KnowledgeEntry.category).distinct().all() if r[0]]
        active = db.query(KnowledgeEntry).filter(KnowledgeEntry.is_active == True).count()
        override_count = db.query(KnowledgeAuditLog).filter(KnowledgeAuditLog.action == "override").count()

        cat_raw = db.query(KnowledgeEntry.category, func.count()).group_by(KnowledgeEntry.category).all()
        cat_counts = {c: n for c, n in cat_raw}

        recent_audits = db.query(KnowledgeAuditLog).order_by(desc(KnowledgeAuditLog.created_at)).limit(8).all()

        return templates.TemplateResponse(request, "knowledge.html", {
            "request": request, "page": "knowledge",
            "entries": entries, "cat_filter": cat, "filter_confidence": confidence, "q": q,
            "categories": all_cats,
            "total": total, "active_count": active,
            "override_count": override_count,
            "page": page, "total_pages": total_pages,
            "cat_counts_json": json.dumps({k: v for k, v in cat_counts.items() if k}),
            "recent_audits": recent_audits,
            "CONFIDENCE_LABELS": CONFIDENCE_LABELS, "CONFIDENCE_COLORS": CONFIDENCE_COLORS,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.post("/knowledge/{entry_id}/toggle")
async def toggle_knowledge(request: Request, entry_id: int):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
        if entry:
            entry.is_active = not entry.is_active
            entry.updated_at = datetime.now(timezone.utc)
            db.add(KnowledgeAuditLog(
                entry_id=entry_id,
                action="deactivate" if not entry.is_active else "reactivate",
                reason="Admin 手動操作", operator="human",
            ))
            db.commit()
        return RedirectResponse("/admin/knowledge", status_code=303)
    finally:
        db.close()


@admin_app.post("/knowledge/{entry_id}/adopt")
async def adopt_knowledge_as_writing_rule(request: Request, entry_id: int):
    """L1 學習閉環：將 KnowledgeEntry (pattern) 採納為 WritingRule。"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
        if not entry:
            raise HTTPException(status_code=404)
        # Check if a rule with identical content already exists
        existing = db.query(WritingRule).filter(
            WritingRule.project_id == entry.project_id,
            WritingRule.content == entry.pattern,
        ).first()
        if not existing:
            rule = WritingRule(
                project_id=entry.project_id,
                rule_type="style",
                name=entry.category or "知識庫採納",
                content=entry.pattern,
            )
            db.add(rule)
            db.add(KnowledgeAuditLog(
                entry_id=entry_id,
                action="adopted_as_rule",
                reason="Admin 採納為 WritingRule",
                operator="human",
            ))
            db.commit()
        return RedirectResponse("/admin/knowledge", status_code=303)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# SCHEDULER  /scheduler
# ═══════════════════════════════════════════════════════════════

@admin_app.post("/scheduler/trigger/{job_id}")
async def trigger_scheduler_job(request: Request, job_id: str):
    """手動觸發排程任務（僅限已知 job）"""
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    job_map = get_scheduler_job_map()
    fn = job_map.get(job_id)
    if not fn:
        return RedirectResponse("/admin/scheduler?error=unknown_job", status_code=303)
    try:
        await fn()
        return RedirectResponse(f"/admin/scheduler?triggered={job_id}", status_code=303)
    except Exception as e:
        logger.error(f"[Scheduler] Manual trigger {job_id} failed: {e}")
        return RedirectResponse(f"/admin/scheduler?error={job_id}", status_code=303)


@admin_app.get("/scheduler", response_class=HTMLResponse)
async def scheduler_page(request: Request):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        logs = db.query(SchedulerLog).order_by(desc(SchedulerLog.started_at)).limit(50).all()

        job_latest: dict = {}
        for log in logs:
            if log.job_id not in job_latest:
                job_latest[log.job_id] = log

        known_jobs = get_known_scheduler_jobs()
        for j in known_jobs:
            j["latest"] = job_latest.get(j["id"])

        success_c = db.query(SchedulerLog).filter(SchedulerLog.status == "success").count()
        fail_c    = db.query(SchedulerLog).filter(SchedulerLog.status == "failed").count()

        cutoff7 = datetime.now(timezone.utc) - timedelta(days=7)
        logs7 = db.query(SchedulerLog).filter(SchedulerLog.started_at >= cutoff7).all()
        daily_stats: dict = {}
        for log in logs7:
            day = log.started_at.strftime("%m/%d")
            if day not in daily_stats:
                daily_stats[day] = {"success": 0, "failed": 0}
            daily_stats[day][log.status] = daily_stats[day].get(log.status, 0) + 1

        return templates.TemplateResponse(request, "scheduler.html", {
            "request": request, "page": "scheduler",
            "logs": logs, "known_jobs": known_jobs,
            "success_count": success_c, "fail_count": fail_c,
            "total_count": db.query(SchedulerLog).count(),
            "daily_stats": json.dumps(daily_stats),
            "scheduler_enabled": settings.scheduler_enabled,
            "SCHEDULER_TIMEZONE": settings.scheduler_timezone,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# SYSTEM HEALTH  /health
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        def _svc(name, ok, model="", description="", latency_ms=None):
            return SimpleNamespace(name=name, ok=ok, model=model, description=description, latency_ms=latency_ms)

        api_groups = {
            "ai": [
                _svc("OpenAI",    bool(settings.openai_api_key),    model=getattr(settings, "llm_lite_model", ""),     description="Research + SEO QA + FactCheck"),
                _svc("Anthropic", bool(settings.anthropic_api_key), model=getattr(settings, "llm_writing_model", ""),  description="Writing Agent（主力寫作）"),
            ],
            "data": [
                _svc("SerpAPI / Serper", bool(getattr(settings, "serper_api_key", None) or getattr(settings, "serpapi_key", None)), description="SERP 分析 + 競品追蹤"),
                _svc("Google Search Console", bool(
                    getattr(settings, "google_service_account_file", None) and
                    __import__("os").path.isfile(getattr(settings, "google_service_account_file", ""))
                ), description="每日 GSC 排名同步"),
                _svc("PubMed / NCBI", bool(getattr(settings, "ncbi_api_key", None)), description="Research Agent 學術佐證"),
            ],
            "publish": [
                _svc("WordPress", bool(getattr(settings, "wordpress_site_url", None)), description="文章自動發布"),
                _svc("ForgeBase", bool(getattr(settings, "forgebase_api_base_url", None)), description="ForgeBase 發布後端"),
            ],
            "notify": [
                _svc("Slack Webhook", bool(getattr(settings, "slack_webhook_url", None)), description="排程失敗通知"),
            ],
        }
        all_svcs = [s for grp in api_groups.values() for s in grp]
        ok_count = sum(1 for s in all_svcs if s.ok)
        total_services = len(all_svcs)
        all_ok = ok_count == total_services
        error_count = total_services - ok_count

        db_stats = [
            SimpleNamespace(table="articles",        count=db.query(Article).count()),
            SimpleNamespace(table="keywords",         count=db.query(Keyword).count()),
            SimpleNamespace(table="seo_rankings",     count=db.query(SEORanking).count()),
            SimpleNamespace(table="agent_decisions",  count=db.query(AgentDecisionLog).count()),
            SimpleNamespace(table="knowledge_entries",count=db.query(KnowledgeEntry).count()),
            SimpleNamespace(table="scheduler_logs",   count=db.query(SchedulerLog).count()),
            SimpleNamespace(table="topic_clusters",   count=db.query(TopicCluster).count()),
            SimpleNamespace(table="projects",         count=db.query(Project).count()),
        ]

        total_runs = db.query(func.count(func.distinct(AgentDecisionLog.run_id))).scalar() or 0
        monthly_runs = db.query(func.count(func.distinct(AgentDecisionLog.run_id))).filter(
            AgentDecisionLog.created_at >= datetime.now(timezone.utc) - timedelta(days=30)
        ).scalar() or 0
        cost_metrics = _get_agent_cost_metrics(db)
        avg_article_cost = cost_metrics["avg_run_cost"]
        month_cost = cost_metrics["monthly_cost"]
        total_cost = cost_metrics["total_cost"]
        operations_health = _build_operations_health(db)
        recent_health_snapshots = (
            db.query(OperationsHealthSnapshot)
            .order_by(desc(OperationsHealthSnapshot.snapshot_date), desc(OperationsHealthSnapshot.created_at))
            .limit(7)
            .all()
        )

        recent_errors = db.query(SchedulerLog).filter(SchedulerLog.status == "failed").order_by(desc(SchedulerLog.started_at)).limit(5).all()

        db_display = settings.database_url
        if "@" in db_display:
            db_display = db_display.split("@")[-1]

        return templates.TemplateResponse(request, "health.html", {
            "request": request, "page": "health",
            "api_groups": api_groups, "all_ok": all_ok,
            "ok_count": ok_count, "error_count": error_count, "total_services": total_services,
            "db_stats": db_stats, "total_rows": sum(s.count for s in db_stats),
            "recent_errors": recent_errors,
            "total_pipeline_runs": total_runs, "monthly_runs": monthly_runs,
            "avg_article_cost": avg_article_cost,
            "month_cost": month_cost, "total_cost": total_cost,
            "operations_health": operations_health,
            "recent_health_snapshots": recent_health_snapshots,
            "scheduler_enabled": settings.scheduler_enabled,
            "database_url": db_display,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# AUTHORS  /authors
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/authors", response_class=HTMLResponse)
async def authors_page(request: Request, project_id: int = 0):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        projects = db.query(Project).order_by(Project.name).all()
        if project_id == 0 and projects:
            project_id = projects[0].id

        authors = (
            db.query(Author)
            .filter(Author.project_id == project_id)
            .order_by(Author.name)
            .all()
        ) if project_id else []

        # Article count per author
        from sqlalchemy import func as _func
        art_counts = {}
        if project_id:
            rows = (
                db.query(Article.author_id, _func.count(Article.id).label("cnt"))
                .filter(Article.project_id == project_id, Article.author_id.isnot(None))
                .group_by(Article.author_id)
                .all()
            )
            art_counts = {r.author_id: r.cnt for r in rows}

        return templates.TemplateResponse(request, "authors.html", {
            "request": request, "page": "authors",
            "projects": projects, "project_id": project_id,
            "authors": authors, "art_counts": art_counts,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.post("/authors/new", response_class=HTMLResponse)
async def create_author(
    request: Request,
    project_id: int = Form(...),
    name: str = Form(...),
    title: str = Form(""),
    bio: str = Form(""),
    credentials: str = Form(""),
    profile_url: str = Form(""),
    is_medical_reviewer: bool = Form(False),
    reviewer_role: str = Form(""),
):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        reviewer_role_value = reviewer_role.strip().lower()
        if reviewer_role_value not in {"", "general", "medical", "legal", "financial"}:
            reviewer_role_value = ""
        author = Author(
            project_id=project_id,
            name=name.strip(),
            title=title.strip(),
            bio=bio.strip(),
            credentials=credentials.strip(),
            profile_url=profile_url.strip(),
            is_medical_reviewer=is_medical_reviewer or reviewer_role_value == "medical",
            reviewer_role=reviewer_role_value or None,
        )
        db.add(author)
        db.commit()
        return RedirectResponse(f"/admin/authors?project_id={project_id}", status_code=303)
    finally:
        db.close()


@admin_app.post("/authors/{author_id}/delete")
async def delete_author(request: Request, author_id: int):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        author = db.query(Author).filter(Author.id == author_id).first()
        project_id = author.project_id if author else 0
        if author:
            db.delete(author)
            db.commit()
        return RedirectResponse(f"/admin/authors?project_id={project_id}", status_code=303)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# CONTENT HEALTH  /content-health
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/content-health", response_class=HTMLResponse)
async def content_health_page(request: Request, project_id: int = 0):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        from contentflow.agents.analytics_agent import CannibalizationDetector, RefreshTriggerChecker

        projects = db.query(Project).order_by(Project.name).all()
        if project_id == 0 and projects:
            project_id = projects[0].id

        cannibal_pairs = []
        refresh_recs = []
        refresh_queue_items = []
        stale_articles = []

        if project_id:
            try:
                cannibal = CannibalizationDetector(db)
                cannibal_pairs = cannibal.detect(project_id)
            except Exception as e:
                logger.warning(f"[ContentHealth] Cannibalization detect error: {e}")

            try:
                checker = RefreshTriggerChecker(db)
                refresh_recs = checker.check_project(project_id)
            except Exception as e:
                logger.warning(f"[ContentHealth] RefreshTrigger error: {e}")

            # 知識庫中的 refresh_priority 待辦
            refresh_queue_items = (
                db.query(KnowledgeEntry)
                .filter(KnowledgeEntry.project_id == project_id, KnowledgeEntry.category == "refresh_priority")
                .order_by(desc(KnowledgeEntry.evidence_count))
                .limit(20)
                .all()
            )

            # 超過 6 個月未更新的已發布文章
            from datetime import date, timedelta
            stale_cutoff = datetime.now(timezone.utc) - timedelta(days=180)
            stale_articles = (
                db.query(Article)
                .filter(
                    Article.project_id == project_id,
                    Article.status == "published",
                    Article.updated_at < stale_cutoff,
                )
                .order_by(Article.updated_at)
                .limit(20)
                .all()
            )

        return templates.TemplateResponse(request, "content_health.html", {
            "request": request, "page": "content-health",
            "projects": projects, "project_id": project_id,
            "cannibal_pairs": cannibal_pairs,
            "refresh_recs": refresh_recs,
            "refresh_queue_items": refresh_queue_items,
            "stale_articles": stale_articles,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# TECH SEO  /tech-seo
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/tech-seo", response_class=HTMLResponse)
async def tech_seo_page(request: Request, project_id: int = 0):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        projects = db.query(Project).order_by(Project.name).all()
        if project_id == 0 and projects:
            project_id = projects[0].id

        tech_issues = []
        cwv_summary = {}
        ga_metrics = []

        if project_id:
            project = db.get(Project, project_id)
            # GA4 最新指標
            from datetime import date
            ga_metrics = (
                db.query(GAPageMetric)
                .filter(GAPageMetric.project_id == project_id)
                .order_by(desc(GAPageMetric.tracked_date), desc(GAPageMetric.sessions))
                .limit(20)
                .all()
            )

            # 嘗試呼叫 TechSEO checker
            if project and project.brand_url:
                try:
                    from contentflow.tools.tech_seo import (
                        CoreWebVitalsMonitor,
                        TechSEOHealthDashboard,
                    )
                    cwv_monitor = CoreWebVitalsMonitor()
                    cwv_data = await cwv_monitor.fetch(project.brand_url, strategy="mobile")

                    if not cwv_data.error:
                        cwv_summary = {
                            "lcp": f"{cwv_data.lcp:.2f}s" if cwv_data.lcp is not None else None,
                            "fid": f"{cwv_data.inp:.0f}ms" if cwv_data.inp is not None else None,
                            "cls": f"{cwv_data.cls:.3f}" if cwv_data.cls is not None else None,
                            "lcp_score": cwv_data.performance_score or "—",
                        }

                    dashboard = TechSEOHealthDashboard()
                    health = dashboard.calculate(cwv=cwv_data if not cwv_data.error else None)

                    for rec in health.recommendations:
                        tech_issues.append({
                            "severity": "warning",
                            "title": rec,
                            "description": "",
                            "affected_urls": [],
                        })
                except Exception as e:
                    logger.warning(f"[TechSEO] check error: {e}")

        # GSC 索引狀況
        from datetime import date
        cutoff_28 = (datetime.now(timezone.utc) - timedelta(days=28)).date()
        pages_indexed = (
            db.query(func.count(func.distinct(SEORanking.landing_page)))
            .filter(SEORanking.project_id == project_id, SEORanking.tracked_date >= cutoff_28)
            .scalar() or 0
        ) if project_id else 0

        return templates.TemplateResponse(request, "tech_seo.html", {
            "request": request, "page": "tech-seo",
            "projects": projects, "project_id": project_id,
            "tech_issues": tech_issues,
            "cwv_summary": cwv_summary,
            "ga_metrics": ga_metrics,
            "pages_indexed": pages_indexed,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# REPORTS CENTER  /reports
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, project_id: int = 0, period: str = "weekly"):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        projects = db.query(Project).order_by(Project.name).all()
        if project_id == 0 and projects:
            project_id = projects[0].id

        report_data = {}

        if project_id:
            from datetime import date, timedelta
            today = date.today()

            if period == "weekly":
                cutoff = today - timedelta(days=7)
            elif period == "monthly":
                cutoff = today - timedelta(days=30)
            else:  # quarterly
                cutoff = today - timedelta(days=90)

            # 文章統計
            articles_published = (
                db.query(Article)
                .filter(Article.project_id == project_id, Article.status == "published")
                .count()
            )
            articles_new_period = (
                db.query(Article)
                .filter(Article.project_id == project_id, Article.status == "published",
                        Article.updated_at >= datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=timezone.utc))
                .count()
            )

            # SEO 指標
            seo_metrics = db.query(
                func.sum(SEORanking.clicks).label("total_clicks"),
                func.sum(SEORanking.impressions).label("total_impressions"),
                func.avg(SEORanking.position).label("avg_position"),
                func.avg(SEORanking.ctr).label("avg_ctr"),
            ).filter(
                SEORanking.project_id == project_id,
                SEORanking.tracked_date >= cutoff,
            ).first()

            # 熱門文章（by clicks）
            top_articles = (
                db.query(
                    SEORanking.landing_page,
                    func.sum(SEORanking.clicks).label("total_clicks"),
                    func.sum(SEORanking.impressions).label("total_impressions"),
                    func.avg(SEORanking.position).label("avg_position"),
                )
                .filter(SEORanking.project_id == project_id, SEORanking.tracked_date >= cutoff)
                .group_by(SEORanking.landing_page)
                .order_by(desc("total_clicks"))
                .limit(10)
                .all()
            )

            # 知識庫摘要
            knowledge_count = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.project_id == project_id, KnowledgeEntry.is_active == True
            ).count()

            refresh_alerts = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.project_id == project_id, KnowledgeEntry.category == "refresh_priority"
            ).count()

            cannibal_alerts = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.project_id == project_id, KnowledgeEntry.category == "cannibalization"
            ).count()

            # ── CRO：GA4 轉換分析 ─────────────────────────────────
            ga_metrics = db.query(
                func.sum(GAPageMetric.sessions).label("total_sessions"),
                func.sum(GAPageMetric.active_users).label("total_users"),
                func.sum(GAPageMetric.conversions).label("total_conversions"),
                func.avg(GAPageMetric.bounce_rate).label("avg_bounce_rate"),
                func.avg(GAPageMetric.avg_engagement_time_sec).label("avg_engagement"),
            ).filter(
                GAPageMetric.project_id == project_id,
                GAPageMetric.tracked_date >= cutoff,
            ).first()

            # Top 轉換頁面
            top_conversion_pages = (
                db.query(
                    GAPageMetric.page_path,
                    func.sum(GAPageMetric.sessions).label("sessions"),
                    func.sum(GAPageMetric.conversions).label("conversions"),
                    func.avg(GAPageMetric.bounce_rate).label("bounce_rate"),
                )
                .filter(GAPageMetric.project_id == project_id, GAPageMetric.tracked_date >= cutoff)
                .group_by(GAPageMetric.page_path)
                .order_by(desc("conversions"))
                .limit(8)
                .all()
            )

            # ── 核心演算法更新：排名掉落偵測 ──────────────────────
            # 比對「本期」vs「前期」平均排名，找出掉落 >3 名的關鍵字
            from datetime import date as _date
            period_days = {"weekly": 7, "monthly": 30, "quarterly": 90}.get(period, 7)
            prior_cutoff = cutoff - timedelta(days=period_days)

            # 本期關鍵字平均排名
            curr_ranks = {
                row.keyword: row.avg_pos
                for row in db.query(
                    SEORanking.keyword,
                    func.avg(SEORanking.position).label("avg_pos"),
                ).filter(
                    SEORanking.project_id == project_id,
                    SEORanking.tracked_date >= cutoff,
                ).group_by(SEORanking.keyword).all()
            }

            # 前期關鍵字平均排名
            prev_ranks = {
                row.keyword: row.avg_pos
                for row in db.query(
                    SEORanking.keyword,
                    func.avg(SEORanking.position).label("avg_pos"),
                ).filter(
                    SEORanking.project_id == project_id,
                    SEORanking.tracked_date >= prior_cutoff,
                    SEORanking.tracked_date < cutoff,
                ).group_by(SEORanking.keyword).all()
            }

            ranking_drops = []
            for kw, curr_pos in curr_ranks.items():
                if kw in prev_ranks and curr_pos and prev_ranks[kw]:
                    delta = float(curr_pos) - float(prev_ranks[kw])  # 正數 = 排名退步
                    if delta >= 3:
                        ranking_drops.append({
                            "keyword": kw,
                            "prev_pos": round(float(prev_ranks[kw]), 1),
                            "curr_pos": round(float(curr_pos), 1),
                            "delta": round(delta, 1),
                        })
            ranking_drops.sort(key=lambda x: x["delta"], reverse=True)
            ranking_drops = ranking_drops[:10]  # top 10 drops

            report_data = {
                "period": period,
                "cutoff": cutoff,
                "articles_published": articles_published,
                "articles_new_period": articles_new_period,
                "total_clicks": int(seo_metrics.total_clicks or 0),
                "total_impressions": int(seo_metrics.total_impressions or 0),
                "avg_position": round(float(seo_metrics.avg_position or 0), 1),
                "avg_ctr": round(float(seo_metrics.avg_ctr or 0) * 100, 2),
                "top_articles": top_articles,
                "knowledge_count": knowledge_count,
                "refresh_alerts": refresh_alerts,
                "cannibal_alerts": cannibal_alerts,
                # CRO
                "total_sessions": int(ga_metrics.total_sessions or 0),
                "total_users": int(ga_metrics.total_users or 0),
                "total_conversions": int(ga_metrics.total_conversions or 0),
                "avg_bounce_rate": round(float(ga_metrics.avg_bounce_rate or 0) * 100, 1),
                "avg_engagement_sec": round(float(ga_metrics.avg_engagement or 0), 0),
                "top_conversion_pages": top_conversion_pages,
                "conversion_rate": round(
                    int(ga_metrics.total_conversions or 0) /
                    max(int(ga_metrics.total_sessions or 0), 1) * 100, 2
                ),
                # 排名掉落
                "ranking_drops": ranking_drops,
            }

            # ── 戰略計畫執行成效 ──────────────────────────────────
            cutoff_dt = datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=timezone.utc)
            strategic_plans = (
                db.query(StrategicPlan)
                .filter(
                    StrategicPlan.project_id == project_id,
                    StrategicPlan.plan_date >= cutoff,
                )
                .order_by(desc(StrategicPlan.plan_date))
                .all()
            )
            plan_ids = [p.id for p in strategic_plans]

            # Strategic Agent 觸發的 PipelineRun
            strategic_runs = []
            if plan_ids:
                strategic_runs = (
                    db.query(PipelineRun)
                    .filter(PipelineRun.strategic_plan_id.in_(plan_ids))
                    .all()
                )
            # 也找 trigger="strategic_agent" 但沒有 plan_id 的歷史資料
            legacy_runs = (
                db.query(PipelineRun)
                .filter(
                    PipelineRun.project_id == project_id,
                    PipelineRun.trigger == "strategic_agent",
                    PipelineRun.started_at >= cutoff_dt,
                    PipelineRun.strategic_plan_id == None,
                )
                .all()
            )
            all_strategic_runs = strategic_runs + legacy_runs
            # 去重
            seen_ids = set()
            unique_runs = []
            for r in all_strategic_runs:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    unique_runs.append(r)
            all_strategic_runs = unique_runs

            sp_total = len(strategic_plans)
            sp_completed = sum(1 for p in strategic_plans if p.status == "completed")
            sp_actions_total = sum(p.total_count for p in strategic_plans)
            sp_actions_executed = sum(p.executed_count for p in strategic_plans)
            sp_runs_ok = sum(1 for r in all_strategic_runs if r.status == "completed")
            sp_runs_fail = sum(1 for r in all_strategic_runs if r.status == "failed")

            # 取得 strategic runs 對應的文章標題與 SEO score
            sp_run_details = []
            for r in all_strategic_runs:
                art = db.get(Article, r.article_id) if r.article_id else None
                sp_run_details.append({
                    "run_id": r.run_id[:8],
                    "article_title": art.title if art else "—",
                    "article_id": r.article_id,
                    "status": r.status,
                    "seo_score": r.seo_score,
                    "cost": round(r.total_cost or 0, 3),
                    "started_at": r.started_at,
                    "finished_at": r.finished_at,
                })

            report_data["strategic"] = {
                "plans_total": sp_total,
                "plans_completed": sp_completed,
                "actions_total": sp_actions_total,
                "actions_executed": sp_actions_executed,
                "runs_ok": sp_runs_ok,
                "runs_fail": sp_runs_fail,
                "run_details": sp_run_details,
            }

        return templates.TemplateResponse(request, "reports.html", {
            "request": request, "page": "reports",
            "projects": projects, "project_id": project_id,
            "period": period,
            "report_data": report_data,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# SETTINGS  /settings
# ═══════════════════════════════════════════════════════════════

@admin_app.post("/settings/auto-publish/save")
async def save_auto_publish(
    request: Request,
    project_id: int = Form(...),
    auto_publish_enabled: str = Form("off"),
    auto_publish_min_score: int = Form(85),
):
    _require_role(request, "owner")
    db = _db()
    try:
        proj = db.query(Project).filter(Project.id == project_id).first()
        if not proj:
            raise HTTPException(status_code=404)
        proj.auto_publish_enabled = (auto_publish_enabled == "on")
        proj.auto_publish_min_score = max(0, min(100, auto_publish_min_score))
        proj.updated_at = datetime.now(timezone.utc)
        db.commit()
        return RedirectResponse(
            f"/admin/settings?project_id={project_id}&saved=1#auto-publish",
            status_code=303,
        )
    finally:
        db.close()


@admin_app.post("/settings/project/save")
async def save_project(
    request: Request,
    project_id: int = Form(0),
    slug: str = Form(...),
    name: str = Form(...),
    brand_name: str = Form(""),
    brand_url: str = Form(""),
    brand_description: str = Form(""),
    site_contact_email: str = Form(""),
    site_blog_path: str = Form("/blog"),
    industry: str = Form(""),
    writing_principles: str = Form(""),
    domain_profile: str = Form(""),
    compliance_profile: str = Form(""),
    default_content_format: str = Form(""),
    reviewer_role_label: str = Form(""),
    disclaimer_template: str = Form(""),
    evidence_policy: str = Form(""),
    image_style_override: str = Form(""),
    extra_schema_types_json: str = Form(""),
    factcheck_mode_override: str = Form(""),
    serp_gl: str = Form("tw"),
    serp_hl: str = Form("zh-tw"),
    business_goals: str = Form(""),
    target_audience: str = Form(""),
    ga4_property_id: str = Form(""),
):
    role = _require_role(request, "owner")
    db = _db()
    try:
        import json as _json
        now = datetime.now(timezone.utc)
        # Parse target_audience as JSON if it's a valid JSON string, otherwise store as plain text
        try:
            ta_json = _json.loads(target_audience) if target_audience.strip().startswith("{") else {"description": target_audience}
        except Exception:
            ta_json = {"description": target_audience}

        if project_id:
            proj = db.query(Project).filter(Project.id == project_id).first()
            if proj:
                proj.name = name; proj.slug = slug
                proj.brand_name = brand_name; proj.brand_url = brand_url
                proj.brand_description = brand_description; proj.industry = industry
                proj.site_contact_email = site_contact_email
                proj.site_blog_path = site_blog_path or "/blog"
                proj.writing_principles = writing_principles
                proj.domain_profile = domain_profile if domain_profile in SUPPORTED_DOMAIN_PROFILES else None
                proj.compliance_profile = compliance_profile if compliance_profile in SUPPORTED_COMPLIANCE_PROFILES else None
                proj.default_content_format = default_content_format if default_content_format in SUPPORTED_CONTENT_FORMAT_PROFILES else None
                proj.reviewer_role_label = reviewer_role_label or None
                proj.disclaimer_template = disclaimer_template or None
                proj.evidence_policy = evidence_policy or None
                proj.image_style_override = image_style_override or None
                proj.extra_schema_types_json = _normalize_schema_types_input(extra_schema_types_json)
                proj.factcheck_mode_override = factcheck_mode_override or None
                proj.serp_gl = serp_gl; proj.serp_hl = serp_hl
                proj.business_goals = business_goals or None
                proj.target_audience_json = _json.dumps(ta_json, ensure_ascii=False) if target_audience else None
                proj.ga4_property_id = ga4_property_id or None
                proj.updated_at = now
                _append_project_audit(
                    db,
                    project_id=proj.id,
                    action_type="project_profile_updated",
                    summary=f"更新專案設定：{proj.name}",
                    payload={
                        "slug": proj.slug,
                        "brand_url": proj.brand_url,
                        "site_contact_email": proj.site_contact_email,
                        "site_blog_path": proj.site_blog_path,
                        "domain_profile": proj.domain_profile,
                        "compliance_profile": proj.compliance_profile,
                        "default_content_format": proj.default_content_format,
                    },
                    actor=role,
                )
                db.commit()
                return RedirectResponse(f"/admin/settings?project_id={proj.id}&saved=1", status_code=303)
            raise HTTPException(status_code=404)
        else:
            proj = Project(
                slug=slug, name=name,
                brand_name=brand_name, brand_url=brand_url,
                brand_description=brand_description, industry=industry,
                site_contact_email=site_contact_email,
                site_blog_path=site_blog_path or "/blog",
                writing_principles=writing_principles,
                domain_profile=domain_profile if domain_profile in SUPPORTED_DOMAIN_PROFILES else None,
                compliance_profile=compliance_profile if compliance_profile in SUPPORTED_COMPLIANCE_PROFILES else None,
                default_content_format=default_content_format if default_content_format in SUPPORTED_CONTENT_FORMAT_PROFILES else None,
                reviewer_role_label=reviewer_role_label or None,
                disclaimer_template=disclaimer_template or None,
                evidence_policy=evidence_policy or None,
                image_style_override=image_style_override or None,
                extra_schema_types_json=_normalize_schema_types_input(extra_schema_types_json),
                factcheck_mode_override=factcheck_mode_override or None,
                serp_gl=serp_gl, serp_hl=serp_hl,
                locale="zh-tw",
                business_goals=business_goals or None,
                target_audience_json=_json.dumps(ta_json, ensure_ascii=False) if target_audience else None,
                ga4_property_id=ga4_property_id or None,
                created_at=now, updated_at=now,
            )
            db.add(proj)
            db.flush()
            _append_project_audit(
                db,
                project_id=proj.id,
                action_type="project_created",
                summary=f"建立專案：{proj.name}",
                payload={"slug": proj.slug, "brand_url": proj.brand_url},
                actor=role,
            )
            db.commit(); db.refresh(proj)
            return RedirectResponse(f"/admin/settings?project_id={proj.id}&saved=1#policy-wizard", status_code=303)
    finally:
        db.close()


@admin_app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, project_id: int = 0):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    session_role = _get_session_role(request)
    db = _db()
    try:
        projects = db.query(Project).order_by(Project.name).all()
        if project_id == 0 and projects:
            project_id = projects[0].id

        current_project = None
        rules_by_type: dict = {}
        strategy_by_section: dict = {}
        products = []
        legal_by_type: dict = {}
        integrations_by_type: dict[str, ProjectIntegration] = {}

        if project_id:
            current_project = db.query(Project).filter(Project.id == project_id).first()
            rules = db.query(WritingRule).filter(WritingRule.project_id == project_id).order_by(WritingRule.order_num).all()
            for r in rules:
                rules_by_type.setdefault(r.rule_type or "其他", []).append(r)
            strats = db.query(ContentStrategy).filter(ContentStrategy.project_id == project_id).order_by(ContentStrategy.order_num).all()
            for s in strats:
                strategy_by_section.setdefault(s.section or "其他", []).append(s)
            products = db.query(Product).filter(Product.project_id == project_id).all()
            legal = db.query(LegalTerm).filter(LegalTerm.project_id == project_id).all()
            for lt in legal:
                legal_by_type.setdefault(lt.term_type or "other", []).append(lt)
            integration_rows = (
                db.query(ProjectIntegration)
                .filter(ProjectIntegration.project_id == project_id)
                .order_by(ProjectIntegration.integration_type)
                .all()
            )
            integrations_by_type = {row.integration_type: row for row in integration_rows}

        wordpress_integration = resolve_wordpress_settings(db=db, project_id=project_id if current_project else None)
        forgebase_integration = resolve_forgebase_settings(db=db, project_id=project_id if current_project else None)
        onboarding_checklist = _build_onboarding_checklist(
            current_project,
            wordpress_integration=wordpress_integration,
            forgebase_integration=forgebase_integration,
        )
        onboarding_completed = sum(1 for item in onboarding_checklist if item.done)
        recent_project_audits = (
            db.query(ProjectAuditLog)
            .filter(ProjectAuditLog.project_id == project_id)
            .order_by(desc(ProjectAuditLog.created_at))
            .limit(8)
            .all()
        ) if current_project else []
        audit_view = _build_project_audit_view(recent_project_audits)

        goal_config = _goal_config_for_template(current_project.business_goals if current_project else "")
        goal_monthly_report = (
            _build_goal_weighted_monthly_report(db, project_id, goal_config)
            if project_id and current_project
            else {"window_days": 30, "plan_count": 0, "by_action": []}
        )
        usage_report = (
            _build_project_usage_report(db, project_id)
            if project_id and current_project
            else {"window_days": 30, "run_count": 0, "step_counts": [], "feedback_counts": {}, "total_cost": 0.0, "avg_cost": 0.0, "total_llm_calls": 0}
        )
        approval_history = (
            _build_project_approval_history(db, project_id)
            if project_id and current_project
            else {"window_days": 30, "entries": [], "by_status": {}, "total": 0}
        )
        integration_diagnostics = {
            integration_type: _load_json_object(row.config_json).get("last_diagnostic", {})
            for integration_type, row in integrations_by_type.items()
        }
        onboarding_wizard = _build_onboarding_wizard(
            current_project,
            wordpress_integration=wordpress_integration,
            forgebase_integration=forgebase_integration,
        )
        policy_onboarding_wizard = _build_policy_setup_wizard(current_project)
        connector_wizard = _build_connector_wizard(
            wordpress_integration=wordpress_integration,
            forgebase_integration=forgebase_integration,
            integration_diagnostics=integration_diagnostics,
        )
        policy_preview = {}
        policy_warnings: list[str] = []
        if current_project:
            policy_preview, policy_warnings = _build_policy_preview(current_project.id, db=db)

        return templates.TemplateResponse(request, "settings.html", {
            "request": request, "page": "settings",
            "projects": projects,
            "project": current_project,          # template expects 'project'
            "current_project": current_project,
            "project_id": project_id,
            "rules_by_type": rules_by_type, "strategy_by_section": strategy_by_section,
            "products": products, "legal_by_type": legal_by_type,
            "content_strategy": list(strategy_by_section.values()),
            "writing_rules": [r for rules in rules_by_type.values() for r in rules],
            "legal_terms": [lt for lts in legal_by_type.values() for lt in lts],
            "goal_config": goal_config,
            "goal_monthly_report": goal_monthly_report,
            "usage_report": usage_report,
            "approval_history": approval_history,
            "integrations_by_type": integrations_by_type,
            "wordpress_integration": wordpress_integration,
            "forgebase_integration": forgebase_integration,
            "integration_diagnostics": integration_diagnostics,
            "onboarding_checklist": onboarding_checklist,
            "onboarding_completed": onboarding_completed,
            "recent_project_audits": audit_view,
            "onboarding_wizard": onboarding_wizard,
            "policy_onboarding_wizard": policy_onboarding_wizard,
            "connector_wizard": connector_wizard,
            "policy_preview": policy_preview,
            "policy_warnings": policy_warnings,
            "domain_profiles": DOMAIN_PROFILES,
            "compliance_profiles": COMPLIANCE_PROFILES,
            "content_format_profiles": CONTENT_FORMAT_PROFILES,
            "platform_mode": settings.platform_mode,
            "managed_site_enabled": settings.managed_site_enabled,
            "session_role": session_role,
            "can_manage_settings": _has_role(request, "owner"),
            "can_review_actions": _has_role(request, "reviewer"),
            "can_view_advanced_overrides": _has_role(request, "reviewer"),
            "env_vars": _get_env_var_status(),
            "llm_writing_model": settings.llm_writing_model,
            "llm_lite_model": settings.llm_lite_model,
            "scheduler_enabled": settings.scheduler_enabled,
            "scheduler_timezone": settings.scheduler_timezone,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.post("/settings/project/integration/save")
async def save_project_integration(
    request: Request,
    project_id: int = Form(...),
    integration_type: str = Form(...),
    label: str = Form(""),
    base_url: str = Form(""),
    username: str = Form(""),
    secret_value: str = Form(""),
    seo_plugin: str = Form("yoast"),
    publish_mode: str = Form("publish"),
    is_enabled: str | None = Form(None),
):
    role = _require_role(request, "owner")
    db = _db()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404)

        row = _upsert_project_integration(
            db,
            project_id=project_id,
            integration_type=integration_type,
            label=label,
            base_url=base_url,
            username=username,
            secret_value=secret_value,
            seo_plugin=seo_plugin,
            publish_mode=publish_mode,
            is_enabled=bool(is_enabled),
        )
        _append_project_audit(
            db,
            project_id=project_id,
            action_type="integration_saved",
            summary=f"更新 {integration_type} connector",
            payload={
                "integration_type": integration_type,
                "base_url": row.base_url,
                "is_enabled": row.is_enabled,
                "publish_mode": row.publish_mode,
            },
            actor=role,
        )
        db.commit()
        return RedirectResponse(f"/admin/settings?project_id={project_id}&saved=1#integrations", status_code=303)
    finally:
        db.close()


@admin_app.post("/settings/project/integration/test")
async def test_project_integration(
    request: Request,
    project_id: int = Form(...),
    integration_type: str = Form(...),
):
    role = _require_role(request, "reviewer")
    db = _db()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404)

        row = (
            db.query(ProjectIntegration)
            .filter(
                ProjectIntegration.project_id == project_id,
                ProjectIntegration.integration_type == integration_type,
            )
            .first()
        )
        diagnostic = await run_integration_diagnostic(integration_type=integration_type, db=db, project_id=project_id)
        now = datetime.now(timezone.utc)
        if row is not None:
            config_data = _load_json_object(row.config_json)
            config_data["last_diagnostic"] = diagnostic.as_dict()
            row.config_json = json.dumps(config_data, ensure_ascii=False)
            row.health_status = diagnostic.status
            row.last_checked_at = now
            row.updated_at = now
        _append_project_audit(
            db,
            project_id=project_id,
            action_type="integration_tested",
            summary=f"測試 {integration_type} connector：{diagnostic.status}",
            payload=diagnostic.as_dict(),
            actor=role,
        )
        db.commit()
        return RedirectResponse(f"/admin/settings?project_id={project_id}&saved=1#integrations", status_code=303)
    finally:
        db.close()


@admin_app.post("/settings/project/goals/save")
async def save_project_goals(
    request: Request,
    project_id: int = Form(...),
    primary_goal: str = Form("awareness"),
    secondary_goal: str = Form("authority"),
    goal_awareness_weight: float = Form(0.3),
    goal_conversion_weight: float = Form(0.4),
    goal_lead_capture_weight: float = Form(0.15),
    goal_authority_weight: float = Form(0.15),
    priority_topics: str = Form(""),
    money_pages: str = Form(""),
):
    role = _require_role(request, "owner")
    db = _db()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404)

        config = {
            "primary_goal": primary_goal,
            "secondary_goal": secondary_goal,
            "weights": {
                "awareness": max(0.0, float(goal_awareness_weight or 0.0)),
                "conversion": max(0.0, float(goal_conversion_weight or 0.0)),
                "lead_capture": max(0.0, float(goal_lead_capture_weight or 0.0)),
                "authority": max(0.0, float(goal_authority_weight or 0.0)),
            },
            "priority_topics": [item.strip() for item in priority_topics.splitlines() if item.strip()],
            "money_pages": [item.strip() for item in money_pages.splitlines() if item.strip()],
        }
        project.business_goals = json.dumps(config, ensure_ascii=False)
        project.updated_at = datetime.now(timezone.utc)
        _append_project_audit(
            db,
            project_id=project_id,
            action_type="goal_model_saved",
            summary="更新 goal-weighted decision model",
            payload=config,
            actor=role,
        )
        db.commit()
        return RedirectResponse(f"/admin/settings?project_id={project_id}&saved=1#goal-weighted-model", status_code=303)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# AJAX  /api/*
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/api/stats")
async def api_stats(request: Request):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        return {
            "articles":        db.query(Article).count(),
            "published":       db.query(Article).filter(Article.status == "published").count(),
            "keywords":        db.query(Keyword).count(),
            "clusters":        db.query(TopicCluster).count(),
            "competitors":     db.query(Competitor).count(),
            "knowledge":       db.query(KnowledgeEntry).filter(KnowledgeEntry.is_active == True).count(),
            "scheduler_errors":db.query(SchedulerLog).filter(SchedulerLog.status == "failed").count(),
            "pipeline_runs":   db.query(func.count(func.distinct(AgentDecisionLog.run_id))).scalar() or 0,
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# PIPELINE RUNS  /pipeline-runs  (Enhanced B)
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/pipeline-runs", response_class=HTMLResponse)
async def pipeline_runs_page(request: Request, status: str = "", trigger: str = "", page: int = 1):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        q = db.query(PipelineRun).order_by(desc(PipelineRun.started_at))
        if status:
            q = q.filter(PipelineRun.status == status)
        if trigger:
            q = q.filter(PipelineRun.trigger == trigger)
        all_runs = q.all()

        per_page = 30
        total = len(all_runs)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        runs = all_runs[(page - 1) * per_page : page * per_page]

        # 統計
        total_runs  = db.query(PipelineRun).count()
        completed   = db.query(PipelineRun).filter(PipelineRun.status == "completed").count()
        failed      = db.query(PipelineRun).filter(PipelineRun.status == "failed").count()
        running_now = db.query(PipelineRun).filter(PipelineRun.status == "running").count()
        avg_seo     = db.query(func.avg(PipelineRun.seo_score)).filter(PipelineRun.seo_score != None).scalar()
        total_cost  = db.query(func.sum(PipelineRun.total_cost)).scalar() or 0.0

        # 取得 article titles
        article_ids = [r.article_id for r in runs if r.article_id]
        articles_by_id = {}
        if article_ids:
            for a in db.query(Article).filter(Article.id.in_(article_ids)).all():
                articles_by_id[a.id] = a.title

        return templates.TemplateResponse(request, "pipeline_runs.html", {
            "request": request, "page": "pipeline_runs",
            "runs": runs, "articles_by_id": articles_by_id,
            "status_filter": status, "trigger_filter": trigger,
            "total": total, "page_num": page, "total_pages": total_pages,
            "total_runs": total_runs, "completed": completed,
            "failed": failed, "running_now": running_now,
            "avg_seo": round(avg_seo, 1) if avg_seo else 0,
            "total_cost": round(total_cost, 4),
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# STRATEGIC PLANS  /strategic-plans  (Enhanced B)
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/strategic-plans", response_class=HTMLResponse)
async def strategic_plans_page(request: Request, page: int = 1, review_only: int = 0):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        all_plans = db.query(StrategicPlan).order_by(desc(StrategicPlan.plan_date)).all()

        plans_decoded_all = []
        pending_review_actions_total = 0
        reviewable_actions_total = 0

        # decode actions_json for display
        for p in all_plans:
            try:
                actions = json.loads(p.actions_json or "[]")
            except Exception:
                actions = []
            try:
                ctx = json.loads(p.context_snapshot or "{}")
            except Exception:
                ctx = {}

            pending_review_count = sum(
                1 for a in actions
                if str(a.get("review_status") or "").lower() == "pending" and bool(a.get("review_required"))
            )
            reviewable_count = sum(1 for a in actions if a.get("review_required"))
            pending_review_actions_total += pending_review_count
            reviewable_actions_total += reviewable_count

            plans_decoded_all.append({
                "plan": p,
                "actions": actions,
                "context": ctx,
                "pending_review_count": pending_review_count,
                "reviewable_count": reviewable_count,
                "action_counts": {
                    "generate": sum(1 for a in actions if a.get("action") == "generate"),
                    "refresh":  sum(1 for a in actions if a.get("action") == "refresh"),
                    "optimize_meta": sum(1 for a in actions if a.get("action") == "optimize_meta"),
                    "alert":    sum(1 for a in actions if a.get("action") == "alert"),
                },
            })

        if review_only:
            plans_decoded_all = [item for item in plans_decoded_all if item["pending_review_count"] > 0]

        per_page = 20
        total = len(plans_decoded_all)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        plans_decoded = plans_decoded_all[(page - 1) * per_page : page * per_page]

        # 從 pipeline_runs 計算每個 strategic plan 的平均 SEO 分數
        plan_ids = [item["plan"].id for item in plans_decoded]
        plan_avg_seo: dict[int, float] = {}
        if plan_ids:
            for plan_id, avg_s in (
                db.query(PipelineRun.strategic_plan_id, func.avg(PipelineRun.seo_score))
                .filter(
                    PipelineRun.strategic_plan_id.in_(plan_ids),
                    PipelineRun.seo_score.isnot(None),
                )
                .group_by(PipelineRun.strategic_plan_id)
                .all()
            ):
                plan_avg_seo[plan_id] = round(float(avg_s), 0)
        # 將 avg_seo_score 注入 context dict（覆蓋舊快照中可能過時的值）
        for pd_item in plans_decoded:
            pid = pd_item["plan"].id
            if pid in plan_avg_seo:
                pd_item["context"]["avg_seo_score"] = int(plan_avg_seo[pid])

        total_plans    = db.query(StrategicPlan).count()
        completed_plans = db.query(StrategicPlan).filter(StrategicPlan.status == "completed").count()
        pending_plans  = db.query(StrategicPlan).filter(StrategicPlan.status == "pending").count()

        return templates.TemplateResponse(request, "strategic_plans.html", {
            "request": request, "page": "strategic_plans",
            "plans_decoded": plans_decoded,
            "total": total, "page_num": page, "total_pages": total_pages,
            "total_plans": total_plans,
            "completed_plans": completed_plans, "pending_plans": pending_plans,
            "pending_review_actions_total": pending_review_actions_total,
            "reviewable_actions_total": reviewable_actions_total,
            "review_only": bool(review_only),
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.get("/strategic/inbox")
async def strategic_inbox_page(request: Request):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    return RedirectResponse("/admin/strategic-plans?review_only=1", status_code=303)


@admin_app.post("/strategic-plans/{plan_id}/actions/{action_index}/preview")
async def preview_strategic_action(
    request: Request,
    plan_id: int,
    action_index: int,
    redirect_to: str = Form("/admin/strategic-plans"),
):
    _require_role(request, "editor")

    db = _db()
    try:
        plan = db.query(StrategicPlan).filter(StrategicPlan.id == plan_id).first()
        if not plan:
            raise HTTPException(status_code=404)

        try:
            actions = json.loads(plan.actions_json or "[]")
        except Exception:
            actions = []
        try:
            context_snapshot = json.loads(plan.context_snapshot or "{}")
        except Exception:
            context_snapshot = {}

        if action_index < 0 or action_index >= len(actions):
            raise HTTPException(status_code=404)

        action = dict(actions[action_index] or {})
        preview = await _generate_action_preview(db, plan, action, context_snapshot)
        action["preview"] = preview
        action["preview_generated_at"] = datetime.now(timezone.utc).isoformat()
        actions[action_index] = action
        plan.actions_json = json.dumps(actions, ensure_ascii=False)

        db.add(StrategicFeedbackLog(
            project_id=plan.project_id,
            strategic_plan_id=plan.id,
            action_index=action_index,
            article_id=action.get("article_id"),
            action_type=action.get("action") or "unknown",
            feedback_type="preview",
            review_status=str(action.get("review_status") or "approved"),
            note="preview generated",
            payload_json=json.dumps(preview, ensure_ascii=False),
        ))
        db.commit()
        return RedirectResponse(redirect_to or "/admin/strategic-plans", status_code=303)
    finally:
        db.close()


@admin_app.post("/strategic-plans/{plan_id}/actions/{action_index}/review")
async def review_strategic_action(
    request: Request,
    plan_id: int,
    action_index: int,
    review_status: str = Form(...),
    review_note: str = Form(""),
    promote_to_asset: str = Form("off"),
    asset_type: str = Form("knowledge_entry"),
    feedback_type: str = Form("review"),
    redirect_to: str = Form("/admin/strategic-plans"),
):
    role = _require_role(request, "reviewer")
    if review_status not in {"pending", "approved", "rejected", "deferred"}:
        raise HTTPException(status_code=400, detail="invalid review status")

    db = _db()
    try:
        plan = db.query(StrategicPlan).filter(StrategicPlan.id == plan_id).first()
        if not plan:
            raise HTTPException(status_code=404)

        try:
            actions = json.loads(plan.actions_json or "[]")
        except Exception:
            actions = []

        if action_index < 0 or action_index >= len(actions):
            raise HTTPException(status_code=404)

        action = dict(actions[action_index] or {})
        action["review_status"] = review_status
        action["review_required"] = True
        action["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        if review_note.strip():
            action["review_note"] = review_note.strip()
        actions[action_index] = action

        plan.actions_json = json.dumps(actions, ensure_ascii=False)

        promoted_asset_type = None
        promote_learning = promote_to_asset == "on" and bool(review_note.strip())
        if promote_learning and asset_type == "writing_rule":
            max_order = db.query(func.max(WritingRule.order_num)).filter(WritingRule.project_id == plan.project_id).scalar() or 0
            db.add(WritingRule(
                project_id=plan.project_id,
                rule_type="strategic_override",
                name=f"Strategic override: {action.get('action') or 'action'}",
                content=review_note.strip(),
                order_num=int(max_order) + 1,
            ))
            promoted_asset_type = "writing_rule"
        elif promote_learning and asset_type == "knowledge_entry":
            db.add(KnowledgeEntry(
                project_id=plan.project_id,
                category="strategic_feedback",
                pattern=review_note.strip(),
                evidence_count=1,
                confidence_level="unverified",
                metadata_json=json.dumps({
                    "action_type": action.get("action"),
                    "review_status": review_status,
                    "plan_id": plan.id,
                    "action_index": action_index,
                }, ensure_ascii=False),
                is_active=True,
            ))
            promoted_asset_type = "knowledge_entry"

        db.add(StrategicFeedbackLog(
            project_id=plan.project_id,
            strategic_plan_id=plan.id,
            action_index=action_index,
            article_id=action.get("article_id"),
            action_type=action.get("action") or "unknown",
            feedback_type=feedback_type or "review",
            review_status=review_status,
            note=f"[{role}] {review_note.strip()}" if review_note.strip() else f"[{role}]",
            payload_json=json.dumps(action, ensure_ascii=False),
            promoted_asset_type=promoted_asset_type,
        ))
        db.commit()
        return RedirectResponse(redirect_to or "/admin/strategic-plans", status_code=303)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# REFLECTION LOGS  /reflections  (Enhanced B)
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/reflections", response_class=HTMLResponse)
async def reflections_page(request: Request, reflection_type: str = "", page: int = 1):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        q = db.query(ReflectionLog).order_by(desc(ReflectionLog.created_at))
        if reflection_type:
            q = q.filter(ReflectionLog.reflection_type == reflection_type)
        all_logs = q.all()

        per_page = 20
        total = len(all_logs)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        logs = all_logs[(page - 1) * per_page : page * per_page]

        logs_decoded = []
        for log in logs:
            try:
                insights = json.loads(log.insights_json or "[]")
            except Exception:
                insights = []
            logs_decoded.append({"log": log, "insights": insights})

        # 統計
        total_logs  = db.query(ReflectionLog).count()
        total_kb    = db.query(func.sum(ReflectionLog.knowledge_updates)).scalar() or 0
        total_wr    = db.query(func.sum(ReflectionLog.writing_rule_updates)).scalar() or 0
        type_counts = dict(
            db.query(ReflectionLog.reflection_type, func.count())
            .group_by(ReflectionLog.reflection_type).all()
        )

        # 取得 article titles
        article_ids = [log.article_id for log in logs if log.article_id]
        articles_by_id = {}
        if article_ids:
            for a in db.query(Article).filter(Article.id.in_(article_ids)).all():
                articles_by_id[a.id] = a.title

        return templates.TemplateResponse(request, "reflections.html", {
            "request": request, "page": "reflections",
            "logs_decoded": logs_decoded, "articles_by_id": articles_by_id,
            "type_filter": reflection_type,
            "total": total, "page_num": page, "total_pages": total_pages,
            "total_logs": total_logs, "total_kb": total_kb, "total_wr": total_wr,
            "type_counts": type_counts,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# AI CHAT  /chat
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(request, "chat.html", {
        "request": request,
        "page": "chat",
        "now": datetime.now(timezone.utc),
    })


@admin_app.post("/api/chat")
async def chat_api(request: Request):
    """AI 對話 API — 接受 messages 陣列，回傳 assistant 回答。"""
    if not _check_login(request):
        raise HTTPException(status_code=403, detail="未登入")

    body = await request.json()
    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="messages 不可為空")

    # 限制 messages 數量防止過長 context
    messages = messages[-20:]

    from contentflow.agents.chat_agent import chat as chat_fn
    try:
        result = await chat_fn(messages)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"[ChatAPI] 錯誤: {e}")
        return JSONResponse(
            {"role": "assistant", "content": f"發生錯誤：{str(e)}", "tool_calls_count": 0},
            status_code=500,
        )
