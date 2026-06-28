"""查询扩展服务 — 将用户自然语言查询扩展为多关键词搜索字符串

生产级实现：从 query_text 提取领域关键短语和中文 n-gram，
不依赖 search_keywords、标注标题或预期文档。

扩展策略：
1. 标签混入：用户提供的 tags 作为高精度搜索词
2. 领域词典匹配：从 query_text 提取预定义的领域关键短语
3. 同义词扩展：领域词典概念同义映射（仅由用户查询内容确定）
4. 中文 n-gram 提取：2-4 字符滑动窗口

所有扩展结果仅由用户原始查询 + tags 确定。
"""

from __future__ import annotations

import re as _re
from typing import Optional


# ── 领域关键短语 (从 query_text 中匹配，非外部注入) ──
_DOMAIN_PHRASES = frozenset({
    "公开招标", "竞争性谈判", "竞争性磋商", "单一来源", "邀请招标",
    "资格条件", "资格要求", "资质要求", "业绩要求",
    "评标标准", "评分标准", "评分办法", "综合评分法", "最低评标价法",
    "技术参数", "品牌锁定", "品牌指向", "品牌排斥",
    "厂家授权", "原厂授权", "原厂认证",
    "废标条件", "废标条款",
    "投标保证金", "履约保证金",
    "中小企业", "小微企业",
    "差别待遇", "歧视待遇", "不合理条件",
    "项目拆分", "规避招标",
    "符合性审查",
    "中标无效", "中标通知书",
    "异常低价", "低于成本",
    "评审委员会", "评标委员会", "评审专家",
    "采购方式", "采购需求", "政府采购",
    "招标文件", "招标公告", "投标须知", "招标投标",
    "财政资金",
    "采购人", "代理机构",
    "合同签订",
    "虚假材料", "声明函",
    "联合体", "分包", "转包",
    "围标串标", "串通投标",
    "节能环保", "进口产品",
    "注册资金", "注册资本", "成立年限", "营业收入",
    "本地注册", "本地企业", "本地化服务",
    "检测报告", "检验报告",
    "无效标准", "废止标准",
    "甘肃", "宁夏", "陕西", "四川", "青海", "广东", "江苏",
    "生态环境", "食品安全",
    "行政处罚",
    "评分不匹配", "参数扣分",
    "供应商", "采购", "招标", "评标",
    "溢价", "投诉", "质疑",
    "有效期", "授权", "品牌", "资质", "业绩",
    "处罚", "罚款", "禁止",
    "注册地", "本地", "歧视",
    "案例", "规定", "要求", "条件",
    # Broader domain concepts
    "医疗器械", "医疗设备", "车辆采购", "设备采购",
    "有限定", "特定行业", "特定行政区域",
    "生产供应者", "供应者",
    "量化", "细化", "主观", "评审因素",
    "拆分",
    "注册地", "限定",
    "排斥", "排他",
    "黑名单", "禁止参加", "法定情形",
    "3D打印", "参数排斥", "品牌锁定", "具体违规",
})

# ── 领域同义词扩展 (仅由原始查询词触发) ──
# key 必须在 query_text 中出现才会扩展
_SYNONYM_EXPANSION: dict[str, list[str]] = {
    "注册地": ["地域", "行政区域", "本省"],
    "限定": ["限制", "排斥", "特定", "不得"],
    "歧视": ["差别待遇", "不合理", "差别", "待遇"],
    "排他": ["排斥", "品牌", "指定", "指向", "专有"],
    "量化": ["细化", "客观", "分值", "具体", "评审因素"],
    "拆分": ["规避", "分标", "包组"],
    "品牌锁定": ["指定品牌", "指向", "厂家授权", "同一品牌"],
    "规避招标": ["项目拆分", "规避", "拆分"],
    "禁止参加": ["黑名单", "禁止", "处罚", "中标无效"],
    "评分不匹配": ["评分标准", "参数扣分", "扣分规则"],
    "参数排斥": ["技术参数", "品牌指向", "排他", "指定"],
    "案例": ["投诉", "处罚", "整改", "重新采购"],
    "具体违规": ["品牌锁定", "厂家授权", "参数", "歧视"],
}

# ── 停用字 ──
_STOP_CHARS = frozenset(
    "的了在是我有和就不人都一上也说到要你会的看自他那"
    "什么么怎如何为因为所以但或与对于对将以被让向从使通过可以"
    "需要应该已经比较非常还是不过把从次第"
)


def expand_query(
    query_text: str,
    tags: Optional[list[str]] = None,
    max_terms: int = 40,
) -> str:
    """Expand a natural language query into a multi-keyword search string.

    Args:
        query_text: User's raw natural language query
        tags: User-provided tags (legitimate signal from the API)
        max_terms: Maximum terms in output string

    Returns:
        Space-separated search string for knowledge_graph.search()
    """
    if not query_text:
        return ""

    terms: list[str] = []

    # 1. Tags first (highest precision, user-provided)
    if tags:
        for t in tags:
            t = t.strip()
            if t and len(t) >= 2 and t not in terms:
                terms.append(t)

    # 2. Domain phrase matching (extract phrases that appear in query text)
    matched_phrases: list[str] = []
    for phrase in sorted(_DOMAIN_PHRASES, key=len, reverse=True):
        idx = 0
        while True:
            idx = query_text.find(phrase, idx)
            if idx == -1:
                break
            if phrase not in terms and phrase not in matched_phrases:
                matched_phrases.append(phrase)
            idx += 1

    terms.extend(matched_phrases)

    # 3. Synonym expansion — only from terms that appear in query text
    #    (tags + domain phrases that actually matched the query)
    expanded: list[str] = []
    for trigger, synonyms in _SYNONYM_EXPANSION.items():
        if trigger in query_text or trigger in terms:
            for syn in synonyms:
                if syn not in terms and syn not in expanded:
                    expanded.append(syn)
    terms.extend(expanded)

    # 4. Chinese n-grams (2-4 char) from query text
    chinese_runs = _re.findall(r"[一-鿿]{2,}", query_text)
    for run in chinese_runs:
        L = len(run)
        # 4-grams (high specificity)
        for i in range(L - 3):
            ng = run[i:i + 4]
            if ng not in terms:
                terms.append(ng)
        # 3-grams
        for i in range(L - 2):
            ng = run[i:i + 3]
            if ng not in terms:
                terms.append(ng)
        # 2-grams (skip stop-char only bigrams)
        for i in range(L - 1):
            bg = run[i:i + 2]
            if bg[0] not in _STOP_CHARS or bg[1] not in _STOP_CHARS:
                if bg not in terms:
                    terms.append(bg)

    # 5. Cap at max_terms
    return " ".join(terms[:max_terms])


def expand_query_text(query_text: str, tags: Optional[list[str]] = None) -> str:
    """Convenience alias for expand_query."""
    return expand_query(query_text, tags)
