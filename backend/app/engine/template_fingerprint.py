"""STDT 标准模板指纹库

从 STDT/ 目录下的 34 份标准招标文件模板中提取固定内容指纹，
用于后续的「定变分离」预处理——区分模板固定文字（定量）和
代理机构填写内容（变量）。

核心概念：
- FIXED:  所有同类型模板共有的句子/段落 → 标准模板框架文字
- VARIABLE: 占位符标记处 + 模板间不同的句子 → 代理机构填写区域

数据结构：
- 存储归一化文本的 SHA256 哈希 → O(1) 精确查询
- 同时保留原始文本，用于降级模糊匹配
- 按 行业/采购方式/项目类型 三级维度组织
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── STDT 模板目录 ────────────────────────────────────────────
_STDT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "STDT"

# ── 占位符标记正则 ───────────────────────────────────────────
# 招标文件标准模板中常见的占位符模式
VARIABLE_MARKER_PATTERNS = [
    re.compile(r"[（(][^）)]*?(?:项目名称|采购人|招标人|供应商|投标人|金额|日期|时间|地点|地址|名称|编号|数量|规格|参数|要求|内容|说明|填写|自定|根据|视情|协商|约定)[^）)]*?[）)]"),
    re.compile(r"[（(][^）)]{0,30}[）)]"),              # 通用括号占位符
    re.compile(r"【[^】]{0,50}】"),                    # 方头括号占位符
    re.compile(r"[Xx_＿]{2,}"),                       # 下划线/X占位符
    re.compile(r"(?:根据项目|根据实际|视项目|按项目|协商|约定|自定|参照).{0,20}(?:确定|执行|处理|填写)"),
    re.compile(r"（.*?）"),                            # 中文括号内容
    re.compile(r"此处.*?(?:填写|填入|插入|自定|自定义)"),
    re.compile(r"详见.{0,20}(?:附件|附表|下文|下表|要求)"),
]

# ── 固定内容识别关键词（低置信度辅助标记） ──────────────────
# 当句子包含这些关键词组合时，更可能是模板固定文字
FIXED_CONTENT_KEYWORDS = [
    "招标投标法", "政府采购法", "实施条例", "财政部",
    "公共资源交易", "电子招标投标", "招标文件",
    "投标人须知", "投标须知", "前附表",
    "投标文件", "投标保证金", "履约保证金",
    "招标公告", "资格要求", "评审办法", "评标办法",
    "开标", "评标", "定标", "中标",
    "质疑", "投诉", "答复",
    "签字", "盖章", "密封", "装订",
    "格式", "要求", "说明", "注：", "注:",
    "不得", "必须", "应当", "严禁",
    "第一条", "第二条", "第三条", "第四条", "第五条",
]

# ── 句子分割正则 ────────────────────────────────────────────
_SENTENCE_SPLIT_RE = re.compile(
    r'(?<=[。！？；\n])\s*'
)

# ── 文本归一化函数 ───────────────────────────────────────────
def normalize_text(text: str) -> str:
    """归一化文本用于指纹匹配：去空白、统一标点"""
    text = re.sub(r'\s+', '', text)                    # 去除所有空白
    text = text.replace('（', '(').replace('）', ')')   # 统一括号
    text = text.replace('【', '[').replace('】', ']')
    text = text.replace('：', ':').replace('，', ',')
    text = text.replace('。', '.').replace('；', ';')
    text = text.replace('！', '!').replace('？', '?')
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace(''', "'").replace(''', "'")
    text = text.replace('—', '-').replace('–', '-')
    return text


def text_hash(text: str) -> str:
    """计算文本的 SHA256 指纹"""
    return hashlib.sha256(normalize_text(text).encode('utf-8')).hexdigest()[:16]


def text_ngram_set(text: str, n: int = 3) -> set[str]:
    """计算字符级 n-gram 集合，用于模糊匹配"""
    clean = normalize_text(text)
    return {clean[i:i+n] for i in range(len(clean) - n + 1)}


def ngram_overlap(a: str, b: str, n: int = 3) -> float:
    """计算两个文本的 n-gram 重叠率"""
    set_a = text_ngram_set(a, n)
    set_b = text_ngram_set(b, n)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / min(len(set_a), len(set_b))


# ── 数据结构 ────────────────────────────────────────────────

@dataclass
class TemplateFingerprint:
    """单条模板指纹"""
    text: str                           # 原始文本
    normalized: str                     # 归一化文本
    hash_id: str                        # SHA256 前16位
    sector: str                         # 行业
    procurement_method: str             # 采购方式
    project_type: str                   # 项目类型
    section_type: str = ""              # 所属章节类型
    is_section_header: bool = False     # 是否为章节标题
    is_variable_marker: bool = False    # 是否为占位符标记
    frequency: int = 1                  # 在同类模板中出现的次数
    length: int = 0                     # 字符数


@dataclass
class SectorFingerprints:
    """一个行业+采购方式+项目类型组合的指纹集合"""
    sector: str
    procurement_method: str
    project_type: str
    fingerprints: dict[str, TemplateFingerprint] = field(default_factory=dict)
    variable_markers: list[str] = field(default_factory=list)
    section_headers: set[str] = field(default_factory=set)
    total_sentences: int = 0


class TemplateFingerprintDB:
    """模板指纹数据库

    加载 STDT 目录下所有模板，提取固定内容指纹，
    支持 SHA256 精确匹配和 n-gram 模糊匹配。
    """

    def __init__(self, stdt_dir: str | Path | None = None):
        self._stdt_dir = Path(stdt_dir) if stdt_dir else _STDT_DIR
        # 三级索引: sector → procurement_method → project_type → fingerprints
        self._index: dict[str, dict[str, dict[str, SectorFingerprints]]] = {}
        # 全局哈希索引: hash_id → TemplateFingerprint（跨行业去重查询）
        self._hash_index: dict[str, TemplateFingerprint] = {}
        # 全局文本索引: 用于没有行业信息时的通用匹配
        self._global_hashes: set[str] = set()
        self._loaded = False

    # ── 构建指纹库 ──────────────────────────────────────────

    def build(self, force: bool = False) -> int:
        """扫描 STDT 目录，提取所有模板指纹。

        Returns:
            提取的指纹总数
        """
        if self._loaded and not force:
            return len(self._hash_index)

        if not self._stdt_dir.is_dir():
            logger.warning("STDT 模板目录不存在: %s", self._stdt_dir)
            return 0

        # 收集所有模板文件并按 (sector, method, type) 分组
        from app.services.parser import DocumentParser
        parser = DocumentParser()

        groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)

        for pdf_path in sorted(self._stdt_dir.rglob("*.pdf")):
            rel_path = pdf_path.relative_to(self._stdt_dir)
            parts = rel_path.parts

            sector = self._map_sector(parts[0]) if len(parts) >= 1 else "unknown"
            filename = pdf_path.stem

            method, proj_type = self._parse_filename(filename)

            logger.info("处理模板: %s | sector=%s method=%s type=%s",
                       rel_path, sector, method, proj_type)

            try:
                doc = parser.parse_pdf(str(pdf_path))
                sentences = self._extract_sentences(doc.full_text)

                # 提取章节标题
                headers = set()
                for heading in doc.headings:
                    headers.add(heading.strip())

                groups[(sector, method, proj_type)].append({
                    "path": str(rel_path),
                    "sentences": sentences,
                    "headers": headers,
                    "full_text": doc.full_text,
                })
                logger.info("  → 提取 %d 句，%d 标题", len(sentences), len(headers))
            except Exception as e:
                logger.error("解析模板失败 %s: %s", rel_path, e)

        # 对每组取交集提取固定指纹
        total_count = 0
        for (sector, method, proj_type), docs in groups.items():
            sf = self._extract_group_fingerprints(
                sector, method, proj_type, docs
            )
            self._index.setdefault(sector, {}).setdefault(method, {})[proj_type] = sf

            for fp in sf.fingerprints.values():
                self._hash_index[fp.hash_id] = fp
                self._global_hashes.add(fp.hash_id)

            total_count += len(sf.fingerprints)
            logger.info(
                "指纹组 [%s/%s/%s]: %d 固定句, %d 占位符标记, %d 章节标题 (来自 %d 份模板)",
                sector, method, proj_type,
                len(sf.fingerprints), len(sf.variable_markers),
                len(sf.section_headers), len(docs),
            )

        self._loaded = True
        logger.info("指纹库构建完成: %d 条指纹 (索引 %d 组)", total_count, len(groups))
        return total_count

    # ── 查询接口 ────────────────────────────────────────────

    def lookup_exact(self, text: str) -> Optional[TemplateFingerprint]:
        """精确匹配：SHA256 哈希查询"""
        h = text_hash(text)
        return self._hash_index.get(h)

    def lookup_fuzzy(self, text: str, threshold: float = 0.85) -> Optional[TemplateFingerprint]:
        """模糊匹配：n-gram 重叠率 ≥ threshold

        在全局指纹库中查找最相似的指纹。
        注意：这是 O(n) 操作，仅在精确匹配失败时使用。
        """
        best_score = 0.0
        best_fp: Optional[TemplateFingerprint] = None

        # 先尝试精确匹配
        exact = self.lookup_exact(text)
        if exact:
            return exact

        # 模糊匹配——仅对长度相近的指纹比较（性能优化）
        text_len = len(normalize_text(text))
        for fp in self._hash_index.values():
            # 长度差超过 30% 直接跳过
            if abs(fp.length - text_len) > max(text_len * 0.3, 10):
                continue
            score = ngram_overlap(text, fp.text)
            if score > best_score:
                best_score = score
                best_fp = fp

        if best_score >= threshold:
            return best_fp
        return None

    def is_known_fixed(self, text: str, fuzzy: bool = True,
                       threshold: float = 0.85) -> tuple[bool, float, Optional[str]]:
        """综合判断文本是否为已知模板固定内容

        Returns:
            (is_fixed, confidence, fingerprint_id)
        """
        # 精确匹配
        exact = self.lookup_exact(text)
        if exact:
            return True, 0.95, exact.hash_id

        # 模糊匹配
        if fuzzy:
            fuzzy_match = self.lookup_fuzzy(text, threshold)
            if fuzzy_match:
                return True, 0.80, fuzzy_match.hash_id

        return False, 0.0, None

    def is_variable_marker(self, text: str) -> bool:
        """判断文本是否匹配占位符标记模式"""
        for pat in VARIABLE_MARKER_PATTERNS:
            if pat.search(text):
                return True
        return False

    def get_section_headers(self, sector: str = "", method: str = "",
                           proj_type: str = "") -> set[str]:
        """获取已知的章节标题集合"""
        if sector and method and proj_type:
            sf = self._get_sector_fingerprints(sector, method, proj_type)
            if sf:
                return sf.section_headers

        # 合并所有章节标题
        all_headers: set[str] = set()
        for sec_idx in self._index.values():
            for meth_idx in sec_idx.values():
                for sf in meth_idx.values():
                    all_headers.update(sf.section_headers)
        return all_headers

    # ── 内部方法 ────────────────────────────────────────────

    def _get_sector_fingerprints(self, sector: str, method: str,
                                 proj_type: str) -> Optional[SectorFingerprints]:
        return self._index.get(sector, {}).get(method, {}).get(proj_type)

    @staticmethod
    def _map_sector(dir_name: str) -> str:
        """目录名 → 标准化行业名"""
        mapping = {
            "政府采购": "政府采购",
            "公路工程": "公路工程",
            "水利工程": "水利工程",
            "铁路工程项目": "铁路工程",
        }
        return mapping.get(dir_name, dir_name)

    @staticmethod
    def _parse_filename(filename: str) -> tuple[str, str]:
        """从文件名解析采购方式和项目类型。

        Examples:
            "公开招标--货物类" → ("公开招标", "货物类")
            "后审公开施工" → ("公开招标", "工程类")
            "磋商--服务类" → ("竞争性磋商", "服务类")
            "预审施工" → ("资格预审", "工程类")
            "总承包" → ("公开招标", "工程类")
        """
        # 政府采购格式: "采购方式--项目类型"
        if "--" in filename:
            parts = filename.split("--")
            method_raw = parts[0].strip()
            type_raw = parts[1].strip() if len(parts) > 1 else "工程类"
            return TemplateFingerprintDB._normalize_method(method_raw), type_raw

        # 工程类格式: "审查方式+采购方式+项目类型"
        method_raw = filename
        type_raw = "工程类"

        if "监理" in filename:
            type_raw = "服务类"  # 监理归类为服务
        elif "勘察设计" in filename or "设计" in filename:
            type_raw = "服务类"
        elif "货物" in filename:
            type_raw = "货物类"
        elif "服务" in filename:
            type_raw = "服务类"
        elif "材料" in filename:
            type_raw = "货物类"
        elif "总承包" in filename:
            type_raw = "工程类"

        if "预审" in filename:
            method_raw = "资格预审"
        elif "后审" in filename:
            # 后审公开施工 → 公开招标
            if "邀请" in filename:
                method_raw = "邀请招标"
            else:
                method_raw = "公开招标"

        return TemplateFingerprintDB._normalize_method(method_raw), type_raw

    @staticmethod
    def _normalize_method(raw: str) -> str:
        """标准化采购方式名称"""
        mapping = {
            "公开招标": "公开招标",
            "邀请招标": "邀请招标",
            "竞争性谈判": "竞争性谈判",
            "谈判": "竞争性谈判",
            "竞争性磋商": "竞争性磋商",
            "磋商": "竞争性磋商",
            "询价": "询价",
            "单一来源": "单一来源",
            "资格预审": "资格预审",
        }
        for key, val in mapping.items():
            if key in raw:
                return val
        return raw

    @staticmethod
    def _extract_sentences(text: str) -> list[str]:
        """将文本分割为句子列表（过滤空句和纯空白）"""
        raw = _SENTENCE_SPLIT_RE.split(text)
        result = []
        for s in raw:
            s = s.strip()
            if not s:
                continue
            # 过滤纯数字/标点行
            if re.match(r'^[\d\s\.\,\;\:\!\?\-_\/\\|\(\)\[\]\{\}]+$', s):
                continue
            # 过滤过短的碎片（< 3 个汉字）
            if len(re.findall(r'[一-鿿]', s)) < 3:
                continue
            result.append(s)
        return result

    def _extract_group_fingerprints(
        self,
        sector: str,
        method: str,
        proj_type: str,
        docs: list[dict],
    ) -> SectorFingerprints:
        """从同组的多份模板中提取固定内容指纹。

        策略：
        1. 章节标题：取所有模板标题的并集
        2. 固定句子：取所有模板句子的交集（多份模板共有的句子）
        3. 占位符标记：扫描每份模板中的占位符模式
        4. 如果只有 1 份模板：用启发式规则判断（含法规引用、标准用语等）
        """
        sf = SectorFingerprints(
            sector=sector,
            procurement_method=method,
            project_type=proj_type,
        )

        if not docs:
            return sf

        # ── 章节标题：并集 ──────────────────────────────────
        all_headers: set[str] = set()
        for doc in docs:
            all_headers.update(doc["headers"])
        sf.section_headers = all_headers

        # ── 提取所有模板的句子集合 ──────────────────────────
        sentence_sets: list[set[str]] = []
        for doc in docs:
            sent_set = set()
            for s in doc["sentences"]:
                sent_set.add(normalize_text(s))
            sentence_sets.append(sent_set)

        # ── 固定句子：交集 ──────────────────────────────────
        if len(sentence_sets) >= 2:
            # 多份模板：交集 = 所有模板都有的句子
            common_normalized = sentence_sets[0].intersection(*sentence_sets[1:])
        else:
            # 仅一份模板：启发式判断固定内容
            common_normalized = self._heuristic_fixed_filter(
                docs[0]["sentences"], docs[0]["full_text"]
            )

        # ── 构建指纹对象 ────────────────────────────────────
        # 从原始文本中找到归一化匹配的句子
        for doc in docs:
            for s in doc["sentences"]:
                norm = normalize_text(s)
                if norm in common_normalized:
                    h = text_hash(s)
                    if h not in sf.fingerprints:
                        sf.fingerprints[h] = TemplateFingerprint(
                            text=s,
                            normalized=norm,
                            hash_id=h,
                            sector=sector,
                            procurement_method=method,
                            project_type=proj_type,
                            is_section_header=s.strip() in all_headers,
                            length=len(norm),
                        )
                    else:
                        sf.fingerprints[h].frequency += 1

        # ── 占位符标记扫描 ──────────────────────────────────
        for doc in docs:
            for s in doc["sentences"]:
                if self.is_variable_marker(s):
                    sf.variable_markers.append(s)

        sf.total_sentences = sum(len(doc["sentences"]) for doc in docs)
        return sf

    def _heuristic_fixed_filter(self, sentences: list[str], full_text: str) -> set[str]:
        """启发式固定内容过滤（用于单份模板场景）。

        判断依据：
        1. 包含法规名称引用（招标投标法、政府采购法等）
        2. 包含标准程序描述关键词
        3. 句子长度 ≥ 40 字（短句通常是填写的变量内容）
        4. 匹配已知的固定内容关键词组合
        """
        result: set[str] = set()
        for s in sentences:
            norm = normalize_text(s)
            score = 0

            # 法规引用 +3
            if re.search(r'(?:招标投标法|政府采购法|实施条例|财政部|87号令|94号令|38号文)', s):
                score += 3

            # 标准用语 +2
            fixed_count = sum(1 for kw in FIXED_CONTENT_KEYWORDS if kw in s)
            score += min(fixed_count, 5) * 2

            # 长句（≥40字）= 模板结构文本 +2
            if len(s) >= 40:
                score += 2

            # 包含章节编号模式 +2
            if re.search(r'(?:第[一二三四五六七八九十\d]+[章节条]|^\d+[\.\、])', s):
                score += 2

            # 包含"注：" "说明：" 等提示语 +1
            if re.search(r'(?:注[：:]|说明[：:]|注意[：:]|提示[：:])', s):
                score += 1

            # 得分 ≥ 5 → 判定为固定内容
            if score >= 5:
                result.add(norm)

        return result

    # ── 序列化 / 持久化 ─────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化为可 JSON 化的 dict"""
        result = {
            "version": "1.0.0",
            "source": str(self._stdt_dir),
            "total_fingerprints": len(self._hash_index),
            "sectors": {},
        }
        for sector, methods in self._index.items():
            sec_data = {}
            for method, types in methods.items():
                meth_data = {}
                for proj_type, sf in types.items():
                    meth_data[proj_type] = {
                        "fingerprint_count": len(sf.fingerprints),
                        "fingerprints": [
                            {
                                "hash_id": fp.hash_id,
                                "text": fp.text,
                                "is_section_header": fp.is_section_header,
                            }
                            for fp in sf.fingerprints.values()
                        ],
                        "variable_markers": sf.variable_markers[:50],
                        "section_headers": sorted(sf.section_headers),
                    }
                sec_data[method] = meth_data
            result["sectors"][sector] = sec_data
        return result

    def save(self, path: str | Path) -> None:
        """保存指纹库到 JSON 文件"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("指纹库已保存: %s (%d 条指纹)", path, len(self._hash_index))

    @classmethod
    def load(cls, path: str | Path, stdt_dir: str | Path | None = None) -> "TemplateFingerprintDB":
        """从 JSON 文件加载指纹库"""
        path = Path(path)
        if not path.exists():
            logger.warning("指纹库文件不存在: %s，将重新构建", path)
            db = cls(stdt_dir)
            db.build()
            db.save(path)
            return db

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        db = cls(stdt_dir)

        for sector, methods in data.get("sectors", {}).items():
            for method, types in methods.items():
                for proj_type, sf_data in types.items():
                    sf = SectorFingerprints(
                        sector=sector,
                        procurement_method=method,
                        project_type=proj_type,
                        section_headers=set(sf_data.get("section_headers", [])),
                        variable_markers=sf_data.get("variable_markers", []),
                    )
                    for fp_data in sf_data.get("fingerprints", []):
                        fp = TemplateFingerprint(
                            text=fp_data["text"],
                            normalized=normalize_text(fp_data["text"]),
                            hash_id=fp_data["hash_id"],
                            sector=sector,
                            procurement_method=method,
                            project_type=proj_type,
                            is_section_header=fp_data.get("is_section_header", False),
                            length=len(normalize_text(fp_data["text"])),
                        )
                        sf.fingerprints[fp.hash_id] = fp
                        db._hash_index[fp.hash_id] = fp
                        db._global_hashes.add(fp.hash_id)

                    db._index.setdefault(sector, {}).setdefault(method, {})[proj_type] = sf

        db._loaded = True
        logger.info("指纹库已加载: %s (%d 条指纹)", path, len(db._hash_index))
        return db

    def __len__(self) -> int:
        return len(self._hash_index)

    def __repr__(self) -> str:
        return f"<TemplateFingerprintDB fingerprints={len(self._hash_index)} loaded={self._loaded}>"


# ── 模块级单例 ──────────────────────────────────────────────

_fingerprint_cache_path = Path(__file__).resolve().parent.parent.parent.parent / "rules" / "template_fingerprints.json"

# 懒加载单例
_fingerprint_db: Optional[TemplateFingerprintDB] = None


def get_fingerprint_db(stdt_dir: str | Path | None = None,
                       force_rebuild: bool = False) -> TemplateFingerprintDB:
    """获取指纹库单例（懒加载 + 缓存）

    Args:
        stdt_dir: STDT 模板目录路径（默认自动检测）
        force_rebuild: 是否强制重新构建
    """
    global _fingerprint_db
    if _fingerprint_db is not None and not force_rebuild:
        return _fingerprint_db

    if _fingerprint_cache_path.exists() and not force_rebuild:
        _fingerprint_db = TemplateFingerprintDB.load(_fingerprint_cache_path, stdt_dir)
    else:
        _fingerprint_db = TemplateFingerprintDB(stdt_dir)
        _fingerprint_db.build()
        _fingerprint_db.save(_fingerprint_cache_path)

    return _fingerprint_db
