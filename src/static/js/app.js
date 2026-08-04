/**
 * ==========================================================================
 * 📂 STATE MANAGEMENT
 * ==========================================================================
 * Global object that tracks variables throughout the user session.
 */
const cvState = {
  originalCvPath: null,
  originalCvText: null,
  selectedJob: null,
  searchResults: [],
  tailoredCvData: null,
  tailoredDocxPath: null,
  tailoredPdfPath: null,
  theme: "creative",
  layoutMode: "2col",
  lineStyle: "short",
  bulletSymbol: "│",
  customColor: "#0F766E",
  photo: null
};

// ==========================================
// 🧭 TAB NAVIGATION & DISPLAY CONTROLS
// ==========================================

/**
 * Switch active navigation tabs on the left sidebar console.
 */
function switchTab(tabId) {
  // Hide all contents and deactivate tab header lines
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('nav button').forEach(el => {
    el.classList.remove('text-rose-500', 'border-rose-500');
    el.classList.add('text-slate-400', 'border-transparent');
  });

  // Show selected content and activate tab header line
  document.getElementById(`tab-${tabId}`).classList.remove('hidden');
  const activeBtn = document.getElementById(`btn-tab-${tabId}`);
  activeBtn.classList.remove('text-slate-400', 'border-transparent');
  activeBtn.classList.add('text-rose-500', 'border-rose-500');
}

/**
 * Toggle LLM configuration input blocks based on provider select value.
 */
function toggleLLMInputs() {
  const provider = document.getElementById("llm-provider")?.value || "gemini";
  if (provider === "gemini") {
    document.getElementById("gemini-inputs")?.classList.remove("hidden");
    document.getElementById("ollama-inputs")?.classList.add("hidden");
    showToast("Selected Provider: Google Gemini API");
  } else {
    document.getElementById("gemini-inputs")?.classList.add("hidden");
    document.getElementById("ollama-inputs")?.classList.remove("hidden");
    showToast("Selected Provider: Ollama (Local LLM)");
  }
}

// ==========================================
// 🔔 UTILITY TOAST NOTIFICATIONS
// ==========================================

function showToast(message, isError = false) {
  const toast = document.getElementById("toast-banner");
  const icon = document.getElementById("toast-icon");
  const text = document.getElementById("toast-text");

  icon.innerText = isError ? "❌" : "✅";
  text.innerText = message;
  
  toast.classList.remove("hidden", "translate-y-10");
  toast.classList.add("flex");

  setTimeout(() => {
    toast.classList.add("translate-y-10");
    setTimeout(() => {
      toast.classList.remove("flex");
      toast.classList.add("hidden");
    }, 300);
  }, 3000);
}

// ==========================================
// 🚀 API HANDLERS (Asynchronous Communication)
// ==========================================

/**
 * Upload CV file (PDF or DOCX) to the backend API.
 * FastAPI concept: We send a standard 'multipart/form-data' request containing the file.
 */
