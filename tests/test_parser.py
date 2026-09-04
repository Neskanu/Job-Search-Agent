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

def test_multi_paragraph_support(tmp_path):
    """Verify that multi-paragraph text sections split with double newlines are cleanly formatted in HTML, DOCX, and PDF."""
    from src.parser import generate_html_for_cv, save_cv_as_pdf_reportlab
    import docx

    multi_cv = {
        "name": "Jane Doe",
        "contact_info": ["jane@example.com"],
        "sections": [
            {
                "title": "Professional Profile",
                "type": "text",
                "content": "Paragraph 1: Experienced architect with focus on scalable cloud systems.\n\nParagraph 2: Specialized in distributed microservices, fault tolerance, and observability.\n\nParagraph 3: Passionate mentor and agile evangelist."
            }
        ]
    }

    # 1. HTML generation
    html_output = generate_html_for_cv(multi_cv)
    assert '<p class="cv-paragraph-p"' in html_output
    assert "Paragraph 1:" in html_output
    assert "Paragraph 2:" in html_output
    assert "Paragraph 3:" in html_output

    # 2. DOCX generation
    docx_file = os.path.join(tmp_path, "multi_para.docx")
    save_cv_as_docx(multi_cv, docx_file)
    assert os.path.exists(docx_file)
    doc = docx.Document(docx_file)
    para_texts = [p.text for p in doc.paragraphs]
    assert any("Paragraph 1:" in t for t in para_texts)
    assert any("Paragraph 2:" in t for t in para_texts)
    assert any("Paragraph 3:" in t for t in para_texts)

    # 3. ReportLab PDF generation
    rl_file = os.path.join(tmp_path, "multi_para_rl.pdf")
    save_cv_as_pdf_reportlab(multi_cv, rl_file)
    assert os.path.exists(rl_file)
    assert os.path.getsize(rl_file) > 0

    # 4. save_cv_as_pdf (HTML engine)
    pdf_file = os.path.join(tmp_path, "multi_para_html.pdf")
    save_cv_as_pdf(multi_cv, pdf_file, pdf_engine="html")
    assert os.path.exists(pdf_file)
    assert os.path.getsize(pdf_file) > 0


def test_fit_one_page_strictly_single_page(tmp_path):
    """Verify that fit_one_page=True strictly constrains even long multi-experience CVs into exactly 1 page."""
    import pypdf

    long_cv = {
        "name": "Alex Mercer",
        "contact_info": ["alex@example.com", "+1-555-0199", "Seattle, WA", "linkedin.com/in/alex"],
        "sections": [
            {
                "title": "Summary",
                "type": "text",
                "content": "Accomplished engineering lead specializing in high-throughput cloud distributed architectures, Kubernetes clusters, and automated CI/CD microservices."
            },
            {
                "title": "Technical Skills",
                "type": "list",
                "content": ["Python", "FastAPI", "Go", "Docker", "Kubernetes", "AWS", "PostgreSQL", "Terraform", "Redis", "Kafka"]
            },
            {
                "title": "Professional Experience",
                "type": "experience",
                "content": [
                    {
                        "role": "Staff Software Engineer",
                        "company": "CloudScale Global",
                        "period": "2021 - Present",
                        "location": "Seattle, WA",
                        "bullets": [
                            "Architected distributed event streaming pipelines handling 25M daily transactions with 99.99% availability.",
                            "Spearheaded database partitioning across PostgreSQL clusters cutting query latency by 45%.",
                            "Mentored team of 10 engineers establishing automated testing standards and trunk-based deployment."
                        ]
                    },
                    {
                        "role": "Senior Cloud Engineer",
                        "company": "NextGen Systems",
                        "period": "2018 - 2021",
                        "location": "San Francisco, CA",
                        "bullets": [
                            "Automated AWS multi-region infrastructure provisioning using Terraform and GitHub Actions saving 20 eng-hours/week.",
                            "Optimized Docker container images reducing deployment bundle sizes by 65% and cold starts by 3x.",
                            "Integrated real-time Prometheus and Grafana telemetry reducing mean time to detection (MTTD) from 45 min to 4 min."
                        ]
                    },
                    {
                        "role": "Software Developer",
                        "company": "DataCore Solutions",
                        "period": "2015 - 2018",
                        "location": "San Francisco, CA",
                        "bullets": [
                            "Developed high-concurrency RESTful APIs using Python and Redis caching serving 500k active users.",
                            "Refactored legacy monolithic reporting service into microservices improving report generation speed by 50%."
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
                        "institution": "University of Washington",
                        "period": "2011 - 2015",
                        "location": "Seattle, WA",
                        "bullets": ["Graduated Magna Cum Laude", "Dean's Honor List"]
                    }
                ]
            }
        ]
    }

    # 1. Without fit_one_page, this 3-job CV spans 2 pages
    pdf_normal = str(tmp_path / "long_cv_normal.pdf")
    save_cv_as_pdf(long_cv, pdf_normal, pdf_engine="html", fit_one_page=False)
    reader_normal = pypdf.PdfReader(pdf_normal)
    assert len(reader_normal.pages) >= 1

    # 2. With fit_one_page=True, dynamic scaling and validation strictly enforces 1 page
    pdf_fit1 = str(tmp_path / "long_cv_fit1.pdf")
    save_cv_as_pdf(long_cv, pdf_fit1, pdf_engine="html", fit_one_page=True)
    reader_fit1 = pypdf.PdfReader(pdf_fit1)
    assert len(reader_fit1.pages) == 1, f"Expected 1 page but got {len(reader_fit1.pages)}"

