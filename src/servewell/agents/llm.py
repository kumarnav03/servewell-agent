"""Ollama chat wrapper with schema-enforced JSON output, retries and call metadata."""

import time
from pathlib import Path

import ollama
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt

from servewell.config import get_settings

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


@retry(stop=stop_after_attempt(2), retry=retry_if_exception_type(ValidationError), reraise=True)
def chat_structured(system: str, user: str, schema: type[BaseModel]) -> tuple[BaseModel, dict]:
    s = get_settings()
    client = ollama.Client(host=s.ollama_host, timeout=180)
    started = time.time()
    resp = client.chat(
        model=s.llm_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        format=schema.model_json_schema(),
        keep_alive="60m",
        options={"temperature": s.llm_temperature, "num_ctx": s.llm_num_ctx},
    )
    raw = resp["message"]["content"]
    meta = {
        "model": s.llm_model,
        "latency_ms": int((time.time() - started) * 1000),
        "prompt_tokens": resp.get("prompt_eval_count"),
        "output_tokens": resp.get("eval_count"),
        "raw": raw,
    }
    return schema.model_validate_json(raw), meta


def llm_available() -> bool:
    try:
        ollama.Client(host=get_settings().ollama_host, timeout=3).list()
        return True
    except Exception:
        return False
