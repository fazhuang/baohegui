# 包合规 - 规则库维护文档

## 规则文件结构

```
rules/
├── base_rules.json          # 基础法规规则
├── platform_rules.json      # 平台规则映射
├── forbidden_words.json     # 禁用词库
├── industry/                 # 行业细分规则
│   ├── construction.json    # 建筑行业
│   ├── healthcare.json      # 医疗行业
│   └── it.json              # 信息化行业
└── prompts/                  # LLM Prompt 模板
    └── compliance_check.txt # 合规审查 Prompt
```

## 规则类型

| 类型 | 说明 | 来源 | 更新频率 |
|------|------|------|----------|
| chapter_required | 必备章节检查 | 《政府采购法》《招标投标法》 | 1-2年 |
| keyword_required | 必备关键字检查 | 《政府采购法实施条例》 | 1-2年 |
| forbidden | 禁用词检查 | 财政部执法实践 | 按需 |
| semantic | 语义审查（AI） | 《政府采购法》/行业标准 | 按需 |

## 规则结构

```json
{
  "id": "SEC-001",
  "type": "chapter_required",
  "target": "评标办法",
  "weight": 30,
  "description": "缺少《评标办法》章节",
  "law_ref": "《政府采购法实施条例》第三十四条",
  "suggestion": "请补充《评标办法》章节...",
  "category": "base",
  "enabled": true,
  "version": "1.0"
}
```

## 平台规则映射

```json
{
  "rule_id": "SEC-CGH-001",
  "platform_rules": [
    { "platform": "广东省公共资源交易平台", "code": "GZPT-101", "desc": "..." },
    { "platform": "重庆市公共资源交易平台", "code": "CQPT-201", "desc": "..." }
  ]
}
```

## 维护流程

1. 法规更新 → 人工审核 → 修改 JSON 规则文件
2. 平台规则变更 → 同步后自动/人工导入
3. 用户反馈 → 生成规则草稿 → 管理员审核 → 正式启用
4. 更新后规则引擎自动热加载（无需重启）
