import os
import shutil
import pytest
from src.parser import save_cv_as_docx, save_cv_as_pdf, parse_raw_cv_to_json
from src.agent import sanitize_filename
from src.scraper import normalize_linkedin_url

def test_parse_raw_cv_to_json():
    raw_text = "Jane Doe\njane@example.com | 555-0199\n\nSummary\nExperienced developer.\n\nSkills\nPython\nFastAPI"
    data = parse_raw_cv_to_json(raw_text, "jane_cv.txt")
    assert data["name"] == "Jane Doe"
    assert "jane@example.com" in data["contact_info"]
    assert len(data["sections"]) > 0

def test_normalize_linkedin_url():
    bad_url1 = "https://www.linkedin.comwww.linkedin.com/jobs/view/mokym%C5%B3-specialistas-%C4%97-at-kitron-group-4439906348/"
    assert normalize_linkedin_url(bad_url1) == "https://www.linkedin.com/jobs/view/mokym%C5%B3-specialistas-%C4%97-at-kitron-group-4439906348/"

    bad_url2 = "www.linkedin.com/jobs/view/4439906348/"
    assert normalize_linkedin_url(bad_url2) == "https://www.linkedin.com/jobs/view/4439906348/"

    bad_url3 = "https://www.linkedin.com/jobs/search/?currentJobId=4439906348&keywords=Python"
    assert normalize_linkedin_url(bad_url3) == "https://www.linkedin.com/jobs/view/4439906348/"

# Test data representing a typical parsed CV
DUMMY_CV = {
    "name": "Jane Doe",
    "contact_info": [
        "jane.doe@email.com",
        "+1 (555) 019-2834",
        "San Francisco, CA",
        "linkedin.com/in/janedoe"
    ],
    "sections": [
        {
            "title": "Summary",
            "type": "text",
            "content": "Result-oriented software developer with 4 years of experience specializing in Python, microservices, and web applications. Proven track record of improving API latency and automation throughput."
        },
        {
            "title": "Technical Skills",
            "type": "list",
            "content": ["Python", "Flask", "PostgreSQL", "Docker", "Git", "REST APIs", "AWS"]
        },
        {
            "title": "Experience",
            "type": "experience",
            "content": [
                {
                    "role": "Software Engineer",
                    "company": "Tech Innovations Inc.",
                    "period": "2022 - Present",
                    "location": "San Francisco, CA",
                    "bullets": [
                        "Designed and developed RESTful microservices using Flask and PostgreSQL, serving 10k+ daily active users.",
                        "Integrated third-party APIs and reduced database query response times by 25%.",
                        "Containerized applications using Docker to streamline dev-to-prod deployment pipeline."
                    ]
                }
            ]
        },
        {
            "title": "Education",
            "type": "education",
            "content": [
                {
                    "degree": "B.S. in Computer Science",
                    "institution": "University of California, Berkeley",
                    "period": "2018 - 2022",
                    "location": "Berkeley, CA",
                    "bullets": ["Graduated with Honors", "GPA: 3.8/4.0"]
                }
            ]
        }
    ]
}

def test_sanitize_filename():
    assert sanitize_filename("Jane Doe/Resume") == "Jane_Doe_Resume"
    assert sanitize_filename("John | Smith: CV") == "John___Smith__CV"

def test_docx_pdf_generation(tmp_path):
    """Verify that docx and pdf files are created without exceptions and exist across all themes and engines."""
    themes = ["minimalist", "executive", "creative", "tech", "academic"]
    engines = ["html", "executive", "classic"]
    
    for theme in themes:
        docx_file = os.path.join(tmp_path, f"test_cv_{theme}.docx")
        save_cv_as_docx(DUMMY_CV, docx_file, theme=theme)
        assert os.path.exists(docx_file)
        assert os.path.getsize(docx_file) > 0

    for engine in engines:
        pdf_file = os.path.join(tmp_path, f"test_cv_{engine}.pdf")
        save_cv_as_pdf(DUMMY_CV, pdf_file, theme="creative", pdf_engine=engine, fit_one_page=False)
        assert os.path.exists(pdf_file)
        assert os.path.getsize(pdf_file) > 0

        pdf_fit1 = os.path.join(tmp_path, f"test_cv_{engine}_fit1.pdf")
        save_cv_as_pdf(DUMMY_CV, pdf_fit1, theme="creative", pdf_engine=engine, fit_one_page=True)
        assert os.path.exists(pdf_fit1)
        assert os.path.getsize(pdf_fit1) > 0
