"""LLM 结构化抽取服务

Phase 2 — 从投诉案例中通过 LLM 抽取结构化信息：
- 争议焦点
- 监管认定
- 处理结果
- 法规依据
- 合规启示
- 风险标签

安全约束：
- 必须保存模型、Prompt 版本、置信度、证据片段
- LLM 结果只能成为候选，不能自动发布
- 抽取失败的案例进入 parse_failed 状态
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.engine.case_state_machine import CaseStatus, CaseStatusStateMachine
from app.engine.llm_engine import llm_engine
from app.models.complaint_case import ComplaintCase

logger = logging.getLogger(__name__)

# Prompt 版本（每次修改 Prompt 需要递增）
EXTRACTOR_VERSION = "2.0.0"
PROMPT_VERSION = "2.0.0"

# 抽取 Prompt 模板
EXTRACTION_PROMPT = """你是一名政府采购合规专家。请从以下投诉处理结果公告中提取结构化信息。

## 原始公告内容
{content}

## 要求
请提取以下信息并以 JSON 格式返回：

1. dispute_focus: 争议焦点（投诉人提出的主要争议事项，1-3 条）
2. regulatory_finding: 监管认定（监管部门对投诉事项的认定结论及理由）
3. decision_result: 处理结果（维持/驳回/部分成立/撤销，以及具体处理意见）
4. legal_basis: 法规依据（引用的法律法规及具体条文，如《政府采购法》第X条）
5. compliance_insights: 合规启示（从本案例中可以吸取的经验教训，1-3 条）
6. risk_tags: 风险标签（从以下类别中选择，可多选）：
   - brand_lock: 品牌锁定/指定
   - param_exclusion: 参数排他性
   - auth_restriction: 厂家授权限制
   - qualification_excess: 资质超标
   - score_subjective: 评审主观性
   - bid_rigging: 串通投标
   - false_documents: 虚假材料
   - procedure_violation: 程序违规
   - sme_discrimination: 中小企业歧视
   - mixed_package: 标包划分不合理
   - low_price: 异常低价
   - other: 其他
7. confidence: 整体置信度（0.0-1.0，评估信息提取的可靠程度）
8. evidence_snippets: 证据片段（从原文摘录的关键句子，每条不超过200字）

## 重要约束
- 如果信息不足，请标注为 "未知" 或使用空数组 []
- 所有结论必须有原文依据
- 不要编造不存在的法规条文
- 只返回 JSON，不要有任何其他文字

