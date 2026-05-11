from __future__ import annotations

from datetime import timedelta
from statistics import median


def _normalize_url_path(url: str) -> str:
    if not url:
        return ""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = (parsed.path or url).strip()
    if not path:
        return ""
    if not path.startswith("/"):
        path = f"/{path.lstrip('/')}"
    return path.rstrip("/") or "/"


def _get_gsc_snapshot(
    session,
    project_id: int,
    keyword: str,
    target_date,
    *,
    landing_page: str | None = None,
    window_days: int = 2,
):
    from contentflow.models.database import SEORanking

    window_start = target_date - timedelta(days=window_days)
    window_end = target_date + timedelta(days=window_days)
    rows = (
        session.query(SEORanking)
        .filter(
            SEORanking.project_id == project_id,
            SEORanking.keyword == keyword,
            SEORanking.tracked_date >= window_start,
            SEORanking.tracked_date <= window_end,
        )
        .all()
    )
    if not rows:
        return None

    target_path = _normalize_url_path(landing_page or "")
    if target_path:
        path_rows = [row for row in rows if _normalize_url_path(row.landing_page or "") == target_path]
        if path_rows:
            rows = path_rows

    latest_date = max((row.tracked_date for row in rows if row.tracked_date), default=None)
    if latest_date is None:
        return None

    latest_rows = [row for row in rows if row.tracked_date == latest_date]
    positions = [float(row.position) for row in latest_rows if row.position is not None]
    impressions = sum(int(row.impressions or 0) for row in latest_rows)
    clicks = sum(int(row.clicks or 0) for row in latest_rows)
    ctr = round((clicks / impressions), 4) if impressions > 0 else 0.0

    return {
        "rank": round(sum(positions) / len(positions), 1) if positions else None,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "tracked_date": latest_date,
    }


def _classify_outcome_success(outcome, snapshot: dict[str, object]) -> tuple[str, str, float | None]:
    rank = snapshot.get("rank")
    if rank is None:
        return "stable", "low", None

    if outcome.baseline_rank is None:
        if rank <= 50:
            return "improved", "medium", None
        return "stable", "low", None

    rank_delta = round(float(rank) - float(outcome.baseline_rank), 1)
    click_delta = int(snapshot.get("clicks", 0) or 0) - int(outcome.baseline_clicks or 0)
    ctr_delta = round(float(snapshot.get("ctr", 0.0) or 0.0) - float(outcome.baseline_ctr or 0.0), 4)

    if rank_delta <= -3:
        return "improved", "high", rank_delta
    if rank_delta <= 0 and (click_delta > 0 or ctr_delta >= 0.01):
        return "improved", "medium", rank_delta
    if rank_delta <= 3 and (click_delta >= 0 or ctr_delta >= 0.0):
        return "stable", "medium", rank_delta
    return "declined", "high", rank_delta


def _evaluation_weight(outcome) -> float:
    confidence_weight = {
        "low": 0.75,
        "medium": 1.0,
        "high": 1.25,
    }.get((outcome.learning_confidence or "low").lower(), 0.75)
    traffic_reference = max(
        int(outcome.baseline_impressions or 0),
        int(outcome.impressions_after_28d or 0),
    )
    traffic_weight = 1.0 + min(0.35, traffic_reference / 800.0)
    rank_delta = abs(float(outcome.rank_delta or 0.0))
    rank_weight = 1.0 + min(rank_delta, 10.0) * 0.03
    return round(confidence_weight * traffic_weight * rank_weight, 4)


def _evaluation_clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _outcome_effects(outcome) -> dict[str, float | None]:
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


def _control_baseline(outcomes) -> dict[str, float]:
    rank_deltas: list[float] = []
    click_deltas: list[float] = []
    ctr_deltas: list[float] = []

    for outcome in outcomes:
        effects = _outcome_effects(outcome)
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


def _build_outcome_evaluation_snapshot(outcome, reference_outcomes) -> dict[str, float | None]:
    effects = _outcome_effects(outcome)
    baseline = _control_baseline(reference_outcomes)

    rank_advantage = 0.0 if effects["rank_delta"] is None else baseline["rank_delta_median"] - float(effects["rank_delta"])
    click_advantage = 0.0 if effects["click_delta"] is None else float(effects["click_delta"]) - baseline["click_delta_median"]
    ctr_advantage = 0.0 if effects["ctr_delta"] is None else float(effects["ctr_delta"]) - baseline["ctr_delta_median"]

    rank_component = _evaluation_clamp(rank_advantage / 5.0)
    click_component = _evaluation_clamp(click_advantage / 10.0)
    ctr_component = _evaluation_clamp(ctr_advantage / 0.015)
    control_adjustment = (rank_component * 0.35) + (click_component * 0.15) + (ctr_component * 0.2)

    return {
        "outcome_weight": _evaluation_weight(outcome),
        "rank_delta": round(float(effects["rank_delta"]), 3) if effects["rank_delta"] is not None else None,
        "click_delta": round(float(effects["click_delta"]), 3) if effects["click_delta"] is not None else None,
        "ctr_delta": round(float(effects["ctr_delta"]), 4) if effects["ctr_delta"] is not None else None,
        "control_rank_delta_median": baseline["rank_delta_median"],
        "control_click_delta_median": baseline["click_delta_median"],
        "control_ctr_delta_median": baseline["ctr_delta_median"],
        "rank_advantage_vs_baseline": round(rank_advantage, 3),
        "click_advantage_vs_baseline": round(click_advantage, 3),
        "ctr_advantage_vs_baseline": round(ctr_advantage, 4),
        "control_adjustment": round(control_adjustment, 3),
    }