"""
Ollama LLM 用戶端工廠
支援多實例負載平衡（round_robin / random）
"""

import logging
import random
import yaml
from pathlib import Path
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
        num_predict: int = 768
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
        self.current_index = 0

        logger.info(f"Ollama 負載平衡器初始化：{len(instances)} 個實例，策略：{strategy}")

    def _client_for_instance(self, instance: str):
        """Create an Ollama SDK client for a specific instance URL."""
        if not OLLAMA_AVAILABLE:
            raise RuntimeError("Ollama SDK 未安裝")

        parsed = urlparse(instance)
        host = instance if parsed.scheme else f"http://{instance}"
        return ollama.Client(host=host)

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


class OllamaClient:
    """Ollama 本地 LLM 用戶端（向後相容）"""

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

        configured_instances = instances or ollama_config.get("instances")

        if configured_instances:
            # 使用多實例負載平衡
            self.client = OllamaLoadBalancer(
                instances=configured_instances,
                model=model,
                strategy=strategy or ollama_config.get("strategy", "round_robin"),
                num_predict=self.num_predict
            )
        else:
            # 向後相容：使用單一實例
            self.client = OllamaLoadBalancer(
                instances=[base_url],
                model=model,
                num_predict=self.num_predict
            )

        self.model = model

    def _load_config(self) -> dict:
        """載入 config.yaml"""
        config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        return {}

    def chat(self, messages: list, temperature: float = 0.3) -> str:
        """傳送聊天請求"""
        return self.client.chat(messages, temperature)

    def generate(self, prompt: str, temperature: float = 0.3) -> str:
        """單次生成"""
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