async function uploadCVFile() {
  const fileInput = document.getElementById("cv-file");
  if (fileInput.files.length === 0) return;

  const file = fileInput.files[0];
  const formData = new FormData();
  formData.append("file", file);

  const statusText = document.getElementById("upload-status-text");
  statusText.innerText = "Parsing CV...";

  try {
    // We send a POST request to FastAPI upload endpoint
    const response = await fetch("/api/upload-cv", {
      method: "POST",
      body: formData
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Upload failed.");

    // Update global state
    cvState.originalCvPath = data.file_path;
    cvState.originalCvText = data.text;

    // Display loaded details
    document.getElementById("loaded-filename").innerText = data.filename;
    document.getElementById("loaded-chars-count").innerText = data.text.length;
    document.getElementById("cv-details-panel").classList.remove("hidden");
    
    // Open CV in WYSIWYG canvas immediately on upload!
    if (data.cv_data) {
      cvState.tailoredCvData = data.cv_data;
      renderWYSIWYG(data.cv_data);
      document.getElementById("download-actions-bar").classList.remove("hidden");
      document.getElementById("resume-sheet").classList.remove("hidden");
      document.getElementById("cv-empty-placeholder").classList.add("hidden");
      setViewMode("split");
    }
    if (data.pdf_path) {
      cvState.tailoredPdfPath = data.pdf_path;
      refreshPDFPreview();
    }

    statusText.innerText = "Upload CV (PDF/DOCX)";
    showToast("CV uploaded and opened in canvas!");
    alert(`📂 CV Uploaded Successfully!\n\nFile: ${data.filename}\nCharacters Parsed: ${data.text.length}\n\nYour CV is now loaded in the interactive WYSIWYG canvas.`);
    checkTailorEnable();
    saveAppStateToCache();
    loadSavedCVList();
  } catch (err) {
    statusText.innerText = "Upload CV (PDF/DOCX)";
    alert(`Upload Error: ${err.message}`);
  }
}

/**
 * Render Easy Apply visual badge indicator.
 */
function renderEasyApplyBadge(isEasyApply) {
  if (isEasyApply === true) {
    return `<span class="inline-flex items-center gap-1 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] px-2 py-0.5 rounded-full font-semibold"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>⚡ Easy Apply</span>`;
  } else if (isEasyApply === false) {
    return `<span class="inline-flex items-center gap-1 bg-slate-800/80 text-slate-400 border border-slate-700/60 text-[10px] px-2 py-0.5 rounded-full font-medium">🔗 External Apply</span>`;
  }
  return '';
}

/**
 * Update the Easy Apply badge in the target selection banner.
 */
function updateBannerEasyApplyBadge(isEasyApply) {
  const badgeEl = document.getElementById("banner-easy-apply-badge");
  if (!badgeEl) return;
  if (isEasyApply === true) {
    badgeEl.className = "text-[10px] px-2 py-0.5 rounded-full font-semibold border bg-emerald-500/10 text-emerald-400 border-emerald-500/20 inline-flex items-center gap-1";
    badgeEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>⚡ Easy Apply`;
    badgeEl.classList.remove("hidden");
  } else if (isEasyApply === false) {
    badgeEl.className = "text-[10px] px-2 py-0.5 rounded-full font-medium border bg-slate-800/80 text-slate-400 border-slate-700/60 inline-flex items-center gap-1";
    badgeEl.innerHTML = `🔗 External Apply`;
    badgeEl.classList.remove("hidden");
  } else {
    badgeEl.classList.add("hidden");
  }
}

/**
 * Search jobs on LinkedIn via Playwright scraper API.
 */
async function searchJobs() {
  const keywords = document.getElementById("search-keywords")?.value || "Python Developer";
  const location = document.getElementById("search-location")?.value || "United States";
  const limit = parseInt(document.getElementById("search-limit")?.value || "5");
  const cookie = document.getElementById("li-at-cookie")?.value || "";

  const resultsDiv = document.getElementById("job-search-results");
  resultsDiv.innerHTML = `<div class="text-center py-4 text-xs text-slate-400">🔎 Launching browser & searching LinkedIn...</div>`;

  try {
    const response = await fetch("/api/search-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        keywords: keywords,
        location: location,
        limit: limit,
        li_at_cookie: cookie || null
      })
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Search failed.");

    resultsDiv.innerHTML = "";
    if (data.jobs.length === 0) {
      resultsDiv.innerHTML = `<div class="text-xs text-slate-500 py-3">No jobs found. Try adjusting keywords or injecting a session cookie.</div>`;
      return;
    }

    cvState.searchResults = data.jobs;
    // Render job cards list
    data.jobs.forEach((job, idx) => {
      const isSelected = cvState.selectedJob && cvState.selectedJob.title === job.title && cvState.selectedJob.company === job.company;
      const card = document.createElement("div");
      card.className = "bg-[#0F172A] border border-[#334155] rounded-xl p-4 space-y-2 relative";
      const isQueued = cvState.applyQueue && cvState.applyQueue.some(q => q.job_url === job.url);
      const eaBadge = renderEasyApplyBadge(job.easy_apply);
      card.innerHTML = `
        <div class="flex items-start justify-between gap-2">
          <div class="text-xs font-bold text-slate-100">${job.title}</div>
          ${eaBadge}
        </div>
        <div class="text-[11px] text-rose-400 font-medium">🏢 ${job.company}</div>
        <div class="text-[10px] text-slate-500">📍 ${job.location}</div>
        <div class="flex justify-between items-center mt-2 border-t border-[#1E293B] pt-2">
          <a href="${job.url}" target="_blank" class="text-[10px] text-slate-400 hover:underline">View Post 🔗</a>
          <div class="flex gap-1.5 items-center">
            ${!job.easy_apply || (job.url && !job.url.includes('linkedin.com')) ? `
              <button onclick="triggerGuidedApplyForJob(${idx})" class="bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-[10px] px-2.5 py-1 rounded transition-all cursor-pointer">
                🌐 Guided Apply
              </button>
            ` : ''}
            <button onclick="toggleJobQueue(${idx})" id="queue-btn-${idx}" class="text-[10px] px-2.5 py-1 rounded transition-all font-semibold ${isQueued ? 'bg-violet-600 text-white' : 'bg-slate-700 hover:bg-violet-700 text-slate-300'}">
              ${isQueued ? '✓ Queued' : '+ Queue'}
            </button>
            <button onclick="selectJobByIndex(${idx})" class="job-card-select-btn ${isSelected ? 'bg-emerald-600 text-white font-bold shadow-sm' : 'bg-rose-600 hover:bg-rose-700 text-white font-bold'} text-[10px] px-3 py-1 rounded cursor-pointer transition-all">
              ${isSelected ? '✔ Selected' : 'Select Job'}
            </button>
          </div>
        </div>
      `;
      resultsDiv.appendChild(card);
    });

  } catch (err) {
    resultsDiv.innerHTML = `<div class="text-xs text-red-400 py-3">Error: ${err.message}</div>`;
  }
}

/**
 * Scrape a specific LinkedIn job posting by pasting the URL directly.
 */
async function scrapeDirectJob() {
  const url = document.getElementById("direct-job-url")?.value || "";
  const cookie = document.getElementById("li-at-cookie")?.value || "";
  if (!url) {
    alert("Please paste a LinkedIn job URL first.");
    return;
  }

  showToast("Launching scraper, fetching job description...");

  try {
    const response = await fetch("/api/scrape-job", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url, li_at_cookie: cookie || null })
    });

    const data = await response.json();
    if (!data.success) throw new Error(data.error || "Scraping failed.");

    // Fill the manual entry inputs with scraped data
    document.getElementById("job-title").value = data.title;
    document.getElementById("job-company").value = data.company;
    document.getElementById("job-desc").value = data.description;
    
    // Automatically select job with easy_apply metadata
    selectJob({
      title: data.title,
      company: data.company,
      description: data.description,
      url: url,
      easy_apply: data.easy_apply
    });

    showToast("Job details fetched successfully!");
  } catch (err) {
    alert(`Fetch Error: ${err.message}`);
  }
}

/**
 * Select the job filled in manual form fields as target.
 */
function selectManualJob() {
  const title = document.getElementById("job-title")?.value || "";
  const company = document.getElementById("job-company")?.value || "";
  const desc = document.getElementById("job-desc")?.value || "";
  const url = document.getElementById("direct-job-url")?.value || "Direct Entry";

  if (!title || !desc) {
    alert("Please enter at least a Job Title and Job Description.");
    return;
  }

  const job = {
    title: title,
    company: company || "Target Company",
    description: desc,
    url: url
  };

  selectJob(job);
}

function selectJobByIndex(idx) {
  if (cvState.searchResults && cvState.searchResults[idx]) {
    // Update card button styles visually across all cards
    document.querySelectorAll(".job-card-select-btn").forEach((btn, bIdx) => {
      if (bIdx === idx) {
        btn.innerText = "✔ Selected";
        btn.className = "job-card-select-btn bg-emerald-600 text-white font-bold text-[10px] px-3 py-1 rounded cursor-pointer shadow-sm transition-all";
      } else {
        btn.innerText = "Select Job";
        btn.className = "job-card-select-btn bg-rose-600 hover:bg-rose-700 text-white font-bold text-[10px] px-3 py-1 rounded cursor-pointer transition-all";
      }
    });

    selectJob(cvState.searchResults[idx]);
  }
}

/**
 * Select target job and update console selection state.
 */
async function selectJob(job) {
  cvState.selectedJob = job;
  
  document.getElementById("banner-job-title").innerText = job.title;
  document.getElementById("banner-job-company").innerText = job.company;
  updateBannerEasyApplyBadge(job.easy_apply);
  document.getElementById("target-selection-banner").classList.remove("hidden");
  
  // Fill out the manual section form fields
  if (document.getElementById("job-title")) document.getElementById("job-title").value = job.title || "";
  if (document.getElementById("job-company")) document.getElementById("job-company").value = job.company || "";
  if (document.getElementById("direct-job-url")) document.getElementById("direct-job-url").value = job.url || "";
  if (document.getElementById("job-desc")) {
    document.getElementById("job-desc").value = job.description || (job.url ? "Fetching full job description..." : "");
  }

  showToast(`Selected Target: ${job.title} at ${job.company}`);
  checkTailorEnable();
  saveAppStateToCache();

  // Automatically fetch full job description if missing
  if (!job.description && job.url && job.url.startsWith("http")) {
    const cookie = document.getElementById("li-at-cookie")?.value;
    showToast(`Fetching description for ${job.title}...`);
    try {
      const response = await fetch("/api/scrape-job", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: job.url, li_at_cookie: cookie || null })
      });
      const data = await response.json();
      if (data.success && data.description) {
        cvState.selectedJob.description = data.description;
        if (data.title) cvState.selectedJob.title = data.title;
        if (data.company) cvState.selectedJob.company = data.company;
        if (data.easy_apply !== undefined) {
          cvState.selectedJob.easy_apply = data.easy_apply;
          updateBannerEasyApplyBadge(data.easy_apply);
        }
        
        // Update manual form fields with the scraped details
        if (document.getElementById("job-title")) document.getElementById("job-title").value = cvState.selectedJob.title;
        if (document.getElementById("job-company")) document.getElementById("job-company").value = cvState.selectedJob.company;
        if (document.getElementById("job-desc")) document.getElementById("job-desc").value = data.description;
        
        saveAppStateToCache();
        showToast(`Job details loaded! Ready to optimize.`);
      }
    } catch (err) {
      console.warn("Auto job scrape failed:", err);
      if (document.getElementById("job-desc") && document.getElementById("job-desc").value === "Fetching full job description...") {
        document.getElementById("job-desc").value = `Job Title: ${job.title}\nCompany: ${job.company}`;
      }
    }
  }
}

/**
 * Print real-time diagnostic log message to console and UI Debug Status Panel.
 */
function logDebug(msg, isError = false) {
  console.log(`[CV AGENT DEBUG] ${msg}`);
  const panel = document.getElementById("debug-log-panel");
  const content = document.getElementById("debug-log-content");
  if (!panel || !content) return;
  
  panel.classList.remove("hidden");
  const line = document.createElement("div");
  const timestamp = new Date().toLocaleTimeString();
  line.className = isError ? "text-rose-400 font-semibold" : "text-emerald-400";
  line.innerText = `[${timestamp}] ${msg}`;
  content.appendChild(line);
  panel.scrollTop = panel.scrollHeight;
}

/**
 * Fetch list of saved original & tailored CV files from backend and populate dropdowns.
 */
/**
 * Fetch list of saved original & tailored CV files from backend and populate dropdowns.
 */
async function loadSavedCVList() {
  logDebug("Refreshing saved CV library from server...");
  try {
    const response = await fetch("/api/list-cvs");
    const data = await response.json();
    if (!data.success) return;

    const origSelect = document.getElementById("select-saved-original-cv");
    const tailoredSelect = document.getElementById("select-saved-tailored-cv");

    if (origSelect) {
      origSelect.innerHTML = `<option value="">-- Choose Original CV (${data.original_cvs.length} available) --</option>`;
      if (data.original_cvs.length === 0) {
        origSelect.innerHTML += `<option value="" disabled>(No original CVs found in data/original_cv)</option>`;
      }
      data.original_cvs.forEach(file => {
        const opt = document.createElement("option");
        opt.value = file.path;
        opt.innerText = file.name;
        if (cvState.originalCvPath === file.path) opt.selected = true;
        origSelect.appendChild(opt);
      });
    }

    if (tailoredSelect) {
      tailoredSelect.innerHTML = `<option value="">-- Choose Tailored CV (${data.tailored_cvs.length} available) --</option>`;
      if (data.tailored_cvs.length === 0) {
        tailoredSelect.innerHTML += `<option value="" disabled>(No tailored CVs found in data/tailored_cvs)</option>`;
      }
      data.tailored_cvs.forEach(file => {
        const opt = document.createElement("option");
        opt.value = file.path;
        opt.innerText = file.name;
        if (cvState.tailoredPdfPath === file.path) opt.selected = true;
        tailoredSelect.appendChild(opt);
      });
    }
    logDebug(`✓ Saved CV Library updated: ${data.original_cvs.length} original CVs, ${data.tailored_cvs.length} tailored CVs.`);
  } catch (err) {
    console.warn("Failed to load saved CV list:", err);
  }
}

/**
 * Load a chosen saved CV from disk and immediately display in canvas workspace.
 */
async function loadSelectedSavedCV(type) {
  const selectId = type === "original" ? "select-saved-original-cv" : "select-saved-tailored-cv";
  const path = document.getElementById(selectId)?.value;
  if (!path) return;

  logDebug(`Loading selected ${type} CV: ${path}`);
  showToast("Loading CV into canvas...");

  try {
    const response = await fetch("/api/load-cv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: path })
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Failed to load CV.");

    cvState.originalCvPath = data.file_path;
    cvState.originalCvText = data.text;
    cvState.tailoredCvData = data.cv_data;
    if (data.pdf_path) cvState.tailoredPdfPath = data.pdf_path;

    // Display loaded details
    document.getElementById("loaded-filename").innerText = data.filename;
    document.getElementById("loaded-chars-count").innerText = data.text.length;
    document.getElementById("cv-details-panel").classList.remove("hidden");

    renderWYSIWYG(data.cv_data);
    document.getElementById("download-actions-bar").classList.remove("hidden");
    document.getElementById("resume-sheet").classList.remove("hidden");
    document.getElementById("cv-empty-placeholder").classList.add("hidden");
    setViewMode("split");

    refreshPDFPreview();
    checkTailorEnable();
    saveAppStateToCache();
    showToast(`Loaded ${data.filename} into canvas!`);
    alert(`📂 Loaded Saved CV into Canvas!\n\nFile: ${data.filename}\nCharacters Parsed: ${data.text.length}`);
  } catch (err) {
    alert(`Load Error: ${err.message}`);
  }
}

/**
 * Display full-screen optimization overlay with step text & progress bar.
 */
function showOptimizingOverlay(stepText, progressPct = 35) {
  const overlay = document.getElementById("optimizing-overlay");
  const stepEl = document.getElementById("optimizing-overlay-step");
  const barEl = document.getElementById("optimizing-progress-bar");
  if (!overlay) return;
  
  overlay.classList.remove("hidden");
  if (stepEl) stepEl.innerText = stepText;
  if (barEl) barEl.style.width = `${progressPct}%`;
}

/**
 * Hide full-screen optimization overlay.
 */
function hideOptimizingOverlay() {
  const overlay = document.getElementById("optimizing-overlay");
  if (overlay) overlay.classList.add("hidden");
}

/**
 * Show validation warning modal dialog on missing requirements.
 */
function showValidationModal(title, bodyText, iconSymbol = "⚠️", actionsHtml = null) {
  const overlay = document.getElementById("validation-modal-overlay");
  const titleEl = document.getElementById("validation-modal-title");
  const bodyEl = document.getElementById("validation-modal-body");
  const iconEl = document.getElementById("validation-modal-icon");
  const actionsEl = document.getElementById("validation-modal-actions");
  if (!overlay) return;

  if (titleEl) titleEl.innerText = title;
  if (bodyEl) bodyEl.innerText = bodyText;
  if (iconEl) iconEl.innerText = iconSymbol;
  if (actionsEl && actionsHtml) actionsEl.innerHTML = actionsHtml;

  overlay.classList.remove("hidden");
}

/**
 * Close validation warning modal.
 */
function closeValidationModal() {
  const overlay = document.getElementById("validation-modal-overlay");
  if (overlay) overlay.classList.add("hidden");
}

/**
 * Display Optimization Success Summary Modal dialog detailing what was changed.
 */
function showOptimizationSummary(info) {
  const modal = document.getElementById("optimization-summary-modal");
  if (!modal) return;

  if (document.getElementById("summary-job-title")) document.getElementById("summary-job-title").innerText = info.job_title || "Target Role";
  if (document.getElementById("summary-company")) document.getElementById("summary-company").innerText = info.company || "Target Company";
  if (document.getElementById("summary-model")) document.getElementById("summary-model").innerText = info.model || "gemini-2.5-flash";

  modal.classList.remove("hidden");
}

/**
 * Close Optimization Success Summary Modal dialog.
 */
function closeSummaryModal() {
  const modal = document.getElementById("optimization-summary-modal");
  if (modal) modal.classList.add("hidden");
}

/**
 * Enable/Disable tailoring orchestrator button based on upload and target state.
 */
function checkTailorEnable() {
  const btn = document.getElementById("btn-tailor-cv");
  if (btn) {
    btn.removeAttribute("disabled");
  }
}

/**
 * Trigger CV tailoring LLM agent pipeline.
 */
async function tailorResume() {
  // GUARANTEED NOTIFICATION ON EVERY CLICK:
  showToast("🚀 Optimize Resume clicked! Checking inputs...");
  logDebug("🚀 Optimize Resume for Role button clicked.");

  // Auto-detect manually typed job in Tab 3 if selectedJob is not set
  if (!cvState.selectedJob) {
    const title = document.getElementById("job-title")?.value;
    const desc = document.getElementById("job-desc")?.value;
    const company = document.getElementById("job-company")?.value;
    const url = document.getElementById("direct-job-url")?.value || "Direct Entry";
    
    if (title || desc) {
      logDebug(`Auto-registering manual job entry: "${title || 'Target Role'}" at "${company || 'Target Company'}"`);
      cvState.selectedJob = {
        title: title || "Target Role",
        company: company || "Target Company",
        description: desc || `Job Title: ${title}`,
        url: url
      };
      document.getElementById("banner-job-title").innerText = cvState.selectedJob.title;
      document.getElementById("banner-job-company").innerText = cvState.selectedJob.company;
      document.getElementById("target-selection-banner").classList.remove("hidden");
      saveAppStateToCache();
    }
  }

  // Check 1: CV Upload Validation
  if (!cvState.originalCvPath) {
    logDebug("❌ Validation Failed: No original CV uploaded.", true);
    showToast("⚠️ Please upload your original CV first!", true);
    alert("⚠️ Missing Original CV!\n\nPlease upload a CV or select a previously saved CV from the library in Tab 1 ('📂 Upload') before optimizing.");
    showValidationModal(
      "Original CV Missing",
      "Please upload your original CV file (PDF or DOCX) in Tab 1 before optimizing.",
      "📁",
      `<button onclick="switchTab('upload'); closeValidationModal();" class="w-full py-2.5 bg-rose-600 hover:bg-rose-700 text-white font-bold text-xs rounded-lg shadow-md">📂 Go to Upload Tab</button>`
    );
    return;
  }
  logDebug(`✓ Original CV Path: ${cvState.originalCvPath}`);

  // Check 2: Target Job Validation
  if (!cvState.selectedJob) {
    logDebug("❌ Validation Failed: No target job selected or entered.", true);
    showToast("⚠️ Please select a target job post first!", true);
    alert("⚠️ Missing Target Job!\n\nPlease select a job from Tab 2 ('🔍 Search') or enter job details in Tab 3 ('✍️ Manual') before optimizing.");
    showValidationModal(
      "Target Job Missing",
      "Please select a job from Tab 2 ('Search') or enter job details in Tab 3 ('Manual').",
      "🎯",
      `<div class="flex gap-2 w-full">
        <button onclick="switchTab('linkedin'); closeValidationModal();" class="flex-1 py-2.5 bg-rose-600 hover:bg-rose-700 text-white font-bold text-xs rounded-lg shadow-md">🔍 Search Jobs</button>
        <button onclick="switchTab('manual'); closeValidationModal();" class="flex-1 py-2.5 bg-slate-700 hover:bg-slate-600 text-white font-bold text-xs rounded-lg shadow-md">✍️ Manual Entry</button>
       </div>`
    );
    return;
  }
  logDebug(`✓ Target Job: ${cvState.selectedJob.title} at ${cvState.selectedJob.company}`);

  // Check 3: LLM Provider Parameters
  const provider = document.getElementById("llm-provider")?.value || "gemini";
  const additionalInfo = document.getElementById("additional-info")?.value || "";

  let llmConfig = {};
  if (provider === "gemini") {
    const key = document.getElementById("gemini-key")?.value || "";
    const model = getSelectedModel("gemini");
    logDebug(`✓ LLM Provider: Gemini | Model: ${model}`);
    if (!key) {
      logDebug("⚠️ Warning: Gemini API key field is empty. Using server environment key fallback...", true);
    }
    llmConfig = {
      gemini_api_key: key || null,
      gemini_model: model
    };
  } else {
    const url = document.getElementById("ollama-url")?.value || "http://localhost:11434";
    const model = getSelectedModel("ollama");
    logDebug(`✓ LLM Provider: Ollama | Host: ${url} | Model: ${model}`);
    llmConfig = {
      ollama_url: url,
      ollama_model: model
    };
  }

  const btn = document.getElementById("btn-tailor-cv");
  const btnText = btn?.querySelector("span");
  if (btnText) btnText.innerText = "Tailoring Resume (10-30s)...";

  showOptimizingOverlay("Step 1/3: Reading CV & analyzing job requirements...", 25);

  // Check 4: Job Description Content
  let jobDesc = cvState.selectedJob.description;
  if (!jobDesc || jobDesc.trim().length === 0) {
    if (cvState.selectedJob.url && cvState.selectedJob.url.startsWith("http")) {
      showOptimizingOverlay("Step 1/3: Scraper fetching full job posting details...", 35);
      logDebug(`Scraper fetching job details from: ${cvState.selectedJob.url}`);
      try {
        const cookie = document.getElementById("li-at-cookie")?.value;
        const response = await fetch("/api/scrape-job", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: cvState.selectedJob.url, li_at_cookie: cookie || null })
        });
        const data = await response.json();
        if (data.success && data.description) {
          jobDesc = data.description;
          cvState.selectedJob.description = jobDesc;
          logDebug("✓ Job details scraped successfully!");
          saveAppStateToCache();
        }
      } catch (err) {
        logDebug(`Auto-scrape warning: ${err.message}`, true);
      }
    }
    
    if (!jobDesc || jobDesc.trim().length === 0) {
      jobDesc = `Job Title: ${cvState.selectedJob.title}\nCompany: ${cvState.selectedJob.company}\nLocation: ${cvState.selectedJob.location || ''}`;
    }
  }

  showOptimizingOverlay("Step 2/3: AI Agent tailoring experience & matching keywords...", 60);
  logDebug("Sending POST payload to /api/tailor-cv endpoint...");

  try {
    const response = await fetch("/api/tailor-cv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        original_cv_path: cvState.originalCvPath,
        job_description_text: jobDesc,
        job_title: cvState.selectedJob.title,
        company: cvState.selectedJob.company,
        provider: provider,
        llm_config: llmConfig,
        additional_info: additionalInfo || null
      })
    });

    const data = await response.json();
    if (!response.ok) {
      const errMsg = data.detail || JSON.stringify(data);
      logDebug(`❌ Backend API Error (${response.status}): ${errMsg}`, true);
      throw new Error(errMsg);
    }

    showOptimizingOverlay("Step 3/3: Rebuilding PDF preview & Word documents...", 90);
    logDebug("✓ Backend API returned 200 OK. Updating state & WYSIWYG elements...");

    cvState.tailoredCvData = data.cv_data;
    cvState.tailoredDocxPath = data.docx_path;
    cvState.tailoredPdfPath = data.pdf_path;

    renderWYSIWYG(data.cv_data);

    document.getElementById("download-actions-bar").classList.remove("hidden");
    document.getElementById("resume-sheet").classList.remove("hidden");
    document.getElementById("cv-empty-placeholder").classList.add("hidden");

    showToast("CV tailored successfully! PDF/Word files generated.");
    refreshPDFPreview();
    saveAppStateToCache();
    logDebug("🎉 Optimization Complete! Tailored CV rendered successfully.");

    // Display explicit Optimization Summary Modal detailing changes & downloads
    showOptimizationSummary({
      job_title: cvState.selectedJob.title,
      company: cvState.selectedJob.company,
      model: getSelectedModel(provider)
    });
  } catch (err) {
    logDebug(`❌ Pipeline Execution Error: ${err.message}`, true);
    showValidationModal(
      "Optimization Failed",
      `The AI CV Tailoring pipeline encountered an error:\n\n${err.message}\n\nPlease check your API key, model selection, or server connection and try again.`,
      "❌",
      `<button onclick="closeValidationModal()" class="w-full py-2.5 bg-rose-600 hover:bg-rose-700 text-white font-bold text-xs rounded-lg shadow-md">Dismiss & Fix Issue</button>`
    );
  } finally {
    hideOptimizingOverlay();
    if (btnText) btnText.innerText = "Optimize Resume for Role";
    checkTailorEnable();
  }
}

// ==========================================
// ✏️ WYSIWYG CANVAS RENDERING & INTERACTION
// ==========================================

/**
 * Render JSON resume structure to interactive WYSIWYG DOM elements.
 */
function renderWYSIWYG(cvData) {
  if (!cvData) return;

  const sheet = document.getElementById("resume-sheet");
  if (sheet) {
    const classesToRemove = Array.from(sheet.classList).filter(cls => cls.startsWith("theme-") || cls.startsWith("layout-") || cls.startsWith("line-style-"));
    classesToRemove.forEach(cls => sheet.classList.remove(cls));
    
    const selectedTheme = document.getElementById("cv-theme-select")?.value || cvState.theme || "creative";
    const selectedLayout = document.getElementById("cv-layout-select")?.value || cvState.layoutMode || "2col";
    const selectedLine = document.getElementById("cv-line-style-select")?.value || cvState.lineStyle || "short";
    
    sheet.classList.add(`theme-${selectedTheme}`, `layout-${selectedLayout}`, `line-style-${selectedLine}`);
    cvState.theme = selectedTheme;
    cvState.layoutMode = selectedLayout;
    cvState.lineStyle = selectedLine;
  }

  if (cvState.customColor) {
    document.documentElement.style.setProperty('--theme-accent', cvState.customColor);
  }

  const listContainer = document.getElementById("sections-list");
  listContainer.innerHTML = "";

  if (Array.isArray(cvData.sections)) {
    const is2Col = (cvState.layoutMode === "2col");
    
    let currentPageCard = document.createElement("div");
    currentPageCard.className = "a4-page-card bg-white shadow-2xl rounded-md relative";

    // 1. Header Banner Block
    const headerBanner = document.createElement("div");
    headerBanner.className = "cv-header-banner";

    const photoSrc = cvData.photo || "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 100 100'><rect width='100' height='100' fill='%230F766E'/><text x='50%' y='55%' font-family='Arial' font-size='12' fill='%23FFFFFF' text-anchor='middle'>Photo</text></svg>";
    const contactText = Array.isArray(cvData.contact_info) ? cvData.contact_info.join("  │  ") : (cvData.contact_info || "");

    headerBanner.innerHTML = `
      <div id="cv-photo-container" class="relative group/photo cursor-pointer shrink-0">
        <img id="cv-photo" src="${photoSrc}" class="cv-photo-frame" alt="Profile Photo">
        <input type="file" id="cv-photo-input" accept="image/*" class="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10" onchange="uploadCVPhoto()">
        <div class="absolute inset-0 bg-black/40 rounded-full opacity-0 group-hover/photo:opacity-100 transition-opacity flex items-center justify-center text-[10px] text-white font-bold pointer-events-none z-10">Update</div>
        <button onclick="removeCVPhoto(event)" id="btn-remove-photo" class="absolute -top-1 -right-1 bg-red-500 hover:bg-red-600 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs shadow-md ${cvData.photo ? '' : 'hidden'} transition-all hover:scale-110 z-20" title="Remove Photo">×</button>
      </div>
      <div class="flex-1">
        <h1 contenteditable="true" id="cv-name" class="text-2xl font-extrabold text-white tracking-wide outline-none mb-1">${cvData.name || "Your Name"}</h1>
        <div contenteditable="true" id="cv-contact" class="text-xs text-teal-100 font-medium outline-none">${contactText}</div>
      </div>
    `;
    currentPageCard.appendChild(headerBanner);

    // 2. Layout Grid Container (2-Col Sidebar vs 1-Col Standard)
    let layoutContainer = document.createElement("div");
    let sidebarCol = null;
    let mainCol = null;

    if (is2Col) {
      layoutContainer.className = "cv-2col-layout";
      sidebarCol = document.createElement("div");
      sidebarCol.className = "cv-2col-sidebar";
      
      mainCol = document.createElement("div");
      mainCol.className = "cv-2col-main";

      layoutContainer.appendChild(sidebarCol);
      layoutContainer.appendChild(mainCol);
    } else {
      layoutContainer.className = "cv-1col-layout";
    }
    currentPageCard.appendChild(layoutContainer);
    listContainer.appendChild(currentPageCard);

    // 3. Render Sections
    cvData.sections.forEach((sec, sIdx) => {
      const secEl = document.createElement("div");
      secEl.className = "draggable-section group/section";
      secEl.setAttribute("data-type", sec.type || "text");
      
      let contentHTML = "";

      if (sec.type === "text") {
        contentHTML = `<div class="sec-content text-xs text-slate-700 leading-relaxed outline-none p-2 border-l-3 rounded-r-md ml-0" contenteditable="true">${sec.content || ""}</div>`;
      } 
      else if (sec.type === "list") {
        if (Array.isArray(sec.content)) {
          const listItemsHTML = sec.content.map(skill => `
            <div class="skill-item-row flex items-center gap-1.5 py-0.5">
              <span class="bullet-marker text-xs font-bold select-none">${cvState.bulletSymbol || '│'}</span>
              <span contenteditable="true" class="skill-chip flex-1 outline-none text-xs font-semibold text-slate-700">${skill}</span>
            </div>
          `).join('');
          contentHTML = `<div class="sec-content space-y-1">${listItemsHTML}</div>`;
        } else {
          contentHTML = `<div class="sec-content text-xs text-slate-600 font-medium outline-none p-2 ml-0" contenteditable="true">${sec.content || ""}</div>`;
        }
      } 
      else if (sec.type === "experience" || sec.type === "education") {
        contentHTML = `<div class="sec-content space-y-3">`;
        if (Array.isArray(sec.content)) {
          sec.content.forEach((item, itemIdx) => {
            const isExp = sec.type === "experience";
            const titleVal = isExp ? (item.role || "Role") : (item.degree || "Degree");
            const subTitleVal = isExp ? (item.company || "Company") : (item.institution || "Institution");
            const period = item.period || "";
            const location = item.location || "";

            let bulletsHTML = `<div class="bullets-container space-y-1 mt-1.5">`;
            if (Array.isArray(item.bullets)) {
              item.bullets.forEach((bullet, bIdx) => {
                bulletsHTML += `
                  <div class="bullet-item flex items-start gap-1.5 group/bullet relative pr-6 my-0.5">
                    <span class="bullet-marker text-xs font-bold select-none pt-0.5">${cvState.bulletSymbol || '│'}</span>
                    <span contenteditable="true" class="bullet-text flex-1 outline-none text-xs text-slate-700 leading-relaxed">${bullet}</span>
                    <button onclick="deleteBullet(this)" class="absolute right-0 top-0.5 hidden group-hover/bullet:block text-[10px] text-red-500 font-bold hover:underline">Delete</button>
                  </div>`;
              });
            }
            bulletsHTML += `</div>`;

            contentHTML += `
              <div class="item-block border-l-3 pl-3 py-0.5 mb-2 relative group/item rounded-r-md" data-idx="${itemIdx}">
                <div class="flex flex-wrap justify-between items-start gap-2 mb-0.5">
                  <div class="flex items-center gap-1.5 flex-wrap">
                    <span contenteditable="true" class="item-title text-xs font-bold text-slate-900 outline-none">${titleVal}</span>
                    <span class="text-slate-400 font-medium text-xs">@</span>
                    <span contenteditable="true" class="item-sub-title font-semibold text-slate-700 text-xs outline-none">${subTitleVal}</span>
                  </div>
                  <div class="flex items-center gap-1 text-[10px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md border border-slate-200 font-medium">
                    <span contenteditable="true" class="item-period outline-none">${period}</span>
                    ${location ? `<span class="text-slate-300">│</span> <span contenteditable="true" class="item-location outline-none">${location}</span>` : `<span contenteditable="true" class="item-location outline-none hidden"></span>`}
                  </div>
                </div>
                ${bulletsHTML}
                
                <div class="flex gap-3 mt-1 opacity-0 group-hover/item:opacity-100 transition-opacity">
                  <button onclick="addBullet(this)" class="text-[10px] text-rose-500 font-semibold hover:underline">+ Add Bullet</button>
                  <button onclick="deleteItemBlock(this)" class="text-[10px] text-red-400 font-semibold hover:underline">🗑️ Delete Block</button>
                </div>
              </div>`;
          });
        }
        contentHTML += `</div>`;
        
        contentHTML += `
          <div class="mt-2 flex gap-2">
            <button onclick="addBlockItem(this, '${sec.type}')" class="inline-flex items-center gap-1 text-[10px] bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold px-2.5 py-1 rounded-md border border-slate-200 transition-all">
              ➕ Add ${sec.type === 'experience' ? 'Position' : 'Education'}
            </button>
          </div>`;
      }

      secEl.innerHTML = `
        <div class="sec-header">
          <h2 contenteditable="true" class="sec-title outline-none">${sec.title || "Section"}</h2>
          <div class="sec-tools">
            <span class="drag-handle" title="Drag to reorder section">☰</span>
            <button onclick="deleteSection(this)" class="text-[10px] text-red-500 font-semibold hover:underline">Delete 🗑️</button>
          </div>
        </div>
        ${contentHTML}
      `;

      if (is2Col && sidebarCol && mainCol) {
        if (sec.type === "list" || sec.type === "education") {
          sidebarCol.appendChild(secEl);
        } else {
          mainCol.appendChild(secEl);
        }
      } else {
        layoutContainer.appendChild(secEl);
      }
    });
  }

  // Initialize SortableJS for dragging & reordering sections
  new Sortable(listContainer.querySelector('.cv-2col-main') || listContainer.querySelector('.cv-1col-layout') || listContainer, {
    handle: '.drag-handle',
    ghostClass: 'ghost-class',
    animation: 180
  });
}

function getActiveCV() {
  return cvState.tailoredCvData || cvState.parsedCvData || cvState.currentCV;
}

function changeCVTheme() {
  const themeSelect = document.getElementById("cv-theme-select");
  if (!themeSelect) return;
  
  const selectedTheme = themeSelect.value;
  cvState.theme = selectedTheme;

  const themeColors = {
    creative: "#0F766E",
    executive: "#1E3A8A",
    tech: "#0F172A",
    academic: "#27272A",
    minimalist: "#E11D48"
  };

  const accentColor = themeColors[selectedTheme] || "#0F766E";
  cvState.customColor = accentColor;
  document.documentElement.style.setProperty('--theme-accent', accentColor);
  
  // Update the color picker input to reflect the new theme's default color
  const colorPicker = document.getElementById("custom-color-input");
  if (colorPicker) colorPicker.value = accentColor;

  const sheet = document.getElementById("resume-sheet");
  if (sheet) {
    const classesToRemove = Array.from(sheet.classList).filter(cls => cls.startsWith("theme-"));
    classesToRemove.forEach(cls => sheet.classList.remove(cls));
    sheet.classList.add(`theme-${selectedTheme}`);
  }
  
  const activeCV = getActiveCV();
  if (activeCV) {
    renderWYSIWYG(activeCV);
    saveAndCompile();
  }
}

function changeLayoutMode(mode) {
  cvState.layoutMode = mode;
  const sheet = document.getElementById("resume-sheet");
  if (sheet) {
    sheet.classList.remove("layout-2col", "layout-1col");
    sheet.classList.add(`layout-${mode}`);
  }
  const activeCV = getActiveCV();
  if (activeCV) {
    renderWYSIWYG(activeCV);
    saveAndCompile();
  }
}

function changeLineStyle(style) {
  cvState.lineStyle = style;
  const sheet = document.getElementById("resume-sheet");
  if (sheet) {
    sheet.classList.remove("line-style-short", "line-style-full", "line-style-none");
    sheet.classList.add(`line-style-${style}`);
  }
  const activeCV = getActiveCV();
  if (activeCV) {
    renderWYSIWYG(activeCV);
    saveAndCompile();
  }
}

function changeBulletSymbol(symbol) {
  cvState.bulletSymbol = symbol;
  document.querySelectorAll(".bullet-marker").forEach(el => {
    el.innerText = symbol;
  });
  const activeCV = getActiveCV();
  if (activeCV) {
    saveAndCompile();
  }
}

function changeCustomColor(color) {
  cvState.customColor = color;
  document.documentElement.style.setProperty('--theme-accent', color);
  const activeCV = getActiveCV();
  if (activeCV) {
    saveAndCompile();
  }
}

function addBullet(btn) {
  const container = btn.closest('.item-block').querySelector('.bullets-container') || btn.closest('.item-block').querySelector('ul') || btn.closest('.item-block');
  const div = document.createElement('div');
  div.className = 'bullet-item flex items-start gap-2 group/bullet relative pr-8 my-1';
  div.innerHTML = `
    <span class="bullet-marker text-xs font-bold select-none pt-0.5">${cvState.bulletSymbol || '│'}</span>
    <span contenteditable="true" class="bullet-text flex-1 outline-none text-xs text-slate-700 leading-relaxed">New bullet point. Click to customize.</span>
    <button onclick="deleteBullet(this)" class="absolute right-0 top-0.5 hidden group-hover/bullet:block text-[10px] text-red-500 font-bold hover:underline">Delete</button>
  `;
  container.appendChild(div);
  saveAndCompile();
}

function deleteBullet(btn) {
  const item = btn.closest('.bullet-item') || btn.closest('li');
  if (item) item.remove();
  saveAndCompile();
}

function deleteItemBlock(btn) {
  if (confirm("Are you sure you want to delete this block item?")) {
    btn.closest('.item-block').remove();
    saveAndCompile();
  }
}

// ==========================================
// 💾 SAVE & REBUILD HANDLERS
// ==========================================

async function saveAndCompile() {
  const activeCV = getActiveCV();
  if (!activeCV) return;

  const nameEl = document.getElementById("cv-name");
  const contactEl = document.getElementById("cv-contact");

  if (nameEl) activeCV.name = nameEl.innerText.trim();
  if (contactEl) {
    const contactRaw = contactEl.innerText.trim();
    activeCV.contact_info = contactRaw.split("│").map(s => s.trim()).filter(s => s.length > 0);
  }

  const sections = [];
  document.querySelectorAll(".draggable-section").forEach(secEl => {
    const titleEl = secEl.querySelector(".sec-title");
    const title = titleEl ? titleEl.innerText.trim() : "SECTION";
    const type = secEl.getAttribute("data-type") || "text";
    let content = null;

    if (type === "text") {
      const contentEl = secEl.querySelector(".sec-content");
      content = contentEl ? contentEl.innerText.trim() : "";
    } 
    else if (type === "list") {
      const chips = secEl.querySelectorAll(".skill-chip");
      if (chips.length > 0) {
        content = Array.from(chips).map(c => c.innerText.trim()).filter(s => s.length > 0);
      } else {
        const contentEl = secEl.querySelector(".sec-content");
        content = contentEl ? contentEl.innerText.trim() : "";
      }
    } 
    else if (type === "experience" || type === "education") {
      content = [];
      secEl.querySelectorAll(".item-block").forEach(itemEl => {
        const item = {
          period: itemEl.querySelector(".item-period")?.innerText.trim() || ""
        };

        const locEl = itemEl.querySelector(".item-location");
        if (locEl && locEl.innerText.trim().length > 0) {
          item.location = locEl.innerText.trim();
        }

        if (type === "experience") {
          item.role = itemEl.querySelector(".item-title")?.innerText.trim() || "";
          item.company = itemEl.querySelector(".item-sub-title")?.innerText.trim() || "";
        } else {
          item.degree = itemEl.querySelector(".item-title")?.innerText.trim() || "";
          item.institution = itemEl.querySelector(".item-sub-title")?.innerText.trim() || "";
        }

        const bullets = [];
        itemEl.querySelectorAll(".bullet-text").forEach(bEl => {
          bullets.push(bEl.innerText.trim());
        });
        item.bullets = bullets;

        content.push(item);
      });
    }

    sections.push({ title, type, content });
  });

  if (sections.length > 0) {
    activeCV.sections = sections;
  }

  // Inject photo from state into cv_data so backend can embed it in PDF/DOCX
  activeCV.photo = cvState.photo || null;

  try {
    const response = await fetch("/api/generate-docs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cv_data: activeCV,
        job_title: cvState.selectedJob ? cvState.selectedJob.title : "Target Role",
        company: cvState.selectedJob ? cvState.selectedJob.company : "Company",
        theme: cvState.theme || "creative",
        custom_color: cvState.customColor || "#0F766E",
        line_style: cvState.lineStyle || "short",
        bullet_symbol: cvState.bulletSymbol || "│",
        layout_mode: cvState.layoutMode || "2col"
      })
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Regeneration failed.");

    cvState.tailoredCvData = activeCV;
    cvState.tailoredDocxPath = data.docx_path;
    cvState.tailoredPdfPath = data.pdf_path;

    refreshPDFPreview();
  } catch (err) {
    console.error("Save Error:", err);
  }
}

/**
 * Request File download from the FastAPI backend.
 * FastAPI concept: We pass file path as query parameters to '/api/download'.
 * Starlette serves it as a streaming binary file response.
 */
function downloadFormat(format) {
  const path = format === 'pdf' ? cvState.tailoredPdfPath : cvState.tailoredDocxPath;
  if (!path) {
    alert("No generated file found. Please run the optimizer first.");
    return;
  }
  
  // Open download link
  window.open(`/api/download?path=${encodeURIComponent(path)}`, '_blank');
}

/**
 * Alias for downloadFormat to support modal buttons.
 */
function downloadTailoredFile(format) {
  downloadFormat(format);
}

/**
 * Upload CV profile image file, convert it to Base64, and sync.
 */
function uploadCVPhoto() {
  const input = document.getElementById("cv-photo-input");
  if (!input || input.files.length === 0) return;
  
  const file = input.files[0];
  const reader = new FileReader();
  
  reader.onload = function(e) {
    const base64Img = e.target.result;
    document.getElementById("cv-photo").src = base64Img;
    cvState.photo = base64Img;
    
    // Toggle remove button visibility
    const removeBtn = document.getElementById("btn-remove-photo");
    if (removeBtn) {
      removeBtn.classList.remove("hidden");
    }
    
    if (cvState.tailoredCvData) {
      saveAndCompile();
    }
  };
  reader.readAsDataURL(file);
}

/**
 * Remove the CV profile photo, resetting to image placeholder.
 */
function removeCVPhoto(event) {
  if (event) {
    event.stopPropagation();
    event.preventDefault();
  }
  
  if (confirm("Are you sure you want to remove the profile photo?")) {
    cvState.photo = null;
    const photoImg = document.getElementById("cv-photo");
    if (photoImg) {
      photoImg.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 100 100'><rect width='100' height='100' fill='%23F1F5F9'/><text x='50%' y='55%' font-family='Arial' font-size='12' fill='%2394A3B8' text-anchor='middle'>Add Photo</text></svg>";
    }
    const removeBtn = document.getElementById("btn-remove-photo");
    if (removeBtn) {
      removeBtn.classList.add("hidden");
    }
    
    if (cvState.tailoredCvData) {
      saveAndCompile();
    }
  }
}

/**
 * Add a new experience / education block item under a section.
 */
function addBlockItem(btn, type) {
  const contentDiv = btn.closest('.draggable-section').querySelector('.sec-content');
  if (!contentDiv) return;
  
  const newItem = document.createElement("div");
  newItem.className = "item-block border-l-3 pl-3.5 py-1 mb-3 relative group/item rounded-r-lg transition-all mt-3";
  
  const isExp = type === "experience";
  const titleVal = isExp ? "Job Title / Role" : "Degree / Certificate";
  const subTitleVal = isExp ? "Company Name" : "Institution Name";
  
  newItem.innerHTML = `
    <div class="flex flex-wrap justify-between items-start gap-2 mb-1">
      <div class="flex items-center gap-1.5 flex-wrap">
        <span contenteditable="true" class="item-title text-sm font-bold text-slate-900 outline-none">${titleVal}</span>
        <span class="text-slate-400 font-medium text-xs">@</span>
        <span contenteditable="true" class="item-sub-title font-semibold text-slate-700 outline-none">${subTitleVal}</span>
      </div>
      <div class="flex items-center gap-1.5 text-[11px] bg-slate-100 text-slate-600 px-2.5 py-0.5 rounded-full border border-slate-200 font-medium shadow-2xs">
        <span>📅</span>
        <span contenteditable="true" class="item-period outline-none">2024 - Present</span>
        <span class="text-slate-300">|</span> <span>📍</span>
        <span contenteditable="true" class="item-location outline-none">Location</span>
      </div>
    </div>
    <div class="bullets-container space-y-1.5 mt-2">
      <div class="bullet-item flex items-start gap-2 group/bullet relative pr-8 my-1">
        <span class="bullet-marker text-xs font-bold select-none pt-0.5">│</span>
        <span contenteditable="true" class="bullet-text flex-1 outline-none text-xs text-slate-700 leading-relaxed">Describe your impact or responsibilities.</span>
        <button onclick="deleteBullet(this)" class="absolute right-0 top-0.5 hidden group-hover/bullet:block text-[10px] text-red-500 font-bold hover:underline">Delete</button>
      </div>
    </div>
    <div class="flex gap-3 mt-1.5 opacity-0 group-hover/item:opacity-100 transition-opacity">
      <button onclick="addBullet(this)" class="text-[10px] text-rose-500 font-semibold hover:underline">+ Add Bullet</button>
      <button onclick="deleteItemBlock(this)" class="text-[10px] text-red-400 font-semibold hover:underline">🗑️ Delete Block</button>
    </div>
  `;
  contentDiv.appendChild(newItem);
  saveAndCompile();
}

/**
 * Create a new dynamic text, list, experience, or education section.
 */
function addNewSection() {
  const type = document.getElementById("new-section-type").value;
  const titleMap = {
    text: "New Text Section",
    list: "New List Section",
    experience: "Work Experience",
    education: "Education"
  };
  
  const newSec = {
    title: titleMap[type],
    type: type,
    content: type === "text" ? "Enter details here." :
             type === "list" ? ["Item 1", "Item 2"] : []
  };
  
  if (!cvState.tailoredCvData) {
    cvState.tailoredCvData = { name: "Your Name", contact_info: [], sections: [] };
  }
  if (!Array.isArray(cvState.tailoredCvData.sections)) {
    cvState.tailoredCvData.sections = [];
  }
  
  cvState.tailoredCvData.sections.push(newSec);
  renderWYSIWYG(cvState.tailoredCvData);
  saveAndCompile();
}

/**
 * Delete a CV section.
 */
function deleteSection(btn) {
  if (confirm("Are you sure you want to delete this entire section?")) {
    btn.closest('.draggable-section').remove();
    saveAndCompile();
  }
}

/**
 * Set the workspace layout view mode (edit, split, preview).
 */
function setViewMode(mode) {
  const editor = document.getElementById("editor-container");
  const preview = document.getElementById("preview-container");
  const btnEdit = document.getElementById("btn-mode-edit");
  const btnSplit = document.getElementById("btn-mode-split");
  const btnPreview = document.getElementById("btn-mode-preview");
  
  if (!editor || !preview) return;
  
  // Update button active states
  [btnEdit, btnSplit, btnPreview].forEach(btn => {
    if (btn) {
      btn.classList.remove("bg-white", "text-slate-800", "shadow-sm");
      btn.classList.add("text-slate-600", "hover:text-slate-800");
    }
  });
  
  const activeBtn = document.getElementById(`btn-mode-${mode}`);
  if (activeBtn) {
    activeBtn.classList.remove("text-slate-600", "hover:text-slate-800");
    activeBtn.classList.add("bg-white", "text-slate-800", "shadow-sm");
  }
  
  if (mode === "edit") {
    editor.classList.remove("hidden", "w-1/2");
    editor.classList.add("flex-1");
    preview.classList.add("hidden");
  } 
  else if (mode === "split") {
    editor.classList.remove("hidden", "flex-1");
    editor.classList.add("w-1/2");
    preview.classList.remove("hidden", "w-1/2");
    preview.classList.add("flex-1"); // Let it expand nicely
    refreshPDFPreview();
  } 
  else if (mode === "preview") {
    editor.classList.add("hidden");
    preview.classList.remove("hidden", "w-1/2");
    preview.classList.add("flex-1");
    refreshPDFPreview();
  }
  
  localStorage.setItem("cv_view_mode", mode);
}

/**
 * Reload the Live PDF Preview iframe source using a cache-buster.
 */
function refreshPDFPreview() {
  const iframe = document.getElementById("pdf-preview-iframe");
  if (!iframe) return;
  
  if (cvState.tailoredPdfPath) {
    iframe.src = `/api/download?path=${encodeURIComponent(cvState.tailoredPdfPath)}&inline=true&t=${Date.now()}#toolbar=0&navpanes=0`;
  } else {
    iframe.src = "about:blank";
  }
}

/**
 * Get selected model name from dropdown select or custom input text.
 */
function getSelectedModel(provider) {
  const select = document.getElementById(`${provider}-model-select`);
  const custom = document.getElementById(`${provider}-model-custom`);
  if (!select) return provider === "gemini" ? "gemini-2.5-flash" : "llama3";
  
  if (select.value === "custom") {
    return custom ? (custom.value.trim() || (provider === "gemini" ? "gemini-2.5-flash" : "llama3")) : "gemini-2.5-flash";
  }
  return select.value;
}

/**
 * Toggle visibility of custom model text input.
 */
function toggleCustomModelInput(provider) {
  const select = document.getElementById(`${provider}-model-select`);
  const custom = document.getElementById(`${provider}-model-custom`);
  if (!select || !custom) return;
  
  if (select.value === "custom") {
    custom.classList.remove("hidden");
  } else {
    custom.classList.add("hidden");
  }
  saveAppStateToCache();
}

/**
 * Save current application state to browser localStorage cache.
 */
function saveAppStateToCache() {
  const stateToCache = {
    originalCvPath: cvState.originalCvPath,
    originalCvText: cvState.originalCvText,
    selectedJob: cvState.selectedJob,
    tailoredCvData: cvState.tailoredCvData,
    tailoredDocxPath: cvState.tailoredDocxPath,
    tailoredPdfPath: cvState.tailoredPdfPath,
    theme: cvState.theme,
    photo: cvState.photo,
    
    // Inputs
    geminiKey: document.getElementById("gemini-key")?.value || "",
    geminiModelSelect: document.getElementById("gemini-model-select")?.value || "gemini-2.5-flash",
    geminiModelCustom: document.getElementById("gemini-model-custom")?.value || "",
    ollamaUrl: document.getElementById("ollama-url")?.value || "http://localhost:11434",
    ollamaModelSelect: document.getElementById("ollama-model-select")?.value || "llama3",
    ollamaModelCustom: document.getElementById("ollama-model-custom")?.value || "",
    llmProvider: document.getElementById("llm-provider")?.value || "gemini",
    liAtCookie: document.getElementById("li-at-cookie")?.value || "",
    searchKeywords: document.getElementById("search-keywords")?.value || "",
    searchLocation: document.getElementById("search-location")?.value || "",
    searchLimit: document.getElementById("search-limit")?.value || "5",
    additionalInfo: document.getElementById("additional-info")?.value || "",
    
    // Loaded details
    loadedFilename: document.getElementById("loaded-filename")?.innerText || "",
    loadedCharsCount: document.getElementById("loaded-chars-count")?.innerText || "0",
    cvDetailsVisible: !document.getElementById("cv-details-panel")?.classList.contains("hidden")
  };
  
  localStorage.setItem("cv_app_cached_state", JSON.stringify(stateToCache));
}

/**
 * Restore application state from browser localStorage cache on load.
 */
function loadAppStateFromCache() {
  const cached = localStorage.getItem("cv_app_cached_state");
  if (!cached) return;
  
  try {
    const state = JSON.parse(cached);
    
    cvState.originalCvPath = state.originalCvPath || null;
    cvState.originalCvText = state.originalCvText || null;
    cvState.selectedJob = state.selectedJob || null;
    cvState.tailoredCvData = state.tailoredCvData || null;
    cvState.tailoredDocxPath = state.tailoredDocxPath || null;
    cvState.tailoredPdfPath = state.tailoredPdfPath || null;
    cvState.theme = state.theme || "minimalist";
    cvState.photo = state.photo || null;
    
    if (document.getElementById("gemini-key")) document.getElementById("gemini-key").value = state.geminiKey || "";
    if (document.getElementById("gemini-model-select")) {
      document.getElementById("gemini-model-select").value = state.geminiModelSelect || "gemini-2.5-flash";
      toggleCustomModelInput("gemini");
    }
    if (document.getElementById("gemini-model-custom")) document.getElementById("gemini-model-custom").value = state.geminiModelCustom || "";
    if (document.getElementById("ollama-url")) document.getElementById("ollama-url").value = state.ollamaUrl || "http://localhost:11434";
    if (document.getElementById("ollama-model-select")) {
      document.getElementById("ollama-model-select").value = state.ollamaModelSelect || "llama3";
      toggleCustomModelInput("ollama");
    }
    if (document.getElementById("ollama-model-custom")) document.getElementById("ollama-model-custom").value = state.ollamaModelCustom || "";
    if (document.getElementById("llm-provider")) {
      document.getElementById("llm-provider").value = state.llmProvider || "gemini";
      toggleLLMInputs();
    }
    if (document.getElementById("li-at-cookie")) document.getElementById("li-at-cookie").value = state.liAtCookie || "";
    if (document.getElementById("search-keywords")) document.getElementById("search-keywords").value = state.searchKeywords || "";
    if (document.getElementById("search-location")) document.getElementById("search-location").value = state.searchLocation || "";
    if (document.getElementById("search-limit")) document.getElementById("search-limit").value = state.searchLimit || "5";
    if (document.getElementById("additional-info")) document.getElementById("additional-info").value = state.additionalInfo || "";
    
    if (document.getElementById("cv-theme-select")) {
      document.getElementById("cv-theme-select").value = cvState.theme;
    }
    
    if (cvState.selectedJob) {
      document.getElementById("banner-job-title").innerText = cvState.selectedJob.title;
      document.getElementById("banner-job-company").innerText = cvState.selectedJob.company;
      document.getElementById("target-selection-banner").classList.remove("hidden");
    }
    
    if (state.loadedFilename && cvState.originalCvPath) {
      document.getElementById("loaded-filename").innerText = state.loadedFilename;
      document.getElementById("loaded-chars-count").innerText = state.loadedCharsCount;
    }
    if (state.cvDetailsVisible && cvState.originalCvPath) {
      document.getElementById("cv-details-panel").classList.remove("hidden");
    }
    
    checkTailorEnable();
    
    if (cvState.tailoredCvData) {
      renderWYSIWYG(cvState.tailoredCvData);
      document.getElementById("download-actions-bar").classList.remove("hidden");
      document.getElementById("resume-sheet").classList.remove("hidden");
      document.getElementById("cv-empty-placeholder").classList.add("hidden");
      refreshPDFPreview();
    }
  } catch (e) {
    console.error("Failed to load cached state:", e);
  }
}

// Initialize default view mode & load cached state on load
document.addEventListener("DOMContentLoaded", () => {
  loadAppStateFromCache();
  loadSavedCVList();
  syncCookieFromMemory(); // Pre-fill li_at from server memory if localStorage is empty
  
  const savedMode = localStorage.getItem("cv_view_mode") || "edit";
  setViewMode(savedMode);
  
  // Attach auto-save listeners on all sidebar inputs
  const sidebarInputs = [
    "gemini-key", "gemini-model-select", "gemini-model-custom",
    "ollama-url", "ollama-model-select", "ollama-model-custom",
    "llm-provider", "li-at-cookie", "search-keywords",
    "search-location", "search-limit", "additional-info"
  ];
  sidebarInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", saveAppStateToCache);
      el.addEventListener("change", saveAppStateToCache);
    }
  });

  // Persist li-at-cookie to server memory when user changes it, so
  // guided apply sessions can find it even if the field is cleared
  const liAtInput = document.getElementById("li-at-cookie");
  if (liAtInput) {
    liAtInput.addEventListener("change", persistCookieToMemory);
    liAtInput.addEventListener("blur", persistCookieToMemory);
  }

  // Auto-sync manual job form inputs to cvState.selectedJob
  const manualInputs = ["job-title", "job-company", "job-desc", "direct-job-url"];
  manualInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      const autoSyncJob = () => {
        const title = document.getElementById("job-title")?.value;
        const company = document.getElementById("job-company")?.value;
        const desc = document.getElementById("job-desc")?.value;
        const url = document.getElementById("direct-job-url")?.value || "Direct Entry";
        
        if (title || desc) {
          cvState.selectedJob = {
            title: title || "Target Role",
            company: company || "Target Company",
            description: desc || `Job Title: ${title}`,
            url: url
          };
          document.getElementById("banner-job-title").innerText = cvState.selectedJob.title;
          document.getElementById("banner-job-company").innerText = cvState.selectedJob.company;
          document.getElementById("target-selection-banner").classList.remove("hidden");
          saveAppStateToCache();
        }
      };
      el.addEventListener("input", autoSyncJob);
      el.addEventListener("change", autoSyncJob);
    }
  });
});

