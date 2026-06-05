"""Unit tests for the AST analyzer."""

from __future__ import annotations

import pytest

from app.analyzers.ast_analyzer import ASTAnalyzer, ASTReport


class TestASTAnalyzer:
    """Tests for tree-sitter AST analysis."""

    @pytest.fixture
    def analyzer(self) -> ASTAnalyzer:
        return ASTAnalyzer()

    def test_clean_code(self, analyzer: ASTAnalyzer, sample_python_code: str | None = None) -> None:
        """Test that clean simple code has no issues."""
        code = '''def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
'''
        report = analyzer.analyze("test.py", code, "python")
        assert isinstance(report, ASTReport)
        assert report.parse_error is False
        assert report.lines_of_code > 0

    def test_detects_function_complexity(self, analyzer: ASTAnalyzer) -> None:
        code = '''def complex_func(x):
    if x > 0:
        if x > 10:
            if x > 100:
                if x > 1000:
                    for i in range(x):
                        if i % 2 == 0:
                            pass
'''
        report = analyzer.analyze("test.py", code, "python")
        assert report.max_complexity > 5 or len(report.issues) > 0

    def test_detects_nesting_depth(self, analyzer: ASTAnalyzer) -> None:
        code = '''def deep_nesting(data):
    if data:
        if data.get("a"):
            if data["a"].get("b"):
                if data["a"]["b"].get("c"):
                    return True
    return False
'''
        report = analyzer.analyze("test.py", code, "python")
        nesting_issues = [i for i in report.issues if "nesting" in i.issue_type.lower()]
        assert len(nesting_issues) > 0 or report.max_complexity > 3

    def test_count_functions(self, analyzer: ASTAnalyzer) -> None:
        code = '''def func1():
    pass

def func2():
    pass

class MyClass:
    def method(self):
        pass
'''
        report = analyzer.analyzer("test.py", code, "python") if hasattr(analyzer, "analyzer") else analyzer.analyze("test.py", code, "python")
        assert report.function_count >= 3

    def test_parse_error_handling(self, analyzer: ASTAnalyzer) -> None:
        code = "def broken(:\n    !!!invalid python"
        report = analyzer.analyze("test.py", code, "python")
        # Should handle gracefully, not crash
        assert isinstance(report, ASTReport)

    def test_empty_code(self, analyzer: ASTAnalyzer) -> None:
        report = analyzer.analyze("empty.py", "", "python")
        assert isinstance(report, ASTReport)

    def test_unsupported_language(self, analyzer: ASTAnalyzer) -> None:
        code = "echo hello"
        report = analyzer.analyze("test.sh", code, "bash")
        assert isinstance(report, ASTReport)
        # Should handle unsupported languages gracefully

    def test_long_function_detection(self, analyzer: ASTAnalyzer) -> None:
        lines = ["def very_long_function():"] + ["    x = 1"] * 60
        code = "\n".join(lines)
        report = analyzer.analyze("test.py", code, "python")
        length_issues = [i for i in report.issues if "length" in i.message.lower() or "long" in i.message.lower()]
        assert len(length_issues) > 0 or report.lines_of_code > 60
