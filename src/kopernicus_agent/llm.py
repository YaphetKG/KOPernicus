import os
import logging
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

logger = logging.getLogger(__name__)

class LLMFactory:
    @staticmethod
    def get_llm(provider: str = "openai", model_name: str = None):
        if provider == "openai":
            model = model_name or os.getenv("OPENAI_MODEL", "openai/gpt-oss-20b")
            api_key = os.getenv("OPENAI_API_KEY", "EMPTY")
            base_url = os.getenv("OPENAI_BASE_URL", "http://localhost:9777/v1")
            print(model , api_key, base_url)
            logger.info(f"Initializing OpenAI LLM with model: {model}")
            return ChatOpenAI(model=model, api_key=api_key, base_url=base_url, temperature=0)
        elif provider == "gemini":
            return ChatGoogleGenerativeAI(model=model_name or "gemini-1.5-pro", temperature=0)
        else:
            raise ValueError(f"Unknown provider: {provider}")
