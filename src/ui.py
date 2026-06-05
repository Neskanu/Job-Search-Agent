import os
import sys
import yaml
from dotenv import load_dotenv
import streamlit as st

# Load environment variables
load_dotenv()

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import read_cv
from src.scraper import scrape_job_details, search_linkedin_jobs
from src.agent import run_cv_tailoring_pipeline
from src.wysiwyg import cv_wysiwyg

# Page Configuration
st.set_page_config(
    page_title="CV Tailor AI - ATS Optimization Agent",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Premium Design & Micro-animations
custom_css = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');

/* Apply font to elements */
html, body, [class*="css"], .stMarkdown, p, div {
    font-family: 'Outfit', sans-serif;
}

/* Gradient Title */
.main-title {
    background: linear-gradient(135deg, #8A2387 0%, #E94057 50%, #F27121 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-size: 2.8rem;
    font-weight: 700;
    margin-bottom: 0.1rem;
    padding-bottom: 0.5rem;
}

.subtitle {
    color: #4A4A4A;
    font-size: 1.15rem;
    font-weight: 400;
    margin-bottom: 2rem;
}

/* Glassmorphism Cards for Jobs */
.job-card {
    background: rgba(255, 255, 255, 0.7);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(220, 220, 220, 0.5);
    border-radius: 14px;
    padding: 1.5rem;
    margin-bottom: 1.2rem;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03);
    transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
}

.job-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 25px rgba(0, 0, 0, 0.08);
    border-color: #E94057;
}

.job-title {
    font-size: 1.3rem;
    font-weight: 600;
    color: #1E1E1E;
    margin-bottom: 0.3rem;
}

.job-company {
    font-size: 1.05rem;
    font-weight: 500;
    color: #E94057;
    margin-bottom: 0.5rem;
}

.job-meta {
    font-size: 0.9rem;
    color: #7A7A7A;
    margin-bottom: 1rem;
    display: flex;
    gap: 15px;
}

/* Custom styled buttons */
div.stButton > button {
    background: linear-gradient(135deg, #8A2387 0%, #E94057 100%);
    color: white !important;
    border: none !important;
    padding: 0.6rem 1.6rem !important;
    border-radius: 25px !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
    box-shadow: 0 4px 15px rgba(233, 64, 87, 0.25) !important;
    transition: all 0.25s ease !important;
}

div.stButton > button:hover {
    transform: scale(1.03) !important;
    box-shadow: 0 8px 20px rgba(233, 64, 87, 0.4) !important;
    color: white !important;
}

div.stButton > button:active {
    transform: scale(0.98) !important;
}

/* Download buttons styling override */
div[data-testid="stDownloadButton"] > button {
    background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%) !important;
    color: white !important;
    border: none !important;
    padding: 0.6rem 1.6rem !important;
    border-radius: 25px !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
    box-shadow: 0 4px 15px rgba(56, 239, 125, 0.25) !important;
    transition: all 0.25s ease !important;
}

div[data-testid="stDownloadButton"] > button:hover {
    transform: scale(1.03) !important;
    box-shadow: 0 8px 20px rgba(56, 239, 125, 0.4) !important;
    color: white !important;
}

/* Sidebar styling */
[data-testid="stSidebar"] {
    background-color: #1E293B !important;
    border-right: 1px solid #334155;
}
[data-testid="stSidebar"] .stMarkdown, 
[data-testid="stSidebar"] p, 
[data-testid="stSidebar"] span, 
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #F1F5F9 !important;
}
/* Ensure inputs in sidebar have correct text color and styling */
[data-testid="stSidebar"] input {
    color: #F1F5F9 !important;
    background-color: #0F172A !important;
    border-color: #475569 !important;
}


/* Section styling */
.section-header {
    font-size: 1.5rem;
    font-weight: 600;
    color: #2E2E3A;
    border-bottom: 2px solid #F1F1F4;
    padding-bottom: 0.5rem;
    margin-bottom: 1.2rem;
    margin-top: 1.5rem;
}
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

# Helper function to load settings
def load_settings():
    config_path = "config/settings.yaml"
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    return {}

# Helper function to save settings
def save_settings(config):
    os.makedirs("config", exist_ok=True)
    with open("config/settings.yaml", "w") as f:
        yaml.safe_dump(config, f)

# Initialize Session States
if 'jobs_list' not in st.session_state:
    st.session_state.jobs_list = []
if 'selected_job' not in st.session_state:
    st.session_state.selected_job = None
if 'original_cv_path' not in st.session_state:
    st.session_state.original_cv_path = None
if 'tailored_cv_data' not in st.session_state:
    st.session_state.tailored_cv_data = None
if 'tailored_docx_path' not in st.session_state:
    st.session_state.tailored_docx_path = None
