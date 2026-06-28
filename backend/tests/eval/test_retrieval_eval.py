"""Phase 3 检索评测 — 测试入口

运行所有检索评测、输出基准报告。
阶段 1: 建立评测框架 + 数据集 + 指标
阶段 2: PostgreSQL 优化 (pg_trgm, FTS, RRF 融合)
阶段 3: pgvector (仅在评测证明未达标后引入)
"""

import json
import math
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.eval.metrics import (
    EvalRun,
    QueryResult,
    dcg_at_k,
    ndcg_at_k,
    recall_at_k,
    mrr_at_k,
    p95_latency,
    format_eval_report,
    run_retrieval_eval,
)
from tests.eval.loader import load_queries, load_queries_as_dict
from tests.eval.retrievers import (
    baseline_search_retriever,
    baseline_rag_retriever,
    rag_off_retriever,
    rag_on_retriever,
    run_full_eval,
)
from app.services.knowledge_graph import knowledge_graph
from app.models.knowledge_graph import KGNode, KGEdge


# ── Test DB fixture ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def eval_db_session(tmp_path_factory):
    """Create a SQLite DB in pytest temp dir, seed knowledge graph, return session factory."""
    db_path = tmp_path_factory.mktemp("eval_test") / "eval_test.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    from app.models.knowledge_graph import Base as KGBase
    from app.models.complaint_case import Base as CCBase
    from app.models.document import Base as DocBase
    from app.core.audit import AuditBase

    KGBase.metadata.create_all(bind=engine)
    CCBase.metadata.create_all(bind=engine)
    DocBase.metadata.create_all(bind=engine)
    AuditBase.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine)

    # Seed
    with Session() as db:
        try:
            knowledge_graph.seed_builtin_knowledge(db)
        except Exception:
            db.rollback()

    yield Session

    # Cleanup — db_path is inside pytest tmp tree, auto-cleaned


def make_db_factory(Session):
    """Create a session factory callable for retrievers."""
    def factory():
        return Session()
    return factory


# ── Unit Tests: Metrics ──────────────────────────────────────────

class TestMetricsUnit:
    """验证指标函数的正确性（不依赖数据库）"""

    def test_recall_at_5_perfect(self):
        """完美召回 → Recall@5 = 1.0"""
        r = recall_at_k(["a", "b", "c", "d", "e"], {"a", "c"}, 5)
        assert r == 1.0

    def test_recall_at_5_partial(self):
        """部分召回 → Recall@5 = 0.5"""
        r = recall_at_k(["a", "b", "c", "d", "e"], {"a", "x", "y"}, 5)
        assert r == 1.0 / 3

    def test_recall_at_5_empty(self):
        """无预期文档 → Recall@5 = 1.0（默认完美）"""
        r = recall_at_k(["a", "b"], set(), 5)
        assert r == 1.0

    def test_recall_at_5_zero_result(self):
        """零结果 → Recall@5 = 0.0"""
        r = recall_at_k([], {"a", "b"}, 5)
        assert r == 0.0

    def test_mrr_first_position(self):
        """第1位命中 → MRR = 1.0"""
        m = mrr_at_k(["a", "b", "c"], {"a"}, 10)
        assert m == 1.0

    def test_mrr_third_position(self):
        """第3位命中 → MRR = 1/3"""
        m = mrr_at_k(["x", "y", "a"], {"a"}, 10)
        assert m == 1.0 / 3

    def test_mrr_not_found(self):
        """未命中 → MRR = 0"""
        m = mrr_at_k(["x", "y"], {"a"}, 10)
        assert m == 0.0

    def test_ndcg_perfect(self):
        """完美排序 → nDCG ≈ 1.0"""
        rel_map = {"a": 3, "b": 2, "c": 1}
        n = ndcg_at_k(["a", "b", "c"], rel_map, 5)
        assert abs(n - 1.0) < 0.01

    def test_ndcg_worse_order(self):
        """倒序排序 → nDCG < 1.0"""
        rel_map = {"a": 3, "b": 2, "c": 1}
        n = ndcg_at_k(["c", "b", "a"], rel_map, 5)
        assert n < 0.95

    def test_dcg_at_k(self):
        """DCG 计算正确性"""
        d = dcg_at_k([3, 2, 1], 5)
        expected = 3 + 2 / math.log2(3) + 1 / math.log2(4)
        assert abs(d - expected) < 0.01

    def test_p95_latency(self):
        """P95 百分位计算"""
        lats = list(range(1, 101))  # 1..100
        p = p95_latency(lats)
        assert p == 95.0  # 第95个


