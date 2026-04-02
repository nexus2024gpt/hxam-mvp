import os
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("HX-AM.LLM")

class BaseLLMClient(ABC):
    @abstractmethod
    async def complete(self, messages: List[Dict[str, str]], **kwargs) -> str:
        pass

class GroqClient(BaseLLMClient):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_MODEL", "groq/llama-3.3-70b-versatile")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.4"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "800"))
        self.timeout = int(os.getenv("LLM_TIMEOUT", "30"))
        try:
            from litellm import acompletion
            self.acompletion = acompletion
            self.available = True
        except ImportError:
            logger.error("litellm not installed")
            self.available = False

    async def complete(self, messages: List[Dict[str, str]], **kwargs) -> str:
        if not self.available:
            raise RuntimeError("LiteLLM not available")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not set")
        response = await self.acompletion(
            model=self.model,
            messages=messages,
            api_key=self.api_key,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            timeout=kwargs.get("timeout", self.timeout)
        )
        return response.choices[0].message.content.strip()
