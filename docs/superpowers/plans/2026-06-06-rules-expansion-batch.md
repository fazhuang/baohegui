# 规则库扩展实施计划 (35 → 82 条)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将合规规则库从 35 条扩展到 82 条，分三批交付，同步扩展禁用词库和参数倾向性规则库。

**Architecture:** 所有规则存储在 `rules/compliance_rules.json`，遵循现有 Schema（35 条规则使用的结构）。禁用词库在 `rules/forbidden_words.json` 按维度扩展，参数倾向性规则在 `rules/parameter_bias_rules.json` 新增检测模式。规则引擎 (`rule_engine.py`) 和 LLM 引擎通过 Prompt 引用规则内容，API 层在 `rules.py` 提供 CRUD 操作。

**Tech Stack:** Python 3.13, JSON Schema, pytest

---

## 文件结构

```
rules/
├── compliance_rules.json              # 修改：35 → 82条（本计划核心文件）
├── forbidden_words.json               # 修改：新增3个维度 + 扩展正则列表
├── parameter_bias_rules.json          # 修改：新增3种检测模式
├── prompts/
│   └── compliance_check.txt           # 不变（Prompt 引用规则，规则扩后自动生效）
└── versions/
    └── manifest.json                  # 修改：更新规则版本号和清单

backend/app/engine/
├── rule_engine.py                      # 不变（通过 base_rules.json + forbidden_words.json 加载）
├── llm_engine.py                       # 不变（Prompt 模板引用 compliance_rules 内容）
└── parameter_bias.py                   # 不变（动态加载 parameter_bias_rules.json）

backend/app/api/
└── rules.py                            # 不变（通过 compliance_rules.json 提供 CRUD）

backend/tests/
├── test_rule_engine.py                 # 修改：新增规则命中/不命中测试用例
├── test_parameter_bias.py              # 修改：新增模式检测测试用例
└── test_rules_admin.py                 # 修改：新增规则数量验证
```

---

### Task 1: Batch 1 — 移植 hlgs 通报资产规则（12条）

**Files:**
- Modify: `rules/compliance_rules.json`
- Modify: `rules/forbidden_words.json`
- Modify: `rules/parameter_bias_rules.json`
- Modify: `backend/tests/test_rule_engine.py`

**Goal:** 从 hlgs 移植 12 条自动采集的通报资产规则，适配到 baohegui Schema。累计 47 条。

- [ ] **Step 1: 将 12 条 hlgs 通报规则追加到 compliance_rules.json**

在 `rules/compliance_rules.json` 的 `rules` 数组末尾（`R206` 规则之后），追加以下 12 条规则：

```json
{
  "rule_id": "R301",
  "rule_name": "特定厂家授权作为资格条件的处罚案例警示",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:限定特定厂家授权|特定厂商.*授权函|原厂授权.*资格|核心软硬件.*厂商.*授权)",
  "forbidden_message": "触发警示库违规拦截！案例依据：某高校智慧校园建设项目违规将特定厂家授权作为资格条件。案由：对违规索取特定核心软硬件厂商原厂授权函作为资格准入门槛行为的处理通报。",
  "message": "存在与历史违规通报案例高度相似的排他性或限制性表述。依据：某高校智慧校园建设项目违规将特定厂家授权作为资格条件。",
  "applicable_scope": {"project_type": ["采购","服务"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["厂家授权","原厂授权","厂商授权函"], "semantic": "存在索取厂家授权作为资格条件"},
  "risk_level": "high",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}, {"title": "市级财政监管部门通报", "article": ""}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+语义分析"},
  "suggestion": "移除将厂家授权作为资格条件的要求，改为技术参数满足即可",
  "example_bad": "投标人须提供核心交换机厂家原厂授权函",
  "example_good": "投标产品须满足招标文件所列技术参数要求"
},
{
  "rule_id": "R302",
  "rule_name": "妨碍统一市场公平竞争的排查清理要求",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:信用评价.*门槛|注册资金.*[门][槛]|特定资质.*[门][槛]|设定.*不合理.*条件)",
  "forbidden_message": "触发警示库违规拦截！依据：关于全面排查清理政府采购领域妨碍统一市场公平竞争规定的通知。案由：部署专项清理行动，重点核查信用评价、注册资金、特定资质等设定门槛的问题。",
  "message": "存在妨碍统一市场公平竞争的风险表述。依据：关于全面排查清理政府采购领域妨碍统一市场公平竞争规定的通知。",
  "applicable_scope": {"project_type": ["工程","服务","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["信用评价","注册资金","特定资质","门槛"], "semantic": "存在以信用评价/注册资金等设定门槛"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "深化政府采购制度改革领导小组办公室通知", "article": ""}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+条件分析"},
  "suggestion": "移除以信用评价、注册资金、特定资质等设定的不合理门槛条件",
  "example_bad": "投标人须在信用评价平台获得A级以上评价",
  "example_good": "投标人须具有良好的商业信誉（以信用中国查询结果为准）"
},
{
  "rule_id": "R303",
  "rule_name": "提供虚假材料谋取中标的违规警示",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:虚假材料|伪造.*证明|伪造.*业绩|虚假.*资质|造假)",
  "forbidden_message": "触发警示库违规拦截！案例依据：甘肃省政府采购网关于某建设工程咨询有限公司提供虚假材料谋取中标的通报。投标人应确保所提供资质证明材料的真实性。",
  "message": "资质要求中应明确虚假材料将导致的后果。依据：甘肃省政府采购网关于某建设工程咨询有限公司提供虚假材料谋取中标的通报。",
  "applicable_scope": {"project_type": ["工程","服务","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["虚假","伪造","造假","材料不实"], "semantic": "存在虚假材料风险"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购法", "article": "第七十七条"}, {"title": "甘肃省政府采购网通报", "article": ""}],
  "audit_method": {"type": "semantic", "pattern": "关键词语义检测"},
  "suggestion": "在废标条件中明确：提供虚假材料的将取消投标资格并上报监管部门",
  "example_bad": "",
  "example_good": "投标人须对所提供证明材料的真实性负责，提供虚假材料的将取消投标资格并列入不良行为记录名单"
},
{
  "rule_id": "R304",
  "rule_name": "串通投标行为的警示与防范",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:串通投标|围标|串标|陪标)",
  "forbidden_message": "触发警示库违规拦截！案例依据：中国政府采购网实时违规披露：某信息技术服务商涉嫌串通投标行为。采购文件中应明确串通投标的认定标准和法律后果。",
  "message": "存在串通投标风险提示。依据：中国政府采购网实时违规披露：某信息技术服务商涉嫌串通投标行为。",
  "applicable_scope": {"project_type": ["工程","服务","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["串通","围标","串标","陪标"], "semantic": "存在串通投标风险"},
  "risk_level": "high",
  "regulation_basis": [{"title": "招标投标法实施条例", "article": "第四十条"}, {"title": "中国政府采购网通报", "article": ""}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+语义分析"},
  "suggestion": "在废标条件中明确串通投标的认定标准及法律后果",
  "example_bad": "",
  "example_good": "有下列情形之一的视为串通投标：不同投标人的投标文件由同一单位或个人编制；不同投标人委托同一单位或个人办理投标事宜；不同投标人的投标文件异常一致或报价呈规律性差异"
},
{
  "rule_id": "R305",
  "rule_name": "违规收取未列明服务费的案例警示",
  "category": "C",
  "field": "bid_rejection_conditions",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:未列明.*服务费|额外.*收费|附加.*费用|中标服务费.*未.*列)",
  "forbidden_message": "触发警示库违规拦截！案例依据：某代理机构违规收取未列明服务费被通报。所有收费项目须在招标文件中明确列明。",
  "message": "存在违规收费风险。依据：某代理机构违规收取未列明服务费被通报案例。",
  "applicable_scope": {"project_type": ["工程","服务","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["服务费","收费","费用"], "semantic": "存在收费要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "招标投标法实施条例", "article": ""}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "在招标文件中明确列明所有收费项目、标准和收取方式",
  "example_bad": "中标人须缴纳中标服务费（未列明具体金额和标准）",
  "example_good": "中标服务费按中标金额的0.8%收取，在领取中标通知书时缴纳"
},
{
  "rule_id": "R306",
  "rule_name": "医疗设备采购排他性技术参数的案例警示",
  "category": "B",
  "field": "technical_params",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:医疗设备.*[指][定]|专[利].*[设][备]|特定型号.*[医][疗]|独家.*配置)",
  "forbidden_message": "触发警示库违规拦截！案例依据：关于某医院医疗设备采购项目违规设定排他性技术参数的通报。医疗设备采购参数应保证至少3个品牌可满足。",
  "message": "医疗设备技术参数存在排他性风险。依据：关于某医院医疗设备采购项目违规设定排他性技术参数的通报。",
  "applicable_scope": {"project_type": ["采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["医疗设备","CT","MRI","超声","DR"], "semantic": "存在医疗设备技术参数"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+参数对标分析"},
  "suggestion": "确保医疗设备技术参数至少3个品牌可满足，改用性能指标而非具体型号参数",
  "example_bad": "CT扫描仪：探测器排数256排（仅GE品牌满足）",
  "example_good": "CT扫描仪：探测器排数≥64排（至少3个品牌可满足）"
},
{
  "rule_id": "R307",
  "rule_name": "要求当地分支机构证明的违规警示",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:当地.*分支.*证明|项目所在地.*分支.*机构.*证明|本地.*服务.*机构.*证明|在本市.*设有.*分公司)",
  "forbidden_message": "触发警示库违规拦截！案例依据：关于部分工程类招标违规要求提供当地分支机构证明的警示通知。不得要求投标人在项目所在地设立分支机构作为资格条件。",
  "message": "要求提供当地分支机构证明属于地域歧视。依据：关于部分工程类招标违规要求提供当地分支机构证明的警示通知。",
  "applicable_scope": {"project_type": ["工程","服务"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["当地分支","本地服务","分公司","分支机构","当地机构"], "semantic": "存在分支机构要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "取消提供当地分支机构证明的要求，改为中标后设立服务网点或指定授权服务商",
  "example_bad": "投标人须提供在兰州市设有分支机构或分公司的证明材料",
  "example_good": "投标人须承诺中标后在项目所在地提供本地化服务支持"
},
{
  "rule_id": "R308",
  "rule_name": "串通投标及评标标准畸高的警示通报",
  "category": "B",
  "field": "scoring_criteria",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:评标标准.*畸高|评审标准.*过高|评分.*门槛.*过高|业绩.*分数.*超过.*30)",
  "forbidden_message": "触发警示库违规拦截！案例依据：某交通监控设施改造项目串通投标及评标标准畸高典型违规通报。评审标准应与项目实际需要相适应。",
  "message": "评标标准设置存在畸高风险。依据：某交通监控设施改造项目串通投标及评标标准畸高典型违规通报。",
  "applicable_scope": {"project_type": ["工程","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["业绩分","评分标准","技术分","商务分"], "semantic": "存在评标标准设置"},
  "risk_level": "high",
  "regulation_basis": [{"title": "招标投标法实施条例", "article": "第三十二条"}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+分值评估"},
  "suggestion": "评审因素的设定应与项目实际需要相适应，业绩分值不宜畸高",
  "example_bad": "投标人业绩得分占总分50%（畸高不合理）",
  "example_good": "投标人业绩得分占总分10%-15%"
},
{
  "rule_id": "R309",
  "rule_name": "无正当理由拒签合同的行为警示",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:拒签.*合同|无正当理由.*不.*签.*合同|放弃.*中标)",
  "forbidden_message": "触发警示库违规拦截！案例依据：信用中国（甘肃）实时监测：某科技发展服务公司无正当理由拒不签署合同。招标文件应明确无故放弃中标的后果。",
  "message": "应明确无故放弃中标或拒签合同的后果。依据：信用中国（甘肃）实时监测：某科技发展服务公司无正当理由拒不签署合同。",
  "applicable_scope": {"project_type": ["工程","服务","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["放弃中标","拒签","不签合同"], "semantic": "存在弃标风险"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "招标投标法实施条例", "article": "第七十四条"}, {"title": "信用中国（甘肃）通报", "article": ""}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "在招标文件中明确：无故放弃中标的将没收投标保证金并列入不良行为记录",
  "example_bad": "",
  "example_good": "中标人无正当理由不与招标人订立合同的，取消其中标资格，投标保证金不予退还，并上报监管部门"
},
{
  "rule_id": "R310",
  "rule_name": "技术参数通用排他性案例警示",
  "category": "B",
  "field": "technical_params",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:参数.*[唯][一].*[满][足]|至少.*品牌.*[满][足]|至少.*供应商.*[满][足])",
  "forbidden_message": "触发警示库违规拦截！技术参数应保证至少3个品牌或供应商可满足。如参数导致仅1-2家满足，构成排他性条款。",
  "message": "技术参数存在排他性风险，应确保至少3个品牌可满足。",
  "applicable_scope": {"project_type": ["采购","工程"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["技术参数","规格要求","配置要求"], "semantic": "存在技术参数描述"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+参数分析"},
  "suggestion": "拓宽技术参数范围，确保至少3个品牌可满足核心参数要求",
  "example_bad": "芯片须采用Intel第14代酷睿i7-14700（仅Intel满足）",
  "example_good": "CPU主频≥3.0GHz，核心数≥12核（Intel/AMD/国产CPU均可满足）"
},
{
  "rule_id": "R311",
  "rule_name": "代理机构违规收费的案例警示",
  "category": "C",
  "field": "bid_rejection_conditions",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:代理.*收费.*未.*公示|招标代理.*服务费.*[未][明]|违规.*收费)",
  "forbidden_message": "触发警示库违规拦截！案例依据：甘肃省发展和改革委员会关于部分招标代理机构违规收费典型案例的通报。代理服务费须在招标公告中明确。",
  "message": "代理服务费须在招标文件中明确列明。依据：甘肃省发展和改革委员会关于部分招标代理机构违规收费典型案例的通报。",
  "applicable_scope": {"project_type": ["工程","服务","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["代理服务费","招标代理","服务费"], "semantic": "存在代理收费"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "甘肃省发展和改革委员会通报", "article": ""}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "在招标公告或投标人须知中明确招标代理服务费的收取标准和方式",
  "example_bad": "招标代理服务费由中标人承担（未列明具体标准）",
  "example_good": "招标代理服务费按中标金额的0.7%收取，由中标人在领取中标通知书时一次性支付"
},
{
  "rule_id": "R312",
  "rule_name": "违规转包的案例警示与合规要求",
  "category": "C",
  "field": "bid_rejection_conditions",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:违规转包|违法.*分包|未经.*同意.*分包|擅自.*转让)",
  "forbidden_message": "触发警示库违规拦截！案例依据：甘肃省公共资源交易局实时通报：关于某建筑工程局有限公司违规转包的通报。应明确转包禁止、分包须经采购人同意的规定。",
  "message": "应明确禁止转包、限制分包的规定。依据：甘肃省公共资源交易局通报：关于某建筑工程局有限公司违规转包的通报。",
  "applicable_scope": {"project_type": ["工程","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["转包","分包","转让"], "semantic": "存在转包分包条款"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "招标投标法", "article": "第四十八条"}, {"title": "甘肃省公共资源交易局通报", "article": ""}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "明确：中标人不得转包，非主体部分经采购人同意可依法分包",
  "example_bad": "",
  "example_good": "中标人不得将项目转包。非主体、非关键性工作经采购人书面同意可依法分包"
}
```

