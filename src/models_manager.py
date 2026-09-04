import os
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import errors

CACHE_DIR = "data/cache"
CACHE_FILE = os.path.join(CACHE_DIR, "gemini_models_cache.json")
DEFAULT_CACHE_TTL_SECONDS = 86400  # 24 hours

# Up-to-date fallback model list when offline or unauthenticated
DEFAULT_FALLBACK_MODELS: List[Dict[str, Any]] = [
    # --- Latest & Recommended ---
    {
        "id": "gemini-3.8-flash",
        "name": "models/gemini-3.8-flash",
        "display_name": "Gemini 3.8 Flash",
        "description": "Latest next-generation multimodal model with breakthrough speed and capabilities (Recommended)",
        "is_recommended": True,
        "category": "Latest & Recommended"
    },
    {
        "id": "gemini-3.8-pro",
        "name": "models/gemini-3.8-pro",
        "display_name": "Gemini 3.8 Pro",
        "description": "State-of-the-art reasoning, code analysis, and deep comprehension",
        "is_recommended": True,
        "category": "Latest & Recommended"
    },
    {
        "id": "gemini-3.7-flash",
        "name": "models/gemini-3.7-flash",
        "display_name": "Gemini 3.7 Flash",
        "description": "Fast, balanced performance for agentic workflows and complex reasoning (Recommended)",
        "is_recommended": True,
        "category": "Latest & Recommended"
    },
    {
        "id": "gemini-3.7-pro",
        "name": "models/gemini-3.7-pro",
        "display_name": "Gemini 3.7 Pro",
        "description": "Advanced reasoning, programming, and multimodal processing",
        "is_recommended": True,
        "category": "Latest & Recommended"
    },
    {
        "id": "gemini-2.5-flash",
        "name": "models/gemini-2.5-flash",
        "display_name": "Gemini 2.5 Flash",
        "description": "Fast and versatile production model for high-frequency tasks (Recommended)",
        "is_recommended": True,
        "category": "Latest & Recommended"
    },
    {
        "id": "gemini-2.5-pro",
        "name": "models/gemini-2.5-pro",
        "display_name": "Gemini 2.5 Pro",
        "description": "Mid-tier multimodal model with strong reasoning capabilities",
        "is_recommended": True,
        "category": "Latest & Recommended"
    },

    # --- Gemini 3.5 & 3.0 Series ---
    {
        "id": "gemini-3.5-flash",
        "name": "models/gemini-3.5-flash",
        "display_name": "Gemini 3.5 Flash",
        "description": "High-speed multimodal intelligence",
        "is_recommended": False,
        "category": "Gemini 3.x Series"
    },
    {
        "id": "gemini-3.5-flash-lite",
        "name": "models/gemini-3.5-flash-lite",
        "display_name": "Gemini 3.5 Flash Lite",
        "description": "Fastest and lowest-cost model for high-throughput execution",
        "is_recommended": False,
        "category": "Gemini 3.x Series"
    },
    {
        "id": "gemini-3.5-pro",
        "name": "models/gemini-3.5-pro",
        "display_name": "Gemini 3.5 Pro",
        "description": "Enhanced reasoning and synthesis",
        "is_recommended": False,
        "category": "Gemini 3.x Series"
    },
    {
        "id": "gemini-3.1-pro-preview",
        "name": "models/gemini-3.1-pro-preview",
        "display_name": "Gemini 3.1 Pro Preview",
        "description": "Complex reasoning, programming, and deep research tasks",
        "is_recommended": False,
        "category": "Gemini 3.x Series"
    },
    {
        "id": "gemini-3.0-flash",
        "name": "models/gemini-3.0-flash",
        "display_name": "Gemini 3.0 Flash",
        "description": "Gemini 3.0 generation flash model",
        "is_recommended": False,
        "category": "Gemini 3.x Series"
    },
    {
        "id": "gemini-3.0-pro",
        "name": "models/gemini-3.0-pro",
        "display_name": "Gemini 3.0 Pro",
        "description": "Gemini 3.0 generation pro model",
        "is_recommended": False,
        "category": "Gemini 3.x Series"
    },

    # --- Gemini 2.0 Series ---
    {
        "id": "gemini-2.0-flash",
        "name": "models/gemini-2.0-flash",
        "display_name": "Gemini 2.0 Flash",
        "description": "Second generation flash model",
        "is_recommended": False,
        "category": "Gemini 2.0 Series"
    },
    {
        "id": "gemini-2.0-flash-lite",
        "name": "models/gemini-2.0-flash-lite",
        "display_name": "Gemini 2.0 Flash Lite",
        "description": "Lightweight second generation model",
        "is_recommended": False,
        "category": "Gemini 2.0 Series"
    },
    {
        "id": "gemini-2.0-pro-exp-0205",
        "name": "models/gemini-2.0-pro-exp-0205",
        "display_name": "Gemini 2.0 Pro Experimental",
        "description": "Experimental reasoning model",
        "is_recommended": False,
        "category": "Gemini 2.0 Series"
    },

    # --- Gemini 1.5 Legacy ---
    {
        "id": "gemini-1.5-flash",
        "name": "models/gemini-1.5-flash",
        "display_name": "Gemini 1.5 Flash",
        "description": "First generation fast model with 1M token context",
        "is_recommended": False,
        "category": "Gemini 1.5 Legacy"
    },
    {
        "id": "gemini-1.5-pro",
        "name": "models/gemini-1.5-pro",
        "display_name": "Gemini 1.5 Pro",
        "description": "First generation pro model with 2M token context",
        "is_recommended": False,
        "category": "Gemini 1.5 Legacy"
    },

    # --- Gemma Open Models ---
    {
        "id": "gemma-4-31b-it",
        "name": "models/gemma-4-31b-it",
        "display_name": "Gemma 4 31B",
        "description": "Open weights dense instruction-tuned model (31B parameters)",
        "is_recommended": False,
        "category": "Gemma Open Models"
    },
    {
        "id": "gemma-4-26b-a4b-it",
        "name": "models/gemma-4-26b-a4b-it",
        "display_name": "Gemma 4 26B MoE",
        "description": "Open weights MoE instruction-tuned model (4B active parameters)",
        "is_recommended": False,
        "category": "Gemma Open Models"
    },
    {
        "id": "gemma-3-27b-it",
        "name": "models/gemma-3-27b-it",
        "display_name": "Gemma 3 27B",
        "description": "Third generation open instruction model (27B parameters)",
        "is_recommended": False,
        "category": "Gemma Open Models"
    },
    {
        "id": "gemma-3-12b-it",
        "name": "models/gemma-3-12b-it",
        "display_name": "Gemma 3 12B",
        "description": "Third generation compact open instruction model (12B parameters)",
        "is_recommended": False,
        "category": "Gemma Open Models"
    },
    {
        "id": "gemma-2-27b-it",
        "name": "models/gemma-2-27b-it",
        "display_name": "Gemma 2 27B",
        "description": "Second generation open instruction model (27B parameters)",
        "is_recommended": False,
        "category": "Gemma Open Models"
    },
    {
        "id": "gemma-2-9b-it",
        "name": "models/gemma-2-9b-it",
        "display_name": "Gemma 2 9B",
        "description": "Second generation high-efficiency open model (9B parameters)",
        "is_recommended": False,
        "category": "Gemma Open Models"
    }
]

