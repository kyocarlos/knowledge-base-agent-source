"""LLM client factory for local Ollama and OpenAI-compatible gateways."""
import logging

logger = logging.getLogger(__name__)

def create_llm_client(config: dict, model_override: str | None = None):
    provider = str(config.get("llm_provider", "ollama")).strip().lower()
    if provider in {"openai", "openai_compatible", "sub2api"}:
        from .openai_compatible_client import OpenAICompatibleClient

        settings = config.get("openai", {})
        model = model_override or config.get("llm_model")
        if not model:
            raise RuntimeError("llm_model is required for an OpenAI-compatible provider")
        return OpenAICompatibleClient(
            model=model,
            base_url=settings.get("base_url", "https://api.openai.com/v1"),
            api_key_env=settings.get("api_key_env", "SUB2API_API_KEY"),
            timeout=settings.get("timeout", 300),
            max_tokens=settings.get("max_tokens", settings.get("max_output_tokens", 4096)),
        )
    return create_ollama_client(config, model_override=model_override)


def create_ollama_client(config: dict, model_override: str | None = None):
    """
    創建 Ollama Client
    
    Args:
        config: 設定字典
    
    Returns:
        OllamaClient 物件
    """
    from .ollama_client import OllamaClient
    
    ollama_config = config.get("ollama", {})
    
    if ollama_config.get("instances"):
        return OllamaClient(
            instances=ollama_config["instances"],
            model=model_override or ollama_config.get("model", "qwen3-coder-next"),
            strategy=ollama_config.get("strategy", "round_robin")
        )
    else:
        return OllamaClient(
            model=model_override or ollama_config.get("model", "qwen3-coder-next"),
            base_url=ollama_config.get("base_url", "http://localhost:11434")
        )
