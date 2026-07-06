"""报告查询与导出 API"""

import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.permissions import Permission, PermissionService
from app.core.security import get_current_user, get_current_user_id, assert_resource_access, require_admin
from app.db.database import get_db
from app.models.document import ComplianceReport as ReportModel, UploadedFile
from app.services.excel_exporter import build_violation_rows, export_report_to_excel
from app.services.clause_generator import clause_generator
from app.services.feedback_service import feedback_service
from app.services.report_gen import report_generator

router = APIRouter(prefix="/api/report", tags=["report"])


_INTEGRITY_FAILED_409 = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail={"integrity_status": "integrity_failed",
            "message": "决策完整性校验失败，本报告结论可能已被篡改。请重新执行合规审查。"},
)

_LEGACY_UNVERIFIABLE_409 = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail={
        "integrity_status": "legacy_unverifiable",
        "message": "历史报告缺少可验证决策链，请重新执行审查后导出",
    },
)


def _load_report_violation_rows(db: Session, report_id: int, report_data: dict) -> list[dict]:
    """优先读取独立违规表，缺失时回退到 report_data 内的明细。"""
    try:
        from app.models.report_detail import ReportViolation as ReportViolationModel
    except ImportError:
        return build_violation_rows(report_data)

    rows = db.query(ReportViolationModel).filter(ReportViolationModel.report_id == report_id).all()
    if not rows:
        return build_violation_rows(report_data)

    violations: list[dict] = []
    for item in rows:
        violations.append(
            {
                "source": getattr(item, "source", ""),
                "rule_id": getattr(item, "rule_id", ""),
                "rule_type": getattr(item, "rule_type", ""),
                "risk_level": getattr(item, "risk_level", ""),
                "category": getattr(item, "category", ""),
                "title": getattr(item, "title", ""),
                "description": getattr(item, "description", ""),
                "evidence_text": getattr(item, "evidence_text", ""),
                "suggestion": getattr(item, "suggestion", ""),
                "law_ref": getattr(item, "law_ref", ""),
                "confidence": getattr(item, "confidence", ""),
            }
        )
    return violations


def _try_verify_report(db_report) -> dict | None:
    """尝试对 schema v2+ 报告执行版本化完整性校验。

    返回 None 表示校验通过（verified）；
    返回 dict 表示 non-verified 状态：
      - status = "legacy_unverifiable" → 历史报告，无法校验
      - status = "integrity_failed" → v2 报告但校验失败
    """
    from app.core.policy_kernel import (
        PolicySchemaVersion,
        PolicyDecision,
        parse_decision_input_for_version,
        verify_trace_for_version,
        _V2_KNOWN,
    )

    db_sv = db_report.policy_schema_version or ""
    integrity_status = db_report.decision_integrity_status or "legacy_unverifiable"
    result = {
        "status": integrity_status,
        "decision_action": db_report.decision_action,
        "decision_risk_level": db_report.decision_risk_level,
        "decision_hash": db_report.decision_hash,
        "policy_schema_version": db_report.policy_schema_version,
    }

    # None / 空字符串 → true legacy（从未写 schema version）
    if not db_sv:
        result["status"] = "legacy_unverifiable"
        result["warning"] = (
            "本报告为历史版本，缺少可验证决策链。"
            "合规结论仅供参考，建议重新执行审查。"
        )
        result["final_action"] = "unknown"
        result["final_risk_level"] = "unknown"
        return result

    # 非已知 v2.x 版本 → integrity_failed（不得伪装成 legacy_unverifiable）
    if db_sv not in _V2_KNOWN:
        result["status"] = "integrity_failed"
        result["warning"] = (
            f"未知 schema 版本 {db_sv!r}，决策完整性不可验证。"
            "请重新执行合规审查。"
        )
        result["final_action"] = "unknown"
        result["final_risk_level"] = "unknown"
        return result

    report_data = json.loads(db_report.report_data) if db_report.report_data else {}
    di_raw = report_data.get("_decision_input")
    pd_raw = report_data.get("_policy_decision")

    if not di_raw or not pd_raw:
        result["status"] = "integrity_failed"
        result["warning"] = "缺少 DecisionInput 或 PolicyDecision 回放材料。"
        return result

    # ── 三端版本一致性 ──
    di_sv = di_raw.get("schema_version", "")
    pd_sv = pd_raw.get("schema_version", "")
    if db_sv != di_sv or di_sv != pd_sv:
        result["status"] = "integrity_failed"
        result["warning"] = (
            f"Schema version mismatch: db={db_sv!r}, "
            f"input={di_sv!r}, decision={pd_sv!r}"
        )
        return result

    # ── 版本化解析 ──
    try:
        di = parse_decision_input_for_version(di_raw)
        pd = PolicyDecision.model_validate(pd_raw)
    except Exception as e:
        result["status"] = "integrity_failed"
        result["warning"] = f"Pydantic 反序列化失败: {e}"
        return result

    # 数据库列一致性检查
    if db_report.decision_hash and db_report.decision_hash != pd.decision_hash:
        result["status"] = "integrity_failed"
        result["warning"] = "数据库 decision_hash 与 PolicyDecision 不一致。"
        return result
    if db_report.decision_action and db_report.decision_action != pd.final_action.value:
        result["status"] = "integrity_failed"
        result["warning"] = "数据库 decision_action 与 PolicyDecision 不一致。"
        return result
    if db_report.decision_risk_level and db_report.decision_risk_level != pd.final_risk_level.value:
        result["status"] = "integrity_failed"
        result["warning"] = "数据库 decision_risk_level 与 PolicyDecision 不一致。"
        return result

    vr = verify_trace_for_version(di_raw, pd_raw)
    result["verify_result"] = vr
    if not vr["valid"]:
        result["status"] = "integrity_failed"
        result["warning"] = (
            "决策完整性校验失败，本报告结论可能已被篡改。请重新执行合规审查。"
        )
        return result

    # verified
    result["status"] = "verified"
    return None  # 校验通过


