import json
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contentflow.admin.app import admin_app
from contentflow.models.database import AgentDecisionLog, Article, Author, Base, KnowledgeEntry, PipelineRun, Project, ProjectAuditLog, ProjectIntegration, StrategicFeedbackLog, StrategicPlan
from contentflow.project_integrations import IntegrationDiagnostic, resolve_wordpress_settings


client = TestClient(admin_app)


def _make_threadsafe_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def test_chat_api_requires_login():
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 403


def test_chat_api_returns_chat_agent_response_when_logged_in():
    with patch("contentflow.admin.app._check_login", return_value=True), \
         patch("contentflow.agents.chat_agent.chat", new=AsyncMock(return_value={
             "role": "assistant",
             "content": "ok",
             "tool_calls_count": 0,
         })):
        response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})

    assert response.status_code == 200
    assert response.json()["content"] == "ok"


def test_strategic_plans_page_renders_evidence_card_when_logged_in():
    plan = StrategicPlan(
        project_id=1,
        plan_date=date.today(),
        plan_type="daily",
        actions_json=json.dumps([
            {
                "action": "refresh",
                "keyword": "膝蓋骨刺",
                "priority": 2,
                "reason": "排名下滑",
                "evidence": {
                    "summary": "排名下滑且存在 GSC query gap",
                    "primary_signals": [{"label": "排名變化", "value": "P8 -> P15"}],
                    "thresholds_triggered": ["排名下滑 >= 5 位"],
                    "counter_signals": [],
                    "expected_outcome": "28 天內改善排名或 CTR",
                    "confidence": "high",
                },
            }
        ], ensure_ascii=False),
        context_snapshot=json.dumps({}, ensure_ascii=False),
        total_count=1,
        executed_count=0,
        status="pending",
    )
    plan.id = 1

    class _FakeQuery:
        def __init__(self, rows=None, count_value=0):
            self._rows = rows or []
            self._count_value = count_value

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def group_by(self, *args, **kwargs):
            return self

        def all(self):
            return self._rows

        def count(self):
            return self._count_value

    class _FakeDB:
        def query(self, *entities):
            if len(entities) == 1 and entities[0] is StrategicPlan:
                return _FakeQuery([plan], 1)
            return _FakeQuery([], 0)

        def close(self):
            return None

    with patch("contentflow.admin.app._check_login", return_value=True), \
         patch("contentflow.admin.app._db", return_value=_FakeDB()):
        response = client.get("/strategic-plans")

    assert response.status_code == 200
    assert "查看 evidence card" in response.text
    assert "排名下滑且存在 GSC query gap" in response.text


