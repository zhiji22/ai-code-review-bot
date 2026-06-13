"""Unit tests for the rule engine."""

from __future__ import annotations

import pytest
from app.analyzers.rule_engine import RuleCategory, RuleEngine, RuleSeverity


class TestRuleEngine:
    """Tests for built-in rule detection."""

    @pytest.fixture
    def engine(self) -> RuleEngine:
        return RuleEngine()

    def test_sql_injection_detection(self, engine: RuleEngine) -> None:
        code = 'cursor.execute("SELECT * FROM users WHERE id = " + user_id)'
        violations = engine.check(code, "python")
        sec_violations = [v for v in violations if v.category == RuleCategory.SECURITY]
        assert len(sec_violations) > 0
        assert any("SEC001" in v.rule_id for v in sec_violations)

    def test_hardcoded_secret_detection(self, engine: RuleEngine) -> None:
        code = 'password = "super_secret_password_12345"'
        violations = engine.check(code, "python")
        assert any("SEC002" in v.rule_id for v in violations)

    def test_disabled_https_verify(self, engine: RuleEngine) -> None:
        code = "requests.post(url, verify=False)"
        violations = engine.check(code, "python")
        assert any("SEC005" in v.rule_id for v in violations)

    def test_eval_command_injection(self, engine: RuleEngine) -> None:
        code = "eval(user_input)"
        violations = engine.check(code, "python")
        # eval() matches SEC003 (Unsafe Deserialization), not SEC006 (Command Injection)
        assert any("SEC003" in v.rule_id for v in violations)

    def test_weak_hashing(self, engine: RuleEngine) -> None:
        code = "import hashlib\nhashlib.md5(data)"
        violations = engine.check(code, "python")
        assert any("SEC007" in v.rule_id for v in violations)

    def test_debug_true(self, engine: RuleEngine) -> None:
        code = "app.run(debug=True)"
        violations = engine.check(code, "python")
        assert any("SEC008" in v.rule_id for v in violations)

    def test_broad_exception_pass(self, engine: RuleEngine) -> None:
        code = """try:
    risky()
except:
    pass"""
        violations = engine.check(code, "python")
        assert any("SEC010" in v.rule_id for v in violations)

    def test_performance_n_plus_1(self, engine: RuleEngine) -> None:
        code = "for user in User.objects.filter(is_active=True):"
        violations = engine.check(code, "python")
        perf = [v for v in violations if v.category == RuleCategory.PERFORMANCE]
        assert len(perf) > 0

    def test_style_long_line(self, engine: RuleEngine) -> None:
        code = "x = " + "a" * 150
        violations = engine.check(code, "python")
        assert any("STYLE001" in v.rule_id for v in violations)

    def test_style_todo_fixme(self, engine: RuleEngine) -> None:
        code = "# TODO: fix this later"
        violations = engine.check(code, "python")
        assert any("STYLE002" in v.rule_id for v in violations)

    def test_style_print_statement(self, engine: RuleEngine) -> None:
        code = 'print("debug info")'
        violations = engine.check(code, "python")
        assert any("STYLE003" in v.rule_id for v in violations)

    def test_best_practice_mutable_default(self, engine: RuleEngine) -> None:
        code = "def foo(items=[]):\n    pass"
        violations = engine.check(code, "python")
        assert any("BP002" in v.rule_id for v in violations)

    def test_javascript_xss_detection(self, engine: RuleEngine) -> None:
        code = "element.innerHTML = userInput;"
        violations = engine.check(code, "javascript")
        assert any("SEC004" in v.rule_id for v in violations)

    def test_clean_code_no_violations(self, engine: RuleEngine) -> None:
        code = '''def calculate_sum(a: int, b: int) -> int:
    """Calculate the sum of two integers."""
    return a + b
'''
        violations = engine.check(code, "python")
        critical = [v for v in violations if v.severity == RuleSeverity.CRITICAL]
        assert len(critical) == 0

    def test_disable_enable_rule(self, engine: RuleEngine) -> None:
        engine.disable_rule("SEC002")
        code = 'password = "hardcoded_secret_value_12345"'
        violations = engine.check(code, "python")
        assert all("SEC002" not in v.rule_id for v in violations)

        engine.enable_rule("SEC002")
        violations = engine.check(code, "python")
        assert any("SEC002" in v.rule_id for v in violations)

    def test_get_rules_by_category(self, engine: RuleEngine) -> None:
        security_rules = engine.get_rules_by_category(RuleCategory.SECURITY)
        assert len(security_rules) >= 10
        assert all(r.category == RuleCategory.SECURITY for r in security_rules)