更新 `last_updated` 字段为 `"2026-06-06"`。

- [ ] **Step 2: 验证规则 JSON 格式无语法错误**

Run:
```bash
python3 -c "import json; f=open('rules/compliance_rules.json'); d=json.load(f); f.close(); print(f'OK: {len(d[\"rules\"])} rules')"
```
Expected: `OK: 47 rules`

- [ ] **Step 3: 在 forbidden_words.json 中新增通报资产维度**

在 `rules/forbidden_words.json` 的 `patterns` 对象中新增 `case_alert` 维度：

```json
"case_alert": {
  "label": "通报案例警示",
  "description": "来自真实投诉案例和监管通报的违规模式警示",
  "severity": "high",
  "risk_level": "高",
  "regex_list": [
    {
      "id": "FORB-F01",
      "pattern": "原厂授权.*资格|厂家授权.*门槛|特定厂商.*授权函",
      "message": "将厂家授权作为资格条件，触发案例警示（R301）",
      "weight": 20,
      "law_ref": "《政府采购法实施条例》第二十条",
      "suggestion": "移除厂家授权作为资格条件的要求"
    },
    {
      "id": "FORB-F02",
      "pattern": "当地.*分支.*证明|项目所在地.*设有.*分公司",
      "message": "要求当地分支机构证明，触发地域歧视案例警示（R307）",
      "weight": 20,
      "law_ref": "《政府采购法实施条例》第二十条",
      "suggestion": "取消当地分支机构要求，改为中标后设立服务网点"
    },
    {
      "id": "FORB-F03",
      "pattern": "虚假材料|伪造.*业绩|伪造.*资质",
      "message": "提醒：虚假材料将导致取消资格并列入不良记录（R303）",
      "weight": 15,
      "law_ref": "《政府采购法》第七十七条",
      "suggestion": "明确虚假材料的法律后果"
    },
    {
      "id": "FORB-F04",
      "pattern": "招标代理.*服务费.*未|代理.*收费.*未.*明",
      "message": "代理服务费未明确列明，触发违规收费案例警示（R311）",
      "weight": 15,
      "law_ref": "《招标投标法实施条例》",
      "suggestion": "明确列明代理服务费的收取标准和方式"
    },
    {
      "id": "FORB-F05",
      "pattern": "评标标准.*畸高|业绩.*分.*超过.*30|评分.*门槛.*过高",
      "message": "评标标准或业绩分值畸高，触发违规案例警示（R308）",
      "weight": 20,
      "law_ref": "《招标投标法实施条例》第三十二条",
      "suggestion": "评审因素应与项目实际需要相适应"
    }
  ]
}
```

- [ ] **Step 4: 验证 forbidden_words.json 格式无语法错误**

Run:
```bash
python3 -c "import json; f=open('rules/forbidden_words.json'); d=json.load(f); f.close(); dims=list(d['patterns'].keys()); print(f'OK: {len(dims)} dimensions — {dims}')"
```
Expected: `OK: 13 dimensions` (12 + 1 new)

- [ ] **Step 5: 在 parameter_bias_rules.json 中新增案例驱动检测模式**

在 `rules/parameter_bias_rules.json` 的 `violation_patterns` 对象中新增：

```json
"case_driven_authorization_lock": {
  "severity": "high",
  "risk_level": "高",
  "description": "案例驱动：特定厂家授权锁——基于某高校智慧校园建设通报案例（hlgs R_AUTO_D1F457）",
  "keywords": [
    "厂家授权函",
    "原厂授权",
    "特定厂商",
    "核心软硬件厂商",
    "厂商授权书"
  ],
  "check_fields": ["qualification_requirements"],
  "check_logic": "搜索资格要求中是否含特定厂家授权相关的强制性要求",
  "suggestion": "移除厂家授权作为资格条件的条款，改为技术参数满足即可",
  "rule_id": "R301"
},
"case_driven_local_branch_lock": {
  "severity": "high",
  "risk_level": "高",
  "description": "案例驱动：本地分支机构要求——基于工程类招标违规要求当地分支机构证明的警示（hlgs R_AUTO_C15A5C）",
  "keywords": [
    "设有分公司",
    "当地分支机构",
    "项目所在地.*分支",
    "在本市.*设有",
    "注册.*分支机构"
  ],
  "check_fields": ["qualification_requirements"],
  "check_logic": "搜索是否要求投标人在项目所在地设有分支机构",
  "suggestion": "取消分支机构证明要求，改为中标后设立或承诺提供本地化服务",
  "rule_id": "R307"
},
"case_driven_high_threshold_scoring": {
  "severity": "medium",
  "risk_level": "中",
  "description": "案例驱动：评标标准畸高——基于交通监控设施项目评标标准畸高通报（hlgs R_AUTO_9464A4）",
  "keywords": [
    "业绩分值",
    "评分权重",
    "技术分.*占比",
    "业绩.*分.*高"
  ],
  "check_fields": ["scoring_criteria", "evaluation_criteria"],
  "check_logic": "评估评分标准中业绩分值或技术分值是否畸高",
  "suggestion": "确保评审因素分值分配合理，业绩分不宜超过总分30%",
  "rule_id": "R308"
}
```

- [ ] **Step 6: 验证 parameter_bias_rules.json 格式无语法错误**