def test_health_page_renders_operations_dashboard_when_logged_in():
    class _FakeQuery:
        def __init__(self, rows=None, count_value=0, scalar_value=0):
            self._rows = rows or []
            self._count_value = count_value
            self._scalar_value = scalar_value

        def order_by(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def group_by(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def all(self):
            return self._rows

        def count(self):
            return self._count_value

        def scalar(self):
            return self._scalar_value

    class _FakeDB:
        def query(self, *entities):
            return _FakeQuery([], 0, 0)

        def close(self):
            return None

    operations_health = {
        "summary_cards": [
            type("Card", (), {"title": "資料新鮮度異常", "value": 2, "tone": "danger"})(),
            type("Card", (), {"title": "Scheduler 7d 成功率", "value": "80%", "tone": "warning"})(),
        ],
        "freshness_items": [
            type("Item", (), {
                "name": "GSC 同步",
                "detail": "2026-05-09",
                "metric": "72h",
                "tone": "danger",
                "label": "異常",
            })(),
        ],
        "execution_items": [
            type("Item", (), {
                "name": "Scheduler 7d 成功率",
                "detail": "成功 8 / 失敗 2",
                "metric": "80%",
                "tone": "warning",
                "label": "注意",
            })(),
        ],
        "outcome_items": [
            type("Item", (), {
                "name": "refresh",
                "detail": "improved 1 / stable 0 / declined 2",
                "metric": "33%",
                "tone": "danger",
                "label": "異常",
            })(),
        ],
        "alerts": [
            type("Alert", (), {"level": "critical", "message": "GSC 同步 超過新鮮度門檻：2026-05-09"})(),
        ],
    }

    with patch("contentflow.admin.app._check_login", return_value=True), \
         patch("contentflow.admin.app._db", return_value=_FakeDB()), \
         patch("contentflow.admin.app._get_agent_cost_metrics", return_value={
             "avg_run_cost": None,
             "monthly_cost": 0,
             "total_cost": 0,
             "run_costs": {},
         }), \
         patch("contentflow.admin.app._build_operations_health", return_value=operations_health), \
         patch("contentflow.admin.app.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
        response = client.get("/health")

    assert response.status_code == 200
    assert "Operations Dashboard" in response.text
    assert "Active Alerts" in response.text
    assert "GSC 同步 超過新鮮度門檻" in response.text
    assert "成效健康" in response.text


def test_agents_page_renders_when_logged_in():
    class _FakeQuery:
        def __init__(self, rows=None, scalar_value=0):
            self._rows = rows or []
            self._scalar_value = scalar_value

        def order_by(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def group_by(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

        def scalar(self):
            return self._scalar_value

    class _Decision:
        def __init__(self, step, confidence):
            self.step = step
            self.confidence = confidence

    class _FakeDB:
        def query(self, *entities):
            if len(entities) == 5:
                return _FakeQuery([])
            if len(entities) == 1 and entities[0] is Project:
                return _FakeQuery([])
            if len(entities) == 1:
                entity = entities[0]
                if entity is Article:
                    return _FakeQuery([])
                if entity is AgentDecisionLog:
                    return _FakeQuery([
                        _Decision("research", "high"),
                        _Decision("writing", "medium"),
                    ])
            return _FakeQuery([], 0)

        def close(self):
            return None

    with patch("contentflow.admin.app._check_login", return_value=True), \
         patch("contentflow.admin.app._db", return_value=_FakeDB()), \
         patch("contentflow.admin.app._get_agent_cost_metrics", return_value={
             "avg_run_cost": None,
             "monthly_cost": 0,
             "total_cost": 0,
             "run_costs": {},
         }):
        response = client.get("/agents")

    assert response.status_code == 200
    assert "Agent 執行中心" in response.text
    assert "觸發 Pipeline" in response.text
    assert "Pipeline 執行紀錄" in response.text


def test_article_detail_publish_button_uses_site_name():
    class _FakeQuery:
        def __init__(self, rows=None):
            self._rows = rows or []

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

    article = Article(
        id=1,
        title="測試文章",
        status="reviewing",
        primary_keyword="骨科",
        draft_content="# 測試\n\n內容",
    )

    class _FakeDB:
        def query(self, *entities):
            if len(entities) == 1 and entities[0] is Article:
                return _FakeQuery([article])
            return _FakeQuery([])

        def close(self):
            return None

    with patch("contentflow.admin.app._check_login", return_value=True), \
         patch("contentflow.admin.app._db", return_value=_FakeDB()), \
         patch("contentflow.admin.app.settings.site_name", "Client Knowledge Hub"):
        response = client.get("/articles/1")

    assert response.status_code == 200
    assert "批准並發佈到 Client Knowledge Hub" in response.text


def test_save_project_goals_persists_goal_weight_schema():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="testbrand", name="測試品牌")
        session.add(project)
        session.commit()
        project_id = project.id

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.post(
                "/settings/project/goals/save",
                data={
                    "project_id": project_id,
                    "primary_goal": "conversion",
                    "secondary_goal": "authority",
                    "goal_awareness_weight": "0.25",
                    "goal_conversion_weight": "0.45",
                    "goal_lead_capture_weight": "0.15",
                    "goal_authority_weight": "0.15",
                    "priority_topics": "膝蓋骨刺\n退化性關節炎",
                    "money_pages": "/products/joint-care",
                },
                follow_redirects=False,
            )

        session.expire_all()
        saved = json.loads(session.get(Project, project_id).business_goals)
        assert response.status_code == 303
        assert saved["weights"]["awareness"] == 0.25
        assert saved["weights"]["conversion"] == 0.45
        assert saved["weights"]["lead_capture"] == 0.15
        assert saved["weights"]["authority"] == 0.15
    finally:
        session.close()
        engine.dispose()


def test_save_project_persists_site_profile_fields():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="testbrand", name="測試品牌")
        session.add(project)
        session.commit()
        project_id = project.id

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.post(
                "/settings/project/save",
                data={
                    "project_id": project_id,
                    "slug": "testbrand",
                    "name": "測試品牌",
                    "brand_name": "Client Knowledge Hub",
                    "brand_url": "https://client.example",
                    "brand_description": "客戶品牌描述",
                    "site_contact_email": "team@client.example",
                    "site_blog_path": "/insights",
                    "industry": "醫療",
                    "writing_principles": "清楚、可信",
                    "serp_gl": "tw",
                    "serp_hl": "zh-tw",
                    "business_goals": "",
                    "target_audience": "",
                    "ga4_property_id": "GA4-123",
                },
                follow_redirects=False,
            )

        session.expire_all()
        saved = session.get(Project, project_id)
        audits = session.query(ProjectAuditLog).filter(ProjectAuditLog.project_id == project_id).all()
        assert response.status_code == 303
        assert saved.site_contact_email == "team@client.example"
        assert saved.site_blog_path == "/insights"
        assert saved.brand_url == "https://client.example"
        assert any(log.action_type == "project_profile_updated" for log in audits)
    finally:
        session.close()
        engine.dispose()


def test_save_project_returns_404_for_missing_project_id():
    session, engine = _make_threadsafe_session()
    try:
        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.post(
                "/settings/project/save",
                data={
                    "project_id": 999,
                    "slug": "missing-project",
                    "name": "不存在的專案",
                    "brand_name": "Missing Project",
                    "brand_url": "https://missing.example",
                    "brand_description": "missing",
                    "site_contact_email": "team@missing.example",
                    "site_blog_path": "/blog",
                    "industry": "醫療",
                    "writing_principles": "清楚",
                    "serp_gl": "tw",
                    "serp_hl": "zh-tw",
                    "business_goals": "",
                    "target_audience": "",
                    "ga4_property_id": "",
                },
                follow_redirects=False,
            )

        assert response.status_code == 404
    finally:
        session.close()
        engine.dispose()


def test_save_project_persists_policy_profile_fields():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="policy-brand", name="Policy Brand")
        session.add(project)
        session.commit()
        project_id = project.id

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.post(
                "/settings/project/save",
                data={
                    "project_id": project_id,
                    "slug": "policy-brand",
                    "name": "Policy Brand",
                    "brand_name": "Policy Brand",
                    "brand_url": "https://policy.example",
                    "brand_description": "法律知識品牌",
                    "site_contact_email": "team@policy.example",
                    "site_blog_path": "/insights",
                    "industry": "法律",
                    "writing_principles": "清楚、保守",
                    "domain_profile": "law",
                    "compliance_profile": "ymyl_legal",
                    "default_content_format": "comparison",
                    "reviewer_role_label": "法律審閱",
                    "disclaimer_template": "本文僅供一般參考。",
                    "evidence_policy": "manual_reference",
                    "image_style_override": "Formal editorial illustration.",
                    "extra_schema_types_json": "FAQPage, Article",
                    "factcheck_mode_override": "strict",
                    "serp_gl": "tw",
                    "serp_hl": "zh-tw",
                    "business_goals": "",
                    "target_audience": "",
                    "ga4_property_id": "",
                },
                follow_redirects=False,
            )

        session.expire_all()
        saved = session.get(Project, project_id)
        assert response.status_code == 303
        assert saved.domain_profile == "law"
        assert saved.compliance_profile == "ymyl_legal"
        assert saved.default_content_format == "comparison"
        assert json.loads(saved.extra_schema_types_json) == ["FAQPage", "Article"]
        assert saved.factcheck_mode_override == "strict"
    finally:
        session.close()
        engine.dispose()


def test_save_project_integration_persists_connector():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="connector-brand", name="Connector Brand")
        session.add(project)
        session.commit()
        project_id = project.id

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.post(
                "/settings/project/integration/save",
                data={
                    "project_id": project_id,
                    "integration_type": "wordpress",
                    "label": "Client WP",
                    "base_url": "https://wp.client.example",
                    "username": "editor",
                    "secret_value": "app-pass",
                    "seo_plugin": "rankmath",
                    "publish_mode": "publish",
                    "is_enabled": "on",
                },
                follow_redirects=False,
            )

        rows = session.query(ProjectIntegration).all()
        audits = session.query(ProjectAuditLog).filter(ProjectAuditLog.project_id == project_id).all()
        assert response.status_code == 303
        assert len(rows) == 1
        assert rows[0].integration_type == "wordpress"
        assert rows[0].base_url == "https://wp.client.example"
        assert rows[0].username == "editor"
        assert rows[0].is_enabled is True
        assert any(log.action_type == "integration_saved" for log in audits)
    finally:
        session.close()
        engine.dispose()


def test_save_project_integration_blank_secret_preserves_existing_value_and_settings_hides_it():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="connector-brand", name="Connector Brand")
        session.add(project)
        session.flush()
        project_id = project.id
        session.add(ProjectIntegration(
            project_id=project_id,
            integration_type="wordpress",
            label="Client WP",
            base_url="https://wp.client.example",
            username="editor",
            secret_value="app-pass",
            seo_plugin="rankmath",
            publish_mode="publish",
            is_enabled=True,
        ))
        session.commit()

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.post(
                "/settings/project/integration/save",
                data={
                    "project_id": project_id,
                    "integration_type": "wordpress",
                    "label": "Client WP",
                    "base_url": "https://wp.client.example",
                    "username": "editor-updated",
                    "secret_value": "",
                    "seo_plugin": "rankmath",
                    "publish_mode": "publish",
                    "is_enabled": "on",
                },
                follow_redirects=False,
            )
            page = client.get(f"/settings?project_id={project_id}")

        session.expire_all()
        row = session.query(ProjectIntegration).filter(ProjectIntegration.project_id == project_id).first()
        assert response.status_code == 303
        assert row is not None
        assert row.username == "editor-updated"
        assert row.secret_value == "app-pass"
        assert page.status_code == 200
        assert "app-pass" not in page.text
        assert "留空則保留既有密鑰" in page.text
    finally:
        session.close()
        engine.dispose()


