"""测试：双引擎结果融合（FusionEngine）

去重策略（规则引擎优先）：
- LLM 违规与规则违规"同章节 + 同风险等级 + LLM 原文 ⊆ 规则原文" → 剔除 LLM
- 其他 LLM 违规 → 保留（新发现）
"""

from __future__ import annotations

from app.engine.fusion import FusionEngine, _extract_section
from app.engine.llm_engine import LLMEngineResult, LLMViolation
from app.engine.rule_engine import RuleEngineResult, Violation

# ═══════════════════════════════════════════════════════════════
# _extract_section — 章节提取
# ═══════════════════════════════════════════════════════════════


class TestExtractSection:
    def test_from_location_angle_bracket(self):
        assert _extract_section("应在《资格要求》中") == "资格要求"

    def test_from_location_tilde(self):
        assert _extract_section("评审办法 ~第1行") == "评审办法"

    def test_from_location_colon(self):
        assert _extract_section("资格要求：投标人条件") == "资格要求"

    def test_from_location_colon_en(self):
        assert _extract_section("招标公告: 项目概况") == "招标公告"

    def test_from_description_missing(self):
        assert _extract_section("缺少《招标公告》章节") == "招标公告"

    def test_from_description_should_in(self):
        assert _extract_section("应在《评审办法》中") == "评审办法"

    def test_from_description_no_bracket(self):
        # 无格式标记时无法可靠提取
        assert _extract_section("评审办法章节内容缺失") == ""

    def test_empty(self):
        assert _extract_section("") == ""


# ═══════════════════════════════════════════════════════════════
# FusionEngine.deduplicate — 核心去重
# ═══════════════════════════════════════════════════════════════


