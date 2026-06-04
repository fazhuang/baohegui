"""合规检查 API"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.config import settings
from app.db.database import get_db
from app.engine.fusion import fusion_engine
from app.engine.llm_engine import llm_engine
from app.engine.rule_engine import rule_engine
from app.engine.variable_marker import variable_marker
from app.models.document import ComplianceReport, UploadedFile
from app.services.parser import parser

router = APIRouter(prefix="/api/check", tags=["check"])


@router.post("/{file_id}")
async def run_compliance_check(
    file_id: int,
    industries: str | None = Query(default=None, description="行业标识，逗号分隔，如 it,healthcare"),
    sector: str | None = Query(default=None, description="招标行业：政府采购/公路工程/水利工程/铁路工程"),
    procurement_method: str | None = Query(default=None, description="采购方式：公开招标/邀请招标/竞争性谈判/竞争性磋商/询价/单一来源"),
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

    # ── 定变分离预处理 ──────────────────────────────────────
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

    # 规则引擎检查（传入 marked_doc → 智能跳过 FIXED 区域）
    rule_result = rule_engine.run(
        sections=parsed.sections,
        full_text=parsed.full_text,
        marked_doc=marked_doc,
    )

    # LLM 语义检查（传入 marked_doc → <<TEMPLATE>>/<<REVIEW>> 标记文本）
    # 对所有解析出的章节进行语义审查，而非仅限「评审办法」「技术要求」
    # 定变分离模式下，LLM 会自行判断 <<TEMPLATE>> 区域无需审查
    target_sections = set(parsed.sections.keys()) if parsed.sections else set()
    if not target_sections:
        # 降级：如果解析器没有识别出任何章节，至少检查这两个核心章节
        target_sections = {"评审办法", "技术要求"}

    llm_result = await llm_engine.analyze(
        sections=parsed.sections,
        rule_violations=rule_result.violations,
        file_id=file_id,
        user_id=int(user["sub"]),
        target_section_types=target_sections,
        marked_doc=marked_doc,
    )

    # 融合结果
    report = fusion_engine.merge(
        rule_result=rule_result,
        llm_result=llm_result,
        file_name=db_file.filename,
        check_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    )

    # 保存报告
    import json
    template_stats = marked_doc.stats if marked_doc else {}

    # ── 审查诊断信息 ──────────────────────────────────────────
    # 记录解析和审查质量指标，帮助定位内容识别问题
    diagnostics = {
        "parser": {
            "sections_found": len(parsed.sections),
            "section_names": list(parsed.sections.keys()),
            "section_content_lengths": {
                k: len(v) for k, v in parsed.sections.items()
            },
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
                    1 for v in rule_result.violations
                    if v.rule_type == "chapter_required"
                ),
                "keyword_required": sum(
                    1 for v in rule_result.violations
                    if v.rule_type == "keyword_required"
                ),
                "forbidden": sum(
                    1 for v in rule_result.violations
                    if v.rule_type == "forbidden"
                ),
                "format_required": sum(
                    1 for v in rule_result.violations
                    if v.rule_type == "format_required"
                ),
            },
        },
        "llm_engine": {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "mock_mode": settings.llm_mock_mode,
            "target_section_types": list(target_sections),
            "sections_analyzed": llm_result.sections_analyzed,
            "sections_skipped": llm_result.sections_skipped,
            "tokens_used": llm_result.tokens_used,
            "cost_yuan": llm_result.cost_yuan,
            "error": llm_result.error,
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
        report_data=json.dumps({
            **report.model_dump(),
            "_diagnostics": diagnostics,
        }, ensure_ascii=False),
        checked_by=int(user["sub"]),
    )
    db.add(db_report)

    db_file.status = "completed"
    db.commit()
    db.refresh(db_report)

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
    }
