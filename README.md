# CV Tailor AI: LinkedIn Job Search & CV Optimization Web App

A modern, responsive web application that searches LinkedIn for jobs, scrapes posting descriptions, and optimizes your original CV to match the job criteria. Powered by a **FastAPI** backend and a custom **HTML/CSS/JS** single-page frontend featuring a native drag-and-drop WYSIWYG editor. 

Allows tailoring CVs using Google Gemini or local Ollama instances, outputting ATS-compliant resumes in both PDF and Word (.docx) formats.

---

## Features

1. **FastAPI Backend**: Native async routes for Playwright browser scraping and LLM completion pipelines.
2. **Native WYSIWYG Editor**: Directly drag and reorder resume sections (powered by SortableJS) and edit any text element inline.
3. **LinkedIn Scraper**: Playwright-based search and direct URL details scraper.
4. **LLM Provider Options**: Supports Google Gemini API (via async clients) or local Ollama instances.
5. **High-quality Document Compiler**: Writes styled, single-column ATS-compliant PDF (ReportLab) and DOCX (python-docx) files.

---

## Installation & Setup

### 1. Prerequisites
- Python 3.9 or higher.
- (Optional) [Ollama](https://ollama.com/) if running LLMs locally.

### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 3. Install Playwright Browsers (Required for Scraper)
```bash
playwright install chromium
```

### 4. Configure Environment Variables
Create a `.env` file in the root folder (or copy from the `.env` template):
```env
GEMINI_API_KEY=your_google_gemini_api_key
```

---

## How to Run

### Run the FastAPI Web Server
Start the Uvicorn ASGI server in reload mode (perfect for local development):
```bash
python -m uvicorn src.main:app --reload
```

Open **`http://localhost:8000`** in your browser.

---

## Step-by-Step Usage Guide

1. **LLM Config**: In the left console panel, choose your LLM Provider (Gemini or Ollama). Enter your API key if using Gemini.
2. **LinkedIn Session (Optional)**: Paste your `li_at` cookie in the input field to authenticate the job search and scraper. (Inspect LinkedIn -> Application Tab -> Cookies -> Copy `li_at`).
3. **Upload CV**: Click the upload box in **Tab 1** and upload your current CV (PDF or DOCX). You can also add custom guidelines in the text area (e.g. *"Focus heavily on AWS experience"*).
4. **Find a Target Job**: Go to **Tab 2** to search LinkedIn and click **Select Job** on a result card. Or, go to **Tab 3** and paste a direct job URL to scrape details automatically.
5. **Optimize CV**: Click **Optimize Resume for Role** at the bottom of the console.
6. **Edit Inline & Download**: The live tailored CV page will render on the right. You can:
   - Drag sections (using the `☰` handle) to reorder them.
   - Click any text element (name, titles, bullet points) and edit inline.
   - Click `+ Add Bullet` or `🗑️ Delete Block` on items.
   - Click `💾 Save Changes` at the top right to compile, and then download the Word or PDF formats!

---

## Development & Verification

### Running Automated Tests
The project contains unit tests for document readers and compilers. Run:
```bash
pytest
```
To run tests with PYTHONPATH set:
- **Windows PowerShell**: `$env:PYTHONPATH="." ; pytest`
- **Linux/macOS**: `PYTHONPATH=. pytest`