RECOMMENDED_MODEL_IDS = {
    "gemini-3.8-flash",
    "gemini-3.8-pro",
    "gemini-3.7-flash",
    "gemini-3.7-pro",
    "gemini-2.5-flash",
    "gemini-2.5-pro"
}

def clean_model_id(raw_name: str) -> str:
    """Normalize model resource name to plain model identifier."""
    if not raw_name:
        return ""
    if raw_name.startswith("models/"):
        return raw_name[len("models/"):]
    if "/" in raw_name:
        return raw_name.split("/")[-1]
    return raw_name

def is_generative_model(model_obj: Any) -> bool:
    """Check if model supports content generation suitable for CV tailoring."""
    name = getattr(model_obj, "name", "") or ""
    clean_id = clean_model_id(name).lower()
    
    # Exclude embeddings, vision-only, aqa, and image/video generators
    excluded_keywords = [
        "embedding", "embedcontent", "aqa", "imagen", "veo",
        "native-multimodal", "bison", "chat-bison", "text-bison",
        "transcribe"
    ]
    if any(k in clean_id for k in excluded_keywords):
        return False
        
    supported_actions = getattr(model_obj, "supported_actions", None) or []
    if supported_actions and "generateContent" not in supported_actions:
        return False
        
    return clean_id.startswith("gemini") or clean_id.startswith("gemma")

def categorize_model(model_id: str, is_recommended: bool) -> str:
    """Assign human-readable category for UI grouping."""
    if is_recommended or model_id in RECOMMENDED_MODEL_IDS:
        return "Latest & Recommended"
    mid = model_id.lower()
    if "gemma" in mid:
        return "Gemma Open Models"
    if "3.8" in mid or "3.7" in mid:
        return "Gemini 3.8 / 3.7 Series"
    if "3.5" in mid or "3.1" in mid or "3.0" in mid:
        return "Gemini 3.x Series"
    if "2.5" in mid:
        return "Gemini 2.5 Series"
    if "2.0" in mid:
        return "Gemini 2.0 Series"
    if "1.5" in mid:
        return "Gemini 1.5 Legacy"
    if "lite" in mid or "flash" in mid:
        return "Flash & High-Throughput"
    if "pro" in mid or "preview" in mid:
        return "Reasoning & Previews"
    return "All Available Google Models"

