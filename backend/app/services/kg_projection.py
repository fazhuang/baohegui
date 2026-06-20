"""KG 投影服务

Phase 2 — 案例运营闭环的 KG 投影：
- 仅 published 案例投影到生产 KG
- 使用 origin_type/origin_id/content_hash/sync_version 追踪
- 投影失败可重试（幂等）
- 下架案例同步从 RAG 隔离
- 不产生重复节点或重复边
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.complaint_case import ComplaintCase
from app.models.knowledge_graph import KGNode, KGEdge
from app.engine.case_state_machine import CaseStatus, PublishStatus

logger = logging.getLogger(__name__)

# KG 投影版本
SYNC_VERSION = "2.0.0"

# 同步版本键（存储在 KGNode.metadata_json）
SYNC_VERSION_KEY = "sync_version"
ORIGIN_TYPE_KEY = "origin_type"
ORIGIN_ID_KEY = "origin_id"


class KGProjectionService:
    """KG 投影服务 — 将发布案例投影到知识图谱"""

    @staticmethod
    def project_case(db: Session, case: ComplaintCase) -> dict:
        """将单个案例投影到 KG。

        幂等：已存在同 origin_type/origin_id 的节点则更新。
        仅 published 案例可投影。
        重新发布（republish）时将 rejected 节点恢复为 verified 并清除 unprojected_at。

        Phase 2 幂等判断比较：
        - content_hash
        - audit_status（rejected → 需要恢复，不是 skipped）
        - 是否存在 unprojected_at（下架过 → 需要恢复而不是跳过）
        - sync_version（版本升级 → 更新而不是跳过）

        返回：
        {
            "success": bool,
            "action": "created" | "updated" | "restored" | "skipped",
            "node_id": int | None,
            "case_id": int,
            "error": str | None,
        }
        """
        result = {
            "success": False,
            "action": "skipped",
            "node_id": None,
            "case_id": case.id,
            "error": None,
        }

        # 安全约束：仅 published
        if case.review_status != CaseStatus.PUBLISHED.value:
            result["error"] = f"案例 {case.id} 未发布 (status={case.review_status})"
            return result

        # 安全约束：仅 publish_status = published
        if case.publish_status != PublishStatus.PUBLISHED.value:
            result["error"] = f"案例 {case.id} 已下架 (publish_status={case.publish_status})"
            return result

        try:
            # 安全约束：拒绝未脱敏内容进入 KG/RAG
            _sanitized = (case.sanitized_content or "").strip()
            if not _sanitized:
                result["error"] = (
                    f"案例 {case.id} 缺少 sanitized_content，"
                    f"禁止将未脱敏内容投影到 KG/RAG"
                )
                return result

            content_hash = case.content_hash or _compute_content_hash(case)

            # 查找已有节点（幂等）
            existing = KGProjectionService._find_by_origin(db, "complaint_case", case.id)

            if existing:
                existing_meta = _parse_metadata(existing.metadata_json)
                needs_restore = (
                    existing.audit_status == "rejected"
                    or existing_meta.get("unprojected_at") is not None
                    or existing_meta.get(SYNC_VERSION_KEY) != SYNC_VERSION
                )
                content_unchanged = existing_meta.get("content_hash") == content_hash

                # Phase 2 fix: 重新发布时必须恢复 rejected 节点
                if needs_restore:
                    _restore_case_node(existing, case, content_hash)
                    result["action"] = "restored"
                    result["node_id"] = existing.id
                elif content_unchanged:
                    # 内容未变、状态正常、版本匹配 → 真正跳过
                    result["action"] = "skipped"
                    result["node_id"] = existing.id
                    result["success"] = True
                    return result
                else:
                    # 内容变化 → 更新
                    _update_case_node(existing, case, content_hash)
                    result["action"] = "updated"
                    result["node_id"] = existing.id
            else:
                # 创建新节点
                node = _create_case_node(case, content_hash)
                db.add(node)
                db.flush()
                result["action"] = "created"
                result["node_id"] = node.id

            result["success"] = True

        except Exception as e:
            logger.error(f"案例 {case.id} KG 投影失败: {e}")
            result["error"] = str(e)

        return result

    @staticmethod
    def unproject_case(db: Session, case: ComplaintCase) -> dict:
        """下架案例的 KG 投影 — 软删除节点（标记 rejected）

        这使得该案例从 RAG 检索中隔离。记录 unprojected_at 时间戳。
        再次 republish 时会被 _restore_case_node 恢复。
        """
        result = {
            "success": False,
            "action": "skipped",
            "node_id": None,
            "case_id": case.id,
            "error": None,
        }

        try:
            existing = KGProjectionService._find_by_origin(db, "complaint_case", case.id)
            if existing:
                existing.audit_status = "rejected"
                existing.trust_level = 0.35  # 降低信任度，防止意外 RAG 引用
                existing.metadata_json = _update_metadata(existing.metadata_json, {
                    SYNC_VERSION_KEY: SYNC_VERSION,
                    "unprojected_at": datetime.now(timezone.utc).isoformat(),
                    # 清除 synced_at 以强制 republish 时重新同步
                })
                # 清除 synced_at
                meta = _parse_metadata(existing.metadata_json)
                meta.pop("synced_at", None)
                existing.metadata_json = json.dumps(meta, ensure_ascii=False)
                existing.trust_level = 0.35  # 降低信任度，防止意外 RAG 引用
                result["action"] = "removed"
                result["node_id"] = existing.id
            else:
                result["action"] = "skipped"  # 本来就没有 KG 节点

            result["success"] = True

        except Exception as e:
            logger.error(f"案例 {case.id} KG 下架失败: {e}")
            result["error"] = str(e)

        return result

    @staticmethod
    def project_all_published(
        db: Session,
        limit: int = 100,
        retry_failed: bool = True,
    ) -> dict:
        """批量投影所有 published 案例到 KG。

        幂等，已投影的自动更新。
        """
        q = db.query(ComplaintCase).filter(
            ComplaintCase.review_status == CaseStatus.PUBLISHED.value,
            ComplaintCase.publish_status == PublishStatus.PUBLISHED.value,
        )

        cases = q.limit(limit).all()

        created = 0
        updated = 0
        failed = 0
        details = []

        for case in cases:
            r = KGProjectionService.project_case(db, case)
            details.append(r)

            if r["success"]:
                if r["action"] == "created":
                    created += 1
                elif r["action"] == "updated":
                    updated += 1
            else:
                failed += 1

        db.commit()

        logger.info(
            f"KG 批量投影完成: created={created}, updated={updated}, failed={failed}"
        )

        return {
            "total": len(cases),
            "created": created,
            "updated": updated,
            "failed": failed,
            "sync_version": SYNC_VERSION,
            "details": details,
        }

    @staticmethod
    def remove_unpublished(
        db: Session,
        limit: int = 100,
    ) -> dict:
        """清理 KG 中已下架案例的节点（标记 rejected）"""
        unpublished_cases = db.query(ComplaintCase).filter(
            ComplaintCase.review_status == CaseStatus.UNPUBLISHED.value,
        ).limit(limit).all()

        removed = 0
        details = []

        for case in unpublished_cases:
            r = KGProjectionService.unproject_case(db, case)
            details.append(r)
            if r["action"] == "removed":
                removed += 1

        db.commit()

        return {
            "total": len(unpublished_cases),
            "removed": removed,
            "details": details,
        }

    @staticmethod
    def _find_by_origin(db: Session, origin_type: str, origin_id: int) -> KGNode | None:
        """通过 origin_type/origin_id 查找 KG 节点。

        在 metadata_json 中查找 origin_type 和 origin_id。
        """
        # 方法 1: 通过 rule_id（complaint_cases 映射为 CC-{id}）
        node = db.query(KGNode).filter(
            KGNode.node_type == "case",
            KGNode.rule_id == f"CC-{origin_id}",
        ).first()
        if node:
            return node

        # 方法 2: 扫描 metadata_json（回退）
        # 这是 O(n) 的但 case 节点数量有限
        candidates = db.query(KGNode).filter(
            KGNode.node_type == "case",
        ).all()

        for node in candidates:
            meta = _parse_metadata(node.metadata_json)
            if (
                meta.get(ORIGIN_TYPE_KEY) == origin_type
                and meta.get(ORIGIN_ID_KEY) == origin_id
            ):
                return node

        return None


# ── 内部辅助 ────────────────────────────────────────

def _create_case_node(case: ComplaintCase, content_hash: str) -> KGNode:
    """从 ComplaintCase 创建 KGNode"""
    import ast
    import json as _json

    # 标签
    decision_tag_map = {
        "upheld": "投诉成立",
        "rejected": "投诉驳回",
        "partial": "部分成立",
        "dismissed": "驳回",
    }
    decision_label = decision_tag_map.get(case.decision_type, case.decision_type or "unknown")
    complaint_types = case.get_complaint_types()
    tags_parts = ["案例", "投诉案例", decision_label]
    tags_parts.extend(complaint_types)
    tags = ",".join(filter(None, tags_parts))

    # 内容
    content_parts = []
    if case.project_name:
        content_parts.append(f"项目名称: {case.project_name}")
    if case.project_number:
        content_parts.append(f"项目编号: {case.project_number}")
    if case.case_no:
        content_parts.append(f"案件编号: {case.case_no}")
    if case.decision_date:
        content_parts.append(f"决定日期: {case.decision_date.isoformat()}")
    content_parts.append(f"处理结果: {decision_label}")
    if complaint_types:
        content_parts.append(f"投诉类型: {', '.join(complaint_types)}")
    if case.legal_basis:
        content_parts.append(f"法规依据: {case.legal_basis}")
    if case.summary:
        content_parts.append(f"摘要: {case.summary}")

    # 脱敏内容 （仅允许 sanitized_content）
    body = (case.sanitized_content or "").strip()
    if body:
        content_parts.append(f"正文: {body[:1500]}")

    content = "\n".join(content_parts)[:3000]

    # 元数据
    metadata = {
        ORIGIN_TYPE_KEY: "complaint_case",
        ORIGIN_ID_KEY: case.id,
        "content_hash": content_hash,
        "decision_type": case.decision_type,
        "complaint_types": complaint_types,
        "project_name": case.project_name,
        "project_number": case.project_number,
        "source_url": case.source_url,
        "canonical_url": case.canonical_url,
        "case_no": case.case_no,
        "city": case.city,
        "quality_score": case.quality_score,
        "extractor_version": case.extractor_version,
        SYNC_VERSION_KEY: SYNC_VERSION,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }

    title_prefix = f"[{case.province}] " if case.province and case.province != "全国" else ""
    title = f"{title_prefix}{case.title}"

    return KGNode(
        node_type="case",
        title=title,
        content=content,
        source=f"{case.province}政府采购网" if case.province else "政府采购网",
        source_url=case.canonical_url or case.source_url or "",
        tags=tags,
        jurisdiction=case.province or "",
        rule_id=f"CC-{case.id}",
        publish_date=case.decision_date,
        metadata_json=json.dumps(metadata, ensure_ascii=False),
        trust_level=0.65,
        audit_status="verified",  # published cases auto-entitled to RAG retrieval
    )


def _restore_case_node(
    node: KGNode,
    case: ComplaintCase,
    content_hash: str,
) -> None:
    """恢复被下架的 KG 节点（rejected → verified，清除 unprojected_at）。

    用于 republish 路径：published → unpublished → republish。
    """
    # 恢复审核状态为 verified
    node.audit_status = "verified"

    # 更新内容和元数据
    old_meta = _parse_metadata(node.metadata_json)
    old_meta.update({
        ORIGIN_TYPE_KEY: "complaint_case",
        ORIGIN_ID_KEY: case.id,
        "content_hash": content_hash,
        SYNC_VERSION_KEY: SYNC_VERSION,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    })
    # 清除下架标记
    old_meta.pop("unprojected_at", None)
    node.metadata_json = json.dumps(old_meta, ensure_ascii=False)

    # 更新展示字段
    _update_case_node_fields(node, case)
    logger.info("KG 节点 %d 已恢复 (republish case %d)", node.id, case.id)


def _update_case_node_fields(node: KGNode, case: ComplaintCase) -> None:
    """更新 KG 节点的展示字段（不碰 metadata）"""
    decision_tag_map = {
        "upheld": "投诉成立",
        "rejected": "投诉驳回",
        "partial": "部分成立",
        "dismissed": "驳回",
    }
    decision_label = decision_tag_map.get(case.decision_type, case.decision_type or "unknown")

    title_prefix = f"[{case.province}] " if case.province and case.province != "全国" else ""
    node.title = f"{title_prefix}{case.title}"

    content_parts = []
    if case.project_name:
        content_parts.append(f"项目名称: {case.project_name}")
    if case.project_number:
        content_parts.append(f"项目编号: {case.project_number}")
    if case.case_no:
        content_parts.append(f"案件编号: {case.case_no}")
    if case.decision_date:
        content_parts.append(f"决定日期: {case.decision_date.isoformat()}")
    content_parts.append(f"处理结果: {decision_label}")
    if case.summary:
        content_parts.append(f"摘要: {case.summary}")
    body = (case.sanitized_content or "").strip()
    if body:
        content_parts.append(f"正文: {body[:1500]}")
    node.content = "\n".join(content_parts)[:3000]
    node.source_url = case.canonical_url or case.source_url or ""
    node.jurisdiction = case.province or ""
    node.publish_date = case.decision_date


def _update_case_node(
    node: KGNode,
    case: ComplaintCase,
    content_hash: str,
) -> None:
    """更新 KG 节点（幂等同步）"""
    # 更新基础展示字段
    _update_case_node_fields(node, case)

    # 更新 metadata
    old_meta = _parse_metadata(node.metadata_json)
    old_meta.update({
        ORIGIN_TYPE_KEY: "complaint_case",
        ORIGIN_ID_KEY: case.id,
        "content_hash": content_hash,
        "decision_type": case.decision_type,
        "complaint_types": case.get_complaint_types(),
        "project_name": case.project_name,
        "project_number": case.project_number,
        "source_url": case.source_url,
        "canonical_url": case.canonical_url,
        "case_no": case.case_no,
        "city": case.city,
        "quality_score": case.quality_score,
        "extractor_version": case.extractor_version,
        SYNC_VERSION_KEY: SYNC_VERSION,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    })
    node.metadata_json = json.dumps(old_meta, ensure_ascii=False)


def _compute_content_hash(case: ComplaintCase) -> str:
    """计算案例内容哈希"""
    text = (
        (case.title or "")
        + (case.raw_content or "")
        + (case.summary or "")
        + (case.project_number or "")
        + (case.case_no or "")
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_metadata(raw: str | None) -> dict:
    """解析 metadata JSON"""
    import json as _json
    if not raw:
        return {}
    try:
        return _json.loads(raw)
    except (_json.JSONDecodeError, TypeError):
        return {}


def _update_metadata(raw: str | None, updates: dict) -> str:
    """更新 metadata JSON"""
    meta = _parse_metadata(raw)
    meta.update(updates)
    return json.dumps(meta, ensure_ascii=False)


# 模块级单例
kg_projection = KGProjectionService()
