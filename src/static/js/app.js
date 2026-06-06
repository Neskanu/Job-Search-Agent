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
  tailoredCvData: null,
  tailoredDocxPath: null,
  tailoredPdfPath: null,
  theme: "minimalist",
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
  const provider = document.getElementById("llm-provider").value;
  if (provider === "gemini") {
    document.getElementById("gemini-inputs").classList.remove("hidden");
    document.getElementById("ollama-inputs").classList.add("hidden");
  } else {
    document.getElementById("gemini-inputs").classList.add("hidden");
    document.getElementById("ollama-inputs").classList.remove("hidden");
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
    
    statusText.innerText = "Upload CV (PDF/DOCX)";
    showToast("CV uploaded and parsed successfully!");
    checkTailorEnable();
  } catch (err) {
    statusText.innerText = "Upload CV (PDF/DOCX)";
    alert(`Upload Error: ${err.message}`);
  }
}

/**
 * Search jobs on LinkedIn via Playwright scraper API.
 */
async function searchJobs() {
  const keywords = document.getElementById("search-keywords").value;
  const location = document.getElementById("search-location").value;
  const limit = parseInt(document.getElementById("search-limit").value);
  const cookie = document.getElementById("li-at-cookie").value;

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

    // Render job cards list
    data.jobs.forEach((job, idx) => {
      const card = document.createElement("div");
      card.className = "bg-[#0F172A] border border-[#334155] rounded-xl p-4 space-y-2 relative";
      card.innerHTML = `
        <div class="text-xs font-bold text-slate-100">${job.title}</div>
        <div class="text-[11px] text-rose-400 font-medium">🏢 ${job.company}</div>
        <div class="text-[10px] text-slate-500">📍 ${job.location}</div>
        <div class="flex justify-between items-center mt-2 border-t border-[#1E293B] pt-2">
          <a href="${job.url}" target="_blank" class="text-[10px] text-slate-400 hover:underline">View Post 🔗</a>
          <button onclick='selectJob(${JSON.stringify(job)})' class="bg-rose-600 hover:bg-rose-700 text-white font-bold text-[10px] px-3 py-1 rounded">Select Job</button>
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
  const url = document.getElementById("direct-job-url").value;
  const cookie = document.getElementById("li-at-cookie").value;
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
    
    showToast("Job details fetched successfully!");
  } catch (err) {
    alert(`Fetch Error: ${err.message}`);
  }
}

/**
 * Select the job filled in manual form fields as target.
 */
function selectManualJob() {
  const title = document.getElementById("job-title").value;
  const company = document.getElementById("job-company").value;
  const desc = document.getElementById("job-desc").value;
  const url = document.getElementById("direct-job-url").value || "Direct Entry";

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

/**
 * Select target job and update console selection state.
 */
function selectJob(job) {
  cvState.selectedJob = job;
  
  document.getElementById("banner-job-title").innerText = job.title;
  document.getElementById("banner-job-company").innerText = job.company;
  document.getElementById("target-selection-banner").classList.remove("hidden");
  
  showToast(`Selected Target: ${job.title} at ${job.company}`);
  checkTailorEnable();
}

/**
 * Enable/Disable tailoring orchestrator button based on upload and target state.
 */
function checkTailorEnable() {
  const btn = document.getElementById("btn-tailor-cv");
  if (cvState.originalCvPath && cvState.selectedJob) {
    btn.removeAttribute("disabled");
  } else {
    btn.setAttribute("disabled", "true");
  }
}

/**
 * Trigger CV tailoring LLM agent pipeline.
 */
async function tailorResume() {
  if (!cvState.originalCvPath || !cvState.selectedJob) return;

  const provider = document.getElementById("llm-provider").value;
  const additionalInfo = document.getElementById("additional-info").value;

  // Compile LLM parameters
  let llmConfig = {};
  if (provider === "gemini") {
    const key = document.getElementById("gemini-key").value;
    const model = document.getElementById("gemini-model").value;
    llmConfig = {
      gemini_api_key: key || null,
      gemini_model: model
    };
  } else {
    const url = document.getElementById("ollama-url").value;
    const model = document.getElementById("ollama-model").value;
    llmConfig = {
      ollama_url: url,
      ollama_model: model
    };
  }

  const btn = document.getElementById("btn-tailor-cv");
  const btnText = btn.querySelector("span");
  btn.setAttribute("disabled", "true");
  btnText.innerText = "Tailoring Resume (10-30s)...";

  try {
    const response = await fetch("/api/tailor-cv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        original_cv_path: cvState.originalCvPath,
        job_description_text: cvState.selectedJob.description,
        job_title: cvState.selectedJob.title,
        company: cvState.selectedJob.company,
        provider: provider,
        llm_config: llmConfig,
        additional_info: additionalInfo || null
      })
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Tailoring failed.");

    // Update global state with tailored data and file locations
    cvState.tailoredCvData = data.cv_data;
    cvState.tailoredDocxPath = data.docx_path;
    cvState.tailoredPdfPath = data.pdf_path;

    // Render WYSIWYG canvas
    renderWYSIWYG(data.cv_data);

    // Show download bar and resume page sheet, hide empty state placeholder
    document.getElementById("download-actions-bar").classList.remove("hidden");
    document.getElementById("resume-sheet").classList.remove("hidden");
    document.getElementById("cv-empty-placeholder").classList.add("hidden");

    showToast("CV tailored successfully! PDF/Word files generated.");
    refreshPDFPreview();
  } catch (err) {
    alert(`Tailoring Error: ${err.message}`);
  } finally {
    btnText.innerText = "Optimize Resume for Role";
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

  // Sync style theme classes on resume-sheet
  const sheet = document.getElementById("resume-sheet");
  if (sheet) {
    const classesToRemove = Array.from(sheet.classList).filter(cls => cls.startsWith("theme-"));
    classesToRemove.forEach(cls => sheet.classList.remove(cls));
    const selectedTheme = document.getElementById("cv-theme-select").value || "minimalist";
    sheet.classList.add(`theme-${selectedTheme}`);
    cvState.theme = selectedTheme;
  }

  // Set photo if available
  const photoImg = document.getElementById("cv-photo");
  const removeBtn = document.getElementById("btn-remove-photo");
  if (photoImg) {
    if (cvData.photo) {
      photoImg.src = cvData.photo;
      cvState.photo = cvData.photo;
      if (removeBtn) removeBtn.classList.remove("hidden");
    } else {
      photoImg.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 100 100'><rect width='100' height='100' fill='%23F1F5F9'/><text x='50%' y='55%' font-family='Arial' font-size='12' fill='%2394A3B8' text-anchor='middle'>Add Photo</text></svg>";
      cvState.photo = null;
      if (removeBtn) removeBtn.classList.add("hidden");
    }
  }

  // Set Name
  document.getElementById("cv-name").innerText = cvData.name || "Your Name";

  // Set Contact Header
  const contactText = Array.isArray(cvData.contact_info) ? cvData.contact_info.join("  |  ") : (cvData.contact_info || "");
  document.getElementById("cv-contact").innerText = contactText;

  // Set Sections
  const listContainer = document.getElementById("sections-list");
  listContainer.innerHTML = "";

  if (Array.isArray(cvData.sections)) {
    cvData.sections.forEach((sec, sIdx) => {
      const secEl = document.createElement("div");
      secEl.className = "draggable-section group/section";
      secEl.setAttribute("data-type", sec.type || "text");
      
      let contentHTML = "";

      if (sec.type === "text") {
        contentHTML = `<div class="sec-content text-sm text-slate-600 leading-relaxed outline-none" contenteditable="true">${sec.content || ""}</div>`;
      } 
      else if (sec.type === "list") {
        const listVal = Array.isArray(sec.content) ? sec.content.join(", ") : (sec.content || "");
        contentHTML = `<div class="sec-content text-sm text-slate-600 font-medium outline-none" contenteditable="true">${listVal}</div>`;
      } 
      else if (sec.type === "experience" || sec.type === "education") {
        contentHTML = `<div class="sec-content space-y-4">`;
        if (Array.isArray(sec.content)) {
          sec.content.forEach((item, itemIdx) => {
            const isExp = sec.type === "experience";
            const titleVal = isExp ? (item.role || "Role") : (item.degree || "Degree");
            const subTitleVal = isExp ? (item.company || "Company") : (item.institution || "Institution");
            const period = item.period || "";
            const location = item.location || "";

            // Bullets List
            let bulletsHTML = `<ul class="list-disc pl-5 mt-1.5 space-y-1 text-xs text-slate-500 font-normal">`;
            if (Array.isArray(item.bullets)) {
              item.bullets.forEach((bullet, bIdx) => {
                bulletsHTML += `
                  <li class="bullet-item relative group/bullet pr-8">
                    <span contenteditable="true" class="bullet-text block outline-none">${bullet}</span>
                    <button onclick="deleteBullet(this)" class="absolute right-0 top-0.5 hidden group-hover/bullet:block text-[10px] text-red-500 font-bold hover:underline">Delete</button>
                  </li>`;
              });
            }
            bulletsHTML += `</ul>`;

            contentHTML += `
              <div class="item-block border-l-2 border-slate-100 pl-3 relative group/item" data-idx="${itemIdx}">
                <div class="flex justify-between items-baseline">
                  <div class="text-sm font-semibold text-slate-800">
                    <span contenteditable="true" class="item-title outline-none">${titleVal}</span>
                    <span class="text-slate-400 font-normal"> at </span>
                    <span contenteditable="true" class="item-sub-title italic font-medium text-slate-700 outline-none">${subTitleVal}</span>
                  </div>
                  <div class="text-[11px] text-slate-400 font-medium text-right">
                    <span contenteditable="true" class="item-period outline-none">${period}</span>
                    ${location ? ` | <span contenteditable="true" class="item-location outline-none">${location}</span>` : `<span contenteditable="true" class="item-location outline-none hidden"></span>`}
                  </div>
                </div>
                ${bulletsHTML}
                
                <!-- Inner Actions inside Experience Item -->
                <div class="flex gap-3 mt-1.5">
                  <button onclick="addBullet(this)" class="text-[10px] text-rose-500 font-semibold hover:underline">+ Add Bullet</button>
                  <button onclick="deleteItemBlock(this)" class="text-[10px] text-red-400 font-semibold hover:underline">🗑️ Delete Block</button>
                </div>
              </div>`;
          });
        }
        contentHTML += `</div>`;
        
        // Append "+ Add Block" button for list blocks (always visible)
        contentHTML += `
          <div class="mt-3 flex gap-2">
            <button onclick="addBlockItem(this, '${sec.type}')" class="inline-flex items-center gap-1 text-[11px] bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold px-3 py-1.5 rounded-lg border border-slate-200 shadow-sm transition-all hover:scale-105 active:scale-95">
              ➕ Add ${sec.type === 'experience' ? 'Job Position' : 'Education Item'}
            </button>
          </div>`;
      }

      // Build section wrapper HTML containing sortable handles and Delete Section button (always visible)
      secEl.innerHTML = `
        <div class="drag-handle">☰</div>
        <div class="flex justify-between items-center border-b border-slate-100 pb-1 mb-2">
          <h2 contenteditable="true" class="sec-title text-sm font-bold text-slate-900 tracking-wide uppercase outline-none">${sec.title || "Section"}</h2>
          <button onclick="deleteSection(this)" class="text-[10px] text-red-500 font-semibold hover:underline transition-opacity">Delete Section 🗑️</button>
        </div>
        ${contentHTML}
      `;
      listContainer.appendChild(secEl);
    });
  }

  // Initialize SortableJS for dragging & reordering sections
  new Sortable(listContainer, {
    handle: '.drag-handle',
    ghostClass: 'ghost-class',
    animation: 180
  });
}

/**
 * Change the layout style theme of the resume preview.
 * Swaps CSS classes on the sheet wrapper and auto-saves the new layout.
 */
function changeCVTheme() {
  const themeSelect = document.getElementById("cv-theme-select");
  if (!themeSelect) return;
  
  const selectedTheme = themeSelect.value;
  cvState.theme = selectedTheme;
  
  const sheet = document.getElementById("resume-sheet");
  if (sheet) {
    const classesToRemove = Array.from(sheet.classList).filter(cls => cls.startsWith("theme-"));
    classesToRemove.forEach(cls => sheet.classList.remove(cls));
    sheet.classList.add(`theme-${selectedTheme}`);
  }
  
  // Automatically trigger save and compile in the background
  if (cvState.tailoredCvData) {
    saveAndCompile();
  }
}

// ==========================================
// ➕ INLINE DYNAMIC CV EDIT INTERACTIONS
// ==========================================

function addBullet(btn) {
  const ul = btn.closest('.item-block').querySelector('ul');
  const li = document.createElement('li');
  li.className = 'bullet-item relative group/bullet pr-8';
  li.innerHTML = `
    <span contenteditable="true" class="bullet-text block outline-none">New bullet point. Click to customize.</span>
    <button onclick="deleteBullet(this)" class="absolute right-0 top-0.5 hidden group-hover/bullet:block text-[10px] text-red-500 font-bold hover:underline">Delete</button>
  `;
  ul.appendChild(li);
  saveAndCompile();
}

function deleteBullet(btn) {
  btn.closest('li').remove();
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

/**
 * Scrape all edits from the WYSIWYG DOM nodes, compile them back into JSON,
 * and hit generate-docs API to regenerate PDF & Word files.
 */
async function saveAndCompile() {
  if (!cvState.tailoredCvData) return;

  const name = document.getElementById("cv-name").innerText.trim();
  const contactRaw = document.getElementById("cv-contact").innerText.trim();
  const contact_info = contactRaw.split("|").map(s => s.trim()).filter(s => s.length > 0);

  const sections = [];
  document.querySelectorAll(".draggable-section").forEach(secEl => {
    const title = secEl.querySelector(".sec-title").innerText.trim();
    const type = secEl.getAttribute("data-type");
    let content = null;

    if (type === "text") {
      content = secEl.querySelector(".sec-content").innerText.trim();
    } 
    else if (type === "list") {
      const listRaw = secEl.querySelector(".sec-content").innerText.trim();
      content = listRaw.split(",").map(s => s.trim()).filter(s => s.length > 0);
    } 
    else if (type === "experience" || type === "education") {
      content = [];
      secEl.querySelectorAll(".item-block").forEach(itemEl => {
        const item = {
          period: itemEl.querySelector(".item-period").innerText.trim()
        };

        const locEl = itemEl.querySelector(".item-location");
        if (locEl && locEl.innerText.trim().length > 0) {
          item.location = locEl.innerText.trim();
        }

        if (type === "experience") {
          item.role = itemEl.querySelector(".item-title").innerText.trim();
          item.company = itemEl.querySelector(".item-sub-title").innerText.trim();
        } else {
          item.degree = itemEl.querySelector(".item-title").innerText.trim();
          item.institution = itemEl.querySelector(".item-sub-title").innerText.trim();
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

  const updatedCv = {
    name: name,
    contact_info: contact_info,
    photo: cvState.photo || null,
    sections: sections
  };

  showToast("Rebuilding documents...");

  try {
    // Send updated JSON to compile documents
    const response = await fetch("/api/generate-docs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cv_data: updatedCv,
        job_title: cvState.selectedJob.title,
        company: cvState.selectedJob.company,
        theme: cvState.theme
      })
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Regeneration failed.");

    // Update file paths in state
    cvState.tailoredCvData = updatedCv;
    cvState.tailoredDocxPath = data.docx_path;
    cvState.tailoredPdfPath = data.pdf_path;

    showToast("Rebuilt Word & PDF outputs successfully!");
    refreshPDFPreview();
  } catch (err) {
    alert(`Save Error: ${err.message}`);
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
  newItem.className = "item-block border-l-2 border-slate-100 pl-3 relative group/item mt-4";
  
  const isExp = type === "experience";
  const titleVal = isExp ? "Job Title / Role" : "Degree / Certificate";
  const subTitleVal = isExp ? "Company Name" : "Institution Name";
  
  newItem.innerHTML = `
    <div class="flex justify-between items-baseline">
      <div class="text-sm font-semibold text-slate-800">
        <span contenteditable="true" class="item-title outline-none">${titleVal}</span>
        <span class="text-slate-400 font-normal"> at </span>
        <span contenteditable="true" class="item-sub-title italic font-medium text-slate-700 outline-none">${subTitleVal}</span>
      </div>
      <div class="text-[11px] text-slate-400 font-medium text-right">
        <span contenteditable="true" class="item-period outline-none">2024 - Present</span>
        <span contenteditable="true" class="item-location outline-none"> | Location</span>
      </div>
    </div>
    <ul class="list-disc pl-5 mt-1.5 space-y-1 text-xs text-slate-500 font-normal">
      <li class="bullet-item relative group/bullet pr-8">
        <span contenteditable="true" class="bullet-text block outline-none">Describe your impact or responsibilities.</span>
        <button onclick="deleteBullet(this)" class="absolute right-0 top-0.5 hidden group-hover/bullet:block text-[10px] text-red-500 font-bold hover:underline">Delete</button>
      </li>
    </ul>
    <div class="flex gap-3 mt-1.5">
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
    iframe.src = `/api/download?path=${encodeURIComponent(cvState.tailoredPdfPath)}&t=${Date.now()}#toolbar=0&navpanes=0`;
  } else {
    iframe.src = "about:blank";
  }
}

// Initialize default view mode on load
document.addEventListener("DOMContentLoaded", () => {
  const savedMode = localStorage.getItem("cv_view_mode") || "edit";
  setViewMode(savedMode);
});