def test_save_project_integration_encrypts_secret_when_key_is_configured():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="connector-brand", name="Connector Brand")
        session.add(project)
        session.commit()
        project_id = project.id

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session), \
             patch("contentflow.admin.app.settings.connector_secret_key", "connector-test-key"):
            response = client.post(
                "/settings/project/integration/save",
                data={
                    "project_id": project_id,
                    "integration_type": "wordpress",
                    "label": "Client WP",
                    "base_url": "https://wp.client.example",
                    "username": "editor",
                    "secret_value": "app-pass",
                    "seo_plugin": "rankmath",
                    "publish_mode": "publish",
                    "is_enabled": "on",
                },
                follow_redirects=False,
            )

        session.expire_all()
        row = session.query(ProjectIntegration).filter(ProjectIntegration.project_id == project_id).first()
        with patch("contentflow.project_integrations.settings.connector_secret_key", "connector-test-key"):
            cfg = resolve_wordpress_settings(db=session, project_id=project_id)

        assert response.status_code == 303
        assert row is not None
        assert row.secret_value != "app-pass"
        assert row.secret_value.startswith("cfsec:v1:")
        assert cfg.secret_value == "app-pass"
    finally:
        session.close()
        engine.dispose()


def test_preview_strategic_action_persists_preview_and_feedback_log():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="preview-brand", name="測試品牌")
        session.add(project)
        session.flush()
        plan = StrategicPlan(
            project_id=project.id,
            plan_date=date.today(),
            plan_type="daily",
            actions_json=json.dumps([
                {"action": "refresh", "article_id": 1, "priority": 2}
            ], ensure_ascii=False),
            context_snapshot=json.dumps({"article_lookup": {"1": {"publish_path": "/products/joint-care"}}}, ensure_ascii=False),
            total_count=1,
            executed_count=0,
            status="pending",
        )
        session.add(plan)
        session.commit()
        plan_id = plan.id

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session), \
             patch("contentflow.admin.app._generate_action_preview", new=AsyncMock(return_value={"preview_type": "refresh", "diff": "demo"})):
            response = client.post(
                f"/strategic-plans/{plan_id}/actions/0/preview",
                data={"redirect_to": "/admin/strategic-plans"},
                follow_redirects=False,
            )

        session.expire_all()
        saved_actions = json.loads(session.get(StrategicPlan, plan_id).actions_json)
        feedback_logs = session.query(StrategicFeedbackLog).all()
        assert response.status_code == 303
        assert saved_actions[0]["preview"]["diff"] == "demo"
        assert len(feedback_logs) == 1
        assert feedback_logs[0].feedback_type == "preview"
    finally:
        session.close()
        engine.dispose()


