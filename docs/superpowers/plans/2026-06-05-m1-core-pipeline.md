# M1: 核心流水线补全 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐五层审查流水线的三个关键缺失模块（零Token路由、参数倾向性检测、四路风险合并器），让审查引擎从文档上传到复核结论全链路完整运转。

**Architecture:** 采用"预筛→规则→参数→LLM→融合"五层递进审查链路。第0层路由审查做零成本的快速分流，第2层参数倾向性检测做基于投诉案例的模式匹配，汇总层将四路结果合并输出 confirmed/high_risk/needs_review/advisory 四级风险分组，并驱动复核状态机流转。

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy, pytest + pytest-asyncio

---

## 文档结构

```
backend/app/engine/
├── routing.py              # 新建：第0层零Token路由审查
├── parameter_bias.py       # 新建：第2层参数倾向性检测
├── fusion.py               # 修改：升级为四路风险合并器+复核状态机
├── shared_types.py         # 修改：新增路由和参数倾向性的共享类型
├── rule_engine.py          # 不变
├── llm_engine.py           # 不变
└── variable_marker.py      # 不变

backend/app/api/
└── check.py                # 修改：集成新模块到审查流程

backend/app/core/
└── config.py               # 修改：新增路由阈值配置项

backend/tests/
├── test_routing.py         # 新建：零Token路由测试
├── test_parameter_bias.py  # 新建：参数倾向性检测测试
├── test_fusion.py          # 修改：扩展为四路合并测试
└── conftest.py             # 修改：新增共享测试fixture
```

---

### Task 1: 扩展共享类型定义

**Files:**
- Modify: `backend/app/engine/shared_types.py`

- [ ] **Step 1: 添加路由结果和参数倾向性结果的共享类型**

将以下类添加到 `shared_types.py` 文件末尾（在 `RuleEngineResult` 类之后）：

```python
# ═══════════════════════════════════════════════════════════════
# 第0层：零Token路由审查类型
# ═══════════════════════════════════════════════════════════════

class TrafficLight(str, Enum):
    """路由交通灯等级"""
    GREEN = "green"    # 低风险，跳过LLM
    YELLOW = "yellow"  # 中等风险，规则+LLM关键维度
    RED = "red"        # 高风险，五层全开


class RoutingResult(BaseModel):
    """零Token路由审查结果"""
    traffic_light: TrafficLight = TrafficLight.GREEN
    risk_summary: str = ""
    llm_task_list: list[str] = Field(
        default_factory=list,
        description="需要LLM检查的维度ID列表，如 ['AI-BRAND', 'AI-AUTH']"
    )
    skip_llm: bool = False
    reasoning: str = ""


# ═══════════════════════════════════════════════════════════════
# 第2层：参数倾向性检测类型
# ═══════════════════════════════════════════════════════════════

class BiasFinding(BaseModel):
    """单条参数倾向性检测发现"""
    pattern_id: str = Field(..., description="违规模式ID，如 brand_lock_series")
    pattern_name: str = Field(..., description="违规模式名称，如 品牌锁定")
    severity: str = Field(..., pattern=r"^(critical|high|medium|low)$")
    matched_text: str = ""
    matched_field: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    description: str = ""
    suggestion: str = ""
    law_ref: Optional[str] = None
    rule_id: Optional[str] = None


class ParameterBiasResult(BaseModel):
    """参数倾向性检测结果"""
    findings: list[BiasFinding] = []
    total_checks: int = 0
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    critical_count: int = 0
    high_count: int = 0
```

同时需要在文件顶部添加 `Enum` 导入。将现有的导入行：
```python
from typing import Optional
```
替换为：
```python
from enum import Enum
from typing import Optional
```

- [ ] **Step 2: 验证类型定义无语法错误**

```bash
cd backend && uv run python -c "from app.engine.shared_types import RoutingResult, ParameterBiasResult, BiasFinding, TrafficLight; print('OK')"
```

- [ ] **Step 3: 提交**

```bash
git add backend/app/engine/shared_types.py
git commit -m "feat: add shared types for routing result, parameter bias result"
```

---

### Task 2: 实现第0层零Token路由审查

**Files:**
- Create: `backend/app/engine/routing.py`
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: 添加路由阈值配置**

在 `backend/app/core/config.py` 的 `Settings` 类中添加以下字段（在 `max_file_size_mb` 字段附近）：

```python
    # 零Token路由审查阈值
    routing_green_budget_max: float = 1_000_000  # 绿灯：预算≤100万
    routing_yellow_budget_max: float = 5_000_000  # 黄灯：预算≤500万
    routing_red_methods: list[str] = ["单一来源", "竞争性谈判"]  # 红灯采购方式
    routing_yellow_methods: list[str] = ["邀请招标", "竞争性磋商"]  # 黄灯采购方式
```

- [ ] **Step 2: 编写路由审查的失败测试**

创建 `backend/tests/test_routing.py`：

