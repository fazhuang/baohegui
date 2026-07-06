"""数据库 Schema 一致性测试。

验证：
1. Alembic 升级后的 schema 与运行时模型关键约束一致
2. complaint_cases.source_url 唯一索引存在
3. complaint_cases 关键索引存在
4. KG 外键和关键索引存在
5. 不依赖开发机已有数据库 — 使用独立的 SQLite 文件数据库

约束：只读检查，不修改数据库。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text


@pytest.fixture(scope="module")
def alembic_engine():
    """创建干净数据库，仅执行 Alembic 升级（不补表），返回引擎用于检查 schema。

    不执行 create_all()，确保断言只反映 Alembic 迁移实际产生的 schema。
    """
    # 使用临时文件数据库，不依赖开发机已有数据库
    db_path = os.path.join(tempfile.gettempdir(), "bhg_schema_consistency_test.db")

    # 强制设置环境变量
    os.environ["BHG_DATABASE_URL"] = f"sqlite:///{db_path}"
    # Rules dir needed for seed — use the test copy location
    rules_dir = os.environ.get(
        "BHG_RULES_DIR",
        str(Path(__file__).resolve().parents[1] / "tests" / ".test_tmp" / "rules"),
    )
    os.environ["BHG_RULES_DIR"] = rules_dir

    # 关键修复：conftest 在 module 级别设置了 BHG_DATABASE_URL，settings 对象
    # 已缓存该值。env.py 中的 `config.set_main_option("sqlalchemy.url", settings.database_url)`
    # 会读取缓存的旧值并覆盖我们的 alembic_cfg 设置。
    # 因此必须直接修改 settings.database_url 以确保 Alembic 连接到正确的数据库。
    from app.core.config import settings
    settings.database_url = f"sqlite:///{db_path}"

    # Remove old test DB
    if os.path.exists(db_path):
        os.unlink(db_path)

    # Run Alembic upgrade head
    from alembic.config import Config
    from alembic import command

    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    if not alembic_ini.exists():
        pytest.skip("alembic.ini not found")

    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "head")

    # 注意：不执行 create_all()！
    # 仅用 Alembic 升级结果做断言，暴露迁移与 ORM 之间的真实差距。
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    yield engine

    # Cleanup
    engine.dispose()
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture(scope="module")
def orm_engine():
    """纯 ORM create_all 引擎 — 用于对比 Alembic 与 ORM 的差距。"""
    from app.core.audit import AuditBase
    from app.models.announcement import Base as AnnouncementBase
    from app.models.candidate_rule import Base as CandidateRuleBase
    from app.models.complaint_case import Base as ComplaintCaseBase
    from app.models.document import Base as DocumentBase
    from app.models.knowledge_graph import KGNode, KGEdge  # noqa: F401
    from app.models.rule import Base as RuleBase
    from app.models.subscription import Base as SubscriptionBase
    from app.services.feedback_service import FeedbackRecord, RuleConfidence  # noqa: F401

    db_path = os.path.join(tempfile.gettempdir(), "bhg_orm_only_test.db")
    if os.path.exists(db_path):
        os.unlink(db_path)

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    for base in [DocumentBase, RuleBase, AuditBase, AnnouncementBase, ComplaintCaseBase, CandidateRuleBase, SubscriptionBase]:
        base.metadata.create_all(bind=engine)

    yield engine

    engine.dispose()
    if os.path.exists(db_path):
        os.unlink(db_path)


class TestComplaintCasesSchema:
    """complaint_cases 表 schema 一致性"""

    def test_table_exists(self, alembic_engine):
        inspector = inspect(alembic_engine)
        tables = inspector.get_table_names()
        assert "complaint_cases" in tables, f"Table missing: {tables}"

    def test_unique_index_on_source_url(self, alembic_engine):
        """source_url 唯一索引存在。"""
        inspector = inspect(alembic_engine)
        indexes = inspector.get_indexes("complaint_cases")
        index_names = {idx["name"] for idx in indexes}
        url_indexes = [idx for idx in indexes if "source_url" in idx["name"]]
        assert len(url_indexes) >= 1, f"No source_url index found in: {index_names}"
        source_url_idx = url_indexes[0]
        assert bool(source_url_idx.get("unique")) is True, (
            f"source_url index must be UNIQUE, got: {source_url_idx}"
        )

    def test_key_indexes_exist(self, alembic_engine):
        """关键 complaint_cases 索引存在。"""
        inspector = inspect(alembic_engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("complaint_cases")}
        expected = {
            "ix_complaint_cases_source_url",
            "ix_complaint_cases_decision_type",
            "ix_complaint_cases_province",
            "ix_complaint_cases_is_analyzed",
            "ix_complaint_cases_created_at",
        }
        missing = expected - indexes
        assert not missing, f"Missing indexes: {missing}"

    def test_columns_match_model(self, alembic_engine):
        """Alembic 升级后的列与 ORM 模型一致。"""
        inspector = inspect(alembic_engine)
        db_columns = {col["name"] for col in inspector.get_columns("complaint_cases")}

        from app.models.complaint_case import ComplaintCase
        model_columns = {c.name for c in ComplaintCase.__table__.columns}

        missing_in_db = model_columns - db_columns
        assert not missing_in_db, f"Columns in model but not in DB: {missing_in_db}"


class TestKGSchema:
    """KG 表 schema 一致性"""

    def test_kg_nodes_table_exists(self, alembic_engine):
        inspector = inspect(alembic_engine)
        tables = inspector.get_table_names()
        assert "kg_nodes" in tables

    def test_kg_edges_table_exists(self, alembic_engine):
        inspector = inspect(alembic_engine)
        tables = inspector.get_table_names()
        assert "kg_edges" in tables

    def test_kg_edges_foreign_keys(self, alembic_engine):
        """KG 边外键存在。"""
        inspector = inspect(alembic_engine)
        fks = inspector.get_foreign_keys("kg_edges")
        source_fks = [fk for fk in fks if fk.get("constrained_columns") == ["source_id"]]
        target_fks = [fk for fk in fks if fk.get("constrained_columns") == ["target_id"]]
        assert len(source_fks) >= 1, f"No FK on source_id in kg_edges"
        assert len(target_fks) >= 1, f"No FK on target_id in kg_edges"

    def test_kg_nodes_key_indexes(self, alembic_engine):
        """KG nodes 关键索引存在。"""
        inspector = inspect(alembic_engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("kg_nodes")}
        expected = {
            "ix_kg_nodes_type_status",
            "ix_kg_nodes_type_trust",
        }
        missing = expected - indexes
        # These are composite indexes defined in the model's __table_args__
        # On SQLite they may have slightly different names
        if missing:
            # Check if any index has both columns
            for idx in inspector.get_indexes("kg_nodes"):
                cols = [c for c in idx.get("column_names", [])]
                if "node_type" in cols and "audit_status" in cols:
                    expected.discard("ix_kg_nodes_type_status")
                if "node_type" in cols and "trust_level" in cols:
                    expected.discard("ix_kg_nodes_type_trust")
        assert not missing, f"Missing indexes: {missing}"


class TestAlembicSchemaVsOrm:
    """Alembic 升级后的 schema 与运行时模型关键约束一致"""

    def test_alembic_creates_core_tables(self, alembic_engine):
        """Alembic upgrade 将核心表创建出来（不是空库也不是被补表后的）。"""
        inspector = inspect(alembic_engine)
        tables = set(inspector.get_table_names())
        # Alembic 迁移当前创建这些核心表（audit_logs 可能由迁移或 AuditService 创建）
        required = {"complaint_cases", "kg_nodes", "kg_edges", "candidate_rules"}
        missing = required - tables
        assert not missing, f"Alembic tables missing: {missing}"

    def test_alembic_tables_only(self, alembic_engine):
        """纯 Alembic 库仅应有核心表 + alembic_version。
        此断言确保 create_all 没有被执行，否则会多出 users / announcements 等表。
        Phase 2: 新增 crawl_jobs + crawl_job_items + crawl_source_health。
        Phase 5: 新增 bridge 核心表（Policy chain）+ _bhg_migration_objects。"""
        inspector = inspect(alembic_engine)
        tables = set(inspector.get_table_names())
        core = {
            "alembic_version",
            "complaint_cases", "kg_edges", "kg_nodes",
            "candidate_rules", "crawl_jobs", "crawl_job_items",
            "crawl_source_health", "daily_health_snapshots",
            # bridge migration (Policy chain)
            "uploaded_files", "document_sections", "compliance_reports",
            "_bhg_migration_objects",
        }
        extra = tables - core
        unexpected = extra - {"audit_logs", "sqlite_sequence"}
        assert not unexpected, \
            f"Alembic-only tables should only have core + audit_logs; unexpected: {sorted(unexpected)}"

    def test_complaint_cases_columns_match_model(self, alembic_engine):
        """确保所有 complaint_cases 列名与模型一致。"""
        from app.models.complaint_case import ComplaintCase

        inspector = inspect(alembic_engine)
        db_columns = {col["name"] for col in inspector.get_columns("complaint_cases")}
        model_columns = {c.name for c in ComplaintCase.__table__.columns}

        for col_name in model_columns:
            assert col_name in db_columns, f"Column '{col_name}' from model not found in DB"

    def test_foreign_key_references(self, alembic_engine):
        """KG edges 的外键引用正确的表。"""
        inspector = inspect(alembic_engine)
        fks = inspector.get_foreign_keys("kg_edges")
        for fk in fks:
            assert fk["referred_table"] == "kg_nodes", (
                f"FK should reference kg_nodes, got {fk['referred_table']}"
            )

    def test_alembic_vs_orm_complaint_kg_gap(self, alembic_engine, orm_engine):
        """对比纯 Alembic 与纯 ORM 的 complaint_cases / kg_nodes / kg_edges 表差异。

        Phase 0 范围仅限于 complaint_cases + KG 表的 schema 一致性。
        其他表（users、rules、announcements 等）在后续阶段补齐迁移。
        """
        alembic_tables = set(inspect(alembic_engine).get_table_names())
        orm_tables = set(inspect(orm_engine).get_table_names())
        # Phase 0 范围：仅检查 complaint_cases + KG 表
        scope = {"complaint_cases", "kg_nodes", "kg_edges"}
        scope_missing = scope - alembic_tables
        assert not scope_missing, \
            f"Phase 0 scope tables missing from Alembic: {sorted(scope_missing)}"

        # 记录超出范围的表差异供参考（非硬失败）
        beyond_scope = (orm_tables - alembic_tables - {"alembic_version", "sqlite_sequence"}) - scope
        if beyond_scope:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                "Tables in ORM but NOT in Alembic (beyond Phase 0 scope, needs future migration): %s",
                sorted(beyond_scope),
            )
