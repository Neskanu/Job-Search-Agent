import os
import json
import re
from typing import Dict, Any, Optional
import httpx

# Gemini imports
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

SYSTEM_PROMPT = """
You are an expert ATS (Applicant Tracking System) optimization assistant and resume writer. 
Your task is to tailor the User's original CV (Resume) to match a specific Job Description.

Guidelines for optimization:
1. Identify key skills, tools, methodologies, and exact keywords in the Job Description.
2. Align the CV's skills section, summary, and experience bullet points to emphasize these keywords.
3. Make sure the CV is highly readable for humans, using action verbs and quantifiable results where possible.
4. Keep the CV completely truthful: do NOT invent new jobs, degrees, certifications, or projects. You should rephrase, re-order, and highlight existing experience to match the description.
5. Apply a standard ATS-friendly structure.

You must output your response in valid JSON format matching the schema below:

{
  "name": "string (the user's name from original CV)",
  "contact_info": "string or array of strings (e.g. Email, Phone, LinkedIn, Location, Portfolio)",
  "sections": [
    {
      "title": "string (e.g. 'Summary', 'Technical Skills', 'Professional Experience', 'Education')",
      "type": "string (must be exactly one of: 'text', 'list', 'experience', 'education')",
      "content": "depends on type:
                  - if type is 'text': a string paragraph (e.g., summary)
                  - if type is 'list': array of strings (e.g., list of skills)
                  - if type is 'experience': array of job objects:
                    {
                      "role": "string (job title)",
                      "company": "string (company name)",
                      "period": "string (dates)",
                      "location": "string (optional)",
                      "bullets": ["array", "of", "action-oriented", "resume", "bullets"]
                    }
                  - if type is 'education': array of education objects:
                    {
                      "degree": "string (degree/major)",
                      "institution": "string (school/university)",
                      "period": "string (dates)",
                      "location": "string (optional)",
                      "bullets": ["optional", "bullets"]
                    }"
    }
  ]
}

DO NOT include any explanation, intro text, or markdown formatting outside of the JSON block. Return ONLY the JSON object.
"""

def build_user_prompt(original_cv_text: str, job_description_text: str, job_title: str, company: str, additional_info: Optional[str] = None) -> str:
    """Generate the user prompt combining CV, Job Description details, and optional user instructions."""
    info_section = ""
    if additional_info and additional_info.strip():
        info_section = f"\n--- ADDITIONAL USER GUIDELINES & CONTEXT ---\n{additional_info.strip()}\n"
        
    return f"""
Job Title to target: {job_title}
Company: {company}
{info_section}
--- JOB DESCRIPTION ---
{job_description_text}

--- ORIGINAL CV TEXT ---
{original_cv_text}

--- INSTRUCTIONS ---
Using the original CV, rewrite it to optimize for the job description. Extract all section titles and content, restructure them, write tailored experience bullet points matching keywords from the job description, and output the result in the exact JSON schema requested. Make sure to adhere to any provided ADDITIONAL USER GUIDELINES & CONTEXT.
"""

def parse_llm_json(response_text: str) -> Dict[str, Any]:
    """Parse JSON output from the LLM, cleaning markdown wraps if present."""
    clean_text = response_text.strip()
    
    # Strip markdown block wraps ```json ... ``` if the LLM included them
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]
        
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
        
    clean_text = clean_text.strip()
    
    try:
        return json.loads(clean_text)
    except json.JSONDecodeError as e:
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as nested_err:
                print(f"[tailorer] Failed to parse regex-extracted JSON block: {nested_err}")
                pass
        raise ValueError(f"Failed to parse LLM response as JSON. Raw response: {response_text}\nError: {e}")