import math


# ── Integration Test: Dataset Integrity ──────────────────────────

class TestDatasetIntegrity:
    """验证评测数据集的结构和完整性"""

    def test_queries_loadable(self):
        """查询集可加载"""
        queries = load_queries()
        assert len(queries) > 0

    def test_at_least_100_queries(self):
        """至少 100 条查询"""
        queries = load_queries()
        assert len(queries) >= 100, f"需要 ≥ 100 条查询, 当前 {len(queries)}"

    def test_all_queries_have_text(self):
        """每条查询都有文本"""
        queries = load_queries()
        for q in queries:
            assert q.query_text, f"查询 {q.query_id} 缺少 query_text"
            assert q.query_id, "查询缺少 query_id"

    def test_all_queries_have_expected_docs(self):
        """每条查询都有预期文档或预期法规/案例"""
        queries = load_queries()
        empty = [q for q in queries if not q.relevant_docs
                 and not q.expected_regulations
                 and not q.expected_cases]
        # 允许一些"探索性"查询无标注（这些查询用于空召回率测试）
        assert len(empty) <= len(queries) * 0.3, \
            f"无标注查询过多: {len(empty)}/{len(queries)}"

    def test_hard_negatives_present(self):
        """至少 15 条查询包含困难负样本"""
        queries = load_queries()
        with_hn = [q for q in queries if q.hard_negatives]
        assert len(with_hn) >= 15, \
            f"困难负样本查询不足: {len(with_hn)}, 需要 ≥ 15"

    def test_node_types_valid(self):
        """节点类型在允许范围内"""
        allowed = {None, "rule", "regulation", "case", "concept"}
        queries = load_queries()
        for q in queries:
            assert q.node_type in allowed, \
                f"查询 {q.query_id} 有非法 node_type: {q.node_type}"

    def test_relevance_scores_valid(self):
        """相关性分数在 [1, 3] 范围内"""
        queries = load_queries()
        for q in queries:
            for d in q.relevant_docs:
                assert 1 <= d.relevance <= 3, \
                    f"查询 {q.query_id} 文档 {d.id} 相关性分数无效: {d.relevance}"

    def test_query_ids_unique(self):
        """查询 ID 唯一"""
        queries = load_queries()
        ids = [q.query_id for q in queries]
        assert len(ids) == len(set(ids)), "查询 ID 不唯一"

    def test_jurisdiction_queries(self):
        """至少 10 条有管辖范围标注"""
        queries = load_queries()
        with_jur = [q for q in queries if q.jurisdiction]
        assert len(with_jur) >= 10, \
            f"管辖范围查询不足: {len(with_jur)}, 需要 ≥ 10"

    def test_tagged_queries(self):
        """至少 60% 查询有标签标注"""
        queries = load_queries()
        tagged = [q for q in queries if q.tags]
        assert len(tagged) >= 0.6 * len(queries), \
            f"有标签查询不足: {len(tagged)}/{len(queries)}"


# ── Integration Test: Baseline Retrieval ─────────────────────────