def require_exportable_verified_report(db_report) -> None:
    """统一门禁：PDF/Excel 共用。

    - legacy_unverifiable → 409，禁止导出
    - integrity_failed → 409，禁止导出
    - verified → 通过（不抛异常）
    """
    integrity = _try_verify_report(db_report)
    if integrity is None:
        return  # verified
    if integrity["status"] == "integrity_failed":
        raise _INTEGRITY_FAILED_409
    if integrity["status"] == "legacy_unverifiable":
        raise _LEGACY_UNVERIFIABLE_409
    # defensive: any other non-verified status
    raise _INTEGRITY_FAILED_409


# ── 白名单：legacy_unverifiable report detail 可返回的字段 ──
_LEGACY_WHITELIST_KEYS = frozenset({
    "report_id", "file_id", "file_name",
    "check_time", "created_at",
    "integrity_status", "final_action", "final_risk_level",
})


def _build_legacy_detail(db_report) -> dict:
    """为 legacy_unverifiable 报告构造白名单-only 响应。"""
    integrity_info = {
        "status": "legacy_unverifiable",
        "final_action": "unknown",
        "final_risk_level": "unknown",
        "warning": (
            "本报告为历史版本，缺少可验证决策链。请重新执行审查以获取正式合规结论。"
        ),
    }
    return {
        "report_id": db_report.id,
        "file_id": db_report.file_id,
        "file_name": db_report.report_data and json.loads(db_report.report_data).get("file_name", ""),
        "check_time": None,
        "created_at": db_report.created_at.isoformat() if db_report.created_at else None,
        "_integrity": integrity_info,
        "integrity_status": "legacy_unverifiable",
        "final_action": "unknown",
        "final_risk_level": "unknown",
    }


@router.get("/{report_id}")
async def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """获取合规报告详情（含规则溯源 + 决策完整性校验）"""
    db_report = db.query(ReportModel).filter(ReportModel.id == report_id).first()
    if not db_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    assert_resource_access(db, db_report, user, owner_attr="checked_by")

    integrity = _try_verify_report(db_report)
    if integrity is not None:
        if integrity["status"] == "integrity_failed":
            raise _INTEGRITY_FAILED_409
        # legacy_unverifiable: return whitelist-only metadata, not full report
        return _build_legacy_detail(db_report)

    # verified: full report
    report_dict = json.loads(db_report.report_data)
    report_dict["_integrity"] = {
        "status": "verified",
        "decision_action": db_report.decision_action,
        "decision_risk_level": db_report.decision_risk_level,
        "decision_hash": db_report.decision_hash,
        "policy_schema_version": db_report.policy_schema_version,
    }

    # v3: 注入规则溯源元数据
    from app.engine.rule_engine import rule_engine
    rule_provenance: dict[str, dict] = {}
    for rule in rule_engine.rules:
        rule_provenance[rule.id] = {
            "source_file": rule.source_file,
            "source_version": rule.source_version,
            "source_url": rule.source_url,
            "provenance": rule.provenance,
            "last_updated": rule.last_updated,
        }
    report_dict["_rule_provenance"] = rule_provenance

    return report_dict


