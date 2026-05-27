"""Ollama AI client for daycare AI features — milestone tagging, Q&A, and report summarization."""

import os
import json
import logging

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
MODEL = "phi3:mini"
TIMEOUT = 15  # seconds

# Validate Ollama URL at import time so misconfiguration is caught early
if not OLLAMA_URL:
    logger.warning("OLLAMA_URL is empty — AI features will fall back to cached/demo responses")

# Pre-computed demo responses keyed by observation note and question text.
# Used when Ollama is unavailable or as a fast path for the demo script.
DEMO_CACHE = {
    "milestone_tagging": {
        "emma built a tower of 12 blocks": {
            "category": "Cognitive",
            "tags": "Fine Motor, Counting, Math, Cognitive, 1:1 Correspondence",
            "description": "Emma built a tower of 12 blocks and counted each one as she stacked them",
            "milestone": "Demonstrates 1:1 correspondence counting up to 12 — aligns with 3yr Cognitive benchmarks (counting objects with 1:1 correspondence)",
        },
        "emma used descriptive language": {
            "category": "Language",
            "tags": "Language, Art, Descriptive, Vocabulary, Creative Expression",
            "description": "Emma used descriptive language to describe her painting — 'it's a purple dinosaur!'",
            "milestone": "Uses descriptive adjectives in spontaneous speech — aligns with 3yr Language benchmarks (descriptive vocabulary, 3+ word sentences)",
        },
    },
    "qa": {
        "peanut allergies": {
            "response": (
                "Sunshine Sprouts is a peanut-aware center. We do not serve peanut products. "
                "Liam Martinez has a severe peanut allergy (EpiPen on site). All staff are trained "
                "in epinephrine administration. Our kitchen is peanut-free."
            ),
        },
        "policy on peanut": {
            "response": (
                "Sunshine Sprouts is a peanut-aware center. We do not serve peanut products. "
                "Liam Martinez has a severe peanut allergy (EpiPen on site). All staff are trained "
                "in epinephrine administration. Our kitchen is peanut-free."
            ),
        },
    },
}


def _ollama(prompt: str, system: str | None = None) -> str | None:
    """Call the Ollama API with a prompt and optional system message.

    Returns the model response text, or None on any failure (timeout, HTTP error, etc.).
    """
    try:
        payload = {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 256},
        }
        if system:
            payload["system"] = system
        r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json().get("response", "").strip()
        logger.warning("Ollama returned %s for prompt %.120r", r.status_code, prompt)
        return None
    except requests.Timeout:
        logger.warning("Ollama timed out after %ss for prompt %.120r", TIMEOUT, prompt)
        return None
    except Exception:
        logger.warning("Ollama error for prompt %.120r", prompt, exc_info=True)
        return None


def check_cache(cache_key: str, query: str) -> dict | None:
    """Return the cached entry if *query* substring-matches a key in *cache_key*."""
    query_lower = query.lower().strip()
    for key, value in DEMO_CACHE.get(cache_key, {}).items():
        if key in query_lower:
            return value
    return None


def tag_milestone(observation_note: str) -> dict:
    """Analyze an observation note and return developmental milestone metadata.

    Returns a dict with keys: category, tags, description, milestone.
    Falls back to a generic entry when Ollama is unreachable or its JSON is unparseable.
    """
    cached = check_cache("milestone_tagging", observation_note)
    if cached:
        logger.info("Using cached milestone tagging for: %.50s...", observation_note)
        return cached

    system = (
        "You are an early childhood education AI assistant. Your job is to analyze teacher "
        "observation notes about children (ages 2-5) and extract developmental milestones.\n"
        "You must respond with ONLY valid JSON, no other text:\n"
        '{\n'
        '  "category": "Physical|Cognitive|Language|Social-Emotional",\n'
        '  "tags": "comma, separated, tags",\n'
        '  "milestone": "A professional milestone description aligned with early childhood developmental frameworks"\n'
        '}'
    )

    prompt = (
        f"Analyze this teacher observation note and identify the developmental milestone:\n\n"
        f'Observation: "{observation_note}"\n\n'
        f"Respond with JSON only:"
    )

    result = _ollama(prompt, system)
    if result:
        try:
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[1].rsplit("\n", 1)[0]
                if result.startswith("json"):
                    result = result[4:]
            data = json.loads(result)
            data["description"] = observation_note
            return data
        except json.JSONDecodeError:
            logger.warning("Failed to parse Ollama JSON response: %.200s", result)
    return {"category": "General", "tags": "", "description": observation_note, "milestone": ""}


def ask_question(question: str) -> str:
    """Answer a parent question about daycare policies or curriculum.

    Checks the demo cache first, then falls back to Ollama.
    """
    cached = check_cache("qa", question)
    if cached:
        logger.info("Using cached Q&A for: %.50s...", question)
        return cached["response"]

    system = (
        "You are a helpful daycare center assistant for Sunshine Sprouts Early Learning Center. "
        "You answer parent questions about policies, curriculum, schedules, and child development. "
        "Keep answers friendly, concise, and parent-appropriate. Never share another child's private information. "
        "Base your answers on standard early childhood education practices."
    )

    prompt = (
        f"Parent question: {question}\n\n"
        f"Answer as the Sunshine Sprouts daycare assistant:"
    )
    return _ollama(prompt, system) or "I'm sorry, I couldn't process that question. Please try again."


def summarize_report(report_data: dict) -> str:
    """Generate a warm, parent-friendly narrative summary from daily report data."""
    system = (
        "You are an early childhood educator writing a parent-friendly daily summary. "
        "Write 2-3 warm, engaging sentences describing the child's day. Be specific and positive."
    )

    prompt = (
        f"Write a brief, warm summary for a parent based on this daily report:\n"
        f"- Child: {report_data.get('child_name', 'Your child')}\n"
        f"- Mood: {report_data.get('mood', 'good')}\n"
        f"- Activities: {report_data.get('activities_summary', 'various activities')}\n"
        f"- Meals: {report_data.get('breakfast', '')}, {report_data.get('lunch', '')}\n"
        f"- Nap: {report_data.get('nap_start', '')} - {report_data.get('nap_end', '')}\n"
        f"- Milestones: {report_data.get('milestone_notes', 'none')}\n\n"
        f"Summary:"
    )
    return _ollama(prompt, system) or (
        f"Your child had a {report_data.get('mood', 'good').lower()} day enjoying "
        f"{report_data.get('activities_summary', 'various activities').lower()}."
    )
