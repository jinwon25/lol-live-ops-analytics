"""Distributed (Redis Lua sliding-window) and in-memory fallback Riot API request budget."""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import math
import re
import sys
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

ScopeKey = str | tuple[str, str]

MAX_WINDOW_SECONDS = 86400
DEFAULT_MAX_WINDOW_SECONDS = 120
DEFAULT_APP_LIMITS = {1: 18, 120: 95}

_request_telemetry_var: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    'request_telemetry',
    default=None,
)


def init_request_telemetry(trace_id: str | None = None) -> tuple[dict[str, Any], contextvars.Token]:
    """Initialize per-request telemetry context for structured logging."""
    state = {
        'trace_id': trace_id or uuid.uuid4().hex,
        'riot_api_calls': 0,
        'cache_hit': False,
    }
    token = _request_telemetry_var.set(state)
    return state, token


def reset_request_telemetry(token: contextvars.Token) -> None:
    _request_telemetry_var.reset(token)


def get_request_telemetry() -> dict[str, Any]:
    state = _request_telemetry_var.get()
    if state is None:
        return {'trace_id': None, 'riot_api_calls': 0, 'cache_hit': False}
    return state


def record_riot_api_call(count: int = 1) -> None:
    state = _request_telemetry_var.get()
    if state is not None:
        state['riot_api_calls'] = int(state.get('riot_api_calls', 0)) + count


def record_cache_hit(hit: bool = True) -> None:
    state = _request_telemetry_var.get()
    if state is not None and hit:
        state['cache_hit'] = True


class StructuredJsonFormatter(logging.Formatter):
    """Standard logging Formatter emitting single-line JSON records."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            'timestamp': datetime.now(UTC).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        structured_fields = getattr(record, 'structured_data', None)
        if isinstance(structured_fields, dict):
            payload.update(structured_fields)
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_json_logger(logger_name: str = 'lol_live_ops', stream: Any = None) -> logging.Logger:
    """Configure and return a logger that outputs single-line JSON to stdout."""
    target_logger = logging.getLogger(logger_name)
    target_logger.setLevel(logging.INFO)
    target_logger.propagate = False
    target_stream = stream if stream is not None else sys.stdout
    handler = logging.StreamHandler(target_stream)
    handler.setFormatter(StructuredJsonFormatter())
    target_logger.handlers = [handler]
    return target_logger


# Atomic Redis Lua script for multi-worker sliding-window reservation across app and method scopes.
SLIDING_WINDOW_RESERVE_LUA = """
local cooldown_key = KEYS[1]
local app_calls_key = KEYS[2]
local method_calls_key = KEYS[3]
local app_limits_key = KEYS[4]
local method_limits_key = KEYS[5]
local app_obs_prefix = KEYS[6]
local method_obs_prefix = KEYS[7]

local now_ms = tonumber(ARGV[1])
local request_id = ARGV[2]
local default_app_limits_raw = ARGV[3]

local function parse_pairs(raw)
    local parsed = {}
    if not raw or raw == '' then
        return parsed
    end
    for pair in string.gmatch(raw, '([^,]+)') do
        local sep = string.find(pair, ':')
        if sep then
            local count = tonumber(string.sub(pair, 1, sep - 1))
            local seconds = tonumber(string.sub(pair, sep + 1))
            if count and seconds and count >= 0 and seconds > 0 then
                parsed[seconds] = count
            end
        end
    end
    return parsed
end

local max_wait_ms = 0
local cooldown_until = tonumber(redis.call('GET', cooldown_key) or '0')
if cooldown_until > now_ms then
    max_wait_ms = cooldown_until - now_ms
end

local app_limits_raw = redis.call('GET', app_limits_key)
local app_limits = parse_pairs(app_limits_raw or default_app_limits_raw)
local method_limits_raw = redis.call('GET', method_limits_key)
local method_limits = parse_pairs(method_limits_raw or '')

