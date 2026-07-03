"""Add a new LLM provider without changing core code.

Subclass the OpenAI-compatible base, declare static attributes, and decorate with
`@register_provider` — importing the module registers the adapter. Run inside the
backend environment:

    cd backend && source .venv/bin/activate
    python ../examples/08_custom_provider.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def main() -> None:
    from app.providers.base import Capability
    from app.providers.adapters.openai_compatible import OpenAICompatibleProvider
    from app.providers.registry import provider_registry, register_provider

    @register_provider
    class MyProvider(OpenAICompatibleProvider):
        name = "my-provider"
        base_url = "https://api.my-provider.com/v1"
        api_key_env = "MYPROVIDER_API_KEY"
        default_model = "my-model-large"
        models = ["my-model-large", "my-model-small"]
        capabilities = {Capability.CHAT, Capability.STREAMING, Capability.EMBEDDING}
        pricing = {"my-model-large": (0.005, 0.015)}  # (input, output) USD / 1k

    info = provider_registry.info("my-provider")
    print("Registered provider:", info.name)
    print("  kind:        ", info.kind)
    print("  capabilities:", info.capabilities)
    print("  models:      ", info.models)
    print("  default:     ", info.default_model)
    print("\nAll registered providers:", provider_registry.names())


if __name__ == "__main__":
    main()