def test_review_strategic_action_promotes_knowledge_feedback():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="review-brand", name="測試品牌")
        session.add(project)
        session.flush()
        plan = StrategicPlan(
            project_id=project.id,
            plan_date=date.today(),
            plan_type="daily",
            actions_json=json.dumps([
                {"action": "refresh", "article_id": 1, "priority": 2, "review_required": True}
            ], ensure_ascii=False),
            context_snapshot=json.dumps({}, ensure_ascii=False),
            total_count=1,
            executed_count=0,
            status="pending",
        )
        session.add(plan)
        session.commit()
        plan_id = plan.id

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.post(
            f"/strategic-plans/{plan_id}/actions/0/review",
                data={
                    "review_status": "approved",
                    "review_note": "這個 refresh 需保留產品頁 CTA",
                    "promote_to_asset": "on",
                    "asset_type": "knowledge_entry",
                    "feedback_type": "review",
                    "redirect_to": "/admin/strategic-plans",
                },
                follow_redirects=False,
            )

        session.expire_all()
        saved_actions = json.loads(session.get(StrategicPlan, plan_id).actions_json)
        feedback_logs = session.query(StrategicFeedbackLog).all()
        knowledge_entries = session.query(KnowledgeEntry).all()
        assert response.status_code == 303
        assert saved_actions[0]["review_status"] == "approved"
        assert len(feedback_logs) == 1
        assert feedback_logs[0].promoted_asset_type == "knowledge_entry"
        assert len(knowledge_entries) == 1
        assert "CTA" in knowledge_entries[0].pattern
    finally:
        session.close()
        engine.dispose()


