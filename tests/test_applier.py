"""
tests/test_applier.py — Unit tests for the LinkedIn Auto-Apply applier module.

Tests the utility functions without launching a real browser, so they run fast.
"""
import re
import os
import json
import pytest
import tempfile
from unittest.mock import MagicMock, patch

# Import the functions we want to test
from src.applier import (
    human_delay,
    sanitize_dirname,
    make_audit_dir,
    extract_numeric_years,
    screenshot_to_base64,
)


# ---------------------------------------------------------------------------
# human_delay tests
# ---------------------------------------------------------------------------

def test_human_delay_is_within_range():
    """Verify human_delay sleeps between min and max seconds."""
    import time
    start = time.time()
    human_delay(0.05, 0.1)
    elapsed = time.time() - start
    assert 0.04 <= elapsed <= 0.5, f"Delay {elapsed:.3f}s is outside expected range"


# ---------------------------------------------------------------------------
# Numeric extractor tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("6+ years", "6"),
    ("Over 5 years", "5"),
    ("3-4 years", "3"),
    ("10", "10"),
    ("More than 2 years experience", "2"),
    ("No number here", None),
    ("", None),
])
def test_extract_numeric_years(text, expected):
    """extract_numeric_years should correctly parse year counts from various formats."""
    assert extract_numeric_years(text) == expected


# ---------------------------------------------------------------------------
# sanitize_dirname tests
# ---------------------------------------------------------------------------

def test_sanitize_dirname_removes_unsafe_chars():
    """Filesystem-unsafe characters should be replaced with underscores."""
    result = sanitize_dirname('Kitron Group / L&D: "Manager"')
    assert "/" not in result
    assert ":" not in result
    assert '"' not in result


# ---------------------------------------------------------------------------
# Audit directory creation
# ---------------------------------------------------------------------------

def test_make_audit_dir_creates_directory():
    """make_audit_dir should create a timestamped dir under data/applications/."""
    os.makedirs("data/applications", exist_ok=True)
    path = make_audit_dir("TestCompany")
    assert os.path.isdir(path)
    assert "TestCompany" in path
    # Cleanup
    import shutil
    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Screenshot base64 encoding
# ---------------------------------------------------------------------------

def test_screenshot_to_base64_returns_data_url(tmp_path):
    """screenshot_to_base64 should return a valid base64 PNG data URL."""
    # Write a tiny fake PNG file
    png_file = tmp_path / "test.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    result = screenshot_to_base64(str(png_file))
    assert result.startswith("data:image/png;base64,")
    assert len(result) > 30


# ---------------------------------------------------------------------------
# Apply job queue result structure
# ---------------------------------------------------------------------------

def test_apply_job_queue_result_structure():
    """apply_job_queue with mocked apply_to_job should return correct result shape."""
    from src.applier import apply_job_queue

    mock_result = {
        "success": True,
        "status": "pending_confirmation",
        "step_reached": "review",
        "screenshots": [],
        "screenshots_b64": [],
        "screening_answers": {},
        "audit_dir": "data/applications/test",
        "error": None
    }

    with patch("src.applier.apply_to_job", return_value=mock_result):
        job_queue = [
            {"job_url": "https://linkedin.com/jobs/view/1234", "job_title": "L&D Manager",
             "company": "Test Corp", "pdf_path": "data/tailored_cvs/test.pdf",
             "cover_letter": "Dear Team...", "answers_override": {}},
        ]
        results = apply_job_queue(job_queue, cv_data={}, li_at="fake_cookie", dry_run=True)

    assert len(results) == 1
    assert results[0]["status"] == "pending_confirmation"
    assert results[0]["company"] == "Test Corp"
    assert results[0]["job_title"] == "L&D Manager"
