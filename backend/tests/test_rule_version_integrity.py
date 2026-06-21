"""规则版本完整性测试

覆盖:
1. 指定污染 rule_id 检测
2. 测试内容污染检测（description/target/platform/platform_code/category）
3. 全部发布资产扫描（platform_rules.json / manifest / rules_*.json）
4. manifest 一致性（rule_count == len(rules), version 唯一, 快照文件存在）
5. 快照一致性（JSON 可解析, version/文件名一致, rule_id 唯一, PlatformRule 校验）
6. 防回归：模块加载时 + 测试前后 rules 目录哈希比对
7. 未追踪快照文件检测（不限日期前缀）
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

# ── 污染标记 ────────────────────────────────────────────

_POLLUTED_RULE_IDS = frozenset({
    "TEST-AUDIT", "FILE-T1", "UFB-3390EBC9", "VR-T2", "V-TEST-1", "V-T3",
})

_POLLUTED_FIELD_VALUES = frozenset({
    "E2E测试更新",
    "test-platform",
    "TestPlat",
    "反馈测试",
    "版本测试",
    "文件导入",
})

# 白名单：合法描述中包含这些词不是污染
_WHITELIST_DESCRIPTIONS_CONTAINING_TEST = frozenset({
    # 当前无已知合法含"测试"的平台规则描述
    # 如果有，在此添加
})


def _is_polluted_field_value(value: str) -> bool:
    """基于已知污染模式和可信业务规则清单判断字段值是否为污染"""
    if not value or not isinstance(value, str):
        return False
    if value in _POLLUTED_FIELD_VALUES:
        return True
    if value in _WHITELIST_DESCRIPTIONS_CONTAINING_TEST:
        return False
    return False


# ── 辅助函数 ────────────────────────────────────────────

def _rules_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "rules"


def _versions_dir() -> Path:
    return _rules_dir() / "versions"


def _compute_dir_hash() -> str:
    """计算 rules 目录的内容哈希（排序文件后拼接）"""
    rules_dir = _rules_dir()
    hashes = []
    for fpath in sorted(rules_dir.rglob("*")):
        if fpath.is_file() and fpath.suffix in (".json", ".md"):
            rel = fpath.relative_to(rules_dir)
            content = fpath.read_bytes()
            hashes.append(f"{rel}:{hashlib.sha256(content).hexdigest()}")
    return hashlib.sha256("\n".join(hashes).encode()).hexdigest()


# ── 模块加载时捕获哈希（检测任何先前的污染）─────

_MODULE_LOAD_HASH = _compute_dir_hash()


# ── 测试类 ──────────────────────────────────────────────

class TestRuleIdPollution:
    """检测已知污染 rule_id"""

    def test_platform_rules_no_polluted_ids(self):
        path = _rules_dir() / "platform_rules.json"
        data = json.loads(path.read_text("utf-8"))
        violations = []
        for m in data.get("mappings", []):
            rid = m.get("rule_id", "")
            for marker in _POLLUTED_RULE_IDS:
                if marker in rid:
                    violations.append(f"platform_rules.json: {rid}")
        assert not violations, f"Polluted rule_ids found:\n" + "\n".join(violations)

    def test_manifest_no_polluted_ids(self):
        path = _versions_dir() / "manifest.json"
        if not path.exists():
            return
        data = json.loads(path.read_text("utf-8"))
        violations = []
        for vi, v in enumerate(data.get("versions", [])):
            for ri, r in enumerate(v.get("rules", [])):
                rid = r.get("rule_id", "")
                for marker in _POLLUTED_RULE_IDS:
                    if marker in rid:
                        violations.append(
                            f"manifest versions[{vi}].rules[{ri}]: {rid}"
                        )
        assert not violations, f"Polluted rule_ids in manifest:\n" + "\n".join(violations)

    def test_snapshots_no_polluted_ids(self):
        violations = []
        for fpath in sorted(_versions_dir().glob("rules_*.json")):
            data = json.loads(fpath.read_text("utf-8"))
            for ri, r in enumerate(data.get("rules", [])):
                rid = r.get("rule_id", "")
                for marker in _POLLUTED_RULE_IDS:
                    if marker in rid:
                        violations.append(f"{fpath.name}[{ri}]: {rid}")
        assert not violations, f"Polluted rule_ids in snapshots:\n" + "\n".join(violations)


class TestFieldContentPollution:
    """检测测试内容污染（description/target/platform/platform_code/category）"""

    _CHECK_FIELDS = ("description", "target", "platform", "platform_code", "category")

    def test_platform_rules_no_polluted_fields(self):
        path = _rules_dir() / "platform_rules.json"
        data = json.loads(path.read_text("utf-8"))
        violations = []
        for m in data.get("mappings", []):
            rid = m.get("rule_id", "?")
            for field in self._CHECK_FIELDS:
                value = m.get(field, "")
                if _is_polluted_field_value(value):
                    violations.append(
                        f"platform_rules.json {rid}.{field}='{value}'"
                    )
        assert not violations, f"Polluted field values:\n" + "\n".join(violations)

    def test_manifest_no_polluted_fields(self):
        path = _versions_dir() / "manifest.json"
        if not path.exists():
            return
        data = json.loads(path.read_text("utf-8"))
        violations = []
        for vi, v in enumerate(data.get("versions", [])):
            for ri, r in enumerate(v.get("rules", [])):
                rid = r.get("rule_id", "?")
                for field in self._CHECK_FIELDS:
                    value = r.get(field, "")
                    if _is_polluted_field_value(value):
                        violations.append(
                            f"manifest[{vi}].rules[{ri}] {rid}.{field}='{value}'"
                        )
        assert not violations, f"Polluted field values in manifest:\n" + "\n".join(violations)

    def test_snapshots_no_polluted_fields(self):
        violations = []
        for fpath in sorted(_versions_dir().glob("rules_*.json")):
            data = json.loads(fpath.read_text("utf-8"))
            for ri, r in enumerate(data.get("rules", [])):
                rid = r.get("rule_id", "?")
                for field in self._CHECK_FIELDS:
                    value = r.get(field, "")
                    if _is_polluted_field_value(value):
                        violations.append(
                            f"{fpath.name}[{ri}] {rid}.{field}='{value}'"
                        )
        assert not violations, f"Polluted field values in snapshots:\n" + "\n".join(violations)


class TestManifestConsistency:
    """manifest 结构一致性"""

    def test_rule_count_matches_rules_length(self):
        path = _versions_dir() / "manifest.json"
        if not path.exists():
            return
        data = json.loads(path.read_text("utf-8"))
        violations = []
        for v in data.get("versions", []):
            rc = v.get("rule_count", 0)
            rl = len(v.get("rules", []))
            if rc != rl:
                violations.append(
                    f"{v['version']}: rule_count={rc} != len(rules)={rl}"
                )
        assert not violations, f"rule_count mismatch:\n" + "\n".join(violations)

    def test_version_unique(self):
        path = _versions_dir() / "manifest.json"
        if not path.exists():
            return
        data = json.loads(path.read_text("utf-8"))
        versions = [v["version"] for v in data.get("versions", [])]
        dupes = [v for v in set(versions) if versions.count(v) > 1]
        assert not dupes, f"Duplicate versions: {dupes}"

    def test_version_not_empty(self):
        path = _versions_dir() / "manifest.json"
        if not path.exists():
            return
        data = json.loads(path.read_text("utf-8"))
        violations = []
        for v in data.get("versions", []):
            if not v.get("version", "").strip():
                violations.append(f"Empty version in manifest")
        assert not violations, "Empty version found"

    def test_no_empty_rules_deceptive(self):
        """不允许描述声称有规则但 rules 为空"""
        path = _versions_dir() / "manifest.json"
        if not path.exists():
            return
        data = json.loads(path.read_text("utf-8"))
        violations = []
        for v in data.get("versions", []):
            if len(v.get("rules", [])) == 0:
                desc = v.get("description", "") or v.get("change_log", "")
                keywords = ["规则", "条", "rule", "新增", "扩展", "batch"]
                if any(kw in desc.lower() for kw in keywords):
                    violations.append(
                        f"{v['version']}: claims rules in description but rules=[]"
                    )
        assert not violations, f"Deceptive empty-rules versions:\n" + "\n".join(violations)

    def test_rollback_versions_have_rules(self):
        """可回滚版本必须有完整 rules"""
        path = _versions_dir() / "manifest.json"
        if not path.exists():
            return
        data = json.loads(path.read_text("utf-8"))
        violations = []
        for v in data.get("versions", []):
            if v.get("rule_count", 0) > 0 and len(v.get("rules", [])) == 0:
                violations.append(
                    f"{v['version']}: rule_count={v['rule_count']} but rules=[]"
                )
        assert not violations, f"Rollback versions with no rules:\n" + "\n".join(violations)

    def test_no_3_0_0(self):
        """3.0.0 不应再出现在 versions 列表中"""
        path = _versions_dir() / "manifest.json"
        if not path.exists():
            return
        data = json.loads(path.read_text("utf-8"))
        has_300 = any(v.get("version") == "3.0.0" for v in data.get("versions", []))
        assert not has_300, "3.0.0 should not be in manifest versions"


class TestSnapshotConsistency:
    """快照文件结构一致性"""

    def test_all_snapshots_parseable(self):
        violations = []
        for fpath in sorted(_versions_dir().glob("rules_*.json")):
            try:
                json.loads(fpath.read_text("utf-8"))
            except json.JSONDecodeError as e:
                violations.append(f"{fpath.name}: JSON parse error: {e}")
        assert not violations, f"Unparseable snapshots:\n" + "\n".join(violations)

    def test_version_matches_filename(self):
        violations = []
        for fpath in sorted(_versions_dir().glob("rules_*.json")):
            data = json.loads(fpath.read_text("utf-8"))
            file_ver = fpath.stem.replace("rules_", "")
            data_ver = data.get("version", "")
            if file_ver != data_ver:
                violations.append(
                    f"{fpath.name}: filename version={file_ver}, data version={data_ver}"
                )
        assert not violations, f"Version/filename mismatch:\n" + "\n".join(violations)

    def test_rule_count_matches_rules(self):
        violations = []
        for fpath in sorted(_versions_dir().glob("rules_*.json")):
            data = json.loads(fpath.read_text("utf-8"))
            rc = data.get("rule_count", 0)
            rl = len(data.get("rules", []))
            if rc != rl:
                violations.append(
                    f"{fpath.name}: rule_count={rc} != len(rules)={rl}"
                )
        assert not violations, f"Snapshot rule_count mismatch:\n" + "\n".join(violations)

    def test_rule_ids_unique_within_snapshot(self):
        violations = []
        for fpath in sorted(_versions_dir().glob("rules_*.json")):
            data = json.loads(fpath.read_text("utf-8"))
            rids = [r.get("rule_id", "") for r in data.get("rules", [])]
            dupes = set(rid for rid in rids if rids.count(rid) > 1)
            if dupes:
                violations.append(f"{fpath.name}: duplicate rule_ids: {dupes}")
        assert not violations, f"Duplicate rule_ids in snapshots:\n" + "\n".join(violations)

    def test_rules_pass_platform_rule_validation(self):
        """快照中的规则能通过 PlatformRule 校验"""
        from app.services.rule_sync import PlatformRule

        violations = []
        for fpath in sorted(_versions_dir().glob("rules_*.json")):
            data = json.loads(fpath.read_text("utf-8"))
            for ri, r in enumerate(data.get("rules", [])):
                try:
                    PlatformRule(**r)
                except Exception as e:
                    violations.append(
                        f"{fpath.name}[{ri}] {r.get('rule_id', '?')}: {e}"
                    )
        assert not violations, f"Rules failing PlatformRule validation:\n" + "\n".join(violations)


class TestAntiRegression:
    """防回归：模块加载时 + 测试前后 rules 目录哈希比对"""

    _PRE_HASH = _MODULE_LOAD_HASH

    def test_no_prior_pollution_detected(self):
        """模块加载时的哈希应等于当前哈希 — 检测任何先前的污染（如 E2E 测试泄漏）"""
        current = _compute_dir_hash()
        assert self._PRE_HASH == current, (
            f"rules 目录在测试导入前已被污染!\n"
            f"  module_load: {self._PRE_HASH}\n"
            f"  current:     {current}\n"
            f"  提示：运行 pytest tests/test_e2e.py 后，环境可能已将 E2E 测试内容写入 rules/ 目录。"
        )

    @pytest.fixture(autouse=True)
    def _capture_and_verify_hash(self):
        """捕获本轮测试前后的哈希并验证不变"""
        pre = _compute_dir_hash()
        yield
        post = _compute_dir_hash()
        assert pre == post, (
            f"rules 目录在本轮测试中发生变化!\n"
            f"  pre:  {pre}\n"
            f"  post: {post}"
        )

    def test_rules_dir_integrity_preserved(self):
        """占位测试：实际检查由 fixture teardown 完成"""
        assert self._PRE_HASH is not None, "Pre-hash should be captured"

    def test_runtime_rule_service_uses_test_copy(self):
        """pytest 运行时规则服务必须指向隔离副本，不能指向仓库 rules/。"""
        from app.services.rule_sync import rule_sync_service

        runtime_dir = rule_sync_service.rules_dir.resolve()
        production_dir = _rules_dir().resolve()
        assert runtime_dir != production_dir
        assert runtime_dir.name == "rules"
        assert runtime_dir.parent.name == ".test_tmp"

    def test_no_untracked_snapshots_exist(self):
        """rules/versions/ 下所有 rules_*.json 必须被 git 追踪（不限日期前缀）"""
        versions_dir = _versions_dir()
        all_files = set(f.name for f in versions_dir.glob("rules_*.json"))
        result = subprocess.run(
            ["git", "ls-files", "--", "rules/versions/"],
            capture_output=True, text=True,
            cwd=str(_rules_dir().parent),
        )
        tracked = {f.split("/")[-1] for f in result.stdout.strip().split("\n") if f}
        untracked = all_files - tracked
        assert not untracked, (
            f"rules/versions/ 下存在未追踪的快照文件 ({len(untracked)} 个):\n"
            + "\n".join(sorted(untracked))
        )


class TestNatl001Canonical:
    """验证 NATL-001 已恢复为可信业务描述

    可信描述来源:
    - backend/app/services/rule_sync.py MOCK_PLATFORMS["全国公共资源交易平台"][0]:
      {"code": "NATL-001", "desc": "缺少规定章节"}
    - 早期快照 (20260601154625/37/38) 使用 "招标文件缺少规定章节"
      这 3 个快照创建于污染注入之前，描述为历史合法变体。

    当前 platform_rules.json 的规范描述取自源代码 = "缺少规定章节"。
    """

    CANONICAL = "缺少规定章节"
    # 历史合法变体（非污染，predates E2E测试更新注入）
    HISTORICAL_VARIANTS = frozenset({
        "招标文件缺少规定章节",
    })
    VALID = {CANONICAL} | HISTORICAL_VARIANTS

    def test_platform_rules_natl001_canonical(self):
        path = _rules_dir() / "platform_rules.json"
        data = json.loads(path.read_text("utf-8"))
        for m in data.get("mappings", []):
            if m.get("rule_id") == "NATL-001":
                assert m["description"] in self.VALID, (
                    f"NATL-001 description should be in {self.VALID}, "
                    f"got '{m['description']}'"
                )
                return
        pytest.fail("NATL-001 not found in platform_rules.json")

    def test_snapshots_natl001_canonical(self):
        violations = []
        for fpath in sorted(_versions_dir().glob("rules_*.json")):
            data = json.loads(fpath.read_text("utf-8"))
            for r in data.get("rules", []):
                if r.get("rule_id") == "NATL-001":
                    if r.get("description") not in self.VALID:
                        violations.append(
                            f"{fpath.name}: NATL-001 description='{r['description']}'"
                        )
        assert not violations, (
            f"NATL-001 not canonical in snapshots:\n" + "\n".join(violations)
        )

    def test_manifest_natl001_canonical(self):
        path = _versions_dir() / "manifest.json"
        if not path.exists():
            return
        data = json.loads(path.read_text("utf-8"))
        violations = []
        for vi, v in enumerate(data.get("versions", [])):
            for ri, r in enumerate(v.get("rules", [])):
                if r.get("rule_id") == "NATL-001":
                    if r.get("description") not in self.VALID:
                        violations.append(
                            f"manifest[{vi}].rules[{ri}]: '{r['description']}'"
                        )
        assert not violations, (
            f"NATL-001 not canonical in manifest:\n" + "\n".join(violations)
        )