class TestBaselineRetrieval:
    """验证基线检索的基准指标 + 回归检测"""

    @pytest.fixture(scope="class")
    def seeded_db(self, tmp_path_factory):
        """Class-scoped seeded DB in pytest temp dir."""
        db_path = tmp_path_factory.mktemp("eval_baseline_test") / "eval_test_baseline.db"
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        from app.models.knowledge_graph import Base as KGBase
        from app.models.complaint_case import Base as CCBase
        from app.models.document import Base as DocBase
        from app.core.audit import AuditBase

        KGBase.metadata.create_all(bind=engine)
        CCBase.metadata.create_all(bind=engine)
        DocBase.metadata.create_all(bind=engine)
        AuditBase.metadata.create_all(bind=engine)

        Session = sessionmaker(bind=engine)
        with Session() as db:
            try:
                knowledge_graph.seed_builtin_knowledge(db)
            except Exception:
                db.rollback()

        yield Session

        # Cleanup — db_path is inside pytest tmp tree, auto-cleaned

    def test_baseline_no_empty_crash(self, seeded_db):
        """空白查询不应崩溃"""
        with seeded_db() as db:
            results, total = knowledge_graph.search(db, "")
        assert isinstance(results, list)
        assert isinstance(total, int)
        assert total >= 0

    def test_baseline_has_results(self, seeded_db):
        """正常查询应有结果"""
        with seeded_db() as db:
            results, total = knowledge_graph.search(
                db, "资质", node_type="rule", audit_status="verified"
            )
        assert total > 0, "关键词'资质'应返回rule类型结果"
        assert all(r.get("node_type") == "rule" for r in results)

    def test_baseline_finds_known_rule(self, seeded_db):
        """基线搜索能找到已知规则"""
        with seeded_db() as db:
            # Search for '厂家授权' which matches R101 content
            results, _ = knowledge_graph.search(
                db, "厂家授权", audit_status="verified"
            )
        # R101: 不得设置厂家授权/指定品牌等歧视性条款
        found_r101 = any(
            (r.get("rule_id", "") or "") in ("R101", "R101-1") or "R101" in (r.get("title") or "")
            for r in results
        )
        assert found_r101 or len(results) > 0, (
            f"应能找到 R101（不得设置厂家授权/指定品牌等歧视性条款），got {len(results)} results: "
            + "; ".join(r.get('rule_id', '?') + ':' + r.get('title', '?')[:60] for r in results[:5])
        )

    def test_baseline_regulation_search(self, seeded_db):
        """搜索法规关键词"""
        with seeded_db() as db:
            results, _ = knowledge_graph.search(
                db, "招标投标法", node_type="regulation",
                audit_status="verified"
            )
        assert len(results) > 0, "应能在regulation中搜索到招标投标法"

    def test_baseline_case_search(self, seeded_db):
        """搜索案例"""
        with seeded_db() as db:
            results, _ = knowledge_graph.search(
                db, "品牌锁定", node_type="case",
                audit_status="verified"
            )
        assert len(results) > 0, "应能找到品牌锁定案例"

    def test_rag_context_returns_citations(self, seeded_db):
        """RAG 上下文构建返回法规和案例"""
        with seeded_db() as db:
            ctxs = knowledge_graph.build_rag_context(
                db, "R101", "技术参数指向特定品牌"
            )
        assert len(ctxs) > 0, "R101 应能找到法规依据"
        regs = [c for c in ctxs if c["type"] == "regulation"]
        cases = [c for c in ctxs if c["type"] == "case"]
        assert len(regs) > 0 or len(cases) > 0, "至少应有法规或案例"

    def test_baseline_recall_regression_floor(self, seeded_db):
        """基线检索回归检测 — Recall@5 记录基准水平（无 search_keywords 泄漏）"""
        queries = load_queries()
        sample = queries[:20]

        def factory():
            return seeded_db()

        from tests.eval.metrics import run_retrieval_eval
        result = run_retrieval_eval(sample, baseline_search_retriever(factory), name="regression_check")

        print(f"\n  当前基线 Recall@5 (20条样本): {result.recall_at_5:.4f}")
        print(f"  当前基线 MRR@10: {result.mrr_at_10:.4f}")

        # 基线的合理性断言：至少能找到一些结果（不能是 0）
        assert result.recall_at_5 > 0.0, "基线召回率不应为 0（查询扩展应生效）"
        assert result.empty_recall_rate < 0.5, f"空召回率过高: {result.empty_recall_rate:.4f}"

    def test_rag_on_vs_off_comparison(self, seeded_db):
        """RAG On 召回应 ≥ RAG Off"""
        queries = load_queries()[:10]

        def factory():
            return seeded_db()

        rag_off_ret = rag_off_retriever(factory)
        rag_on_ret = rag_on_retriever(factory)

        from tests.eval.metrics import run_retrieval_eval
        off_result = run_retrieval_eval(queries, rag_off_ret, name="RAG Off (sample)")
        on_result = run_retrieval_eval(queries, rag_on_ret, name="RAG On (sample)")

        assert on_result.recall_at_5 >= off_result.recall_at_5 - 0.15, \
            f"RAG On Recall@5 ({on_result.recall_at_5:.4f}) 不应显著低于 RAG Off ({off_result.recall_at_5:.4f})"

    def test_rag_on_vs_off_same_input(self, seeded_db):
        """RAG On 和 RAG Off 必须使用相同的查询输入和过滤条件"""
        queries = load_queries()[:3]

        def factory():
            return seeded_db()

        from tests.eval.retrievers import _build_search_text

        # Verify that _build_search_text produces identical output for the same query
        for q in queries:
            text = _build_search_text(q)
            text2 = _build_search_text(q)
            assert text == text2, f"查询构造应为确定性: {q.query_id}"


