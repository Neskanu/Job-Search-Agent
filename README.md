# CV Tailor AI: LinkedIn Job Search & CV Optimization Agent

An interactive Python application that searches LinkedIn for jobs, reads posting descriptions, and optimizes your original CV to align with the job requirements. It uses Google Gemini or a local Ollama model to tailor your experience while retaining human readability and truthfulness, generating ATS-compliant outputs in both Word (DOCX) and PDF formats.

---

## Features

1. **LinkedIn Job Scraper**: Playwright-based search and details extractor. Supports cookie injection (`li_at`) to bypass login blocks.
2. **Flexible Job Input**: Direct link paste or manual text input is available to tailer custom jobs instantly.
3. **Advanced AI Optimization**: Rewrites bullet points to match keywords from job descriptions.
4. **Multiple LLMs**: Supports Google Gemini API (via new SDK) or local Ollama instances (e.g. Llama 3 / Mistral) for privacy and cost-free execution.
5. **High-quality Document Output**: Compiles structural resume elements into beautiful, clean, single-column ATS-friendly documents in both PDF and Word (.docx).

---

## Installation & Setup

### 1. Prerequisites
- Python 3.8 or higher.
- (Optional) [Ollama](https://ollama.com/) if you intend to run models locally.

### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 3. Install Playwright Browsers (Required for Scraping)
```bash
playwright install chromium
```

### 4. Configure Environment Variables
Create a file named `.env` in the root folder (or copy from the `.env` template):
```env
GEMINI_API_KEY=your_google_gemini_api_key
```

---

## How to Run

### Run the Streamlit Dashboard
```bash
streamlit run src/ui.py
```

Open `http://localhost:8501` in your browser.

---

## Step-by-Step Usage Guide

1. **Set Up Keys**: In the left sidebar of the UI, choose your LLM Provider (Gemini or Ollama). Enter your Gemini API key if using Gemini.
2. **Set Up LinkedIn Sessions (Optional)**: To perform search queries reliably, log into LinkedIn in your normal browser, open Developer Tools -> Application -> Cookies -> `www.linkedin.com` -> copy the value of the `li_at` cookie. Paste this cookie value in the sidebar to bypass login walls.
3. **Upload Resume**: Go to **Tab 1: Upload CV** and upload your current CV (PDF or DOCX format).
4. **Find a Job**: Go to **Tab 2: Browse LinkedIn**, enter your target job keywords and location, and search. Click **"Tailor CV for Job..."** under any listing.
   * *Alternatively*, go to **Tab 3: Direct Link / Manual Job** and paste a direct job URL or copy-paste job details manually.
5. **Tailor CV**: Go to **Tab 4: Tailored CV Output**, review the job details, and click **"Tailor My CV for This Role"**.
6. **Download Results**: View the section-by-section comparison of changes, then download your optimized CV as a Word Document (.docx) or ATS-friendly PDF.

---

## Development & Verification

### Running Automated Tests
The project contains unit tests for document readers and writers. Run:
```bash
pytest
```