// =============================================================================
// 🤖 AUTO-APPLY QUEUE MODULE
// =============================================================================

if (!cvState.applyQueue) cvState.applyQueue = [];

let _applyQueueResults = [];
let _applyCurrentResultIdx = 0;
let _queueStopped = false;
let _currentScreenshotIdx = 0;
let _currentScreenshots = [];
const SCREENSHOT_LABELS = [
  'Contact Information', 'Resume Upload', 'Screening Qs (1)',
  'Screening Qs (2)', 'Screening Qs (3)', 'Review Page', 'Submitted'
];

function updateQueueBadge() {
  const count = cvState.applyQueue.length;
  const badge = document.getElementById('queue-count-badge');
  const btn = document.getElementById('btn-auto-apply-queue');
  if (badge) badge.textContent = count;
  if (btn) btn.classList.toggle('hidden', count === 0);
}

function toggleJobQueue(idx) {
  const job = cvState.searchResults?.[idx];
  if (!job) return;
  const existing = cvState.applyQueue.findIndex(q => q.job_url === job.url);
  if (existing >= 0) {
    cvState.applyQueue.splice(existing, 1);
    showToast(`Removed ${job.company} from queue`);
  } else {
    cvState.applyQueue.push({
      job_url: job.url, job_title: job.title, company: job.company,
      pdf_path: cvState.tailoredPdfPath || cvState.originalCvPath || '',
      cover_letter: '', answers_override: {},
      easy_apply: job.easy_apply
    });
    showToast(`Added ${job.company} to queue ✓`);
  }
  updateQueueBadge();
  saveAppStateToCache();
  const btn = document.getElementById(`queue-btn-${idx}`);
  if (btn) {
    const isNowQueued = existing < 0;
    btn.textContent = isNowQueued ? '✓ Queued' : '+ Queue';
    btn.className = `text-[10px] px-2.5 py-1 rounded transition-all font-semibold ${isNowQueued ? 'bg-violet-600 text-white' : 'bg-slate-700 hover:bg-violet-700 text-slate-300'}`;
  }
}