Run:
```bash
python3 -c "import json; f=open('rules/parameter_bias_rules.json'); d=json.load(f); f.close(); vp=list(d['violation_patterns'].keys()); print(f'OK: {len(vp)} patterns — {vp}')"
```
Expected: `OK: 13 patterns` (10 + 3 new)

- [ ] **Step 7: 新增测试用例**

在 `backend/tests/test_rule_engine.py` 末尾添加：

```python

# ═══════════════════════════════════════════════════════════════
# Batch 1: hlgs 通报资产规则验证
# ═══════════════════════════════════════════════════════════════


class TestBatch1HlgsAutoRules:
    """验证 12 条 hlgs 通报资产规则正确追加到 compliance_rules.json"""

    def test_r301_auth_lock_detected(self):
        """R301: 特定厂家授权作为资格条件"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        r301 = next(r for r in data["rules"] if r["rule_id"] == "R301")
        assert r301["category"] == "A"
        assert r301["rule_type"] == "forbidden_pattern"
        assert "厂家授权" in r301["forbidden_pattern"]

    def test_r307_local_branch_detected(self):
        """R307: 要求当地分支机构证明"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        r307 = next(r for r in data["rules"] if r["rule_id"] == "R307")
        assert r307["category"] == "A"
        assert "分支" in r307["forbidden_pattern"]

    def test_all_12_hlgs_rules_present(self):
        """验证 12 条 R301-R312 规则均存在且格式正确"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        for rid in [f"R{30 + i}" for i in range(1, 13)]:  # R301 - R312
            rule = next((r for r in data["rules"] if r["rule_id"] == rid), None)
            assert rule is not None, f"{rid} 缺失"
            assert "rule_id" in rule
            assert "rule_name" in rule
            assert "rule_type" in rule
            assert "forbidden_pattern" in rule
            assert "risk_level" in rule
            assert "regulation_basis" in rule

    def test_total_rules_after_batch1(self):
        """Batch 1 后规则总数为 47"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        assert len(data["rules"]) == 47, f"Expected 47 rules, got {len(data['rules'])}"
```

- [ ] **Step 8: 运行测试**

```bash
cd backend && uv run pytest tests/test_rule_engine.py::TestBatch1HlgsAutoRules -v
```
Expected: 4 PASS

- [ ] **Step 9: 运行全量回归测试**

```bash
cd backend && uv run pytest tests/test_rule_engine.py tests/test_parameter_bias.py tests/test_rules_admin.py -v
```
Expected: ALL PASS (无回归失败)

- [ ] **Step 10: 提交**

```bash
git add rules/compliance_rules.json rules/forbidden_words.json rules/parameter_bias_rules.json backend/tests/test_rule_engine.py
git commit -m "feat: add batch 1 — 12 hlgs auto-asset rules (35→47)"
```

---

### Task 2: Batch 2 — 行业专项规则（25条）

**Files:**
- Modify: `rules/compliance_rules.json`
- Modify: `rules/forbidden_words.json`
- Modify: `rules/parameter_bias_rules.json`
- Modify: `backend/tests/test_rule_engine.py`

**Goal:** 新增 25 条行业专项规则，覆盖工程建设(10)、IT设备采购(8)、服务类(7)。累计 72 条。

- [ ] **Step 1: 追加 25 条行业专项规则到 compliance_rules.json**

在 `compliance_rules.json` 的 `rules` 数组末尾（`R312` 之后）追加规则。规则内容见本步骤末尾的完整 JSON 块，更新 `last_updated` 为 `"2026-06-06"`。

