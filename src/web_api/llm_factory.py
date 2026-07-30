"""
LLM Client 工廠 - 統一使用 Ollama
"""
import logging

logger = logging.getLogger(__name__)

def create_llm_client(config: dict):
    """
    建立 Ollama LLM Client
    
    Args:
        config: 設定字典
    
    Returns:
        LLM Client 物件
    """
    return create_ollama_client(config)


def create_ollama_client(config: dict):
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
            model=ollama_config.get("model", "qwen3-coder-next"),
            strategy=ollama_config.get("strategy", "round_robin")
        )
    else:
        return OllamaClient(
            model=ollama_config.get("model", "qwen3-coder-next"),
            base_url=ollama_config.get("base_url", "http://localhost:11434")
        )