def format_model_dict(model_obj: Any) -> Dict[str, Any]:
    """Convert Google GenAI model object into standardized frontend dict."""
    raw_name = getattr(model_obj, "name", "")
    model_id = clean_model_id(raw_name)
    display_name = getattr(model_obj, "display_name", "") or model_id.replace("-", " ").title()
    description = getattr(model_obj, "description", "") or "Google Generative AI Model"
    
    is_rec = model_id in RECOMMENDED_MODEL_IDS
    category = categorize_model(model_id, is_rec)
    
    return {
        "id": model_id,
        "name": raw_name,
        "display_name": display_name,
        "description": description,
        "is_recommended": is_rec,
        "category": category,
        "input_token_limit": getattr(model_obj, "input_token_limit", None),
        "output_token_limit": getattr(model_obj, "output_token_limit", None)
    }

def read_models_cache(ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> Optional[Dict[str, Any]]:
    """Read cached models from disk if file exists and has not expired."""
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            timestamp = data.get("timestamp", 0)
            if (time.time() - timestamp) <= ttl_seconds:
                return data
    except Exception as e:
        print(f"[models_manager] Warning: Failed to read models cache: {e}")
    return None

def write_models_cache(models: List[Dict[str, Any]], source: str = "google_api") -> None:
    """Persist fetched models list to local JSON cache."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        data = {
            "timestamp": time.time(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "models": models
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[models_manager] Warning: Failed to write models cache: {e}")

def fetch_gemini_models_from_google(api_key: str) -> List[Dict[str, Any]]:
    """
    Connect to Google Generative AI API using the google-genai SDK
    and retrieve the live list of models.
    """
    if not api_key:
        raise ValueError("No Gemini API key provided.")
        
    client = genai.Client(api_key=api_key)
    # Fetch base models
    pager = client.models.list(config={"page_size": 100})
    raw_models = list(pager)
    
    # Filter for generative models suitable for CV tailoring
    valid_models = [m for m in raw_models if is_generative_model(m)]
    live_formatted = [format_model_dict(m) for m in valid_models]
    
    # Merge live models with default catalog so all known and new models are present
    live_ids = {m["id"] for m in live_formatted}
    combined = list(live_formatted)
    for default_m in DEFAULT_FALLBACK_MODELS:
        if default_m["id"] not in live_ids:
            combined.append(default_m)
            
    category_order = [
        "Latest & Recommended",
        "Gemini 3.8 / 3.7 Series",
        "Gemini 3.x Series",
        "Gemini 2.5 Series",
        "Gemini 2.0 Series",
        "Gemini 1.5 Legacy",
        "Gemma Open Models",
        "Flash & High-Throughput",
        "Reasoning & Previews",
        "All Available Google Models"
    ]
    def sort_key(m):
        rec_rank = 0 if m.get("is_recommended") else 1
        cat = m.get("category", "")
        cat_rank = category_order.index(cat) if cat in category_order else 99
        return (rec_rank, cat_rank, m.get("id", ""))

    combined.sort(key=sort_key)
    return combined

def get_available_gemini_models(
    api_key: Optional[str] = None,
    force_refresh: bool = False,
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
) -> Dict[str, Any]:
    """
    Main orchestrator function:
    1. If not force_refresh, check local disk cache first.
    2. If cache invalid/expired or force_refresh requested, attempt live fetch from Google API.
    3. On success, update disk cache and return live list.
    4. On failure or missing key, gracefully fall back to existing cache or default model catalog.
    """
    resolved_key = (api_key or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    
    # 1. Return cached if still valid and not forcing a refresh
    if not force_refresh:
        cached = read_models_cache(ttl_seconds=ttl_seconds)
        if cached and cached.get("models"):
            return {
                "success": True,
                "source": "cache",
                "last_updated": cached.get("last_updated"),
                "models": cached["models"],
                "total": len(cached["models"])
            }
            
    # 2. Attempt live query to Google if key is available
    if resolved_key and resolved_key != "your_gemini_api_key_here":
        try:
            live_models = fetch_gemini_models_from_google(resolved_key)
            if live_models:
                write_models_cache(live_models, source="google_api")
                return {
                    "success": True,
                    "source": "google_api",
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "models": live_models,
                    "total": len(live_models)
                }
        except Exception as e:
            print(f"[models_manager] Live model fetch failed: {e}. Falling back to cache/default.")
            
    # 3. Fallback to existing cache even if expired
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("models"):
                    return {
                        "success": True,
                        "source": "expired_cache",
                        "last_updated": data.get("last_updated"),
                        "models": data["models"],
                        "total": len(data["models"]),
                        "notice": "Using previously cached models (Google API not reachable or key invalid)"
                    }
        except Exception:
            pass

    # 4. Fallback to curated default catalog
    return {
        "success": True,
        "source": "default",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "models": DEFAULT_FALLBACK_MODELS,
        "total": len(DEFAULT_FALLBACK_MODELS),
        "notice": "Using standard default model list. Enter a valid Gemini API key to query your live Google account."
    }