if 'tailored_pdf_path' not in st.session_state:
    st.session_state.tailored_pdf_path = None

settings = load_settings()

# Sidebar: Config & Keys
st.sidebar.markdown("<h2 style='color:#00000000; font-size:1.5rem;'>⚙️ Configuration</h2>", unsafe_allow_html=True)

# LLM Selection
provider = st.sidebar.selectbox(
    "LLM Provider",
    options=["gemini", "ollama"],
    index=0 if settings.get("llm", {}).get("provider") == "gemini" else 1
)

llm_config = {}
if provider == "gemini":
    gemini_key = st.sidebar.text_input(
        "Gemini API Key",
        type="password",
        value=os.environ.get("GEMINI_API_KEY", "") or settings.get("llm", {}).get("gemini", {}).get("api_key", "")
    )
    gemini_model = st.sidebar.text_input(
        "Gemini Model",
        value=settings.get("llm", {}).get("gemini", {}).get("model", "gemini-2.5-flash")
    )
    llm_config = {
        "gemini_api_key": gemini_key,
        "gemini_model": gemini_model
    }
else:
    ollama_url = st.sidebar.text_input(
        "Ollama Host URL",
        value=settings.get("llm", {}).get("ollama", {}).get("api_url", "http://localhost:11434")
    )
    ollama_model = st.sidebar.text_input(
        "Ollama Model Name",
        value=settings.get("llm", {}).get("ollama", {}).get("model", "llama3")
    )
    llm_config = {
        "ollama_url": ollama_url,
        "ollama_model": ollama_model
    }

# LinkedIn Config
st.sidebar.markdown("<h3 style='font-size:1.1rem; margin-top:1.5rem;'>🔒 LinkedIn Search Settings</h3>", unsafe_allow_html=True)
li_at_cookie = st.sidebar.text_input(
    "li_at Session Cookie (Optional)",
    type="password",
    help="Highly recommended for full results. Inspect LinkedIn -> Application Tab -> Cookies -> Copy 'li_at' value.",
    value=os.environ.get("LINKEDIN_LI_AT", "")
)

# Criteria
keywords = st.sidebar.text_input("Default Keywords", value=settings.get("search_criteria", {}).get("keywords", "Python Developer"))
location = st.sidebar.text_input("Default Location", value=settings.get("search_criteria", {}).get("location", "United States"))
limit = st.sidebar.number_input("Search Limit", min_value=1, max_value=25, value=settings.get("search_criteria", {}).get("limit", 5))

# Save settings on change
if st.sidebar.button("💾 Save Settings"):
    new_settings = {
        "search_criteria": {
            "keywords": keywords,
            "location": location,
            "limit": limit
        },
        "paths": settings.get("paths", {
            "original_cv_dir": "data/original_cv",
            "tailored_cv_dir": "data/tailored_cvs"
        }),
        "llm": {
            "provider": provider,
            "gemini": {
                "model": llm_config.get("gemini_model", "gemini-2.5-flash")
            },
            "ollama": {
                "model": llm_config.get("ollama_model", "llama3"),
                "api_url": llm_config.get("ollama_url", "http://localhost:11434")
            }
        }
    }
    save_settings(new_settings)
    st.sidebar.success("Settings saved locally!")

# Layout: Split screen for Main Workspace (Left) and CV Live Workspace (Right)
col_main, col_sidebar = st.columns([5, 3])