local function check_scope(calls_key, limits_table, obs_prefix)
    local max_sec = 120
    for sec, _ in pairs(limits_table) do
        if sec > max_sec then
            max_sec = sec
        end
    end
    redis.call('ZREMRANGEBYSCORE', calls_key, '-inf', now_ms - (max_sec * 1000))
    for sec, limit in pairs(limits_table) do
        local window_ms = sec * 1000
        local window_start = now_ms - window_ms
        local recent_count = redis.call('ZCOUNT', calls_key, window_start + 1, '+inf')
        if recent_count >= limit then
            local oldest = redis.call('ZRANGEBYSCORE', calls_key, window_start + 1, '+inf', 'WITHSCORES', 'LIMIT', 0, 1)
            if oldest and #oldest >= 2 then
                local wait_ms = window_ms - (now_ms - tonumber(oldest[2]))
                if wait_ms > max_wait_ms then
                    max_wait_ms = wait_ms
                end
            end
        end
        local obs_raw = redis.call('GET', obs_prefix .. ':' .. tostring(sec))
        if obs_raw then
            local sep = string.find(obs_raw, ':')
            if sep then
                local obs_count = tonumber(string.sub(obs_raw, 1, sep - 1))
                local obs_until = tonumber(string.sub(obs_raw, sep + 1))
                if obs_count and obs_until and now_ms < obs_until and obs_count >= limit then
                    local wait_ms = obs_until - now_ms
                    if wait_ms > max_wait_ms then
                        max_wait_ms = wait_ms
                    end
                end
            end
        end
    end
    return max_sec
end

local app_max_sec = check_scope(app_calls_key, app_limits, app_obs_prefix)
local method_max_sec = check_scope(method_calls_key, method_limits, method_obs_prefix)

if max_wait_ms > 0 then
    local wait_sec = math.ceil(max_wait_ms / 1000.0)
    if wait_sec < 1 then
        wait_sec = 1
    end
    return wait_sec
end

redis.call('ZADD', app_calls_key, now_ms, request_id)
redis.call('PEXPIRE', app_calls_key, app_max_sec * 1000)
redis.call('ZADD', method_calls_key, now_ms, request_id)
redis.call('PEXPIRE', method_calls_key, method_max_sec * 1000)

local function bump_observed(limits_table, obs_prefix)
    for sec, _ in pairs(limits_table) do
        local obs_key = obs_prefix .. ':' .. tostring(sec)
        local obs_raw = redis.call('GET', obs_key)
        if obs_raw then
            local sep = string.find(obs_raw, ':')
            if sep then
                local obs_count = tonumber(string.sub(obs_raw, 1, sep - 1))
                local obs_until = tonumber(string.sub(obs_raw, sep + 1))
                if obs_count and obs_until and now_ms < obs_until then
                    redis.call('SET', obs_key, tostring(obs_count + 1) .. ':' .. tostring(obs_until), 'PXAT', obs_until)
                end
            end
        end
    end
end

bump_observed(app_limits, app_obs_prefix)
bump_observed(method_limits, method_obs_prefix)
return 0
"""

# Atomic Redis Lua script to synchronize observed rate-limit headers across workers.
UPDATE_HEADERS_LUA = """
local limits_key = KEYS[1]
local obs_prefix = KEYS[2]
local now_ms = tonumber(ARGV[1])
local limits_raw = ARGV[2]
local counts_raw = ARGV[3]

if limits_raw and limits_raw ~= '' then
    redis.call('SET', limits_key, limits_raw, 'EX', 86400)
end

if counts_raw and counts_raw ~= '' then
    for pair in string.gmatch(counts_raw, '([^,]+)') do
        local sep = string.find(pair, ':')
        if sep then
            local count = tonumber(string.sub(pair, 1, sep - 1))
            local seconds = tonumber(string.sub(pair, sep + 1))
            if count and seconds and count >= 0 and seconds > 0 then
                local obs_key = obs_prefix .. ':' .. tostring(seconds)
                local prev_raw = redis.call('GET', obs_key)
                local target_until = now_ms + (seconds * 1000)
                if prev_raw then
                    local psep = string.find(prev_raw, ':')
                    if psep then
                        local prev_count = tonumber(string.sub(prev_raw, 1, psep - 1))
                        local prev_until = tonumber(string.sub(prev_raw, psep + 1))
                        if prev_count and prev_until and now_ms < prev_until and count >= prev_count then
                            target_until = prev_until
                        end
                    end
                end
                local ttl_ms = math.max(1, target_until - now_ms)
                redis.call('SET', obs_key, tostring(count) .. ':' .. tostring(target_until), 'PX', ttl_ms)
            end
        end
    end
