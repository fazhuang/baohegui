"""合规检查 API"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db
from app.engine.fusion import fusion_engine, four_way_merger
from app.engine.parameter_bias import ParameterBiasDetector
from app.engine.routing import compliance_router
from app.engine.llm_engine import llm_engine
from app.engine.rule_engine import rule_engine
from app.engine.variable_marker import variable_marker
from app.models.document import ComplianceReport, UploadedFile
from app.services.parser import parser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/check", tags=["check"])


@router.post("/{file_id}")
async def run_compliance_check(
    file_id: int,
    industries: str | None = Query(
        default=None,
        description="行业标识，逗号分隔，如 it,healthcare",
    ),
    sector: str | None = Query(
        default=None,
        description="招标行业：政府采购/公路工程/水利工程/铁路工程",
    ),
    procurement_method: str | None = Query(
        default=None,
        description="采购方式：公开招标/邀请招标/竞争性谈判/竞争性磋商/询价/单一来源",
    ),
    project_type: str | None = Query(default=None, description="项目类型：货物类/服务类/工程类"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """对指定文件执行合规检查（支持行业规则激活 + 定变分离优化）"""
    db_file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if not db_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    # 解析文件（通过 MinIO 或本地路径）
    from app.services.minio_service import minio_service

    try:
        with minio_service.local_path(db_file.storage_path) as local_path:
            parsed = parser.parse(local_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件解析失败: {str(e)}",
        )

    # 更新状态
    db_file.status = "checking"
    db.commit()

    # 如果指定了行业，激活对应的行业规则
    industry_list: list[str] = []
    if industries:
        industry_list = [ind.strip() for ind in industries.split(",") if ind.strip()]
        rule_engine.set_active_industries(industry_list)

    # ── 性能计时 ──────────────────────────────────────────────
    t_check_start = time.monotonic()

    # ── 第0层：零Token路由审查 ──────────────────────────────
    t0 = time.monotonic()
    budget = _extract_budget_from_document(parsed)
    routing_result = compliance_router.route(
        budget=budget,
        procurement_method=procurement_method or "",
        project_type=project_type or "",
    )
    t_routing = time.monotonic() - t0

    # ── 定变分离预处理 ──────────────────────────────────────
    t0 = time.monotonic()
    # 对文档内容进行模板固定内容 vs 代理机构填写内容的标记
    marked_doc = None
    try:
        marked_doc = variable_marker.mark(
            parsed_doc=parsed,
            sector=sector or "",
            procurement_method=procurement_method or "",
            project_type=project_type or "",
        )
    except Exception as e:
        # 定变分离失败不影响审查主流程（回退到无过滤模式）
        logger.warning("定变分离标记失败，将跳过模板过滤: %s", e)
    t_marker = time.monotonic() - t0

    # ── 第1层：规则引擎检查（传入 marked_doc → 智能跳过 FIXED 区域）──
    t0 = time.monotonic()
    rule_result = rule_engine.run(
        sections=parsed.sections,
        full_text=parsed.full_text,
        marked_doc=marked_doc,
    )
    t_rules = time.monotonic() - t0

    # ── 第2层：参数倾向性检测 ──────────────────────────────────
    t0 = time.monotonic()
    parameter_bias_detector = ParameterBiasDetector()
    parameter_bias_result = parameter_bias_detector.run(
        sections=parsed.sections,
    )
    t_param_bias = time.monotonic() - t0

    # ── 第3层：LLM语义审查（遵循路由决策）──────────────────────
    t0 = time.monotonic()
    target_sections = set(parsed.sections.keys()) if parsed.sections else set()
    if not target_sections:
        target_sections = {"评审办法", "技术要求"}

    if routing_result.skip_llm:
        logger.info("路由判定跳过LLM审查: %s", routing_result.reasoning)
        llm_result = None
    else:
        llm_result = await llm_engine.analyze(
            sections=parsed.sections,
            rule_violations=rule_result.violations,
            file_id=file_id,
            user_id=int(user["sub"]),
            target_section_types=target_sections,
            marked_doc=marked_doc,
        )
    t_llm = time.monotonic() - t0

    # ── 汇总层：融合结果 ─────────────────────────────────────
    t0 = time.monotonic()
    # ── 汇总层：融合结果 ─────────────────────────────────────
    t0 = time.monotonic()
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
    t_fusion = time.monotonic() - t0

    # ── 总耗时 ──────────────────────────────────────────────
    t_total = time.monotonic() - t_check_start

    # 保存报告
    import json

    template_stats = marked_doc.stats if marked_doc else {}

    # ── 审查诊断信息 ──────────────────────────────────────────
    # 记录解析和审查质量指标，帮助定位内容识别问题
    diagnostics = {
        "parser": {
            "sections_found": len(parsed.sections),
            "section_names": list(parsed.sections.keys()),
            "section_content_lengths": {k: len(v) for k, v in parsed.sections.items()},
            "full_text_length": len(parsed.full_text),
            "page_count": parsed.page_count,
            "headings_count": len(parsed.headings),
        },
        "variable_marker": template_stats,
        "rule_engine": {
            "rules_loaded": len(rule_engine.rules),
            "section_violations": len(rule_result.violations),
            "by_type": {
                "chapter_required": sum(
                    1 for v in rule_result.violations if v.rule_type == "chapter_required"
                ),
                "keyword_required": sum(
                    1 for v in rule_result.violations if v.rule_type == "keyword_required"
                ),
                "forbidden": sum(1 for v in rule_result.violations if v.rule_type == "forbidden"),
                "format_required": sum(
                    1 for v in rule_result.violations if v.rule_type == "format_required"
                ),
            },
        },
        "llm_engine": {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "mock_mode": settings.llm_mock_mode,
            "target_section_types": list(target_sections),
            "sections_analyzed": llm_result.sections_analyzed if llm_result else 0,
            "sections_skipped": llm_result.sections_skipped if llm_result else 0,
            "tokens_used": llm_result.tokens_used if llm_result else 0,
            "cost_yuan": llm_result.cost_yuan if llm_result else 0.0,
            "error": llm_result.error if llm_result else "skipped_by_routing",
        },
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
        "timing": {
            "total_seconds": round(t_total, 3),
            "routing_ms": round(t_routing * 1000, 1),
            "marker_ms": round(t_marker * 1000, 1),
            "rules_ms": round(t_rules * 1000, 1),
            "param_bias_ms": round(t_param_bias * 1000, 1),
            "llm_ms": round(t_llm * 1000, 1),
            "fusion_ms": round(t_fusion * 1000, 1),
        },
    }

    db_report = ComplianceReport(
        file_id=file_id,
        total_score=report.total_score,
        section_score=report.section_score,
        keyword_score=report.keyword_score,
        forbidden_score=report.forbidden_score,
        semantic_score=report.semantic_score,
        violation_count=report.total_violations,
        report_data=json.dumps(
            {
                **report.model_dump(),
                "_diagnostics": diagnostics,
            },
            ensure_ascii=False,
        ),
        checked_by=int(user["sub"]),
    )
    db.add(db_report)

    db_file.status = "completed"
    db.commit()
    db.refresh(db_report)

    # ── 检查成功后才消耗配额（先执行检查 → 成功后消耗）────
    # 避免用户因系统故障损失配额
    from app.services.quota_service import consume_file, consume_tokens

    consume_file(db, int(user["sub"]))
    if llm_result and llm_result.tokens_used:
        consume_tokens(db, int(user["sub"]), llm_result.tokens_used, llm_result.cost_yuan)

    return {
        "report_id": db_report.id,
        "total_score": report.total_score,
        "total_violations": report.total_violations,
        "high_risk_count": report.high_risk_count,
        "medium_risk_count": report.medium_risk_count,
        "low_risk_count": report.low_risk_count,
        "section_score": report.section_score,
        "keyword_score": report.keyword_score,
        "forbidden_score": report.forbidden_score,
        "semantic_score": report.semantic_score,
        "llm_model_used": report.llm_model_used,
        "llm_tokens_used": report.llm_tokens_used,
        "llm_cost_yuan": report.llm_cost_yuan,
        "llm_error": report.llm_error,
        "industries": industry_list or None,
        "template_stats": template_stats,
        "traffic_light": routing_result.traffic_light.value,
        "routing_reasoning": routing_result.reasoning,
        "parameter_bias_score": parameter_bias_result.risk_score,
        "parameter_bias_findings": parameter_bias_result.critical_count + parameter_bias_result.high_count,
        "merge_risk_level": merge_result.risk_level,
        "merge_review_status": merge_result.review_status,
        "merge_requires_human_review": merge_result.requires_human_review,
        "merge_confirmed_count": merge_result.confirmed_count,
        "merge_high_risk_count": merge_result.high_risk_count,
        "timing": {
            "total_seconds": round(t_total, 3),
            "routing_ms": round(t_routing * 1000, 1),
            "marker_ms": round(t_marker * 1000, 1),
            "rules_ms": round(t_rules * 1000, 1),
            "param_bias_ms": round(t_param_bias * 1000, 1),
            "llm_ms": round(t_llm * 1000, 1),
            "fusion_ms": round(t_fusion * 1000, 1),
        },
    }


def _extract_budget_from_document(parsed) -> Optional[float]:
    """从解析后的文档中智能提取预算金额"""
    import re

    full_text = parsed.full_text or ""
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
