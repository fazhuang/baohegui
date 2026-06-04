"""公共资源交易平台规则同步服务

功能：
1. 平台规则的 CRUD（增删改查）
2. 从 JSON / CSV / Excel 文件导入规则
3. 异步对接外部平台 API（含重试）
4. 从用户拦截反馈生成规则草稿
5. 规则版本追踪与差异比较
6. 启用/停用控制
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ── 数据模型 ────────────────────────────────────────────────

class PlatformRule(BaseModel):
    """平台规则"""
    rule_id: str
    platform: str
    platform_code: str
    rule_type: str = Field(..., pattern=r"^(chapter|keyword|forbidden|semantic|unknown)$")
    target: str = ""
    mandatory: bool = True
    description: str = ""
    version: str = "1.0"
    effective_date: str = ""
    enabled: bool = True
    category: str = "platform"  # base / platform / industry / custom / draft

    @field_validator("rule_id")
    @classmethod
    def validate_rule_id(cls, v: str) -> str:
        if not re.match(r"^[A-Z0-9_-]{3,32}$", v):
            raise ValueError(f"rule_id 格式无效: {v}")
        return v


class SyncResult(BaseModel):
    """同步结果"""
    total_rules: int = 0
    new_rules: int = 0
    updated_rules: int = 0
    disabled_rules: int = 0
    errors: list[str] = []


class RuleDiff(BaseModel):
    """规则差异"""
    rule_id: str
    local_version: str
    remote_version: str
    fields_changed: list[str] = []


# ── 服务 ────────────────────────────────────────────────────

class RuleSyncService:
    """规则同步服务"""

    # 模拟的外部平台 API
    MOCK_PLATFORMS: dict[str, list[dict]] = {
        "全国公共资源交易平台": [
            {"code": "NATL-001", "type": "chapter", "target": "章节完整性",
             "desc": "缺少规定章节", "mandatory": True},
            {"code": "NATL-003", "type": "keyword", "target": "采购方式",
             "desc": "采购方式缺失", "mandatory": True},
            {"code": "NATL-005", "type": "forbidden", "target": "地域歧视",
             "desc": "地域歧视条款", "mandatory": True},
            {"code": "NATL-007", "type": "forbidden", "target": "注册资金门槛",
             "desc": "注册资金作为资格条件", "mandatory": False},
            {"code": "NATL-009", "type": "semantic", "target": "评分标准合理性",
             "desc": "评分标准需符合公平原则", "mandatory": False},
        ],
        "广东省公共资源交易平台": [
            {"code": "GZPT-101", "type": "chapter", "target": "章节完整性",
             "desc": "招标文件缺少必备章节", "mandatory": True},
            {"code": "GZPT-102", "type": "keyword", "target": "采购方式",
             "desc": "未明确采购方式", "mandatory": True},
            {"code": "GZPT-103", "type": "keyword", "target": "评审标准",
             "desc": "评标办法中缺少评分标准", "mandatory": True},
            {"code": "GZPT-201", "type": "forbidden", "target": "指定品牌",
             "desc": "检测到指定品牌特征", "mandatory": True},
            {"code": "GZPT-202", "type": "forbidden", "target": "地域限制",
             "desc": "地域限制条款", "mandatory": False},
            {"code": "GZPT-301", "type": "semantic", "target": "排他性条款",
             "desc": "检测到排他性语义", "mandatory": True},
        ],
        "重庆市公共资源交易平台": [
            {"code": "CQPT-201", "type": "chapter", "target": "章节完整性",
             "desc": "章节缺失或为空", "mandatory": True},
            {"code": "CQPT-202", "type": "keyword", "target": "评审标准",
             "desc": "评审标准缺失", "mandatory": True},
            {"code": "CQPT-301", "type": "forbidden", "target": "指定品牌",
             "desc": "排他性条款", "mandatory": True},
            {"code": "CQPT-302", "type": "forbidden", "target": "独家授权",
             "desc": "独家授权排他性", "mandatory": False},
        ],
    }

    RULE_TYPE_MAP = {
        "chapter": "chapter",
        "keyword": "keyword",
        "forbidden": "forbidden",
        "semantic": "semantic",
    }

    def __init__(self, rules_dir: str | Path | None = None):
        if rules_dir:
            self.rules_dir = Path(rules_dir)
        else:
            # 自动探测路径
            self.rules_dir = (
                Path("/app/rules") if Path("/app").exists()
                else Path(__file__).resolve().parent.parent.parent.parent / "rules"
            )
        self.platform_rules_file = self.rules_dir / "platform_rules.json"
        self._rules_cache: list[PlatformRule] = []
        self._load_cache()

    # ── 加载 / 持久化 ──────────────────────────────────

    def _load_cache(self) -> None:
        if self.platform_rules_file.exists():
            with open(self.platform_rules_file, encoding="utf-8") as f:
                data = json.load(f)
                self._rules_cache = [
                    PlatformRule(**m) for m in data.get("mappings", [])
                ]
            logger.info("已加载 %d 条平台规则", len(self._rules_cache))

    def _save(self) -> None:
        data = {
            "version": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "mappings": [r.model_dump() for r in self._rules_cache],
        }
        self.platform_rules_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.platform_rules_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("已保存 %d 条平台规则至 %s", len(self._rules_cache), self.platform_rules_file)

    # ── 查询 ───────────────────────────────────────────

    def get_all_rules(self, enabled_only: bool = False) -> list[PlatformRule]:
        if enabled_only:
            return [r for r in self._rules_cache if r.enabled]
        return list(self._rules_cache)

    def get_rule(self, rule_id: str) -> Optional[PlatformRule]:
        for r in self._rules_cache:
            if r.rule_id == rule_id:
                return r
        return None

    def search_rules(self, keyword: str) -> list[PlatformRule]:
        kw = keyword.lower()
        return [
            r for r in self._rules_cache
            if kw in r.rule_id.lower()
            or kw in r.platform.lower()
            or kw in r.description.lower()
            or kw in r.target.lower()
        ]

    def get_rules_by_platform(self, platform: str) -> list[PlatformRule]:
        return [r for r in self._rules_cache if r.platform == platform]

    def get_platforms(self) -> list[str]:
        return sorted(set(r.platform for r in self._rules_cache))

    # ── CRUD ───────────────────────────────────────────

    def add_rule(self, data: dict) -> tuple[Optional[PlatformRule], Optional[str]]:
        """添加规则。返回 (rule, error)"""
        try:
            rule = PlatformRule(**data)
        except Exception as e:
            return None, str(e)

        # 检查重复
        if self.get_rule(rule.rule_id):
            return None, f"规则 {rule.rule_id} 已存在"

        self._rules_cache.append(rule)
        self._save()
        return rule, None

    def update_rule(self, rule_id: str, data: dict) -> tuple[Optional[PlatformRule], Optional[str]]:
        """更新规则。返回 (updated_rule, error)"""
        existing = self.get_rule(rule_id)
        if not existing:
            return None, f"规则 {rule_id} 不存在"

        # 不允许修改 rule_id
        data.pop("rule_id", None)

        updated = existing.model_copy(update=data)
        # 重新验证
        try:
            # 保持 rule_id 不变
            updated.rule_id = rule_id
            PlatformRule(**updated.model_dump())
        except Exception as e:
            return None, str(e)

        idx = next(i for i, r in enumerate(self._rules_cache) if r.rule_id == rule_id)
        self._rules_cache[idx] = updated
        self._save()
        return updated, None

    def delete_rule(self, rule_id: str) -> bool:
        existing = self.get_rule(rule_id)
        if not existing:
            return False
        self._rules_cache = [r for r in self._rules_cache if r.rule_id != rule_id]
        self._save()
        return True

    def toggle_rule(self, rule_id: str) -> Optional[bool]:
        """切换启用/停用，返回新的 enabled 状态"""
        existing = self.get_rule(rule_id)
        if not existing:
            return None
        existing.enabled = not existing.enabled
        self._save()
        return existing.enabled

    # ── 批量导入 ──────────────────────────────────────

    def import_rules(self, rules_data: list[dict]) -> SyncResult:
        """导入规则列表（批量）"""
        result = SyncResult()
        existing_ids = {r.rule_id for r in self._rules_cache}

        for item in rules_data:
            try:
                # 自动生成 rule_id（如果没有）
                if "rule_id" not in item or not item.get("rule_id"):
                    item["rule_id"] = self._generate_id(item)

                rule = PlatformRule(**item)
                if rule.rule_id in existing_ids:
                    result.updated_rules += 1
                    idx = next(
                        i for i, r in enumerate(self._rules_cache)
                        if r.rule_id == rule.rule_id
                    )
                    self._rules_cache[idx] = rule
                else:
                    result.new_rules += 1
                    self._rules_cache.append(rule)
                    existing_ids.add(rule.rule_id)
            except Exception as e:
                result.errors.append(f"导入 {item.get('rule_id', '?')} 失败: {e}")

        self._save()
        result.total_rules = len(self._rules_cache)
        return result

    # ── 外部同步（模拟） ──────────────────────────────

    def sync_from_platform(self, platform: str) -> SyncResult:
        """
        模拟从外部平台同步规则。
        对比内置的 MOCK_PLATFORMS 数据，新增和更新本地规则。
        """
        result = SyncResult()
        remote_rules = self.MOCK_PLATFORMS.get(platform, [])
        if not remote_rules:
            result.errors.append(f"未知平台: {platform}")
            return result

        existing_ids = {r.rule_id for r in self._rules_cache}
        local_platform_rules = {
            r.platform_code: r for r in self._rules_cache if r.platform == platform
        }

        for item in remote_rules:
            # 从平台名取拼音首字母作为前缀
            prefix_map = {"全国": "NATL", "广东": "GD", "重庆": "CQ"}
            pf = next((v for k, v in prefix_map.items() if k in platform), "EXT")
            rule_id = f"{pf}-{item['code']}"
            rule_data = {
                "rule_id": rule_id,
                "platform": platform,
                "platform_code": item["code"],
                "rule_type": self.RULE_TYPE_MAP.get(item["type"], "unknown"),
                "target": item.get("target", ""),
                "mandatory": item.get("mandatory", True),
                "description": item.get("desc", ""),
                "version": "1.0",
                "effective_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "enabled": True,
                "category": "platform",
            }

            try:
                rule = PlatformRule(**rule_data)
                if rule_id in existing_ids:
                    # 更新本地
                    lr = local_platform_rules.get(item["code"])
                    if lr:
                        idx = next(
                            i for i, r in enumerate(self._rules_cache)
                            if r.rule_id == rule_id
                        )
                        self._rules_cache[idx] = rule
                        result.updated_rules += 1
                else:
                    self._rules_cache.append(rule)
                    existing_ids.add(rule_id)
                    result.new_rules += 1
            except Exception as e:
                result.errors.append(f"同步 {rule_id} 失败: {e}")

        # 标记不在远端列表中的本地规则为禁用
        remote_codes = {r["code"] for r in remote_rules}
        for lr in self._rules_cache:
            if lr.platform == platform and lr.platform_code not in remote_codes:
                if lr.enabled:
                    lr.enabled = False
                    result.disabled_rules += 1

        self._save()
        result.total_rules = len(self._rules_cache)
        return result

    def get_diff(self, platform: str) -> list[RuleDiff]:
        """对比本地与远程规则的差异"""
        diffs: list[RuleDiff] = []
        remote_rules = self.MOCK_PLATFORMS.get(platform, {})
        local_by_code = {
            r.platform_code: r for r in self._rules_cache if r.platform == platform
        }

        for code, remote in remote_rules.items():
            local = local_by_code.get(code)
            if not local:
                continue
            changed: list[str] = []
            if local.version != "1.0":
                changed.append("version")
            if local.target != remote.get("target", ""):
                changed.append("target")
            if changed:
                diffs.append(RuleDiff(
                    rule_id=local.rule_id,
                    local_version=local.version,
                    remote_version="1.0",
                    fields_changed=changed,
                ))
        return diffs

    # ── 用户反馈创建规则草稿 ─────────────────────────

    def create_draft_from_feedback(
        self, platform: str, code: str, description: str
    ) -> Optional[PlatformRule]:
        """根据用户反馈创建规则草稿（已存在则返回 None）"""
        for r in self._rules_cache:
            if r.platform == platform and r.platform_code == code:
                return None

        rule_id = f"UFB-{hashlib.md5(f'{platform}{code}'.encode()).hexdigest()[:8].upper()}"
        rule = PlatformRule(
            rule_id=rule_id,
            platform=platform,
            platform_code=code,
            rule_type="unknown",
            target=description[:100],
            mandatory=True,
            description=description,
            version="draft",
            effective_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            enabled=False,
            category="draft",
        )
        self._rules_cache.append(rule)
        self._save()
        return rule

    # ── 工具 ───────────────────────────────────────────

    # ── 从文件导入 ──────────────────────────────────────

    async def sync_from_file(self, filepath: str | Path) -> SyncResult:
        """
        从 JSON / CSV 文件导入规则。

        JSON 格式：顶层为 mappings[] 数组或规则的 dict 列表。
        CSV 格式：首行为列名（rule_id, platform, platform_code, rule_type...）。
        """
        result = SyncResult()
        path = Path(filepath)
        if not path.exists():
            result.errors.append(f"文件不存在: {filepath}")
            return result

        try:
            if path.suffix.lower() == ".json":
                raw_data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw_data, dict):
                    items = raw_data.get("mappings", raw_data.get("rules", []))
                elif isinstance(raw_data, list):
                    items = raw_data
                else:
                    result.errors.append("JSON 格式不支持")
                    return result

            elif path.suffix.lower() == ".csv":
                items = []
                text = path.read_text(encoding="utf-8-sig")
                reader = csv.DictReader(io.StringIO(text))
                for row in reader:
                    # 下划线转驼峰（CSV 列名）
                    cleaned = {}
                    for k, v in row.items():
                        if k is None:
                            continue
                        key = k.strip().replace(" ", "_").lower()
                        # 映射到 PlatformRule 字段
                        field_map = {
                            "rule_id": "rule_id", "platform": "platform",
                            "platform_code": "platform_code", "rule_type": "rule_type",
                            "target": "target", "description": "description",
                            "version": "version", "effective_date": "effective_date",
                            "category": "category",
                            "mandatory": "mandatory", "enabled": "enabled",
                        }
                        mapped = field_map.get(key, key)
                        # 布尔转换
                        if v and v.lower() in ("true", "false"):
                            cleaned[mapped] = v.lower() == "true"
                        else:
                            cleaned[mapped] = v
                    if cleaned.get("rule_id") or cleaned.get("platform_code"):
                        items.append(cleaned)

            else:
                result.errors.append(f"不支持的格式: {path.suffix}（仅支持 .json 和 .csv）")
                return result

            if not items:
                result.errors.append("文件中未找到规则数据")
                return result

        except Exception as e:
            result.errors.append(f"文件解析失败: {e}")
            return result

        # 导入
        imported = self.import_rules(items)
        result.new_rules = imported.new_rules
        result.updated_rules = imported.updated_rules
        result.total_rules = imported.total_rules
        result.errors.extend(imported.errors)
        return result

    # ── 从 API 同步 ─────────────────────────────────────

    async def sync_from_api(
        self,
        api_url: str,
        api_key: str = "",
        platform_name: str = "",
    ) -> SyncResult:
        """
        从外部平台 API 拉取规则（HTTP GET + JSON 响应）。

        期望 API 返回格式：
          { "rules": [ { "code": "...", "type": "...", "desc": "...", ... } ] }
        或
          [ { "code": "...", "type": "...", ... } ]

        支持重试：最多 3 次，指数退避。
        """
        result = SyncResult()
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        last_error: Optional[str] = None
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(api_url, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()

                items: list[dict] = []
                if isinstance(data, dict):
                    raw = data.get("rules", data.get("data", []))
                    items = raw if isinstance(raw, list) else [data]
                elif isinstance(data, list):
                    items = data

                if not items:
                    result.errors.append("API 返回空规则列表")
                    return result

                # 映射到内部格式
                mapped: list[dict] = []
                for item in items:
                    mapped.append({
                        "rule_id": f"API-{item.get('code', item.get('id', f'UNKNOWN-{len(mapped)}'))}",
                        "platform": platform_name or item.get("platform", "外部平台"),
                        "platform_code": item.get("code", item.get("id", "")),
                        "rule_type": self.RULE_TYPE_MAP.get(
                            item.get("type", "unknown"), "unknown"
                        ),
                        "target": item.get("target", item.get("desc", "")),
                        "description": item.get("desc", item.get("description", "")),
                        "mandatory": item.get("mandatory", True),
                        "version": item.get("version", "1.0"),
                        "effective_date": item.get("effective_date",
                            datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                        "enabled": item.get("enabled", True),
                        "category": "platform",
                    })

                imported = self.import_rules(mapped)
                result.new_rules = imported.new_rules
                result.updated_rules = imported.updated_rules
                result.total_rules = imported.total_rules
                result.errors.extend(imported.errors)
                return result

            except httpx.TimeoutException:
                last_error = f"超时 (attempt {attempt}/3)"
                logger.warning("API 同步超时 (attempt %d/3)", attempt)
                if attempt < 3:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}"
                logger.warning("API 同步 HTTP 错误: %s", last_error)
                break  # HTTP 错误不重试
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.error("API 同步失败: %s", last_error)
                if attempt < 3:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)

        result.errors.append(f"API 同步失败: {last_error}")
        result.total_rules = len(self._rules_cache)
        return result

    # ── 从用户反馈 ──────────────────────────────────────

    async def sync_from_feedback(
        self, platform: str, code: str, description: str
    ) -> Optional[PlatformRule]:
        """
        从用户拦截反馈生成规则草稿（异步接口，与 sync_from_api 一致的调用风格）。

        当用户在上传/检查时遇到规则引擎未覆盖的平台拦截，
        可通过此方法提交反馈生成规则草稿，经管理员审核后启用。
        """
        return self.create_draft_from_feedback(platform, code, description)

    # ── 工具 ───────────────────────────────────────────────

    @staticmethod
    def _generate_id(item: dict) -> str:
        raw = f"{item.get('platform', '')}{item.get('platform_code', '')}"
        return f"AUTO-{hashlib.md5(raw.encode()).hexdigest()[:8].upper()}"

    def reload(self) -> None:
        """从磁盘重载"""
        self._load_cache()


# ═══════════════════════════════════════════════════════════════
# 规则版本管理器
# ═══════════════════════════════════════════════════════════════

class VersionSnapshot(BaseModel):
    """版本快照"""
    version: str
    timestamp: str
    rule_count: int
    change_log: str = ""
    rules: list[PlatformRule] = []


class RuleVersionManager:
    """
    规则版本管理器。

    功能：
    - 每次规则更新自动生成版本快照
    - 记录变更日志
    - 支持版本回滚
    - 保持最近 N 个版本历史
    - 可对比任意两个版本的差异
    """

    def __init__(self, max_versions: int = 10):
        self.max_versions = max_versions
        # 版本存储目录（与规则文件同目录）
        self._versions_dir = (
            rule_sync_service.rules_dir / "versions"
        )
        self._versions_dir.mkdir(parents=True, exist_ok=True)
        self._versions: list[VersionSnapshot] = []
        self._load_versions()

    # ── 持久化 ──────────────────────────────────────────

    def _versions_file(self, version: str) -> Path:
        return self._versions_dir / f"rules_{version}.json"

    def _manifest_file(self) -> Path:
        return self._versions_dir / "manifest.json"

    def _load_versions(self) -> None:
        """从 manifest 加载版本索引"""
        manifest = self._manifest_file()
        if manifest.exists():
            with open(manifest, encoding="utf-8") as f:
                data = json.load(f)
            self._versions = [VersionSnapshot(**v) for v in data.get("versions", [])]

    def _save_manifest(self) -> None:
        manifest = self._manifest_file()
        data = {
            "max_versions": self.max_versions,
            "versions": [v.model_dump() for v in self._versions],
        }
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 版本操作 ────────────────────────────────────────

    def snapshot(self, change_log: str = "") -> str:
        """
        对当前规则集创建版本快照。

        Args:
            change_log: 变更说明

        Returns:
            版本号（时间戳）
        """
        version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        rules = rule_sync_service.get_all_rules()

        snap = VersionSnapshot(
            version=version,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            rule_count=len(rules),
            change_log=change_log or f"规则更新 — {len(rules)} 条",
            rules=[r.model_copy() for r in rules],
        )

        # 写入快照文件
        with open(self._versions_file(version), "w", encoding="utf-8") as f:
            json.dump({
                "version": version,
                "timestamp": snap.timestamp,
                "change_log": snap.change_log,
                "rules": [r.model_dump() for r in snap.rules],
            }, f, ensure_ascii=False, indent=2)

        self._versions.append(snap)

        # 超出限制时删除最旧的
        while len(self._versions) > self.max_versions:
            old = self._versions.pop(0)
            old_file = self._versions_file(old.version)
            if old_file.exists():
                old_file.unlink()

        self._save_manifest()
        logger.info("版本快照 %s 已创建 (%d 条规则)", version, len(rules))
        return version

    def rollback(self, version: str) -> tuple[bool, str]:
        """
        回滚到指定版本。

        Args:
            version: 目标版本号

        Returns:
            (success: bool, message: str)
        """
        if version == "latest":
            target = self._versions[-1] if self._versions else None
        else:
            target = next(
                (v for v in self._versions if v.version == version), None
            )

        if not target:
            return False, f"版本 {version} 不存在"

        # 用目标版本的规则覆盖当前规则
        rule_sync_service._rules_cache = [r.model_copy() for r in target.rules]
        rule_sync_service._save()

        logger.info("已回滚至版本 %s (%s)", version, target.change_log)
        return True, f"已回滚至 {version} ({target.change_log})"

    def get_version(self, version: str) -> Optional[VersionSnapshot]:
        """获取指定版本的快照"""
        if version == "latest":
            return self._versions[-1] if self._versions else None
        return next(
            (v for v in self._versions if v.version == version), None
        )

    def list_versions(self) -> list[VersionSnapshot]:
        """列出所有历史版本（新→旧）"""
        return list(reversed(self._versions))

    def diff(self, v1: str, v2: str) -> list[dict]:
        """
        对比两个版本的规则差异。

        Returns:
            [{ "rule_id": "...", "status": "added|removed|changed",
               "field": "...", "old": ..., "new": ... }]
        """
        snap1 = self.get_version(v1)
        snap2 = self.get_version(v2)
        if not snap1 or not snap2:
            return []

        by_id1 = {r.rule_id: r for r in snap1.rules}
        by_id2 = {r.rule_id: r for r in snap2.rules}
        diffs: list[dict] = []

        all_ids = set(by_id1.keys()) | set(by_id2.keys())
        for rid in sorted(all_ids):
            r1 = by_id1.get(rid)
            r2 = by_id2.get(rid)
            if r1 and not r2:
                diffs.append({"rule_id": rid, "status": "removed"})
            elif r2 and not r1:
                diffs.append({"rule_id": rid, "status": "added"})
            else:
                changed = {}
                for field in ("platform", "rule_type", "target",
                              "description", "enabled", "mandatory"):
                    v1v = getattr(r1, field, None)
                    v2v = getattr(r2, field, None)
                    if v1v != v2v:
                        changed[field] = {"old": v1v, "new": v2v}
                if changed:
                    diffs.append({
                        "rule_id": rid, "status": "changed",
                        "fields": changed,
                    })

        return diffs


# ═══════════════════════════════════════════════════════════════
# 模块单例
# ═══════════════════════════════════════════════════════════════

rule_sync_service = RuleSyncService()
rule_version_manager = RuleVersionManager()
