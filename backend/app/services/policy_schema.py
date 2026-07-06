"""Policy data schemas — 严格 Pydantic 模型验证 policy_data

严禁仅检查 "是否为 JSON 对象"。
所有 policy_data 在 create_draft、apply、loader 三个阶段均需通过 schema 验证。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from app.core.policy_kernel import RuleType


# ═══════════════════════════════════════════════════════════════
# Tenant policy schema
# ═══════════════════════════════════════════════════════════════

class TenantPolicyData(BaseModel, extra="forbid"):
    """租户策略数据 — 仅包含当前真实支持的字段。

    extra="forbid": 任何未知字段均拒绝。
    """
    suppressed_rule_ids: list[str] = Field(
        default_factory=list,
        description="抑制的规则 ID 列表（精确豁免）",
    )
    auto_fail_rule_types: list[RuleType] = Field(
        default_factory=list,
        description="直接 BLOCK 的规则类型",
    )


# ═══════════════════════════════════════════════════════════════
# Platform policy schema
# ═══════════════════════════════════════════════════════════════

class PlatformPolicyData(BaseModel, extra="forbid"):
    """平台策略数据 — 仅包含当前真实支持的字段。

    extra="forbid": 任何未知字段均拒绝。
    """
    required_sections: list[str] = Field(
        default_factory=list,
        description="平台额外要求的章节列表（只能增加，不能删除内置要求）",
    )


# ═══════════════════════════════════════════════════════════════
# Policy type → schema mapping
# ═══════════════════════════════════════════════════════════════

_POLICY_TYPE_SCHEMA: dict[str, type[BaseModel]] = {
    "tenant": TenantPolicyData,
    "platform": PlatformPolicyData,
}

# Only these policy types are currently wired into the execution chain.
# ux is NOT wired — reject at creation time.
_SUPPORTED_POLICY_TYPES = frozenset({"tenant", "platform"})


def validate_policy_data(policy_type: str, policy_data_str: str) -> BaseModel:
    """验证并规范化 policy_data — 所有阶段调用的单一校验入口。

    Returns: 验证通过后的 Pydantic 模型实例
    Raises:  ValueError — 非法 policy_type、非 JSON、schema 不匹配、未知字段、未知枚举值
    """
    import json as _json

    if policy_type not in _SUPPORTED_POLICY_TYPES:
        raise ValueError(
            f"不支持的 policy_type: {policy_type!r}。"
            f"当前支持: {sorted(_SUPPORTED_POLICY_TYPES)}"
        )

    try:
        raw = _json.loads(policy_data_str)
    except (_json.JSONDecodeError, TypeError) as e:
        raise ValueError(f"policy_data JSON 解析失败: {e}")

    if not isinstance(raw, dict):
        raise ValueError("policy_data 必须是 JSON 对象")

    schema_cls = _POLICY_TYPE_SCHEMA[policy_type]
    try:
        return schema_cls.model_validate(raw)
    except ValidationError as e:
        raise ValueError(f"policy_data schema 验证失败 ({policy_type}): {e}")


def normalize_policy_data(policy_type: str, policy_data_str: str) -> str:
    """验证并规范化为确定性 JSON 字符串。"""
    import json as _json

    validated = validate_policy_data(policy_type, policy_data_str)
    return _json.dumps(validated.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


def is_supported_policy_type(policy_type: str) -> bool:
    """检查 policy_type 是否被当前执行链支持。"""
    return policy_type in _SUPPORTED_POLICY_TYPES


# ═══════════════════════════════════════════════════════════════
# Effective policy builders — check.py 与测试共享的单一实现
# ═══════════════════════════════════════════════════════════════

def build_effective_tenant_policy(base, applied_policies):
    """从 base TenantPolicy 和 applied DynamicPolicy 记录构建有效租户策略。

    这是 check.py 与测试共享的唯一合并实现。禁止测试复制一份模拟合并算法。

    无效/历史非法 policy_data → 记录错误日志并跳过，从不静默部分解析。
    """
    import logging
    from app.core.policy_kernel import TenantPolicy

    logger = logging.getLogger(__name__)
    tp = base.model_copy(deep=True)

    for dp in applied_policies:
        try:
            validated = validate_policy_data("tenant", dp.policy_data)
        except ValueError as e:
            logger.error(
                "跳过非法 applied tenant policy: id=%d key=%s error=%s",
                dp.id, dp.policy_key, e,
            )
            continue

        data = TenantPolicyData.model_validate(validated.model_dump())
        if data.suppressed_rule_ids:
            tp.suppressed_rule_ids.update(data.suppressed_rule_ids)
        if data.auto_fail_rule_types:
            for rt in data.auto_fail_rule_types:
                tp.auto_fail_rule_types.add(rt)

    return tp


def build_effective_platform_policy(base, applied_policies):
    """从 base PlatformPolicy 和 applied DynamicPolicy 记录构建有效平台策略。

    只能增加 required_sections，不能删除内置要求。
    """
    import logging
    from app.core.policy_kernel import PlatformPolicy

    logger = logging.getLogger(__name__)
    pp = base.model_copy(deep=True)

    for dp in applied_policies:
        try:
            validated = validate_policy_data("platform", dp.policy_data)
        except ValueError as e:
            logger.error(
                "跳过非法 applied platform policy: id=%d key=%s error=%s",
                dp.id, dp.policy_key, e,
            )
            continue

        data = PlatformPolicyData.model_validate(validated.model_dump())
        if data.required_sections:
            for s in data.required_sections:
                if isinstance(s, str) and s.strip():
                    pp.required_sections.add(s.strip())

    return pp
