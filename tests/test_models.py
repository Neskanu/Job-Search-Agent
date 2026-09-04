import os
import json
import time
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from src.main import app
from src.models_manager import (
    get_available_gemini_models,
    is_generative_model,
    clean_model_id,
    categorize_model,
    format_model_dict,
    read_models_cache,
    write_models_cache,
    DEFAULT_FALLBACK_MODELS,
    CACHE_FILE
)

@pytest.fixture
def client():
    return TestClient(app)

def test_clean_model_id():
    assert clean_model_id("models/gemini-2.5-flash") == "gemini-2.5-flash"
    assert clean_model_id("publishers/google/models/gemini-2.5-pro") == "gemini-2.5-pro"
    assert clean_model_id("gemini-3.7-flash") == "gemini-3.7-flash"
    assert clean_model_id("") == ""

def test_is_generative_model():
    # Valid generation models
    m1 = MagicMock(name="models/gemini-2.5-flash", supported_actions=["generateContent"])
    m1.name = "models/gemini-2.5-flash"
    assert is_generative_model(m1) is True

    m2 = MagicMock(name="models/gemma-4-31b-it", supported_actions=["generateContent"])
    m2.name = "models/gemma-4-31b-it"
    assert is_generative_model(m2) is True

    # Invalid / embedding / non-text models
    m3 = MagicMock(name="models/text-embedding-004", supported_actions=["embedContent"])
    m3.name = "models/text-embedding-004"
    assert is_generative_model(m3) is False

    m4 = MagicMock(name="models/imagen-3.0-generate-002", supported_actions=["generateImages"])
    m4.name = "models/imagen-3.0-generate-002"
    assert is_generative_model(m4) is False

    m5 = MagicMock(name="models/gemini-2.5-flash", supported_actions=["countTokens"])
    m5.name = "models/gemini-2.5-flash"
    assert is_generative_model(m5) is False

def test_categorize_model():
    assert categorize_model("gemini-3.8-flash", is_recommended=True) == "Latest & Recommended"
    assert categorize_model("gemini-2.5-flash", is_recommended=True) == "Latest & Recommended"
    assert categorize_model("gemini-3.5-flash-lite", is_recommended=False) == "Gemini 3.x Series"
    assert categorize_model("gemini-2.0-flash", is_recommended=False) == "Gemini 2.0 Series"
    assert categorize_model("gemini-1.5-pro", is_recommended=False) == "Gemini 1.5 Legacy"
    assert categorize_model("gemma-4-31b-it", is_recommended=False) == "Gemma Open Models"

def test_default_fallback_models(tmp_path):
    with patch("src.models_manager.CACHE_FILE", str(tmp_path / "cache.json")):
        res = get_available_gemini_models(api_key=None, force_refresh=True)
        assert res["success"] is True
        assert len(res["models"]) >= 15
        model_ids = [m["id"] for m in res["models"]]
        assert "gemini-3.8-flash" in model_ids
        assert "gemini-3.8-pro" in model_ids
        assert "gemini-3.7-flash" in model_ids
        assert "gemini-2.5-flash" in model_ids
        assert "gemini-2.5-pro" in model_ids

def test_caching_mechanism(tmp_path):
    test_models = [
        {"id": "test-model-1", "name": "models/test-model-1", "display_name": "Test Model 1", "is_recommended": True, "category": "Latest & Recommended"}
    ]
    
    with patch("src.models_manager.CACHE_FILE", str(tmp_path / "test_cache.json")):
        # Initially no cache
        assert read_models_cache() is None
        
        # Write cache
        write_models_cache(test_models, source="test")
        cached = read_models_cache(ttl_seconds=60)
        assert cached is not None
        assert cached["source"] == "test"
        assert len(cached["models"]) == 1
        assert cached["models"][0]["id"] == "test-model-1"
        
        # Expired cache
        assert read_models_cache(ttl_seconds=-1) is None

def test_fetch_gemini_models_mock(tmp_path):
    mock_model_1 = MagicMock()
    mock_model_1.name = "models/gemini-2.5-flash"
    mock_model_1.display_name = "Gemini 2.5 Flash Live"
    mock_model_1.description = "Live flash model"
    mock_model_1.supported_actions = ["generateContent"]
    mock_model_1.input_token_limit = 1000000
    mock_model_1.output_token_limit = 8192

    mock_model_2 = MagicMock()
    mock_model_2.name = "models/gemini-embedding-001"
    mock_model_2.display_name = "Embedding"
    mock_model_2.description = "Embeddings only"
    mock_model_2.supported_actions = ["embedContent"]

    with patch("src.models_manager.CACHE_FILE", str(tmp_path / "cache.json")):
        with patch("src.models_manager.genai.Client") as mock_client_cls:
            mock_client_instance = MagicMock()
            mock_client_instance.models.list.return_value = [mock_model_1, mock_model_2]
            mock_client_cls.return_value = mock_client_instance

            res = get_available_gemini_models(api_key="dummy_valid_key", force_refresh=True)
            assert res["success"] is True
            assert res["source"] == "google_api"
            # Embedding model is excluded, live model 1 is merged with catalog
            matching = [m for m in res["models"] if m["id"] == "gemini-2.5-flash"]
            assert len(matching) == 1
            assert matching[0]["display_name"] == "Gemini 2.5 Flash Live"
            assert not any(m["id"] == "gemini-embedding-001" for m in res["models"])

def test_api_models_gemini_endpoints(client, tmp_path):
    with patch("src.models_manager.CACHE_FILE", str(tmp_path / "cache.json")):
        # GET test
        res_get = client.get("/api/models/gemini")
        assert res_get.status_code == 200
        data_get = res_get.json()
        assert data_get["success"] is True
        assert "models" in data_get
        assert len(data_get["models"]) > 0

        # POST test
        res_post = client.post("/api/models/gemini", json={"api_key": "", "force_refresh": False})
        assert res_post.status_code == 200
        data_post = res_post.json()
        assert data_post["success"] is True
        assert "models" in data_post
        assert len(data_post["models"]) > 0
