import os
import shutil
import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.parser import save_cv_as_docx, save_cv_as_pdf, parse_raw_cv_to_json
from src.agent import sanitize_filename

client = TestClient(app)

SAMPLE_CV_TEXT = """
Alex Mercer
alex.mercer@email.com | (555) 019-9821 | Seattle, WA

Summary
Senior Cloud Solutions Engineer with 6+ years of experience building resilient backend infrastructure and Python microservices on AWS and Kubernetes.

Technical Skills
Python, FastAPI, Docker, Kubernetes, AWS, PostgreSQL, Redis, CI/CD, Terraform

Professional Experience
Senior Infrastructure Engineer | CloudScale Inc. | 2021 - Present | Seattle, WA
- Designed and operated Kubernetes microservices handling 50k requests per minute with 99.99% uptime.
- Optimized database query performance on PostgreSQL reducing API p95 response latency by 35%.
- Automated infrastructure deployment using Terraform and GitHub Actions.

Education
B.S. Computer Science | University of Washington | 2015 - 2019
- Graduated Magna Cum Laude.
"""

def test_full_user_workflow(tmp_path):
    """
    Test 1: Full end-to-end user journey simulation:
    1. Upload CV file to /api/upload-cv
    2. List saved files via /api/list-cvs
    3. Load saved file via /api/load-cv
    4. Compile DOCX and PDF outputs across all layout themes
    """
    # 1. Simulate Uploading a CV file
    sample_path = tmp_path / "sample_resume.txt"
    sample_path.write_text(SAMPLE_CV_TEXT, encoding="utf-8")
    
    with open(sample_path, "rb") as f:
        response = client.post("/api/upload-cv", files={"file": ("sample_resume.txt", f, "text/plain")})
        
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "cv_data" in data
    assert data["cv_data"]["name"] == "Alex Mercer"
    assert "file_path" in data
    assert "pdf_path" in data
    
    # 2. List saved CV library
    list_res = client.get("/api/list-cvs")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["success"] is True
    assert len(list_data["original_cvs"]) > 0
    
    # 3. Load saved CV from disk
    uploaded_file_path = data["file_path"]
    load_res = client.post("/api/load-cv", json={"path": uploaded_file_path})
    assert load_res.status_code == 200
    load_data = load_res.json()
    assert load_data["success"] is True
    assert load_data["cv_data"]["name"] == "Alex Mercer"
    
    # 4. Generate DOCX and PDF outputs for all themes
    themes = ["minimalist", "executive", "creative", "tech", "academic"]
    cv_struct = load_data["cv_data"]
    
    for theme in themes:
        docx_out = tmp_path / f"test_{theme}.docx"
        pdf_out = tmp_path / f"test_{theme}.pdf"
        
        save_cv_as_docx(cv_struct, str(docx_out), theme=theme)
        save_cv_as_pdf(cv_struct, str(pdf_out), theme=theme)
        
        assert os.path.exists(docx_out)
        assert os.path.exists(pdf_out)
        assert os.path.getsize(docx_out) > 0
        assert os.path.getsize(pdf_out) > 0

def test_parse_raw_cv_to_json_heuristics():
    """Test raw text parsing fallback rules."""
    parsed = parse_raw_cv_to_json(SAMPLE_CV_TEXT, "Alex_Mercer.txt")
    assert parsed["name"] == "Alex Mercer"
    assert "alex.mercer@email.com" in parsed["contact_info"]
    assert len(parsed["sections"]) >= 3

def test_preview_downloads_and_js_integrity():
    """Verify inline PDF download endpoint security boundaries and JavaScript integrity."""
    orig_path = "data/original_cv/sample_resume_preview.pdf"
    if not os.path.exists(orig_path):
        os.makedirs("data/original_cv", exist_ok=True)
        with open(orig_path, "wb") as f:
            f.write(b"%PDF-1.4 sample pdf content")
            
    res = client.get(f"/api/download?path={orig_path}&inline=true")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    
    with open("src/static/js/app.js", "r", encoding="utf-8") as f:
        js_code = f.read()
        
    required_fns = [
        "function showOptimizingOverlay",
        "function hideOptimizingOverlay",
        "function showValidationModal",
        "function closeValidationModal",
        "function showOptimizationSummary",
        "function closeSummaryModal",
        "function tailorResume",
        "function renderWYSIWYG",
        "function downloadFormat",
        "function downloadTailoredFile"
    ]
    for fn in required_fns:
        assert fn in js_code, f"Missing required frontend JS function: {fn}"

def test_utf8_filename_download_header():
    """Verify that downloading files with extended UTF-8 characters (e.g. Lithuanian ų) does not crash Starlette headers with UnicodeEncodeError."""
    utf8_path = "data/original_cv/Vytautas_Jurgaitis_mokymų.pdf"
    os.makedirs("data/original_cv", exist_ok=True)
    with open(utf8_path, "wb") as f:
        f.write(b"%PDF-1.4 test utf8 content")
        
    res = client.get(f"/api/download?path={utf8_path}")
    assert res.status_code == 200
    assert "attachment;" in res.headers["content-disposition"]


def test_easy_apply_indicator_support():
    """Verify that Easy Apply indicators are supported across backend schemas and frontend scripts."""
    with open("src/static/js/app.js", "r", encoding="utf-8") as f:
        js_code = f.read()
        
    assert "function renderEasyApplyBadge" in js_code
    assert "function updateBannerEasyApplyBadge" in js_code
    assert "⚡ Easy Apply" in js_code
    assert "🔗 External Apply" in js_code

    from src.main import AutoApplyJob
    job_model = AutoApplyJob(
        job_url="https://linkedin.com/jobs/view/123",
        job_title="Dev",
        company="Co",
        pdf_path="path.pdf",
        easy_apply=True
    )
    assert job_model.easy_apply is True