@router.get("/{report_id}/pdf")
async def download_report_pdf(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """下载合规报告（PDF）"""
    db_report = db.query(ReportModel).filter(ReportModel.id == report_id).first()
    if not db_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    assert_resource_access(db, db_report, user, owner_attr="checked_by")

    require_exportable_verified_report(db_report)

    report_data = json.loads(db_report.report_data)
    from app.engine.fusion import ComplianceReport
    report = ComplianceReport(**report_data)

    pdf_path = report_generator.generate_pdf(report)
    with open(pdf_path, "rb") as f:
        pdf_content = f.read()

    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="baohegui_report_{report_id}.pdf"'},
    )


@router.get("/{report_id}/export")
async def export_report_excel(
    report_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """导出合规报告为 Excel 文件。"""
    db_report = db.query(ReportModel).filter(ReportModel.id == report_id).first()
    if not db_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    assert_resource_access(db, db_report, user, owner_attr="checked_by")

    require_exportable_verified_report(db_report)

    report_data = json.loads(db_report.report_data) if db_report.report_data else {}
    violations = _load_report_violation_rows(db, report_id, report_data)
    output = export_report_to_excel(report_data, violations)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="baohegui_report_{report_id}.xlsx"'
        },
    )


@router.get("/list/")
async def list_reports(
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    score_min: float = 0,
    score_max: float = 100,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """列出报告，支持筛选、排序和分页。普通用户只能看自己的报告，管理员看全部。"""
    query = (
        db.query(ReportModel, UploadedFile.filename.label("file_name"))
        .outerjoin(UploadedFile, ReportModel.file_id == UploadedFile.id)
    )

    # 权限过滤：非管理员只能看到自己创建的检查报告
    if user.get("role") != "admin":
        user_id = get_current_user_id(user)
        query = query.filter(ReportModel.checked_by == user_id)

    if search.strip():
        query = query.filter(UploadedFile.filename.ilike(f"%{search.strip()}%"))

    if date_from:
        try:
            start_dt = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_from 格式应为 YYYY-MM-DD") from exc
        query = query.filter(ReportModel.created_at >= start_dt)

    if date_to:
        try:
            end_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_to 格式应为 YYYY-MM-DD") from exc
        query = query.filter(ReportModel.created_at < end_dt)

    if score_min > 0:
        query = query.filter(ReportModel.total_score >= score_min)
    if score_max < 100:
        query = query.filter(ReportModel.total_score <= score_max)

    sort_key = sort_by.strip().lower()
    sort_field_map = {
        "id": ReportModel.id,
        "file_id": ReportModel.file_id,
        "file_name": UploadedFile.filename,
        "total_score": ReportModel.total_score,
        "violation_count": ReportModel.violation_count,
        "created_at": ReportModel.created_at,
    }
    sort_field = sort_field_map.get(sort_key, ReportModel.created_at)
    sort_direction = sort_order.strip().lower()
    order_clause = sort_field.asc() if sort_direction == "asc" else sort_field.desc()
    query = query.order_by(order_clause)

    total = query.order_by(None).count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [
        {
            "id": report.id,
            "file_id": report.file_id,
            "file_name": file_name or "",
            "total_score": report.total_score,
            "violation_count": report.violation_count,
            "created_at": report.created_at.isoformat() if report.created_at else None,
        }
        for report, file_name in rows
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    }


# ── 审查反馈 API ────────────────────────────────────────────


class FeedbackRequest(BaseModel):
    report_id: int
    rule_id: str
    feedback_type: str  # confirm / false_positive / missed
    comment: Optional[str] = None


@router.post("/feedback")
async def submit_feedback(
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """提交审查反馈 — 不可变事件日志

    验证：
    - 报告存在且用户有访问权限
    - rule_id 确实存在于该报告的权威 report_data 中
    - 禁止针对伪造 rule_id 提交反馈
    - 同一 user+report+rule 幂等返回 409
    """
    import json as _json

    user_id = int(user["sub"])
    is_admin = user.get("role") == "admin"

    # 检查报告是否存在
    db_report = db.query(ReportModel).filter(ReportModel.id == req.report_id).first()
    if not db_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")

    # 报告所有者或管理员可提交
    if db_report.checked_by != user_id and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权为此报告提交反馈")

    # 验证 rule_id 存在于报告的权威 report_data 中（fail-closed）
    report_data = {}
    is_valid_json = True
    if db_report.report_data:
        try:
            report_data = _json.loads(db_report.report_data)
        except (_json.JSONDecodeError, TypeError):
            is_valid_json = False

    if not is_valid_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="报告数据格式异常，无法验证反馈",
        )

    valid_rule_ids = _extract_rule_ids_from_report(report_data)
    if not valid_rule_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="此报告不包含可反馈的审查发现",
        )
    if req.rule_id not in valid_rule_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"rule_id '{req.rule_id}' 不存在于此报告的审查结果中",
        )

    try:
        result = feedback_service.submit_feedback(
            db=db,
            report_id=req.report_id,
            rule_id=req.rule_id,
            user_id=user_id,
            feedback_type=req.feedback_type,
            comment=req.comment,
        )
        if result.get("status") == "duplicate":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["message"])
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _extract_rule_ids_from_report(report_data: dict) -> set[str]:
    """从 report_data 中提取所有合法的 rule_id — fail-closed: 无数据返回空集合。

    支持的权威格式：
    - _decision_input.rule_violations[].rule_id
    - _decision_input.bias_findings[].pattern_id → BIAS-{pattern_id}
    - violations[].rule_id (兼容旧格式)
    """
    ids: set[str] = set()
    di = report_data.get("_decision_input", {}) if isinstance(report_data, dict) else {}

    # 新格式: decision_input
    for rv in di.get("rule_violations", []):
        if isinstance(rv, dict):
            rid = rv.get("rule_id")
            if rid:
                ids.add(rid)
    for bf in di.get("bias_findings", []):
        if isinstance(bf, dict):
            pid = bf.get("pattern_id")
            if pid:
                ids.add(f"BIAS-{pid}")

    # 旧格式: 顶层 violations
    violations = report_data.get("violations", [])
    if isinstance(violations, list):
        for v in violations:
            if isinstance(v, dict):
                rid = v.get("rule_id")
                if rid:
                    ids.add(rid)

    return ids