with col_main:
    # Header block
    st.markdown('<div class="main-title">CV Tailor AI Agent</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Search LinkedIn jobs and instantly optimize your CV to match job criteria with ATS-friendly styling.</div>', unsafe_allow_html=True)

    # Tabs
    tab_cv, tab_search, tab_manual, tab_result = st.tabs([
        "📂 1. Upload CV", 
        "🔍 2. Browse LinkedIn", 
        "✍️ 3. Direct Link / Manual Job", 
        "🚀 4. Optimization Console"
    ])

    # TAB 1: Upload Original CV
    with tab_cv:
        st.markdown('<div class="section-header">Upload your Original CV</div>', unsafe_allow_html=True)
        uploaded_file = st.file_uploader("Upload CV (PDF or DOCX)", type=["pdf", "docx"])
        
        if uploaded_file is not None:
            # Save uploaded file
            os.makedirs("data/original_cv", exist_ok=True)
            cv_path = os.path.join("data/original_cv", uploaded_file.name)
            with open(cv_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            st.session_state.original_cv_path = cv_path
            
            st.success(f"Successfully uploaded: **{uploaded_file.name}**")
            
            # Read text & display metadata
            try:
                cv_text = read_cv(cv_path)
                st.info(f"Loaded CV file. Extracted {len(cv_text)} characters of text.")
                
                with st.expander("🔍 View extracted text from your CV"):
                    st.text_area("Original CV Text", cv_text, height=300, disabled=True)
                    
                st.markdown('<div class="section-header">💡 Additional Guidance (Optional)</div>', unsafe_allow_html=True)
                additional_info = st.text_area(
                    "Provide any focus areas, course/certification updates, or specific guidelines for the AI (e.g., 'Focus heavily on my AWS experience' or 'I recently completed a FastAPI certification, add it to skills.')",
                    value=st.session_state.get("additional_info", ""),
                    help="These guidelines are sent to the AI to customize the tailoring process.",
                    height=120,
                    key="additional_info_input"
                )
                st.session_state.additional_info = additional_info
            except Exception as e:
                st.error(f"Error reading file: {str(e)}")
        else:
            st.warning("Please upload your CV to start the optimization process.")

    # TAB 2: Browse LinkedIn
    with tab_search:
        st.markdown('<div class="section-header">Find Jobs on LinkedIn</div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            search_kw = st.text_input("Keywords", value=keywords, key="search_kw")
        with col2:
            search_loc = st.text_input("Location", value=location, key="search_loc")
        with col3:
            search_limit = st.number_input("Limit", min_value=1, max_value=25, value=limit, key="search_limit")
            
        if st.button("🔎 Search LinkedIn Jobs"):
            with st.spinner("Initializing browser and searching LinkedIn... This may take a moment."):
                try:
                    jobs = search_linkedin_jobs(
                        keywords=search_kw,
                        location=search_loc,
                        limit=search_limit,
                        li_at_cookie=li_at_cookie
                    )
                    st.session_state.jobs_list = jobs
                    if not jobs:
                        st.warning("No jobs found. Try adjusting keywords/location or providing a session cookie in the sidebar.")
                except Exception as e:
                    st.error(f"Failed to search jobs: {str(e)}")
                    st.info("Tip: Playwright might need browsers installed. Try running 'playwright install chromium' in the terminal.")
                    
        if st.session_state.jobs_list:
            st.write(f"### Found {len(st.session_state.jobs_list)} jobs:")
            for idx, job in enumerate(st.session_state.jobs_list):
                st.markdown(
                    f"""
                    <div class="job-card">
                        <div class="job-title">{job['title']}</div>
                        <div class="job-company">🏢 {job['company']}</div>
                        <div class="job-meta">
                            <span>📍 {job['location']}</span>
                            <span>🔗 <a href="{job['url']}" target="_blank">View Posting on LinkedIn</a></span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                # Streamlit columns to put action buttons under each card
                b_col1, b_col2 = st.columns([1, 4])
                with b_col1:
                    if st.button(f"Tailor CV for Job #{idx+1}", key=f"tailor_job_{idx}"):
                        st.session_state.selected_job = job
                        st.success(f"Selected: **{job['title']}** at **{job['company']}**. Go to Tab 4 to tailor!")
                        # Auto switch to manual tab or let them use it

    # TAB 3: Direct Link / Manual Job Entry
    with tab_manual:
        st.markdown('<div class="section-header">Direct Job Link or Manual Entry</div>', unsafe_allow_html=True)
        
        st.write("You can paste a LinkedIn URL directly to scrape it, or enter details manually.")
        
        job_url_input = st.text_input("Paste LinkedIn Job URL", placeholder="https://www.linkedin.com/jobs/view/...")
        
        scrape_btn = st.button("🔗 Fetch Job Details from URL")
        
        st.markdown("<hr/>", unsafe_allow_html=True)
        
        manual_title = st.text_input("Job Title", value=st.session_state.selected_job['title'] if st.session_state.selected_job else "")
        manual_company = st.text_input("Company Name", value=st.session_state.selected_job['company'] if st.session_state.selected_job else "")
        manual_desc = st.text_area("Job Description", height=250, value=st.session_state.selected_job.get('description', '') if st.session_state.selected_job else "")
        
        if scrape_btn and job_url_input:
            with st.spinner("Fetching job page..."):
                scraped = scrape_job_details(job_url_input, li_at_cookie=li_at_cookie)
                if scraped["success"]:
                    st.session_state.selected_job = scraped
                    st.success("Successfully fetched job details!")
                    # Force rerun to populate inputs
                    st.rerun()
                else:
                    st.error(f"Failed to scrape: {scraped['error']}")
                    st.info("You can still fill in the details manually below.")

        if st.button("🎯 Select This Manual Job"):
            if manual_title and manual_desc:
                st.session_state.selected_job = {
                    "title": manual_title,
                    "company": manual_company if manual_company else "Target Company",
                    "description": manual_desc,
                    "url": job_url_input if job_url_input else "Direct Entry"
                }
                st.success(f"Selected: **{manual_title}**. Ready to tailor under Tab 4!")
            else:
                st.error("Please enter at least a Job Title and Job Description.")

    # TAB 4: Optimization Console
    with tab_result:
        st.markdown('<div class="section-header">Tailor CV & AI Optimization</div>', unsafe_allow_html=True)
        
        if not st.session_state.original_cv_path:
            st.warning("⚠️ No original CV uploaded. Please go to **Tab 1** and upload your CV first.")
        elif not st.session_state.selected_job:
            st.warning("⚠️ No target job selected. Please select a job from **Tab 2** or enter details in **Tab 3** first.")
        else:
            job = st.session_state.selected_job
            st.write("### Target Job Summary")
            st.markdown(f"**Title**: {job['title']} | **Company**: {job['company']}")
            
            with st.expander("View Job Description being targeted"):
                st.text(job.get('description', 'No full description text available.'))
                
            st.markdown("<hr/>", unsafe_allow_html=True)
            
            if st.button("🚀 Tailor My CV for This Role"):
                if provider == "gemini" and not gemini_key:
                    st.error("Please enter a Gemini API Key in the configuration sidebar to use Gemini.")
                else:
                    with st.spinner("AI is tailoring your resume... Injecting keywords and aligning formatting... This takes 10-30 seconds."):
                        try:
                            # Ensure we pass the description (scrape if it wasn't fetched fully during search)
                            job_description = job.get('description')
                            if not job_description or len(job_description) < 50:
                                if job.get('url') and job['url'] != "Direct Entry":
                                    with st.spinner("Scraping full job description first..."):
                                        scraped = scrape_job_details(job['url'], li_at_cookie=li_at_cookie)
                                        if scraped['success']:
                                            job['description'] = scraped['description']
                                            job_description = scraped['description']
                                        else:
                                            st.warning(f"Could not scrape description automatically: {scraped['error']}. Tailoring with search metadata.")
                                            job_description = f"Job Title: {job['title']}. Company: {job['company']}."
                                else:
                                    job_description = f"Job Title: {job['title']}. Company: {job['company']}."
                            
                            # Run the actual pipeline
                            tailored_data, docx_path, pdf_path = run_cv_tailoring_pipeline(
                                original_cv_path=st.session_state.original_cv_path,
                                job_description_text=job_description,
                                job_title=job['title'],
                                company=job['company'],
                                provider=provider,
                                llm_config=llm_config,
                                additional_info=st.session_state.get("additional_info")
                            )
                            
                            st.session_state.tailored_cv_data = tailored_data
                            st.session_state.tailored_docx_path = docx_path
                            st.session_state.tailored_pdf_path = pdf_path
                            
                            st.success("🎉 CV tailored successfully! Output generated in the right workspace.")
                        except Exception as e:
                            st.error(f"Tailoring failed: {str(e)}")

# Right Sidebar: Global Live CV Workspace
with col_sidebar:
    st.markdown("<h3 class='section-header'>📋 Live CV Workspace</h3>", unsafe_allow_html=True)
    
    if st.session_state.tailored_cv_data:
        # Download buttons
        d_col1, d_col2 = st.columns(2)
        with d_col1:
            if os.path.exists(st.session_state.tailored_docx_path):
                with open(st.session_state.tailored_docx_path, "rb") as f:
                    st.download_button(
                        label="📝 Download Word (.docx)",
                        data=f,
                        file_name=os.path.basename(st.session_state.tailored_docx_path),
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key="sb_download_docx"
                    )
        with d_col2:
            if os.path.exists(st.session_state.tailored_pdf_path):
                with open(st.session_state.tailored_pdf_path, "rb") as f:
                    st.download_button(
                        label="📄 Download ATS PDF",
                        data=f,
                        file_name=os.path.basename(st.session_state.tailored_pdf_path),
                        mime="application/pdf",
                        key="sb_download_pdf"
                    )
        
        # Render the custom WYSIWYG editor
        edited_cv = cv_wysiwyg(st.session_state.tailored_cv_data, key="cv_wysiwyg_editor_canvas")
        
        # Check if the user clicked "Save & Rebuild" (value changes)
        if edited_cv != st.session_state.tailored_cv_data:
            st.session_state.tailored_cv_data = edited_cv
            with st.spinner("Rebuilding document files..."):
                try:
                    from src.parser import save_cv_as_docx, save_cv_as_pdf
                    save_cv_as_docx(edited_cv, st.session_state.tailored_docx_path)
                    save_cv_as_pdf(edited_cv, st.session_state.tailored_pdf_path)
                    st.toast("✅ CV updated and files regenerated successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Rebuild failed: {str(e)}")
    else:
        st.info("💡 Your tailored CV preview and quick manual editor will appear here once you select a job and run the optimization engine.")

