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
    industry = Column(String, default="")
    writing_principles = Column(Text, default="")

    # SERP & 地區
    locale = Column(String, default="zh-tw")
    serp_gl = Column(String, default="tw")
    serp_hl = Column(String, default="zh-tw")

    # Phase 0 — 商業目標 & 受眾（SEO SOP §2）
    business_goals = Column(Text, default="")          # 品牌知名度 / 導購 / 收集名單
    target_audience_json = Column(Text, default="{}")  # JSON: persona_name, age_range, pain_points...
    ga4_property_id = Column(String, default="")       # GA4 Property ID for this project

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

    def __repr__(self):
        return f"<Project '{self.slug}' ({self.name})>"


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
    # Phase 5/21 — E-E-A-T & 優化迭代
    author_id = Column(Integer, ForeignKey("authors.id"), nullable=True)
    eeat_score = Column(Integer, nullable=True)     # E-E-A-T 綜合評分 0-100
    last_refresh_date = Column(DateTime, nullable=True)  # 最近一次 Content Refresh
    factcheck_flags_json = Column(Text, default="[]")    # FactCheck 高風險標記
    suggested_internal_links = Column(Text, default="[]")  # AI 建議的內部連結
    scheduled_publish_at = Column(DateTime, nullable=True)  # 排程發布時間
    wp_post_id = Column(String, default="")         # WordPress post ID
    forgebase_id = Column(String, default="")       # ForgeBase page ID
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    calendar_entry = relationship("ContentCalendar", back_populates="article", uselist=False)
    project = relationship("Project", back_populates="articles")
    author = relationship("Author", back_populates="articles")

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="authors")
    articles = relationship("Article", back_populates="author")

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
