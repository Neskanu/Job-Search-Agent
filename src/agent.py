import os
import re
from typing import Dict, Any, Tuple, Optional
from src.parser import read_cv, save_cv_as_docx, save_cv_as_pdf
from src.tailorer import tailor_cv

def sanitize_filename(name: str) -> str:
    """Remove invalid filesystem characters from strings to make safe filenames."""
    return re.sub(r'[\\/*?:"<>| ]', '_', name)

def run_cv_tailoring_pipeline(
    original_cv_path: str,
    job_description_text: str,
    job_title: str,
    company: str,
    provider: str,
    llm_config: Dict[str, Any],
    output_dir: str = "data/tailored_cvs",
    additional_info: Optional[str] = None
) -> Tuple[Dict[str, Any], str, str]:
    """
    Orchestrate the CV tailoring pipeline:
    1. Read original CV file.
    2. Invoke selected LLM provider to rewrite content matching the job description.
    3. Generate and save tailored CV as PDF and DOCX files.
    
    Returns:
        (tailored_cv_data, docx_path, pdf_path)
    """
    if not os.path.exists(original_cv_path):
        raise FileNotFoundError(f"Original CV not found at path: {original_cv_path}")
        
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Read Original CV
    original_cv_text = read_cv(original_cv_path)
    
    # 2. Call LLM to tailor the content
    tailored_cv_data = tailor_cv(
        original_cv_text=original_cv_text,
        job_description_text=job_description_text,
        job_title=job_title,
        company=company,
        provider=provider,
        config=llm_config,
        additional_info=additional_info
    )
    
    # 3. Save tailored CV files
    candidate_name = tailored_cv_data.get("name", "Tailored")
    sanitized_name = sanitize_filename(candidate_name)
    sanitized_company = sanitize_filename(company)
    sanitized_title = sanitize_filename(job_title)
    
    filename_base = f"{sanitized_name}_CV_{sanitized_company}_{sanitized_title}"
    
    docx_path = os.path.join(output_dir, f"{filename_base}.docx")
    pdf_path = os.path.join(output_dir, f"{filename_base}.pdf")
    
    # Generate DOCX
    save_cv_as_docx(tailored_cv_data, docx_path)
    
    # Generate PDF
    save_cv_as_pdf(tailored_cv_data, pdf_path)
    
    return tailored_cv_data, docx_path, pdf_path