```json
{
  "rule_id": "R401",
  "rule_name": "施工资质等级与项目规模匹配",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '工程'",
  "forbidden_pattern": "(?:三级资质.*[预][算].*[超].*\\d{4,}|二级资质.*[预][算].*[超].*\\d{6,}|一级资质.*[预][算].*[超].*\\d{7,}|特级资质.*[预][算].*[不].*[足])",
  "forbidden_message": "资质等级与项目预算规模不匹配，或资质等级过高构成隐性门槛",
  "message": "施工资质等级应与项目预算规模相匹配，不得过高要求资质等级",
  "applicable_scope": {"project_type": ["工程"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["资质","总承包","专业承包","特级","一级","二级","三级"], "semantic": "存在施工资质等级要求"},
  "risk_level": "critical",
  "regulation_basis": [{"title": "建筑业企业资质管理规定", "article": ""}, {"title": "住房和城乡建设部相关通知", "article": ""}],
  "audit_method": {"type": "keyword+numeric", "pattern": "资质等级+预算金额对照"},
  "suggestion": "按照建筑业企业资质标准合理设定资质等级，不得高于项目实际需要",
  "example_bad": "须具备建筑工程施工总承包特级资质（项目预算500万元）",
  "example_good": "须具备建筑工程施工总承包三级及以上资质"
},
{
  "rule_id": "R402",
  "rule_name": "项目经理不得有在建工程",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "pattern_required",
  "required": false,
  "condition": "project_type == '工程'",
  "pattern": "(?:不得有在建|无在建工程|不得同时担任|项目经理.*未在建)",
  "pattern_message": "应明确项目经理不得有在建工程",
  "message": "应要求项目经理不得有在建工程项目",
  "applicable_scope": {"project_type": ["工程"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["项目经理","项目负责人","建造师"], "semantic": "存在项目经理要求"},
  "risk_level": "high",
  "regulation_basis": [{"title": "注册建造师管理规定", "article": ""}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "在资格要求中明确：项目经理不得有在建工程，并提供无在建承诺书",
  "example_bad": "项目经理须具有建筑工程一级注册建造师资格",
  "example_good": "项目经理须具有建筑工程一级注册建造师资格，且不得有在建工程（提供无在建承诺书）"
},
{
  "rule_id": "R403",
  "rule_name": "安全生产许可证须有效",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "required",
  "required": true,
  "condition": "project_type == '工程'",
  "pattern": "(?:安全生产许可证|安全生产许可)",
  "pattern_message": "须要求投标人具备有效的安全生产许可证",
  "message": "工程施工项目须要求投标人具备有效的安全生产许可证",
  "applicable_scope": {"project_type": ["工程"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["安全生产","施工安全"], "semantic": "存在安全生产相关要求"},
  "risk_level": "critical",
  "regulation_basis": [{"title": "安全生产许可证条例", "article": ""}, {"title": "建筑施工企业安全生产许可证管理规定", "article": ""}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "在资格要求中增加：投标人须具备有效的建筑施工企业安全生产许可证",
  "example_bad": "投标人须具备建筑工程施工总承包资质",
  "example_good": "投标人须具备建筑工程施工总承包三级及以上资质和有效的安全生产许可证"
},
{
  "rule_id": "R404",
  "rule_name": "工期要求不得低于合理工期",
  "category": "B",
  "field": "technical_params",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '工程'",
  "forbidden_pattern": "(?:工期.*不[得超].*\\d{1,2}\\s*[日天]|工期.*不少于.*\\d{1,2}\\s*[个]?[月]|工期要求.*紧[急])",
  "forbidden_message": "工期要求过短可能影响工程质量或限制投标人范围",
  "message": "工期要求应合理，不得以压缩工期为由排斥潜在投标人",
  "applicable_scope": {"project_type": ["工程"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["工期","竣工","完成时间","日历天"], "semantic": "存在工期要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "建设工程质量管理条例", "article": "第十条"}],
  "audit_method": {"type": "keyword+numeric", "pattern": "关键词检测+工期评估"},
  "suggestion": "工期设定应参考定额工期，不得任意压缩合理工期",
  "example_bad": "工期：30日历天（常规需60日历天的工程）",
  "example_good": "工期：60日历天（参照定额工期合理设定）"
},
{
  "rule_id": "R405",
  "rule_name": "履约保证金比例不得超10%",
  "category": "C",
  "field": "bid_rejection_conditions",
  "rule_type": "numeric_range",
  "required": false,
  "condition": "project_type == '工程'",
  "forbidden_pattern": "(?:履约保证金.*[超].*10%|履约保证金.*[超].*百分之十|履约.*保证金.*[超].*合同.*价.*10%)",
  "forbidden_message": "履约保证金不得超过中标合同金额的10%",
  "message": "履约保证金比例不得超过中标合同金额的10%",
  "applicable_scope": {"project_type": ["工程"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["履约保证金","履约担保"], "semantic": "存在履约保证金要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "招标投标法实施条例", "article": "第五十八条"}],
  "audit_method": {"type": "keyword+numeric", "pattern": "关键词检测+比例比对"},
  "suggestion": "将履约保证金调整为不超过中标合同金额的10%",
  "example_bad": "履约保证金：中标合同金额的15%",
  "example_good": "履约保证金：中标合同金额的10%"
},
{
  "rule_id": "R406",
  "rule_name": "工程量清单须完整无缺项",
  "category": "B",
  "field": "technical_params",
  "rule_type": "pattern_required",
  "required": true,
  "condition": "project_type == '工程'",
  "pattern": "(?:工程量清单|分部分项.*工程量|清单.*计价|工程量.*表)",
  "pattern_message": "工程量清单须完整，无缺项漏项",
  "message": "工程量清单须完整列明各分部分项工程量",
  "applicable_scope": {"project_type": ["工程"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["工程量清单","清单","分部分项"], "semantic": "存在工程量清单"},
  "risk_level": "high",
  "regulation_basis": [{"title": "建设工程工程量清单计价规范", "article": "GB50500"}],
  "audit_method": {"type": "keyword+structure", "pattern": "关键词+结构完整性检测"},
  "suggestion": "提供完整的工程量清单，不得缺项漏项",
  "example_bad": "",
  "example_good": "工程量清单已包含本项目全部施工内容，详见附件"
},
{
  "rule_id": "R407",
  "rule_name": "不得在施工要求中指定主要建材品牌",
  "category": "B",
  "field": "technical_params",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '工程'",
  "forbidden_pattern": "(?:须采用.{0,5}品牌|指定.{0,5}品牌.*[材][料]|钢材.*须[为].*品牌|水泥.*指定|电缆.*指定.*品牌|涂料.*[指][定].*品牌)",
  "forbidden_message": "在施工技术参数中指定主要建材品牌构成排他性条款",
  "message": "施工技术参数中不得指定主要建材品牌",
  "applicable_scope": {"project_type": ["工程"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["品牌","指定","须为"], "semantic": "存在建材品牌指定"},
  "risk_level": "critical",
  "regulation_basis": [{"title": "招标投标法实施条例", "article": "第三十二条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "改用性能指标而非指定品牌，或列出至少3个同等档次品牌并注明'或同等品'",
  "example_bad": "电缆须采用正泰品牌",
  "example_good": "电缆须满足GB/T 12706标准（正泰、德力西、人民或同等品均可）"
},
{
  "rule_id": "R408",
  "rule_name": "项目经理业绩要求须与项目规模匹配",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '工程'",
  "forbidden_pattern": "(?:项目经理.*业绩.*\\d{4,}\\s*万|项目负责人.*[业][绩].*超过.*\\d{4,}|建造师.*[业][绩].*[超])",
  "forbidden_message": "项目经理业绩要求超过项目规模构成不合理条件",
  "message": "项目经理业绩要求应与本项目规模相当，不得过高",
  "applicable_scope": {"project_type": ["工程"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["项目经理","项目负责人","业绩","类似项目"], "semantic": "存在项目经理业绩要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "招标投标法实施条例", "article": "第三十二条"}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+业绩规模评估"},
  "suggestion": "项目经理业绩要求应与本项目规模（预算、面积）相当",
  "example_bad": "项目经理须具备单项合同金额5000万元及以上的同类项目业绩（本项目预算1000万元）",
  "example_good": "项目经理须具备单项合同金额1000万元及以上的同类项目业绩"
},
{
  "rule_id": "R409",
  "rule_name": "联合体各方须满足相应资质条件",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "conditional",
  "required": false,
  "condition": "project_type == '工程'",
  "pattern": "(?:联合体.*各方.*资质|联合体.*资质.*满足|联合体.*成员.*资质)",
  "pattern_message": "应明确联合体各方的资质要求和责任划分",
  "message": "联合体投标应明确各方资质条件及牵头人",
  "applicable_scope": {"project_type": ["工程"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["联合体","联合投标","联合各方"], "semantic": "存在联合体投标"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "招标投标法", "article": "第三十一条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "明确联合体各方资质要求及牵头人责任，同一专业的联合体按较低资质等级确定",
  "example_bad": "本项目接受联合体投标",
  "example_good": "本项目接受联合体投标。联合体各方均应满足资质要求，牵头人须具备主要专业资质，联合体各方不得再以自己名义单独或参加其他联合体投标"
},
{
  "rule_id": "R410",
  "rule_name": "安全文明施工费须单独列明",
  "category": "D",
  "field": "technical_params",
  "rule_type": "required",
  "required": true,
  "condition": "project_type == '工程'",
  "pattern": "(?:安全文明施工费|安全防护|文明施工|安全措施.*费)",
  "pattern_message": "安全文明施工费须在工程量清单中单独列明，不得作为竞争性费用",
  "message": "安全文明施工费须单独列明，不得作为竞争性费用",
  "applicable_scope": {"project_type": ["工程"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["安全文明","安全措施","文明施工"], "semantic": "存在安全文明施工费"},
  "risk_level": "high",
  "regulation_basis": [{"title": "建设工程安全生产管理条例", "article": ""}, {"title": "建设工程工程量清单计价规范", "article": ""}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "在工程量清单中单独列明安全文明施工费，注明不可竞争",
  "example_bad": "",
  "example_good": "安全文明施工费按XX元列入（不可竞争费用，投标人不得调整）"
},
{
  "rule_id": "R501",
  "rule_name": "IT设备技术参数不得指定芯片型号",
  "category": "B",
  "field": "technical_params",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '采购'",
  "forbidden_pattern": "(?:Intel\\s*Core\\s*i[3579]|AMD\\s*Ryzen|龙芯.*必须|飞腾.*必须|芯片型号.*[须必][须为])",
  "forbidden_message": "技术参数中指定芯片型号将排除其他品牌，构成排他性条款",
  "message": "IT设备技术参数不得指定CPU/芯片具体型号",
  "applicable_scope": {"project_type": ["采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["CPU","芯片","处理器","Intel","AMD","龙芯","飞腾"], "semantic": "存在芯片型号指定"},
  "risk_level": "critical",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "keyword+regex", "pattern": "品牌/型号关键词检测"},
  "suggestion": "改用性能指标描述（如CPU主频≥3.0GHz，核心数≥8），列出至少3个满足的品牌",
  "example_bad": "CPU：Intel Core i7-14700",
  "example_good": "CPU：主频≥3.0GHz，核心数≥12核（Intel/AMD/国产CPU均可满足）"
},
{
  "rule_id": "R502",
  "rule_name": "IT设备不得要求整机原厂认证",
  "category": "B",
  "field": "technical_params",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '采购'",
  "forbidden_pattern": "(?:整机.*原厂.*认证|原厂.*整机.*认证|原厂.*[出][厂].*[检][测]|品牌.*原厂.*出厂)",
  "forbidden_message": "要求整机原厂认证构成品牌锁定，限制代理商参与竞争",
  "message": "不得要求整机原厂认证，应允许代理商提供同等品质保证",
  "applicable_scope": {"project_type": ["采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["整机原厂","原厂认证","原厂出厂"], "semantic": "存在整机原厂认证要求"},
  "risk_level": "high",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "取消整机原厂认证要求，允许经销商/代理商提供同等品质保证",
  "example_bad": "服务器须提供整机原厂出厂检测报告及原厂认证证书",
  "example_good": "服务器须满足招标文件技术参数要求，并提供产品合格证及质保承诺"
},
{
  "rule_id": "R503",
  "rule_name": "IT设备软件授权不得排他性要求",
  "category": "B",
  "field": "technical_params",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '采购'",
  "forbidden_pattern": "(?:必须.*[使].*[用].*[软][件]|须为.*[原][厂].*[软][件]|指定.*软件.*版本|软件.*授权.*唯一)",
  "forbidden_message": "软件授权要求不得排他，应允许同等功能的替代方案",
  "message": "软件授权要求不得排他，应允许同等功能替代方案",
  "applicable_scope": {"project_type": ["采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["软件授权","软件许可","软件版本","操作系统"], "semantic": "存在软件授权要求"},
  "risk_level": "high",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+语义分析"},
  "suggestion": "改为功能要求描述：支持XX功能或同等功能的软件系统均可",
  "example_bad": "数据库须使用Oracle 19c企业版",
  "example_good": "数据库系统须支持ACID事务、SQL标准（Oracle/MySQL/PostgreSQL/达梦等均可）"
},
{
  "rule_id": "R504",
  "rule_name": "IT设备兼容性要求须有至少3家满足",
  "category": "B",
  "field": "technical_params",
  "rule_type": "semantic_required",
  "required": false,
  "condition": "project_type == '采购'",
  "semantic_keywords": ["兼容","互连互通","互联互通","标准协议","标准接口"],
  "message": "兼容性要求应基于标准协议，确保至少3家供应商可满足",
  "applicable_scope": {"project_type": ["采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["兼容","互连","对接","集成"], "semantic": "存在兼容性要求"},
  "risk_level": "high",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "semantic", "pattern": "关键词+语义关联检测"},
  "suggestion": "明确兼容性标准（如TCP/IP协议、标准API、标准数据格式），不指定特定品牌对接",
  "example_bad": "须与现有XX品牌视频监控平台无缝对接",
  "example_good": "须支持ONVIF/GB/T 28181标准协议实现视频监控平台对接"
},
{
  "rule_id": "R505",
  "rule_name": "IT设备质保期要求须合理",
  "category": "C",
  "field": "technical_params",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '采购'",
  "forbidden_pattern": "(?:质保.*\\d{2,}\\s*[年]|免费保修.*\\d{2,}\\s*[年]|保修期.*不少于.*\\d{2,})",
  "forbidden_message": "质保期要求过长可能排除部分供应商，应符合行业惯例",
  "message": "质保期要求应合理，符合行业惯例",
  "applicable_scope": {"project_type": ["采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["质保","保修","售后服务"], "semantic": "存在质保期要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "产品质量法", "article": ""}],
  "audit_method": {"type": "keyword+numeric", "pattern": "关键词+年份数值检测"},
  "suggestion": "将质保期调整至行业常规水平：IT设备通常1-3年原厂质保",
  "example_bad": "服务器须提供10年原厂免费质保服务",
  "example_good": "服务器须提供3年原厂质保服务（7×24小时响应）"
},
{
  "rule_id": "R506",
  "rule_name": "IT设备国产化要求须有政策依据",
  "category": "D",
  "field": "technical_params",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '采购'",
  "forbidden_pattern": "(?:须为国产|必须国产|国产品牌|国产自主可控|信创.*必须)",
  "forbidden_message": "国产化要求须有明确的政策依据，不得以国产化为名排斥特定供应商",
  "message": "国产化要求须有政策依据并明确界定标准",
  "applicable_scope": {"project_type": ["采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["国产","国产化","信创","自主可控"], "semantic": "存在国产化要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购法", "article": "第十条"}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+政策依据检查"},
  "suggestion": "如属于信创目录范围，注明依据文件；如非信创范围，不得以国产化为名排斥进口产品",
  "example_bad": "服务器须为国产自主可控品牌",
  "example_good": "服务器须满足以下技术参数（国产或进口均可，信创目录产品优先）"
},
{
  "rule_id": "R507",
  "rule_name": "IT设备不得要求特定测试机构报告",
  "category": "B",
  "field": "technical_params",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '采购'",
  "forbidden_pattern": "(?:须.*[国][家].*[质][检].*[中][心].*[检][测]|须.*指定.*实验室.*[报][告]|须.*[某].*[机][构].*[检][测].*[报][告])",
  "forbidden_message": "要求特定测试机构出具检测报告限制竞争",
  "message": "检测报告应由具有资质的检测机构出具，不得限定具体机构",
  "applicable_scope": {"project_type": ["采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["检测报告","检测机构","检测中心","质检"], "semantic": "存在检测机构要求"},
  "risk_level": "high",
  "regulation_basis": [{"title": "政府采购法", "article": "第二十二条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "改为具有CMA/CNAS资质的第三方检测机构出具即可",
  "example_bad": "须提供国家电子计算机质量监督检验中心出具的检测报告",
  "example_good": "须提供具有CMA/CNAS资质的第三方检测机构出具的检测报告"
},
{
  "rule_id": "R508",
  "rule_name": "IT设备功能参数须可量化验证",
  "category": "B",
  "field": "technical_params",
  "rule_type": "pattern_required",
  "required": true,
  "condition": "project_type == '采购'",
  "pattern": "(?:主频|频率|容量|速度|带宽|分辨率|吞吐|并发|能耗|功耗|功率)",
  "pattern_message": "技术参数须包含可量化验证的指标",
  "message": "IT设备技术参数须提供可量化验证的具体指标",
  "applicable_scope": {"project_type": ["采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["技术参数","规格参数","配置参数"], "semantic": "存在技术参数描述"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第十五条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "补充具体可量化的技术指标，如主频、容量、速度、分辨率等",
  "example_bad": "服务器配置：高性能处理器、大容量内存",
  "example_good": "服务器配置：CPU主频≥3.0GHz、内存≥32GB DDR5、硬盘≥2TB SSD"
},
{
  "rule_id": "R601",
  "rule_name": "服务类人员配置数量须与项目规模匹配",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '服务'",
  "forbidden_pattern": "(?:人员.*不少于.*\\d{2,}|派驻.*人员.*\\d{2,}|项目团队.*不少于.*\\d{2,})",
  "forbidden_message": "人员配置数量要求过高可能限制中小企业参与",
  "message": "服务类项目人员配置数量应与项目规模匹配",
  "applicable_scope": {"project_type": ["服务"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["人员","团队","派驻","配置"], "semantic": "存在人员配置要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "keyword+numeric", "pattern": "关键词+人数检测"},
  "suggestion": "人员配置要求应与项目实际需求匹配，中小型项目不得要求过多人员",
  "example_bad": "投标人须配备不少于30人的项目团队（小型物业管理项目）",
  "example_good": "投标人须配备满足项目需求的项目经理1名、保洁员不少于5名、安保人员不少于3名"
},
{
  "rule_id": "R602",
  "rule_name": "服务类业绩数量要求不得超过项目规模",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '服务'",
  "forbidden_pattern": "(?:服务.*业绩.*不少于.*\\d{2,}|类似.*业绩.*\\d{2,}\\s*[个项]|同类.*合同.*不少于.*\\d{2,})",
  "forbidden_message": "业绩数量要求过高限制中小企业参与竞争",
  "message": "服务类项目业绩数量要求应与项目规模匹配，不得过高",
  "applicable_scope": {"project_type": ["服务"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["业绩","类似项目","同类","服务经验"], "semantic": "存在服务业绩要求"},
  "risk_level": "high",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "keyword+numeric", "pattern": "关键词+数量检测"},
  "suggestion": "将业绩要求调整至合理水平，如'近三年至少1个同类项目业绩'",
  "example_bad": "投标人须具有20个以上同类物业服务项目业绩",
  "example_good": "投标人须具有3个以上同类物业服务项目业绩"
},
{
  "rule_id": "R603",
  "rule_name": "服务类不得要求本地化服务作为资格条件",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '服务'",
  "forbidden_pattern": "(?:须.*[在][本].*[有].*[服][务].*[网][点]|须.*[在][本].*[设][有].*[机][构]|本地.*服务.*必须|项目所在地.*须有)",
  "forbidden_message": "将本地化服务作为资格条件构成地域歧视",
  "message": "不得将本地化服务作为资格条件，可设为加分项或中标后承诺",
  "applicable_scope": {"project_type": ["服务"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["本地","当地","所在市","服务网点"], "semantic": "存在本地化服务资格要求"},
  "risk_level": "critical",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+地域分析"},
  "suggestion": "将本地化服务要求改为加分项，或要求中标后设立服务网点",
  "example_bad": "投标人须在兰州市设有常驻物业管理服务网点",
  "example_good": "投标人须承诺中标后在项目所在地设立服务网点（或投标人已在本地设有服务机构的可作为加分项）"
},
{
  "rule_id": "R604",
  "rule_name": "服务方案评分须量化",
  "category": "B",
  "field": "scoring_criteria",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '服务'",
  "forbidden_pattern": "(?:服务方案.*综合.*评审|根据.*服务.*质量.*给分|根据.*服务.*水平.*打分|服务.*方案.*一般)",
  "forbidden_message": "服务方案评分使用模糊表述，须量化为具体指标",
  "message": "服务类项目评分须有明确量化的评审标准",
  "applicable_scope": {"project_type": ["服务"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["服务方案","服务质量","服务水平"], "semantic": "存在服务方案评分"},
  "risk_level": "high",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第三十四条"}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词+量化评估"},
  "suggestion": "将服务方案的评分细化为可量化指标：如服务响应时间、人员配置完整度、应急预案完善度等",
  "example_bad": "服务方案（15分）：根据服务方案的完善程度和可行性综合打分",
  "example_good": "服务方案（15分）：含详细服务流程5分、人员配置方案4分、应急处理方案3分、质量保证措施3分"
},
{
  "rule_id": "R605",
  "rule_name": "服务类不得要求特定认证体系",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '服务'",
  "forbidden_pattern": "(?:须通过.*ISO.*认证|须取得.*特定.*认证|须持有.*指定.*证书|须获得.*认证.*资[质])",
  "forbidden_message": "要求与项目无关的特定认证体系限制竞争",
  "message": "服务类资质要求不得限定特定认证体系",
  "applicable_scope": {"project_type": ["服务"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["认证","ISO","资质证书","资格"], "semantic": "存在认证体系要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "认证要求应限于国家强制性认证或与项目直接相关的认证",
  "example_bad": "投标人须通过ISO 28000供应链安全管理体系认证（与物业服务无关）",
  "example_good": "投标人须具有物业管理资质证书"
},
{
  "rule_id": "R606",
  "rule_name": "服务期限须合理设定",
  "category": "C",
  "field": "bid_rejection_conditions",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '服务'",
  "forbidden_pattern": "(?:服务[期][限].*\\d{2,}\\s*[年]|合[同][期][限].*\\d{2,}\\s*[年]|合同.*不少于.*\\d{2,}\\s*[年])",
  "forbidden_message": "服务期限过长限制市场竞争",
  "message": "服务类项目合同期限应合理设定",
  "applicable_scope": {"project_type": ["服务"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["服务期限","合同期限","服务期"], "semantic": "存在服务期限要求"},
  "risk_level": "low",
  "regulation_basis": [{"title": "财政部关于推进和完善服务项目政府采购有关问题的通知", "article": "财库〔2014〕37号"}],
  "audit_method": {"type": "keyword+numeric", "pattern": "关键词+年限检测"},
  "suggestion": "服务合同期限一般不超过3年，采购需求具有相对固定性、延续性的可一次签订不超过3年的合同",
  "example_bad": "物业服务合同期限10年",
  "example_good": "物业服务合同期限3年（每年考核合格后续签）"
},
{
  "rule_id": "R607",
  "rule_name": "服务类不得要求派驻人员特定学历",
  "category": "A",
  "field": "qualification_requirements",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "project_type == '服务'",
  "forbidden_pattern": "(?:派驻.*人员.*学历.*[须必].*\\w{2,}|项目经理.*学历.*[须必].*\\w{2,}|本科.*学历.*必须|研究生.*学历.*必须)",
  "forbidden_message": "将特定学历作为派驻人员准入条件限制竞争",
  "message": "服务类人员要求不得限定特定学历层次",
  "applicable_scope": {"project_type": ["服务"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["学历","学位","本科","研究生"], "semantic": "存在学历要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第二十条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "改为能力要求而非学历要求，如'具备XX年以上相关经验'或'持有XX职业资格证书'",
  "example_bad": "派驻保洁主管须具有全日制本科及以上学历",
  "example_good": "派驻保洁主管须具有2年以上物业管理经验，持有物业管理相关证书"
}
```