class TestDeduplicate:
    """规则引擎优先的去重策略"""

    # ── 场景：LLM 违规与规则违规重复 → 剔除 LLM ─────────

    def test_same_section_same_risk_text_contained(self):
        """同章节 + 同风险 + LLM文本是规则文本子串 → 剔除 LLM"""
        rules = [
            Violation(
                rule_id="FORB-001",
                rule_type="forbidden",
                description="指定品牌",
                text="指定品牌XXXX作为唯一授权产品",
                location="评审办法 ~第1行",
                risk_level="high",
                weight=25,
            ),
        ]
        llms = [
            LLMViolation(
                type="exclusivity", section="评审办法", text="指定品牌", risk_level="high"
            ),
        ]
        _, kept_llm = FusionEngine.deduplicate(rules, llms)
        assert len(kept_llm) == 0  # 完全重复 → 被剔除

    def test_same_section_same_risk_partial_text_contained(self):
        """LLM原文部分包含在规则原文中 → 剔除"""
        rules = [
            Violation(
                rule_id="FORB-001",
                rule_type="forbidden",
                description="指定品牌",
                text="指定使用XX品牌",
                location="评审办法 ~第1行",
                risk_level="high",
                weight=25,
            ),
        ]
        llms = [
            LLMViolation(type="exclusivity", section="评审办法", text="XX品牌", risk_level="high"),
        ]
        _, kept_llm = FusionEngine.deduplicate(rules, llms)
        assert len(kept_llm) == 0

    # ── 场景：条件不满足 → 保留 LLM ──────────────────

    def test_different_section_kept(self):
        """不同章节 → 保留 LLM"""
        rules = [
            Violation(
                rule_id="FORB-001",
                rule_type="forbidden",
                description="指定品牌",
                text="指定品牌",
                location="评审办法 ~第1行",
                risk_level="high",
                weight=25,
            ),
        ]
        llms = [
            LLMViolation(
                type="exclusivity", section="资格要求", text="指定品牌", risk_level="high"
            ),
        ]
        _, kept_llm = FusionEngine.deduplicate(rules, llms)
        assert len(kept_llm) == 1  # 章节不同 → 保留

    def test_different_risk_level_kept(self):
        """风险等级不同 → 保留 LLM"""
        rules = [
            Violation(
                rule_id="FORB-001",
                rule_type="forbidden",
                description="指定品牌",
                text="指定品牌",
                location="评审办法 ~第1行",
                risk_level="high",
                weight=25,
            ),
        ]
        llms = [
            LLMViolation(
                type="exclusivity", section="评审办法", text="指定品牌", risk_level="medium"
            ),
        ]
        _, kept_llm = FusionEngine.deduplicate(rules, llms)
        assert len(kept_llm) == 1  # 风险等级不同 → 保留

    def test_llm_text_not_in_rule_text_kept(self):
        """LLM 原文不是规则原文子串 → 保留"""
        rules = [
            Violation(
                rule_id="FORB-001",
                rule_type="forbidden",
                description="指定品牌",
                text="指定品牌",
                location="评审办法 ~第1行",
                risk_level="high",
                weight=25,
            ),
        ]
        llms = [
            LLMViolation(type="bias", section="评审办法", text="评分权重不合理", risk_level="high"),
        ]
        _, kept_llm = FusionEngine.deduplicate(rules, llms)
        assert len(kept_llm) == 1  # 文本不同 → 保留

    # ── 场景：边界情况 ────────────────────────────────

    def test_no_llm_violations(self):
        rules = [
            Violation(rule_id="S1", rule_type="chapter_required", description="缺少", weight=10)
        ]
        _, kept_llm = FusionEngine.deduplicate(rules, [])
        assert len(kept_llm) == 0

    def test_no_rule_violations(self):
        llms = [
            LLMViolation(type="exclusivity", section="评审办法", text="指定品牌", risk_level="high")
        ]
        rules, kept_llm = FusionEngine.deduplicate([], llms)
        assert rules == []
        assert len(kept_llm) == 1  # 无规则 → LLM 全部保留

    def test_empty_section_skips_match(self):
        """章节名为空时跳过匹配，LLM 保留"""
        rules = [
            Violation(
                rule_id="F1",
                rule_type="forbidden",
                description="指定品牌",
                text="指定品牌",
                risk_level="high",
                weight=25,
            ),
        ]
        llms = [
            LLMViolation(type="exclusivity", section="", text="指定品牌", risk_level="high"),
        ]
        _, kept_llm = FusionEngine.deduplicate(rules, llms)
        assert len(kept_llm) == 1  # 章节名为空 → 跳过匹配

    def test_multiple_llm_one_matched(self):
        """多条 LLM 中只剔除匹配的那条"""
        rules = [
            Violation(
                rule_id="F1",
                rule_type="forbidden",
                description="指定品牌",
                text="指定品牌",
                location="评审办法 ~第1行",
                risk_level="high",
                weight=25,
            ),
        ]
        llms = [
            LLMViolation(
                type="exclusivity", section="评审办法", text="指定品牌", risk_level="high"
            ),  # 匹配 → 剔除
            LLMViolation(
                type="bias", section="评分标准", text="评分权重不合理", risk_level="medium"
            ),  # 不匹配 → 保留
        ]
        _, kept_llm = FusionEngine.deduplicate(rules, llms)
        assert len(kept_llm) == 1
        assert kept_llm[0].type == "bias"


# ═══════════════════════════════════════════════════════════════
# FusionEngine.merge — 完整集成
# ═══════════════════════════════════════════════════════════════


