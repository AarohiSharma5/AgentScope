# Providers

The provider abstraction gives AgentScope a **vendor-neutral** interface to
external services. You can add new providers without changing any core code —
adapters self-register into a registry, and capabilities are discoverable at
runtime.

## Provider kinds

| Interface | Kind | Purpose |
| --------- | ---- | ------- |
| `LLMProvider` | `llm` | Chat/completions and (optionally) embeddings. |
| `EmbeddingProvider` | `embedding` | Text embeddings. |
| `RetrieverProvider` | `retriever` | Vector search / knowledge lookup. |
| `MemoryProvider` | `memory` | Conversational/long-term memory. |
| `ToolProvider` | `tool` | Callable tools. |

## Built-in adapters

Nine LLM adapters ship built-in. Most speak the OpenAI-compatible wire format via
a shared base (`OpenAICompatibleProvider`); Anthropic and Gemini have bespoke
adapters.

| Provider | Registry name | Notes |
| -------- | ------------- | ----- |
| OpenAI | `openai` | Chat, stream, embeddings. |
| Anthropic | `anthropic` | Bespoke Messages API adapter. |
| Google Gemini | `google-gemini` | Bespoke `generateContent` adapter. |
| Azure OpenAI | `azure-openai` | Deployment-based URLs + `api-key` auth. |
| Groq | `groq` | OpenAI-compatible. |
| DeepSeek | `deepseek` | OpenAI-compatible. |
| Mistral | `mistral` | OpenAI-compatible. |
| OpenRouter | `openrouter` | OpenAI-compatible gateway. |
| Ollama | `ollama` | Local models; no API key required. |

## The provider interface

Every provider exposes a consistent surface:

```python
provider.chat(messages, model=...)        # -> ChatResult
provider.stream(messages, model=...)       # -> Iterator[ChatChunk]
provider.embed(texts, model=...)           # -> EmbeddingResult (if supported)
provider.count_tokens(text, model=...)     # -> int
provider.estimate_cost(usage, model=...)   # -> float | None
provider.health_check()                    # -> HealthStatus
provider.get_capabilities()                # -> set[str]
provider.info()                            # -> ProviderInfo (name, kind, models, ...)
```

Static, credential-free discovery is available via class attributes: `name`,
`kind`, `capabilities`, `models`, `default_model`, `requires_api_key`,
`api_key_env`, and a `pricing` table.

## Discover providers over REST

```bash
curl http://localhost:8000/api/providers                 # list + info
curl http://localhost:8000/api/providers/capabilities    # capability matrix
curl http://localhost:8000/api/providers/openai          # one provider's info
curl http://localhost:8000/api/providers/openai/health   # reachability/health
```

## Add a provider without touching core code

For an OpenAI-compatible service, subclass the shared base, set class attributes,
and decorate with `@register_provider`:

```python
from app.providers.base import Capability
from app.providers.registry import register_provider
from app.providers.adapters.openai_compatible import OpenAICompatibleProvider

@register_provider
class MyProvider(OpenAICompatibleProvider):
    name = "my-provider"
    base_url = "https://api.my-provider.com/v1"
    api_key_env = "MYPROVIDER_API_KEY"
    default_model = "my-model-large"
    models = ["my-model-large", "my-model-small"]
    capabilities = {Capability.CHAT, Capability.STREAMING, Capability.EMBEDDING}
    pricing = {"my-model-large": (0.005, 0.015)}  # (input, output) USD / 1k tokens
```

Provider capabilities include `CHAT`, `STREAMING`, `EMBEDDING`, `TOOLS`,
`VISION` and `JSON_MODE` (see `app.providers.base.Capability`).

Simply importing the module registers the adapter — no core file changes. For a
completely different wire format, subclass `LLMProvider` (or another base) and
implement `chat`, `stream` and `health_check`.

You can also ship a provider as a [plugin](plugins.md) so it can be installed,
enabled and disabled at runtime.

## Injectable HTTP client

Adapters take an injectable `HttpClient` (default `UrllibHttpClient`), so you can
unit-test providers fully offline by passing a fake client — no network required.

## Next

- Package a provider as an installable [Plugin](plugins.md).
- See the runnable [`examples/08_custom_provider.py`](../../examples/08_custom_provider.py).
