"""合规检查 API"""

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.policy_kernel import (
    DecisionInput,
    ParseQuality,
    PlanTier,
    PlatformPolicy,
    RuleType,
    RiskLevel,
    RuleViolationInput,
    LLMViolationInput,
    BiasFindingInput,
    RoutingInput,
    TenantPolicy,
    TrafficLight,
    UxPolicy,
    derive_merge_fields,
    policy_kernel,
    POLICY_SCHEMA_VERSION,
    verify_trace as _verify_trace,
)
from app.core.security import get_current_user, assert_resource_access
from app.db.database import get_db
from app.engine.fusion import fusion_engine, four_way_merger, validate_llm_evidence
from app.engine.parameter_bias import ParameterBiasDetector
from app.engine.routing import compliance_router
from app.engine.llm_engine import llm_engine
from app.engine.rule_engine import rule_engine, normalize_section_name
from app.engine.variable_marker import variable_marker
from app.models.document import ComplianceReport, UploadedFile
from app.services.parser import parser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/check", tags=["check"])


def _to_llm_violation_input(lv) -> LLMViolationInput:
    """将上游 LLM 违规对象映射为 PolicyKernel 的 LLMViolationInput。

    此函数是生产代码与测试共享的单一映射源。禁止生产与测试各写一套映射。
    """
    return LLMViolationInput(
        type=lv.type,
        risk_level=RiskLevel(lv.risk_level),
        reason=getattr(lv, "reason", ""),
        validation_error=getattr(lv, "validation_error", None),
        requires_human_review=getattr(lv, "requires_human_review", False),
    )


# ── Simple in-memory rate limiter ────────────────────────────
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 10     # max requests per window

# ── 检查进度内存存储 ──────────────────────────────────────────
_check_progress: dict[int, dict] = {}
_progress_lock = threading.Lock()
_PROGRESS_TTL = 600  # 10 分钟后自动清理


def _set_check_progress(file_id: int, **kwargs) -> None:
    with _progress_lock:
        entry = _check_progress.setdefault(file_id, {})
        entry.update(kwargs)
        entry["_updated"] = time.time()


def _get_check_progress(file_id: int) -> dict | None:
    with _progress_lock:
        entry = _check_progress.get(file_id)
        if entry and time.time() - entry.get("_updated", 0) > _PROGRESS_TTL:
            del _check_progress[file_id]
            return None
        return entry