@router.post("/feedback/{feedback_id}/transition")
async def transition_feedback_state(
    feedback_id: int,
    to_status: str = Query(..., description="目标状态: acknowledged/resolved/closed"),
    note: str = Query(default="", description="管理备注"),
    db: Session = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """管理员转换反馈状态 — 状态变化不触发任何执行链写入"""
    from app.services.feedback_service import FeedbackEvent
    from app.engine.feedback_state_machine import feedback_state_machine

    event = db.query(FeedbackEvent).filter(FeedbackEvent.id == feedback_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈事件不存在")

    ok, msg = feedback_state_machine.transition(
        event, to_status, admin_id=int(user["sub"]), note=note
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    db.commit()
    return {"feedback_id": feedback_id, "status": event.status, "message": msg}


@router.get("/feedback/rules-needing-review")
async def list_rules_needing_review(
    db: Session = Depends(get_db),
    user: dict = Depends(PermissionService.require_permission(Permission.RULES_READ)),
):
    """获取待审核的规则列表"""
    rules = feedback_service.get_rules_needing_review(db)
    return {"rules": rules}


# ── 智能条款生成 API ────────────────────────────────────────


class GenerateClauseRequest(BaseModel):
    original_text: str
    rule_description: str
    suggestion: str
    project_type: str = ""
    budget: str = ""
    industry: str = ""


@router.post("/generate-clause")
async def generate_clause(
    req: GenerateClauseRequest,
    user: dict = Depends(get_current_user),
):
    """生成合规替代条款"""
    if not req.original_text or not req.suggestion:
        raise HTTPException(status_code=400, detail="缺少必要参数 original_text 或 suggestion")

    result = await clause_generator.generate(
        original_text=req.original_text,
        rule_description=req.rule_description,
        suggestion=req.suggestion,
        project_type=req.project_type,
        budget=req.budget,
        industry=req.industry,
    )
    return result
