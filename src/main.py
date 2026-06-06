import os
import sys
import asyncio
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import read_cv, save_cv_as_docx, save_cv_as_pdf
from src.scraper import scrape_job_details, search_linkedin_jobs
from src.agent import run_cv_tailoring_pipeline, sanitize_filename

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
    keywords: str = Field(..., example="Python Developer")
    location: str = Field(..., example="United States")
    limit: int = Field(default=5, ge=1, le=25, example=5)
    li_at_cookie: Optional[str] = Field(default=None, description="LinkedIn li_at session cookie")

class ScrapeRequest(BaseModel):
    url: str = Field(..., example="https://www.linkedin.com/jobs/view/123456789/")
    li_at_cookie: Optional[str] = Field(default=None)

class TailorRequest(BaseModel):
    original_cv_path: str = Field(..., example="data/original_cv/my_cv.pdf")
    job_description_text: str = Field(..., example="We are looking for a Python engineer...")
    job_title: str = Field(..., example="Python Developer")
    company: str = Field(..., example="Google")
    provider: str = Field(..., example="gemini", description="Must be 'gemini' or 'ollama'")
    llm_config: Dict[str, Any] = Field(..., example={"gemini_model": "gemini-2.5-flash"})
    additional_info: Optional[str] = Field(default=None)

class GenerateDocsRequest(BaseModel):
    cv_data: Dict[str, Any] = Field(..., description="The fully updated JSON representation of the CV")
    job_title: str = Field(..., example="Python Developer")
    company: str = Field(..., example="Google")
    theme: Optional[str] = Field(default="minimalist", description="CV layout style template theme")

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
    and returns the extracted raw text along with the saved file path.
    """
    # Verify file extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.pdf', '.docx', '.txt', '.md']:
        raise HTTPException(status_code=400, detail="Unsupported file format. Please upload PDF, DOCX, TXT, or MD.")
        
    os.makedirs("data/original_cv", exist_ok=True)
    save_path = os.path.join("data/original_cv", file.filename)
    
    # Save the file asynchronously
    try:
        content = await file.read()
        # writing file to disk is blocking, so run it in thread pool
        await asyncio.to_thread(lambda: open(save_path, "wb").write(content))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")
        
    # Read CV text
    try:
        # read_cv is blocking, so run it in thread pool
        cv_text = await asyncio.to_thread(read_cv, save_path)
        return {
            "success": True,
            "filename": file.filename,
            "file_path": save_path,
            "text": cv_text
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse CV document: {str(e)}")


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
        
        # Save files on background threads to prevent event loop lag, passing selected theme layout
        await asyncio.to_thread(save_cv_as_docx, request.cv_data, docx_path, request.theme)
        await asyncio.to_thread(save_cv_as_pdf, request.cv_data, pdf_path, request.theme)
        
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
    t: Optional[str] = None
):
    """
    Serves the compiled PDF or Word file as a file download.
    Implements security bounds checks to avoid directory traversal.
    """
    abs_path = os.path.abspath(path)
    allowed_dir = os.path.abspath("data/tailored_cvs")
    
    # SECURITY: Ensure path is within the allowed output directory boundary
    if not abs_path.startswith(allowed_dir):
        raise HTTPException(status_code=403, detail="Unauthorized file access path.")
        
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="Requested file not found on disk.")
        
    filename = os.path.basename(abs_path)
    # FileResponse handles asynchronous file chunking and header setup (Content-Disposition)
    return FileResponse(
        path=abs_path, 
        filename=filename, 
        media_type="application/octet-stream"
    )

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