def test_login_submit_sets_reviewer_role_in_session_context():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="role-brand", name="Role Brand")
        session.add(project)
        session.commit()

        with TestClient(admin_app) as role_client, \
             patch("contentflow.admin.app.settings.api_secret_key", "owner-secret"), \
             patch("contentflow.admin.app.settings.admin_reviewer_secret", "reviewer-secret"), \
             patch("contentflow.admin.app.settings.admin_editor_secret", "editor-secret"), \
             patch("contentflow.admin.app._db", return_value=session):
            login_response = role_client.post("/login", data={"password": "reviewer-secret"}, follow_redirects=False)
            response = role_client.get(f"/settings?project_id={project.id}")

        assert login_response.status_code == 303
        assert response.status_code == 200
        assert "目前登入角色" in response.text
        assert "reviewer" in response.text
    finally:
        session.close()
        engine.dispose()


def test_review_strategic_action_requires_reviewer_role():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="editor-brand", name="Editor Brand")
        session.add(project)
        session.flush()
        plan = StrategicPlan(
            project_id=project.id,
            plan_date=date.today(),
            plan_type="daily",
            actions_json=json.dumps([
                {"action": "refresh", "article_id": 1, "priority": 2, "review_required": True}
            ], ensure_ascii=False),
            context_snapshot=json.dumps({}, ensure_ascii=False),
            total_count=1,
            executed_count=0,
            status="pending",
        )
        session.add(plan)
        session.commit()

        with TestClient(admin_app) as role_client, \
             patch("contentflow.admin.app.settings.api_secret_key", "owner-secret"), \
             patch("contentflow.admin.app.settings.admin_reviewer_secret", "reviewer-secret"), \
             patch("contentflow.admin.app.settings.admin_editor_secret", "editor-secret"), \
             patch("contentflow.admin.app._db", return_value=session):
            role_client.post("/login", data={"password": "editor-secret"}, follow_redirects=False)
            response = role_client.post(
                f"/strategic-plans/{plan.id}/actions/0/review",
                data={
                    "review_status": "approved",
                    "review_note": "editor should not review",
                    "redirect_to": "/strategic-plans",
                },
                follow_redirects=False,
            )

        assert response.status_code == 403
    finally:
        session.close()
        engine.dispose()


