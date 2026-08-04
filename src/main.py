import os
import sys
import json
import asyncio
import urllib.parse
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import read_cv, save_cv_as_docx, save_cv_as_pdf, parse_raw_cv_to_json
from src.scraper import scrape_job_details, search_linkedin_jobs
from src.agent import run_cv_tailoring_pipeline, sanitize_filename
from src.tailorer import generate_cover_letter
from src.applier import apply_to_job, apply_job_queue

# ==========================================
# 🚀 FastAPI INITIALIZATION
# ==========================================

# Create the main FastAPI application instance.
# FastAPI automatically hosts interactive Swagger API docs at '/docs' and Redoc at '/redoc'.
app = FastAPI(
    title="CV Tailor AI Agent API",
    description="Backend API for managing LinkedIn job searches, scraping job postings, and tailoring resumes using LLMs.",
    version="1.0.0"
)

# CORS (Cross-Origin Resource Sharing) Middleware.
# This allows requests coming from different domains/ports (like frontends running on other servers)
# to communicate with our FastAPI backend. Here we allow everything for local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 📊 PYDANTIC MODELS (Request Schemas)
# ==========================================

# Pydantic is a data validation library. In FastAPI, we define classes inheriting from 
# BaseModel to define the exact structure of data we expect in request bodies.
# FastAPI will automatically validate incoming JSON against these schemas, throw 422 errors 
# if validation fails, and document these schemas in the Swagger UI.

class SearchRequest(BaseModel):
    keywords: str = Field(..., json_schema_extra={"example": "Python Developer"})
    location: str = Field(..., json_schema_extra={"example": "United States"})
    limit: int = Field(default=5, ge=1, le=25, json_schema_extra={"example": 5})
    li_at_cookie: Optional[str] = Field(default=None, description="LinkedIn li_at session cookie")

class ScrapeRequest(BaseModel):
    url: str = Field(..., json_schema_extra={"example": "https://www.linkedin.com/jobs/view/123456789/"})
    li_at_cookie: Optional[str] = Field(default=None)

class TailorRequest(BaseModel):
    original_cv_path: str = Field(..., json_schema_extra={"example": "data/original_cv/my_cv.pdf"})
    job_description_text: str = Field(..., json_schema_extra={"example": "We are looking for a Python engineer..."})
    job_title: str = Field(..., json_schema_extra={"example": "Python Developer"})
    company: str = Field(..., json_schema_extra={"example": "Google"})
    provider: str = Field(..., json_schema_extra={"example": "gemini"}, description="Must be 'gemini' or 'ollama'")
    llm_config: Dict[str, Any] = Field(..., json_schema_extra={"example": {"gemini_model": "gemini-2.5-flash"}})
    additional_info: Optional[str] = Field(default=None)

class GenerateDocsRequest(BaseModel):
    cv_data: Dict[str, Any] = Field(..., description="The fully updated JSON representation of the CV")
    job_title: str = Field(..., json_schema_extra={"example": "Python Developer"})
    company: str = Field(..., json_schema_extra={"example": "Google"})
    theme: Optional[str] = Field(default="minimalist", description="CV layout style template theme")
    custom_color: Optional[str] = Field(default=None, description="Custom accent color hex")
    line_style: Optional[str] = Field(default="short", description="Accent line style: short, full, none")
    bullet_symbol: Optional[str] = Field(default="│", description="Bullet symbol: │, ▸, •, ◆")
    layout_mode: Optional[str] = Field(default="2col", description="Layout mode: 2col, 1col")

# ==========================================
# 🛠️ API ENDPOINTS
# ==========================================

# FastAPI Concept: Endpoint handlers are marked as 'async def' so they run on FastAPI's 
# asynchronous event loop. Any blocking calls (like file saving) are wrapped in 
# 'asyncio.to_thread' to run them in a separate thread pool so they don't block the server.

