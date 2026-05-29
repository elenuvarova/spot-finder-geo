"""SpotFinder zone explainer.

Two layers:
  Layer 1 (template): deterministic, rule-based sentence. Always available.
  Layer 2 (AI / Gemini): optional natural-language explanation via the
    Google Generative Language REST API.

The orchestrator ``explain`` tries the AI layer first and falls back to the
template on ANY failure (missing key, HTTP 429 RESOURCE_EXHAUSTED, non-200,
timeout, parse error, unexpected exception). It must NEVER raise.

The template rules here MUST stay identical to
``frontend/src/explainer.js``.
"""

import logging
import os

import httpx

logger = logging.getLogger("spotfinder.explain")

# --- Config / thresholds (keep in sync with frontend/src/explainer.js) ------
HIGH = 0.6  # threshold for the *_norm fields (0..1)
GAP_HIGH_M = 400  # meters: "far from nearest" catchment gap
COMP_HIGH = 4  # competitor count considered crowded
VEGAN_LOW = 0.2  # vegan_coverage below this => "almost no documented offering"

TYPE_LABELS = {
    "cafe": "coffee shop",
    "bakery": "bakery",
    "confectionery": "confectionery",
}

CAVEAT = " These are signals, not guarantees — worth checking on foot."

# Gemini REST config
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash-lite"
GEMINI_TIMEOUT_S = 8.0


def _label(type_: str) -> str:
    return TYPE_LABELS.get(type_, TYPE_LABELS["cafe"])


def _num(props: dict, key: str, default: float = 0.0) -> float:
    """Read a numeric property, tolerating None/missing/non-numeric values."""
    value = props.get(key, default)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_template_explanation(type_: str, vegan: bool, props: dict) -> str:
    """Layer 1: deterministic rule-based explanation.

    Evaluates the rules in order and returns the first match. Mirrors
    ``frontend/src/explainer.js`` exactly.
    """
    label = _label(type_)

    gap_t = round(_num(props, f"gap_{type_}"))
    comp_t = _num(props, f"comp_{type_}")
    residential_norm = _num(props, "residential_norm")
    income_norm = _num(props, "income_norm")
    traffic_norm = _num(props, "traffic_norm")

    if gap_t >= GAP_HIGH_M and residential_norm >= HIGH:
        sentence = (
            f"Residential area and the nearest {label} is roughly "
            f"{gap_t}m away — a classic catchment gap."
        )
    elif comp_t >= COMP_HIGH:
        sentence = (
            f"This zone is already crowded with {label} competitors "
            f"— higher risk."
        )
    elif income_norm >= HIGH and traffic_norm >= HIGH:
        sentence = (
            f"Affluent foot-traffic with limited supply here "
            f"— a strong signal for a {label}."
        )
    elif traffic_norm >= HIGH and comp_t < COMP_HIGH:
        sentence = f"Plenty of movement and few {label} competitors nearby."
    else:
        sentence = (
            f"Demand signals here are weak — a lower-potential zone for a {label}."
        )

    if vegan and _num(props, "vegan_coverage") < VEGAN_LOW:
        sentence += (
            " There is almost no documented vegan offering nearby "
            "(the diet:vegan tag undercounts reality)."
        )

    sentence += CAVEAT
    return sentence


def _build_prompt(type_: str, vegan: bool, props: dict) -> tuple[str, str]:
    """Return (system_instruction, user_text) for the Gemini call."""
    label = _label(type_)

    system = (
        f"You help a non-analyst business owner choose where to open a new "
        f"{label}. You are given neighborhood metrics for one map cell. In 2-3 "
        f"short, plain-language sentences with NO jargon and NO raw numbers "
        f"dump, explain why this zone is or is not promising for a {label}. "
        f"Finish by reminding that these are signals, not guarantees — worth "
        f"checking in person."
    )

    gap_t = round(_num(props, f"gap_{type_}"))
    comp_t = int(_num(props, f"comp_{type_}"))

    # A compact, qualitative-leaning summary line of the relevant signals.
    parts = [
        f"Business type: {label}",
        f"Vegan lens active: {'yes' if vegan else 'no'}",
        f"Foot-traffic proxy (0-1): {_num(props, 'traffic_norm'):.2f}",
        f"Transit access (0-1): {_num(props, 'transit_norm'):.2f}",
        f"Residential density (0-1): {_num(props, 'residential_norm'):.2f}",
        f"Local income level (0-1): {_num(props, 'income_norm'):.2f}",
        f"Offices/universities count: {int(_num(props, 'offices'))}",
        f"Nearby {label} competitors: {comp_t}",
        f"Meters to nearest {label}: {gap_t}",
    ]

    opp = props.get(f"opp_{type_}")
    if opp is not None:
        try:
            parts.append(f"Opportunity score within type (0-1): {float(opp):.2f}")
        except (TypeError, ValueError):
            pass

    if vegan:
        parts.append(
            f"Documented vegan coverage (0-1): {_num(props, 'vegan_coverage'):.2f}"
        )

    user_text = "; ".join(parts) + "."
    return system, user_text


async def build_ai_explanation(type_: str, vegan: bool, props: dict) -> str:
    """Layer 2: call the Gemini REST API and return the generated text.

    Raises on any failure (missing key, non-200, RESOURCE_EXHAUSTED, timeout,
    parse error). The orchestrator is responsible for catching these.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    model = os.environ.get("GEMINI_MODEL", GEMINI_DEFAULT_MODEL).strip() or (
        GEMINI_DEFAULT_MODEL
    )
    url = GEMINI_ENDPOINT.format(model=model)

    system, user_text = _build_prompt(type_, vegan, props)

    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "maxOutputTokens": 160,
            "temperature": 0.7,
        },
    }
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT_S) as client:
        resp = await client.post(url, json=payload, headers=headers)

    if resp.status_code != 200:
        # 429 RESOURCE_EXHAUSTED and any other non-200 surface here.
        raise RuntimeError(
            f"Gemini returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini response had no candidates")

    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError("Gemini response had empty text")

    return text


async def explain(type_: str, vegan: bool, props: dict) -> dict:
    """Orchestrator: try the AI layer, fall back to the template on ANY failure.

    Returns ``{"explanation": str, "source": "ai" | "template"}``.
    Never raises.
    """
    try:
        text = await build_ai_explanation(type_, vegan, props)
        return {"explanation": text, "source": "ai"}
    except Exception as exc:  # noqa: BLE001 - intentional broad fallback
        logger.info("AI explanation unavailable, using template: %s", exc)
        return {
            "explanation": build_template_explanation(type_, vegan, props),
            "source": "template",
        }