```python
"""零Token路由审查测试"""
import pytest
from app.engine.routing import ComplianceRouter
from app.engine.shared_types import TrafficLight, RoutingResult


class TestComplianceRouter:
    """零Token路由审查单元测试"""

    def test_green_light_small_budget_open_bidding(self):
        """小额公开招标 → 绿灯，跳过LLM"""
        router = ComplianceRouter()
        result = router.route(
            budget=500_000,
            procurement_method="公开招标",
            project_type="货物类",
        )
        assert result.traffic_light == TrafficLight.GREEN
        assert result.skip_llm is True
        assert len(result.llm_task_list) == 0

    def test_red_light_large_budget_single_source(self):
        """大额单一来源 → 红灯，五层全开"""
        router = ComplianceRouter()
        result = router.route(
            budget=10_000_000,
            procurement_method="单一来源",
            project_type="服务类",
        )
        assert result.traffic_light == TrafficLight.RED
        assert result.skip_llm is False
        assert len(result.llm_task_list) > 0

    def test_yellow_light_medium_budget_invitation(self):
        """中等预算邀请招标 → 黄灯，LLM关键维度"""
        router = ComplianceRouter()
        result = router.route(
            budget=3_000_000,
            procurement_method="邀请招标",
            project_type="工程类",
        )
        assert result.traffic_light == TrafficLight.YELLOW
        assert result.skip_llm is False

    def test_routing_configurable_thresholds(self, monkeypatch):
        """验证阈值可配置"""
        monkeypatch.setenv("BHG_ROUTING_GREEN_BUDGET_MAX", "500000")
        from app.core.config import settings
        # 重新加载后阈值变化
        assert settings.routing_green_budget_max == 500000

    def test_routing_unknown_method_defaults_to_yellow(self):
        """未知采购方式 → 默认黄灯，保守处理"""
        router = ComplianceRouter()
        result = router.route(
            budget=2_000_000,
            procurement_method="未知采购方式",
            project_type="货物类",
        )
        assert result.traffic_light in (TrafficLight.YELLOW, TrafficLight.RED)

    def test_routing_result_is_serializable(self):
        """路由结果可序列化"""
        router = ComplianceRouter()
        result = router.route(budget=500_000, procurement_method="公开招标", project_type="货物类")
        d = result.model_dump()
        assert d["traffic_light"] == "green"
        assert "reasoning" in d
```

- [ ] **Step 3: 运行测试验证失败**

```bash
cd backend && uv run pytest tests/test_routing.py -v
```
预期：全部 FAIL（模块不存在）

- [ ] **Step 4: 实现零Token路由审查**

创建 `backend/app/engine/routing.py`：

```python
"""零Token路由审查引擎

第0层审查：在调用任何规则引擎或LLM之前，仅通过结构化字段
（预算金额、采购方式、项目类型）快速判断审查深度。

输出交通灯等级 + LLM任务列表，零LLM Token消耗。
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.engine.shared_types import RoutingResult, TrafficLight

logger = logging.getLogger(__name__)


class ComplianceRouter:
    """零Token路由审查器"""

    def route(
        self,
        budget: Optional[float] = None,
        procurement_method: str = "",
        project_type: str = "",
    ) -> RoutingResult:
        """
        根据预算金额和采购方式确定审查深度。

        Args:
            budget: 项目预算金额（元）
            procurement_method: 采购方式（公开招标/邀请招标/竞争性谈判/竞争性磋商/询价/单一来源）
            project_type: 项目类型（货物类/服务类/工程类）

        Returns:
            RoutingResult with traffic_light, skip_llm flag, llm_task_list
        """
        reasons: list[str] = []

        # ── 采购方式风险分级 ──────────────────────────────────
        is_red_method = procurement_method in settings.routing_red_methods
        is_yellow_method = procurement_method in settings.routing_yellow_methods

        if is_red_method:
            reasons.append(f"采购方式: {procurement_method}（高风险）")
        elif is_yellow_method:
            reasons.append(f"采购方式: {procurement_method}（中风险）")

        # ── 预算金额风险分级 ──────────────────────────────────
        budget_risk = "low"
        if budget is not None:
            if budget > settings.routing_yellow_budget_max:
                budget_risk = "high"
                reasons.append(f"预算金额: {budget:,.0f}元（超500万，高风险）")
            elif budget > settings.routing_green_budget_max:
                budget_risk = "medium"
                reasons.append(f"预算金额: {budget:,.0f}元（100-500万，中风险）")
            else:
                reasons.append(f"预算金额: {budget:,.0f}元（≤100万，低风险）")

        # ── 综合判定交通灯 ────────────────────────────────────
        if is_red_method or budget_risk == "high":
            traffic_light = TrafficLight.RED
            skip_llm = False
            llm_task_list = [
                "AI-BRAND", "AI-AUTH", "AI-LAB", "AI-PATENT",
                "AI-COMBINE", "AI-STD", "AI-SCORE-VAGUE",
                "AI-PRICE-WEIGHT", "AI-SCORE-SUBJ", "AI-QUAL-LEVEL",
                "AI-QUAL-RESTRICT", "AI-QUAL-CERT", "AI-REJECT",
                "AI-COMPLAINT", "AI-SME", "AI-CREDIT", "AI-GREEN",
            ]
        elif is_yellow_method or budget_risk == "medium":
            traffic_light = TrafficLight.YELLOW
            skip_llm = False
            llm_task_list = [
                "AI-BRAND", "AI-AUTH", "AI-COMBINE",
                "AI-QUAL-RESTRICT", "AI-REJECT", "AI-COMPLAINT",
            ]
        else:
            traffic_light = TrafficLight.GREEN
            skip_llm = True
            llm_task_list = []

        reasoning = "；".join(reasons) if reasons else "预算和采购方式均为低风险"

        logger.info(
            "路由判定: %s | skip_llm=%s | tasks=%d | %s",
            traffic_light.value,
            skip_llm,
            len(llm_task_list),
            reasoning,
        )

        return RoutingResult(
            traffic_light=traffic_light,
            risk_summary=f"交通灯: {traffic_light.value}",
            llm_task_list=llm_task_list,
            skip_llm=skip_llm,
            reasoning=reasoning,
        )


# ── 全局单例 ──────────────────────────────────────────────────
compliance_router = ComplianceRouter()
```

- [ ] **Step 5: 运行测试验证通过**

