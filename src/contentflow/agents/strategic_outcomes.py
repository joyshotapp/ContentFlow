from __future__ import annotations

from statistics import median
from typing import Any


def _clamp_score(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _action_outcome_weight(outcome: Any) -> float:
    confidence_weight = {
        "low": 0.75,
        "medium": 1.0,
        "high": 1.25,
    }.get((outcome.learning_confidence or "low").lower(), 0.75)
    traffic_reference = max(
        int(outcome.baseline_impressions or 0),
        int(outcome.impressions_after_28d or 0),
    )
    rank_delta = abs(float(outcome.rank_delta or 0.0))
    rank_weight = 1.0 + min(rank_delta, 10.0) * 0.03
    traffic_weight = 1.0 + min(0.35, traffic_reference / 800.0)
    return round(confidence_weight * traffic_weight * rank_weight, 4)


def _action_outcome_effects(outcome: Any) -> dict[str, float | None]:
    rank_delta = float(outcome.rank_delta) if outcome.rank_delta is not None else None

    baseline_clicks_raw = getattr(outcome, "baseline_clicks", None)
    after_clicks_raw = getattr(outcome, "clicks_after_28d", None)
    if baseline_clicks_raw is None and after_clicks_raw is None:
        click_delta = None
    else:
        click_delta = int(after_clicks_raw or 0) - int(baseline_clicks_raw or 0)

    baseline_ctr_raw = getattr(outcome, "baseline_ctr", None)
    after_ctr_raw = getattr(outcome, "ctr_after_28d", None)
    if baseline_ctr_raw is None and after_ctr_raw is None:
        ctr_delta = None
    else:
        ctr_delta = round(float(after_ctr_raw or 0.0) - float(baseline_ctr_raw or 0.0), 4)

    return {
        "rank_delta": rank_delta,
        "click_delta": click_delta,
        "ctr_delta": ctr_delta,
    }


def _project_control_baseline(outcomes: list[Any]) -> dict[str, float]:
    rank_deltas: list[float] = []
    click_deltas: list[float] = []
    ctr_deltas: list[float] = []

    for outcome in outcomes:
        effects = _action_outcome_effects(outcome)
        if effects["rank_delta"] is not None:
            rank_deltas.append(float(effects["rank_delta"]))
        if effects["click_delta"] is not None:
            click_deltas.append(float(effects["click_delta"]))
        if effects["ctr_delta"] is not None:
            ctr_deltas.append(float(effects["ctr_delta"]))

    return {
        "rank_delta_median": round(float(median(rank_deltas)), 3) if rank_deltas else 0.0,
        "click_delta_median": round(float(median(click_deltas)), 3) if click_deltas else 0.0,
        "ctr_delta_median": round(float(median(ctr_deltas)), 4) if ctr_deltas else 0.0,
    }


def _control_adjustment_from_effects(
    effects: dict[str, float | None],
    control_baseline: dict[str, float],
) -> tuple[float, float, float, float]:
    rank_advantage = 0.0 if effects["rank_delta"] is None else control_baseline["rank_delta_median"] - float(effects["rank_delta"])
    click_advantage = 0.0 if effects["click_delta"] is None else float(effects["click_delta"]) - control_baseline["click_delta_median"]
    ctr_advantage = 0.0 if effects["ctr_delta"] is None else float(effects["ctr_delta"]) - control_baseline["ctr_delta_median"]

    rank_component = _clamp_score(rank_advantage / 5.0)
    click_component = _clamp_score(click_advantage / 10.0)
    ctr_component = _clamp_score(ctr_advantage / 0.015)
    control_adjustment = (rank_component * 0.35) + (click_component * 0.15) + (ctr_component * 0.2)
    return rank_advantage, click_advantage, ctr_advantage, control_adjustment


def _build_action_outcome_stats(
    outcomes: list[Any],
    evaluations_by_outcome_id: dict[int, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    stats: dict[str, dict[str, Any]] = {}
    policy_scores: dict[str, dict[str, Any]] = {}
    control_baseline = _project_control_baseline(outcomes)
    evaluations_by_outcome_id = evaluations_by_outcome_id or {}

    for outcome in outcomes:
        action_type = outcome.action_type or "unknown"
        bucket = stats.setdefault(action_type, {
            "total": 0,
            "improved": 0,
            "declined": 0,
            "stable": 0,
            "weighted_total": 0.0,
            "weighted_improved": 0.0,
            "weighted_declined": 0.0,
            "weighted_stable": 0.0,
            "weighted_rank_delta_sum": 0.0,
            "weighted_rank_delta_total": 0.0,
            "weighted_click_delta_sum": 0.0,
            "weighted_click_delta_total": 0.0,
            "weighted_ctr_delta_sum": 0.0,
            "weighted_ctr_delta_total": 0.0,
            "weighted_control_adjustment_sum": 0.0,
        })
        bucket["total"] += 1
        if outcome.success_flag in ("improved", "declined", "stable"):
            bucket[outcome.success_flag] += 1

        weight = _action_outcome_weight(outcome)
        bucket["weighted_total"] += weight
        if outcome.success_flag == "improved":
            bucket["weighted_improved"] += weight
        elif outcome.success_flag == "declined":
            bucket["weighted_declined"] += weight
        elif outcome.success_flag == "stable":
            bucket["weighted_stable"] += weight

        outcome_id = getattr(outcome, "id", None)
        persisted_eval = evaluations_by_outcome_id.get(outcome_id) if outcome_id is not None else None
        effects = {
            "rank_delta": persisted_eval.rank_delta if persisted_eval and persisted_eval.rank_delta is not None else None,
            "click_delta": persisted_eval.click_delta if persisted_eval and persisted_eval.click_delta is not None else None,
            "ctr_delta": persisted_eval.ctr_delta if persisted_eval and persisted_eval.ctr_delta is not None else None,
        } if persisted_eval else _action_outcome_effects(outcome)

        if persisted_eval:
            control_adjustment = float(persisted_eval.control_adjustment or 0.0)
        else:
            _, _, _, control_adjustment = _control_adjustment_from_effects(effects, control_baseline)

        bucket["weighted_control_adjustment_sum"] += control_adjustment * weight
        if effects["rank_delta"] is not None:
            bucket["weighted_rank_delta_sum"] += float(effects["rank_delta"]) * weight
            bucket["weighted_rank_delta_total"] += weight
        if effects["click_delta"] is not None:
            bucket["weighted_click_delta_sum"] += float(effects["click_delta"]) * weight
            bucket["weighted_click_delta_total"] += weight
        if effects["ctr_delta"] is not None:
            bucket["weighted_ctr_delta_sum"] += float(effects["ctr_delta"]) * weight
            bucket["weighted_ctr_delta_total"] += weight

    for action_type, bucket in stats.items():
        weighted_total = float(bucket.get("weighted_total", 0.0) or 0.0)
        if weighted_total > 0:
            weighted_improved_rate = bucket["weighted_improved"] / weighted_total
            weighted_declined_rate = bucket["weighted_declined"] / weighted_total
            weighted_stable_rate = bucket["weighted_stable"] / weighted_total
        else:
            weighted_improved_rate = 0.0
            weighted_declined_rate = 0.0
            weighted_stable_rate = 0.0

        avg_rank_delta = None
        if bucket["weighted_rank_delta_total"] > 0:
            avg_rank_delta = bucket["weighted_rank_delta_sum"] / bucket["weighted_rank_delta_total"]
        avg_click_delta = None
        if bucket["weighted_click_delta_total"] > 0:
            avg_click_delta = bucket["weighted_click_delta_sum"] / bucket["weighted_click_delta_total"]
        avg_ctr_delta = None
        if bucket["weighted_ctr_delta_total"] > 0:
            avg_ctr_delta = bucket["weighted_ctr_delta_sum"] / bucket["weighted_ctr_delta_total"]
        rank_advantage, click_advantage, ctr_advantage, fallback_control_adjustment = _control_adjustment_from_effects(
            {
                "rank_delta": avg_rank_delta,
                "click_delta": avg_click_delta,
                "ctr_delta": avg_ctr_delta,
            },
            control_baseline,
        )
        control_adjustment = (
            bucket["weighted_control_adjustment_sum"] / weighted_total
            if weighted_total > 0
            else fallback_control_adjustment
        )

        sample_factor = min(weighted_total / 4.0, 1.0) if weighted_total > 0 else 0.0
        raw_score = _clamp_score(
            (weighted_improved_rate - weighted_declined_rate + (weighted_stable_rate * 0.15))
            + control_adjustment
        )
        policy_score = round(raw_score * sample_factor, 3)

        if bucket["total"] < 2:
            recommendation = "insufficient_data"
        elif bucket["total"] < 4:
            recommendation = "maintain"
        elif policy_score >= 0.35:
            recommendation = "scale"
        elif policy_score <= -0.2:
            recommendation = "deprioritize"
        else:
            recommendation = "maintain"

        bucket.update({
            "weighted_total": round(weighted_total, 3),
            "weighted_improved_rate": round(weighted_improved_rate, 3),
            "weighted_declined_rate": round(weighted_declined_rate, 3),
            "weighted_stable_rate": round(weighted_stable_rate, 3),
            "avg_rank_delta": round(float(avg_rank_delta), 3) if avg_rank_delta is not None else None,
            "avg_click_delta": round(float(avg_click_delta), 3) if avg_click_delta is not None else None,
            "avg_ctr_delta": round(float(avg_ctr_delta), 4) if avg_ctr_delta is not None else None,
            "rank_advantage_vs_baseline": round(rank_advantage, 3),
            "click_advantage_vs_baseline": round(click_advantage, 3),
            "ctr_advantage_vs_baseline": round(ctr_advantage, 4),
            "control_adjustment": round(control_adjustment, 3),
            "policy_score": policy_score,
            "recommendation": recommendation,
        })
        policy_scores[action_type] = {
            "sample_count": bucket["total"],
            "weighted_sample_size": round(weighted_total, 3),
            "weighted_improved_rate": round(weighted_improved_rate, 3),
            "weighted_declined_rate": round(weighted_declined_rate, 3),
            "weighted_stable_rate": round(weighted_stable_rate, 3),
            "avg_rank_delta": round(float(avg_rank_delta), 3) if avg_rank_delta is not None else None,
            "avg_click_delta": round(float(avg_click_delta), 3) if avg_click_delta is not None else None,
            "avg_ctr_delta": round(float(avg_ctr_delta), 4) if avg_ctr_delta is not None else None,
            "rank_advantage_vs_baseline": round(rank_advantage, 3),
            "click_advantage_vs_baseline": round(click_advantage, 3),
            "ctr_advantage_vs_baseline": round(ctr_advantage, 4),
            "control_adjustment": round(control_adjustment, 3),
            "control_baseline": dict(control_baseline),
            "policy_score": policy_score,
            "recommendation": recommendation,
        }

    return stats, policy_scores