function openQueueModal() {
  renderQueueModal();
  loadApplicationHistory();
  document.getElementById('auto-apply-modal').classList.remove('hidden');
}
function closeQueueModal() { document.getElementById('auto-apply-modal').classList.add('hidden'); }
function clearQueue() {
  cvState.applyQueue = []; updateQueueBadge(); renderQueueModal(); saveAppStateToCache(); showToast('Queue cleared');
}

function renderQueueModal() {
  const list = document.getElementById('queue-jobs-list');
  const countBadge = document.getElementById('queue-modal-count');
  if (!list) return;
  if (countBadge) countBadge.textContent = `${cvState.applyQueue.length} job${cvState.applyQueue.length !== 1 ? 's' : ''}`;
  if (cvState.applyQueue.length === 0) {
    list.innerHTML = `<div class="text-center py-8 text-xs text-slate-500">No jobs in queue yet.<br>Click <strong class="text-violet-400">+ Queue</strong> on any search result.</div>`;
    return;
  }
  list.innerHTML = cvState.applyQueue.map((job, i) => `
    <div class="bg-[#1E293B] border border-[#334155] rounded-xl p-4 space-y-3">
      <div class="flex items-start justify-between">
        <div>
          <div class="flex items-center gap-2 flex-wrap">
            <div class="text-xs font-bold text-slate-100">${job.job_title}</div>
            ${renderEasyApplyBadge(job.easy_apply)}
          </div>
          <div class="text-[11px] text-violet-400 font-medium mt-0.5">🏢 ${job.company}</div>
          <div class="text-[10px] text-slate-500 font-mono truncate max-w-xs mt-0.5">${job.job_url}</div>
        </div>
        <button onclick="removeFromQueue(${i})" class="text-slate-500 hover:text-red-400 text-xs ml-2 font-bold">✕</button>
      </div>
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">📄 Cover Letter</label>
          <button onclick="generateCoverLetterForJob(${i})" id="cl-gen-btn-${i}" class="text-[10px] text-violet-400 hover:text-violet-300 font-semibold">✨ Generate with AI</button>
        </div>
        <textarea id="cover-letter-${i}" rows="5" onchange="updateQueueJobField(${i},'cover_letter',this.value)"
          placeholder="Click Generate with AI or write your own..."
          class="w-full bg-[#0F172A] border border-[#334155] rounded-lg text-slate-300 text-[11px] p-2.5 focus:outline-none focus:border-violet-500 resize-none font-mono"
        >${job.cover_letter || ''}</textarea>
      </div>
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">💬 Screening Overrides</label>
          <button onclick="addAnswerOverride(${i})" class="text-[10px] text-rose-400 hover:text-rose-300">+ Add</button>
        </div>
        <div id="answers-override-${i}" class="space-y-1">${renderAnswerOverrides(i)}</div>
      </div>
    </div>
  `).join('');
}

