import os
import json
import re
from typing import Dict, Any, Optional
import requests

# Gemini import
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Ollama import
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

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
        # Fallback regex search to find the first '{' and last '}'
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Failed to parse LLM response as JSON. Raw response: {response_text}\nError: {e}")

def tailor_cv_gemini(
    original_cv_text: str, 
    job_description_text: str, 
    job_title: str, 
    company: str, 
    api_key: str, 
    model_name: str = "gemini-2.5-flash",
    additional_info: Optional[str] = None
) -> Dict[str, Any]:
    """Use Google Gemini API to tailor the CV."""
    if not GEMINI_AVAILABLE:
        raise ImportError("google-genai package is not installed.")
        
    client = genai.Client(api_key=api_key)
    
    user_prompt = build_user_prompt(original_cv_text, job_description_text, job_title, company, additional_info)
    
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[SYSTEM_PROMPT, user_prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        return parse_llm_json(response.text)
    except Exception as e:
        raise RuntimeError(f"Gemini API Error: {str(e)}")

def tailor_cv_ollama(
    original_cv_text: str, 
    job_description_text: str, 
    job_title: str, 
    company: str, 
    api_url: str = "http://localhost:11434", 
    model_name: str = "llama3",
    additional_info: Optional[str] = None
) -> Dict[str, Any]:
    """Use local Ollama instance to tailor the CV."""
    user_prompt = build_user_prompt(original_cv_text, job_description_text, job_title, company, additional_info)
    
    if OLLAMA_AVAILABLE:
        try:
            client = ollama.Client(host=api_url)
            # Ollama chat mode
            response = client.chat(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                options={"temperature": 0.2},
                format="json"
            )
            content = response['message']['content']
            return parse_llm_json(content)
        except Exception as e:
            # Fall back to raw API requests in case of SDK issues
            pass
            
    # Direct HTTP requests fallback
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
        res = requests.post(f"{api_url}/api/chat", json=payload, timeout=120)
        res.raise_for_status()
        data = res.json()
        content = data["message"]["content"]
        return parse_llm_json(content)
    except Exception as e:
        raise RuntimeError(f"Ollama Error (Make sure Ollama is running and model '{model_name}' is pulled): {str(e)}")

def tailor_cv(
    original_cv_text: str,
    job_description_text: str,
    job_title: str,
    company: str,
    provider: str,
    config: Dict[str, Any],
    additional_info: Optional[str] = None
) -> Dict[str, Any]:
    """Wrapper function to direct to either Gemini or Ollama based on user choice."""
    if provider == "gemini":
        api_key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set. Please provide it in your settings, UI, or environment.")
        model = config.get("gemini_model", "gemini-2.5-flash")
        return tailor_cv_gemini(original_cv_text, job_description_text, job_title, company, api_key, model, additional_info)
    elif provider == "ollama":
        api_url = config.get("ollama_url", "http://localhost:11434")
        model = config.get("ollama_model", "llama3")
        return tailor_cv_ollama(original_cv_text, job_description_text, job_title, company, api_url, model, additional_info)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