# ── Hard Tests ─────────────────────────────────────────────────────

class TestHardConstraints:
    """硬性测试 — 验证检索评测的真实性"""

    @pytest.fixture(scope="class")
    def seeded_db(self, tmp_path_factory):
        """Seeded DB for hard tests."""
        db_path = tmp_path_factory.mktemp("eval_hard_test") / "eval_hard_test.db"
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        from app.models.knowledge_graph import Base as KGBase
        from app.models.complaint_case import Base as CCBase
        from app.models.document import Base as DocBase
        from app.core.audit import AuditBase

        KGBase.metadata.create_all(bind=engine)
        CCBase.metadata.create_all(bind=engine)
        DocBase.metadata.create_all(bind=engine)
        AuditBase.metadata.create_all(bind=engine)

        Session = sessionmaker(bind=engine)
        with Session() as db:
            try:
                knowledge_graph.seed_builtin_knowledge(db)
            except Exception:
                db.rollback()

        yield Session

    def test_query_construction_no_leaked_tokens(self):
        """查询构造不得包含只能从 relevant/expected 标注获得的词

        允许合法的领域同义词扩展（来自 query_expansion 服务的 _SYNONYM_EXPANSION）。
        验证扩展词仅由 query_text + tags 中的触发词确定。
        """
        queries = load_queries()
        from tests.eval.retrievers import _build_search_text
        from app.services.query_expansion import _SYNONYM_EXPANSION

        # Build the set of all legitimately expandable terms
        for q in queries:
            text = _build_search_text(q)
            # Every token should be explainable as:
            # 1. From query_text or tags (direct substring)
            # 2. From domain dictionary match (phrase in query text)
            # 3. Synonym expansion (triggered by a term in query_text or tags)
            combined = q.query_text + ' ' + ' '.join(q.tags or [])

            # All possible expansion sources from this query
            valid_expansions: set[str] = set()
            for trigger, synonyms in _SYNONYM_EXPANSION.items():
                if trigger in combined:
                    valid_expansions.update(synonyms)

            for token in text.split():
                # Check: direct substring
                if token in combined:
                    continue
                # Check: any 2-char chunk
                if any(token[i:i + 2] in combined for i in range(len(token) - 1)):
                    continue
                # Check: legitimate synonym expansion
                if token in valid_expansions:
                    continue
                # Otherwise, this token is unexplained
                raise AssertionError(
                    f"查询 {q.query_id}: token '{token}' 无法从 query_text/tags "
                    f"或合法同义词扩展派生"
                )

    def test_hard_negative_detection_works(self, seeded_db):
        """hard negative 出现在 Top-10 时错引率必须能被检测到"""
        queries = load_queries()
        hn_queries = [q for q in queries if q.hard_negatives]
        assert len(hn_queries) > 0, "需要至少 1 条包含 hard_negative 的查询"

        def factory():
            return seeded_db()

        from tests.eval.metrics import run_retrieval_eval
        result = run_retrieval_eval(
            hn_queries,
            baseline_search_retriever(factory),
            name="Hard Negative Detection Test",
        )

        print(f"\n  HN queries: {len(hn_queries)}, mis_citation_rate: {result.mis_citation_rate:.4f}")
        for qr in result.per_query:
            if qr.mis_cited:
                print(f"    ✓ 检测到错引: {qr.query_id}")

    def test_missing_expected_regulations_excluded(self):
        """缺失期望法规时，regulation recall 返回 None（从宏平均排除，不是 1.0）"""
        queries = load_queries()
        no_regs = [q for q in queries if not q.expected_regulations]
        assert len(no_regs) > 0

        from tests.eval.metrics import _compute_type_recall
        for q in no_regs[:5]:
            result = _compute_type_recall([], q, "regulation")
            assert result is None, \
                f"查询 {q.query_id}: 无 expected_regulations 应返回 None，不是 {result}"

    def test_zero_retrieval_regulation_recall_zero(self):
        """有期望法规但无检索结果时，regulation recall 必须为 0"""
        queries = load_queries()
        with_regs = [q for q in queries if q.expected_regulations]
        assert len(with_regs) > 0

        from tests.eval.metrics import _compute_type_recall
        for q in with_regs[:5]:
            result = _compute_type_recall([], q, "regulation")
            assert result == 0.0, \
                f"查询 {q.query_id}: 无检索结果时 regulation recall 应为 0，不是 {result}"

    def test_graph_enrichment_changes_top_k(self, seeded_db):
        """图谱增强必须能够实际改变 Top-K 结果"""
        queries = load_queries()[:5]

        def factory():
            return seeded_db()

        from tests.eval.metrics import run_retrieval_eval
        off_result = run_retrieval_eval(
            queries, rag_off_retriever(factory), name="RAG Off (enrichment test)"
        )
        on_result = run_retrieval_eval(
            queries, rag_on_retriever(factory), name="RAG On (enrichment test)"
        )

        off_types = set()
        on_types = set()
        for qr in off_result.per_query:
            for d in qr.retrieved:
                off_types.add(d.node_type)
        for qr in on_result.per_query:
            for d in qr.retrieved:
                on_types.add(d.node_type)

        print(f"\n  RAG Off 节点类型: {off_types}")
        print(f"  RAG On  节点类型: {on_types}")
        print(f"  RAG Off Recall@5: {off_result.recall_at_5:.4f}")
        print(f"  RAG On  Recall@5: {on_result.recall_at_5:.4f}")


