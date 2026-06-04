"""规则管理 API — CRUD + 同步 + 导入"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.security import get_current_user
from app.engine.rule_engine import rule_engine
from app.services.rule_sync import rule_sync_service
from app.services.sync_scheduler import sync_scheduler

router = APIRouter(prefix="/api/rules", tags=["rules"])


# ── 请求模型 ────────────────────────────────────────────────

class ImportRulesRequest(BaseModel):
    rules: list[dict]


class CreateRuleRequest(BaseModel):
    rule_id: str
    platform: str
    platform_code: str
    rule_type: str = "unknown"
    target: str = ""
    mandatory: bool = True
    description: str = ""
    version: str = "1.0"
    effective_date: str = ""
    enabled: bool = True
    category: str = "platform"


class UpdateRuleRequest(BaseModel):
    platform: str | None = None
    platform_code: str | None = None
    rule_type: str | None = None
    target: str | None = None
    mandatory: bool | None = None
    description: str | None = None
    version: str | None = None
    effective_date: str | None = None
    enabled: bool | None = None
    category: str | None = None


# ── 规则引擎管理 ────────────────────────────────────────────

@router.post("/reload")
async def reload_rules(user: dict = Depends(get_current_user)):
    """热加载规则文件"""
    try:
        rule_engine.reload()
        return {
            "message": "规则已重新加载",
            "rule_count": len(rule_engine.rules),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"规则加载失败: {str(e)}",
        )


@router.get("/engine/status")
async def get_engine_status(user: dict = Depends(get_current_user)):
    """规则引擎状态"""
    rules = rule_engine.rules
    by_type: dict[str, int] = {}
    for r in rules:
        by_type[r.type] = by_type.get(r.type, 0) + 1
    return {
        "total": len(rules),
        "by_type": by_type,
    }


# ── 平台规则 CRUD ──────────────────────────────────────────

@router.get("/platform/list")
async def list_platform_rules(
    enabled_only: bool = Query(False),
    search: str | None = Query(None),
    platform: str | None = Query(None),
    user: dict = Depends(get_current_user),
):
    """列出平台规则（支持搜索和筛选）"""
    if search:
        rules = rule_sync_service.search_rules(search)
    elif platform:
        rules = rule_sync_service.get_rules_by_platform(platform)
    else:
        rules = rule_sync_service.get_all_rules(enabled_only=enabled_only)

    return {
        "total": len(rules),
        "rules": [r.model_dump() for r in rules],
        "platforms": rule_sync_service.get_platforms(),
    }


@router.get("/platform/{rule_id}")
async def get_platform_rule(
    rule_id: str,
    user: dict = Depends(get_current_user),
):
    """获取单条平台规则"""
    rule = rule_sync_service.get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    return rule.model_dump()


@router.post("/platform")
async def create_platform_rule(
    request: CreateRuleRequest,
    user: dict = Depends(get_current_user),
):
    """创建平台规则"""
    rule, error = rule_sync_service.add_rule(request.model_dump())
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    return {"message": "规则已创建", "rule": rule.model_dump()}


@router.put("/platform/{rule_id}")
async def update_platform_rule(
    rule_id: str,
    request: UpdateRuleRequest,
    user: dict = Depends(get_current_user),
):
    """更新平台规则"""
    data = {k: v for k, v in request.model_dump().items() if v is not None}
    rule, error = rule_sync_service.update_rule(rule_id, data)
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    return {"message": "规则已更新", "rule": rule.model_dump()}


@router.delete("/platform/{rule_id}")
async def delete_platform_rule(
    rule_id: str,
    user: dict = Depends(get_current_user),
):
    """删除平台规则"""
    if not rule_sync_service.delete_rule(rule_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    return {"message": "规则已删除"}


@router.post("/platform/{rule_id}/toggle")
async def toggle_platform_rule(
    rule_id: str,
    user: dict = Depends(get_current_user),
):
    """切换规则启用/停用"""
    enabled = rule_sync_service.toggle_rule(rule_id)
    if enabled is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    return {
        "message": f"规则已{'启用' if enabled else '停用'}",
        "enabled": enabled,
    }


# ── 导入 ────────────────────────────────────────────────────

@router.post("/import")
async def import_rules(
    request: ImportRulesRequest,
    user: dict = Depends(get_current_user),
):
    """批量导入规则"""
    result = rule_sync_service.import_rules(request.rules)
    return result


# ── 同步 ────────────────────────────────────────────────────

@router.get("/sync/status")
async def get_sync_status(user: dict = Depends(get_current_user)):
    """同步状态概览"""
    all_rules = rule_sync_service.get_all_rules()
    enabled_count = len([r for r in all_rules if r.enabled])
    return {
        "total_rules": len(all_rules),
        "enabled_rules": enabled_count,
        "platforms": rule_sync_service.get_platforms(),
        "rule_engine_loaded": len(rule_engine.rules),
        "available_platforms": list(rule_sync_service.MOCK_PLATFORMS.keys()),
    }


@router.post("/sync/run")
async def run_sync(
    platform: str,
    user: dict = Depends(get_current_user),
):
    """执行平台规则同步"""
    import asyncio
    record = await sync_scheduler.sync(platform)
    return {
        "status": record.status.value,
        "new_rules": record.result.new_rules if record.result else 0,
        "updated_rules": record.result.updated_rules if record.result else 0,
        "errors": record.result.errors if record.result else [],
        "retry_count": record.retry_count,
        "version": record.version_created,
    }


@router.get("/sync/history")
async def get_sync_history(user: dict = Depends(get_current_user)):
    """同步历史记录"""
    return sync_scheduler.get_history(20)


@router.get("/sync/diff")
async def get_sync_diff(
    platform: str,
    user: dict = Depends(get_current_user),
):
    """查看与平台的规则差异"""
    diffs = rule_sync_service.get_diff(platform)
    return {"platform": platform, "diffs": [d.model_dump() for d in diffs]}