function renderAnswerOverrides(queueIdx) {
  const entries = Object.entries(cvState.applyQueue[queueIdx]?.answers_override || {});
  if (!entries.length) return `<div class="text-[10px] text-slate-600 italic">No overrides — AI auto-detects from your CV.</div>`;
  return entries.map(([q, a], ri) => `
    <div class="flex gap-1">
      <input value="${q.replace(/"/g,'&quot;')}" placeholder="Question" onchange="updateOverrideKey(${queueIdx},${ri},this.value)"
        class="flex-1 bg-[#0F172A] border border-[#334155] rounded text-slate-300 text-[10px] p-1.5 focus:outline-none">
      <input value="${a.replace(/"/g,'&quot;')}" placeholder="Answer" onchange="updateOverrideVal(${queueIdx},${ri},this.value)"
        class="w-24 bg-[#0F172A] border border-[#334155] rounded text-slate-300 text-[10px] p-1.5 focus:outline-none">
      <button onclick="removeOverride(${queueIdx},${ri})" class="text-slate-500 hover:text-red-400 text-xs px-1">✕</button>
    </div>
  `).join('');
}

function addAnswerOverride(qi) { if (cvState.applyQueue[qi]) { cvState.applyQueue[qi].answers_override['New question'] = 'Answer'; renderQueueModal(); } }
function removeOverride(qi, ri) { const keys = Object.keys(cvState.applyQueue[qi].answers_override); delete cvState.applyQueue[qi].answers_override[keys[ri]]; renderQueueModal(); }
function updateOverrideKey(qi, ri, nk) { const e = Object.entries(cvState.applyQueue[qi].answers_override); const v = e[ri][1]; delete cvState.applyQueue[qi].answers_override[e[ri][0]]; cvState.applyQueue[qi].answers_override[nk] = v; }
function updateOverrideVal(qi, ri, nv) { const k = Object.keys(cvState.applyQueue[qi].answers_override)[ri]; cvState.applyQueue[qi].answers_override[k] = nv; }
function removeFromQueue(idx) { cvState.applyQueue.splice(idx,1); updateQueueBadge(); renderQueueModal(); saveAppStateToCache(); }
function updateQueueJobField(idx, field, value) { if (cvState.applyQueue[idx]) { cvState.applyQueue[idx][field] = value; saveAppStateToCache(); } }

