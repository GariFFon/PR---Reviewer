from prreviewer.config import Settings
from prreviewer.llm.client import LLMClient


def test_client_constructs_with_no_api_key_configured():
    """Regression: the OpenAI SDK raises eagerly on an empty api_key. A missing
    LLM_API_KEY must not crash the worker at startup — it should only fail
    (and gracefully degrade) on the first real call."""
    settings = Settings(llm_api_key="", github_app_id="x", github_webhook_secret="x")
    client = LLMClient(settings)
    assert client is not None