# FastAPI / Async Concept: We mark these functions as 'async def' because querying an 
# external LLM API is a network-bound task. By using 'await' during the network call, 
# the server thread can suspend this function and handle other operations until the API responds.
async def tailor_cv_gemini(
    original_cv_text: str, 
    job_description_text: str, 
    job_title: str, 
    company: str, 
    api_key: str, 
    model_name: str = "gemini-2.5-flash",
    additional_info: Optional[str] = None
) -> Dict[str, Any]:
    """
    Asynchronously use Google Gemini API to tailor the CV.
    Uses Gemini's asynchronous client ('client.aio') to avoid blocking.
    """
    if not GEMINI_AVAILABLE:
        raise ImportError("google-genai package is not installed.")
        
    client = genai.Client(api_key=api_key)
    user_prompt = build_user_prompt(original_cv_text, job_description_text, job_title, company, additional_info)
    
    try:
        # We call client.aio instead of client.models to utilize the async client
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=[SYSTEM_PROMPT, user_prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        return parse_llm_json(response.text)
    except Exception as e:
        raise RuntimeError(f"Gemini API Error: {str(e)}")

async def tailor_cv_ollama(
    original_cv_text: str, 
    job_description_text: str, 
    job_title: str, 
    company: str, 
    api_url: str = "http://localhost:11434", 
    model_name: str = "llama3",
    additional_info: Optional[str] = None
) -> Dict[str, Any]:
    """
    Asynchronously use local Ollama instance to tailor the CV.
    Uses httpx.AsyncClient for non-blocking HTTP requests.
    """
    user_prompt = build_user_prompt(original_cv_text, job_description_text, job_title, company, additional_info)
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "options": {"temperature": 0.2},
        "stream": False,
        "format": "json"
    }
    
    try:
        # We use httpx.AsyncClient() as an async context manager for non-blocking post requests
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{api_url}/api/chat", json=payload, timeout=120.0)
            res.raise_for_status()
            data = res.json()
            content = data["message"]["content"]
            return parse_llm_json(content)
    except Exception as e:
        raise RuntimeError(f"Ollama Error (Make sure Ollama is running and model '{model_name}' is pulled): {str(e)}")

async def tailor_cv(
    original_cv_text: str,
    job_description_text: str,
    job_title: str,
    company: str,
    provider: str,
    config: Dict[str, Any],
    additional_info: Optional[str] = None
) -> Dict[str, Any]:
    """
    Async wrapper function to direct to either Gemini or Ollama based on user choice.
    """
    if provider == "gemini":
        api_key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set. Please configure it in your settings or dashboard.")
        model = config.get("gemini_model", "gemini-2.5-flash")
        # Await the async gemini handler
        return await tailor_cv_gemini(original_cv_text, job_description_text, job_title, company, api_key, model, additional_info)
    elif provider == "ollama":
        api_url = config.get("ollama_url", "http://localhost:11434")
        model = config.get("ollama_model", "llama3")
        # Await the async ollama handler
        return await tailor_cv_ollama(original_cv_text, job_description_text, job_title, company, api_url, model, additional_info)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


async def generate_cover_letter(
    cv_data: Dict[str, Any],
    job_description: str,
    job_title: str,
    company: str,
    provider: str,
    config: Dict[str, Any]
) -> str:
    """
    Generate a concise, professional cover letter using the LLM.

    Produces 3 paragraphs (max ~400 words, plain text, no formatting):
      1. Why I'm excited about this specific role at the company
      2. My most relevant experience that directly matches the job requirements
      3. Closing / call to action

    Args:
        cv_data: Structured CV JSON (name, contact_info, sections...)
        job_description: Full text of the job posting
        job_title: Target job title
        company: Target company name
        provider: LLM provider name ("gemini" or "ollama")
        config: Provider config dict (api_key, model name, etc.)

    Returns:
        Cover letter as a plain text string.
    """
    # Build a short CV summary for the prompt (name + summary section)
    name = cv_data.get("name", "Candidate")
    summary_text = ""
    for sec in cv_data.get("sections", []):
        if sec.get("type") == "text" and "summary" in sec.get("title", "").lower():
            summary_text = str(sec.get("content", ""))
            break

    prompt = f"""You are a professional cover letter writer. Write a compelling, concise cover letter for the following application.

Candidate name: {name}
Target role: {job_title}
Target company: {company}

Candidate summary:
{summary_text}

Job description:
{job_description[:2000]}

INSTRUCTIONS:
- Write exactly 3 paragraphs. No bullet points. Plain text only, no markdown.
- Paragraph 1 (2-3 sentences): Express genuine enthusiasm for THIS specific role at {company}. Mention something specific from the job description.
- Paragraph 2 (3-4 sentences): Highlight 2-3 concrete achievements from the candidate's background that directly match the job requirements. Be specific.
- Paragraph 3 (2 sentences): Professional closing. Express interest in an interview.
- Start with "Dear Hiring Team," and end with "Best regards,\\n{name}".
- Maximum 380 words. Do NOT include any subject line, date, or address headers.
"""

    if provider == "gemini":
        if not GEMINI_AVAILABLE:
            return f"Dear Hiring Team,\n\nI am excited to apply for the {job_title} position at {company}.\n\nBest regards,\n{name}"
        api_key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
        model_name = config.get("gemini_model", "gemini-2.5-flash")
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.7, max_output_tokens=600)
        )
        return response.text.strip()

    elif provider == "ollama":
        api_url = config.get("ollama_url", "http://localhost:11434")
        model_name = config.get("ollama_model", "llama3")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{api_url}/api/generate",
                json={"model": model_name, "prompt": prompt, "stream": False}
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()

    return f"Dear Hiring Team,\n\nI am excited to apply for the {job_title} position at {company}.\n\nBest regards,\n{name}"