async function generateCoverLetterForJob(qi) {
  const job = cvState.applyQueue[qi]; if (!job) return;
  const btn = document.getElementById(`cl-gen-btn-${qi}`);
  if (btn) { btn.textContent = '⏳ Generating...'; btn.disabled = true; }
  try {
    const provider = document.getElementById('llm-provider')?.value || 'gemini';
    const jobDesc = cvState.searchResults?.find(r => r.url === job.job_url)?.description || cvState.selectedJob?.description || '';
    const resp = await fetch('/api/generate-cover-letter', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cv_data: cvState.tailoredCvData || cvState.parsedCvData || {}, job_description: jobDesc,
        job_title: job.job_title, company: job.company, provider, llm_config: getLLMConfig() })
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Generation failed');
    const ta = document.getElementById(`cover-letter-${qi}`);
    if (ta) ta.value = data.cover_letter;
    cvState.applyQueue[qi].cover_letter = data.cover_letter;
    saveAppStateToCache();
    showToast(`✨ Cover letter generated for ${job.company}`);
  } catch(err) { showToast(`❌ ${err.message}`); }
  finally { if (btn) { btn.textContent = '✨ Generate with AI'; btn.disabled = false; } }
}

async function startAutoApplyQueue() {
  if (!cvState.applyQueue.length) { showToast('Queue is empty'); return; }
  const liAt = document.getElementById('li-at-cookie')?.value || '';
  if (!liAt) { showToast('⚠️ Enter your li_at cookie first'); return; }
  const btn = document.getElementById('btn-start-queue');
  if (btn) { btn.textContent = '⏳ Running... Chromium is filling forms'; btn.disabled = true; }
  _queueStopped = false; closeQueueModal();
  showToast('🤖 Auto Apply started — browser opening...');
  try {
    const resp = await fetch('/api/auto-apply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_queue: cvState.applyQueue, li_at: liAt,
        cv_data: cvState.tailoredCvData || cvState.parsedCvData || {}, dry_run: true })
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Auto-apply failed');
    _applyQueueResults = data.results || []; _applyCurrentResultIdx = 0;
    if (!_applyQueueResults.length) { showToast('No results returned'); return; }
    showToast(`✅ Dry run done — reviewing ${_applyQueueResults.length} job(s)`);
    showConfirmModal(0);
  } catch(err) { showToast(`❌ ${err.message}`); }
  finally { if (btn) { btn.textContent = '🚀 Start Auto Apply (Dry Run — Preview Before Submit)'; btn.disabled = false; } }
}

