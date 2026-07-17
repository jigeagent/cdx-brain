# -*- coding: utf-8 -*-
"""Real LLM client for Ark/OpenAI via local proxy."""
from __future__ import annotations
import json, logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """Configuration for LLM API calls (proxy -> ark-code-latest)."""
    api_url: str = "https://ark.cn-beijing.volces.com/api/plan/v3"
    api_key: str = ""  # Set via env ARK_API_KEY or CDX_BRAIN_LLM_API_KEY
    model: str = "ark-code-latest"
    temperature: float = 0.3
    max_tokens: int = 2000
    timeout_ms: int = 60000
    verify_ssl: bool = True


class LLMClient:
    """Unified LLM client routing through local proxy."""

    def __init__(self, config: LLMConfig | None = None):
        self._config = config or LLMConfig()

    @property
    def config(self) -> LLMConfig:
        return self._config

    async def chat(self, messages: list[dict], **overrides) -> str:
        import httpx
        cfg = self._config
        headers = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        payload = {
            "model": overrides.get("model", cfg.model),
            "messages": messages,
            "temperature": overrides.get("temperature", cfg.temperature),
            "max_tokens": overrides.get("max_tokens", cfg.max_tokens),
        }
        url = overrides.get("api_url", cfg.api_url)
        tout = overrides.get("timeout_ms", cfg.timeout_ms) / 1000.0
        try:
            async with httpx.AsyncClient(timeout=tout, verify=cfg.verify_ssl) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"].get("content", "").strip()
        except Exception as e:
            logger.warning("LLM call failed: %s", e)
            raise

    async def chat_json(self, messages: list[dict], **overrides) -> dict:
        text = await self.chat(messages, **overrides)
        text = text.strip()
        if text.startswith("`"):
            lines = text.splitlines()
            if lines[0].startswith("`"):
                lines = lines[1:]
            if lines and lines[-1].startswith("`"):
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)

    async def analyze_query(self, query: str) -> dict:
        prompt = (
            "Analyze the search query and return JSON:\n"
            '- "rewritten_query": optimized version\n'
            '- "aliases": list of 2-5 alternative names\n'
            '- "needs_time_window": true/false\n'
            '- "time_window_start": ISO date or null\n'
            '- "time_window_end": ISO date or null\n'
            f"Query: {query}"
        )
        messages = [
            {"role": "system", "content": "You are a search query analyzer. Return ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ]
        return await self.chat_json(messages, temperature=0.2)

    async def infer_causal_chain(self, seed_entities: list[str], context: str = "") -> list[dict]:
        prompt = "Given entities: " + ", ".join(seed_entities) + "\n"
        if context:
            prompt += f"Context: {context}\n"
        prompt += (
            "Infer causal relationships. Return JSON array:\n"
            '- "source","target","relation" (causes|caused_by|enables|inhibits|correlates)\n'
            '- "confidence" (0-1), "rationale" (short)\n'
        )
        messages = [
            {"role": "system", "content": "You are a causal inference engine. Return ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ]
        result = await self.chat_json(messages, temperature=0.2)
        if isinstance(result, list):
            return result
        return result.get("relations", [])

    async def expand_aliases(self, query: str, entity: str) -> list[str]:
        prompt = f"Given query '{query}', list 3-5 aliases for '{entity}'. Return JSON array."
        messages = [
            {"role": "system", "content": "Return ONLY a JSON array of strings."},
            {"role": "user", "content": prompt},
        ]
        result = await self.chat_json(messages, temperature=0.4, max_tokens=300)
        if isinstance(result, list):
            return result
        return result.get("aliases", [])
