"""sanitize_filename() 纯函数单元测试。

覆盖范围：
  - 正常文件名（有/无 .md 后缀，大小写不敏感判断）
  - 多行输入（只取第一行；strip() 先于 splitlines()）
  - 路径前缀（通过 Path().name 只取 basename）
  - 空字符串 / 纯空白 / 纯换行 → 回退 default
  - 自定义 default 参数
  - Windows 非法字符（< > : " / | ? * 及控制字符 \x00-\x1f）
  - Windows 保留名（CON PRN AUX NUL COM1-9 LPT1-9，大小写不敏感）
  - 首尾点/空格被 strip(". ") 清理
  - 中文文件名
"""

from __future__ import annotations

import pytest

from main import sanitize_filename


# ---------------------------------------------------------------------------
# 正常文件名
# ---------------------------------------------------------------------------

class TestNormalFilenames:
    def test_valid_md_filename_unchanged(self):
        assert sanitize_filename("report.md") == "report.md"

    def test_adds_md_extension_when_missing(self):
        assert sanitize_filename("report") == "report.md"

    def test_uppercase_MD_extension_not_doubled(self):
        # 大小写不敏感：.MD 已是 .md，不应再追加
        assert sanitize_filename("Report.MD") == "Report.MD"

    def test_mixed_case_Md_extension_not_doubled(self):
        assert sanitize_filename("Report.Md") == "Report.Md"

    def test_chinese_filename_with_md(self):
        assert sanitize_filename("SAS数据血缘分析设计.md") == "SAS数据血缘分析设计.md"

    def test_chinese_filename_without_md(self):
        assert sanitize_filename("SAS数据血缘分析设计") == "SAS数据血缘分析设计.md"

    def test_filename_with_internal_spaces(self):
        # 内部空格合法，首尾由 strip() 已处理
        assert sanitize_filename("  my file.md  ") == "my file.md"


# ---------------------------------------------------------------------------
# 多行输入：strip() 先于 splitlines()
# ---------------------------------------------------------------------------

class TestMultilineInput:
    def test_only_first_line_used(self):
        # 典型场景：LLM 在文件名后附加了解释文字
        assert sanitize_filename("foo.md\n这是模型的解释文字") == "foo.md"

    def test_only_first_line_used_crlf(self):
        assert sanitize_filename("foo.md\r\n这是解释") == "foo.md"

    def test_multiline_warning_scenario(self):
        # 验证：多行内容经清洗后 != raw.strip()，从而触发 warning 判断
        raw = "foo.md\n解释文字"
        result = sanitize_filename(raw)
        assert result == "foo.md"
        assert result != raw.strip()          # 触发 warning 的比较条件成立

    def test_trailing_newline_silent_fix(self):
        # 仅有尾部换行时，strip() 处理后与结果一致，不应触发 warning
        raw = "foo.md\n"
        result = sanitize_filename(raw)
        assert result == "foo.md"
        assert result == raw.strip()          # 触发 warning 的比较条件不成立

    def test_leading_whitespace_and_newline_stripped(self):
        # strip() 先行：前导空格+换行被去掉，后续内容正常解析
        assert sanitize_filename("  \nfoo.md") == "foo.md"

    def test_content_after_leading_newline_used(self):
        # "\n第二行.md" → strip() → "第二行.md"（不是空，第二行内容被用）
        assert sanitize_filename("\n第二行.md") == "第二行.md"


# ---------------------------------------------------------------------------
# 路径前缀
# ---------------------------------------------------------------------------

class TestPathPrefix:
    def test_strips_unix_directory(self):
        assert sanitize_filename("dir/foo.md") == "foo.md"

    def test_strips_deep_unix_path(self):
        assert sanitize_filename("/a/b/c/foo.md") == "foo.md"


# ---------------------------------------------------------------------------
# 空字符串 / 纯空白 / 纯换行
# ---------------------------------------------------------------------------

class TestEmptyAndWhitespace:
    def test_empty_string_returns_default(self):
        assert sanitize_filename("") == "design.md"

    def test_spaces_only_returns_default(self):
        assert sanitize_filename("   ") == "design.md"

    def test_newlines_only_returns_default(self):
        assert sanitize_filename("\n\n") == "design.md"

    def test_custom_default_returned_on_empty(self):
        assert sanitize_filename("", default="fallback.md") == "fallback.md"

    def test_custom_default_used_for_reserved_name(self):
        assert sanitize_filename("CON.md", default="safe.md") == "safe.md"


# ---------------------------------------------------------------------------
# Windows 非法字符
# ---------------------------------------------------------------------------

class TestIllegalCharacters:
    def test_less_than_replaced(self):
        assert sanitize_filename("foo<bar>.md") == "foo_bar_.md"

    def test_question_mark_replaced(self):
        assert sanitize_filename("foo?.md") == "foo_.md"

    def test_asterisk_replaced(self):
        assert sanitize_filename("foo*.md") == "foo_.md"

    def test_double_quote_replaced(self):
        assert sanitize_filename('foo"bar.md') == "foo_bar.md"

    def test_pipe_replaced(self):
        assert sanitize_filename("foo|bar.md") == "foo_bar.md"

    def test_null_control_char_replaced(self):
        assert sanitize_filename("foo\x00bar.md") == "foo_bar.md"

    def test_unit_separator_control_char_replaced(self):
        assert sanitize_filename("foo\x1fbar.md") == "foo_bar.md"

    def test_multiple_illegal_chars_all_replaced(self):
        assert sanitize_filename("foo<>*.md") == "foo___.md"


# ---------------------------------------------------------------------------
# Windows 保留名
# ---------------------------------------------------------------------------

class TestWindowsReservedNames:
    @pytest.mark.parametrize("reserved", [
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM5", "COM9",
        "LPT1", "LPT5", "LPT9",
    ])
    def test_reserved_name_uppercase_returns_default(self, reserved):
        assert sanitize_filename(f"{reserved}.md") == "design.md"

    @pytest.mark.parametrize("reserved", [
        "con", "prn", "aux", "nul", "com1", "lpt1",
    ])
    def test_reserved_name_lowercase_returns_default(self, reserved):
        assert sanitize_filename(f"{reserved}.md") == "design.md"

    def test_reserved_name_mixed_case_returns_default(self):
        assert sanitize_filename("Con.md") == "design.md"

    def test_non_reserved_similar_name_allowed(self):
        # "CONSOLE" 不在保留名列表中
        assert sanitize_filename("CONSOLE.md") == "CONSOLE.md"

    def test_null_device_no_extension_returns_default(self):
        # 无后缀时 stem == "NUL"，仍应拒绝
        assert sanitize_filename("NUL") == "design.md"


# ---------------------------------------------------------------------------
# 首尾点/空格
# ---------------------------------------------------------------------------

class TestLeadingTrailingDotsAndSpaces:
    def test_leading_dots_stripped(self):
        # "...foo.md" → Path().name → "...foo.md" → strip(". ") → "foo.md"
        assert sanitize_filename("...foo.md") == "foo.md"

    def test_trailing_dot_stripped(self):
        # "foo.md." → strip(". ") → "foo.md"（已有 .md，不再追加）
        assert sanitize_filename("foo.md.") == "foo.md"

    def test_only_dots_returns_default(self):
        # strip(". ") 之后为空 → default
        assert sanitize_filename("...") == "design.md"

    def test_dot_and_spaces_returns_default(self):
        assert sanitize_filename(".  .") == "design.md"
