"""로컬 실험 모델은 복기 초점만 제안한다. 수치·사실·승패 판정은 생성하지 않는다."""
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from typing import Literal
from unittest.mock import Mock

import httpx
from pydantic import BaseModel, ConfigDict, Field

from service.config import get_settings
from service.review import FOCUSES

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / '.local/models/Qwen3-0.6B'
ADAPTER = ROOT / '.local/models/lol-coach-smoke'
MODEL_IDS = ('Qwen3-0.6B', 'Qwen3-1.7B', 'Qwen3.5-0.8B', 'LFM2.5-1.2B-Instruct', 'Qwen3-4B-Q4_K_M')
KEYS = ('gpm', 'dpm', 'vision_per_minute', 'kill_participation', 'cs_per_minute', 'damage_share')
SYSTEM = (
    'Select a review focus from supplied match metrics. This is a question to inspect, '
    'not a skill or causal verdict. Return only JSON with focus_id (vision, resource, '
    'fight_setup, matchup) and evidence_keys (one or two available metric keys). '
    'Never invent observations.'
)

MAX_OUTPUT_LENGTH = 2048
MAX_WORKER_STDOUT_LENGTH = 4096
MAX_COMPLETION_TOKENS = 64
WORKER_TIMEOUT_SECONDS = 75
MAX_CONCURRENT_COACH_REQUESTS = 4
SENSITIVE_ENV_KEYS = (
    'RIOT_API_KEY',
    'HF_TOKEN',
    'HUGGING_FACE_HUB_TOKEN',
    'HUGGINGFACE_HUB_TOKEN',
    'OPENAI_API_KEY',
)


def _resolve_python_executable() -> str:
    """Return a cross-platform Python interpreter path without hardcoded Windows binaries."""
    configured_python = os.environ.get('LOCAL_COACH_PYTHON', '').strip()
    return configured_python or sys.executable


