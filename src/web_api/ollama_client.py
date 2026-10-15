"""
Ollama LLM 用戶端工廠
支援多實例負載平衡（round_robin / random），並可設定主要 LLM（OpenAI 相容）、以 Ollama 為備援。
"""

import logging
import os
import random
import yaml
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 嘗試引入 ollama SDK
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    logger.warning("Ollama SDK 未安裝，請執行 pip install ollama")


class OllamaLoadBalancer:
    """Ollama 多實例負載平衡器"""

    def __init__(
        self,
        instances: List[str],
        model: str = "qwen3-coder-next",
        strategy: str = "round_robin",
        num_predict: int = 768,
        timeout: float = 300
    ):
        """
        初始化負載平衡器

        Args:
            instances: Ollama 實例 URL 列表
            model: 模型名稱
            strategy: 負載策略（round_robin / random）
        """
        self.instances = instances
        self.model = model
        self.strategy = strategy
        self.num_predict = num_predict
        self.timeout = timeout
        self.current_index = 0

        logger.info(f"Ollama 負載平衡器初始化：{len(instances)} 個實例，策略：{strategy}")

    def _client_for_instance(self, instance: str):
        """Create an Ollama SDK client for a specific instance URL."""
        if not OLLAMA_AVAILABLE:
            raise RuntimeError("Ollama SDK 未安裝")

        parsed = urlparse(instance)
        host = instance if parsed.scheme else f"http://{instance}"
        return ollama.Client(host=host, timeout=self.timeout)

    def get_next_instance(self) -> str:
        """根據策略取得下一個實例"""
        if self.strategy == "round_robin":
            instance = self.instances[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.instances)
            return instance
        else:  # random
            return random.choice(self.instances)

    def chat(self, messages: list, temperature: float = 0.3) -> str:
        """
        傳送聊天請求到 Ollama（自動負載平衡）

        Args:
            messages: 訊息列表
            temperature: 生成溫度

        Returns:
            str: LLM 回應文字
        """
        if not OLLAMA_AVAILABLE:
            raise RuntimeError("Ollama SDK 未安裝")

        # 嘗試每個實例
        errors = []

        for attempt in range(len(self.instances)):
            instance = self.get_next_instance()

            try:
                client = self._client_for_instance(instance)
                response = client.chat(
                    model=self.model,
                    messages=messages,
                    think=False,
                    options={
                        "temperature": temperature,
                        "num_predict": self.num_predict
                    }
                )

                if hasattr(response, "message"):
                    return response.message.content
                return response["message"]["content"]

            except Exception as e:
                errors.append(f"{instance}: {e}")
                logger.warning(f"Ollama 實例 {instance} 失敗: {e}")
                continue

        # 所有實例都失敗
        error_msg = f"所有 Ollama 實例都失敗: {errors}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    def generate(self, prompt: str, temperature: float = 0.3) -> str:
        """
        單次生成（適用於簡單提示）
        """
        if not OLLAMA_AVAILABLE:
            raise RuntimeError("Ollama SDK 未安裝")

        errors = []

        for attempt in range(len(self.instances)):
            instance = self.get_next_instance()

            try:
                client = self._client_for_instance(instance)
                response = client.generate(
                    model=self.model,
                    prompt=prompt,
                    think=False,
                    options={
                        "temperature": temperature,
                        "num_predict": self.num_predict
                    }
                )

                if hasattr(response, "response"):
                    return response.response
                return response["response"]

            except Exception as e:
                errors.append(f"{instance}: {e}")
                continue

        raise RuntimeError(f"所有 Ollama 實例都失敗: {errors}")


_PRIMARY_PROVIDERS = {"openai", "openai_compatible", "sub2api"}


def _setting(env_name: str, section: dict, key: str, default=None):
    """環境變數優先，其次 config.yaml 的 llm_primary 區段。"""
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    value = section.get(key)
    return default if value in (None, "") else value


def _build_primary_client(config: dict):
    """依 KM_LLM_PRIMARY_* 環境變數或 config.yaml 的 llm_primary 建立主要 LLM。

    回傳 (client, label)；未設定或建立失敗時回傳 (None, "")，維持只用 Ollama。
    建立失敗會明確記錄錯誤，不會靜默忽略。
    """
    section = config.get("llm_primary") or {}
    provider = str(_setting("KM_LLM_PRIMARY_PROVIDER", section, "provider", "")).strip().lower()
    if not provider or provider == "ollama":
        return None, ""
    if provider not in _PRIMARY_PROVIDERS:
        logger.error("未知的主要 LLM provider：%s，維持只用 Ollama", provider)
        return None, ""
    openai_section = config.get("openai") or {}
    model = _setting("KM_LLM_PRIMARY_MODEL", section, "model", "")
    base_url = _setting("KM_LLM_PRIMARY_BASE_URL", section, "base_url", openai_section.get("base_url", ""))
    api_key_env = _setting("KM_LLM_PRIMARY_API_KEY_ENV", section, "api_key_env", openai_section.get("api_key_env", "SUB2API_API_KEY"))
    timeout = float(_setting("KM_LLM_PRIMARY_TIMEOUT_SECONDS", section, "timeout", 60))
    max_tokens = int(_setting("KM_LLM_PRIMARY_MAX_TOKENS", section, "max_tokens", openai_section.get("max_tokens", 4096)))
    if not model or not base_url:
        logger.error("主要 LLM %s 缺少 model 或 base_url，維持只用 Ollama", provider)
        return None, ""
    try:
        from .openai_compatible_client import OpenAICompatibleClient
        client = OpenAICompatibleClient(model=model, base_url=base_url, timeout=timeout, max_tokens=max_tokens, api_key_env=api_key_env)
    except Exception as exc:
        logger.error("主要 LLM %s 建立失敗，維持只用 Ollama: %s", provider, exc)
        return None, ""
    label = f"{provider}:{model}"
    logger.info("主要 LLM：%s（%s），Ollama 為備援", label, base_url)
    return client, label


