"""complaint_cases expansion + candidate_rules table

Revision ID: a1b2c3d4e5f6
Revises: 9c2f4e06d5e8
Create Date: 2026-06-20

Phase 2 — 案例运营闭环：
  - complaint_cases 新增 14 个字段（审核/发布/抽取/去重/脱敏）
  - complaint_types、legal_basis 保持 Text 存储 JSON 字符串（SQLite 兼容）
  - decision_date 改为 Date 类型
  - 新建 candidate_rules 表（候选规则，需人工审核）
  - 所有操作均可回滚
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9c2f4e06d5e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dialect_name() -> str:
    bind = op.get_bind()
    if hasattr(bind, 'dialect'):
        return bind.dialect.name
    return 'sqlite'


def upgrade() -> None:
    dialect = _dialect_name()

    # ═══════════════════════════════════════════════════════════
    # 1. complaint_cases — add new columns
    # ═══════════════════════════════════════════════════════════

    # Text/JSON columns
    for col, comment in [
        ("canonical_url", "权威来源 URL（去重主键）"),
        ("source_type", "来源类型: ccgp/mof/province/manual"),
        ("case_no", "案件编号"),
        ("city", "城市"),
        ("review_status", "审核状态: fetched/normalized/extracted/pending_review/verified/published/duplicate/rejected/parse_failed/quarantined/archived"),
        ("publish_status", "发布状态: draft/published/unpublished"),
        ("content_hash", "内容哈希（SHA256，去重用）"),
        ("sanitized_content", "脱敏后内容"),
        ("extractor_version", "抽取器版本"),
        ("extraction_metadata", "抽取元数据 JSON"),
    ]:
        _add_column("complaint_cases", col, sa.Text(), comment, dialect)

    # Integer/Float columns
    _add_column("complaint_cases", "quality_score", sa.Float(), "质量评分 0.0-1.0", dialect)
    _add_column("complaint_cases", "reviewed_by", sa.Integer(), "审核人 user_id", dialect)

    # DateTime/Date columns
    _add_column("complaint_cases", "reviewed_at", sa.DateTime(), "审核时间", dialect)
    _add_column("complaint_cases", "published_at", sa.DateTime(), "发布时间", dialect)

    # decision_date: String → Date conversion
    if dialect == "sqlite":
        # SQLite doesn't support ALTER COLUMN TYPE, need rebuild
        _convert_decision_date_sqlite()
    else:
        # PostgreSQL: ALTER COLUMN TYPE with USING
        op.execute(
            "ALTER TABLE complaint_cases "
            "ALTER COLUMN decision_date TYPE DATE "
            "USING CASE WHEN decision_date IS NULL OR decision_date = '' THEN NULL "
            "ELSE decision_date::DATE END"
        )

    # Create indexes for new columns
    _create_index_if_not_exists("ix_complaint_cases_review_status", "complaint_cases", "review_status", dialect)
    _create_index_if_not_exists("ix_complaint_cases_content_hash", "complaint_cases", "content_hash", dialect)
    _create_index_if_not_exists("ix_complaint_cases_publish_status", "complaint_cases", "publish_status", dialect)
    _create_index_if_not_exists("ix_complaint_cases_canonical_url", "complaint_cases", "canonical_url", dialect)

    # ═══════════════════════════════════════════════════════════
    # 1a. Backfill existing cases
    # ═══════════════════════════════════════════════════════════
    _backfill_existing_cases()

    # ═══════════════════════════════════════════════════════════
    # 2. candidate_rules — new table
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "candidate_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("candidate_id", sa.String(64), unique=True, nullable=False, comment="候选规则 ID"),
        sa.Column("source_case_id", sa.Integer(), nullable=True, comment="关联投诉案例 ID"),
        sa.Column("source_type", sa.String(32), default="miner", comment="来源: miner/manual/llm"),
        sa.Column("rule_type", sa.String(32), nullable=False, comment="规则类型"),
        sa.Column("target", sa.String(255), nullable=False, comment="检测目标"),
        sa.Column("description", sa.Text, nullable=False, comment="规则描述"),
        sa.Column("risk_level", sa.String(16), default="medium", comment="风险等级: critical/high/medium/low"),
        sa.Column("category", sa.String(64), default="candidate", comment="规则类别"),
        sa.Column("law_ref", sa.Text, nullable=True, comment="法规引用"),
        sa.Column("suggestion", sa.Text, nullable=True, comment="整改建议"),
        sa.Column("pattern", sa.Text, nullable=True, comment="匹配模式 regex"),
        sa.Column("evidence_snippets", sa.Text, nullable=True, comment="证据片段 JSON"),
        sa.Column("confidence", sa.Float, default=0.0, comment="挖掘置信度 0.0-1.0"),
        sa.Column("miner_version", sa.String(32), nullable=True, comment="矿机版本"),
        sa.Column("review_status", sa.String(16), default="pending", comment="审核状态: pending/approved/rejected/duplicate"),
        sa.Column("reviewed_by", sa.Integer(), nullable=True, comment="审核人"),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True, comment="审核时间"),
        sa.Column("review_note", sa.Text, nullable=True, comment="审核意见"),
        sa.Column("promoted_to", sa.String(64), nullable=True, comment="升级为正式规则 ID"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_index("ix_candidate_rules_review_status", "candidate_rules", ["review_status"])
    op.create_index("ix_candidate_rules_source_case", "candidate_rules", ["source_case_id"])
    op.create_index("ix_candidate_rules_confidence", "candidate_rules", ["confidence"])


def downgrade() -> None:
    dialect = _dialect_name()

    # ═══════════════════════════════════════════════════════════
    # 1. Drop candidate_rules table
    # ═══════════════════════════════════════════════════════════
    op.drop_index("ix_candidate_rules_confidence", table_name="candidate_rules")
    op.drop_index("ix_candidate_rules_source_case", table_name="candidate_rules")
    op.drop_index("ix_candidate_rules_review_status", table_name="candidate_rules")
    op.drop_table("candidate_rules")

    # ═══════════════════════════════════════════════════════════
    # 2. Rollback complaint_cases changes
    # ═══════════════════════════════════════════════════════════

    # Drop new indexes
    for idx_name, table in [
        ("ix_complaint_cases_canonical_url", "complaint_cases"),
        ("ix_complaint_cases_publish_status", "complaint_cases"),
        ("ix_complaint_cases_content_hash", "complaint_cases"),
        ("ix_complaint_cases_review_status", "complaint_cases"),
    ]:
        try:
            op.drop_index(idx_name, table_name=table)
        except Exception:
            pass

    # decision_date: Date → String
    if dialect == "sqlite":
        _revert_decision_date_sqlite()
    else:
        op.execute(
            "ALTER TABLE complaint_cases "
            "ALTER COLUMN decision_date TYPE VARCHAR(16)"
        )

    # Drop new columns (SQLite doesn't support DROP COLUMN, handled in _revert)
    if dialect != "sqlite":
        for col in [
            "canonical_url", "source_type", "case_no", "city",
            "review_status", "publish_status", "content_hash",
            "sanitized_content", "extractor_version", "extraction_metadata",
            "quality_score", "reviewed_by", "reviewed_at", "published_at",
        ]:
            try:
                op.drop_column("complaint_cases", col)
            except Exception:
                pass


# ── SQLite helpers (no ALTER COLUMN / DROP COLUMN support) ──

def _add_column(table: str, col: str, col_type, comment: str, dialect: str) -> None:
    """Add a column if it doesn't exist."""
    try:
        op.add_column(table, sa.Column(col, col_type, nullable=True, comment=comment))
    except Exception:
        # Column already exists (idempotent)
        pass