def _check_rate_limit(user_id: str) -> bool:
    """Returns True if rate limit not exceeded"""
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    _rate_limit_store[user_id] = [
        t for t in _rate_limit_store[user_id] if t > window_start
    ]
    if len(_rate_limit_store[user_id]) >= _RATE_LIMIT_MAX:
        return False
    _rate_limit_store[user_id].append(now)
    return True


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
    platform: str | None = Query(
        default=None,
        description="目标平台ID，如 guangdong/jiangsu/gansu/sichuan/zhejiang",
    ),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """对指定文件执行合规检查（支持行业规则激活 + 定变分离优化）"""
    # Rate limit check
    user_id_str = str(user["sub"])
    if not _check_rate_limit(user_id_str):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试（每分钟最多10次）",
        )

    db_file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if not db_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    # 权限校验：只能检查自己上传的文件
    assert_resource_access(db, db_file, user)

    # 状态机校验：只能从 uploaded/queued/failed 开始检查
    if db_file.status not in ("uploaded", "queued", "failed", "completed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"文件状态为 {db_file.status}，无法开始检查（需为 uploaded/queued/failed/completed）",
        )

    # 状态机：进入 queued → checking
    db_file.status = "queued"
    db.commit()

    # ── queued → checking（模拟入队延迟，实际可接消息队列） ──
    db_file.status = "checking"
    db.commit()

    try:
        # 解析文件（通过 MinIO 或本地路径）
        from app.services.minio_service import minio_service

        try:
            with minio_service.local_path(db_file.storage_path) as local_path:
                parsed = parser.parse(local_path)
        except Exception as e:
            logger.exception("文件解析失败 file_id=%d: %s", file_id, e)
            sanitized = "文件解析失败，请稍后重试"
            db_file.status = "failed"
            db_file.error_message = sanitized
            db_file.failed_at = datetime.now(timezone.utc)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=sanitized,
            )

        # 如果指定了行业，激活对应的行业规则
        industry_list: list[str] = []
        industry_descriptions = ""
        industry_load_warnings: list[str] = []
        if industries:
            industry_list = [ind.strip() for ind in industries.split(",") if ind.strip()]
            rule_engine.set_active_industries(industry_list)
            industry_descriptions = rule_engine.get_industry_descriptions(industry_list)

        # ── 性能计时 ──────────────────────────────────────────────
        t_check_start = time.monotonic()

        # ── 第0层：零Token路由审查 ──────────────────────────────
        t0 = time.monotonic()
        _set_check_progress(file_id, stage="routing")
        budget = _extract_budget_from_document(parsed)
        routing_result = compliance_router.route(
            budget=budget,
            procurement_method=procurement_method or "",
            project_type=project_type or "",
        )
        t_routing = time.monotonic() - t0

        # ── 定变分离预处理 ──────────────────────────────────────
        t0 = time.monotonic()
        marked_doc = None
        try:
            marked_doc = variable_marker.mark(
                parsed_doc=parsed,
                sector=sector or "",
                procurement_method=procurement_method or "",
                project_type=project_type or "",
            )
        except Exception as e:
            logger.warning("定变分离标记失败，将跳过模板过滤: %s", e)
        t_marker = time.monotonic() - t0

        # ── 第1层：规则引擎检查 ──
        t0 = time.monotonic()
        _set_check_progress(file_id, stage="rule_engine")
        rule_result = rule_engine.run(
            sections=parsed.sections,
            full_text=parsed.full_text,
            marked_doc=marked_doc,
        )
        t_rules = time.monotonic() - t0

        # ── 第2层：参数倾向性检测 ──
        t0 = time.monotonic()
        _set_check_progress(file_id, stage="parameter_bias")
        parameter_bias_detector = ParameterBiasDetector()
        parameter_bias_result = parameter_bias_detector.run(sections=parsed.sections)
        from app.engine.shared_types import Violation
        parameter_bias_violations = []
        for finding in parameter_bias_result.findings:
            severity_map = {"critical": "high", "high": "high", "medium": "medium", "low": "low"}
            weight_map = {"critical": 20.0, "high": 15.0, "medium": 10.0, "low": 5.0}
            parameter_bias_violations.append(Violation(
                rule_id=finding.rule_id or f"BIAS-{finding.pattern_id}",
                rule_type="forbidden",
                description=finding.description or finding.pattern_name,
                location=finding.matched_field,
                text=finding.matched_text,
                risk_level=severity_map.get(finding.severity, "medium"),
                law_ref=finding.law_ref,
                weight=weight_map.get(finding.severity, 10.0),
                suggestion=finding.suggestion,
            ))
        t_param_bias = time.monotonic() - t0

        # ── RAG 依据补充（v3: build_rag_context 保证 trust + audit_status 双重过滤）──
        from app.services.knowledge_graph import knowledge_graph
        kg_context: str = ""
        if rule_result.violations:
            for v in rule_result.violations:
                if v.rule_id:
                    ctxs = knowledge_graph.build_rag_context(
                        db, v.rule_id, v.description or "",
                        max_regulations=2, max_cases=2,
                    )
                    if ctxs:
                        enriched = "; ".join(
                            f"[节点#{c['node_id']}] {c['title']}: {c['content'][:200]}"
                            for c in ctxs
                        )
                        if enriched:
                            v.law_ref = (v.law_ref or "") + (" | KG " + enriched if v.law_ref else enriched)

            # 构建 LLM prompt 的 KG 上下文（可追溯）
            kg_lines = []
            seen_ids = set()
            for v in rule_result.violations[:5]:
                if v.rule_id:
                    ctxs = knowledge_graph.build_rag_context(
                        db, v.rule_id, v.description or "",
                        max_regulations=2, max_cases=2,
                    )
                    for c in ctxs:
                        nid = c.get("node_id")
                        if nid and nid not in seen_ids:
                            seen_ids.add(nid)
                            # 包含法规条款摘要，节点ID/source/trust 可追溯
                            content_preview = (c.get("content", "") or "")[:120]
                            kg_lines.append(
                                f"- [{c['type']}] {v.rule_id}: {c['title']}"
                                f" ({content_preview}...)"
                                f" [来源: {c.get('source', '')}, 节点#{nid}, 可信度:{c.get('trust_level', 0):.0%}]"
                            )
            if not kg_lines:
                sample_desc = rule_result.violations[0].description if rule_result.violations else ""
                if sample_desc:
                    cases = knowledge_graph.find_similar_cases(db, sample_desc, limit=3)
                    for c in cases:
                        nid = c.get("id")
                        if nid and nid not in seen_ids:
                            seen_ids.add(nid)
                            kg_lines.append(
                                f"- [case] 相关案例: {c.get('title', '')}"
                                f" (来源: {c.get('source', '')}, 节点#{nid}, 可信度:{c.get('trust_level', 0):.0%})"
                            )
            if kg_lines:
                kg_context = "\n".join(kg_lines)
                logger.info("RAG 补充: %d 条法规/案例上下文 (min_trust=%.0f%%)", len(kg_lines), knowledge_graph.TRUST_MIN_ENRICHMENT * 100)

        # ── 第3层：LLM语义审查 ──
        t0 = time.monotonic()
        _set_check_progress(file_id, stage="llm_analysis")
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
                industry_descriptions=industry_descriptions,
                kg_context=kg_context or None,
            )
        t_llm = time.monotonic() - t0

        # ── 汇总层：融合结果 ──
        t0 = time.monotonic()
        _set_check_progress(file_id, stage="risk_merge")
        # LLM 证据链校验（evidence 定位 + law_ref 命中规则库）
        if llm_result and llm_result.violations:
            llm_result = validate_llm_evidence(llm_result, parsed.full_text or "")
        report = fusion_engine.merge(
            rule_result=rule_result,
            llm_result=llm_result,
            bias_violations=parameter_bias_violations,
            file_name=db_file.filename,
            check_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )
        parse_quality = parsed.parse_quality
        merge_result = four_way_merger.merge(
            routing_result=routing_result,
            rule_engine_result=rule_result,
            parameter_bias_result=parameter_bias_result,
            llm_result=llm_result,
            parse_quality=parse_quality,
        )

        # ── PolicyKernel：系统唯一决策入口 ────────────────────
        from app.services.quota_service import get_or_create_quota
        user_quota_record = get_or_create_quota(db, int(user["sub"]))
        plan = user_quota_record.plan if user_quota_record else "free"
        _plan_to_tier = {"enterprise": PlanTier.ENTERPRISE, "pro": PlanTier.PRO, "free": PlanTier.FREE}

        # 构建文档真实章节集合（经规范化）
        present_sections_raw = set(parsed.sections.keys()) if parsed.sections else set()
        present_sections = {normalize_section_name(s) for s in present_sections_raw}

        # 从平台规则引擎派生平台策略（加载真实 required_sections）
        platform_policy = PlatformPolicy()
        if platform:
            from app.engine.platform_rules import platform_rule_engine
            plat = platform_rule_engine.get_platform(platform)
            if plat:
                plat_required_raw = set(plat.get("required_sections", []))
                plat_required = {normalize_section_name(s) for s in plat_required_raw}
                platform_policy = PlatformPolicy(
                    platform_id=platform,
                    required_sections=plat_required,
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"未知平台: {platform}",
                )

        # 加载动态 applied 策略（单一入口，不绕过审批）
        from app.services.policy_repository import load_applied_policy_context
        from app.services.policy_schema import (
            build_effective_tenant_policy,
            build_effective_platform_policy,
        )

        # Tenant: base + dynamic applied (仅当前 user scope)
        tenant_policy = TenantPolicy(
            tenant_id=str(user["sub"]),
            auto_fail_rule_types={RuleType.FORBIDDEN} if plan != "enterprise" else set(),
            requires_human_review_if_llm_only=(plan != "enterprise"),
            plan_tier=_plan_to_tier.get(plan, PlanTier.FREE),
        )
        tenant_applied = load_applied_policy_context(
            db, policy_type="tenant",
            scope_type="user", scope_id=str(user["sub"]),
        )
        tenant_policy = build_effective_tenant_policy(tenant_policy, tenant_applied)

        # Platform: base + dynamic applied (仅当前 platform scope)
        if platform:
            platform_applied = load_applied_policy_context(
                db, policy_type="platform",
                scope_type="platform", scope_id=platform,
            )
            platform_policy = build_effective_platform_policy(platform_policy, platform_applied)

        import json as _json

        decision_input = DecisionInput(
            schema_version=POLICY_SCHEMA_VERSION,
            routing=RoutingInput(
                traffic_light=TrafficLight(routing_result.traffic_light.value),
                skip_llm=routing_result.skip_llm,
            ),
            rule_violations=[
                RuleViolationInput(
                    rule_id=v.rule_id,
                    rule_type=RuleType(v.rule_type),
                    risk_level=RiskLevel(v.risk_level),
                    description=v.description,
                    location=getattr(v, "location", None) or "",
                )
                for v in (rule_result.violations if rule_result else [])
            ],
            bias_findings=[
                BiasFindingInput(
                    pattern_id=f.pattern_id,
                    severity=RiskLevel(f.severity),
                    description=f.description or f.pattern_name,
                    matched_text=f.matched_text,
                    matched_field=f.matched_field,
                )
                for f in (parameter_bias_result.findings if parameter_bias_result else [])
            ],
            llm_violations=[
                _to_llm_violation_input(lv)
                for lv in (llm_result.violations if llm_result else [])
            ],
            parse_quality=ParseQuality(parse_quality),
            present_sections=present_sections,
            tenant_policy=tenant_policy,
            platform_policy=platform_policy,
            ux_policy=UxPolicy(),
        )

        policy_decision = policy_kernel.decide(decision_input)

        # PolicyDecision → 兼容字段（merge_*）
        merge_compat = derive_merge_fields(policy_decision)
        t_fusion = time.monotonic() - t0
        t_total = time.monotonic() - t_check_start
        template_stats = marked_doc.stats if marked_doc else {}

        # ── 单一载荷构造函数 ──
        report_data = build_policy_audit_payload(
            report=report,
            decision_input=decision_input,
            policy_decision=policy_decision,
            diagnostics={
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
                    "risk_items_count": len(merge_result.risk_items),
                    "confirmed_count": merge_result.confirmed_count,
                    "high_risk_count": merge_result.high_risk_count,
                    "needs_review_count": merge_result.needs_review_count,
                    "advisory_count": merge_result.advisory_count,
                    "final_passed": merge_compat["final_passed"],
                    "risk_level": merge_compat["risk_level"],
                    "review_status": merge_compat["review_status"],
                    "requires_human_review": merge_compat["requires_human_review"],
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
                "state_machine": {
                    "upload_status": "uploaded",
                    "check_flow": "uploaded → queued → checking → completed",
                },
            },
        )

        # ── 构建确定性重放审计轨道 ──────────────────────────────
        _t0_trace = time.monotonic()
        from app.core.replay_engine import (
            AuditTrace, LLMBoundary, OCRBoundary, verify_replay,
        )

        # Parser boundary snapshot
        ocr_boundary = OCRBoundary.from_parsed(parsed, file_hash=db_file.file_hash)

        # Compute asset hashes for LLM boundary
        import hashlib as _hl
        _rule_asset_hash = ""
        _prompt_asset_hash = ""
        try:
            from app.services.prompt_manager import PromptManager
            pm = PromptManager()
            tmpl = pm.get_prompt("compliance_check")
            _prompt_asset_hash = _hl.sha256(tmpl.content.encode()).hexdigest()
        except Exception:
            pass
        try:
            _rules_content = json.dumps(
                [r.model_dump(mode="json") if hasattr(r, "model_dump") else str(r)
                 for r in rule_engine.rules],
                sort_keys=True, ensure_ascii=False,
            )
            _rule_asset_hash = _hl.sha256(_rules_content.encode()).hexdigest()
        except Exception:
            pass

        # LLM boundary snapshot
        llm_boundary = None
        if llm_result:
            _call_status = "failed" if llm_result.error else "succeeded"
            if settings.llm_mock_mode:
                _call_status = "succeeded"  # mock is still a valid simulation
            # Get prompt text for hash
            _prompt_text = ""
            try:
                _prompt_text = llm_engine.prompt_template
            except Exception:
                pass
            llm_boundary = LLMBoundary.from_llm_result(
                llm_result,
                prompt_text=_prompt_text,
                provider=settings.llm_provider,
                model=settings.llm_model,
                temperature=getattr(llm_engine, "temperature", 0.0),
                seed=getattr(settings, "llm_seed", None),
                max_tokens=getattr(llm_engine, "max_tokens", 0),
                prompt_asset_hash=_prompt_asset_hash,
                rule_asset_hash=_rule_asset_hash,
                call_status=_call_status,
            )
        elif routing_result is not None:
            # LLM was skipped — record why
            skip_reason = "routing_skip_llm" if routing_result.skip_llm else "no_sections"
            llm_boundary = LLMBoundary(
                provider=settings.llm_provider,
                model=settings.llm_model,
                temperature=getattr(llm_engine, "temperature", 0.0),
                max_tokens=getattr(llm_engine, "max_tokens", 0),
                call_status="skipped",
                skip_reason=skip_reason,
            )

        audit_trace = AuditTrace.from_pipeline(
            file_hash=db_file.file_hash,
            file_name=db_file.filename,
            parsed_sections=parsed.sections,
            budget=budget,
            procurement_method=procurement_method or "",
            project_type=project_type or "",
            industries=industry_list or None,
            platform=platform,
            routing_result=routing_result,
            rule_result=rule_result,
            bias_result=parameter_bias_result,
            llm_boundary=llm_boundary,
            ocr_boundary=ocr_boundary,
            decision_input=decision_input,
            policy_decision=policy_decision,
        )

        # ── 写入前验证 ──
        # 1. PolicyKernel 内部 trace 验证
        verification = _verify_trace(decision_input, policy_decision)
        if not verification["valid"]:
            logger.error(
                "PolicyDecision 验证失败，拒绝写入 file_id=%d: %s",
                file_id, verification["errors"],
            )
            db_file.status = "failed"
            db_file.error_message = "内部决策一致性错误，请稍后重试"
            db_file.failed_at = datetime.now(timezone.utc)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="内部决策一致性错误，请稍后重试",
            )

        # 2. 完整确定性重放验证
        replay_verification = verify_replay(audit_trace)
        if not replay_verification["valid"]:
            logger.error(
                "AuditTrace 重放验证失败，拒绝写入 verified 状态 file_id=%d: %s",
                file_id, replay_verification["errors"],
            )
            db_file.status = "failed"
            db_file.error_message = "重放一致性错误，请稍后重试"
            db_file.failed_at = datetime.now(timezone.utc)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="内部重放一致性错误，请稍后重试",
            )

        db_report = ComplianceReport(
            file_id=file_id,
            total_score=report.total_score,
            section_score=report.section_score,
            keyword_score=report.keyword_score,
            forbidden_score=report.forbidden_score,
            semantic_score=report.semantic_score,
            violation_count=report.total_violations,
            report_data=json.dumps(report_data, ensure_ascii=False),
            checked_by=int(user["sub"]),
        )
        # ── 写入权威决策列 ──────────────────────────────────────
        db_report.decision_action = policy_decision.final_action.value
        db_report.decision_risk_level = policy_decision.final_risk_level.value
        db_report.decision_requires_human_review = 1 if policy_decision.requires_human_review else 0
        db_report.decision_hash = policy_decision.decision_hash
        db_report.policy_schema_version = policy_decision.schema_version
        db_report.decision_integrity_status = "verified"

        # ── 写入确定性重放审计轨道 ──────────────────────────────
        db_report.audit_trace = audit_trace.to_dict()
        db_report.audit_trace_valid = True

        db.add(db_report)
        db_file.status = "completed"
        db.commit()
        db.refresh(db_report)

        # 消耗 Token 配额
        from app.services.quota_service import consume_tokens
        if llm_result and llm_result.tokens_used:
            consume_tokens(db, int(user["sub"]), llm_result.tokens_used, llm_result.cost_yuan)

        _set_check_progress(file_id, stage="done", report_id=db_report.id)

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
            "industry_descriptions": industry_descriptions or None,
            "template_stats": template_stats,
            "traffic_light": routing_result.traffic_light.value,
            "routing_reasoning": routing_result.reasoning,
            "parameter_bias_score": parameter_bias_result.risk_score,
            "parameter_bias_findings": parameter_bias_result.critical_count + parameter_bias_result.high_count,
            "merge_risk_level": merge_compat["risk_level"],
            "merge_review_status": merge_compat["review_status"],
            "merge_requires_human_review": merge_compat["requires_human_review"],
            "merge_confirmed_count": merge_result.confirmed_count,
            "merge_high_risk_count": merge_result.high_risk_count,
            "policy_decision": {
                "final_action": policy_decision.final_action.value,
                "final_risk_level": policy_decision.final_risk_level.value,
                "requires_human_review": policy_decision.requires_human_review,
                "decision_hash": policy_decision.decision_hash,
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

    except HTTPException:
        _set_check_progress(file_id, stage="error")
        raise
    except Exception as e:
        logger.exception("合规检查未捕获异常 file_id=%d: %s", file_id, e)
        sanitized = "内部处理错误，请稍后重试"
        _set_check_progress(file_id, stage="error", error=sanitized)
        db_file.status = "failed"
        db_file.error_message = sanitized
        db_file.failed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=sanitized,
        )


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


def build_policy_audit_payload(
    report,
    decision_input: DecisionInput,
    policy_decision,
    diagnostics: dict,
) -> dict:
    """单一报告决策载荷构造函数。

    返回 dict 直接作为 report_data JSON — 所有字段来自两个 Pydantic 模型，
    不手工拼装 PolicyDecision 字段。
    """
    return {
        **report.model_dump(),
        "_diagnostics": diagnostics,
        "_decision_input": decision_input.model_dump(mode="json"),
        "_policy_decision": policy_decision.model_dump(mode="json"),
    }


@router.get("/{file_id}/status")
async def get_check_status(
    file_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """获取合规检查进度（轮询用）"""
    db_file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if not db_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    # 仅文件所有者或管理员可以查询状态
    if db_file.user_id != int(user["sub"]) and user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    progress = _get_check_progress(file_id)
    if progress:
        return progress
    return {"stage": "unknown"}
