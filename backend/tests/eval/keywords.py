"""Chinese keyword extractor for retrieval queries.

Strategy: extract domain key phrases + all Chinese bigrams from query text.
Tags come first (highest precision), then key phrases, then bigrams (coverage).
All terms >= 2 characters to avoid single-character noise.
"""

import re

# ── Domain key phrases (multi-word expressions, kept intact) ──
_KEY_PHRASES = [
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
    "招标文件", "招标公告", "投标须知",
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
    "无效标准",
    "甘肃", "宁夏", "陕西", "四川", "青海", "广东", "江苏",
    "生态环境", "食品安全",
    "行政处罚",
    "无效的法定情形",
    "评分不匹配",
]

# ── Stop words (single chars that carry no retrieval signal) ──
_STOP_CHARS = set("的了在是我有和就不人都一上也说到要你会的看自这他那什么么怎么如何为因为所以但而或与对于对将以被让向从使通过一个可以需要应该已经比较非常还是不过把从次次第")


def extract_keywords(query_text: str, tags: list[str] | None = None, max_terms: int = 12) -> list[str]:
    """Extract search keywords from a Chinese query.

    Steps:
    1. Add tags (highest precision)
    2. Scan for domain key phrases (longest match first)
    3. For remaining Chinese text, extract ALL bigrams
    4. Deduplicate, keep terms >= 2 chars
    """
    keywords: list[str] = []

    # 1. Tags first
    if tags:
        for t in tags:
            t = t.strip()
            if len(t) >= 2:
                keywords.append(t)

    if not query_text:
        return list(dict.fromkeys(keywords))[:max_terms]

    text = query_text

    # 2. Extract domain key phrases (longest match first, non-overlapping)
    phrases_found = []
    for phrase in sorted(_KEY_PHRASES, key=len, reverse=True):
        idx = 0
        while True:
            idx = text.find(phrase, idx)
            if idx == -1:
                break
            phrases_found.append((idx, idx + len(phrase), phrase))
            idx += 1

    phrases_found.sort(key=lambda x: (x[0], -len(x[2])))
    kept_phrases: list[str] = []
    last_end = 0
    for start, end, phrase in phrases_found:
        if start >= last_end:
            kept_phrases.append(phrase)
            last_end = end

    keywords.extend(kept_phrases)

    # Remove matched phrases from text to avoid double-extraction
    for phrase in kept_phrases:
        text = text.replace(phrase, " ", 1)

    # 3. Extract ALL Chinese bigrams from remaining text
    #    This provides broad coverage for partial matches
    chinese_runs = re.findall(r'[一-鿿㐀-䶿]{2,}', text)
    for run in chinese_runs:
        for i in range(len(run) - 1):
            bigram = run[i:i+2]
            if bigram[0] not in _STOP_CHARS and bigram[1] not in _STOP_CHARS:
                keywords.append(bigram)

    # 4. Deduplicate, keep >= 2 chars
    seen: set[str] = set()
    result: list[str] = []
    for k in keywords:
        if k not in seen and len(k) >= 2:
            seen.add(k)
            result.append(k)

    return result[:max_terms]
