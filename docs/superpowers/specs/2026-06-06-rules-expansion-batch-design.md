# 规则库扩展 — 方案 A 分批评审设计

> 日期：2026-06-06
> 状态：设计已确认
> 父文档：2026-06-05-baohegui-comprehensive-upgrade-design.md

## 一、目标

将规则库从当前 35 条扩展到 ~82 条，分三批交付，每批独立可测试、可上线。

## 二、当前状态

| 维度 | 现状 | 目标 |
|------|------|------|
| 合规规则数 | 35条 | 82条 |
| 覆盖采购类型 | 通用型为主 | 工程建设 + IT设备 + 服务类 |
| 条件规则 | 8条 | ~18条（精准触发） |
| 案例驱动规则 | 0条 | 12条（有真实投诉案例背书） |

现有规则库与 hlgs 核心规则 ID 完全对齐（R001-R206），另有 baohegui 独有4条（R108_C, R109_C, R111_B, R112_B）。

## 三、Schema

所有规则遵循 `compliance_rules.json` 现有 Schema，新增字段无。规则结构示例：

```json
{
  "rule_id": "R401",
  "rule_name": "施工资质等级与项目规模匹配",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "condition": "project_type == '工程'",
  "forbidden_pattern": "(?:三级资质.*5000万|二级资质.*2亿|一级资质.*10亿)",
  "forbidden_message": "资质等级与项目规模不匹配",
  "message": "资质等级应与项目预算规模相匹配",
  "risk_level": "critical",
  "regulation_basis": [{"title": "建筑业企业资质管理规定", "article": ""}],
  "suggestion": "调整资质等级要求，或在新规允许范围内说明不按新规执行的原因",
  "example_bad": "",
  "example_good": ""
}
```

## 四、分批计划

### Batch 1：移植 hlgs 通报资产规则（12条 → 累计 47条）

**来源**：hlgs `config/rules/*.json` 中 `R_AUTO_*` 前缀的自动采集规则，全部来自甘肃省政府采购网真实投诉案例。

**适配要点**：
- 重编号为 R301 ~ R312
- 补齐 `rule_type`（从违规内容推理为 `forbidden_pattern` 或 `semantic_required`）
- 补齐 `field`（从案例内容推断目标章节）
- `risk_level` 中文转英文
- 补充 `example_bad` / `example_good`

**规则明细**：

| 新ID | hlgs来源 | 违规类型 | 目标字段 | 风险等级 |
|------|---------|---------|---------|---------|
| R301 | R_AUTO_D1F457 | 特定厂家授权作为资格条件 | qualification_requirements | high |
| R302 | R_AUTO_183A66 | 妨碍统一市场公平竞争 | qualification_requirements | medium |
| R303 | R_AUTO_EB5AFC | 提供虚假材料谋取中标 | qualification_requirements | medium |
| R304 | R_AUTO_A866C3 | 串通投标行为 | qualification_requirements | high |
| R305 | R_AUTO_1476DF | 违规收取未列明服务费 | bid_rejection_conditions | medium |
| R306 | R_AUTO_67C6E3 | 排他性技术参数（医疗设备） | technical_params | medium |
| R307 | R_AUTO_C15A5C | 要求当地分支机构证明 | qualification_requirements | medium |
| R308 | R_AUTO_9464A4 | 串通投标+评标标准畸高 | scoring_criteria | high |
| R309 | R_AUTO_490C98 | 无正当理由拒签合同 | qualification_requirements | medium |
| R310 | R_AUTO_D9B29E | 测试违规案例（通用排他） | technical_params | medium |
| R311 | R_AUTO_FDE74A | 代理机构违规收费 | bid_rejection_conditions | medium |
| R312 | R_AUTO_1B154E | 违规转包 | bid_rejection_conditions | medium |

### Batch 2：行业专项规则（25条 → 累计 72条）

按最高频采购场景补充行业专属规则，每条带 `condition` 表达式精准触发。

**工程建设（10条，R401-R410）**：

| ID | 规则名 | 条件 | 规则类型 | 风险 |
|----|--------|------|---------|------|
| R401 | 施工资质等级与项目规模匹配 | `project_type == '工程'` | forbidden_pattern | critical |
| R402 | 项目经理不得有在建工程 | `project_type == '工程'` | forbidden_pattern | high |
| R403 | 安全生产许可证必须有效 | `project_type == '工程'` | required | critical |
| R404 | 工期要求不得低于合理工期 | `project_type == '工程'` | numeric_range | medium |
| R405 | 履约保证金比例不得超10% | `project_type == '工程'` | numeric_range | medium |
| R406 | 工程量清单须完整无缺项 | `project_type == '工程'` | pattern_required | high |
| R407 | 不得指定主要建材品牌 | `project_type == '工程'` | forbidden_pattern | critical |
| R408 | 项目经理业绩要求须合理 | `project_type == '工程'` | forbidden_pattern | medium |
| R409 | 联合体各方须满足相应资质 | `project_type == '工程'` | conditional | medium |
| R410 | 安全文明施工费须单独列明 | `project_type == '工程'` | required | high |