function showConfirmModal(idx) {
  const result = _applyQueueResults[idx]; if (!result) return;
  const sub = document.getElementById('confirm-modal-subtitle');
  if (sub) sub.textContent = `${result.company} • ${result.job_title} (${idx+1}/${_applyQueueResults.length})`;
  _currentScreenshots = result.screenshots || []; _currentScreenshotIdx = 0; updateScreenshotCarousel();
  const aDiv = document.getElementById('confirm-answers-table');
  const entries = Object.entries(result.screening_answers || {});
  if (aDiv) aDiv.innerHTML = entries.length
    ? entries.map(([q,a]) => `<div class="flex gap-2 text-[10px] bg-[#1E293B] rounded px-2 py-1.5"><span class="text-slate-400 flex-1">${q}</span><span class="text-emerald-400 font-semibold shrink-0">${a}</span></div>`).join('')
    : '<div class="text-[10px] text-slate-600 italic">No screening questions detected.</div>';
  const sb = document.getElementById('btn-confirm-submit');
  if (sb) {
    if (['no_easy_apply','failed'].includes(result.status)) { sb.textContent = result.status === 'no_easy_apply' ? '⚠️ No Easy Apply — Skip' : '❌ Failed — Skip'; sb.onclick = skipCurrentJob; }
    else { sb.textContent = '✅ Confirm & Submit Application'; sb.onclick = confirmAndSubmit; }
  }
  document.getElementById('apply-confirm-modal').classList.remove('hidden');
}

function updateScreenshotCarousel() {
  const img = document.getElementById('confirm-screenshot-img');
  const counter = document.getElementById('screenshot-counter');
  const label = document.getElementById('confirm-screenshot-label');
  if (!_currentScreenshots.length) { if(img) img.src=''; if(counter) counter.textContent='0/0'; if(label) label.textContent='No screenshots'; return; }
  const path = _currentScreenshots[_currentScreenshotIdx];
  if (img) img.src = `/api/download?path=${encodeURIComponent(path)}`;
  if (counter) counter.textContent = `${_currentScreenshotIdx+1}/${_currentScreenshots.length}`;
  if (label) label.textContent = `Step ${_currentScreenshotIdx+1}: ${SCREENSHOT_LABELS[_currentScreenshotIdx] || 'Form Step'}`;
}
function prevScreenshot() { if (_currentScreenshotIdx > 0) { _currentScreenshotIdx--; updateScreenshotCarousel(); } }
function nextScreenshot() { if (_currentScreenshotIdx < _currentScreenshots.length-1) { _currentScreenshotIdx++; updateScreenshotCarousel(); } }

async function confirmAndSubmit() {
  const result = _applyQueueResults[_applyCurrentResultIdx];
  const queueJob = cvState.applyQueue.find(j => j.job_url === result?.job_url);
  if (!result || !queueJob) { skipCurrentJob(); return; }
  const sb = document.getElementById('btn-confirm-submit');
  if (sb) { sb.textContent = '⏳ Submitting...'; sb.disabled = true; }
  try {
    const liAt = document.getElementById('li-at-cookie')?.value || '';
    const resp = await fetch('/api/auto-apply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_queue: [queueJob], li_at: liAt, cv_data: cvState.tailoredCvData || cvState.parsedCvData || {}, dry_run: false })
    });
    const data = await resp.json();
    const ok = data.results?.[0]?.status === 'submitted';
    showToast(ok ? `✅ Applied to ${result.company}!` : `⚠️ Submission may have failed`);
    loadApplicationHistory();
  } catch(err) { showToast(`❌ ${err.message}`); }
  advanceConfirmQueue();
}

function skipCurrentJob() { showToast(`Skipped ${_applyQueueResults[_applyCurrentResultIdx]?.company}`); advanceConfirmQueue(); }
function stopQueue() { _queueStopped = true; document.getElementById('apply-confirm-modal').classList.add('hidden'); showToast('🛑 Queue stopped'); }
function advanceConfirmQueue() {
  document.getElementById('apply-confirm-modal').classList.add('hidden');
  _applyCurrentResultIdx++;
  if (_queueStopped || _applyCurrentResultIdx >= _applyQueueResults.length) { showToast('Queue complete ✅'); return; }
  setTimeout(() => showConfirmModal(_applyCurrentResultIdx), 600);
}

function toggleHistoryPanel() {
  const panel = document.getElementById('application-history-panel');
  const arrow = document.getElementById('history-toggle-arrow');
  if (!panel) return;
  const isHidden = panel.classList.toggle('hidden');
  if (arrow) arrow.textContent = isHidden ? '▼' : '▲';
  if (!isHidden) loadApplicationHistory();
}