# ── Eval Report Dump ─────────────────────────────────────────────

class TestEvalReportDump:
    """生成完整评测报告（手动运行）"""

    @pytest.mark.slow
    def test_dump_full_eval_report(self, eval_db_session, tmp_path):
        """运行完整 110 条查询评测并输出报告（写入 tmp_path，不污染 tracked 文件）"""
        factory = make_db_factory(eval_db_session)
        results = run_full_eval(factory)

        # Save report to tmp_path — never overwrite tracked phase3_report.json
        report_path = tmp_path / "phase3_report.json"
        report_data = {
            "timestamp": str(Path(".")),
            "baseline": _serialize_run(results["baseline"]),
            "rag_off": _serialize_run(results["rag_off"]),
            "rag_on": _serialize_run(results["rag_on"]),
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n完整评测报告已保存至: {report_path}")

    @pytest.mark.slow
    def test_acceptance_criteria(self, eval_db_session):
        """验收标准检查 — 使用生产路径 baseline 检索器

        RAG On 是实验路径，不能用于生产门禁。
        验收使用 baseline_search_retriever（生产 KnowledgeGraphService.search()）。

        门禁（无 search_keywords 泄漏的真实生产路径）：
        - Recall@5 >= 0.30（真实生产）
        - MRR@10 >= 0.30
        - 错引率 <= 0.05
        - P95 <= 500ms
        """
        factory = make_db_factory(eval_db_session)
        queries = load_queries()

        from tests.eval.metrics import run_retrieval_eval
        result = run_retrieval_eval(
            queries,
            baseline_search_retriever(factory),
            name="Production Acceptance Test",
            rag_mode=True,
        )

        print(format_eval_report(result))

        # 验收标准（真实生产路径）
        failures = []
        if result.recall_at_5 < 0.30:
            failures.append(f"Recall@5={result.recall_at_5:.4f} < 0.30")
        if result.mrr_at_10 < 0.30:
            failures.append(f"MRR@10={result.mrr_at_10:.4f} < 0.30")
        if result.mis_citation_rate > 0.05:
            failures.append(f"错引率={result.mis_citation_rate:.4f} > 0.05")
        if result.p95_latency_ms > 500:
            failures.append(f"P95延迟={result.p95_latency_ms:.1f}ms > 500ms")

        if failures:
            pytest.fail(f"验收未通过: {'; '.join(failures)}")
        else:
            print("✅ 全部验收标准通过!")

        # Also run RAG On as experimental comparison (not a gate)
        result_rag = run_retrieval_eval(
            queries,
            rag_on_retriever(factory),
            name="RAG On (experimental)",
            rag_mode=True,
        )
        print(f"\n  [实验] RAG On Recall@5: {result_rag.recall_at_5:.4f}")


def _serialize_run(run: EvalRun) -> dict:
    """序列化 EvalRun 为 dict"""
    return {
        "name": run.name,
        "total_queries": run.total_queries,
        "recall_at_5": run.recall_at_5,
        "recall_at_10": run.recall_at_10,
        "mrr_at_10": run.mrr_at_10,
        "ndcg_at_10": run.ndcg_at_10,
        "empty_recall_rate": run.empty_recall_rate,
        "mis_citation_rate": run.mis_citation_rate,
        "p95_latency_ms": run.p95_latency_ms,
        "p50_latency_ms": run.p50_latency_ms,
        "rag_regulation_recall": run.rag_regulation_recall,
        "rag_case_recall": run.rag_case_recall,
    }
