import os
import shutil
import pytest
from src.parser import save_cv_as_docx, save_cv_as_pdf
from src.agent import sanitize_filename

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
    """Verify that docx and pdf files are created without exceptions and exist across all themes."""
    themes = ["minimalist", "executive", "creative", "tech", "academic"]
    
    for theme in themes:
        docx_file = os.path.join(tmp_path, f"test_cv_{theme}.docx")
        pdf_file = os.path.join(tmp_path, f"test_cv_{theme}.pdf")
        
        # Run saving routines
        save_cv_as_docx(DUMMY_CV, docx_file, theme=theme)
        save_cv_as_pdf(DUMMY_CV, pdf_file, theme=theme)
        
        # Assert existence
        assert os.path.exists(docx_file)
        assert os.path.exists(pdf_file)
        
        # Assert size is larger than 0 bytes
        assert os.path.getsize(docx_file) > 0
        assert os.path.getsize(pdf_file) > 0