def test_project_integration_test_updates_health_and_audit():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="diagnostic-brand", name="Diagnostic Brand")
        session.add(project)
        session.flush()
        project_id = project.id
        session.add(ProjectIntegration(
            project_id=project_id,
            integration_type="wordpress",
            base_url="https://wp.client.example",
            username="editor",
            secret_value="app-pass",
            is_enabled=True,
        ))
        session.commit()

        with TestClient(admin_app) as role_client, \
             patch("contentflow.admin.app.settings.api_secret_key", "owner-secret"), \
             patch("contentflow.admin.app.settings.admin_reviewer_secret", "reviewer-secret"), \
             patch("contentflow.admin.app._db", return_value=session), \
             patch(
                 "contentflow.admin.app.run_integration_diagnostic",
                 new=AsyncMock(return_value=IntegrationDiagnostic(
                     integration_type="wordpress",
                     status="healthy",
                     checked_url="https://wp.client.example/wp-json/wp/v2/posts?per_page=1&_fields=id",
                     message="WordPress API 連線成功",
                     source="project",
                     configured=True,
                 )),
             ):
            role_client.post("/login", data={"password": "reviewer-secret"}, follow_redirects=False)
            response = role_client.post(
                "/settings/project/integration/test",
                data={"project_id": project_id, "integration_type": "wordpress"},
                follow_redirects=False,
            )

        session.expire_all()
        row = session.query(ProjectIntegration).filter(ProjectIntegration.project_id == project_id).first()
        audits = session.query(ProjectAuditLog).filter(ProjectAuditLog.project_id == project_id).all()
        assert response.status_code == 303
        assert row.health_status == "healthy"
        assert row.last_checked_at is not None
        assert any(log.action_type == "integration_tested" for log in audits)
    finally:
        session.close()
        engine.dispose()


def test_settings_page_renders_usage_report_cards():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="usage-brand", name="Usage Brand")
        session.add(project)
        session.flush()
        session.add(PipelineRun(
            run_id="run-1",
            project_id=project.id,
            trigger="manual",
            current_step="completed",
            status="completed",
            total_llm_calls=9,
            total_cost=0.75,
            seo_score=91,
            started_at=datetime.now(timezone.utc),
        ))
        session.add(AgentDecisionLog(
            project_id=project.id,
            article_id=None,
            run_id="run-1",
            step="writing",
            decision="generated draft",
            reason="test",
            confidence="high",
            metadata_json="{}",
            created_at=datetime.now(timezone.utc),
        ))
        session.commit()

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.get(f"/settings?project_id={project.id}")

        assert response.status_code == 200
        assert "平台用量" in response.text
        assert "$0.7500" in response.text
        assert "writing" in response.text
        assert "Billing Basis" in response.text
    finally:
        session.close()
        engine.dispose()


def test_settings_page_renders_onboarding_and_approval_history_sections():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(
            slug="ops-brand",
            name="Ops Brand",
            brand_url="https://ops.example",
            site_contact_email="team@ops.example",
            site_blog_path="/insights",
        )
        session.add(project)
        session.flush()
        session.add(ProjectIntegration(
            project_id=project.id,
            integration_type="wordpress",
            label="Ops WP",
            base_url="https://wp.ops.example",
            username="editor",
            secret_value="secret",
            is_enabled=True,
        ))
        session.add(ProjectAuditLog(
            project_id=project.id,
            actor="owner",
            action_type="integration_saved",
            summary="更新 wordpress connector",
            payload_json=json.dumps({"base_url": "https://wp.ops.example"}, ensure_ascii=False),
            created_at=datetime.now(timezone.utc),
        ))
        plan = StrategicPlan(
            project_id=project.id,
            plan_date=date.today(),
            plan_type="daily",
            actions_json="[]",
            context_snapshot="{}",
            total_count=0,
            executed_count=0,
            status="pending",
        )
        session.add(plan)
        session.flush()
        session.add(StrategicFeedbackLog(
            project_id=project.id,
            strategic_plan_id=plan.id,
            action_index=0,
            article_id=None,
            action_type="refresh",
            feedback_type="review",
            review_status="approved",
            note="核准 refresh",
            payload_json=json.dumps({"reason": "SERP 下滑"}, ensure_ascii=False),
            created_at=datetime.now(timezone.utc),
        ))
        session.commit()

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.get(f"/settings?project_id={project.id}")

        assert response.status_code == 200
        assert "Onboarding Wizard" in response.text
        assert "Connector Setup Wizard" in response.text
        assert "Approval History" in response.text
        assert "查看 payload" in response.text
        assert "核准 refresh" in response.text
    finally:
        session.close()
        engine.dispose()


