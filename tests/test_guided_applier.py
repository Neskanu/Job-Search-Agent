"""
tests/test_guided_applier.py - Unit tests for Guided Applier module.
"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock

from src.guided_applier import (
    normalize_label,
    load_answers_memory,
    save_answers_memory,
    fuzzy_lookup,
    generate_secure_password,
    detect_ats_platform,
    derive_from_cv_heuristics,
    save_session,
    load_session,
)


def test_normalize_label():
    """Verify normalize_label strips special characters and normalizes spaces."""
    assert normalize_label("Years of Experience with Python?") == "years of experience with python"
    assert normalize_label("First Name * (required)") == "first name required"
    assert normalize_label("Email Address:") == "email address"
    assert normalize_label("  LinkedIn  Profile   URL ") == "linkedin profile url"


def test_fuzzy_lookup_exact_and_similar(tmp_path):
    """Verify fuzzy_lookup matches similar labels above similarity threshold."""
    memory = {
        "years of experience with python": "6",
        "email address": "test@example.com",
        "are you authorized to work in the US": "Yes"
    }

    # Exact match
    val, score = fuzzy_lookup("Email Address", memory, threshold=0.75)
    assert val == "test@example.com"
    assert score >= 0.75

    # Slight variation
    val, score = fuzzy_lookup("Years of Python experience?", memory, threshold=0.70)
    assert val == "6"
    assert score >= 0.70

    # Below threshold miss
    val, score = fuzzy_lookup("Favorite Programming Language", memory, threshold=0.75)
    assert val is None


def test_memory_load_save(tmp_path):
    """Verify load_answers_memory and save_answers_memory."""
    mem_file = str(tmp_path / "test_memory.json")
    mem = load_answers_memory(mem_file)
    assert "are you legally authorized to work" in mem

    mem["years of experience with python"] = "7"
    save_answers_memory(mem, mem_file)

    reloaded = load_answers_memory(mem_file)
    assert reloaded["years of experience with python"] == "7"


def test_generate_secure_password():
    """Verify password generator output constraints."""
    pwd = generate_secure_password(16)
    assert len(pwd) == 16
    assert any(c.isupper() for c in pwd)
    assert any(c.islower() for c in pwd)
    assert any(c.isdigit() for c in pwd)
    assert any(c in "!@#$%^&*" for c in pwd)


def test_detect_ats_platform():
    """Verify ATS platform detection by URL domain."""
    assert detect_ats_platform("https://kitron.wd3.myworkdayjobs.com/Careers") == "workday"
    assert detect_ats_platform("https://jobs.lever.co/company/role") == "lever"
    assert detect_ats_platform("https://boards.greenhouse.io/company/jobs/123") == "greenhouse"
    assert detect_ats_platform("https://careers-company.icims.com/jobs/456") == "icims"
    assert detect_ats_platform("https://company.com/careers/apply") == "generic"


def test_derive_from_cv_heuristics():
    """Verify field heuristics from structured CV data."""
    cv_data = {
        "name": "Vytautas Neskanu",
        "contact_info": ["vytautas@example.com", "+37060000000", "https://linkedin.com/in/vytautas"]
    }

    assert derive_from_cv_heuristics("First Name", cv_data) == "Vytautas"
    assert derive_from_cv_heuristics("Last Name", cv_data) == "Neskanu"
    assert derive_from_cv_heuristics("Email", cv_data) == "vytautas@example.com"
    assert derive_from_cv_heuristics("Mobile Phone Number", cv_data) == "+37060000000"
    assert derive_from_cv_heuristics("LinkedIn Profile", cv_data) == "https://linkedin.com/in/vytautas"


def test_save_and_load_session(tmp_path):
    """Verify session state persistence and loading."""
    with patch("src.guided_applier.SESSIONS_DIR", str(tmp_path)):
        session_id = save_session(
            company="Kitron Group",
            portal_url="https://kitron.wd3.myworkdayjobs.com/test",
            current_step=2,
            total_steps=4,
            filled_fields={"First Name": "Vytautas"},
            status="running"
        )

        session_data = load_session(session_id)
        assert session_data is not None
        assert session_data["company"] == "Kitron Group"
        assert session_data["current_step"] == 2
        assert session_data["filled_fields"]["First Name"] == "Vytautas"


def test_api_answers_memory_endpoints(tmp_path):
    """Test GET and POST /api/answers-memory endpoints."""
    from fastapi.testclient import TestClient
    from src.main import app

    client = TestClient(app)

    # 1. GET memory
    response = client.get("/api/answers-memory")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)

    # 2. POST update memory
    updated_memory = data.copy()
    updated_memory["years of experience with python"] = "8"
    post_res = client.post("/api/answers-memory", json={"memory": updated_memory})
    assert post_res.status_code == 200
    assert post_res.json()["success"] is True

    # 3. Verify GET returns updated memory
    verify_res = client.get("/api/answers-memory")
    assert verify_res.json()["years of experience with python"] == "8"


def test_is_search_or_nav_field():
    """Verify search and navigation inputs are correctly identified and skipped."""
    from src.guided_applier import is_search_or_nav_field
    from unittest.mock import MagicMock

    el_search = MagicMock()
    el_search.get_attribute.side_effect = lambda attr: "search" if attr in ("type", "name") else ""

    assert is_search_or_nav_field(el_search, "Search") is True
    assert is_search_or_nav_field(el_search, "Search Jobs") is True
    assert is_search_or_nav_field(el_search, "Paieška") is True

    el_normal = MagicMock()
    el_normal.get_attribute.side_effect = lambda attr: "text" if attr == "type" else "first_name"

    assert is_search_or_nav_field(el_normal, "First Name") is False


def test_is_uuid_or_random_id():
    """Verify GUIDs and random dynamic IDs are correctly recognized and filtered out."""
    from src.guided_applier import is_uuid_or_random_id

    assert is_uuid_or_random_id("a2afee6c-96db-497d-b1a9-ddb297e5e239") is True
    assert is_uuid_or_random_id("B1C2D3E4-F5A6-7B8C-9D0E-1F2A3B4C5D6E") is True
    assert is_uuid_or_random_id("First Name") is False
    assert is_uuid_or_random_id("Email Address") is False
    assert is_uuid_or_random_id("Years of Experience") is False


def test_is_target_closed_error():
    """Verify target closed error message detector."""
    from src.guided_applier import is_target_closed_error

    err1 = Exception("Page.evaluate: Target page, context or browser has been closed")
    err2 = Exception("Page.query_selector_all: Target page, context or browser has been closed")
    err3 = Exception("Some other network timeout error")

    assert is_target_closed_error(err1) is True
    assert is_target_closed_error(err2) is True
    assert is_target_closed_error(err3) is False
    assert is_target_closed_error(None) is False


def test_get_active_page():
    """Verify active page resolution logic."""
    from src.guided_applier import get_active_page

    page_open = MagicMock()
    page_open.is_closed.return_value = False

    page_closed = MagicMock()
    page_closed.is_closed.return_value = True

    context_mock = MagicMock()
    context_mock.pages = [page_closed, page_open]

    # Current page is open -> returns current page
    assert get_active_page(context_mock, page_open) == page_open

    # Current page is closed -> falls back to open page in context
    assert get_active_page(context_mock, page_closed) == page_open

    # All pages closed -> returns None
    context_all_closed = MagicMock()
    context_all_closed.pages = [page_closed]
    assert get_active_page(context_all_closed, page_closed) is None



