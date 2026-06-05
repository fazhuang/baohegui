"""平台规则差异引擎 — 通用规则池 + 平台差异层叠加"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_RULES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "rules"
_PLATFORMS_DIR = _RULES_DIR / "platforms"


class PlatformRuleEngine:
    """平台规则差异引擎"""

    def __init__(self):
        self._platform_rules: dict[str, dict] = {}
        self._load_all()

    def _load_all(self) -> None:
        """加载所有平台的差异规则"""
        if not _PLATFORMS_DIR.exists():
            logger.warning("平台规则目录不存在: %s", _PLATFORMS_DIR)
            return

        for fpath in _PLATFORMS_DIR.glob("*.json"):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                platform_id = data.get("platform", fpath.stem)
                self._platform_rules[platform_id] = data
                logger.info("加载平台规则: %s (%s)", platform_id, data.get("name", ""))
            except Exception as e:
                logger.warning("平台规则加载失败 %s: %s", fpath.name, e)

    def get_platform(self, platform_id: str) -> Optional[dict]:
        """获取指定平台的规则配置"""
        return self._platform_rules.get(platform_id)

    def get_threshold_overrides(self, platform_id: str) -> dict:
        """获取指定平台的阈值覆盖"""
        platform = self.get_platform(platform_id)
        if platform:
            return platform.get("threshold_overrides", {})
        return {}

    def get_additional_rules(self, platform_id: str) -> list[dict]:
        """获取指定平台的额外规则"""
        platform = self.get_platform(platform_id)
        if platform:
            return platform.get("additional_rules", [])
        return []

    def list_platforms(self) -> list[dict]:
        """列出所有可用平台"""
        return [
            {
                "id": pid,
                "name": pdata.get("name", pid),
                "rule_count": len(pdata.get("additional_rules", [])),
            }
            for pid, pdata in self._platform_rules.items()
        ]


platform_rule_engine = PlatformRuleEngine()