def _backfill_existing_cases() -> None:
    """Backfill newly added columns for existing complaint_cases rows.

    Sets review_status to "fetched" and publish_status to "draft" so existing
    cases enter the review queue. Also computes content_hash from existing data.
    """
    import hashlib

    conn = op.get_bind()
    dialect = _dialect_name()

    # Version check: skip if no cases exist
    try:
        if dialect == "sqlite":
            row = conn.exec_driver_sql("SELECT COUNT(*) FROM complaint_cases").fetchone()
        else:
            row = conn.exec_driver_sql(sa.text("SELECT COUNT(*) FROM complaint_cases")).fetchone()
        if not row or row[0] == 0:
            return
    except Exception:
        return

    # Backfill review_status for NULLs
    if dialect == "sqlite":
        conn.exec_driver_sql(
            "UPDATE complaint_cases SET review_status = 'fetched' "
            "WHERE review_status IS NULL OR review_status = ''"
        )
        conn.exec_driver_sql(
            "UPDATE complaint_cases SET publish_status = 'draft' "
            "WHERE publish_status IS NULL OR publish_status = ''"
        )
        conn.exec_driver_sql(
            "UPDATE complaint_cases SET source_type = 'ccgp' "
            "WHERE source_type IS NULL OR source_type = ''"
        )
        # Compute content_hash from raw_content + summary
        cases = conn.exec_driver_sql(
            "SELECT id, raw_content, summary FROM complaint_cases "
            "WHERE content_hash IS NULL OR content_hash = ''"
        ).fetchall()
        for case_id, raw, summary in cases:
            text = (raw or "") + (summary or "")
            if text:
                h = hashlib.sha256(text.encode("utf-8")).hexdigest()
                conn.exec_driver_sql(
                    f"UPDATE complaint_cases SET content_hash = '{h}' WHERE id = {case_id}"
                )
        conn.exec_driver_sql(
            "UPDATE complaint_cases SET quality_score = 0.0 WHERE quality_score IS NULL"
        )
    else:
        conn.exec_driver_sql(
            sa.text("UPDATE complaint_cases SET review_status = 'fetched' "
                    "WHERE review_status IS NULL")
        )
        conn.exec_driver_sql(
            sa.text("UPDATE complaint_cases SET publish_status = 'draft' "
                    "WHERE publish_status IS NULL")
        )
        conn.exec_driver_sql(
            sa.text("UPDATE complaint_cases SET source_type = 'ccgp' "
                    "WHERE source_type IS NULL")
        )
        conn.exec_driver_sql(
            sa.text("UPDATE complaint_cases SET quality_score = 0.0 WHERE quality_score IS NULL")
        )
        # PostgreSQL can compute hash in SQL
        conn.exec_driver_sql(
            sa.text(
                "UPDATE complaint_cases SET content_hash = "
                "encode(sha256((COALESCE(raw_content, '') || COALESCE(summary, ''))::bytea), 'hex') "
                "WHERE content_hash IS NULL AND (raw_content IS NOT NULL OR summary IS NOT NULL)"
            )
        )


