"""專案上下文載入器 — 為 Agent 提供品牌知識與法規資訊"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from loguru import logger

from .policy_resolver import resolve_policy


@dataclass
class ProjectContext:
    """Agent 可消費的專案品牌上下文"""
    project_id: int
    slug: str
    name: str
    brand_name: str = ""
    brand_url: str = ""
    brand_description: str = ""
    industry: str = ""
    writing_principles: str = ""
    domain_profile: str = ""
    compliance_profile: str = ""
    default_content_format: str = ""
    reviewer_role_label: str = ""
    disclaimer_template: str = ""
    evidence_policy: str = ""
    image_style_override: str = ""
    extra_schema_types_json: str = "[]"
    factcheck_mode_override: str = ""
    locale: str = "zh-tw"
    serp_gl: str = "tw"
    serp_hl: str = "zh-tw"

    # Phase 0 — 商業目標 & 受眾
    business_goals: str = ""
    target_audience_json: str = "{}"  # JSON: persona_name, age_range, pain_points...

    # 從 DB 載入（延遲填充）
    writing_rules: list[str] = field(default_factory=list)
    strategies: list[str] = field(default_factory=list)
    legal_terms: list[str] = field(default_factory=list)
    forbidden_words: list[str] = field(default_factory=list)

    def build_brand_prompt(self) -> str:
        """組裝品牌知識 Prompt 區塊（注入 Agent 系統 Prompt）"""
        parts = []

        if self.brand_name:
            parts.append(f"# 品牌：{self.brand_name}")
        if self.brand_url:
            parts.append(f"- 網站：{self.brand_url}")
        if self.brand_description:
            parts.append(f"- 定位：{self.brand_description}")
        if self.writing_principles:
            parts.append(f"- 核心原則：「{self.writing_principles}」")
        if self.business_goals:
            parts.append(f"- 商業目標：{self.business_goals}")
        if self.target_audience_json and self.target_audience_json != "{}":
            import json as _json
            try:
                ta = _json.loads(self.target_audience_json)
                if isinstance(ta, dict) and ta:
                    desc_parts = []
                    if ta.get("persona_name"): desc_parts.append(ta["persona_name"])
                    if ta.get("age_range"): desc_parts.append(f"年齡 {ta['age_range']}")
                    if ta.get("pain_points"): desc_parts.append(f"痛點：{ta['pain_points']}")
                    if desc_parts:
                        parts.append(f"- 目標受眾：{' / '.join(desc_parts)}")
            except (ValueError, TypeError):
                pass
        parts.append("")

        if self.writing_rules:
            parts.append("# 撰寫規範")
            for rule in self.writing_rules[:3]:
                parts.append(rule[:2000])
            parts.append("")

        if self.strategies:
            parts.append("# 內容策略")
            for s in self.strategies[:5]:
                parts.append(f"- {s[:500]}")
            parts.append("")

        if self.legal_terms:
            parts.append("# 法規紅線（絕對不可使用）")
            for t in self.legal_terms:
                parts.append(f"- {t[:300]}")
            parts.append("")

        return "\n".join(parts)


def _extract_forbidden_terms(terms: list[str]) -> list[str]:
    """從法規條文中提取可直接比對的禁用詞。"""
    extracted = []
    seen = set()
    boilerplate_fragments = (
        "行政院衛生署",
        "本署",
        "保障消費者權益",
        "禁止食品標示",
        "宣傳或廣告",
        "誇張易生誤解",
        "醫療效能",
        "特訂定本基準",
        "健康食品管理法",
        "涉及",
        "使用下列詞句者",
        "應認定",
        "例句",
        "引用或摘錄",
        "出版品",
        "典籍",
        "他人名義",
        "日期",
    )

    def add(term: str):
        cleaned = term.strip().strip("-•*，,。；;：:()（）[]")
        if len(cleaned) < 2 or len(cleaned) > 10:
            return
        if not re.search(r"[\u4e00-\u9fff]", cleaned):
            return
        if any(fragment in cleaned for fragment in boilerplate_fragments):
            return
        if re.search(r"[0-9a-zA-Z]", cleaned):
            return
        if cleaned not in seen:
            seen.add(cleaned)
            extracted.append(cleaned)

    for content in terms:
        for match in re.findall(r"[「『](.+?)[」』]", content):
            add(match)
        for examples in re.findall(r"例句[:：]\s*([^\n]+)", content):
            for piece in re.split(r"[。；;、，]+", examples):
                add(piece)
        for piece in re.split(r"[\n,，、；;]+", content):
            add(piece)

    return extracted


def load_project_context(
    project_id: int | None = None,
    project_slug: str | None = None,
) -> ProjectContext:
    """
    載入專案上下文。

    - 指定 project_id → 載入對應專案
    - 指定 project_slug → 以 slug 查詢
    - 皆未指定 → 載入第一個專案（單專案向後兼容）
    """
    try:
        from .db import get_db
        from .models.database import (
            Project,
            WritingRule,
            ContentStrategy,
            LegalTerm,
        )

        session = get_db()
        try:
            if project_id:
                project = session.get(Project, project_id)
            elif project_slug:
                project = session.query(Project).filter(Project.slug == project_slug).first()
            else:
                project = session.query(Project).first()

            if not project:
                logger.warning("找不到專案，使用空白上下文")
                return ProjectContext(project_id=0, slug="default", name="Default")

            ctx = ProjectContext(
                project_id=project.id,
                slug=project.slug,
                name=project.name,
                brand_name=project.brand_name or "",
                brand_url=project.brand_url or "",
                brand_description=project.brand_description or "",
                industry=project.industry or "",
                writing_principles=project.writing_principles or "",
                domain_profile=project.domain_profile or "",
                compliance_profile=project.compliance_profile or "",
                default_content_format=project.default_content_format or "",
                reviewer_role_label=project.reviewer_role_label or "",
                disclaimer_template=project.disclaimer_template or "",
                evidence_policy=project.evidence_policy or "",
                image_style_override=project.image_style_override or "",
                extra_schema_types_json=project.extra_schema_types_json or "[]",
                factcheck_mode_override=project.factcheck_mode_override or "",
                locale=project.locale or "zh-tw",
                serp_gl=project.serp_gl or "tw",
                serp_hl=project.serp_hl or "zh-tw",
                business_goals=project.business_goals or "",
                target_audience_json=project.target_audience_json or "{}",
            )

            # 載入撰寫規範
            rules = (
                session.query(WritingRule)
                .filter(WritingRule.project_id == project.id)
                .all()
            )
            ctx.writing_rules = [r.content for r in rules]

            # 載入內容策略
            strats = (
                session.query(ContentStrategy)
                .filter(ContentStrategy.project_id == project.id)
                .limit(10)
                .all()
            )
            ctx.strategies = [f"{s.title}: {s.content}" for s in strats]

            # 載入法規用詞
            terms = (
                session.query(LegalTerm)
                .filter(LegalTerm.project_id == project.id)
                .all()
            )
            ctx.legal_terms = [t.content for t in terms if t.term_type in ("forbidden", "caution")]
            ctx.forbidden_words = _extract_forbidden_terms(
                [t.content for t in terms if t.term_type == "forbidden"]
            )

            logger.info(
                f"[ProjectContext] {project.name}: "
                f"{len(ctx.writing_rules)} 規範, "
                f"{len(ctx.strategies)} 策略, "
                f"{len(ctx.legal_terms)} 法規"
            )
            return ctx

        finally:
            session.close()

    except Exception as e:
        logger.warning(f"載入專案上下文失敗: {e}")
        return ProjectContext(project_id=0, slug="default", name="Default")


def project_uses_pubmed(ctx: ProjectContext) -> bool:
    """由 policy resolver 決定是否啟用 PubMed。"""
    return resolve_policy(ctx).use_pubmed
