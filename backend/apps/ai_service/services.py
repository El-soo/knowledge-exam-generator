import logging
import os
import time
import requests
from django.conf import settings
from common.exceptions import BusinessError
from common.json_utils import parse_model_json
from apps.system_settings.models import SystemConfig, PromptTemplate

logger = logging.getLogger("ollama")

DEFAULT_CONFIG = {
    "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
    "chat_model": os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b"), "review_model": os.getenv("OLLAMA_REVIEW_MODEL", "qwen2.5:7b"),
    "knowledge_model": os.getenv("OLLAMA_KNOWLEDGE_MODEL", os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")), "embedding_model": os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3"),
    "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.2")), "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "8192")), "top_p": 0.9, "top_k": 40,
    "repeat_penalty": 1.1, "timeout": int(os.getenv("OLLAMA_REQUEST_TIMEOUT", "180")), "max_retries": 2, "batch_size": 8,
    # Ollama支持一次计算多个文本块。64在速度与内存占用之间较平衡，
    # keep_alive避免每个批次之间反复从磁盘加载模型。
    "chunk_size": 800, "chunk_overlap": 120, "embedding_batch_size": 64, "retrieval_top_k": 5,
    "keep_alive": 900,
    "similarity_threshold": 0.25, "duplicate_threshold": 0.88, "max_context_chars": 8000,
}

def get_config():
    saved = SystemConfig.objects.filter(config_key="system").values_list("config_value", flat=True).first() or {}
    return {**DEFAULT_CONFIG, **saved}

class OllamaService:
    def __init__(self):
        self.config = get_config()
        self.base_url = self.config["ollama_base_url"].rstrip("/")

    def list_models(self):
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=8)
            response.raise_for_status()
            return [m.get("name") or m.get("model") for m in response.json().get("models", [])]
        except requests.RequestException as exc:
            raise BusinessError(f"无法连接Ollama服务，请确认Ollama已经启动，并检查服务地址是否为：{self.base_url}", 50301, 503) from exc

    def ensure_model(self, model):
        if model not in self.list_models():
            raise BusinessError(f"本机未安装模型“{model}”，请进入系统设置选择已有模型。", 40031)

    def chat_json(self, messages, model=None, purpose="chat", schema=None):
        model = model or self.config["chat_model"]
        self.ensure_model(model)
        started = time.monotonic()
        payload = {
            "model": model, "messages": messages, "stream": False, "format": schema or "json",
            "keep_alive": int(self.config.get("keep_alive", 900)),
            "options": {"temperature": self.config["temperature"], "num_ctx": self.config["num_ctx"], "top_p": self.config["top_p"], "top_k": self.config["top_k"], "repeat_penalty": self.config["repeat_penalty"]},
        }
        if schema:
            # Ollama官方建议结构化输出时使用更低温度，降低字段偏离和多答案概率。
            payload["options"]["temperature"] = 0
        last_error = None
        for attempt in range(self.config["max_retries"] + 1):
            try:
                response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.config["timeout"])
                response.raise_for_status()
                content = response.json().get("message", {}).get("content", "")
                result = parse_model_json(content)
                logger.info("purpose=%s model=%s elapsed=%.2f input_chars=%s output_chars=%s status=success", purpose, model, time.monotonic() - started, sum(len(m.get("content", "")) for m in messages), len(content))
                return result
            except requests.Timeout as exc:
                last_error = BusinessError(f"Ollama请求超过{self.config['timeout']}秒，请稍后重试或选择更小的模型。", 50401, 504)
            except requests.RequestException as exc:
                last_error = BusinessError(f"Ollama调用失败：{exc}", 50302, 503)
            except (ValueError, TypeError) as exc:
                last_error = BusinessError(f"模型返回内容无法解析为有效JSON：{exc}", 50201, 502)
            if attempt < self.config["max_retries"]:
                time.sleep(min(2 ** attempt, 4))
        logger.error("purpose=%s model=%s elapsed=%.2f status=failed error=%s", purpose, model, time.monotonic() - started, last_error)
        raise last_error

def get_prompt(key, fallback=""):
    filename = {"knowledge_point":"knowledge_point_prompt.txt", "question_generation":"question_generation_prompt.txt", "question_review":"question_review_prompt.txt", "paper_rule":"paper_rule_prompt.txt", "query_rewrite":"query_rewrite_prompt.txt"}.get(key)
    default_content = ""
    if filename:
        path = settings.BASE_DIR / "prompts" / filename
        if path.exists(): default_content = path.read_text(encoding="utf-8")
    row = PromptTemplate.objects.filter(key=key, is_active=True).order_by("-version").first()
    # 只自动升级系统默认提示词；用户自己编辑并保存的版本绝不覆盖。
    if row:
        if row.is_default and default_content and row.content != default_content:
            PromptTemplate.objects.filter(key=key, is_active=True).update(is_active=False)
            latest = PromptTemplate.objects.filter(key=key).order_by("-version").first()
            row = PromptTemplate.objects.create(key=key, version=(latest.version + 1 if latest else 1), content=default_content, is_default=True, is_active=True)
        return row.content
    if default_content:
        PromptTemplate.objects.create(key=key, version=1, content=default_content, is_default=True, is_active=True)
        return default_content
    return fallback