- [ ] **Step 2: 验证规则 JSON — 72条**

```bash
python3 -c "import json; f=open('rules/compliance_rules.json'); d=json.load(f); f.close(); print(f'OK: {len(d[\"rules\"])} rules')"
```
Expected: `OK: 72 rules`

- [ ] **Step 3: 在 forbidden_words.json 中新增行业维度**

在 `patterns` 对象中新增 3 个维度：

**`construction_bias`（工程建设排他）**：

```json
"construction_bias": {
  "label": "工程建设排他",
  "description": "工程建设类招标中指定建材品牌、施工工艺等排他性要求",
  "severity": "critical",
  "risk_level": "严重",
  "regex_list": [
    {
      "id": "FORB-G01",
      "pattern": "须采用.{0,5}品牌.*[材][料]|指定.{0,5}品牌.*施工",
      "message": "在施工要求中指定建材品牌，构成排他性条款（R407）",
      "weight": 25,
      "law_ref": "《招标投标法实施条例》第三十二条",
      "suggestion": "改用性能指标而非指定品牌，或列出至少3个同等档次品牌"
    },
    {
      "id": "FORB-G02",
      "pattern": "资质.*特级|特级资质|资质等级.*过高",
      "message": "资质等级要求可能与项目规模不匹配（R401）",
      "weight": 20,
      "law_ref": "《建筑业企业资质管理规定》",
      "suggestion": "按建筑业企业资质标准合理设定资质等级"
    },
    {
      "id": "FORB-G03",
      "pattern": "工期.*不超过.*\\d{1,2}\\s*[日天]|工期.*少于.*\\d{1,2}\\s*[日天]",
      "message": "工期要求过短可能压缩合理工期（R404）",
      "weight": 15,
      "law_ref": "《建设工程质量管理条例》第十条",
      "suggestion": "工期设定应参考定额工期"
    },
    {
      "id": "FORB-G04",
      "pattern": "项目经理.*业绩.*超过.*\\d{4,}\\s*万|建造师.*业绩.*[超]",
      "message": "项目经理业绩要求超过项目规模（R408）",
      "weight": 15,
      "law_ref": "《招标投标法实施条例》第三十二条",
      "suggestion": "项目经理业绩要求应与本项目规模相当"
    },
    {
      "id": "FORB-G05",
      "pattern": "履约保证金.*超过.*10%|履约保证金.*合同.*价.*\\d{2,}%",
      "message": "履约保证金比例超过法定上限10%（R405）",
      "weight": 20,
      "law_ref": "《招标投标法实施条例》第五十八条",
      "suggestion": "将履约保证金调整至不超过中标合同金额的10%"
    }
  ]
}
```

**`it_spec_lock`（IT参数锁定）**：