def _create_index_if_not_exists(idx_name: str, table: str, column: str, dialect: str) -> None:
    """Create index if not exists."""
    try:
        op.create_index(idx_name, table, [column])
    except Exception:
        pass


def _convert_decision_date_sqlite() -> None:
    """SQLite: rebuild table to change decision_date from String to Date."""
    conn = op.get_bind()
    # Check if decision_date is already Date type
    try:
        result = conn.exec_driver_sql("PRAGMA table_info(complaint_cases)")
        cols = {row[1]: row[2] for row in result.fetchall()}
        if cols.get("decision_date") == "DATE":
            return  # Already converted
    except Exception:
        pass

    # Rebuild table with Date type
    op.execute("""
        CREATE TABLE complaint_cases_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            province VARCHAR(32) NOT NULL DEFAULT '全国',
            source_url VARCHAR(512),
            title VARCHAR(255) NOT NULL,
            project_name VARCHAR(255),
            project_number VARCHAR(128),
            complainant TEXT,
            respondent TEXT,
            decision_date DATE,
            decision_type VARCHAR(16) NOT NULL DEFAULT 'unknown',
            complaint_types TEXT,
            legal_basis TEXT,
            summary TEXT,
            raw_content TEXT,
            is_analyzed INTEGER DEFAULT 0,
            created_at DATETIME,
            canonical_url TEXT,
            source_type TEXT,
            case_no TEXT,
            city TEXT,
            review_status TEXT,
            publish_status TEXT,
            content_hash TEXT,
            sanitized_content TEXT,
            extractor_version TEXT,
            extraction_metadata TEXT,
            quality_score FLOAT,
            reviewed_by INTEGER,
            reviewed_at DATETIME,
            published_at DATETIME
        )
    """)
    op.execute("""
        INSERT INTO complaint_cases_new
        SELECT id, province, source_url, title, project_name, project_number,
               complainant, respondent,
               CASE WHEN decision_date IS NULL OR decision_date = '' THEN NULL
                    ELSE decision_date END,
               decision_type, complaint_types, legal_basis, summary, raw_content,
               is_analyzed, created_at,
               canonical_url, source_type, case_no, city, review_status,
               publish_status, content_hash, sanitized_content,
               extractor_version, extraction_metadata, quality_score,
               reviewed_by, reviewed_at, published_at
        FROM complaint_cases
    """)
    op.execute("DROP TABLE complaint_cases")
    op.execute("ALTER TABLE complaint_cases_new RENAME TO complaint_cases")
    # Recreate indexes on new table
    try:
        op.create_index("ix_complaint_cases_source_url", "complaint_cases", ["source_url"], unique=True)
    except Exception:
        pass
    try:
        op.create_index("ix_complaint_cases_decision_type", "complaint_cases", ["decision_type"])
    except Exception:
        pass
    try:
        op.create_index("ix_complaint_cases_province", "complaint_cases", ["province"])
    except Exception:
        pass
    try:
        op.create_index("ix_complaint_cases_is_analyzed", "complaint_cases", ["is_analyzed"])
    except Exception:
        pass
    try:
        op.create_index("ix_complaint_cases_created_at", "complaint_cases", ["created_at"])
    except Exception:
        pass