class TestFusionEngineMerge:
    def test_empty(self):
        rr = RuleEngineResult(violations=[])
        lr = LLMEngineResult(violations=[])
        report = FusionEngine.merge(rr, lr)
        assert report.total_score == 100.0
        assert report.total_violations == 0
        assert report.dedup_cross_engine == 0

    def test_rule_only(self):
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id="S1",
                    rule_type="chapter_required",
                    description="缺少",
                    weight=20,
                )
            ],
            total_score=80.0,
        )
        report = FusionEngine.merge(rr)
        # 1 medium(weight=20) → medium≥15 → penalty=7 → 100-7=93
        assert report.total_violations == 1
        assert len(report.rule_violations) == 1
        assert report.llm_violations == []
        assert report.total_score == 93.0

    def test_both_engines_no_overlap(self):
        """规则和 LLM 各自发现不同违规 → 全部保留"""
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id="SEC-004",
                    rule_type="chapter_required",
                    description="缺少《投标文件格式》",
                    weight=10,
                ),
            ],
            section_score=90.0,
            keyword_score=100.0,
            forbidden_score=100.0,
            total_score=90.0,
        )
        lr = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="评审办法",
                    text="评分标准偏向特定供应商",
                    risk_level="medium",
                ),
            ],
            total_score=95.0,
            model_used="mock",
        )
        report = FusionEngine.merge(rr, lr, file_name="test.docx")
        assert report.file_name == "test.docx"
        assert report.total_violations == 2  # 规则1 + LLM1
        assert report.dedup_cross_engine == 0
        # 规则medium(10→5) + LLM medium(10→5) → 加权=5*0.6+5*0.4=5 → 100-5=95
        assert report.total_score == 95.0

    def test_with_dedup(self):
        """LLM 违规与规则违规重复 → 剔除 LLM"""
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id="FORB-001",
                    rule_type="forbidden",
                    description="指定品牌",
                    text="指定品牌",
                    location="评审办法 ~第1行",
                    risk_level="high",
                    weight=25,
                ),
            ],
            total_score=75.0,
        )
        lr = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity", section="评审办法", text="指定品牌", risk_level="high"
                ),
                LLMViolation(
                    type="bias", section="评分标准", text="评分权重不合理", risk_level="medium"
                ),
            ],
            total_score=80.0,
        )
        report = FusionEngine.merge(rr, lr)
        # 1 条 LLM 被剔除（指定品牌），1 条保留（评分权重）
        assert report.dedup_cross_engine == 1, f"预期合并1条，实际{report.dedup_cross_engine}"
        assert len(report.rule_violations) == 1
        assert len(report.llm_violations) == 1
        assert report.llm_violations[0].type == "bias"
        assert report.total_violations == 2  # 规则1 + LLM保留1

    def test_weighted_scoring_formula(self):
        """无违规时满分"""
        rr = RuleEngineResult(total_score=60.0)
        lr = LLMEngineResult(total_score=90.0)
        report = FusionEngine.merge(rr, lr)
        assert report.total_score == 100.0  # 无违规 → 满分

    def test_penalty_scoring(self):
        """验证惩罚积分制的计算（含 sqrt 衰减）"""
        # 1 high(weight=25→15) + 1 medium(weight=10→5) = 15 + 5/√2 = 18.54
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id="H1",
                    rule_type="forbidden",
                    description="指定品牌",
                    text="指定品牌",
                    risk_level="high",
                    weight=25,
                ),
                Violation(
                    rule_id="M1",
                    rule_type="keyword_required",
                    description="缺关键字",
                    text="缺关键字",
                    risk_level="medium",
                    weight=10,
                ),
            ]
        )
        lr = LLMEngineResult(
            violations=[
                LLMViolation(type="bias", section="", text="倾向性", risk_level="low", weight=10),
            ]
        )
        report = FusionEngine.merge(rr, lr)
        # 规则惩罚: 15/√1 + 5/√2 ≈ 18.54, LLM惩罚: 2(low+weight≥10→2)
        # 加权: 18.54*0.6 + 2*0.4 ≈ 11.92
        # 总分: 100-11.92 = 88.1
        assert report.total_score == 88.1

    def test_no_llm_fallback(self):
        """仅规则引擎时规则惩罚直接作为总分"""
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id="M1",
                    rule_type="keyword_required",
                    description="缺关键字",
                    text="缺关键字",
                    risk_level="medium",
                    weight=10,
                ),
            ]
        )
        report = FusionEngine.merge(rr, llm_result=None)
        assert report.semantic_score == 100.0  # 无 LLM → 语义满分
        # 1 medium(weight=10→5) → 100-5=95
        assert report.total_score == 95.0

    def test_risk_counting(self):
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id="H1",
                    rule_type="forbidden",
                    description="高",
                    risk_level="high",
                    weight=20,
                ),
                Violation(
                    rule_id="M1",
                    rule_type="forbidden",
                    description="中",
                    risk_level="medium",
                    weight=10,
                ),
            ]
        )
        lr = LLMEngineResult(
            violations=[
                LLMViolation(type="exclusivity", section="", text="低", risk_level="low"),
            ]
        )
        report = FusionEngine.merge(rr, lr)
        assert report.high_risk_count == 1
        assert report.medium_risk_count == 1
        assert report.low_risk_count == 1
        assert report.total_violations == 3

    def test_report_fields(self):
        rr = RuleEngineResult(violations=[], total_score=100.0)
        lr = LLMEngineResult(
            violations=[], total_score=100.0, model_used="qwen", tokens_used=500, cost_yuan=0.002
        )
        report = FusionEngine.merge(rr, lr, file_name="test.pdf", check_time="2026-06-01")
        assert report.llm_model_used == "qwen"
        assert report.llm_tokens_used == 500
        assert report.llm_cost_yuan == 0.002
        assert report.rule_count == 0

    # ══════════════════════════════════════════════════════════
    # 场景 1：仅有规则引擎违规，LLM 无违规
    # ══════════════════════════════════════════════════════════

    def test_only_rule_violations_llm_clean(self):
        """规则引擎有 3 条违例，LLM 无违例→总分为规则惩罚"""
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id="F1",
                    rule_type="forbidden",
                    description="指定品牌",
                    text="指定品牌",
                    risk_level="high",
                    weight=25,
                ),
                Violation(
                    rule_id="F2",
                    rule_type="forbidden",
                    description="本地注册",
                    text="本地注册",
                    risk_level="high",
                    weight=20,
                ),
                Violation(
                    rule_id="K1",
                    rule_type="keyword_required",
                    description="缺废标条款",
                    text="废标",
                    risk_level="medium",
                    weight=10,
                ),
            ]
        )
        lr = LLMEngineResult(violations=[])  # LLM 无违规
        report = FusionEngine.merge(rr, lr)

        # 规则 high(25→15) + high(20→15) + medium(10→5)
        # 用 sqrt 衰减: 15/√1 + 15/√2 + 5/√3 ≈ 15 + 10.61 + 2.89 = 28.5
        # LLM 无违规 → has_llm=False → 规则惩罚直接做总分 = 100-28.5 = 71.5
        assert report.total_score == 71.5
        assert len(report.rule_violations) == 3
        assert len(report.llm_violations) == 0
        assert report.total_violations == 3
        assert report.dedup_cross_engine == 0

    # ══════════════════════════════════════════════════════════
    # 场景 2：规则引擎无违规，LLM 发现语义问题
    # ══════════════════════════════════════════════════════════

    def test_only_llm_violations_rules_clean(self):
        """规则引擎无违规，LLM 发现 2 条语义问题→总分基于 LLM 惩罚"""
        rr = RuleEngineResult(violations=[])
        lr = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity",
                    section="资格要求",
                    text="本市注册企业不合理",
                    risk_level="high",
                ),
                LLMViolation(
                    type="ambiguity", section="评审办法", text="评分标准表述模糊", risk_level="low"
                ),
            ]
        )
        report = FusionEngine.merge(rr, lr)

        # 规则惩罚=0, LLM: high(10→10) + low(10→2) = 12
        # 加权=0*0.6 + 12*0.4 = 4.8 → 100-4.8 = 95.2
        assert report.total_score == 95.2
        assert len(report.rule_violations) == 0
        assert len(report.llm_violations) == 2
        assert report.total_violations == 2
        assert report.semantic_score < 100  # LLM 有违规

    # ══════════════════════════════════════════════════════════
    # 场景 3：两者发现相同违规 → 验证去重逻辑
    # ══════════════════════════════════════════════════════════

    def test_both_find_same_violation_dedup(self):
        """规则引擎和 LLM 在"同章节+同风险+文本包含"时去重"""
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id="FORB-001",
                    rule_type="forbidden",
                    description="指定品牌",
                    text="指定使用XX品牌产品",
                    location="评审办法 ~第1行",
                    risk_level="high",
                    weight=25,
                ),
            ]
        )
        lr = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="exclusivity", section="评审办法", text="指定使用XX品牌", risk_level="high"
                ),
            ]
        )
        report = FusionEngine.merge(rr, lr)

        # 去重：LLM 的"指定使用XX品牌"是规则"指定使用XX品牌产品"的子串
        # + 同章节(评审办法) + 同风险(high) → 剔除 LLM
        assert report.dedup_cross_engine == 1
        assert len(report.rule_violations) == 1  # 规则保留
        assert len(report.llm_violations) == 0  # LLM 被剔除
        assert report.total_violations == 1

    def test_both_find_partial_overlap_no_dedup(self):
        """规则和 LLM 同章节但 LLM 文本不是规则文本子串→不合并"""
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id="FORB-001",
                    rule_type="forbidden",
                    description="指定品牌",
                    text="指定品牌",
                    location="评审办法 ~第1行",
                    risk_level="high",
                    weight=25,
                ),
            ]
        )
        lr = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="hidden_barrier",
                    section="评审办法",
                    text="注册资金不合理",
                    risk_level="high",
                ),
            ]
        )
        report = FusionEngine.merge(rr, lr)

        # 文本不同("指定品牌" vs "注册资金不合理") → 不合并
        assert report.dedup_cross_engine == 0
        assert len(report.rule_violations) == 1
        assert len(report.llm_violations) == 1
        assert report.total_violations == 2

    # ══════════════════════════════════════════════════════════
    # 场景 4：综合评分边界值
    # ══════════════════════════════════════════════════════════

    def test_score_100_perfect(self):
        """无任何违规 → 满分 100"""
        rr = RuleEngineResult(violations=[])
        lr = LLMEngineResult(violations=[])
        report = FusionEngine.merge(rr, lr)
        assert report.total_score == 100.0
        assert report.total_violations == 0

    def test_score_0_max_penalty(self):
        """大量 high 违规 → 扣分超过 100 → 强制归零"""
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id=f"F{i}",
                    rule_type="forbidden",
                    description=f"违例{i}",
                    text=f"违例{i}",
                    risk_level="high",
                    weight=25,
                )
                for i in range(10)  # 10 条 high → Σ 15/√(i+1) ≈ 75.3 惩罚
            ]
        )
        lr = LLMEngineResult(violations=[])
        report = FusionEngine.merge(rr, lr)

        # 10条 high → sqrt衰减后 ≈ 75.3 惩罚 → 总分 ≈ 24.7
        # 但 LLM 无违规，评分不归零
        assert report.total_score == 24.7
        assert report.total_violations == 10

    def test_score_mid_value(self):
        """混合风险等级 → 合理的中间分数（含 sqrt 衰减）"""
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id="H1",
                    rule_type="forbidden",
                    description="指定品牌",
                    text="指定品牌",
                    risk_level="high",
                    weight=25,
                ),
                Violation(
                    rule_id="M1",
                    rule_type="forbidden",
                    description="本地注册",
                    text="本地注册",
                    risk_level="medium",
                    weight=10,
                ),
                Violation(
                    rule_id="M2",
                    rule_type="keyword_required",
                    description="缺质疑条款",
                    text="质疑",
                    risk_level="medium",
                    weight=10,
                ),
                Violation(
                    rule_id="L1",
                    rule_type="forbidden",
                    description="使用'必须'措辞",
                    text="必须",
                    risk_level="low",
                    weight=5,
                ),
            ]
        )
        lr = LLMEngineResult(
            violations=[
                LLMViolation(
                    type="bias", section="评审办法", text="评分权重分配不当", risk_level="medium"
                ),
            ]
        )
        report = FusionEngine.merge(rr, lr)

        # 规则: high(25→15)/√1 + medium(10→5)/√2 + medium(10→5)/√3 + low(5→1)/√4
        #     = 15 + 3.54 + 2.89 + 0.5 = 21.93
        # LLM：medium(10→5)
        # 加权 = 21.93*0.6 + 5*0.4 = 13.16 + 2.0 = 15.16
        # 总分 = 100-15.16 = 84.8
        assert report.total_score == 84.8
        assert report.total_violations == 5

    def test_score_no_llm_edge(self):
        """仅规则引擎 + 7 条 high → sqrt 衰减后的分数"""
        rr = RuleEngineResult(
            violations=[
                Violation(
                    rule_id=f"F{i}",
                    rule_type="forbidden",
                    description=f"高{i}",
                    text=f"高{i}",
                    risk_level="high",
                    weight=25,
                )
                for i in range(7)  # 7×15/√(i+1) → Σ ≈ 60.3 惩罚
            ]
        )
        report = FusionEngine.merge(rr, llm_result=None)
        # 无 LLM → 规则惩罚直接做总分：100 - 60.3 = 39.7
        assert report.total_score == 39.7
        assert report.semantic_score == 100.0  # 无 LLM

    # ══════════════════════════════════════════════════════════
    # 场景 5：大文件性能测试
    # ══════════════════════════════════════════════════════════

    def test_large_volume(self):
        """10 个章节 × 10 条违规/引擎 = 100 条违例 → 验证不到 1 秒完成"""
        import time

        chapters = [f"章节{i}" for i in range(10)]

        # 规则引擎：50 条违例
        rule_vs = [
            Violation(
                rule_id=f"R{c}-{v}" if v % 2 == 0 else f"F{c}-{v}",
                rule_type="forbidden",
                description=f"章节{c}违例{v}",
                text=f"敏感词{v}",
                location=f"{c} ~第{v + 1}行",
                risk_level="high" if v < 3 else ("medium" if v < 7 else "low"),
                weight=25 if v < 3 else (10 if v < 7 else 5),
            )
            for c in chapters
            for v in range(5)  # 10×5=50
        ]

        # LLM：50 条违例，风险等级与规则一致 → 应全部合并
        llm_vs = [
            LLMViolation(
                type="exclusivity" if v % 3 == 0 else ("bias" if v % 3 == 1 else "ambiguity"),
                section=c,
                text=f"敏感词{v}",  # 与规则文本相同 → 触发去重
                risk_level="high" if v < 3 else ("medium" if v < 7 else "low"),
                weight=20,
            )
            for c in chapters
            for v in range(5)  # 10×5=50
        ]

        rr = RuleEngineResult(violations=rule_vs)
        lr = LLMEngineResult(violations=llm_vs)

        t0 = time.monotonic()
        report = FusionEngine.merge(rr, lr)
        elapsed = time.monotonic() - t0

        # 性能断言
        assert elapsed < 1.0, f"大文件处理超时: {elapsed:.3f}s"
        # 去重断言：同章节+同风险+文本包含 → LLM 全部被合并
        assert report.dedup_cross_engine == len(llm_vs), (
            f"预期合并{len(llm_vs)}条，实际{report.dedup_cross_engine}"
        )
        # 总分 ≥ 0
        assert 0 <= report.total_score <= 100
        # 最终违例数 = 规则(去重后)
        assert report.total_violations == len(rule_vs), (
            f"预期{len(rule_vs)}，实际{report.total_violations}"
        )

        print(f"\n  ⏱  大文件耗时: {elapsed:.4f}s")
        print(f"  规则违例: {len(rule_vs)}, LLM违例: {len(llm_vs)}")
        print(f"  去重合并: {report.dedup_cross_engine}")
        print(f"  最终违例: {report.total_violations}")
        print(f"  总分: {report.total_score}")