@app.post("/api/upload-cv", summary="Upload original CV")
async def upload_cv(file: UploadFile = File(...)):
    """
    Uploads a CV file (PDF or DOCX), saves it to the local data directory,
    parses it into structured cv_data JSON, compiles a preview PDF, and returns the workspace state.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.pdf', '.docx', '.txt', '.md']:
        raise HTTPException(status_code=400, detail="Unsupported file format. Please upload PDF, DOCX, TXT, or MD.")
        
    os.makedirs("data/original_cv", exist_ok=True)
    save_path = os.path.join("data/original_cv", file.filename).replace("\\", "/")
    
    try:
        content = await file.read()
        await asyncio.to_thread(lambda: open(save_path, "wb").write(content))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")
        
    try:
        cv_text = await asyncio.to_thread(read_cv, save_path)
        cv_data = parse_raw_cv_to_json(cv_text, file.filename)
        
        # Compile a PDF preview for the uploaded document
        base_name = os.path.splitext(file.filename)[0]
        pdf_preview_path = os.path.join("data/original_cv", f"preview_{base_name}.pdf").replace("\\", "/")
        await asyncio.to_thread(save_cv_as_pdf, cv_data, pdf_preview_path)
        
        return {
            "success": True,
            "filename": file.filename,
            "file_path": save_path,
            "pdf_path": pdf_preview_path,
            "cv_data": cv_data,
            "text": cv_text
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse CV document: {str(e)}")


@app.get("/api/list-cvs", summary="List stored original and tailored CVs")
async def list_cvs():
    """Returns lists of stored original CVs and previously generated tailored CVs."""
    os.makedirs("data/original_cv", exist_ok=True)
    os.makedirs("data/tailored_cvs", exist_ok=True)
    
    orig_files = []
    # Check data/original_cv
    for f in os.listdir("data/original_cv"):
        if f.lower().endswith(('.pdf', '.docx', '.txt', '.md')) and not f.startswith("preview_") and not f.endswith("_preview.pdf"):
            orig_files.append({"name": f, "path": f"data/original_cv/{f}"})
            
    # Also check data/ root folder for any original CV files
    for f in os.listdir("data"):
        p = os.path.join("data", f)
        if os.path.isfile(p) and f.lower().endswith(('.pdf', '.docx', '.txt', '.md')) and not f.startswith("preview_"):
            orig_files.append({"name": f, "path": f"data/{f}"})
            
    tailored_files = []
    for f in os.listdir("data/tailored_cvs"):
        if f.lower().endswith(('.pdf', '.docx')):
            tailored_files.append({"name": f, "path": f"data/tailored_cvs/{f}"})
            
    return {
        "success": True,
        "original_cvs": orig_files,
        "tailored_cvs": tailored_files
    }


class LoadCVRequest(BaseModel):
    path: str

@app.post("/api/load-cv", summary="Load previously saved CV from disk")
async def load_cv(request: LoadCVRequest):
    """Loads a previously uploaded original CV or tailored CV from disk and parses it for WYSIWYG rendering."""
    if not os.path.exists(request.path):
        raise HTTPException(status_code=404, detail=f"File not found: {request.path}")
        
    try:
        cv_text = await asyncio.to_thread(read_cv, request.path)
        filename = os.path.basename(request.path)
        cv_data = parse_raw_cv_to_json(cv_text, filename)
        
        pdf_path = request.path
        if not request.path.lower().endswith(".pdf"):
            pdf_path = os.path.splitext(request.path)[0] + "_preview.pdf"
            await asyncio.to_thread(save_cv_as_pdf, cv_data, pdf_path)
            
        return {
            "success": True,
            "filename": filename,
            "file_path": request.path,
            "pdf_path": pdf_path,
            "cv_data": cv_data,
            "text": cv_text
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load CV: {str(e)}")


@app.post("/api/search-jobs", summary="Browse LinkedIn jobs")
async def search_jobs(request: SearchRequest):
    """
    Search LinkedIn jobs synchronously in a background thread.
    FastAPI / Python Learning Point:
    Since 'search_linkedin_jobs' is a blocking synchronous function (it spawns and joins a thread
    internally), we cannot await it directly (which raises TypeError) and we shouldn't run it
    synchronously in an 'async def' path (which blocks the entire server's event loop).
    Instead, we wrap the call in 'asyncio.to_thread(...)', which offloads it to a system thread pool
    and yields control back to the event loop while it runs.
    """
    try:
        jobs = await asyncio.to_thread(
            search_linkedin_jobs,
            keywords=request.keywords,
            location=request.location,
            limit=request.limit,
            li_at_cookie=request.li_at_cookie
        )
        return {"success": True, "jobs": jobs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Job search failed: {str(e)}")


@app.post("/api/scrape-job", summary="Scrape job details")
async def scrape_job(request: ScrapeRequest):
    """
    Scrape job details synchronously in a background thread.
    FastAPI / Python Learning Point:
    Like the search endpoint, 'scrape_job_details' is synchronous. We offload it to
    'asyncio.to_thread' to run it in a worker thread pool so other clients can continue
    making API requests concurrently.
    """
    try:
        data = await asyncio.to_thread(
            scrape_job_details,
            request.url,
            request.li_at_cookie
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scrape job details: {str(e)}")


@app.post("/api/tailor-cv", summary="AI CV Tailoring Pipeline")
async def tailor_resume(request: TailorRequest):
    """
    Trigger the LLM cv optimization agent. Returns tailored JSON CV structure
    and the file paths of initial PDF/Word builds.
    """
    try:
        # Await the async orchestrator pipeline
        tailored_data, docx_path, pdf_path = await run_cv_tailoring_pipeline(
            original_cv_path=request.original_cv_path,
            job_description_text=request.job_description_text,
            job_title=request.job_title,
            company=request.company,
            provider=request.provider,
            llm_config=request.llm_config,
            additional_info=request.additional_info
        )
        return {
            "success": True,
            "cv_data": tailored_data,
            "docx_path": docx_path,
            "pdf_path": pdf_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CV tailoring process failed: {str(e)}")


@app.post("/api/generate-docs", summary="Compile edited JSON to PDF and DOCX")
async def generate_docs(request: GenerateDocsRequest):
    """
    Accepts CV data (after WYSIWYG edits) and regenerates PDF and DOCX files.
    """
    try:
        os.makedirs("data/tailored_cvs", exist_ok=True)
        
        candidate_name = request.cv_data.get("name", "Tailored")
        sanitized_name = sanitize_filename(candidate_name)
        sanitized_company = sanitize_filename(request.company)
        sanitized_title = sanitize_filename(request.job_title)
        
        filename_base = f"{sanitized_name}_CV_{sanitized_company}_{sanitized_title}"
        docx_path = os.path.join("data/tailored_cvs", f"{filename_base}.docx")
        pdf_path = os.path.join("data/tailored_cvs", f"{filename_base}.pdf")
        
        # Save files on background threads to prevent event loop lag, passing selected theme layout & customizations
        await asyncio.to_thread(save_cv_as_docx, request.cv_data, docx_path, request.theme, request.custom_color, request.bullet_symbol)
        await asyncio.to_thread(save_cv_as_pdf, request.cv_data, pdf_path, request.theme, request.custom_color, request.line_style, request.bullet_symbol, request.layout_mode)
        
        return {
            "success": True,
            "docx_path": docx_path,
            "pdf_path": pdf_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to regenerate files: {str(e)}")


@app.get("/api/download", summary="Download file response")
async def download_file(
    path: str = Query(..., description="Absolute path to the generated file"),
    inline: Optional[bool] = Query(default=False, description="Whether to view file inline in browser"),
    t: Optional[str] = None
):
    """
    Serves the compiled PDF or Word file as a file download or inline view.
    Implements security bounds checks to avoid directory traversal.
    """
    abs_path = os.path.abspath(path)
    allowed_dir = os.path.abspath("data")
    
    # SECURITY: Ensure path is within the data output directory boundary
    if not abs_path.startswith(allowed_dir):
        raise HTTPException(status_code=403, detail="Unauthorized file access path.")
        
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="Requested file not found on disk.")
        
    filename = os.path.basename(abs_path)
    encoded_filename = urllib.parse.quote(filename)
    
    headers = {}
    if inline:
        headers["Content-Disposition"] = "inline"
        if abs_path.lower().endswith(".pdf"):
            media_type = "application/pdf"
        elif abs_path.lower().endswith(".docx"):
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            media_type = "application/octet-stream"
    else:
        # RFC 5987 standard encoding for UTF-8 filenames in HTTP headers
        headers["Content-Disposition"] = f'attachment; filename="{encoded_filename}"; filename*=UTF-8\'\'{encoded_filename}'
        media_type = "application/octet-stream"
        
    return FileResponse(
        path=abs_path, 
        media_type=media_type,
        headers=headers
    )

# ==========================================
# 🚀 AUTO-APPLY ENDPOINTS
# ==========================================

class CoverLetterRequest(BaseModel):
    """Request body for generating an AI cover letter."""
    cv_data: Dict[str, Any]
    job_description: str
    job_title: str
    company: str
    provider: str = "gemini"
    llm_config: Dict[str, Any] = {}


class AutoApplyJob(BaseModel):
    """A single job entry in the auto-apply queue."""
    job_url: str
    job_title: str
    company: str
    pdf_path: str
    cover_letter: Optional[str] = ""
    answers_override: Optional[Dict[str, str]] = {}
    easy_apply: Optional[bool] = None


class AutoApplyRequest(BaseModel):
    """Request body for triggering the auto-apply queue."""
    job_queue: List[AutoApplyJob]
    li_at: str
    cv_data: Dict[str, Any]
    dry_run: bool = True  # Always True by default — must confirm before submitting


@app.post("/api/generate-cover-letter", summary="Generate AI cover letter for a job")
async def api_generate_cover_letter(req: CoverLetterRequest):
    """
    Use the configured LLM to generate a 3-paragraph, plain-text cover letter
    tailored to the specific job description and candidate CV.
    The user can edit the returned text before it is sent during auto-apply.
    """
    try:
        cover_letter = await generate_cover_letter(
            cv_data=req.cv_data,
            job_description=req.job_description,
            job_title=req.job_title,
            company=req.company,
            provider=req.provider,
            config=req.llm_config
        )
        return {"success": True, "cover_letter": cover_letter}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cover letter generation failed: {str(e)}")


@app.post("/api/auto-apply", summary="Run LinkedIn Easy Apply on a queue of jobs")
async def api_auto_apply(req: AutoApplyRequest):
    """
    Processes a queue of LinkedIn Easy Apply jobs one by one using Playwright.

    When dry_run=True (default): fills all form steps but stops before Submit.
    Returns screenshots and form summary for user confirmation.

    When dry_run=False: actually clicks Submit on each job.
    Should only be called after the user reviews and confirms the dry-run results.
    """
    try:
        os.makedirs("data/applications", exist_ok=True)

        # Convert Pydantic models to plain dicts for applier module
        job_queue_dicts = [
            {
                "job_url": job.job_url,
                "job_title": job.job_title,
                "company": job.company,
                "pdf_path": job.pdf_path,
                "cover_letter": job.cover_letter or "",
                "answers_override": job.answers_override or {}
            }
            for job in req.job_queue
        ]

        # Run the queue in a background thread (Playwright is synchronous)
        results = await asyncio.to_thread(
            apply_job_queue,
            job_queue_dicts,
            req.cv_data,
            req.li_at,
            req.dry_run
        )

        # Strip large base64 screenshots from the JSON response summary
        # (screenshots are available as files in data/applications/)
        summary = []
        for r in results:
            summary.append({
                k: v for k, v in r.items() if k != "screenshots_b64"
            })

        all_ok = all(r.get("success") for r in results)
        return {
            "success": all_ok,
            "dry_run": req.dry_run,
            "total_jobs": len(results),
            "results": summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Auto-apply failed: {str(e)}")


@app.get("/api/list-applications", summary="List past job application audit records")
async def api_list_applications():
    """
    Scan data/applications/ for subdirectories containing result.json files
    and return a list of past application records for the history panel.
    Each record includes: company, job_url, status, submitted_at, step_reached.
    """
    apps_dir = "data/applications"
    if not os.path.exists(apps_dir):
        return {"applications": []}

    applications = []
    for entry in sorted(os.scandir(apps_dir), key=lambda e: e.stat().st_mtime, reverse=True):
        if not entry.is_dir():
            continue
        result_path = os.path.join(entry.path, "result.json")
        if not os.path.exists(result_path):
            continue
        try:
            with open(result_path, encoding="utf-8") as f:
                record = json.load(f)
            applications.append({
                "company": record.get("company", "Unknown"),
                "job_url": record.get("job_url", ""),
                "status": record.get("status", "unknown"),
                "step_reached": record.get("step_reached", ""),
                "submitted_at": record.get("submitted_at", ""),
                "audit_dir": entry.path
            })
        except Exception:
            pass  # Skip malformed records silently

    return {"applications": applications}

# ==========================================
# 🌐 STATIC FILES SERVING (Frontend SPA)
# ==========================================

# Mount the static directory so FastAPI serves the HTML/JS/CSS single-page application.
# Starlette (FastAPI's engine) serves files asynchronously from this directory.
# This should be mounted AFTER the API routes so it doesn't intercept API paths.
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
else:
    # If the static directory doesn't exist yet, we define a placeholder root route
    @app.get("/")
    async def root_placeholder():
        return JSONResponse({
            "message": "FastAPI server is running. Create 'src/static' directory to serve the frontend SPA.",
            "docs_url": "/docs"
        })