def _revert_decision_date_sqlite() -> None:
    """SQLite: revert Date back to String type."""
    conn = op.get_bind()
    try:
        result = conn.exec_driver_sql("PRAGMA table_info(complaint_cases)")
        cols = {row[1]: row[2] for row in result.fetchall()}
        if cols.get("decision_date") == "VARCHAR(16)":
            return  # Already reverted
    except Exception:
        pass

    op.execute("""
        CREATE TABLE complaint_cases_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            province VARCHAR(32) NOT NULL DEFAULT '全国',
            source_url VARCHAR(512),
            title VARCHAR(255) NOT NULL,
            project_name VARCHAR(255),
            project_number VARCHAR(128),
            complainant TEXT,
            respondent TEXT,
            decision_date VARCHAR(16),
            decision_type VARCHAR(16) NOT NULL DEFAULT 'unknown',
            complaint_types TEXT,
            legal_basis TEXT,
            summary TEXT,
            raw_content TEXT,
            is_analyzed INTEGER DEFAULT 0,
            created_at DATETIME
        )
    """)
    op.execute("""
        INSERT INTO complaint_cases_old
        SELECT id, province, source_url, title, project_name, project_number,
               complainant, respondent,
               CAST(decision_date AS TEXT),
               decision_type, complaint_types, legal_basis, summary, raw_content,
               is_analyzed, created_at
        FROM complaint_cases
    """)
    op.execute("DROP TABLE complaint_cases")
    op.execute("ALTER TABLE complaint_cases_old RENAME TO complaint_cases")
    try:
        op.create_index("ix_complaint_cases_source_url", "complaint_cases", ["source_url"], unique=True)
    except Exception:
        pass
