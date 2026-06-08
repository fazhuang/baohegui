"""项目分类 API — 从 project_categories.json 提供行业分类层级"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/categories", tags=["categories"])

_CATEGORIES_FILE = (
    Path(__file__).resolve().parent.parent.parent.parent / "rules" / "project_categories.json"
)

_CACHE: dict | None = None


def _load_categories() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        with open(_CATEGORIES_FILE, encoding="utf-8") as f:
            _CACHE = json.load(f)
        logger.info("已加载项目分类: %d 组, %d 子类", len(_CACHE["category_groups"]), len(_CACHE["categories"]))
    except Exception as e:
        logger.error("加载分类文件失败: %s", e)
        _CACHE = {"category_groups": [], "categories": [], "procurement_methods": [], "evaluation_methods": []}
    return _CACHE


@router.get("/")
async def get_categories():
    """返回完整的项目分类层级"""
    return _load_categories()


@router.get("/groups")
async def get_category_groups():
    """返回行业大类列表"""
    data = _load_categories()
    return {"groups": data["category_groups"]}


@router.get("/groups/{group_id}/categories")
async def get_categories_by_group(group_id: str):
    """返回指定大类下的子类列表"""
    data = _load_categories()
    children = [c for c in data["categories"] if c.get("parent") == group_id]
    return {"group_id": group_id, "categories": children}