```json
"it_spec_lock": {
  "label": "IT参数锁定",
  "description": "IT设备采购中通过技术参数、芯片型号等变相锁定品牌",
  "severity": "critical",
  "risk_level": "严重",
  "regex_list": [
    {
      "id": "FORB-H01",
      "pattern": "Intel\\s*(Core|Xeon)|AMD\\s*(Ryzen|EPYC)|龙芯.*必须|飞腾.*必须",
      "message": "技术参数中指定CPU品牌/型号，构成排他性条款（R501）",
      "weight": 25,
      "law_ref": "《政府采购法实施条例》第二十条",
      "suggestion": "改用性能指标描述，如CPU主频≥3.0GHz"
    },
    {
      "id": "FORB-H02",
      "pattern": "整机.*原厂.*认证|原厂.*整机.*检测|原厂.*出厂.*报告",
      "message": "要求整机原厂认证，限制代理商参与（R502）",
      "weight": 20,
      "law_ref": "《政府采购法实施条例》第二十条",
      "suggestion": "取消整机原厂认证要求，允许同等品质保证"
    },
    {
      "id": "FORB-H03",
      "pattern": "Oracle.*[版][本]|SQL\\s*Server.*[版][本]|指定.*软件.*版本",
      "message": "软件授权要求限定特定品牌和版本（R503）",
      "weight": 20,
      "law_ref": "《政府采购法实施条例》第二十条",
      "suggestion": "改为功能要求：支持XX功能或同等功能的软件均可"
    },
    {
      "id": "FORB-H04",
      "pattern": "与.*现有.*\\S*平台.*无缝|与.*现有.*\\S*系统.*对接",
      "message": "以系统对接为由锁定特定品牌（R504）",
      "weight": 20,
      "law_ref": "《政府采购法实施条例》第二十条",
      "suggestion": "明确对接标准协议，不限定特定品牌"
    },
    {
      "id": "FORB-H05",
      "pattern": "须.*指定.*检测.*机构.*报告|须.*特定.*实验室.*报告",
      "message": "限定检测报告出具机构，限制竞争（R507）",
      "weight": 15,
      "law_ref": "《政府采购法》第二十二条",
      "suggestion": "改为具有CMA/CNAS资质的第三方检测机构均可"
    }
  ]
}
```

**`service_restrict`（服务限制）**：

```json
"service_restrict": {
  "label": "服务限制",
  "description": "服务类招标中通过人员学历、认证体系、本地化等变相限制竞争",
  "severity": "high",
  "risk_level": "高",
  "regex_list": [
    {
      "id": "FORB-I01",
      "pattern": "本地.*服务.*必须|须.*在.*本.*有.*服务.*网点|项目所在地.*须有.*机构",
      "message": "将本地化服务作为必须条件构成地域歧视（R603）",
      "weight": 25,
      "law_ref": "《政府采购法实施条例》第二十条",
      "suggestion": "改为中标后承诺设立服务网点或作为加分项"
    },
    {
      "id": "FORB-I02",
      "pattern": "派驻.*人员.*学历.*必须|项目经理.*学历.*须|本科.*学历.*为.*必须",
      "message": "将特定学历作为准入条件限制竞争（R607）",
      "weight": 15,
      "law_ref": "《政府采购法实施条例》第二十条",
      "suggestion": "改为能力要求而非学历要求"
    },
    {
      "id": "FORB-I03",
      "pattern": "须通过.*ISO.*认证.*[与].*无关|须取得.*指定.*认证.*体系",
      "message": "要求与项目无关的特定认证体系（R605）",
      "weight": 15,
      "law_ref": "《政府采购法实施条例》第二十条",
      "suggestion": "认证要求应限于与项目直接相关的认证"
    },
    {
      "id": "FORB-I04",
      "pattern": "业绩.*不少于.*\\d{2,}\\s*[个项]|类似.*合同.*不少于.*\\d{2,}",
      "message": "业绩数量要求过高限制中小企业（R602）",
      "weight": 20,
      "law_ref": "《政府采购法实施条例》第二十条",
      "suggestion": "将业绩要求调整至合理水平"
    },
    {
      "id": "FORB-I05",
      "pattern": "服务.*方案.*综合.*评审|根据.*服务.*质量.*给分|根据.*服务.*水平.*打分",
      "message": "服务方案评分使用模糊表述（R604）",
      "weight": 20,
      "law_ref": "《政府采购法实施条例》第三十四条",
      "suggestion": "将服务方案评分细化为可量化指标"
    }
  ]
}
```

- [ ] **Step 4: 验证 forbidden_words.json**

```bash
python3 -c "import json; f=open('rules/forbidden_words.json'); d=json.load(f); f.close(); dims=list(d['patterns'].keys()); print(f'OK: {len(dims)} dimensions')"
```
Expected: `OK: 16 dimensions` (13 + 3 new)

- [ ] **Step 5: 在 parameter_bias_rules.json 中新增 3 种检测模式**

在 `violation_patterns` 对象中新增：

```json
"construction_exclusivity": {
  "severity": "critical",
  "risk_level": "严重",
  "description": "工程建设参数排他：检测施工要求中是否指定主要建材品牌、施工工艺等排他性内容",
  "keywords": [
    "须采用*品牌",
    "指定*品牌*材料",
    "钢材须为*品牌",
    "水泥指定",
    "电缆指定*品牌",
    "涂料指定*品牌"
  ],
  "check_fields": ["technical_params"],
  "check_logic": "搜索施工技术参数中是否含指定主要建材品牌的表述",
  "suggestion": "改用性能指标而非指定品牌，或列出至少3个同等档次品牌并注明'或同等品'",
  "rule_id": "R407"
},
"it_brand_lock": {
  "severity": "critical",
  "risk_level": "严重",
  "description": "IT品牌锁定：检测IT设备技术参数是否通过芯片型号、整机认证、软件授权等构成组合品牌锁定",
  "keywords": [
    "Intel Core",
    "AMD Ryzen",
    "整机原厂认证",
    "原厂出厂检测",
    "指定软件版本",
    "无缝对接",
    "Oracle*版本",
    "SQL Server*版本"
  ],
  "check_fields": ["technical_params"],
  "check_logic": "搜索IT设备技术参数中是否含芯片型号指定、整机认证要求、软件版本锁定等组合锁定模式",
  "suggestion": "使用性能指标代替品牌型号，确保至少3个品牌可满足",
  "rule_id": "R501"
},
"service_cert_lock": {
  "severity": "high",
  "risk_level": "高",
  "description": "服务认证排他：检测服务类招标中是否通过认证体系、学历要求、本地化等组合限制竞争",
  "keywords": [
    "ISO*认证",
    "特定认证体系",
    "学历必须",
    "本科及以上",
    "研究生学历",
    "本地服务必须",
    "须在*本*有*服务",
    "须在*本*设有"
  ],
  "check_fields": ["qualification_requirements"],
  "check_logic": "搜索服务类招标资格要求中是否含特定认证体系、学历限制、本地化服务等组合排他条件",
  "suggestion": "认证要求限于国家强制性认证或与项目直接相关，学历要求改为能力要求，本地化服务改为中标后承诺",
  "rule_id": "R603"
}
```

- [ ] **Step 6: 验证 parameter_bias_rules.json**

```bash
python3 -c "import json; f=open('rules/parameter_bias_rules.json'); d=json.load(f); f.close(); vp=list(d['violation_patterns'].keys()); print(f'OK: {len(vp)} patterns')"
```
Expected: `OK: 16 patterns` (13 + 3 new)

- [ ] **Step 7: 新增测试用例**

在 `backend/tests/test_rule_engine.py` 末尾添加：

```python

class TestBatch2IndustryRules:
    """验证 25 条行业专项规则正确追加"""

    def test_r401_construction_qualification(self):
        """R401: 施工资质等级与项目规模匹配"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        r401 = next(r for r in data["rules"] if r["rule_id"] == "R401")
        assert r401["condition"] == "project_type == '工程'"
        assert r401["rule_type"] == "forbidden_pattern"
        assert "资质" in r401["forbidden_pattern"]

    def test_r403_safety_permit_required(self):
        """R403: 安全生产许可证必须存在"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        r403 = next(r for r in data["rules"] if r["rule_id"] == "R403")
        assert r403["rule_type"] == "required"
        assert r403["required"] is True
        assert "安全生产" in r403["pattern"]

    def test_r407_no_brand_specification_in_construction(self):
        """R407: 不得在施工要求中指定主要建材品牌"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        r407 = next(r for r in data["rules"] if r["rule_id"] == "R407")
        assert r407["risk_level"] == "critical"
        assert "品牌" in r407["forbidden_pattern"]

    def test_r501_no_chip_model_specification(self):
        """R501: IT设备技术参数不得指定芯片型号"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        r501 = next(r for r in data["rules"] if r["rule_id"] == "R501")
        assert r501["condition"] == "project_type == '采购'"
        assert "Intel" in r501["forbidden_pattern"]

    def test_r603_no_local_service_as_qualification(self):
        """R603: 服务类不得要求本地化服务作为资格条件"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        r603 = next(r for r in data["rules"] if r["rule_id"] == "R603")
        assert r603["risk_level"] == "critical"
        assert r603["condition"] == "project_type == '服务'"

    def test_all_25_industry_rules_present(self):
        """验证 25 条行业规则均存在"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        expected_ids = (
            [f"R{40 + i}" for i in range(1, 11)]  # R401-R410
            + [f"R{50 + i}" for i in range(1, 9)]  # R501-R508
            + [f"R{60 + i}" for i in range(1, 8)]  # R601-R607
        )
        for rid in expected_ids:
            rule = next((r for r in data["rules"] if r["rule_id"] == rid), None)
            assert rule is not None, f"{rid} 缺失"
            # 行业规则必须有 condition 字段
            if rule["rule_id"] not in ("R606",):  # R606 为通用 low 风险规则
                assert "condition" in rule or rule.get("rule_type") != "forbidden_pattern", \
                    f"{rid} 缺少 condition"

    def test_total_rules_after_batch2(self):
        """Batch 2 后规则总数为 72"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        assert len(data["rules"]) == 72, f"Expected 72 rules, got {len(data['rules'])}"
```

- [ ] **Step 8: 运行测试**

```bash
cd backend && uv run pytest tests/test_rule_engine.py::TestBatch2IndustryRules -v
```
Expected: 7 PASS

- [ ] **Step 9: 运行全量回归**

```bash
cd backend && uv run pytest tests/test_rule_engine.py tests/test_parameter_bias.py tests/test_rules_admin.py -v
```
Expected: ALL PASS

- [ ] **Step 10: 提交**

