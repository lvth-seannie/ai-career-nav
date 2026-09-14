"""Gemini (Google AI Studio) client — the ONLY module that calls an LLM.

Writes just the two narration fields the deterministic core can't produce:
the `recommendation` sentence and the per-skill roadmap `description`
(BACKEND_SPEC §4.2.2). Everything else (matchScore, strengths, missingSkills,
roadmap phase/skill) stays pure Python.

Any failure — no API key, timeout, rate limit, malformed response — is caught
here and turned into `None`. Callers (api/routers/analysis.py) always have a
deterministic fallback (api/services/recommendation.py, api/services/roadmap.py)
and must never 500 because Gemini is unavailable.
"""
from __future__ import annotations

import logging
import os
import time

import httpx
import truststore

from api.services.skill_matching import SkillGap

logger = logging.getLogger(__name__)

# Verify TLS against the OS trust store instead of certifi's bundled CAs.
# Needed on machines where a local proxy/EDR intercepts HTTPS (its root CA is
# trusted by Windows/macOS but not by certifi) — see BACKEND_SPEC known risks.
truststore.inject_into_ssl()

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_MODEL = "gemini-flash-latest"
_TIMEOUT = httpx.Timeout(20.0, connect=4.0)
_CACHE_TTL = 60 * 60  # seconds — repeated demo runs with the same input are instant

# 429/503 (rate limit / model momentarily overloaded — common on the free
# tier) and read timeouts are transient and often succeed a couple seconds
# later. Other errors (bad key, bad request, malformed response) are
# deterministic — retrying them wastes the request budget, so only these get
# a retry.
_RETRYABLE_STATUSES = {429, 503}
_RETRY_DELAYS = (1.5, 3.0)  # seconds between attempts; len() + 1 = max attempts

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "recommendation": {"type": "STRING"},
        "roadmap": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "skill": {"type": "STRING"},
                    "description": {"type": "STRING"},
                },
                "required": ["skill", "description"],
            },
        },
    },
    "required": ["recommendation", "roadmap"],
}

_cache: dict[tuple, tuple[float, dict]] = {}


def _prompt(target_role: str, gap: SkillGap) -> str:
    strengths = ", ".join(gap.strengths) or "no listed skills yet"
    missing = ", ".join(gap.missing) or "none — they already meet every requirement"
    return (
        f"A learner wants to become a {target_role}. "
        f"Skills they already have: {strengths}. "
        f"Required skills they are missing: {missing}. "
        "Write one encouraging, specific recommendation (4-6 sentences) about how "
        "they should proceed, and — for EACH missing skill listed above, using "
        "that exact skill name — a one-sentence, actionable learning-plan "
        "description. Return only the requested JSON, no markdown."
    )


def _cache_key(target_role: str, gap: SkillGap) -> tuple:
    return (target_role, tuple(sorted(gap.strengths)), tuple(sorted(gap.missing)))


def _parse(data: dict) -> dict | None:
    import json

    text = data["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text)
    recommendation = parsed["recommendation"].strip()
    descriptions = {
        item["skill"].strip().lower(): item["description"].strip()
        for item in parsed["roadmap"]
        if item.get("skill") and item.get("description")
    }
    if not recommendation:
        return None
    return {"recommendation": recommendation, "descriptions": descriptions}


def narrate(target_role: str, gap: SkillGap) -> dict | None:
    """Returns `{"recommendation": str, "descriptions": {normalised_skill: str}}`
    or `None` if Gemini is unavailable/unusable for any reason."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    key = _cache_key(target_role, gap)
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    model = os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)
    body = {
        "contents": [{"role": "user", "parts": [{"text": _prompt(target_role, gap)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
            "temperature": 0.4,
        },
    }
    url = f"{_API_BASE}/{model}:generateContent"
    headers = {"x-goog-api-key": api_key}

    result = None
    for attempt, delay in enumerate((*_RETRY_DELAYS, None)):
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=_TIMEOUT)
            resp.raise_for_status()
            result = _parse(resp.json())
            break
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _RETRYABLE_STATUSES and delay is not None:
                logger.info("Gemini %s, retrying in %.1fs", exc.response.status_code, delay)
                time.sleep(delay)
                continue
            logger.warning("Gemini narration failed, using deterministic fallback: %s", exc)
            return None
        except httpx.TimeoutException as exc:
            if delay is not None:
                logger.info("Gemini timed out, retrying in %.1fs", delay)
                time.sleep(delay)
                continue
            logger.warning("Gemini narration failed, using deterministic fallback: %s", exc)
            return None
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
            logger.warning("Gemini narration failed, using deterministic fallback: %s", exc)
            return None

    if result is None:
        return None
    _cache[key] = (now, result)
    return result


def clear_cache() -> None:
    _cache.clear()