def _has_images(messages: list) -> bool:
    """Ollama 格式的圖片訊息（OCR／圖片解讀）直接交給 Ollama。"""
    return any(isinstance(m, dict) and m.get("images") for m in messages or [])


class _ChatCompletions:
    def __init__(self, owner: "OllamaClient") -> None:
        self._owner = owner

    def create(self, *, messages: list, temperature: float = 0.3, model: Optional[str] = None, **kwargs):
        content = self._owner._chat_text(messages, temperature)
        return SimpleNamespace(model=model or self._owner.model, choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class _ChatEntry:
    """同時支援 KM 的 ``chat(messages)`` 與 SDK 風格的 ``chat.completions.create``。"""

    def __init__(self, owner: "OllamaClient") -> None:
        self._owner = owner
        self.completions = _ChatCompletions(owner)

    def __call__(self, messages: list, temperature: float = 0.3) -> str:
        return self._owner._chat_text(messages, temperature)


class OllamaClient:
    """Ollama 本地 LLM 用戶端（向後相容）；可設定主要 LLM，Ollama 作為備援。"""

    def __init__(
        self,
        model: str = "qwen3-coder-next",
        base_url: str = "http://localhost:11434",
        instances: Optional[List[str]] = None,
        strategy: Optional[str] = None
    ):
        """
        初始化 Ollama 用戶端

        Args:
            model: 模型名稱
            base_url: 單一 Ollama 實例 URL（向後相容）
        """
        # 嘗試從 config.yaml 讀取多實例設定
        config = self._load_config()

        ollama_config = config.get("ollama", {})
        self.num_predict = int(ollama_config.get("num_predict", 768))
        self.timeout = float(ollama_config.get("timeout", 300))

        configured_instances = instances or ollama_config.get("instances")

        if configured_instances:
            # 使用多實例負載平衡
            self.client = OllamaLoadBalancer(
                instances=configured_instances,
                model=model,
                strategy=strategy or ollama_config.get("strategy", "round_robin"),
                num_predict=self.num_predict,
                timeout=self.timeout
            )
        else:
            # 向後相容：使用單一實例
            self.client = OllamaLoadBalancer(
                instances=[base_url],
                model=model,
                num_predict=self.num_predict,
                timeout=self.timeout
            )

        self.model = model
        # 主要 LLM（例如 OpenAI 相容閘道）；未設定時維持只用 Ollama。
        self._primary, self._primary_label = _build_primary_client(config)
        self.chat = _ChatEntry(self)

    def _load_config(self) -> dict:
        """載入 config.yaml"""
        config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _chat_text(self, messages: list, temperature: float = 0.3) -> str:
        """主要 LLM 優先；失敗或含圖片訊息時改用 Ollama 備援。"""
        if self._primary is not None and not _has_images(messages):
            try:
                return self._primary.chat(messages, temperature=temperature)
            except Exception as exc:
                logger.warning("主要 LLM %s 失敗，改用 Ollama 備援（%s）: %s", self._primary_label, self.model, type(exc).__name__)
        return self.client.chat(messages, temperature)

    def generate(self, prompt: str, temperature: float = 0.3) -> str:
        """單次生成"""
        if self._primary is not None:
            try:
                return self._primary.generate(prompt, temperature=temperature)
            except Exception as exc:
                logger.warning("主要 LLM %s 失敗，改用 Ollama 備援（%s）: %s", self._primary_label, self.model, type(exc).__name__)
        return self.client.generate(prompt, temperature)

    @staticmethod
    def list_models() -> list:
        """列出所有已下載的模型"""
        if not OLLAMA_AVAILABLE:
            return []

        try:
            models = ollama.list()
            return [m["name"] for m in models.get("models", [])]
        except Exception as e:
            logger.error(f"列出模型失敗: {e}")
            return []

    @staticmethod
    def pull_model(model: str) -> bool:
        """
        下載模型

        Args:
            model: 模型名稱

        Returns:
            bool: 是否成功
        """
        if not OLLAMA_AVAILABLE:
            return False

        try:
            logger.info(f"開始下載模型：{model}")
            for progress in ollama.pull(model):
                if "status" in progress:
                    logger.info(f"下載進度：{progress['status']}")
            logger.info(f"模型下載完成：{model}")
            return True

        except Exception as e:
            logger.error(f"下載模型失敗: {e}")
            return False
