"""Eval suite regression tests."""

from app.services.eval_suite import run_eval_suite


def test_eval_suite_passes():
    result = run_eval_suite()
    assert result["total"] >= 1
    assert result["failed"] == 0