async function loadApplicationHistory() {
  const panel = document.getElementById('application-history-panel');
  if (!panel || panel.classList.contains('hidden')) return;
  try {
    const resp = await fetch('/api/list-applications');
    if (!resp.ok) throw new Error();
    const data = await resp.json();
    if (!data.applications?.length) { panel.innerHTML = '<div class="text-[10px] text-slate-600 italic px-1 py-2">No applications yet.</div>'; return; }
    const ICONS = { submitted:'✅', pending_confirmation:'🔍', failed:'❌', timeout:'⏱️', no_easy_apply:'⚠️', skipped:'⏭️', submit_failed:'❌' };
    panel.innerHTML = data.applications.map(app => `
      <div class="bg-[#0F172A] border border-[#334155] rounded-lg p-2.5 text-[10px] space-y-0.5">
        <div class="flex items-center justify-between">
          <span class="font-semibold text-slate-200">${app.company||'Unknown'}</span>
          <span>${ICONS[app.status]||'❓'} <span class="text-slate-500">${app.status}</span></span>
        </div>
        <div class="text-slate-500">${app.submitted_at ? new Date(app.submitted_at).toLocaleDateString() : 'Unknown'}</div>
      </div>`).join('');
  } catch { panel.innerHTML = '<div class="text-[10px] text-slate-600 italic px-1 py-2">No history found yet.</div>'; }
}

// =============================================================================
// 🌐 GUIDED EXTERNAL PORTAL APPLY & ANSWERS MEMORY MODULE
// =============================================================================

let _activeGuidedSessionId = null;
let _guidedPollInterval = null;
let _currentAnswersMemory = {};

async function openAnswersMemoryModal() {
  await loadAnswersMemoryToModal();
  document.getElementById('answers-memory-modal').classList.remove('hidden');
}

function closeAnswersMemoryModal() {
  document.getElementById('answers-memory-modal').classList.add('hidden');
}

async function loadAnswersMemoryToModal() {
  try {
    const resp = await fetch('/api/answers-memory');
    if (!resp.ok) throw new Error('Failed to load answers memory');
    _currentAnswersMemory = await resp.json();
    renderAnswersMemoryList();
  } catch (err) {
    showToast(`❌ Error loading answers memory: ${err.message}`);
  }
}

function renderAnswersMemoryList() {
  const container = document.getElementById('answers-memory-list');
  if (!container) return;
  const entries = Object.entries(_currentAnswersMemory);

  if (entries.length === 0) {
    container.innerHTML = '<div class="text-xs text-slate-500 italic">No answers stored yet. Click + Add Custom Answer below.</div>';
    return;
  }

  container.innerHTML = entries.map(([key, val], idx) => `
    <div class="flex gap-2 items-center">
      <input type="text" value="${key.replace(/"/g, '&quot;')}" onchange="updateMemoryKey(${idx}, this.value)" placeholder="Field Label (e.g. Years of Python)" class="flex-1 bg-[#1E293B] border border-[#334155] rounded-lg text-slate-200 text-xs p-2 focus:outline-none focus:border-rose-500">
      <input type="text" value="${val.replace(/"/g, '&quot;')}" onchange="updateMemoryVal(${idx}, this.value)" placeholder="Stored Answer" class="flex-1 bg-[#1E293B] border border-[#334155] rounded-lg text-slate-200 text-xs p-2 focus:outline-none focus:border-rose-500">
      <button type="button" onclick="removeMemoryRow(${idx})" class="text-slate-500 hover:text-red-400 text-xs font-bold px-1.5">✕</button>
    </div>
  `).join('');
}

function updateMemoryKey(idx, newKey) {
  const entries = Object.entries(_currentAnswersMemory);
  if (!entries[idx]) return;
  const val = entries[idx][1];
  delete _currentAnswersMemory[entries[idx][0]];
  _currentAnswersMemory[newKey] = val;
}

function updateMemoryVal(idx, newVal) {
  const entries = Object.entries(_currentAnswersMemory);
  if (!entries[idx]) return;
  _currentAnswersMemory[entries[idx][0]] = newVal;
}

function addAnswersMemoryRow() {
  _currentAnswersMemory["New Question Label"] = "Answer";
  renderAnswersMemoryList();
}

function removeMemoryRow(idx) {
  const entries = Object.entries(_currentAnswersMemory);
  if (entries[idx]) {
    delete _currentAnswersMemory[entries[idx][0]];
    renderAnswersMemoryList();
  }
}

async function saveAnswersMemoryFromModal() {
  try {
    const resp = await fetch('/api/answers-memory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ memory: _currentAnswersMemory })
    });
    if (!resp.ok) throw new Error('Failed to save memory');
    showToast('💾 Answers memory saved successfully!');
    closeAnswersMemoryModal();
  } catch (err) {
    showToast(`❌ Save error: ${err.message}`);
  }
}

function triggerGuidedApplyForJob(idx) {
  const job = cvState.searchResults?.[idx] || cvState.selectedJob;
  if (!job) return;
  startGuidedApply(job.url, job.company, job.title);
}

async function startGuidedApply(portalUrl, company, jobTitle) {
  const cvData = cvState.tailoredCvData || cvState.parsedCvData;
  if (!cvData) {
    showToast('⚠️ Please upload or parse a CV first');
    return;
  }

  const pdfPath = cvState.tailoredPdfPath || cvState.originalCvPath || '';
  const liAt = document.getElementById('li-at-cookie')?.value || '';

  document.getElementById('guided-modal-company').textContent = `${company} • ${jobTitle}`;
  document.getElementById('guided-status-text').textContent = 'Status: Initializing browser...';
  document.getElementById('guided-last-action').textContent = 'Launching Chromium visible browser session...';
  document.getElementById('guided-paused-container').classList.add('hidden');
  document.getElementById('guided-apply-modal').classList.remove('hidden');

  try {
    const resp = await fetch('/api/guided-apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        portal_url: portalUrl,
        company: company,
        job_title: jobTitle,
        cv_data: cvData,
        pdf_path: pdfPath,
        li_at: liAt
      })
    });

    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Start failed');

    _activeGuidedSessionId = data.session_id;
    showToast(`🌐 Guided Apply session started for ${company}`);
    startGuidedPolling();

  } catch (err) {
    showToast(`❌ Guided apply error: ${err.message}`);
  }
}

function startGuidedPolling() {
  if (_guidedPollInterval) clearInterval(_guidedPollInterval);
  _guidedPollInterval = setInterval(pollGuidedApplyStatus, 2000);
}

async function pollGuidedApplyStatus() {
  if (!_activeGuidedSessionId) return;

  try {
    const resp = await fetch(`/api/guided-apply-status?session_id=${encodeURIComponent(_activeGuidedSessionId)}`);
    if (!resp.ok) return;

    const data = await resp.json();
    document.getElementById('guided-status-text').textContent = `Status: ${data.status.toUpperCase()} (Step ${data.current_step}/${data.total_steps})`;
    document.getElementById('guided-last-action').textContent = data.last_action || 'Processing...';

    if (data.status === 'paused' && data.paused_field) {
      renderGuidedPausedField(data.paused_field);
    } else {
      document.getElementById('guided-paused-container').classList.add('hidden');
    }

    if (data.status === 'completed') {
      clearInterval(_guidedPollInterval);
      showToast(`🎉 Guided Apply completed for ${data.company}!`);
      loadApplicationHistory();
    } else if (data.status === 'failed') {
      clearInterval(_guidedPollInterval);
      showToast(`❌ Guided Apply failed: ${data.last_action}`);
    }

  } catch (err) {
    console.warn("Guided status poll error:", err);
  }
}

function renderGuidedPausedField(pausedField) {
  const container = document.getElementById('guided-paused-container');
  const img = document.getElementById('guided-field-screenshot');
  const labelEl = document.getElementById('guided-field-label');
  const inputWrapper = document.getElementById('guided-field-input-wrapper');

  container.classList.remove('hidden');
  img.src = pausedField.screenshot_b64 || '';
  labelEl.textContent = pausedField.label;

  if (pausedField.field_type === 'captcha') {
    inputWrapper.innerHTML = `
      <p class="text-xs text-rose-300 bg-rose-950/60 p-2.5 rounded-lg border border-rose-800">
        Please complete the CAPTCHA inside the visible Chromium browser window, then click <strong>Resume →</strong> below.
      </p>
    `;
    return;
  }

  if (pausedField.options && pausedField.options.length > 0) {
    inputWrapper.innerHTML = `
      <select id="guided-user-input" class="w-full bg-[#0F172A] border border-[#334155] rounded-lg text-slate-200 text-xs p-2.5 focus:outline-none focus:border-rose-500">
        ${pausedField.options.map(opt => `<option value="${opt.replace(/"/g, '&quot;')}">${opt}</option>`).join('')}
      </select>
    `;
  } else {
    inputWrapper.innerHTML = `
      <input type="text" id="guided-user-input" placeholder="Type your answer..." class="w-full bg-[#0F172A] border border-[#334155] rounded-lg text-slate-200 text-xs p-2.5 focus:outline-none focus:border-rose-500">
    `;
  }
}

async function submitGuidedAnswer() {
  if (!_activeGuidedSessionId) return;

  const labelEl = document.getElementById('guided-field-label');
  const inputEl = document.getElementById('guided-user-input');
  const rememberCheckbox = document.getElementById('guided-remember-checkbox');

  const answer = inputEl ? inputEl.value : 'Done';
  const label = labelEl ? labelEl.textContent : '';
  const remember = rememberCheckbox ? rememberCheckbox.checked : true;

  try {
    const resp = await fetch('/api/answer-field', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: _activeGuidedSessionId,
        field_label: label,
        answer: answer,
        remember: remember
      })
    });

    if (!resp.ok) throw new Error('Failed to submit answer');

    document.getElementById('guided-paused-container').classList.add('hidden');
    showToast('Answer submitted! Resuming session...');

  } catch (err) {
    showToast(`❌ Error submitting answer: ${err.message}`);
  }
}

function closeGuidedApplyModal() {
  if (_guidedPollInterval) clearInterval(_guidedPollInterval);
  document.getElementById('guided-apply-modal').classList.add('hidden');
}


// ---------------------------------------------------------------------------
// Cookie persistence helpers (linkedin li_at session cookie)
// ---------------------------------------------------------------------------

/**
 * On startup: if li-at-cookie input is empty, fetch answers_memory from
 * server and pre-fill from the stored linkedin_li_at_cookie key.
 */
async function syncCookieFromMemory() {
  const input = document.getElementById("li-at-cookie");
  if (!input || input.value.trim()) return; // already has a value
  try {
    const resp = await fetch("/api/answers-memory");
    if (!resp.ok) return;
    const mem = await resp.json();
    const saved = (mem["linkedin_li_at_cookie"] || "").trim();
    if (saved) {
      input.value = saved;
      saveAppStateToCache();
    }
  } catch { /* silently ignore */ }
}

/**
 * When user pastes/types a new li_at cookie value, save it to server-side
 * answers_memory.json so browser automation sessions always find it.
 */
async function persistCookieToMemory() {
  const val = (document.getElementById("li-at-cookie")?.value || "").trim();
  if (!val) return;
  try {
    const resp = await fetch("/api/answers-memory");
    if (!resp.ok) return;
    const mem = await resp.json();
    if (mem["linkedin_li_at_cookie"] === val) return; // no change
    mem["linkedin_li_at_cookie"] = val;
    await fetch("/api/answers-memory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ memory: mem })
    });
  } catch { /* silently ignore */ }
}