end
return 1
"""


def windows(value: str) -> dict[int, int]:
    result = {}
    for pair in value.split(','):
        try:
            count, seconds = map(int, pair.strip().split(':'))
            if count >= 0 and 0 < seconds <= MAX_WINDOW_SECONDS:
                result[seconds] = count
        except ValueError:
            continue
    return result


def _serialize_windows(parsed_windows: dict[int, int]) -> str:
    return ','.join(f'{count}:{seconds}' for seconds, count in sorted(parsed_windows.items()))


def method_key(path: str) -> str:
    if '/matches/by-puuid/' in path:
        return 'match-ids'
    if '/matches/' in path:
        return 'match-timeline' if path.endswith('/timeline') else 'match-detail'
    return re.sub(r'/by-(?:puuid|riot-id)/.*', '/by-identity', path)


class RequestBudget:
    """Hybrid Rate Limit budget supporting Redis Lua sliding-window with in-memory fallback."""

    def __init__(self, redis_client: Any | None = None):
        self.calls: dict[str, deque[float]] = defaultdict(deque)
        self.methods: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self.limits: dict[ScopeKey, dict[int, int]] = {}
        self.observed: dict[tuple[ScopeKey, int], tuple[int, float]] = {}
        self.cooldowns: dict[str, float] = {}
        self.lock = asyncio.Lock()
        self.redis_client = redis_client

    def set_redis(self, redis_client: Any | None) -> None:
        """Bind or detach a shared async Redis client."""
        self.redis_client = redis_client

    async def reserve(self, host: str, method: str) -> int | None:
        if self.redis_client is not None:
            try:
                now_ms = int(time.time() * 1000)
                request_id = f'{now_ms}:{uuid.uuid4().hex[:8]}'
                keys = [
                    f'riot:cooldown:{host}',
                    f'riot:calls:app:{host}',
                    f'riot:calls:method:{host}:{method}',
                    f'riot:limits:app:{host}',
                    f'riot:limits:method:{host}:{method}',
                    f'riot:obs:app:{host}',
                    f'riot:obs:method:{host}:{method}',
                ]
                args = [
                    now_ms,
                    request_id,
                    _serialize_windows(DEFAULT_APP_LIMITS),
                ]
                wait_seconds = await self.redis_client.eval(
                    SLIDING_WINDOW_RESERVE_LUA,
                    len(keys),
                    *keys,
                    *args,
                )
                wait_int = int(wait_seconds or 0)
                return wait_int if wait_int > 0 else None
            except Exception as error:
                logger.warning('Redis RequestBudget.reserve failed, falling back to in-memory: %s', error)

        return await self._reserve_in_memory(host, method)

    async def _reserve_in_memory(self, host: str, method: str) -> int | None:
        async with self.lock:
            now = time.monotonic()
            waits = [self.cooldowns.get(host, 0) - now]
            scopes: list[tuple[ScopeKey, deque[float], dict[int, int]]] = [
                (host, self.calls[host], DEFAULT_APP_LIMITS),
                ((host, method), self.methods[(host, method)], {}),
            ]
            for scope, calls, defaults in scopes:
                limits = self.limits.get(scope, defaults)
                while calls and now - calls[0] >= max(limits.keys(), default=DEFAULT_MAX_WINDOW_SECONDS):
                    calls.popleft()
                for seconds, limit in limits.items():
                    recent = [stamp for stamp in calls if now - stamp < seconds]
                    if len(recent) >= limit and recent:
                        waits.append(seconds - (now - recent[0]))
                    count, until = self.observed.get((scope, seconds), (0, 0))
                    if now < until and count >= limit:
                        waits.append(until - now)
            wait = max(waits)
            if wait > 0:
                return max(1, math.ceil(wait))
            self.calls[host].append(now)
            self.methods[(host, method)].append(now)
            target_scopes: list[ScopeKey] = [host, (host, method)]
            for target_scope in target_scopes:
                for seconds in self.limits.get(target_scope, {}):
                    key = (target_scope, seconds)
                    count, until = self.observed.get(key, (0, 0))
                    if now < until:
                        self.observed[key] = (count + 1, until)
            return None

    def update(self, host: str, method: str, headers: Any) -> None:
        """Update in-memory budget state immediately and schedule Redis sync if configured."""
        self._update_in_memory(host, method, headers)
        if self.redis_client is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.update_async(host, method, headers))
            except RuntimeError:
                pass

    def _update_in_memory(self, host: str, method: str, headers: Any) -> None:
        now = time.monotonic()
        scope_prefixes: list[tuple[ScopeKey, str]] = [(host, 'X-App'), ((host, method), 'X-Method')]
        for scope, prefix in scope_prefixes:
            limits = windows(headers.get(prefix + '-Rate-Limit', ''))
            counts = windows(headers.get(prefix + '-Rate-Limit-Count', ''))
            if limits:
                self.limits[scope] = limits
            for seconds, count in counts.items():
                key = (scope, seconds)
                previous, until = self.observed.get(key, (0, 0))
                # Conservative window tracking that accounts for external worker calls.
                self.observed[key] = (
                    count,
                    until if now < until and count >= previous else now + seconds,
                )

    async def update_async(self, host: str, method: str, headers: Any) -> None:
        """Synchronize rate-limit headers into Redis for multi-worker coordination."""
        self._update_in_memory(host, method, headers)
        if self.redis_client is None:
            return
        now_ms = int(time.time() * 1000)
        scope_configs = [
            (f'riot:limits:app:{host}', f'riot:obs:app:{host}', 'X-App'),
            (f'riot:limits:method:{host}:{method}', f'riot:obs:method:{host}:{method}', 'X-Method'),
        ]
        try:
            for limits_key, obs_prefix, prefix in scope_configs:
                parsed_limits = windows(headers.get(prefix + '-Rate-Limit', ''))
                parsed_counts = windows(headers.get(prefix + '-Rate-Limit-Count', ''))
                if not parsed_limits and not parsed_counts:
                    continue
                await self.redis_client.eval(
                    UPDATE_HEADERS_LUA,
                    2,
                    limits_key,
                    obs_prefix,
                    now_ms,
                    _serialize_windows(parsed_limits),
                    _serialize_windows(parsed_counts),
                )
        except Exception as error:
            logger.warning('Redis RequestBudget.update_async failed: %s', error)

    def cooldown(self, host: str, retry: int) -> None:
        self.cooldowns[host] = max(self.cooldowns.get(host, 0), time.monotonic() + retry)
        if self.redis_client is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.cooldown_async(host, retry))
            except RuntimeError:
                pass

    async def cooldown_async(self, host: str, retry: int) -> None:
        self.cooldowns[host] = max(self.cooldowns.get(host, 0), time.monotonic() + retry)
        if self.redis_client is None:
            return
        try:
            cooldown_until_ms = int((time.time() + retry) * 1000)
            ttl_ms = max(1000, retry * 1000)
            await self.redis_client.set(f'riot:cooldown:{host}', str(cooldown_until_ms), px=ttl_ms)
        except Exception as error:
            logger.warning('Redis RequestBudget.cooldown_async failed: %s', error)

    def remaining_budget(self, host: str = 'asia') -> int:
        """Compute remaining request budget for the given host in the current window."""
        now = time.monotonic()
        if self.cooldowns.get(host, 0) > now:
            return 0
        limits = self.limits.get(host, DEFAULT_APP_LIMITS)
        calls = self.calls.get(host, ())
        remaining_candidates = []
        for seconds, limit in limits.items():
            recent_calls = sum(1 for stamp in calls if now - stamp < seconds)
            obs_count, obs_until = self.observed.get((host, seconds), (0, 0))
            used = max(recent_calls, obs_count if now < obs_until else 0)
            remaining_candidates.append(max(0, limit - used))
        return min(remaining_candidates) if remaining_candidates else DEFAULT_APP_LIMITS[120]