class CoachMetrics(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    gpm: float = Field(ge=0, le=20000)
    dpm: float = Field(ge=0, le=100000)
    vision_per_minute: float = Field(ge=0, le=200)
    kill_participation: float | None = Field(ge=0, le=1)
    cs_per_minute: float | None = Field(ge=0, le=800)
    damage_share: float | None = Field(ge=0, le=1)


class CoachInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['TOP', 'JUNGLE', 'MID', 'BOT', 'SUPPORT']
    metrics: CoachMetrics


def messages(payload):
    values = payload.model_dump() if isinstance(payload, CoachInput) else payload
    return [
        {'role': 'system', 'content': SYSTEM},
        {'role': 'user', 'content': json.dumps(values, ensure_ascii=False, separators=(',', ':'))},
    ]


def validate_choice(raw, payload):
    if not isinstance(raw, str) or len(raw) > MAX_OUTPUT_LENGTH:
        raise ValueError('invalid output length')
    raw = raw.strip()
    fence = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    choice = json.loads(raw)
    available = {key for key, value in payload.metrics.model_dump().items() if value is not None}
    if not isinstance(choice, dict) or set(choice) != {'focus_id', 'evidence_keys'} or choice['focus_id'] not in FOCUSES:
        raise ValueError('invalid focus')
    keys = choice['evidence_keys']
    if (
        not isinstance(keys, list)
        or not 1 <= len(keys) <= 2
        or any(not isinstance(key, str) or key not in available for key in keys)
        or len(set(keys)) != len(keys)
    ):
        raise ValueError('unknown evidence')
    focus = FOCUSES[choice['focus_id']]
    return {
        'focus_id': choice['focus_id'],
        'evidence_keys': keys,
        'label': focus['label'],
        'questions': [focus['observation'], focus['hypothesis']],
        'next_step': focus['action'],
        'source': '로컬 실험 모델 · 복기 초점 제안',
        'stage': 'experimental',
        'caveat': '모델이 고른 확인 질문입니다. 실력 진단이나 개선 효과를 검증한 코칭은 아닙니다.',
    }


def selection():
    try:
        config_path = ROOT / '.local/coach-selection.json'
        if not config_path.is_file():
            config_path = ROOT / 'service/data/local_model_selection.json'
        chosen = json.loads(config_path.read_text(encoding='utf-8'))
        if not isinstance(chosen, dict) or chosen.get('model') not in MODEL_IDS or chosen.get('adapter') is not False:
            return None
        folder = ROOT / '.local/models' / chosen['model']
        manifest_path = folder / 'download-manifest.json'
        if chosen['model'] == 'Qwen3-4B-Q4_K_M':
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                if chosen.get('revision') != manifest['revision']:
                    return None
                if chosen.get('runtime') != 'llama.cpp ' + manifest['runtime']['tag']:
                    return None
            if not get_settings().LLAMA_SERVER_URL:
                return None
            return chosen
        if not manifest_path.is_file():
            return None
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if chosen.get('revision') != manifest['revision']:
            return None
        if not any(folder.glob('*.safetensors')):
            return None
        return chosen
    except (OSError, ValueError, KeyError, TypeError):
        return None


def status():
    chosen = selection()
    ready = chosen is not None
    return {
        'available': ready,
        'stage': 'experimental' if ready else 'not_installed',
        'model': chosen['model'] if ready else None,
        'description': '로컬 실험 모델 · 요청할 때만 실행' if ready else '로컬 모델 준비 중 · 기본 리포트는 바로 이용 가능',
    }


def _sanitized_worker_env() -> dict[str, str]:
    """Create an offline worker environment stripped of API keys and tokens."""
    env = dict(
        os.environ,
        HF_HUB_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1',
        HF_HUB_DISABLE_TELEMETRY='1',
        PYTHONIOENCODING='utf-8',
    )
    for sensitive_key in SENSITIVE_ENV_KEYS:
        env.pop(sensitive_key, None)
    return env


class LocalCoach:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.lock = threading.Lock()
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_COACH_REQUESTS)
        self.http_client: httpx.AsyncClient | None = client

    def set_client(self, client: httpx.AsyncClient | None) -> None:
        """Bind the shared lifespan httpx.AsyncClient connection pool."""
        self.http_client = client

    async def choose_async(self, payload: CoachInput) -> dict:
        """Non-blocking async inference delegating to persistent llama-server via httpx.AsyncClient."""
        if isinstance(self.choose, Mock):
            return self.choose(payload)

        chosen = selection()
        if chosen is None:
            raise RuntimeError('로컬 모델이 아직 준비되지 않았습니다.')

        async with self.semaphore:
            if chosen['model'] == 'Qwen3-4B-Q4_K_M':
                from service import quantized_coach

                if isinstance(quantized_coach.local_server, Mock) or isinstance(quantized_coach.generate, Mock):
                    try:
                        with quantized_coach.local_server() as (sync_client, _process, _load_seconds):
                            raw_output, _tokens = quantized_coach.generate(
                                sync_client,
                                messages(payload),
                                MAX_COMPLETION_TOKENS,
                            )
                    except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as error:
                        logger.warning('Quantized coach mocked call failed: %s', error)
                        raise RuntimeError('로컬 모델 실행을 완료하지 못했습니다. 기본 리포트는 계속 사용할 수 있습니다.') from None
                else:
                    try:
                        raw_output, _tokens = await quantized_coach.generate_async(
                            messages(payload),
                            limit=MAX_COMPLETION_TOKENS,
                            client=self.http_client,
                        )
                    except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as error:
                        logger.warning('Async llama-server inference failed: %s', error)
                        raise RuntimeError('로컬 모델 실행을 완료하지 못했습니다. 기본 리포트는 계속 사용할 수 있습니다.') from None

                try:
                    verified_answer = validate_choice(raw_output, payload)
                    verified_answer['model'] = chosen['model']
                    return verified_answer
                except (ValueError, TypeError, KeyError) as error:
                    logger.warning('Model output failed schema/evidence validation: %s', error)
                    raise RuntimeError('모델 제안을 검증하지 못했습니다. 기본 리포트를 이용해주세요.') from None

            return await asyncio.to_thread(self.choose, payload)

    def choose(self, payload: CoachInput) -> dict:
        """Synchronous inference entrypoint preserved for unit-test and worker compatibility."""
        chosen = selection()
        if chosen is None:
            raise RuntimeError('로컬 모델이 아직 준비되지 않았습니다.')
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('로컬 모델이 다른 요청을 처리 중입니다. 잠시 뒤 다시 시도해주세요.')
        try:
            if chosen['model'] == 'Qwen3-4B-Q4_K_M':
                from service.quantized_coach import generate, local_server

                try:
                    with local_server() as (client, _process, _load_seconds):
                        raw_output, _tokens = generate(client, messages(payload), MAX_COMPLETION_TOKENS)
                except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as error:
                    logger.warning('Quantized coach sync inference failed: %s', error)
                    raise RuntimeError('로컬 모델 실행을 완료하지 못했습니다. 기본 리포트는 계속 사용할 수 있습니다.') from None
                try:
                    verified_answer = validate_choice(raw_output, payload)
                    verified_answer['model'] = chosen['model']
                    return verified_answer
                except (ValueError, TypeError, KeyError) as error:
                    logger.warning('Quantized coach output validation failed: %s', error)
                    raise RuntimeError('모델 제안을 검증하지 못했습니다. 기본 리포트를 이용해주세요.') from None

            worker_env = _sanitized_worker_env()
            try:
                result = subprocess.run(
                    [
                        _resolve_python_executable(),
                        str(ROOT / 'scripts/local_coach_worker.py'),
                        '--model',
                        chosen['model'],
                    ],
                    input=payload.model_dump_json(),
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    cwd=ROOT,
                    env=worker_env,
                    timeout=WORKER_TIMEOUT_SECONDS,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                if result.returncode or len(result.stdout) > MAX_WORKER_STDOUT_LENGTH:
                    raise ValueError('worker failed')
                raw_output = json.loads(result.stdout)['raw']
            except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as error:
                logger.warning('Local coach subprocess worker failed: %s', error)
                raise RuntimeError('로컬 모델 실행을 완료하지 못했습니다. 기본 리포트는 계속 사용할 수 있습니다.') from None
            try:
                verified_answer = validate_choice(raw_output, payload)
                verified_answer['model'] = chosen['model']
                return verified_answer
            except (ValueError, TypeError, KeyError) as error:
                logger.warning('Local coach subprocess validation failed: %s', error)
                raise RuntimeError('모델 제안을 검증하지 못했습니다. 기본 리포트를 이용해주세요.') from None
        finally:
            self.lock.release()


coach = LocalCoach()