def test_settings_page_renders_policy_preview_section():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(
            slug="legal-brand",
            name="Legal Brand",
            industry="法律",
            domain_profile="law",
            compliance_profile="ymyl_legal",
            default_content_format="comparison",
            reviewer_role_label="法律審閱",
            disclaimer_template="本文不構成法律意見。",
        )
        session.add(project)
        session.commit()

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.get(f"/settings?project_id={project.id}")

        assert response.status_code == 200
        assert "Policy Setup" in response.text
        assert "Effective Policy Preview" in response.text
        assert "YMYL Legal" in response.text
    finally:
        session.close()
        engine.dispose()


def test_api_app_does_not_mount_site_in_control_plane_mode():
    with patch("contentflow.config.settings.managed_site_enabled", False), \
         patch("contentflow.config.settings.platform_mode", "control-plane"):
        from importlib import reload
        import contentflow.api as api_module

        reload(api_module)

        mounted_paths = [route.path for route in api_module.app.routes if hasattr(route, "path")]
        assert "/site" not in mounted_paths


def test_update_article_status_passes_current_session_to_native_blog_url():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="publish-brand", name="Publish Brand")
        session.add(project)
        session.flush()
        article = Article(
            project_id=project.id,
            title="測試文章",
            slug="publish-me",
            status="draft",
        )
        session.add(article)
        session.commit()
        article_id = article.id

        def _fake_native_blog_url(slug, project_id=None, db=None):
            assert slug == "publish-me"
            assert project_id == project.id
            assert db is session
            return "https://client.example/blog/publish-me"

        def _close_task(coro):
            coro.close()
            return None

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session), \
             patch("contentflow.admin.app._native_blog_url", side_effect=_fake_native_blog_url), \
             patch("contentflow.admin.app.asyncio.create_task", side_effect=_close_task):
            response = client.post(
                f"/articles/{article_id}/status",
                data={"status": "published"},
                follow_redirects=False,
            )

        session.expire_all()
        saved = session.get(Article, article_id)
        assert response.status_code == 303
        assert saved.publish_url == "https://client.example/blog/publish-me"
        assert saved.status == "published"
    finally:
        session.close()
        engine.dispose()


def test_save_article_persists_policy_overrides():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="article-brand", name="Article Brand")
        session.add(project)
        session.flush()
        article = Article(project_id=project.id, title="測試文章", slug="test-article")
        session.add(article)
        session.commit()
        article_id = article.id

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.post(
                f"/articles/{article_id}/save",
                json={
                    "title": "測試文章",
                    "content_format_override": "tutorial",
                    "reviewer_required_override": "required",
                    "custom_disclaimer": "此篇為示範內容。",
                    "extra_schema_types_override": "FAQPage, HowTo",
                },
            )

        session.expire_all()
        saved = session.get(Article, article_id)
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert saved.content_format_override == "tutorial"
        assert saved.reviewer_required_override is True
        assert saved.custom_disclaimer == "此篇為示範內容。"
        assert json.loads(saved.extra_schema_types_override_json) == ["FAQPage", "HowTo"]
    finally:
        session.close()
        engine.dispose()


def test_create_author_persists_reviewer_role():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(slug="author-brand", name="Author Brand")
        session.add(project)
        session.commit()
        project_id = project.id

        with patch("contentflow.admin.app._check_login", return_value=True), \
             patch("contentflow.admin.app._db", return_value=session):
            response = client.post(
                "/authors/new",
                data={
                    "project_id": project_id,
                    "name": "王律師",
                    "title": "執業律師",
                    "bio": "專長合約與勞資糾紛",
                    "credentials": "台灣律師",
                    "profile_url": "https://example.com/lawyer",
                    "reviewer_role": "legal",
                },
                follow_redirects=False,
            )

        author = session.query(Author).filter(Author.project_id == project_id).first()
        assert response.status_code == 303
        assert author is not None
        assert author.reviewer_role == "legal"
        assert author.is_medical_reviewer is False
    finally:
        session.close()
        engine.dispose()