返回格式：
```json
{
  "dispute_focus": ["争议焦点1", "争议焦点2"],
  "regulatory_finding": "监管认定结论",
  "decision_result": "处理结果",
  "legal_basis": ["法规1 第X条", "法规2 第Y条"],
  "compliance_insights": ["启示1", "启示2"],
  "risk_tags": ["brand_lock", "param_exclusion"],
  "confidence": 0.85,
  "evidence_snippets": ["证据片段1", "证据片段2"]
}
```
"""


class CaseExtractionService:
    """案例 LLM 结构化抽取服务"""

    @staticmethod
    def build_extraction_prompt(case: ComplaintCase) -> str:
        """构建抽取 prompt"""
        content_parts = []

        if case.title:
            content_parts.append(f"## 公告标题\n{case.title}")

        if case.project_name:
            content_parts.append(f"## 采购项目\n{case.project_name}")

        if case.project_number:
            content_parts.append(f"## 项目编号\n{case.project_number}")

        if case.complainant:
            content_parts.append(f"## 投诉人\n{case.complainant}")

        if case.respondent:
            content_parts.append(f"## 被投诉人\n{case.respondent}")

        if case.raw_content:
            content_parts.append(f"## 公告全文\n{case.raw_content[:8000]}")
        elif case.summary:
            content_parts.append(f"## 摘要\n{case.summary}")

        if not content_parts:
            return ""

        content = "\n\n".join(content_parts)
        return EXTRACTION_PROMPT.format(content=content)

    @staticmethod
    def extract(case: ComplaintCase, db: Session) -> dict:
        """对案例执行 LLM 结构化抽取

        返回：
        {
            "success": bool,
            "case_id": int,
            "data": dict | None,       # 抽取结果
            "model": str,              # 使用的模型
            "prompt_version": str,     # Prompt 版本
            "confidence": float,       # 抽取置信度
            "evidence_snippets": list,  # 证据片段
            "tokens_used": int,
            "error": str | None,
        }
        """
        result = {
            "success": False,
            "case_id": case.id,
            "data": None,
            "model": "",
            "prompt_version": PROMPT_VERSION,
            "confidence": 0.0,
            "evidence_snippets": [],
            "tokens_used": 0,
            "error": None,
        }

        prompt = CaseExtractionService.build_extraction_prompt(case)
        if not prompt:
            result["error"] = "无法构建 prompt：案例缺少内容"
            return result

        try:
            # 调用 LLM
            from app.services.prompt_manager import prompt_manager
            from app.engine.llm_engine import LLMEngine

            llm_response = llm_engine.call_llm(
                system_prompt="你是一名政府采购合规分析专家，擅长从投诉处理公告中提取结构化信息。只返回 JSON。",
                user_prompt=prompt,
                temperature=0.1,  # 低温度确保一致性
                max_tokens=2000,
            )

            if not llm_response:
                result["error"] = "LLM 返回空结果"
                return result

            result["tokens_used"] = llm_response.get("tokens_used", 0)
            result["model"] = llm_response.get("model", "")

            # 提取 JSON
            raw_text = llm_response.get("content", "") or llm_response.get("text", "")
            extracted = CaseExtractionService._extract_json(raw_text)

            if extracted:
                result["success"] = True
                result["data"] = extracted
                result["confidence"] = extracted.get("confidence", 0.0)
                result["evidence_snippets"] = extracted.get("evidence_snippets", [])

                # 保存抽取结果到 case
                _save_extraction(case, extracted, result, db)
            else:
                result["error"] = "无法从 LLM 响应中提取 JSON"

        except Exception as e:
            logger.error(f"案例 {case.id} 抽取失败: {e}")
            result["error"] = str(e)

        return result

    @staticmethod
    def extract_batch(
        db: Session,
        case_ids: Optional[list[int]] = None,
        limit: int = 10,
    ) -> dict:
        """批量抽取

        只处理 fetched/normalized/parse_failed 状态的案例。
        """
        sm = CaseStatusStateMachine()

        q = db.query(ComplaintCase).filter(
            ComplaintCase.review_status.in_([
                CaseStatus.FETCHED.value,
                CaseStatus.NORMALIZED.value,
                CaseStatus.PARSE_FAILED.value,
            ])
        )
        if case_ids:
            q = q.filter(ComplaintCase.id.in_(case_ids))

        cases = q.limit(limit).all()

        success_count = 0
        fail_count = 0
        skip_count = 0
        details = []

        for case in cases:
            # 先规范化
            if case.review_status == CaseStatus.FETCHED.value:
                ok, msg = sm.transition(case, CaseStatus.NORMALIZED.value)
                if not ok:
                    skip_count += 1
                    details.append({"case_id": case.id, "status": "skipped", "reason": msg})
                    continue

            result = CaseExtractionService.extract(case, db)
            details.append(result)

            if result["success"]:
                sm.transition(case, CaseStatus.EXTRACTED.value)
                # 自动进入待审核（不自动发布）
                sm.transition(case, CaseStatus.PENDING_REVIEW.value)
                success_count += 1
            else:
                sm.transition(case, CaseStatus.PARSE_FAILED.value)
                fail_count += 1

        db.commit()

        return {
            "total": len(cases),
            "success": success_count,
            "failed": fail_count,
            "skipped": skip_count,
            "extractor_version": EXTRACTOR_VERSION,
            "details": details,
        }

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """从 LLM 响应中提取 JSON 对象"""
        if not text:
            return None

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 块
        json_block = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_block:
            try:
                return json.loads(json_block.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试提取 ``` ... ``` 块
        code_block = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试提取 { ... } 对象
        brace_match = re.search(r'\{.*\}', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(f"无法从 LLM 响应提取 JSON: {text[:200]}...")
        return None


# ── 内部辅助 ────────────────────────────────────────

def _save_extraction(
    case: ComplaintCase,
    extracted: dict,
    llm_result: dict,
    db: Session,
) -> None:
    """保存抽取结果到案例记录"""
    # 更新 legal_basis（如果 LLM 提取到了）
    if extracted.get("legal_basis"):
        case.set_legal_basis(extracted["legal_basis"])

    # 更新 complaint_types（从 risk_tags 派生）
    if extracted.get("risk_tags"):
        existing = case.get_complaint_types()
        new_tags = list(set(existing + extracted["risk_tags"]))
        case.set_complaint_types(new_tags)

    # 保存完整抽取元数据
    extraction_meta = {
        "extractor_version": EXTRACTOR_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model": llm_result.get("model", ""),
        "tokens_used": llm_result.get("tokens_used", 0),
        "confidence": extracted.get("confidence", 0.0),
        "dispute_focus": extracted.get("dispute_focus", []),
        "regulatory_finding": extracted.get("regulatory_finding", ""),
        "decision_result": extracted.get("decision_result", ""),
        "compliance_insights": extracted.get("compliance_insights", []),
        "risk_tags": extracted.get("risk_tags", []),
        "evidence_snippets": extracted.get("evidence_snippets", []),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    case.set_extraction_metadata(extraction_meta)

    # 设置版本
    case.extractor_version = EXTRACTOR_VERSION

    # 更新 content_hash
    if not case.content_hash:
        case.set_content_hash()

    logger.info(f"案例 {case.id} 抽取完成: confidence={extracted.get('confidence', 0)}")


# 模块级单例
case_extraction = CaseExtractionService()
