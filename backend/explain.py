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

# Dietary lenses (canonical order, slugs, metadata) — keep in sync with the
# CONTRACT and frontend/src/lenses.js + explainer.js. Each lens is a
# DATA-COMPLETENESS signal built from a sparse diet:* tag (undercounts reality),
# NEVER a measure of demand/quality.
LENSES = {
    "vegan": {
        "noteLabel": "vegan",
        "tag": "diet:vegan",
        "coverageKey": "vegan_coverage",
    },
    "vegetarian": {
        "noteLabel": "vegetarian",
        "tag": "diet:vegetarian",
        "coverageKey": "vegetarian_coverage",
    },
    "glutenfree": {
        "noteLabel": "gluten-free",
        "tag": "diet:gluten_free",
        "coverageKey": "glutenfree_coverage",
    },
    "halal": {
        "noteLabel": "halal",
        "tag": "diet:halal",
        "coverageKey": "halal_coverage",
    },
}

TYPE_LABELS = {
    "cafe": "coffee shop",
    "bakery": "bakery",
    "confectionery": "confectionery",
}

# Generic, type-aware "go and look" prompt for the offline template.
# Mirror these strings in frontend/src/explainer.js exactly.
ON_GROUND = {
    "cafe": (
        " On the ground, check: peak-hour foot-traffic and how easy it is to "
        "reach on foot or transit."
    ),
    "bakery": (
        " On the ground, check: morning footfall from nearby homes and how far "
        "people already walk for fresh bread."
    ),
    "confectionery": (
        " On the ground, check: who walks past, local spending power, and how "
        "the nearest competitors price and present themselves."
    ),
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


def build_template_explanation(type_: str, lens, props: dict) -> str:
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

    # Reusable rule clauses (byte-identical to frontend/src/explainer.js).
    crowded = f"This zone is already crowded with {label} competitors — higher risk."
    catchment_gap = (
        f"Residential area and the nearest {label} is roughly "
        f"{gap_t}m away — a classic catchment gap."
    )
    affluent_traffic = (
        f"Affluent foot-traffic with limited supply here "
        f"— a strong signal for a {label}."
    )
    movement = f"Plenty of movement and few {label} competitors nearby."
    weak = f"Demand signals here are weak — a lower-potential zone for a {label}."

    # Saturation is the dominant risk for every type, so it leads when present.
    # Otherwise lead with the driver that matters most for this type:
    #   bakery -> residential + proximity gap, cafe -> traffic/transit,
    #   confectionery -> income (affluent foot-traffic).
    if comp_t >= COMP_HIGH:
        sentence = crowded
    elif type_ == "bakery":
        if gap_t >= GAP_HIGH_M and residential_norm >= HIGH:
            sentence = catchment_gap
        elif income_norm >= HIGH and traffic_norm >= HIGH:
            sentence = affluent_traffic
        elif traffic_norm >= HIGH:
            sentence = movement
        else:
            sentence = weak
    elif type_ == "confectionery":
        if income_norm >= HIGH and traffic_norm >= HIGH:
            sentence = affluent_traffic
        elif gap_t >= GAP_HIGH_M and residential_norm >= HIGH:
            sentence = catchment_gap
        elif traffic_norm >= HIGH:
            sentence = movement
        else:
            sentence = weak
    else:  # cafe (and any unknown type) -> traffic/transit first
        if traffic_norm >= HIGH and income_norm >= HIGH:
            sentence = affluent_traffic
        elif traffic_norm >= HIGH:
            sentence = movement
        elif gap_t >= GAP_HIGH_M and residential_norm >= HIGH:
            sentence = catchment_gap
        else:
            sentence = weak

    # Lens NOTE: fire only when a lens is active AND that lens's documented
    # coverage is genuinely 0 (not merely "low"), so the note stops firing on
    # nearly every sector. This MUST stay byte-identical to
    # frontend/src/explainer.js.
    if lens is not None and lens in LENSES:
        meta = LENSES[lens]
        if _num(props, meta["coverageKey"]) == 0:
            sentence += (
                " No " + meta["noteLabel"] + " offering is documented among the "
                "eateries here yet (the " + meta["tag"] + " tag undercounts "
                "reality)."
            )

    sentence += ON_GROUND.get(type_, ON_GROUND["cafe"])
    sentence += CAVEAT
    return sentence


# Per-type lead-driver guidance the model is told to emphasise first.
_TYPE_FOCUS = {
    "cafe": (
        "For a coffee shop, lead with foot-traffic and transit access — those "
        "matter most."
    ),
    "bakery": (
        "For a bakery, lead with residential density and the distance to the "
        "nearest bakery (a proximity gap matters most)."
    ),
    "confectionery": (
        "For a confectionery, lead with local income / affluence — discretionary "
        "spending power matters most."
    ),
}


def _build_prompt(type_: str, lens, props: dict) -> tuple[str, str]:
    """Return (system_instruction, user_text) for the Gemini call."""
    label = _label(type_)
    focus = _TYPE_FOCUS.get(type_, _TYPE_FOCUS["cafe"])
    meta = LENSES.get(lens) if lens is not None else None
    note_label = meta["noteLabel"] if meta else None

    # Lens guidance: generalised over any dietary lens. When a lens is active we
    # name it explicitly so the model refers to it as "documented <noteLabel>
    # offering" only; otherwise the guidance stays generic.
    if note_label:
        lens_guidance = (
            "active; here the active lens is " + note_label + ", so refer to it "
            "only as 'documented " + note_label + " offering'.\n"
        )
    else:
        lens_guidance = "active, and only as 'documented <diet> offering'.\n"

    system = (
        "You help a non-analyst business owner judge whether one neighbourhood "
        f"is promising for a new {label}. You are given a few metrics for one "
        "map cell.\n"
        "\n"
        "HOW TO READ THE METRICS — read carefully:\n"
        "- Every metric scored 0-100 (or 0..1) is a RELATIVE signal: it compares "
        "this area to OTHER neighbourhoods in the SAME city. A low score means "
        "'lower than most areas here', NOT 'none', 'nobody', or 'empty'. Stay "
        "relative and hedged. NEVER assert absolute real-world facts such as "
        "'nobody lives here', 'not many people live nearby', or 'hard to reach "
        "without a car' — you only know relative rankings, not absolute counts "
        "or real travel times.\n"
        "- A 'documented <diet> offering' value (e.g. vegan, vegetarian, "
        "gluten-free, halal) is a DATA-COMPLETENESS lens built from a sparse "
        "diet:* tag, which undercounts reality. It is NEVER a measure of demand, "
        "quality, or popularity. Do not treat a low value as 'low demand' or as a "
        "reason a place is un/popular. Mention it ONLY when a dietary lens is "
        + lens_guidance
        + "- UNDERSERVED DEMAND: when residents, affluence, or foot-traffic are "
        "present AND there are few competitors of this type, that is a possible "
        "gap worth exploring. When there are MANY competitors of this type, the "
        "area is saturated and riskier — say so.\n"
        "\n"
        f"FOCUS: {focus}\n"
        "\n"
        "OUTPUT FORMAT — follow exactly:\n"
        "1. Write 2-3 short, plain sentences (no jargon, no raw numbers) saying "
        f"why this area is or is not promising for a {label}, leading with the "
        "focus drivers above.\n"
        "2. Then ONE short, concrete line that starts with 'On the ground, "
        f"check: ' and names something specific to verify for a {label} (for "
        "example peak-hour foot-traffic, the pricing/quality of nearby "
        "competitors, or parking and street visibility).\n"
        "3. Then end with exactly: Signals, not guarantees."
    )

    gap_t = round(_num(props, f"gap_{type_}"))
    comp_t = int(_num(props, f"comp_{type_}"))
    n_food = int(_num(props, "n_food"))

    # A CLEAN, LABELLED summary. Drivers are 0-100 and explicitly tagged
    # "(relative)" so the model never reads them as absolute counts.
    parts = [
        f"Selected business type: {label}",
        f"Foot-traffic: {round(_num(props, 'traffic_norm') * 100)}/100 (relative)",
        f"Transit access: {round(_num(props, 'transit_norm') * 100)}/100 (relative)",
        (
            "Residential density: "
            f"{round(_num(props, 'residential_norm') * 100)}/100 (relative)"
        ),
        f"Income level: {round(_num(props, 'income_norm') * 100)}/100 (relative)",
        f"Nearest {label}: {gap_t} m away",
        f"Competitors of this type nearby: {comp_t}",
        f"Food establishments here: {n_food}",
    ]

    if meta:
        parts.append(
            "Documented " + note_label + " offering (data-completeness lens, not "
            "demand): "
            f"{round(_num(props, meta['coverageKey']) * 100)}/100"
        )

    user_text = "\n".join(parts) + "."
    return system, user_text


async def build_ai_explanation(type_: str, lens, props: dict) -> str:
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

    system, user_text = _build_prompt(type_, lens, props)

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
        # 429 RESOURCE_EXHAUSTED and any other non-200 surface here. Log only the
        # status code with a short static message — never the upstream response
        # body, which can leak request echoes / key hints into our logs.
        raise RuntimeError(f"Gemini returned non-200 status {resp.status_code}")

    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini response had no candidates")

    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError("Gemini response had empty text")

    return text


async def explain(type_: str, lens, props: dict) -> dict:
    """Orchestrator: try the AI layer, fall back to the template on ANY failure.

    Returns ``{"explanation": str, "source": "ai" | "template"}``.
    Never raises.
    """
    try:
        text = await build_ai_explanation(type_, lens, props)
        return {"explanation": text, "source": "ai"}
    except Exception as exc:  # noqa: BLE001 - intentional broad fallback
        logger.info("AI explanation unavailable, using template: %s", exc)
        return {
            "explanation": build_template_explanation(type_, lens, props),
            "source": "template",
        }