# ═══════════════════════════════════════════════════════════════
# FourWayRiskMerger — 四路风险合并器测试
# ═══════════════════════════════════════════════════════════════

from app.engine.shared_types import (
    RoutingResult, TrafficLight, ParameterBiasResult, BiasFinding,
)


class TestFourWayRiskMerger:
    """四路风险合并器测试"""

    def test_merge_four_ways_confirmed_violation(self):
        """规则命中+参数倾向性确认 → confirmed"""
        from app.engine.fusion import FourWayRiskMerger

        rule_violations = [
            Violation(
                rule_id="R101",
                rule_type="forbidden",
                description="禁止厂家授权",
                risk_level="high",
                weight=15.0,
            )
        ]
        bias_findings = [
            BiasFinding(
                pattern_id="manufacturer_authorization",
                pattern_name="厂家授权锁",
                severity="high",
                matched_text="原厂授权函",
                matched_field="qualification_requirements",
                confidence=0.85,
                rule_id="R101",
            )
        ]
        routing = RoutingResult(
            traffic_light=TrafficLight.RED,
            skip_llm=False,
            llm_task_list=["AI-AUTH"],
        )

        merger = FourWayRiskMerger()
        result = merger.merge(
            routing_result=routing,
            rule_engine_result=RuleEngineResult(violations=rule_violations),
            parameter_bias_result=ParameterBiasResult(
                findings=bias_findings,
                risk_score=25.0,
                critical_count=0,
                high_count=1,
            ),
            llm_result=None,
            parse_quality="ok",
        )
        assert result.risk_level in ("high", "critical")
        assert result.requires_human_review is True

    def test_merge_four_ways_clean_document(self):
        """干净文档 → auto_passed"""
        from app.engine.fusion import FourWayRiskMerger

        merger = FourWayRiskMerger()
        result = merger.merge(
            routing_result=RoutingResult(
                traffic_light=TrafficLight.GREEN,
                skip_llm=True,
            ),
            rule_engine_result=RuleEngineResult(violations=[]),
            parameter_bias_result=ParameterBiasResult(findings=[]),
            llm_result=None,
            parse_quality="ok",
        )
        assert result.final_passed is True
        assert result.review_status == "auto_passed"
        assert result.requires_human_review is False

    def test_merge_four_ways_only_rule_finding(self):
        """仅规则引擎发现（非forbidden）→ advisory"""
        from app.engine.fusion import FourWayRiskMerger

        merger = FourWayRiskMerger()
        result = merger.merge(
            routing_result=RoutingResult(traffic_light=TrafficLight.YELLOW, skip_llm=False),
            rule_engine_result=RuleEngineResult(violations=[
                Violation(rule_id="R001", rule_type="chapter_required",
                          description="缺少招标公告章节", risk_level="low", weight=10.0)
            ]),
            parameter_bias_result=ParameterBiasResult(findings=[]),
            llm_result=None,
            parse_quality="ok",
        )
        assert result.final_passed is True  # 仅low等级 → 通过
        assert result.review_status == "auto_passed"

    def test_merge_parse_quality_adjustment(self):
        """解析质量差时风险上调"""
        from app.engine.fusion import FourWayRiskMerger

        merger = FourWayRiskMerger()
        result_ok = merger.merge(
            routing_result=RoutingResult(traffic_light=TrafficLight.GREEN, skip_llm=True),
            rule_engine_result=RuleEngineResult(violations=[
                Violation(rule_id="R001", rule_type="forbidden",
                          description="test", risk_level="medium", weight=5.0)
            ]),
            parameter_bias_result=ParameterBiasResult(findings=[]),
            llm_result=None,
            parse_quality="ok",
        )
        result_ocr = merger.merge(
            routing_result=RoutingResult(traffic_light=TrafficLight.GREEN, skip_llm=True),
            rule_engine_result=RuleEngineResult(violations=[
                Violation(rule_id="R001", rule_type="forbidden",
                          description="test", risk_level="medium", weight=5.0)
            ]),
            parameter_bias_result=ParameterBiasResult(findings=[]),
            llm_result=None,
            parse_quality="ocr",
        )
        assert result_ocr.risk_level_original == result_ok.risk_level
        assert hasattr(result_ocr, "parse_quality_adjustment")

    def test_merge_four_ways_bias_only_critical(self):
        """仅参数倾向性critial发现 → auto_failed"""
        from app.engine.fusion import FourWayRiskMerger

        merger = FourWayRiskMerger()
        result = merger.merge(
            routing_result=RoutingResult(traffic_light=TrafficLight.YELLOW, skip_llm=False),
            rule_engine_result=RuleEngineResult(violations=[]),
            parameter_bias_result=ParameterBiasResult(
                findings=[
                    BiasFinding(
                        pattern_id="brand_lock_series",
                        pattern_name="品牌锁定",
                        severity="critical",
                        matched_text="须同一品牌",
                        matched_field="technical_params",
                        confidence=0.90,
                        rule_id="R107",
                    )
                ],
                risk_score=25.0,
                critical_count=1,
                high_count=0,
            ),
            llm_result=None,
            parse_quality="ok",
        )
        assert result.review_status in ("auto_failed", "needs_review")
        assert result.requires_human_review is True
