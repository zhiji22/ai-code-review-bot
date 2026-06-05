#!/usr/bin/env bash
set -euo pipefail

# Test runner script
# Usage: ./scripts/test.sh [unit|integration|e2e|all|coverage]

MODE="${1:-all}"

echo "🧪 Running tests (mode: $MODE)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

case "$MODE" in
  unit)
    pytest -m unit -v
    ;;
  integration)
    pytest -m integration -v
    ;;
  e2e)
    pytest -m e2e -v
    ;;
  coverage)
    pytest --cov=app --cov-report=html --cov-report=term-missing
    echo "📊 Coverage report: htmlcov/index.html"
    ;;
  all)
    pytest -v
    ;;
  fast)
    pytest -m "not slow" -v -x
    ;;
  watch)
    pytest-watch -- -m unit -v
    ;;
  *)
    echo "Usage: $0 {unit|integration|e2e|coverage|all|fast|watch}"
    exit 1
    ;;
esac