```bash
git add rules/compliance_rules.json rules/forbidden_words.json rules/parameter_bias_rules.json backend/tests/test_rule_engine.py
git commit -m "feat: add batch 2 — 25 industry-specific rules (47→72)"
```

---

### Task 3: Batch 3 — 条件变体规则（10条）

**Files:**
- Modify: `rules/compliance_rules.json`
- Modify: `backend/tests/test_rule_engine.py`
- Modify: `rules/versions/manifest.json`

**Goal:** 新增 10 条采购方式触发的条件变体规则。累计 82 条。

- [ ] **Step 1: 追加 10 条条件变体规则**

在 `compliance_rules.json` 的 `rules` 数组末尾（`R607` 之后）追加规则：

```json
{
  "rule_id": "R114_C",
  "rule_name": "询价采购须至少3家供应商报价",
  "category": "C",
  "field": "bid_rejection_conditions",
  "rule_type": "pattern_required",
  "required": true,
  "condition": "evaluation_method == '询价'",
  "pattern": "(?:不少于.*3.*[家个].*供应商.*报价|至少.*3.*[家个].*报价|询价.*不少于.*3.*[家个])",
  "pattern_message": "询价采购须从不少于3家供应商的报价中确定成交供应商",
  "message": "询价采购须确保至少3家供应商报价",
  "applicable_scope": {"project_type": ["采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["询价","报价","供应商"], "semantic": "存在询价采购方式"},
  "risk_level": "high",
  "regulation_basis": [{"title": "政府采购法", "article": "第四十条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "明确询价对象不少于3家，且须形成书面询价记录",
  "example_bad": "本项目采用询价方式采购",
  "example_good": "本项目采用询价方式采购，向不少于3家供应商发出询价通知书"
},
{
  "rule_id": "R115_C",
  "rule_name": "竞争性谈判须有谈判记录",
  "category": "C",
  "field": "bid_rejection_conditions",
  "rule_type": "pattern_required",
  "required": true,
  "condition": "evaluation_method == '竞争性谈判'",
  "pattern": "(?:谈判.*记[录要]|谈判.*小组.*记[录要]|竞争性谈判.*记[录要])",
  "pattern_message": "竞争性谈判须有完整的谈判记录",
  "message": "竞争性谈判采购须有完整的谈判记录",
  "applicable_scope": {"project_type": ["工程","服务","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["竞争性谈判","谈判记录"], "semantic": "存在竞争性谈判方式"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购法", "article": "第三十八条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "明确谈判记录要求：谈判小组应当对谈判过程进行记录，谈判记录须经谈判小组全体成员签字确认",
  "example_bad": "本项目采用竞争性谈判方式",
  "example_good": "竞争性谈判的谈判记录须经谈判小组全体成员签字确认"
},
{
  "rule_id": "R116_C",
  "rule_name": "单一来源采购须有专家论证意见",
  "category": "C",
  "field": "evaluation_method",
  "rule_type": "pattern_required",
  "required": true,
  "condition": "evaluation_method == '单一来源'",
  "pattern": "(?:专家.*论[证][意][见]|专家.*审查.*意见|单一来源.*论[证].*专[家]|唯一供应商.*[公][示])",
  "pattern_message": "单一来源采购须经过专家论证并公示",
  "message": "单一来源采购须附专家论证意见和公示截图",
  "applicable_scope": {"project_type": ["采购","服务"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["单一来源","唯一供应商","专家论证"], "semantic": "存在单一来源采购方式"},
  "risk_level": "critical",
  "regulation_basis": [{"title": "政府采购法", "article": "第三十一条"}, {"title": "政府采购非招标采购方式管理办法（74号令）", "article": "第三十八条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "须附专家论证意见：明确适用单一来源采购的具体理由，以及唯一供应商的说明",
  "example_bad": "本项目采用单一来源采购方式",
  "example_good": "本项目采用单一来源采购方式。理由：只能从唯一供应商处采购（专家组3人已论证并公示，公示期不少于5个工作日）"
},
{
  "rule_id": "R117_C",
  "rule_name": "邀请招标须有邀请理由说明",
  "category": "C",
  "field": "evaluation_method",
  "rule_type": "pattern_required",
  "required": true,
  "condition": "evaluation_method == '邀请招标'",
  "pattern": "(?:邀请招标.*[理][由]|邀请.*供应商.*[理][由]|邀请.*[原][因]|资格预审)",
  "pattern_message": "邀请招标须说明采用邀请招标的理由和邀请对象的选择依据",
  "message": "邀请招标须说明采用理由和邀请对象选择依据",
  "applicable_scope": {"project_type": ["工程","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["邀请招标","资格预审"], "semantic": "存在邀请招标方式"},
  "risk_level": "high",
  "regulation_basis": [{"title": "招标投标法实施条例", "article": "第八条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "说明采用邀请招标的理由（技术复杂/有特殊要求/涉及商业秘密等），以及邀请对象的选择依据",
  "example_bad": "本项目采用邀请招标方式",
  "example_good": "本项目采用邀请招标方式。理由：技术复杂，只有少量潜在投标人可供选择。已从资格预审合格名单中邀请不少于3家投标人"
},
{
  "rule_id": "R118_C",
  "rule_name": "竞争性磋商须有磋商纪要",
  "category": "C",
  "field": "bid_rejection_conditions",
  "rule_type": "pattern_required",
  "required": true,
  "condition": "evaluation_method == '竞争性磋商'",
  "pattern": "(?:磋商.*纪要|磋商.*记录|磋商.*小[组].*记[录要]|竞争性磋商.*记录)",
  "pattern_message": "竞争性磋商须有完整的磋商纪要",
  "message": "竞争性磋商须有完整磋商纪要",
  "applicable_scope": {"project_type": ["工程","服务","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["竞争性磋商","磋商纪要"], "semantic": "存在竞争性磋商方式"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购竞争性磋商采购方式管理暂行办法", "article": "第二十六条"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "明确磋商纪要要求：磋商小组应当对磋商过程进行记录，磋商纪要须经磋商小组全体成员签字确认",
  "example_bad": "本项目采用竞争性磋商方式",
  "example_good": "竞争性磋商纪要须经磋商小组全体成员签字确认"
},
{
  "rule_id": "R119_B",
  "rule_name": "价格分权重须符合法定范围（综合评分法）",
  "category": "B",
  "field": "scoring_criteria",
  "rule_type": "conditional",
  "required": false,
  "condition": "evaluation_method == '综合评分法'",
  "forbidden_pattern": "(?:价格分.*[1-9]\\s*[分]|价格.*权[重].*[1-9]\\s*%|价格.*占[比].*[1-9]\\s*%)",
  "forbidden_message": "价格分权重须符合法定范围：货物≥30%，服务≥10%",
  "message": "综合评分法价格分权重须符合法定比例",
  "applicable_scope": {"project_type": ["工程","服务","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["价格分","价格权重","综合评分法"], "semantic": "存在综合评分法价格权重"},
  "risk_level": "high",
  "regulation_basis": [{"title": "政府采购货物和服务招标投标管理办法（87号令）", "article": "第五十五条"}],
  "audit_method": {"type": "keyword+numeric", "pattern": "分值提取+比例计算"},
  "suggestion": "货物项目价格分权重≥30%，服务项目价格分权重≥10%",
  "example_bad": "价格分：10分（货物项目价格分过低）",
  "example_good": "价格分：30分（货物项目价格分不低于30%）"
},
{
  "rule_id": "R120_B",
  "rule_name": "资格条件不得作为评分因素（综合评分法）",
  "category": "B",
  "field": "scoring_criteria",
  "rule_type": "forbidden_pattern",
  "required": false,
  "condition": "evaluation_method == '综合评分法'",
  "forbidden_pattern": "(?:资质.*等级.*得分|注册资本.*评分|成立.*年限.*打分|本地.*企业.*加分)",
  "forbidden_message": "资格条件不得作为评分因素。已设为资格条件的，不得同时作为评审因素。",
  "message": "已设为资格条件的不得同时作为评分因素",
  "applicable_scope": {"project_type": ["工程","服务","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["评分","得分","加分","资格","资质"], "semantic": "存在资格条件作为评分因素"},
  "risk_level": "critical",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第三十四条"}, {"title": "政府采购货物和服务招标投标管理办法", "article": "第五十五条"}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+交叉比对"},
  "suggestion": "将资格条件从评分因素中移除，评分因素仅限于技术、服务、价格等与项目直接相关的条件",
  "example_bad": "综合评分标准：资质等级一级得5分，二级得3分；本地企业加3分",
  "example_good": "综合评分标准：技术方案40分，业绩15分，服务方案15分，价格30分"
},
{
  "rule_id": "R121_A",
  "rule_name": "中小企业须有预留份额或价格扣除说明",
  "category": "A",
  "field": "scoring_criteria",
  "rule_type": "semantic_required",
  "required": false,
  "condition": "budget >= 2000000",
  "semantic_keywords": ["中小企业","小微企业","价格扣除","预留份额","专门面向"],
  "message": "预算≥200万元的项目须说明中小企业政策执行方式",
  "applicable_scope": {"project_type": ["采购","服务"], "region": ["全国"], "amount_range": "200万元以上"},
  "trigger_condition": {"keywords": ["中小企业","小微企业","价格扣除"], "semantic": "存在中小企业政策"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购促进中小企业发展管理办法", "article": "第八条"}, {"title": "财政部关于进一步加大政府采购支持中小企业力度的通知（2022）", "article": ""}],
  "audit_method": {"type": "keyword+semantic", "pattern": "关键词检测+条件判断"},
  "suggestion": "明确：专门面向中小企业采购，或非专门面向时对小微企业报价给予10%-20%的价格扣除",
  "example_bad": "（预算400万元的货物采购，招标文件中未提及中小企业政策）",
  "example_good": "本项目非专门面向中小企业采购，但对符合条件的小微企业报价给予15%的价格扣除"
},
{
  "rule_id": "R122_C",
  "rule_name": "投标保证金不得超过预算金额的2%",
  "category": "C",
  "field": "bid_rejection_conditions",
  "rule_type": "forbidden_pattern",
  "required": false,
  "forbidden_pattern": "(?:投标保证金.*\\d{2,}\\s*%|投标保证金.*超过.*2%|保证金.*比例为.*\\d{2,})",
  "forbidden_message": "投标保证金不得超过采购项目预算金额的2%",
  "message": "投标保证金不得超过预算金额的2%",
  "applicable_scope": {"project_type": ["采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["投标保证金","保证金"], "semantic": "存在投标保证金要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购法实施条例", "article": "第三十三条"}],
  "audit_method": {"type": "keyword+numeric", "pattern": "关键词+比例检测"},
  "suggestion": "将投标保证金比例调整至不超过预算金额的2%，或按固定金额收取",
  "example_bad": "投标保证金：预算金额的5%",
  "example_good": "投标保证金：人民币贰万元整（不超过预算金额的2%）"
},
{
  "rule_id": "R123_D",
  "rule_name": "中标公示须包含评审专家名单",
  "category": "D",
  "field": "bid_rejection_conditions",
  "rule_type": "pattern_required",
  "required": true,
  "pattern": "(?:评审专家.*名[单]|评标.*委员会.*名[单]|评审.*小[组].*名[单]|专家.*名[单].*公[示])",
  "pattern_message": "中标结果公告须包含评审专家名单",
  "message": "中标公示须包含评审专家名单",
  "applicable_scope": {"project_type": ["工程","服务","采购"], "region": ["全国"], "amount_range": "全部"},
  "trigger_condition": {"keywords": ["中标公示","结果公告","中标结果"], "semantic": "存在中标公示要求"},
  "risk_level": "medium",
  "regulation_basis": [{"title": "政府采购信息发布管理办法", "article": ""}, {"title": "关于做好政府采购信息公开工作的通知", "article": "财库〔2015〕135号"}],
  "audit_method": {"type": "keyword", "pattern": "关键词检测"},
  "suggestion": "在中标结果公告中明确包含评审专家名单及采购人代表信息",
  "example_bad": "中标结果将在指定媒体公示",
  "example_good": "中标结果公告应包括：项目名称、中标人名称、中标金额、评审专家名单、公告期限"
}
```