**IT 设备采购（8条，R501-R508）**：

| ID | 规则名 | 条件 | 规则类型 | 风险 |
|----|--------|------|---------|------|
| R501 | 技术参数不得指定芯片型号 | `project_type == '采购'` | forbidden_pattern | critical |
| R502 | 不得要求整机原厂认证 | `project_type == '采购'` | forbidden_pattern | high |
| R503 | 软件授权不得排他 | `project_type == '采购'` | forbidden_pattern | high |
| R504 | 兼容性要求须有至少3家满足 | `project_type == '采购'` | semantic_required | high |
| R505 | 质保期要求须合理 | `project_type == '采购'` | numeric_range | medium |
| R506 | 国产化要求须有政策依据 | `project_type == '采购'` | forbidden_pattern | medium |
| R507 | 不得要求特定测试机构报告 | `project_type == '采购'` | forbidden_pattern | high |
| R508 | 功能参数须可量化验证 | `project_type == '采购'` | pattern_required | medium |

**服务类（7条，R601-R607）**：

| ID | 规则名 | 条件 | 规则类型 | 风险 |
|----|--------|------|---------|------|
| R601 | 人员配置数量须与项目规模匹配 | `project_type == '服务'` | forbidden_pattern | medium |
| R602 | 业绩数量要求不得超过项目规模 | `project_type == '服务'` | numeric_range | high |
| R603 | 本地化服务不得作为资格条件 | `project_type == '服务'` | forbidden_pattern | critical |
| R604 | 服务方案评分须量化 | `project_type == '服务'` | forbidden_pattern | high |
| R605 | 不得要求特定认证体系 | `project_type == '服务'` | forbidden_pattern | medium |
| R606 | 服务期限须合理 | `project_type == '服务'` | numeric_range | low |
| R607 | 不得要求派驻人员特定学历 | `project_type == '服务'` | forbidden_pattern | medium |

### Batch 3：条件变体规则（10条 → 累计 82条）

为现有高频规则添加采购方式触发的变体版本：

| ID | 规则名 | 条件 | 来源 | 风险 |
|----|--------|------|------|------|
| R114_C | 询价采购须至少3家报价 | `evaluation_method == '询价'` | 变体自R005 | high |
| R115_C | 竞争性谈判须有谈判记录 | `evaluation_method == '竞争性谈判'` | 变体自R010 | medium |
| R116_C | 单一来源须有专家论证 | `evaluation_method == '单一来源'` | 变体自R001 | critical |
| R117_C | 邀请招标须有邀请理由说明 | `evaluation_method == '邀请招标'` | 新建 | high |
| R118_C | 竞争性磋商须有磋商纪要 | `evaluation_method == '竞争性磋商'` | 新建 | medium |
| R119_B | 价格分权重须符合法定范围 | `evaluation_method IN ['综合评分法']` | 变体自R208 | high |
| R120_B | 资格条件不得作为评分因素 | `evaluation_method IN ['综合评分法']` | 新建 | critical |
| R121_A | 中小企业须有预留份额说明 | `budget >= 2000000` | 新建 | medium |
| R122_C | 投标保证金不得超过预算2% | 无（通用） | 新建 | medium |
| R123_D | 中标公示须包含评审专家名单 | 无（通用） | 新建 | medium |

## 五、同步扩展

### 禁用词库扩展

对应新增规则补充禁用词模式，`rules/forbidden_words.json` 新增：
- `construction_bias` — 工程建设排他模式（指定建材品牌、特定施工工艺等）
- `it_spec_lock` — IT 参数锁定模式（芯片型号、固件版本、特定协议等）
- `service_restrict` — 服务限制模式（本地化门槛、特定认证、学历锁定等）

### 参数倾向性规则扩展

`rules/parameter_bias_rules.json` 新增模式：
- `construction_exclusivity` — 工程建设参数排他
- `it_brand_lock` — IT 品牌锁定（通过组合参数）
- `service_cert_lock` — 服务认证排他

## 六、测试策略

- 每条新规则至少 1 个正例（应命中）+ 1 个反例（不应命中）
- 条件规则覆盖条件边界（满足 / 不满足 condition）
- 回归测试：新增规则后运行 `uv run pytest tests/test_rule_engine.py` 确保现有规则不受影响
- Batch 完成后运行全量测试 `uv run pytest -v`

## 七、交付物

| 批次 | 文件 | 规则数 | 累计 |
|------|------|--------|------|
| Batch 1 | `rules/compliance_rules.json` | +12 | 47 |
| Batch 2 | `rules/compliance_rules.json` | +25 | 72 |
| Batch 3 | `rules/compliance_rules.json` | +10 | 82 |
| - | `rules/forbidden_words.json` | 同步扩展 | - |
| - | `rules/parameter_bias_rules.json` | 同步扩展 | - |
| - | `backend/tests/test_rule_engine.py` | 新增测试用例 | - |

目标最终规则数：**82 条**。
