"""SQLAlchemy ORM 資料庫模型 — 取代 Excel 成為唯一資料源"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── 專案（多租戶） ───────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)

    # 品牌資訊（注入 Agent Prompt）
    brand_name = Column(String, default="")
    brand_url = Column(String, default="")
    brand_description = Column(Text, default="")
    site_contact_email = Column(String, default="")
    site_blog_path = Column(String, default="/blog")
    industry = Column(String, default="")
    writing_principles = Column(Text, default="")
    domain_profile = Column(String, default="general")
    compliance_profile = Column(String, default="general")
    default_content_format = Column(String, default="knowledge")
    reviewer_role_label = Column(String, default="")
    disclaimer_template = Column(Text, default="")
    evidence_policy = Column(String, default="default")
    image_style_override = Column(Text, default="")
    extra_schema_types_json = Column(Text, default="[]")
    factcheck_mode_override = Column(String, default="")

    # SERP & 地區
    locale = Column(String, default="zh-tw")
    serp_gl = Column(String, default="tw")
    serp_hl = Column(String, default="zh-tw")

    # Phase 0 — 商業目標 & 受眾（SEO SOP §2）
    business_goals = Column(Text, default="")          # 品牌知名度 / 導購 / 收集名單
    target_audience_json = Column(Text, default="{}")  # JSON: persona_name, age_range, pain_points...
    ga4_property_id = Column(String, default="")       # GA4 Property ID for this project

    # 發布政策（L2-1）
    auto_publish_enabled = Column(Boolean, default=False)    # 开啟自動發布
    auto_publish_min_score = Column(Integer, default=85)     # 自動發布所需最低 SEO 分數

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    keywords = relationship("Keyword", back_populates="project")
    categories = relationship("Category", back_populates="project")
    calendar_entries = relationship("ContentCalendar", back_populates="project")
    articles = relationship("Article", back_populates="project")
    writing_rules = relationship("WritingRule", back_populates="project")
    content_strategies = relationship("ContentStrategy", back_populates="project")
    competitors = relationship("Competitor", back_populates="project")
    products = relationship("Product", back_populates="project")
    legal_terms = relationship("LegalTerm", back_populates="project")
    seo_rankings = relationship("SEORanking", back_populates="project")
    category_seos = relationship("CategorySEO", back_populates="project")
    changelogs = relationship("Changelog", back_populates="project")
    ga_page_metrics = relationship("GAPageMetric", back_populates="project")
    competitor_snapshots = relationship("CompetitorSnapshot", back_populates="project")
    authors = relationship("Author", back_populates="project")
    backlink_snapshots = relationship("BacklinkSnapshot", back_populates="project")
    gbp_metrics = relationship("GoogleBusinessMetric", back_populates="project")
    integrations = relationship("ProjectIntegration", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Project '{self.slug}' ({self.name})>"


class ProjectIntegration(Base):
    __tablename__ = "project_integrations"
    __table_args__ = (
        UniqueConstraint("project_id", "integration_type", name="uq_project_integrations_project_type"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    integration_type = Column(String, nullable=False, index=True)   # wordpress / forgebase
    label = Column(String, default="")
    base_url = Column(String, default="")
    username = Column(String, default="")
    secret_value = Column(Text, default="")
    seo_plugin = Column(String, default="yoast")
    publish_mode = Column(String, default="publish")
    is_enabled = Column(Boolean, default=True)
    config_json = Column(Text, default="{}")
    health_status = Column(String, default="unknown")
    last_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="integrations")

    def __repr__(self):
        return f"<ProjectIntegration project={self.project_id} type={self.integration_type}>"


class ProjectAuditLog(Base):
    __tablename__ = "project_audit_logs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    actor = Column(String, default="system")
    action_type = Column(String, nullable=False, index=True)
    summary = Column(Text, default="")
    payload_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    project = relationship("Project")

    def __repr__(self):
        return f"<ProjectAuditLog project={self.project_id} action={self.action_type}>"


# ── 關鍵字表 ─────────────────────────────────────────────────

class Keyword(Base):
    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    keyword = Column(String, nullable=False, index=True)
    search_volume = Column(Float, default=0)
    cpc = Column(Float, default=0)
    paid_difficulty = Column(Float, default=0)
    seo_difficulty = Column(Float, default=0)
    priority = Column(String, default="")        # "X" (低), "green_x" (中), "" (高)
    usage = Column(String, default="")
    steve_note = Column(Text, default="")
    # Phase 2 — 搜尋意圖 & 漏斗階段（SEO SOP §4）
    intent = Column(String, default="")          # informational / investigational / transactional / navigational
    funnel_stage = Column(String, default="")    # awareness / consideration / decision
    # Phase 3 — Google Trends 相對熱度
    trends_score = Column(Integer, default=None)     # 0-100，SerpAPI Google Trends 年均值
    trend_direction = Column(String, default=None)   # "up" / "down" / "stable"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="keywords")

    def __repr__(self):
        return f"<Keyword '{self.keyword}' vol={self.search_volume}>"


# ── 部落格分類 & Tag ──────────────────────────────────────────

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True)
    cat_type = Column(String, default="category")  # "category" / "tag"
    description = Column(Text, default="")
    meta_title = Column(String, default="")
    meta_description = Column(Text, default="")
    meta_keywords = Column(Text, default="")

    project = relationship("Project", back_populates="categories")

    def __repr__(self):
        return f"<Category [{self.cat_type}] {self.name}>"


# ── 2026 內容日曆 ─────────────────────────────────────────────

class ContentCalendar(Base):
    __tablename__ = "content_calendar"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    month = Column(Integer)
    week = Column(Integer)
    article_type = Column(String, default="")      # 知識 / 情境 / 節慶
    title = Column(String, default="")
    keywords = Column(Text, default="")
    search_intent = Column(String, default="")      # 資訊性 / 交易性啟發
    target_audience = Column(Text, default="")
    writing_architecture = Column(String, default="")  # 倒三角 / 金字塔 / 思維流程 / 敘事型
    faq_questions = Column(Text, default="")
    status = Column(String, default="planned")      # planned / researching / writing / published
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True)

    article = relationship("Article", back_populates="calendar_entry")
    project = relationship("Project", back_populates="calendar_entries")

    def __repr__(self):
        return f"<Calendar M{self.month}W{self.week} '{self.title[:30]}'>"


# ── 文章規劃 ──────────────────────────────────────────────────

class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    seqno = Column(Integer, nullable=True)
    primary_keyword = Column(String, default="")
    primary_keyword_volume = Column(Float, default=0)
    secondary_keywords = Column(Text, default="")
    title = Column(String, default="")
    outline = Column(Text, default="")              # 完整文章架構
    google_doc_url = Column(String, default="")
    draft_date = Column(String, default="")
    review_date = Column(String, default="")
    publish_date = Column(String, default="")
    publish_url = Column(String, default="")
    article_type = Column(String, default="")         # 知識 / 情境 / 節慶 / product
    status = Column(String, default="planned")      # planned / researching / writing / reviewing / published
    research_report_json = Column(Text, default="") # JSON 格式的研究報告
    draft_content = Column(Text, default="")        # Markdown 格式的文章內容
    slug = Column(String, default="")               # SEO URL slug
    meta_title = Column(String, default="")         # Meta Title
    meta_description = Column(Text, default="")     # Meta Description
    faq_schema_json = Column(Text, default="")      # FAQPage JSON-LD
    howto_schema_json = Column(Text, default="")    # HowTo JSON-LD（步驟型文章）
    article_schema_json = Column(Text, default="")  # Article/BlogPosting JSON-LD
    paa_questions_json = Column(Text, default="[]")  # People Also Ask 問題列表（持久化）
    seo_score = Column(Integer, nullable=True)      # 最近一次 SEO 檢查分數
    content_format_override = Column(String, default="")
    reviewer_required_override = Column(Boolean, nullable=True)
    custom_disclaimer = Column(Text, default="")
    extra_schema_types_override_json = Column(Text, default="[]")
    # Phase 5/21 — E-E-A-T & 優化迭代
    author_id = Column(Integer, ForeignKey("authors.id"), nullable=True)
    reviewer_id = Column(Integer, ForeignKey("authors.id"), nullable=True)  # 醫療審閱者
    eeat_score = Column(Integer, nullable=True)     # E-E-A-T 綜合評分 0-100
    performance_grade = Column(String(2), nullable=True)  # 歸因引擎計算等級 A/B/C/D/F
    last_refresh_date = Column(DateTime, nullable=True)  # 最近一次 Content Refresh
    factcheck_flags_json = Column(Text, default="[]")    # FactCheck 高風險標記
    suggested_internal_links = Column(Text, default="[]")  # AI 建議的內部連結
    scheduled_publish_at = Column(DateTime, nullable=True)  # 排程發布時間
    published_at = Column(DateTime, nullable=True)          # 實際發布時間（Phase 6 時間線基準）
    target_word_count = Column(Integer, nullable=True)       # Phase 3 任務定義的目標字數
    wp_post_id = Column(String, default="")         # WordPress post ID
    forgebase_id = Column(String, default="")       # ForgeBase page ID
    hero_image_url = Column(String, default="")     # AI 生成 Hero 圖片（Cloudflare R2 URL）
    old_slugs = Column(Text, default="[]")           # 曾用過的 slug（JSON 陣列）—收到請求時發 301
    intent_match_score = Column(Float, nullable=True)   # 上線後 GSC 意圖命中分數 0-100
    intent_match_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    calendar_entry = relationship("ContentCalendar", back_populates="article", uselist=False)
    project = relationship("Project", back_populates="articles")
    author = relationship("Author", foreign_keys="[Article.author_id]", back_populates="articles")
    reviewer = relationship("Author", foreign_keys="[Article.reviewer_id]")

    def __repr__(self):
        return f"<Article #{self.seqno} '{self.title[:30]}'>"


# ── 撰寫規範 ──────────────────────────────────────────────────

class WritingRule(Base):
    __tablename__ = "writing_rules"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    rule_type = Column(String, default="")    # architecture / principle / tone
    name = Column(String, default="")
    content = Column(Text, default="")
    order_num = Column(Integer, default=0)

    project = relationship("Project", back_populates="writing_rules")

    def __repr__(self):
        return f"<WritingRule [{self.rule_type}] {self.name}>"


# ── 部落格內容定位（策略） ────────────────────────────────────

class ContentStrategy(Base):
    __tablename__ = "content_strategy"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    section = Column(String, default="")     # 內容目標 / 撰寫策略 / 關鍵字方向 / 台語用詞
    title = Column(String, default="")
    content = Column(Text, default="")
    order_num = Column(Integer, default=0)

    project = relationship("Project", back_populates="content_strategies")

    def __repr__(self):
        return f"<ContentStrategy [{self.section}] {self.title[:30]}>"


# ── 競業市場研究 ──────────────────────────────────────────────

class Competitor(Base):
    __tablename__ = "competitors"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    brand_name = Column(String, default="")
    website = Column(String, default="")
    features = Column(Text, default="")
    content_analysis = Column(Text, default="")
    sells_products = Column(String, default="")
    recommendation = Column(Text, default="")

    project = relationship("Project", back_populates="competitors")
    snapshots = relationship("CompetitorSnapshot", back_populates="competitor")

    def __repr__(self):
        return f"<Competitor '{self.brand_name}'>"


# ── 產品資訊 ──────────────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    series_name = Column(String, default="")
    description = Column(Text, default="")
    target_symptoms = Column(Text, default="")
    inquiry_percentage = Column(String, default="")

    project = relationship("Project", back_populates="products")

    def __repr__(self):
        return f"<Product '{self.series_name}'>"


# ── 食品廣告用詞規定 ──────────────────────────────────────────

class LegalTerm(Base):
    __tablename__ = "legal_terms"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    term_type = Column(String, default="")    # allowed / forbidden / caution
    category = Column(String, default="")      # 醫療效能 / 誇張易誤解 / 可使用
    content = Column(Text, default="")
    source = Column(String, default="")

    project = relationship("Project", back_populates="legal_terms")

    def __repr__(self):
        return f"<LegalTerm [{self.term_type}] {self.content[:30]}>"


# ── SEO 關鍵字排名表 ─────────────────────────────────────────

class SEORanking(Base):
    __tablename__ = "seo_rankings"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    keyword = Column(String, default="")
    position = Column(Float, nullable=True)          # GSC average position（取代舊 rank）
    landing_page = Column(String, default="")
    search_engine = Column(String, default="Google")
    tracked_date = Column(Date, nullable=True)        # 原先為 String，改為 Date
    impressions = Column(Integer, nullable=True)     # GSC 曝光次數
    clicks = Column(Integer, nullable=True)          # GSC 點斓次數
    ctr = Column(Float, nullable=True)               # GSC 點斓率

    project = relationship("Project", back_populates="seo_rankings")

    def __repr__(self):
        return f"<SEORanking '{self.keyword}' pos={self.position}>"


class GSCDailyMetric(Base):
    """GSC 日級增量（P1 歸因用，非 28 天重疊窗口）。"""
    __tablename__ = "gsc_daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "keyword", "landing_page", "metric_date",
            name="uq_gsc_daily_project_kw_page_date",
        ),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    keyword = Column(String, default="")
    landing_page = Column(String, default="")
    metric_date = Column(Date, nullable=False, index=True)
    clicks = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    ctr = Column(Float, nullable=True)
    position = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BrandMentionSnapshot(Base):
    __tablename__ = "brand_mention_snapshots"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    brand_query = Column(String, default="")
    mention_url = Column(String, default="")
    mention_title = Column(String, default="")
    mention_snippet = Column(Text, default="")
    tracked_date = Column(Date, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class OutreachTask(Base):
    __tablename__ = "outreach_tasks"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    task_type = Column(String, default="brand_mention")
    target_url = Column(String, default="")
    target_domain = Column(String, default="")
    suggested_action = Column(Text, default="")
    status = Column(String, default="open")
    priority = Column(Integer, default=3)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class ContentExperiment(Base):
    __tablename__ = "content_experiments"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True, index=True)
    experiment_key = Column(String, default="")
    variant = Column(String, default="control")
    holdout = Column(Boolean, default=False)
    baseline_metric_json = Column(Text, default="{}")
    result_metric_json = Column(Text, default="{}")
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String, default="running")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CWVSnapshot(Base):
    __tablename__ = "cwv_snapshots"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    url = Column(String, default="")
    strategy = Column(String, default="mobile")
    lcp = Column(Float, nullable=True)
    inp = Column(Float, nullable=True)
    cls = Column(Float, nullable=True)
    performance_score = Column(Integer, nullable=True)
    tracked_date = Column(Date, nullable=True, index=True)
    error = Column(String, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ── 分類規劃、關鍵字配置 ─────────────────────────────────────

class CategorySEO(Base):
    __tablename__ = "category_seo"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    level2 = Column(String, default="")
    level3 = Column(String, default="")
    meta_keywords = Column(Text, default="")
    original_title = Column(String, default="")
    original_description = Column(Text, default="")
    new_title = Column(String, default="")
    new_description = Column(Text, default="")
    notes = Column(Text, default="")

    project = relationship("Project", back_populates="category_seos")

    def __repr__(self):
        return f"<CategorySEO '{self.level2}/{self.level3}'>"


# ── Shopify Changelog ─────────────────────────────────────────

class Changelog(Base):
    __tablename__ = "changelog"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    theme_version = Column(String, default="")
    filename = Column(String, default="")
    original_code = Column(Text, default="")
    new_code = Column(Text, default="")

    project = relationship("Project", back_populates="changelogs")

    def __repr__(self):
        return f"<Changelog '{self.filename}'>"


# ── Agent 決策日誌 ──────────────────────────────────────────────────

class AgentDecisionLog(Base):
    __tablename__ = "agent_decision_logs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True, index=True)
    run_id = Column(String, nullable=False, index=True)  # UUID
    step = Column(String, nullable=False)         # research / strategy / seo_check / ...
    decision = Column(Text, default="")           # 決策描述
    reason = Column(Text, default="")             # 理由
    confidence = Column(String, default="")       # data / heuristic / rule / verified
    metadata_json = Column(Text, default="{}")   # 額外資訊（JSON）
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", foreign_keys=[project_id])

    def __repr__(self):
        return f"<AgentDecisionLog run={self.run_id[:8]} step={self.step}>"


# ── 知識庫條目 ────────────────────────────────────────────────────

class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    category = Column(String, nullable=False)     # format_pattern / keyword_strategy / ...
    pattern = Column(Text, nullable=False)         # 學到的模式描述
    evidence_count = Column(Integer, default=0)   # 支持數據筆數
    confidence_level = Column(String, default="unverified")  # unverified / verified / universal
    metadata_json = Column(Text, default="{}")   # 統計數據（JSON）
    is_active = Column(Boolean, default=True)     # 人工可停用
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    audit_logs = relationship("KnowledgeAuditLog", back_populates="entry",
                              cascade="all, delete-orphan")

    def __repr__(self):
        return f"<KnowledgeEntry [{self.category}] {self.confidence_level}>"


class KnowledgeAuditLog(Base):
    """CF-05-08: 人工覆核軌跡 — 記錄知識條目被人工修改 / 停用 / 推翻的歷史"""
    __tablename__ = "knowledge_audit_logs"

    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("knowledge_entries.id"), nullable=False, index=True)
    action = Column(String, nullable=False)         # deactivate / reactivate / override / note
    reason = Column(Text, nullable=True)            # 人工填寫的理由
    old_value = Column(Text, nullable=True)         # 修改前的值（JSON）
    new_value = Column(Text, nullable=True)         # 修改後的值（JSON）
    operator = Column(String, default="human")      # 操作者（human / system）
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    entry = relationship("KnowledgeEntry", back_populates="audit_logs")

    def __repr__(self):
        return f"<KnowledgeAuditLog entry={self.entry_id} action={self.action}>"


# ── 排程执行日誌 ────────────────────────────────────────────────────

class SchedulerLog(Base):
    __tablename__ = "scheduler_logs"

    id = Column(Integer, primary_key=True)
    job_id = Column(String, nullable=False, index=True)  # APScheduler job ID
    job_name = Column(String, nullable=False)
    status = Column(String, nullable=False)       # success / failed / retrying
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<SchedulerLog job={self.job_name} status={self.status}>"


class OperationsHealthSnapshot(Base):
    """每日持久化 operations health 摘要，供 dashboard / 月報使用。"""
    __tablename__ = "operations_health_snapshots"

    id = Column(Integer, primary_key=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    snapshot_type = Column(String, default="daily", index=True)
    overall_status = Column(String, default="healthy")
    stale_sources = Column(Integer, default=0)
    scheduler_success_rate = Column(Float, nullable=True)
    pipeline_success_rate = Column(Float, nullable=True)
    outcome_improved_rate = Column(Float, nullable=True)
    alert_count = Column(Integer, default=0)
    summary_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self):
        return f"<OperationsHealthSnapshot {self.snapshot_date} status={self.overall_status}>"


# ── Topic Cluster 主題叢集 ──────────────────────────────────────────────

# ── Author（E-E-A-T 作者管理，SEO SOP §21）───────────────────────────────────

class Author(Base):
    __tablename__ = "authors"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    title = Column(String, default="")            # 職稱，例：骨科物理治療師
    bio = Column(Text, default="")
    credentials = Column(Text, default="")        # 資格認證，例：台灣物理治療師執照
    profile_url = Column(String, default="")      # 個人頁面 URL
    photo_url = Column(String, default="")        # 大頭照
    is_medical_reviewer = Column(Boolean, default=False)  # 是否為醫療審閱者
    reviewer_role = Column(String, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="authors")
    articles = relationship("Article", foreign_keys="[Article.author_id]", back_populates="author")

    def __repr__(self):
        return f"<Author '{self.name}' ({self.title})>"


# ── GA4 頁面指標持久化（SEO SOP §16）──────────────────────────────────────────

class GAPageMetric(Base):
    __tablename__ = "ga_page_metrics"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    page_path = Column(String, nullable=False, index=True)
    active_users = Column(Integer, default=0)
    sessions = Column(Integer, default=0)
    avg_engagement_time_sec = Column(Float, default=0.0)
    bounce_rate = Column(Float, default=0.0)      # 0.0 ~ 1.0
    conversions = Column(Integer, default=0)
    tracked_date = Column(Date, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="ga_page_metrics")

    def __repr__(self):
        return f"<GAPageMetric {self.page_path} {self.tracked_date}>"


# ── 競品排名快照（SEO SOP §19）──────────────────────────────────────────────

class CompetitorSnapshot(Base):
    __tablename__ = "competitor_snapshots"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    competitor_id = Column(Integer, ForeignKey("competitors.id"), nullable=True, index=True)
    keyword = Column(String, nullable=False, index=True)
    position = Column(Float, nullable=True)         # 競品在此關鍵字的排名
    url = Column(String, default="")                # 競品的排名 URL
    is_new_content = Column(Boolean, default=False) # 是否為本週新增文章
    our_position = Column(Float, nullable=True)     # 我方在同關鍵字的排名（可 NULL）
    tracked_date = Column(Date, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="competitor_snapshots")
    competitor = relationship("Competitor", back_populates="snapshots")

    def __repr__(self):
        return f"<CompetitorSnapshot kw='{self.keyword}' pos={self.position} {self.tracked_date}>"


class TopicCluster(Base):
    __tablename__ = "topic_clusters"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    pillar_keyword = Column(String, nullable=False)         # 支柱關鍵字
    slug = Column(String, default="", index=True)            # 語意化 URL（P1）
    pillar_title = Column(String, default="")               # 支柱頁建議標題
    pillar_article_id = Column(Integer, ForeignKey("articles.id"), nullable=True)
    status = Column(String, default="building")             # planned / building / complete
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    members = relationship("ClusterMember", back_populates="cluster")

    def __repr__(self):
        return f"<TopicCluster pillar='{self.pillar_keyword}' status={self.status}>"


class ClusterMember(Base):
    """叢集成員（衛星文章）"""
    __tablename__ = "cluster_members"

    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, ForeignKey("topic_clusters.id"), nullable=False, index=True)
    keyword = Column(String, nullable=False)                # 衛星關鍵字
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True)  # null = 尚未撰寫
    link_to_pillar = Column(Boolean, default=False)         # 是否已含連回 Pillar 的連結

    cluster = relationship("TopicCluster", back_populates="members")

    def __repr__(self):
        return f"<ClusterMember cluster={self.cluster_id} kw='{self.keyword}'>"


# ── Pipeline 執行記錄（強化版 B：Tactical 層 checkpoint）──────────────────────

class PipelineRun(Base):
    """每次 pipeline 執行的持久化記錄，支援中途崩潰後 debug 與未來 resume。"""
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True)
    run_id = Column(String, nullable=False, unique=True, index=True)  # UUID
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True, index=True)
    calendar_id = Column(Integer, ForeignKey("content_calendar.id"), nullable=True)
    strategic_plan_id = Column(Integer, ForeignKey("strategic_plans.id"), nullable=True, index=True)
    trigger = Column(String, default="manual")              # manual / scheduler / strategic_agent
    current_step = Column(String, default="pending")        # pending / research / strategy / ... / completed / failed
    status = Column(String, default="running")              # running / completed / failed
    state_json = Column(Text, default="{}")                 # checkpoint 的 pipeline 可序列化狀態
    error_message = Column(Text, nullable=True)
    total_llm_calls = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    seo_score = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<PipelineRun {self.run_id[:8]} step={self.current_step} status={self.status}>"


# ── Strategic Agent 執行計畫（強化版 B：Strategic 層）──────────────────────────

class StrategicPlan(Base):
    """Strategic Agent 每日/每週產出的執行計畫，供 Tactical Pipeline 消費。"""
    __tablename__ = "strategic_plans"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    plan_date = Column(Date, nullable=False, index=True)    # 計畫日期
    plan_type = Column(String, default="daily")             # daily / weekly / quarterly
    actions_json = Column(Text, default="[]")               # JSON array: [{action, target_id, reason, priority}]
    summary = Column(Text, default="")                      # LLM 產出的自然語言摘要
    context_snapshot = Column(Text, default="{}")            # 決策時的數據快照（排名、日曆、知識庫摘要）
    executed_count = Column(Integer, default=0)              # 已執行幾項 action
    total_count = Column(Integer, default=0)                 # 總共幾項 action
    status = Column(String, default="pending")              # pending / executing / completed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<StrategicPlan {self.plan_date} type={self.plan_type} status={self.status}>"


class StrategicFeedbackLog(Base):
    """人工覆核 / 預覽 / override 的 strategic action 回饋軌跡。"""
    __tablename__ = "strategic_feedback_logs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    strategic_plan_id = Column(Integer, ForeignKey("strategic_plans.id"), nullable=False, index=True)
    action_index = Column(Integer, nullable=False)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True, index=True)
    action_type = Column(String, nullable=False, index=True)
    feedback_type = Column(String, default="review")
    review_status = Column(String, default="pending")
    note = Column(Text, default="")
    payload_json = Column(Text, default="{}")
    promoted_asset_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    project = relationship("Project")
    plan = relationship("StrategicPlan")
    article = relationship("Article")

    def __repr__(self):
        return f"<StrategicFeedbackLog plan={self.strategic_plan_id} idx={self.action_index} type={self.feedback_type}>"


# ── Reflective Loop 執行摘要（強化版 B：Reflective 層）────────────────────────

class ReflectionLog(Base):
    """Pipeline 完成後的反思記錄：LLM 分析結果 → 學習洞察 → 知識更新建議。"""
    __tablename__ = "reflection_logs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    run_id = Column(String, nullable=True, index=True)      # 對應 PipelineRun.run_id
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True)
    reflection_type = Column(String, default="post_pipeline")  # post_pipeline / weekly_review / human_edit
    insights_json = Column(Text, default="[]")               # 發現的洞察 [{type, observation, action, confidence}]
    knowledge_updates = Column(Integer, default=0)           # 本次更新了幾條 KnowledgeEntry
    writing_rule_updates = Column(Integer, default=0)        # 本次更新了幾條 WritingRule
    session_summary = Column(Text, default="")               # 壓縮摘要（供下次 Agent 讀取）
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<ReflectionLog run={self.run_id[:8] if self.run_id else '—'} type={self.reflection_type}>"


# ── Action Outcome Tracking（因果閉環：追蹤每個動作的 7/14/28 天成效）───────

class ActionOutcome(Base):
    """記錄每個 SEO 動作（generate / refresh / rewrite）的前後成效對比。

    由 scheduler cron job 在 7d / 14d / 28d 時自動回填 GSC 排名數據，
    供 Strategic Agent 學習哪類動作真正有效。
    """
    __tablename__ = "action_outcomes"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    run_id = Column(String, nullable=True, index=True)          # 對應 PipelineRun.run_id
    strategic_plan_id = Column(Integer, ForeignKey("strategic_plans.id"), nullable=True)

    action_type = Column(String, nullable=False)                # generate / refresh / rewrite
    action_date = Column(Date, nullable=False, index=True)      # 動作執行日期
    primary_keyword = Column(String, nullable=False)            # 追蹤的主要關鍵字

    # 基線（動作執行時的 GSC 數據）
    baseline_rank = Column(Float, nullable=True)                # 動作前排名（NULL = 全新文章）
    baseline_impressions = Column(Integer, nullable=True)
    baseline_clicks = Column(Integer, nullable=True)
    baseline_ctr = Column(Float, nullable=True)

    # 7 天後追蹤
    rank_after_7d = Column(Float, nullable=True)
    impressions_after_7d = Column(Integer, nullable=True)
    clicks_after_7d = Column(Integer, nullable=True)
    ctr_after_7d = Column(Float, nullable=True)
    checked_7d_at = Column(DateTime, nullable=True)

    # 14 天後追蹤
    rank_after_14d = Column(Float, nullable=True)
    impressions_after_14d = Column(Integer, nullable=True)
    clicks_after_14d = Column(Integer, nullable=True)
    ctr_after_14d = Column(Float, nullable=True)
    checked_14d_at = Column(DateTime, nullable=True)

    # 28 天後追蹤
    rank_after_28d = Column(Float, nullable=True)
    impressions_after_28d = Column(Integer, nullable=True)
    clicks_after_28d = Column(Integer, nullable=True)
    ctr_after_28d = Column(Float, nullable=True)
    checked_28d_at = Column(DateTime, nullable=True)

    # 成效判定
    success_flag = Column(String, nullable=True)                # improved / stable / declined / too_early
    rank_delta = Column(Float, nullable=True)                   # 28d 排名變化（負值 = 進步）
    learning_confidence = Column(String, default="low")         # low / medium / high

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project")
    article = relationship("Article")
    evaluation = relationship("ActionOutcomeEvaluation", back_populates="outcome", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ActionOutcome {self.action_type} kw='{self.primary_keyword}' {self.success_flag or 'pending'}>"


class ActionOutcomeEvaluation(Base):
    """持久化 28 天成效評估快照，保留同專案控制基準與淨改善。"""
    __tablename__ = "action_outcome_evaluations"

    id = Column(Integer, primary_key=True)
    action_outcome_id = Column(Integer, ForeignKey("action_outcomes.id"), nullable=False, unique=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    action_type = Column(String, nullable=False, index=True)
    evaluation_window_days = Column(Integer, default=28)
    outcome_weight = Column(Float, nullable=True)

    rank_delta = Column(Float, nullable=True)
    click_delta = Column(Float, nullable=True)
    ctr_delta = Column(Float, nullable=True)

    control_rank_delta_median = Column(Float, nullable=True)
    control_click_delta_median = Column(Float, nullable=True)
    control_ctr_delta_median = Column(Float, nullable=True)

    rank_advantage_vs_baseline = Column(Float, nullable=True)
    click_advantage_vs_baseline = Column(Float, nullable=True)
    ctr_advantage_vs_baseline = Column(Float, nullable=True)
    control_adjustment = Column(Float, nullable=True)

    evaluated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    outcome = relationship("ActionOutcome", back_populates="evaluation")
    project = relationship("Project")
    article = relationship("Article")

    def __repr__(self):
        return f"<ActionOutcomeEvaluation outcome={self.action_outcome_id} adj={self.control_adjustment}>"


# ── 反向連結快照（SEO SOP 反向連結監控）─────────────────────────────────────────

class BacklinkSnapshot(Base):
    """DataForSEO 反向連結摘要快照，每週同步一次。"""
    __tablename__ = "backlink_snapshots"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    target_url = Column(String, nullable=False)                  # 被連結的目標 URL（品牌域名）
    total_backlinks = Column(Integer, default=0)                 # 反向連結總數
    referring_domains = Column(Integer, default=0)               # 引薦域名數
    new_backlinks = Column(Integer, default=0)                   # 本週新增反向連結
    lost_backlinks = Column(Integer, default=0)                  # 本週失去反向連結
    domain_rank = Column(Float, nullable=True)                   # 目標域名評分（DataForSEO DR）
    broken_backlinks = Column(Integer, default=0)                # 指向 4xx/5xx 頁面的反向連結
    nofollow_backlinks = Column(Integer, default=0)              # nofollow 反向連結數
    dofollow_backlinks = Column(Integer, default=0)              # dofollow 反向連結數
    top_anchors_json = Column(Text, default="[]")                # 前 10 錨文字（JSON 陣列）
    top_referring_domains_json = Column(Text, default="[]")      # 前 10 引薦域名（JSON 陣列）
    tracked_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="backlink_snapshots")

    def __repr__(self):
        return f"<BacklinkSnapshot project={self.project_id} domains={self.referring_domains} {self.tracked_date}>"


# ── Google 商家檔案指標（GBP 整合）──────────────────────────────────────────────

class GoogleBusinessMetric(Base):
    """Google Business Profile 每日指標快照（本地 SEO 監控）。"""
    __tablename__ = "google_business_metrics"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    location_id = Column(String, nullable=False, index=True)     # GBP location ID（數字字串）
    location_name = Column(String, default="")                   # 商家名稱
    views_search = Column(Integer, default=0)                    # Google 搜尋曝光次數
    views_maps = Column(Integer, default=0)                      # Google 地圖曝光次數
    clicks_website = Column(Integer, default=0)                  # 點擊官網次數
    clicks_phone = Column(Integer, default=0)                    # 點擊電話次數
    clicks_directions = Column(Integer, default=0)               # 點擊導航次數
    reviews_total = Column(Integer, default=0)                   # 累計評論數
    reviews_avg_rating = Column(Float, nullable=True)            # 平均評分 1.0-5.0
    new_reviews = Column(Integer, default=0)                     # 本期新增評論
    tracked_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="gbp_metrics")

    def __repr__(self):
        return f"<GoogleBusinessMetric loc={self.location_id} views={self.views_search + self.views_maps} {self.tracked_date}>"
