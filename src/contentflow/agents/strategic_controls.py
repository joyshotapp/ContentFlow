from __future__ import annotations

import json
from typing import Any


_BUSINESS_GOAL_ALIASES: dict[str, tuple[str, ...]] = {
    "awareness": ("品牌", "知名度", "曝光", "認知", "流量", "awareness", "traffic"),
    "conversion": ("導購", "轉換", "成交", "銷售", "營收", "conversion", "revenue", "purchase"),
    "lead_capture": ("名單", "預約", "詢價", "表單", "留資", "lead", "signup"),
    "authority": ("信任", "權威", "專業", "教育", "eeat", "expertise", "trust"),
}

_BUSINESS_GOAL_LABELS: dict[str, str] = {
    "awareness": "品牌曝光",
    "conversion": "導購轉換",
    "lead_capture": "名單蒐集",
    "authority": "權威信任",
}

_BUSINESS_GOAL_WEIGHT_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "awareness": ("awareness", "traffic", "ctr", "品牌曝光", "品牌", "知名度"),
    "conversion": ("conversion", "導購轉換", "revenue", "sales", "purchase"),
    "lead_capture": ("lead_capture", "lead", "signup", "form", "名單蒐集", "留資"),
    "authority": ("authority", "engagement", "coverage", "權威信任", "trust", "eeat"),
}

_ACTION_GOAL_ALIGNMENT: dict[str, dict[str, float]] = {
    "generate": {"awareness": 0.85, "conversion": 0.45, "lead_capture": 0.35, "authority": 0.75},
    "refresh": {"awareness": 0.55, "conversion": 0.7, "lead_capture": 0.5, "authority": 0.9},
    "optimize_meta": {"awareness": 0.45, "conversion": 0.95, "lead_capture": 0.9, "authority": 0.4},
    "inject_internal_links": {"awareness": 0.35, "conversion": 0.65, "lead_capture": 0.45, "authority": 0.8},
    "alert": {"awareness": 0.2, "conversion": 0.2, "lead_capture": 0.2, "authority": 0.2},
}


