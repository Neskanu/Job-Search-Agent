import os
import re
import asyncio
from typing import Dict, Any, Tuple, Optional
from src.parser import read_cv, save_cv_as_docx, save_cv_as_pdf
from src.tailorer import tailor_cv

def sanitize_filename(name: str) -> str:
    """Remove invalid filesystem characters from strings to make safe filenames."""
    return re.sub(r'[\\/*?:"<>| ]', '_', name)

# FastAPI / Async Concept: Because document parsing (reading files) and compiling 
# (writing PDF/Word files) are synchronous, CPU-intensive, or blocking disk-I/O operations, 
# running them directly in our route handlers would halt the single-threaded event loop.
# We use 'asyncio.to_thread()' to offload these blocking functions onto Python's 
# built-in thread pool, ensuring our FastAPI server remains responsive.
async def run_cv_tailoring_pipeline(
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
    Asynchronously orchestrate the CV tailoring pipeline:
    1. Read original CV file on a background thread.
    2. Invoke async LLM provider to rewrite CV matching the job description.
    3. Generate and save tailored CV as PDF and DOCX on background threads.
    
    Returns:
        (tailored_cv_data, docx_path, pdf_path)
    """
    if not os.path.exists(original_cv_path):
        raise FileNotFoundError(f"Original CV not found at path: {original_cv_path}")
        
    # Ensure output directory exists (blocking disk I/O, run in thread)
    await asyncio.to_thread(os.makedirs, output_dir, exist_ok=True)
    
    # 1. Read Original CV (disk I/O)
    original_cv_text = await asyncio.to_thread(read_cv, original_cv_path)
    
    # 2. Call LLM to tailor the content (network I/O)
    tailored_cv_data = await tailor_cv(
        original_cv_text=original_cv_text,
        job_description_text=job_description_text,
        job_title=job_title,
        company=company,
        provider=provider,
        config=llm_config,
        additional_info=additional_info
    )
    
    # 3. Save tailored CV files (disk I/O and PDF render computation)
    candidate_name = tailored_cv_data.get("name", "Tailored")
    sanitized_name = sanitize_filename(candidate_name)
    sanitized_company = sanitize_filename(company)
    sanitized_title = sanitize_filename(job_title)
    
    filename_base = f"{sanitized_name}_CV_{sanitized_company}_{sanitized_title}"
    
    docx_path = os.path.join(output_dir, f"{filename_base}.docx")
    pdf_path = os.path.join(output_dir, f"{filename_base}.pdf")
    
    # Run the DOCX and PDF compiling scripts in thread executors to keep server free
    await asyncio.to_thread(save_cv_as_docx, tailored_cv_data, docx_path)
    await asyncio.to_thread(save_cv_as_pdf, tailored_cv_data, pdf_path)
    
    return tailored_cv_data, docx_path, pdf_path