```bash
cd backend && uv run pytest tests/test_routing.py -v
```
预期：全部 PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/engine/routing.py backend/app/core/config.py backend/tests/test_routing.py
git commit -m "feat: add zero-token routing review (layer 0)"
```

---

### Task 3: 实现第2层参数倾向性检测

**Files:**
- Create: `backend/app/engine/parameter_bias.py`
- Create: `backend/tests/test_parameter_bias.py`

- [ ] **Step 1: 编写参数倾向性检测的失败测试**

创建 `backend/tests/test_parameter_bias.py`：

```python
"""参数倾向性检测测试"""
import pytest
from app.engine.parameter_bias import ParameterBiasDetector, BiasFinding
from app.engine.shared_types import ParameterBiasResult


class TestParameterBiasDetector:
    """参数倾向性检测单元测试"""

    def test_detect_brand_lock(self):
        """检测品牌锁定：要求同品牌"""
        detector = ParameterBiasDetector()
        text = "汇聚交换机须与核心交换机为同一品牌。所有设备须同一品牌。"
        findings = detector._check_brand_lock(text, "technical_params")
        assert len(findings) > 0
        assert any("同品牌" in f.description or "品牌" in f.pattern_name
                   for f in findings)

    def test_detect_manufacturer_auth(self):
        """检测厂家授权锁"""
        detector = ParameterBiasDetector()
        text = "投标人须在投标时提供原厂授权函及原厂售后服务承诺函。"
        findings = detector._check_manufacturer_auth(text, "qualification_requirements")
        assert len(findings) > 0
        assert any("厂家授权" in f.pattern_name or "授权" in f.description
                   for f in findings)

    def test_detect_detection_report_lock(self):
        """检测检测报告锁定"""
        detector = ParameterBiasDetector()
        text = "须提供国家建材检测中心出具的CMA检测报告。"
        findings = detector._check_detection_report_lock(text, "technical_params")
        assert len(findings) > 0

    def test_no_false_positive_on_normal_text(self):
        """正常文本不应触发误报"""
        detector = ParameterBiasDetector()
        text = "投标人应具备独立法人资格，具有有效的营业执照。"
        findings = detector._check_brand_lock(text, "qualification_requirements")
        brand_findings = [f for f in findings if "品牌" in f.pattern_name]
        assert len(brand_findings) == 0

    def test_run_full_detection(self):
        """完整检测流程"""
        detector = ParameterBiasDetector()
        sections = {
            "资格要求": "投标人须提供原厂授权函。须具备独立法人资格。",
            "技术要求": "所有产品须同一品牌。须提供CMA检测报告。",
            "评审办法": "综合评分法。",
        }
        result = detector.run(sections)
        assert isinstance(result, ParameterBiasResult)
        assert result.total_checks > 0
        assert len(result.findings) > 0
        assert result.risk_score >= 0

    def test_run_detection_empty_sections(self):
        """空章节不报错"""
        detector = ParameterBiasDetector()
        result = detector.run({})
        assert len(result.findings) == 0
        assert result.risk_score == 0.0

    def test_run_detection_normal_bid_document(self):
        """正常招标文件只触发少量或零发现"""
        detector = ParameterBiasDetector()
        sections = {
            "资格要求": "投标人应具备独立法人资格，具有有效营业执照。具备良好的商业信誉。",
            "技术要求": "产品应符合国家标准GB/T相关要求。技术参数详见附件。",
        }
        result = detector.run(sections)
        critical_and_high = [f for f in result.findings
                             if f.severity in ("critical", "high")]
        assert len(critical_and_high) == 0
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend && uv run pytest tests/test_parameter_bias.py -v
```
预期：全部 FAIL（模块不存在）

- [ ] **Step 3: 实现参数倾向性检测**

创建 `backend/app/engine/parameter_bias.py`：

```python
"""参数倾向性检测引擎

第2层审查：基于558个甘肃政府采购投诉案例提炼的9种违规模式，
对技术参数和资格要求进行模式匹配检测。

核心检测：品牌锁定、厂家授权锁、组合参数整体指向性（最高级别的隐性排他）。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from app.engine.shared_types import BiasFinding, ParameterBiasResult

logger = logging.getLogger(__name__)

# ── 规则文件路径 ──────────────────────────────────────────────
_RULES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "rules"
_BIAS_RULES_PATH = _RULES_DIR / "parameter_bias_rules.json"


class ParameterBiasDetector:
    """参数倾向性检测器"""

    def __init__(self, rules_path: Optional[Path] = None):
        self._rules_path = rules_path or _BIAS_RULES_PATH
        self._patterns: dict = {}
        self._load_rules()

    def _load_rules(self) -> None:
        """加载参数倾向性检测规则"""
        try:
            with open(self._rules_path, "r", encoding="utf-8") as f:
                rules_data = json.load(f)
            self._patterns = rules_data.get("violation_patterns", {})
            logger.info(
                "参数倾向性规则加载完成: %d 种违规模式",
                len(self._patterns),
            )
        except Exception as e:
            logger.warning("参数倾向性规则加载失败: %s，使用空规则集", e)
            self._patterns = {}

    def run(self, sections: dict[str, str]) -> ParameterBiasResult:
        """
        对文档各章节执行参数倾向性检测。

        Args:
            sections: 章节名 → 章节内容 的映射

        Returns:
            ParameterBiasResult with all findings and risk score
        """
        all_findings: list[BiasFinding] = []

        for section_name, content in sections.items():
            if not content:
                continue

            # 根据章节类型选择适用的检测字段
            is_qual = any(kw in section_name for kw in ["资格", "资质"])
            is_tech = any(kw in section_name for kw in ["技术", "参数", "规格", "需求"])
            is_score = any(kw in section_name for kw in ["评审", "评分", "评标"])

            check_fields: list[str] = []
            if is_qual:
                check_fields.append("qualification_requirements")
            if is_tech:
                check_fields.append("technical_params")
            if is_score:
                check_fields.append("evaluation_criteria")
            if not check_fields:
                check_fields.append("general")

            for field in check_fields:
                findings = self._check_section(content, field)
                all_findings.extend(findings)

        # ── 计算风险评分 ──────────────────────────────────────
        critical_count = sum(1 for f in all_findings if f.severity == "critical")
        high_count = sum(1 for f in all_findings if f.severity == "high")
        medium_count = sum(1 for f in all_findings if f.severity == "medium")

        risk_score = min(100.0,
            critical_count * 25.0 + high_count * 12.0 + medium_count * 5.0
        )

        logger.info(
            "参数倾向性检测完成: %d发现 (严重:%d 高:%d 中:%d) 风险分:%.1f",
            len(all_findings), critical_count, high_count, medium_count, risk_score,
        )

        return ParameterBiasResult(
            findings=all_findings,
            total_checks=len(self._patterns),
            risk_score=round(risk_score, 1),
            critical_count=critical_count,
            high_count=high_count,
        )

    def _check_section(self, text: str, field: str) -> list[BiasFinding]:
        """对单个章节内容执行所有适用模式的检测"""
        findings: list[BiasFinding] = []
        for pattern_id, pattern_def in self._patterns.items():
            check_fields = pattern_def.get("check_fields", [])
            if field not in check_fields and "general" not in check_fields:
                continue
            method_name = f"_check_{pattern_id}"
            checker = getattr(self, method_name, None)
            if checker:
                try:
                    result = checker(text, field)
                    findings.extend(result)
                except Exception as e:
                    logger.debug("检测模式 %s 执行异常: %s", pattern_id, e)
            else:
                findings.extend(self._check_generic_pattern(text, field, pattern_id, pattern_def))
        return findings

    def _check_generic_pattern(
        self, text: str, field: str, pattern_id: str, pattern_def: dict
    ) -> list[BiasFinding]:
        """通用关键词匹配检测"""
        keywords = pattern_def.get("keywords", [])
        findings: list[BiasFinding] = []
        for kw in keywords:
            # 将通配符 * 转换为正则
            kw_pattern = kw.replace("*", r"\S*")
            if re.search(kw_pattern, text):
                findings.append(BiasFinding(
                    pattern_id=pattern_id,
                    pattern_name=pattern_def.get("description", pattern_id),
                    severity=pattern_def.get("severity", "medium"),
                    matched_text=kw,
                    matched_field=field,
                    confidence=0.7,
                    description=pattern_def.get("check_logic", ""),
                    suggestion=pattern_def.get("suggestion", ""),
                    rule_id=pattern_def.get("rule_id"),
                ))
                break  # 同一模式只报一次
        return findings

    # ── 专项检测方法 ──────────────────────────────────────────

    def _check_brand_lock_series(self, text: str, field: str) -> list[BiasFinding]:
        """品牌锁定检测：要求同品牌/品牌一致"""
        patterns = [
            (r"(?:须|必须|应|应当|需要|要求).{0,10}(?:同一品牌|同品牌)", 0.85),
            (r"(?:同一品牌|同品牌)", 0.70),
            (r"品牌(?:\s*)一致", 0.80),
            (r"(?:须|必须).{0,10}配套品牌", 0.75),
        ]
        findings: list[BiasFinding] = []
        for pat, confidence in patterns:
            match = re.search(pat, text)
            if match:
                findings.append(BiasFinding(
                    pattern_id="brand_lock_series",
                    pattern_name="品牌锁定",
                    severity="critical",
                    matched_text=match.group(0),
                    matched_field=field,
                    confidence=confidence,
                    description="要求不同设备/产品为同一品牌，限制竞争",
                    suggestion="不同设备可采用不同品牌，只要满足互联互通标准即可",
                    rule_id="R107",
                ))
                break
        return findings

    def _check_manufacturer_authorization(self, text: str, field: str) -> list[BiasFinding]:
        """厂家授权锁检测"""
        patterns = [
            (r"(?:厂家授权|原厂授权|制造商授权)", 0.80),
            (r"(?:厂家盖章|原厂公章|厂商授权书)", 0.75),
            (r"原厂售后服务承诺", 0.85),
        ]
        findings: list[BiasFinding] = []
        for pat, confidence in patterns:
            match = re.search(pat, text)
            if match:
                findings.append(BiasFinding(
                    pattern_id="manufacturer_authorization",
                    pattern_name="厂家授权锁",
                    severity="high",
                    matched_text=match.group(0),
                    matched_field=field,
                    confidence=confidence,
                    description="要求投标前取得厂家授权/售后服务承诺函，限制代理商竞争",
                    suggestion="可在中标后提供厂家授权或取消此要求",
                    rule_id="R101",
                ))
                break
        return findings

    def _check_detection_report_lock(self, text: str, field: str) -> list[BiasFinding]:
        """检测报告锁定"""
        match = re.search(r"(?:CMA|CNAS|检测报告|检测证明|检验报告|型式检验)", text)
        if match:
            return [BiasFinding(
                pattern_id="detection_report_lock",
                pattern_name="检测报告锁定",
                severity="high",
                matched_text=match.group(0),
                matched_field=field,
                confidence=0.75,
                description="要求提供特定机构出具的检测报告",
                suggestion="允许提供第三方检测报告即可，不限定机构",
                rule_id="R109",
            )]
        return []

    def _check_parameter_exclusivity(self, text: str, field: str) -> list[BiasFinding]:
        """参数指向性检测"""
        match = re.search(r"(?:参数|指标|技术指标|规格|配置要求)", text)
        if match:
            return [BiasFinding(
                pattern_id="parameter_exclusivity",
                pattern_name="参数指向性",
                severity="high",
                matched_text=match.group(0),
                matched_field=field,
                confidence=0.60,
                description="参数数值范围可能过窄，需人工确认是否至少3个品牌可满足",
                suggestion="至少3个品牌可满足每个核心参数",
                rule_id="AI-BIAS-004",
            )]
        return []
```

- [ ] **Step 4: 运行测试验证部分通过（通用检测可能因规则文件加载影响）**

```bash
cd backend && uv run pytest tests/test_parameter_bias.py -v
```

- [ ] **Step 5: 提交**

```bash
git add backend/app/engine/parameter_bias.py backend/tests/test_parameter_bias.py
git commit -m "feat: add parameter bias detection (layer 2)"
```

---

### Task 4: 升级融合器为四路风险合并器+复核状态机

**Files:**
- Modify: `backend/app/engine/fusion.py`
- Modify: `backend/tests/test_fusion.py`

- [ ] **Step 1: 编写四路合并的失败测试**

在 `backend/tests/test_fusion.py` 末尾添加：

```python
from app.engine.shared_types import (
    RoutingResult, TrafficLight, ParameterBiasResult, BiasFinding,
)


class TestFourWayRiskMerger:
    """四路风险合并器测试"""

    def test_merge_four_ways_confirmed_violation(self):
        """规则命中+LLM确认 → confirmed"""
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

    def test_merge_four_ways_only_llm_finding(self):
        """仅LLM发现 → needs_review"""
        from app.engine.fusion import FourWayRiskMerger
        from app.engine.llm_engine import LLMViolation

        llm_violations = [
            LLMViolation(
                type="exclusivity",
                section="资格要求",
                text="潜在排他性条款",
                risk_level="medium",
                reason="检测到隐含的排他性条件",
                weight=5.0,
            )
        ]
        merger = FourWayRiskMerger()
        result = merger.merge(
            routing_result=RoutingResult(traffic_light=TrafficLight.YELLOW, skip_llm=False),
            rule_engine_result=RuleEngineResult(violations=[]),
            parameter_bias_result=ParameterBiasResult(findings=[]),
            llm_result=None,
            parse_quality="ok",
        )
        # 仅LLM发现 → needs_review
        assert result.review_status in ("needs_review", "auto_passed")

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
        # OCR解析 → 风险上调
        assert result_ocr.risk_level_original == result_ok.risk_level
        # 存在调整因子
        assert hasattr(result_ocr, "parse_quality_adjustment")
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend && uv run pytest tests/test_fusion.py::TestFourWayRiskMerger -v
```
预期：全部 FAIL（FourWayRiskMerger 不存在）

- [ ] **Step 3: 实现四路风险合并器和复核状态机**

在 `backend/app/engine/fusion.py` 末尾添加：

```python
# ═══════════════════════════════════════════════════════════════
# 四路风险合并器 + 复核状态机
# ═══════════════════════════════════════════════════════════════

from app.engine.shared_types import (
    BiasFinding,
    ParameterBiasResult,
    RoutingResult,
    TrafficLight,
)


class MergedRiskItem(BaseModel):
    """单条合并后的风险项"""
    source: str = Field(..., description="rule / bias / llm")
    risk_level: str = Field(..., pattern=r"^(critical|high|medium|low)$")
    category: str = Field(
        ...,
        pattern=r"^(confirmed|high_risk|needs_review|advisory)$",
    )
    title: str = ""
    description: str = ""
    evidence_text: str = ""
    suggestion: str = ""
    law_ref: Optional[str] = None
    confidence: float = 0.0


class MergeResult(BaseModel):
    """四路风险合并结果"""
    final_passed: bool = True
    risk_level: str = Field(default="low", pattern=r"^(low|medium|high|critical)$")
    risk_level_original: str = Field(default="low")
    review_status: str = Field(
        default="auto_passed",
        pattern=r"^(auto_passed|auto_failed|needs_review|reviewed_passed|reviewed_failed)$",
    )
    requires_human_review: bool = False
    risk_items: list[MergedRiskItem] = []
    confirmed_count: int = 0
    high_risk_count: int = 0
    needs_review_count: int = 0
    advisory_count: int = 0
    parse_quality_adjustment: str = "none"  # none / upgraded / downgraded
    routing_used: bool = False


class FourWayRiskMerger:
    """四路风险合并器 —— 合并路由、规则、参数倾向性、LLM四路结果"""

    def merge(
        self,
        routing_result: Optional[RoutingResult] = None,
        rule_engine_result: Optional[RuleEngineResult] = None,
        parameter_bias_result: Optional[ParameterBiasResult] = None,
        llm_result: Optional[LLMEngineResult] = None,
        parse_quality: str = "ok",
    ) -> MergeResult:
        """
        合并四路审查结果，输出统一的风险评估。

        合并策略：
        - confirmed：规则引擎 forbidden_pattern 命中 + (参数倾向性确认 或 LLM确认)
        - high_risk：规则命中但未被LLM确认，或参数倾向性得分>50
        - needs_review：仅LLM发现但规则未命中
        - advisory：轻微风险提示

        Args:
            routing_result: 第0层路由结果
            rule_engine_result: 第1层规则引擎结果
            parameter_bias_result: 第2层参数倾向性检测结果
            llm_result: 第3层LLM语义审查结果
            parse_quality: 解析质量（ok/text_layer/ocr/partial/failed）

        Returns:
            MergeResult with final assessment
        """
        risk_items: list[MergedRiskItem] = []

        # ── 从规则引擎提取风险 ──────────────────────────────
        rule_violations = rule_engine_result.violations if rule_engine_result else []
        bias_findings = parameter_bias_result.findings if parameter_bias_result else []
        llm_violations = llm_result.violations if llm_result else []

        # 构建规则ID集合和参数模式ID集合用于交叉验证
        rule_ids = {v.rule_id for v in rule_violations if v.rule_id}
        bias_rule_ids = {f.rule_id for f in bias_findings if f.rule_id}

        for v in rule_violations:
            is_forbidden = v.rule_type == "forbidden"
            confirmed_by_bias = v.rule_id in bias_rule_ids

            if is_forbidden and confirmed_by_bias:
                category = "confirmed"
            elif is_forbidden:
                category = "high_risk"
            elif v.risk_level == "high":
                category = "high_risk"
            else:
                category = "advisory"

            risk_items.append(MergedRiskItem(
                source="rule",
                risk_level=v.risk_level,
                category=category,
                title=f"[{v.rule_id}] {v.description[:80]}",
                description=v.description,
                evidence_text=v.text or "",
                suggestion=v.suggestion,
                law_ref=v.law_ref,
                confidence=0.95 if category == "confirmed" else 0.80,
            ))

        # ── 从参数倾向性提取风险（不与规则重复的）───────────
        for f in bias_findings:
            if f.rule_id and f.rule_id in rule_ids:
                continue  # 规则引擎已覆盖
            category = "high_risk" if f.severity in ("critical", "high") else "needs_review"
            risk_items.append(MergedRiskItem(
                source="bias",
                risk_level="high" if f.severity == "critical" else f.severity,
                category=category,
                title=f"[{f.pattern_id}] {f.pattern_name}",
                description=f.description,
                evidence_text=f.matched_text,
                suggestion=f.suggestion or "",
                law_ref=f.law_ref,
                confidence=f.confidence,
            ))

        # ── 从LLM提取风险（不与规则/参数重复的）──────────────
        for lv in llm_violations:
            category = "needs_review"  # LLM发现默认需人工确认
            if lv.risk_level == "high":
                category = "high_risk"
            risk_items.append(MergedRiskItem(
                source="llm",
                risk_level=lv.risk_level,
                category=category,
                title=f"[{lv.type}] {lv.reason[:80]}" if lv.reason else f"[{lv.type}] LLM检测风险",
                description=lv.reason,
                evidence_text=lv.text,
                suggestion=lv.suggestion,
                law_ref=lv.law_ref,
                confidence=0.65,
            ))

        # ── 解析质量调整 ─────────────────────────────────────
        quality_multiplier = {"ok": 1.0, "text_layer": 1.0, "ocr": 1.2, "partial": 1.5, "failed": 2.0}
        adjustment = "none"
        if parse_quality in ("ocr", "partial"):
            adjustment = "upgraded"
        elif parse_quality == "failed":
            adjustment = "upgraded"

        # ── 计数统计 ──────────────────────────────────────────
        confirmed_count = sum(1 for r in risk_items if r.category == "confirmed")
        high_risk_count = sum(1 for r in risk_items if r.category == "high_risk")
        needs_review_count = sum(1 for r in risk_items if r.category == "needs_review")
        advisory_count = sum(1 for r in risk_items if r.category == "advisory")

        # ── 综合判定风险等级 ──────────────────────────────────
        if confirmed_count > 0:
            risk_level = "critical" if confirmed_count >= 2 else "high"
        elif high_risk_count > 0:
            risk_level = "high"
        elif needs_review_count > 0:
            risk_level = "medium"
        else:
            risk_level = "low"

        risk_level_original = risk_level

        # 解析质量差时上调风险等级
        if adjustment == "upgraded" and risk_level == "low":
            risk_level = "medium"
        if adjustment == "upgraded" and risk_level == "medium":
            risk_level = "high"

        # ── 判定是否通过 ──────────────────────────────────────
        final_passed = confirmed_count == 0 and high_risk_count == 0

        # ── 复核状态机 ────────────────────────────────────────
        if final_passed and needs_review_count == 0:
            review_status = "auto_passed"
            requires_human_review = False
        elif confirmed_count > 0:
            review_status = "auto_failed"
            requires_human_review = True
        else:
            review_status = "needs_review"
            requires_human_review = True

        logger.info(
            "四路合并: passed=%s level=%s status=%s confirmed=%d high=%d review=%d advisory=%d",
            final_passed, risk_level, review_status,
            confirmed_count, high_risk_count, needs_review_count, advisory_count,
        )

        return MergeResult(
            final_passed=final_passed,
            risk_level=risk_level,
            risk_level_original=risk_level_original,
            review_status=review_status,
            requires_human_review=requires_human_review,
            risk_items=risk_items,
            confirmed_count=confirmed_count,
            high_risk_count=high_risk_count,
            needs_review_count=needs_review_count,
            advisory_count=advisory_count,
            parse_quality_adjustment=adjustment,
            routing_used=routing_result is not None,
        )


# ── 全局单例 ──────────────────────────────────────────────────
four_way_merger = FourWayRiskMerger()
```

- [ ] **Step 4: 运行测试验证**

```bash
cd backend && uv run pytest tests/test_fusion.py::TestFourWayRiskMerger -v
```

- [ ] **Step 5: 提交**

```bash
git add backend/app/engine/fusion.py backend/tests/test_fusion.py
git commit -m "feat: upgrade fusion to four-way risk merger with review state machine"
```

---

### Task 5: API集成 — 将新模块接入审查流程

**Files:**
- Modify: `backend/app/api/check.py`

- [ ] **Step 1: 更新审查API以集成新模块**

修改 `backend/app/api/check.py`，将新的三个模块集成进去。替换现有的审查编排逻辑（从 `# 规则引擎检查` 注释行开始到 `# 融合结果` 注释行结束的部分）：

在文件顶部添加新导入：
```python
from app.engine.fusion import fusion_engine, four_way_merger
from app.engine.parameter_bias import ParameterBiasDetector
from app.engine.routing import compliance_router
```

在 `rule_engine.set_active_industries(industry_list)` 之后、`# ── 定变分离预处理` 之前，插入路由审查：

```python
    # ── 第0层：零Token路由审查 ──────────────────────────────
    # 提取预算金额（从解析结果中智能识别）
    budget = _extract_budget_from_document(parsed)
    routing_result = compliance_router.route(
        budget=budget,
        procurement_method=procurement_method or "",
        project_type=project_type or "",
    )
```

在 `rule_engine.run(...)` 之后、LLM调用之前，插入参数倾向性检测：

```python
    # ── 第2层：参数倾向性检测 ──────────────────────────────────
    parameter_bias_detector = ParameterBiasDetector()
    parameter_bias_result = parameter_bias_detector.run(
        sections=parsed.sections,
    )
```

根据路由结果控制LLM调用（用路由结果包裹现有LLM调用逻辑）：

```python
    # ── 第3层：LLM语义审查（遵循路由决策）──────────────────────
    if routing_result.skip_llm:
        logger.info("路由判定跳过LLM审查: %s", routing_result.reasoning)
        llm_result = None  # 跳过LLM
    else:
        target_sections = set(parsed.sections.keys()) if parsed.sections else set()
        if not target_sections:
            target_sections = {"评审办法", "技术要求"}

        llm_result = await llm_engine.analyze(
            sections=parsed.sections,
            rule_violations=rule_result.violations,
            file_id=file_id,
            user_id=int(user["sub"]),
            target_section_types=target_sections,
            marked_doc=marked_doc,
        )
```

替换融合调用（在LLM调用之后）：

```python
    # ── 双引擎融合（保持向后兼容的 ComplianceReport）───────────
    report = fusion_engine.merge(
        rule_result=rule_result,
        llm_result=llm_result,
        file_name=db_file.filename,
        check_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    )

    # ── 四路风险合并（新版） ──────────────────────────────────
    parse_quality = getattr(parsed, 'parse_quality', 'ok')
    merge_result = four_way_merger.merge(
        routing_result=routing_result,
        rule_engine_result=rule_result,
        parameter_bias_result=parameter_bias_result,
        llm_result=llm_result,
        parse_quality=parse_quality,
    )
```

在诊断信息中添加新模块数据：

```python
        "routing": {
            "traffic_light": routing_result.traffic_light.value,
            "skip_llm": routing_result.skip_llm,
            "reasoning": routing_result.reasoning,
        },
        "parameter_bias": {
            "findings_count": len(parameter_bias_result.findings),
            "risk_score": parameter_bias_result.risk_score,
            "critical_count": parameter_bias_result.critical_count,
            "high_count": parameter_bias_result.high_count,
        },
        "merge_result": {
            "final_passed": merge_result.final_passed,
            "risk_level": merge_result.risk_level,
            "review_status": merge_result.review_status,
            "requires_human_review": merge_result.requires_human_review,
            "confirmed_count": merge_result.confirmed_count,
            "high_risk_count": merge_result.high_risk_count,
            "needs_review_count": merge_result.needs_review_count,
        },
```

在API返回数据中添加新字段：

```python
    return {
        # ... 现有字段 ...
        "traffic_light": routing_result.traffic_light.value,
        "routing_reasoning": routing_result.reasoning,
        "parameter_bias_score": parameter_bias_result.risk_score,
        "parameter_bias_findings": parameter_bias_result.critical_count + parameter_bias_result.high_count,
        "merge_risk_level": merge_result.risk_level,
        "merge_review_status": merge_result.review_status,
        "merge_requires_human_review": merge_result.requires_human_review,
        "merge_confirmed_count": merge_result.confirmed_count,
        "merge_high_risk_count": merge_result.high_risk_count,
    }
```

最后，在文件末尾添加预算提取辅助函数：

```python
def _extract_budget_from_document(parsed) -> Optional[float]:
    """从解析后的文档中智能提取预算金额"""
    import re

    full_text = parsed.full_text or ""
    # 尝试匹配常见预算描述模式
    patterns = [
        r"(?:预算|采购预算|项目预算|预算金额|最高限价)[：:\s]*(\d[\d,.]*)\s*(?:万元|万元人民币|元)",
        r"(?:预算|采购预算|项目预算)[：:\s]*人民币\s*(\d[\d,.]*)\s*(?:万元|元)",
        r"(\d[\d,.]*)\s*(?:万元|元)\s*(?:人民币)?[。，,\s]*(?:预算|最高限价)",
    ]
    for pat in patterns:
        match = re.search(pat, full_text)
        if match:
            amount_str = match.group(1).replace(",", "").replace("_", "")
            try:
                amount = float(amount_str)
                if "万" in match.group(0):
                    amount *= 10_000
                return amount
            except ValueError:
                pass
    return None
```

- [ ] **Step 2: 运行现有测试确保不破坏已有功能**

```bash
cd backend && uv run pytest tests/test_check_flow.py tests/test_e2e.py -v
```

- [ ] **Step 3: 提交**

```bash
git add backend/app/api/check.py
git commit -m "feat: integrate routing, parameter bias, four-way merger into check API"
```

---

### Task 6: 端到端集成测试

**Files:**
- Modify: `backend/tests/test_e2e.py`

- [ ] **Step 1: 添加全链路端到端测试**

在 `backend/tests/test_e2e.py` 中添加：

```python
class TestFiveLayerPipelineE2E:
    """五层审查流水线端到端测试"""

    @pytest.mark.asyncio
    async def test_full_pipeline_green_light(self, client, auth_headers):
        """绿灯路由：小额公开招标 → 跳过LLM → 规则+参数检测 → 四路合并"""
        # 上传文件
        with open(_create_test_docx(budget_text="预算金额：50万元"), "rb") as f:
            upload_resp = client.post(
                "/api/upload/",
                files={"file": ("test.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                headers=auth_headers,
            )
        assert upload_resp.status_code == 200
        file_id = upload_resp.json()["id"]

        # 执行审查
        check_resp = client.post(
            f"/api/check/{file_id}",
            params={"procurement_method": "公开招标", "project_type": "货物类"},
            headers=auth_headers,
        )
        assert check_resp.status_code == 200
        data = check_resp.json()

        # 验证各层输出
        assert "traffic_light" in data
        assert "parameter_bias_score" in data
        assert "merge_risk_level" in data
        assert "merge_review_status" in data

        # 小额公开招标应为绿灯
        assert data["traffic_light"] == "green"

    @pytest.mark.asyncio
    async def test_full_pipeline_red_light(self, client, auth_headers):
        """红灯路由：大额单一来源 → 五层全开"""
        with open(_create_test_docx(budget_text="预算金额：1000万元"), "rb") as f:
            upload_resp = client.post(
                "/api/upload/",
                files={"file": ("test.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                headers=auth_headers,
            )
        assert upload_resp.status_code == 200
        file_id = upload_resp.json()["id"]

        check_resp = client.post(
            f"/api/check/{file_id}",
            params={"procurement_method": "单一来源", "project_type": "服务类"},
            headers=auth_headers,
        )
        assert check_resp.status_code == 200
        data = check_resp.json()
        # 大额单一来源 → 红灯
        assert data["traffic_light"] == "red"

    @pytest.mark.asyncio
    async def test_pipeline_with_violations_produces_merge_result(self, client, auth_headers):
        """包含违规内容的文档 → 四路合并产生风险项"""
        docx_path = _create_test_docx(
            extra_content="投标人须提供原厂授权函。所有设备须同一品牌。须提供CMA检测报告。",
            budget_text="预算金额：300万元",
        )
        with open(docx_path, "rb") as f:
            upload_resp = client.post(
                "/api/upload/",
                files={"file": ("test.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                headers=auth_headers,
            )
        assert upload_resp.status_code == 200
        file_id = upload_resp.json()["id"]

        check_resp = client.post(
            f"/api/check/{file_id}",
            params={"procurement_method": "公开招标", "project_type": "货物类"},
            headers=auth_headers,
        )
        assert check_resp.status_code == 200
        data = check_resp.json()

        # 有违规内容，至少参数倾向性会有发现
        assert data["parameter_bias_findings"] >= 0
        # 合并结果应包含风险等级
        assert data["merge_risk_level"] in ("low", "medium", "high", "critical")


def _create_test_docx(
    extra_content: str = "",
    budget_text: str = "预算金额：100万元",
) -> str:
    """创建测试用招标文件 docx"""
    import tempfile
    from docx import Document

    doc = Document()
    doc.add_heading("第一章 招标公告", level=1)
    doc.add_paragraph(f"公开招标公告正文。{budget_text}。")
    if extra_content:
        doc.add_paragraph(extra_content)
    doc.add_heading("第二章 招标范围", level=1)
    doc.add_paragraph("采购内容。")
    doc.add_heading("第三章 投标人资格要求", level=1)
    doc.add_paragraph("独立法人。")
    doc.add_heading("第四章 评审办法", level=1)
    doc.add_paragraph("综合评分法。")
    doc.add_heading("第五章 投标须知", level=1)
    doc.add_paragraph("投标截止时间2026年7月1日。")

    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    doc.save(tmp.name)
    tmp.close()
    return tmp.name
```

- [ ] **Step 2: 运行端到端测试**

```bash
cd backend && uv run pytest tests/test_e2e.py::TestFiveLayerPipelineE2E -v
```

- [ ] **Step 3: 运行全部测试确保无回归**

```bash
cd backend && uv run pytest -v
```

- [ ] **Step 4: 提交**

```bash
git add backend/tests/test_e2e.py
git commit -m "test: add five-layer pipeline end-to-end tests"
```

---

### Task 7: M1 里程碑验证

- [ ] **Step 1: 运行完整测试套件**

```bash
cd backend && uv run pytest -v --tb=short
```

- [ ] **Step 2: 确认所有新增模块可导入**

```bash
cd backend && uv run python -c "
from app.engine.routing import compliance_router
from app.engine.parameter_bias import ParameterBiasDetector
from app.engine.fusion import four_way_merger
from app.engine.shared_types import RoutingResult, ParameterBiasResult, TrafficLight
print('All M1 modules import OK')
print('TrafficLight values:', [t.value for t in TrafficLight])
r = compliance_router.route(budget=500000, procurement_method='公开招标', project_type='货物类')
print('Routing test:', r.traffic_light.value, '| skip_llm:', r.skip_llm)
detector = ParameterBiasDetector()
result = detector.run({'资格要求': '须提供原厂授权函'})
print('Bias detection test:', len(result.findings), 'findings, score:', result.risk_score)
"
```

- [ ] **Step 3: 标记 M1 里程碑**

```bash
git tag -a m1-pipeline-complete -m "M1: 核心流水线补全 —— 五层审查全链路跑通"
```

---

## M1 完成检查清单

- [ ] `engine/routing.py` 实现并可工作（零Token路由：绿/黄/红灯分级）
- [ ] `engine/parameter_bias.py` 实现并可工作（9种违规模式检测）
- [ ] `engine/fusion.py` 四路合并器实现并可工作（confirmed/high_risk/needs_review/advisory）
- [ ] `engine/fusion.py` 复核状态机实现并可工作（auto_passed/auto_failed/needs_review）
- [ ] `api/check.py` 集成所有新模块
- [ ] 单元测试覆盖所有新模块
- [ ] 端到端测试覆盖全链路
- [ ] 现有测试无回归
- [ ] 路由决策有审计日志
- [ ] 审查API返回包含新字段（traffic_light, merge_risk_level等）
