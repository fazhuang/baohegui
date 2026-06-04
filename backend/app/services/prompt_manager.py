"""LLM Prompt 模板管理器

功能:
  1. 从 rules/prompts/ 加载 .txt Prompt 模板
  2. 支持版本管理（文件名含 _vN 后缀）
  3. 支持多变量动态替换
  4. 支持多 Prompt 策略（不同维度使用不同模板）

文件命名约定::
    compliance_check.txt        # 综合审查（默认）
    compliance_check_v2.txt     # 综合审查 v2
    exclusivity.txt             # 排他性专项
    bias.txt                    # 倾向性专项
    hidden_barrier.txt          # 隐性壁垒专项
    high_risk.txt               # 质疑风险专项
    ambiguity.txt               # 条款含糊性专项

使用示例::
    manager = PromptManager()
    tmpl = manager.get_prompt("compliance_check")
    rendered = manager.render("compliance_check", text="招标文件内容...")
    versions = manager.list_versions("compliance_check")
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

class PromptTemplate(BaseModel):
    """一个 Prompt 模板的元数据与内容"""

    name: str                         # 模板名，如 "compliance_check"
    version: int = 1                  # 版本号，从文件名 _vN 提取
    content: str                      # 原始模板文本
    path: Optional[str] = None        # 磁盘路径
    variables: list[str] = Field(default_factory=list)  # 从内容中提取的变量名列表
    description: str = ""             # 用途描述（从文件首行注释提取）

    def render(self, **kwargs: str) -> str:
        """
        替换模板中的 {variable} 占位符。

        使用安全的字符串替换而非 str.format()，
        避免模板中 JSON 格式的 { 被错误解析。

        Args:
            **kwargs: 变量名 → 值

        Returns:
            替换后的文本
        """
        result = self.content
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", value)
        return result

    def has_variable(self, name: str) -> bool:
        return f"{{{name}}}" in self.content


# ═══════════════════════════════════════════════════════════════
# 文件命名解析
# ═══════════════════════════════════════════════════════════════

_NAME_AND_VERSION = re.compile(
    r"^(?P<name>[a-z0-9_]+?)(?:_v(?P<version>\d+))?$",
)

_VARIABLE_PATTERN = re.compile(r"\{(\w+)\}")


def _parse_filename(stem: str) -> tuple[str, int]:
    """
    从文件名中解析模板名和版本号。

    Examples::
        "compliance_check"    → ("compliance_check", 1)
        "compliance_check_v2" → ("compliance_check", 2)
        "exclusivity"         → ("exclusivity", 1)
    """
    m = _NAME_AND_VERSION.match(stem)
    if not m:
        raise ValueError(f"文件名不符合命名约定: {stem}.txt")
    name = m.group("name")
    version = int(m.group("version")) if m.group("version") else 1
    return name, version


def _extract_variables(text: str) -> list[str]:
    """从模板文本中提取所有 {variable} 占位符。"""
    return sorted(set(_VARIABLE_PATTERN.findall(text)))


def _extract_description(text: str) -> str:
    """从模板首行或前几行提取描述（跳过空行和 Markdown 注释行）。"""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 取第一句有意义的文本
        if len(line) > 10:
            return line[:80] + ("…" if len(line) > 80 else "")
    return ""


# ═══════════════════════════════════════════════════════════════
# 默认搜索路径
# ═══════════════════════════════════════════════════════════════

_PROMPTS_DIR_CANDIDATES = [
    # 优先：从当前模块文件向上导航到项目根 → rules/prompts
    lambda: Path(__file__).resolve().parent.parent.parent.parent
    / "rules" / "prompts",
    # Docker 容器内
    lambda: Path("/app") / "rules" / "prompts",
    # 从 settings.rules_dir 推导（通常在项目根）
    lambda: Path("rules") / "prompts",
    # 兼容 backend/ 下执行
    lambda: Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "rules" / "prompts",
]


def _find_prompts_dir() -> Path:
    """查找 prompts 目录的实际路径。"""
    for factory in _PROMPTS_DIR_CANDIDATES:
        try:
            path = factory()
            if path.is_dir():
                return path
        except Exception:
            continue
    raise FileNotFoundError(
        "Prompts 目录未找到。请确保 rules/prompts/ 存在，"
        "或通过 PromptManager(prompts_dir=...) 指定。"
    )


class PromptNotFoundError(FileNotFoundError):
    """指定的 Prompt 模板不存在"""

    def __init__(self, name: str, version: Optional[int] = None):
        msg = f"Prompt 模板 '{name}'"
        if version:
            msg += f" v{version}"
        msg += " 未找到"
        super().__init__(msg)


# ═══════════════════════════════════════════════════════════════
# PromptManager
# ═══════════════════════════════════════════════════════════════

class PromptManager:
    """
    LLM Prompt 模板管理器。

    扫描目录下的所有 .txt 文件，按名称和版本号索引，
    支持获取最新版、指定版本、渲染、多维策略切换。
    """

    def __init__(self, prompts_dir: str | Path | None = None):
        self._base_dir = (
            Path(prompts_dir) if prompts_dir
            else _find_prompts_dir()
        )
        self._index: dict[str, dict[int, PromptTemplate]] = {}
        self._rebuild_index()

    # ── 索引构建 ────────────────────────────────────────────

    def _rebuild_index(self) -> None:
        """扫描目录并重建索引。"""
        self._index.clear()

        if not self._base_dir.is_dir():
            logger.warning("Prompts 目录不存在: %s", self._base_dir)
            return

        for path in sorted(self._base_dir.iterdir()):
            if not path.is_file() or path.suffix != ".txt":
                continue

            try:
                name, version = _parse_filename(path.stem)
            except ValueError:
                logger.debug("跳过非标准文件名: %s", path.name)
                continue

            content = path.read_text(encoding="utf-8")
            tmpl = PromptTemplate(
                name=name,
                version=version,
                content=content,
                path=str(path.resolve()),
                variables=_extract_variables(content),
                description=_extract_description(content),
            )

            self._index.setdefault(name, {})[version] = tmpl

        if not self._index:
            logger.warning("Prompts 目录 '%s' 下没有符合命名约定的 .txt 文件", self._base_dir)
            return

        # 汇总日志
        summaries = [
            f"  {name}: {max(vers)} 个版本 (v{min(vers)}~v{max(vers)})"
            for name, vers in sorted(self._index.items())
        ]
        logger.info("PromptManager 索引就绪 (%s)", "; ".join(summaries))

    # ── 查询 ────────────────────────────────────────────────

    def get_prompt(
        self,
        name: str,
        version: Optional[int] = None,
    ) -> PromptTemplate:
        """
        获取指定名称和版本的 Prompt 模板。

        Args:
            name:    模板名（不含 _vN 和 .txt）
            version: 版本号；None 表示最新版本

        Returns:
            PromptTemplate

        Raises:
            PromptNotFoundError: 指定的模板不存在
        """
        versions = self._index.get(name)
        if not versions:
            raise PromptNotFoundError(name)

        if version is None:
            # 取最新版本
            version = max(versions.keys())

        tmpl = versions.get(version)
        if not tmpl:
            raise PromptNotFoundError(name, version)

        return tmpl

    def render(
        self,
        name: str,
        version: Optional[int] = None,
        **kwargs: str,
    ) -> str:
        """
        获取模板并替换变量，一步到位。

        Args:
            name:    模板名
            version: 版本号（None=最新）
            **kwargs: 变量键值对

        Returns:
            渲染后的文本
        """
        tmpl = self.get_prompt(name, version)
        return tmpl.render(**kwargs)

    # ── 列举 ────────────────────────────────────────────────

    def list_prompts(self) -> list[str]:
        """返回所有可用的模板名（去重）。"""
        return sorted(self._index.keys())

    def list_versions(self, name: str) -> list[int]:
        """返回指定模板的所有版本号列表（升序）。"""
        versions = self._index.get(name, {})
        return sorted(versions.keys())

    def get_dimension_prompts(
        self,
    ) -> dict[str, PromptTemplate]:
        """
        获取所有维度专项 Prompt，返回 {维度名 → PromptTemplate}。

        维度名取自文件名（exclusivity / bias / hidden_barrier 等）。
        综合审查模板 (compliance_check) 默认包含在内。
        """
        result: dict[str, PromptTemplate] = {}
        for name in self.list_prompts():
            try:
                result[name] = self.get_prompt(name)
            except PromptNotFoundError:
                continue
        return result

    # ── 刷新 ────────────────────────────────────────────────

    def reload(self) -> None:
        """重新扫描目录（热加载）。"""
        logger.info("PromptManager 热加载: %s", self._base_dir)
        self._rebuild_index()

    def get_path(self) -> str:
        """返回当前 Prompts 目录路径。"""
        return str(self._base_dir.resolve())

    def __repr__(self) -> str:
        prompts = self.list_prompts()
        return (
            f"<PromptManager path={self._base_dir} "
            f"prompts={len(prompts)}>"
        )


# 模块级单例
prompt_manager = PromptManager()
