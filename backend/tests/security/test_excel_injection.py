"""安全测试 — Excel Formula Injection 防护 (CWE-1236)

覆盖：
- _stringify 对以 =, +, -, @ 开头的字符串加单引号前缀
- 安全值（无公式触发字符）不被修改
- None / datetime 正确处理
"""

import pytest

from app.services.excel_exporter import _stringify


class TestStringifyFormulaInjection:
    """_stringify 必须防御 Excel Formula Injection (CWE-1236)"""

    def test_equals_prefix_escaped(self):
        """以 = 开头的字符串应被转义"""
        result = _stringify("=SUM(A1:A10)")
        assert isinstance(result, str)
        assert result == "'=SUM(A1:A10)"

    def test_plus_prefix_escaped(self):
        """以 + 开头的字符串应被转义"""
        result = _stringify("+SUM(A1:A10)")
        assert isinstance(result, str)
        assert result == "'+SUM(A1:A10)"

    def test_minus_prefix_escaped(self):
        """以 - 开头的字符串应被转义"""
        result = _stringify("-SUM(A1:A10)")
        assert isinstance(result, str)
        assert result == "'-SUM(A1:A10)"

    def test_at_prefix_escaped(self):
        """以 @ 开头的字符串应被转义"""
        result = _stringify("@SUM(A1:A10)")
        assert isinstance(result, str)
        assert result == "'@SUM(A1:A10)"

    def test_normal_text_not_escaped(self):
        """普通文本不应被修改"""
        assert _stringify("招标公告") == "招标公告"
        assert _stringify("本项目采用公开招标方式") == "本项目采用公开招标方式"
        assert _stringify("hello world") == "hello world"

    def test_text_containing_formula_chars_mid_not_escaped(self):
        """公式触发字符在字符串中间出现时不应被转义"""
        assert _stringify("招标文件=公开招标") == "招标文件=公开招标"
        assert _stringify("价格-成本") == "价格-成本"
        assert _stringify("user@example.com") == "user@example.com"

    def test_none_returns_empty(self):
        assert _stringify(None) == ""

    def test_empty_string_not_escaped(self):
        assert _stringify("") == ""

    def test_positive_numbers_not_affected(self):
        """正整数和浮点数不触发转义"""
        assert _stringify(42) == "42"
        assert _stringify(3.14) == "3.14"

    def test_negative_number_escaped(self):
        """安全行为：负数的 str 以 '-' 开头，在 Excel 中也会被当作公式，应被转义。
        证据文本/法规引用都是字符串，负数不应出现在报表中；
        若出现，安全转义将其标记为 '-100 防止公式注入。
        """
        assert _stringify(-100) == "'-100"
        assert _stringify(-1) == "'-1"

    def test_boolean_values_not_affected(self):
        assert _stringify(True) == "True"
        assert _stringify(False) == "False"
