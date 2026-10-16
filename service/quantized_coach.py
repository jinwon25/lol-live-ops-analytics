"""Asynchronous HTTP client for a persistent llama-server OpenAI-compatible daemon."""
from __future__ import annotations

from contextlib import contextmanager
import logging
from pathlib import Path
import time

import httpx

from service.config import get_settings

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / '.local/models/Qwen3-4B-Q4_K_M/Qwen3-4B-Q4_K_M.gguf'

DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_TOKENS = 64
DEFAULT_SEED = 17
MAX_RAW_RESPONSE_LENGTH = 4096


def build_completion_request(messages: list[dict], limit: int = DEFAULT_MAX_TOKENS, stop: list[str] | None = None) -> dict:
    """Construct the OpenAI-compatible chat completion payload for llama-server."""
    request_payload = {
        'messages': messages,
        'max_tokens': limit,
        'temperature': 0,
        'seed': DEFAULT_SEED,
        'cache_prompt': False,
        'chat_template_kwargs': {'enable_thinking': False},
    }
    if stop is not None:
        request_payload['stop'] = stop
    return request_payload


def parse_completion_response(response_data: dict) -> tuple[str, int]:
    """Validate and extract content and token count from chat completion JSON."""
    try:
        raw_content = response_data['choices'][0]['message']['content']
        if not isinstance(raw_content, str) or len(raw_content) > MAX_RAW_RESPONSE_LENGTH:
            raise ValueError('invalid model response')
        completion_tokens = response_data.get('usage', {}).get('completion_tokens', 0)
        return raw_content.strip(), completion_tokens
    except (KeyError, TypeError, IndexError):
        raise ValueError('invalid model response') from None


@contextmanager
def local_server(weights: Path | None = None, base_url: str | None = None):
    """Yield an HTTP client connected to the persistent llama-server daemon without spawning subprocesses."""
    del weights
    resolved_base_url = (base_url or get_settings().LLAMA_SERVER_URL).rstrip('/')
    started = time.monotonic()
    with httpx.Client(
        base_url=resolved_base_url,
        timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
        trust_env=False,
    ) as client:
        yield client, None, time.monotonic() - started


def generate(client: httpx.Client, messages: list[dict], limit: int = DEFAULT_MAX_TOKENS, stop: list[str] | None = None) -> tuple[str, int]:
    """Send a synchronous chat completion request to the persistent llama-server daemon."""
    request_payload = build_completion_request(messages, limit=limit, stop=stop)
    response = client.post('/v1/chat/completions', json=request_payload)
    response.raise_for_status()
    return parse_completion_response(response.json())


async def generate_async(
    messages: list[dict],
    limit: int = DEFAULT_MAX_TOKENS,
    stop: list[str] | None = None,
    client: httpx.AsyncClient | None = None,
    base_url: str | None = None,
) -> tuple[str, int]:
    """Send an asynchronous chat completion request to the persistent llama-server daemon."""
    resolved_base_url = (base_url or get_settings().LLAMA_SERVER_URL).rstrip('/')
    request_payload = build_completion_request(messages, limit=limit, stop=stop)
    endpoint_url = f'{resolved_base_url}/v1/chat/completions'

    if client is not None and not getattr(client, 'is_closed', False):
        response = await client.post(
            endpoint_url,
            json=request_payload,
            timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return parse_completion_response(response.json())

    async with httpx.AsyncClient(
        base_url=resolved_base_url,
        timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
        trust_env=False,
    ) as scoped_client:
        response = await scoped_client.post('/v1/chat/completions', json=request_payload)
        response.raise_for_status()
        return parse_completion_response(response.json())
