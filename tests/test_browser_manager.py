"""
tests/test_browser_manager.py - Unit tests for BrowserManager module.
"""
import os
import pytest
from unittest.mock import MagicMock, patch

from src.browser_manager import cleanup_profile_locks, prepare_linkedin_cookies


def test_cleanup_profile_locks(tmp_path):
    """Verify lock file removal in browser profile directory."""
    profile_dir = str(tmp_path / "browser_profile")
    os.makedirs(profile_dir, exist_ok=True)
    
    lock_file = os.path.join(profile_dir, "SingletonLock")
    with open(lock_file, "w") as f:
        f.write("lock")
        
    assert os.path.exists(lock_file)
    cleanup_profile_locks(profile_dir)
    assert not os.path.exists(lock_file)


def test_prepare_linkedin_cookies():
    """Verify cookie dictionary preparation for Playwright."""
    cookies = prepare_linkedin_cookies("test_cookie_value")
    assert len(cookies) >= 2
    domains = [c["domain"] for c in cookies]
    assert ".linkedin.com" in domains
    assert "www.linkedin.com" in domains
    assert any(c["name"] == "li_at" and c["value"] == "test_cookie_value" for c in cookies)

    # Empty / null inputs
    assert prepare_linkedin_cookies("") == []
    assert prepare_linkedin_cookies("none") == []
    assert prepare_linkedin_cookies("null") == []