更新 `last_updated` 为 `"2026-06-06"`。

- [ ] **Step 2: 验证规则 JSON — 82条**

```bash
python3 -c "import json; f=open('rules/compliance_rules.json'); d=json.load(f); f.close(); print(f'OK: {len(d[\"rules\"])} rules')"
```
Expected: `OK: 82 rules`

- [ ] **Step 3: 新增测试用例**

在 `backend/tests/test_rule_engine.py` 末尾添加：

```python

class TestBatch3ConditionVariants:
    """验证 10 条条件变体规则正确追加"""

    def test_r116_c_single_source_expert_review(self):
        """R116_C: 单一来源须有专家论证"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        r116 = next(r for r in data["rules"] if r["rule_id"] == "R116_C")
        assert r116["condition"] == "evaluation_method == '单一来源'"
        assert r116["risk_level"] == "critical"
        assert "专家" in r116["pattern"]

    def test_r120_b_qualification_not_scoring_factor(self):
        """R120_B: 资格条件不得作为评分因素"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        r120 = next(r for r in data["rules"] if r["rule_id"] == "R120_B")
        assert r120["condition"] == "evaluation_method == '综合评分法'"
        assert r120["risk_level"] == "critical"
        assert "资格条件" in r120["forbidden_message"]

    def test_r121_a_sme_policy_for_large_budget(self):
        """R121_A: 预算≥200万须有中小企业政策"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        r121 = next(r for r in data["rules"] if r["rule_id"] == "R121_A")
        assert r121["condition"] == "budget >= 2000000"
        assert "中小企业" in r121.get("semantic_keywords", [""])[0] or "中小企业" in str(r121)

    def test_all_10_variant_rules_present(self):
        """验证 10 条条件变体规则均存在"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        expected_ids = [
            "R114_C", "R115_C", "R116_C", "R117_C", "R118_C",
            "R119_B", "R120_B", "R121_A", "R122_C", "R123_D",
        ]
        for rid in expected_ids:
            rule = next((r for r in data["rules"] if r["rule_id"] == rid), None)
            assert rule is not None, f"{rid} 缺失"
            assert "rule_name" in rule
            assert "rule_type" in rule

    def test_total_rules_after_batch3(self):
        """Batch 3 后规则总数为 82"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        assert len(data["rules"]) == 82, f"Expected 82 rules, got {len(data['rules'])}"

    def test_condition_rules_count(self):
        """条件规则数量从 8 增加到 18+"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        conditional = [r for r in data["rules"] if r.get("condition")]
        assert len(conditional) >= 18, f"Expected >=18 conditional rules, got {len(conditional)}"

    def test_rule_id_uniqueness(self):
        """验证无重复 rule_id"""
        import json, os
        rules_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "rules", "compliance_rules.json"
        )
        with open(rules_path) as f:
            data = json.load(f)
        ids = [r["rule_id"] for r in data["rules"]]
        assert len(ids) == len(set(ids)), f"重复 rule_id: {[x for x in ids if ids.count(x) > 1]}"
```

- [ ] **Step 4: 更新 rules/versions/manifest.json**

在 `rules/versions/manifest.json` 中添加新版本记录：

```json
{
  "version": "3.0.0",
  "date": "2026-06-06",
  "description": "规则库大幅扩展：35→82条。新增hlgs通报资产规则12条、行业专项规则25条、条件变体规则10条。同步扩展禁用词库(+3维度)和参数倾向性规则库(+6模式)。",
  "rules_count": 82,
  "categories": {
    "A": 25,
    "B": 25,
    "C": 17,
    "D": 9,
    "E": 6
  },
  "changes": [
    "Batch 1: 移植hlgs通报资产规则12条 (R301-R312)",
    "Batch 2: 工程建设规则10条 (R401-R410)",
    "Batch 2: IT设备采购规则8条 (R501-R508)",
    "Batch 2: 服务类规则7条 (R601-R607)",
    "Batch 3: 条件变体规则10条 (R114_C-R123_D)",
    "禁用词库新增3个维度: construction_bias, it_spec_lock, service_restrict",
    "参数倾向性规则库新增6种检测模式"
  ]
}
```

- [ ] **Step 5: 运行测试**

```bash
cd backend && uv run pytest tests/test_rule_engine.py::TestBatch3ConditionVariants -v
```
Expected: 7 PASS

- [ ] **Step 6: 运行全量回归测试**

```bash
cd backend && uv run pytest tests/ -v --tb=short --ignore=tests/test_llm_integration.py
```
Expected: ALL PASS (test_llm_integration 需要本地 LLM 服务，跳过)

- [ ] **Step 7: 提交**

```bash
git add rules/compliance_rules.json backend/tests/test_rule_engine.py rules/versions/manifest.json
git commit -m "feat: add batch 3 — 10 condition-variant rules (72→82)"
```

---

### Task 4: 最终验证与汇总

**Files:** (无代码变更，仅验证)

- [ ] **Step 1: 验证最终规则数量**

```bash
python3 << 'EOF'
import json
with open('rules/compliance_rules.json') as f:
    data = json.load(f)
print(f"总规则数: {len(data['rules'])}")

# 按类别统计
from collections import Counter
cats = Counter(r['category'] for r in data['rules'])
print(f"\n按类别:")
for cat in sorted(cats):
    print(f"  {cat}: {cats[cat]}条")

# 按规则类型统计
types = Counter(r['rule_type'] for r in data['rules'])
print(f"\n按规则类型:")
for t, c in types.most_common():
    print(f"  {t}: {c}条")

# 条件规则
cond = [r for r in data['rules'] if r.get('condition')]
print(f"\n条件规则: {len(cond)}条")

# 风险等级分布
levels = Counter(r.get('risk_level', '?') for r in data['rules'])
print(f"\n按风险等级:")
for l, c in levels.most_common():
    print(f"  {l}: {c}条")

# rule_id 唯一性
ids = [r['rule_id'] for r in data['rules']]
assert len(ids) == len(set(ids)), f"重复ID: {[x for x in ids if ids.count(x) > 1]}"
print(f"\nrule_id 唯一性: OK ({len(ids)}个唯一ID)")
EOF
```
Expected:
```
总规则数: 82
条件规则: ≥18条
rule_id 唯一性: OK
```

- [ ] **Step 2: 验证规则引擎可正常加载所有关联规则文件**

```bash
cd backend && uv run python -c "
from app.engine.rule_engine import RuleEngine
engine = RuleEngine()
print(f'规则引擎加载规则总数: {len(engine.rules)}')
types = {r.type for r in engine.rules}
print(f'规则类型: {types}')
forbidden = [r for r in engine.rules if r.type == 'forbidden']
print(f'禁用词规则: {len(forbidden)}条')
print('规则引擎加载 OK')
"
```
Expected: 规则引擎加载成功，禁用词规则数量增加（新增3个维度×5条 = +15）

- [ ] **Step 3: 验证参数倾向性检测加载新规则**

```bash
cd backend && uv run python -c "
from app.engine.parameter_bias import ParameterBiasDetector
detector = ParameterBiasDetector()
patterns = detector._patterns
print(f'参数倾向性检测模式数: {len(patterns.get(\"violation_patterns\", patterns))}')
print('参数倾向性检测加载 OK')
"
```

- [ ] **Step 4: 运行最终全量回归测试（排除LLM集成测试）**

```bash
cd backend && uv run pytest tests/ -v --tb=short --ignore=tests/test_llm_integration.py
```
Expected: ALL PASS

- [ ] **Step 5: 提交最终更新**

```bash
git add rules/compliance_rules.json rules/forbidden_words.json rules/parameter_bias_rules.json rules/versions/manifest.json backend/tests/test_rule_engine.py
git commit -m "feat: complete rules expansion — 35→82 rules with tests"
```

---

## 完成检查清单

- [ ] Batch 1 (12条hlgs通报规则) 追加到 compliance_rules.json
- [ ] Batch 1 forbidden_words 新增 case_alert 维度
- [ ] Batch 1 parameter_bias_rules 新增 3 种案例驱动模式
- [ ] Batch 2 (25条行业专项规则) 追加到 compliance_rules.json
- [ ] Batch 2 forbidden_words 新增 3 个行业维度
- [ ] Batch 2 parameter_bias_rules 新增 3 种检测模式
- [ ] Batch 3 (10条条件变体规则) 追加到 compliance_rules.json
- [ ] manifest.json 版本记录更新
- [ ] 所有规则 rule_id 唯一性验证
- [ ] 规则引擎可正常加载所有关联规则文件
- [ ] 参数倾向性检测加载新规则
- [ ] 全部测试通过（排除需本地LLM的 integration 测试）
- [ ] 最终规则数 = 82 条