def _clamp_score(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _find_calendar_item(context_snapshot: dict[str, Any], calendar_id: Any) -> dict[str, Any] | None:
    for item in context_snapshot.get("calendar_items", []) or []:
        if item.get("calendar_id") == calendar_id:
            return item
    return None


def _normalize_business_goal_weights(raw_weights: dict[str, Any]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    total = 0.0
    for goal in _BUSINESS_GOAL_ALIASES:
        try:
            value = 0.0
            for alias in _BUSINESS_GOAL_WEIGHT_KEY_ALIASES.get(goal, (goal,)):
                value += float(raw_weights.get(alias, 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        value = max(value, 0.0)
        normalized[goal] = value
        total += value

    if total <= 0:
        return {
            "awareness": 0.35,
            "conversion": 0.2,
            "lead_capture": 0.2,
            "authority": 0.25,
        }

    return {
        goal: round(value / total, 4)
        for goal, value in normalized.items()
    }


def _parse_business_goal_profile(raw_value: Any) -> dict[str, Any]:
    text = (raw_value or "").strip()
    if not text:
        weights = _normalize_business_goal_weights({})
        primary_goal = max(weights, key=weights.get)
        return {
            "raw": "",
            "weights": weights,
            "primary_goal": primary_goal,
            "primary_goal_label": _BUSINESS_GOAL_LABELS.get(primary_goal, primary_goal),
        }

    parsed: dict[str, Any] | None = None
    if text.startswith("{"):
        try:
            parsed_json = json.loads(text)
            if isinstance(parsed_json, dict):
                parsed = parsed_json
        except Exception:
            parsed = None

    raw_weights: dict[str, float] = {}
    primary_goal = None
    secondary_goal = None
    priority_topics: list[str] = []
    money_pages: list[str] = []
    if parsed is not None:
        if isinstance(parsed.get("weights"), dict):
            raw_weights.update(parsed["weights"])
        for goal, aliases in _BUSINESS_GOAL_ALIASES.items():
            candidate_keys = (goal, _BUSINESS_GOAL_LABELS[goal], *aliases)
            for key in candidate_keys:
                if key in parsed:
                    raw_weights[goal] = parsed[key]
                    break
        primary_goal = str(parsed.get("primary_goal") or "").strip() or None
        secondary_goal = str(parsed.get("secondary_goal") or "").strip() or None
        priority_topics = [str(item).strip() for item in (parsed.get("priority_topics") or []) if str(item).strip()]
        money_pages = [str(item).strip() for item in (parsed.get("money_pages") or []) if str(item).strip()]
    else:
        lowered = text.lower()
        for goal, aliases in _BUSINESS_GOAL_ALIASES.items():
            score = 0.0
            for alias in aliases:
                alias_lower = alias.lower()
                if alias_lower in lowered:
                    score += 1.0
            raw_weights[goal] = score

    weights = _normalize_business_goal_weights(raw_weights)
    primary_goal = primary_goal if primary_goal in weights else max(weights, key=weights.get)
    secondary_goal = secondary_goal if secondary_goal in weights else next(
        (goal for goal, _ in sorted(weights.items(), key=lambda item: item[1], reverse=True) if goal != primary_goal),
        primary_goal,
    )
    return {
        "raw": text,
        "weights": weights,
        "primary_goal": primary_goal,
        "secondary_goal": secondary_goal,
        "primary_goal_label": _BUSINESS_GOAL_LABELS.get(primary_goal, primary_goal),
        "secondary_goal_label": _BUSINESS_GOAL_LABELS.get(secondary_goal, secondary_goal),
        "priority_topics": priority_topics,
        "money_pages": money_pages,
    }


def _action_target_descriptor(action: dict[str, Any], context_snapshot: dict[str, Any]) -> str:
    article_lookup = context_snapshot.get("article_lookup", {}) or {}
    article_info = article_lookup.get(str(action.get("article_id"))) or article_lookup.get(action.get("article_id")) or {}
    if action.get("keyword"):
        return str(action["keyword"])
    if action.get("title"):
        return str(action["title"])
    if article_info:
        parts = [
            str(article_info.get("primary_keyword") or ""),
            str(article_info.get("title") or ""),
            str(article_info.get("publish_path") or ""),
            str(article_info.get("slug") or ""),
        ]
        return " ".join(part for part in parts if part).strip()
    if action.get("calendar_id") is not None:
        item = _find_calendar_item(context_snapshot, action.get("calendar_id"))
        if item:
            return str(item.get("keywords") or item.get("title") or "")
    return ""


def _score_action_business_utility(action: dict[str, Any], context_snapshot: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
    action_type = action.get("action") or "alert"
    alignment_weights = _ACTION_GOAL_ALIGNMENT.get(action_type, _ACTION_GOAL_ALIGNMENT["alert"])
    goal_profile = context_snapshot.get("business_goal_profile", {}) or {}
    goal_weights = goal_profile.get("weights", {}) or _normalize_business_goal_weights({})

    contributions: list[dict[str, Any]] = []
    alignment_total = 0.0
    for goal, weight in goal_weights.items():
        goal_alignment = float(alignment_weights.get(goal, 0.2))
        contribution = round(float(weight) * goal_alignment, 4)
        alignment_total += contribution
        contributions.append({
            "goal": goal,
            "label": _BUSINESS_GOAL_LABELS.get(goal, goal),
            "weight": round(float(weight), 4),
            "alignment": round(goal_alignment, 4),
            "contribution": contribution,
        })

    contributions.sort(key=lambda item: item["contribution"], reverse=True)

    policy_scores = context_snapshot.get("action_policy_scores", {}) or {}
    action_policy = policy_scores.get(action_type, {}) or {}
    policy_score = action_policy.get("policy_score")
    if policy_score is None:
        policy_component = 0.5
    else:
        policy_component = (_clamp_score(float(policy_score), -1.0, 1.0) + 1.0) / 2.0

    priority_raw = action.get("priority")
    try:
        priority_component = max(0.0, min(float(priority_raw or 0) / 10.0, 1.0))
    except (TypeError, ValueError):
        priority_component = 0.5
    if priority_raw in (None, ""):
        priority_component = 0.5

    target_descriptor = _action_target_descriptor(action, context_snapshot).lower()
    topic_matches = 0
    for topic in goal_profile.get("priority_topics", []) or []:
        normalized_topic = str(topic).strip().lower()
        if normalized_topic and normalized_topic in target_descriptor:
            topic_matches += 1

    money_page_matches = 0
    for money_page in goal_profile.get("money_pages", []) or []:
        normalized_page = str(money_page).strip().lower()
        if normalized_page and normalized_page in target_descriptor:
            money_page_matches += 1

    topic_component = min(topic_matches * 0.08, 0.16)
    money_page_component = min(money_page_matches * 0.12, 0.24)

    utility = round(
        (alignment_total * 0.5)
        + (policy_component * 0.25)
        + (priority_component * 0.15)
        + topic_component
        + money_page_component,
        3,
    )
    return utility, contributions[:3]


def _action_requires_manual_review(action: dict[str, Any], context_snapshot: dict[str, Any]) -> tuple[bool, str]:
    action_type = action.get("action") or ""
    if action_type == "alert":
        return False, ""

    target = _action_target_descriptor(action, context_snapshot)
    target_lower = target.lower()
    for risk in context_snapshot.get("cannibalization_risks", []) or []:
        risk_keyword = str(risk.get("keyword") or "")
        if risk_keyword and risk_keyword.lower() in target_lower:
            return True, f"偵測到關鍵字自蝕風險：{risk_keyword}"

    evidence = action.get("evidence", {}) or {}
    confidence = str(evidence.get("confidence") or "medium").lower()
    priority = action.get("priority") or 0
    try:
        priority_num = float(priority)
    except (TypeError, ValueError):
        priority_num = 0.0

    if action_type in {"generate", "refresh"} and confidence != "high" and priority_num >= 8:
        return True, "高優先動作但證據信心未達 high，需人工覆核"

    return False, ""


def _attach_action_controls(plan_result: dict[str, Any], context_snapshot: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(plan_result or {})
    controlled_actions: list[dict[str, Any]] = []
    for raw_action in enriched.get("actions", []) or []:
        if not isinstance(raw_action, dict):
            continue
        action = dict(raw_action)
        utility, alignment = _score_action_business_utility(action, context_snapshot)
        action["goal_weighted_utility"] = utility
        action["business_goal_alignment"] = alignment
        action.setdefault("execution_status", "pending")

        requires_review, review_reason = _action_requires_manual_review(action, context_snapshot)
        action["review_required"] = bool(requires_review)
        action.setdefault("review_status", "pending" if requires_review else "approved")
        if review_reason:
            action["review_reason"] = review_reason

        controlled_actions.append(action)

    enriched["actions"] = controlled_actions
    return enriched


def _can_execute_action(action: dict[str, Any]) -> tuple[bool, str]:
    review_status = str(action.get("review_status") or "approved").lower()
    review_required = bool(action.get("review_required"))

    if review_status in {"rejected", "deferred"}:
        return False, f"review_status={review_status}"
    if review_required and review_status != "approved":
        return False, f"review_status={review_status or 'pending'}"
    return True, ""