"""Azure OpenAI provider adapter.

Azure uses a deployment-based URL scheme and an ``api-key`` header rather than a
bearer token, so it overrides URL construction and auth while reusing the
OpenAI-compatible request/response handling for everything else.
"""
import os
from typing import Optional

from ..base import Capability
from ..http import HttpClient
from ..registry import register_provider
from .openai_compatible import OpenAICompatibleProvider


@register_provider
class AzureOpenAIProvider(OpenAICompatibleProvider):
    name = "azure-openai"
    api_key_env = "AZURE_OPENAI_API_KEY"
    #: Azure resource endpoint, e.g. ``https://my-resource.openai.azure.com``.
    base_url_env = "AZURE_OPENAI_ENDPOINT"
    base_url = "https://YOUR-RESOURCE.openai.azure.com"
    default_model = "gpt-4o-mini"
    embedding_model = "text-embedding-3-small"
    capabilities = {
        Capability.CHAT,
        Capability.STREAMING,
        Capability.EMBEDDING,
        Capability.TOOLS,
        Capability.VISION,
        Capability.JSON_MODE,
    }
    models = ["gpt-4o", "gpt-4o-mini", "gpt-35-turbo", "text-embedding-3-small"]
    pricing = {
        "gpt-4o": (0.0025, 0.01),
        "gpt-4o-mini": (0.00015, 0.0006),
        "gpt-35-turbo": (0.0005, 0.0015),
        "text-embedding-3-small": 0.00002,
    }

    def __init__(self, *args, api_version: Optional[str] = None, http_client: Optional[HttpClient] = None, **kwargs) -> None:
        super().__init__(*args, http_client=http_client, **kwargs)
        self.api_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")

    def _auth_headers(self) -> dict:
        headers = dict(self.extra_headers)
        if self.api_key:
            headers["api-key"] = self.api_key
        return headers

    def _chat_url(self, model: str) -> str:
        return f"{self.base_url}/openai/deployments/{model}/chat/completions?api-version={self.api_version}"

    def _embeddings_url(self, model: str) -> str:
        return f"{self.base_url}/openai/deployments/{model}/embeddings?api-version={self.api_version}"

    def _models_url(self) -> str:
        return f"{self.base_url}/openai/models?api-version={self.api_version}"

    def _payload_model(self, model: str) -> dict:
        # The deployment is encoded in the URL, so the body omits "model".
        return {}
