# SpotFinder backend

Lightweight async FastAPI service. It does **no heavy computation** — it serves
the precomputed Antwerpen GeoJSON and provides an AI zone-explainer with
graceful degradation. Built for the Render free tier.

## Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

> **Python version:** Local dev requires Python 3.11-3.13 (the pinned
> pydantic-core has no wheels for Python 3.14 yet); Render runs 3.12.7.

The API is then at `http://localhost:8000`. The GeoJSON file is expected at
`backend/data/antwerpen.geojson` (produced by the pipeline). If it is missing,
`/api/spots` returns a clear 503; the rest of the API still works.

Copy `.env.example` to `.env` and fill in values as needed. Without a
`GEMINI_API_KEY` the explainer still works — it just always uses the
deterministic template layer.

## Endpoints

| Method | Path           | Description                                                        |
| ------ | -------------- | ------------------------------------------------------------------ |
| GET    | `/health`      | `{"status":"ok"}` — used for Render keep-alive pings.              |
| GET    | `/api/spots`   | The full `antwerpen.geojson` FeatureCollection (cached in memory). |
| POST   | `/api/explain` | Two-layer zone explanation. Never returns 5xx.                     |

### `POST /api/explain`

Request:

```json
{
  "type": "cafe",
  "vegan": false,
  "props": { "traffic_norm": 0.7, "comp_cafe": 1, "gap_cafe": 450, "...": "..." }
}
```

Response:

```json
{ "explanation": "…2-3 sentences ending with the caveat…", "source": "ai" }
```

`source` is `"ai"` when the Gemini layer answered, `"template"` otherwise.

## Two-layer explainer + fallback

- **Layer 2 (AI / Gemini):** if `GEMINI_API_KEY` is set, the backend calls the
  model named by `GEMINI_MODEL` (default `gemini-2.5-flash-lite`) via the
  Generative Language REST API with an ~8s timeout and returns
  `source: "ai"` on success.
- **Layer 1 (template):** a deterministic, rule-based explanation. This is the
  fallback on **any** AI failure — no key, HTTP `429 RESOURCE_EXHAUSTED`
  (quota), any non-200, timeout, parse error, or unexpected exception. It
  returns `source: "template"`.

`POST /api/explain` is designed to **never return a 5xx**: the orchestrator in
`explain.py` catches everything and degrades to the template, and `main.py`
wraps the call once more as a last-resort guard.

The template rules live in both `backend/explain.py` and
`frontend/src/explainer.js` and must stay identical.

## Environment variables

| Variable          | Default                 | Notes                                                              |
| ----------------- | ----------------------- | ------------------------------------------------------------------ |
| `GEMINI_API_KEY`  | _(blank)_               | Backend only — never expose to the frontend. Blank = template only. |
| `GEMINI_MODEL`    | `gemini-2.5-flash-lite` | Gemini model used by the AI layer.                                 |
| `FRONTEND_ORIGIN` | `*`                     | Comma-separated CORS origins. Set to the real frontend URL in prod. |
| `PYTHON_VERSION`  | `3.12.7` (Render)       | Pins the Python runtime on Render.                                 |

## Privacy / EU note (honest)

Only **open, aggregated statistics** are sent to Gemini: OpenStreetMap-derived
metrics and Statbel-derived neighborhood stats for a single map cell (foot-
traffic proxy, transit/income/residential signals, competitor counts and
distances). No personal data and no raw coordinates of individuals are sent.

Be aware: the **free** Gemini tier may use submitted prompts to improve Google's
models, and Google's terms **disallow commercial use of the free tier in the
EU/EEA/UK/CH**. That is fine for this **non-commercial portfolio demo**, but a
real product serving EU users would need a **paid tier** (where prompts are not
used for training) — or you can run with no key at all and ship the
template-only explainer.

Also note the foot-traffic figure is an honest **proxy** (weighted gastro/retail
points), not measured footfall, and the OSM `diet:vegan` tag **undercounts** the
real vegan offering.

## Deploy to Render

1. Push the repo to GitHub.
2. In Render: **New → Blueprint**, point it at this repo (branch `main`). Render reads
   `render.yaml` at the repo root (one free web service with `rootDir: backend`,
   build `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT`,
   health check `/health`).
3. Set the secret env vars in the dashboard:
   - `GEMINI_API_KEY` — your key (optional; omit for template-only).
   - `FRONTEND_ORIGIN` — your real frontend URL (e.g.
     `https://spotfinder.vercel.app`), **not** `*`.
4. The free instance sleeps after inactivity; a cron/uptime ping to `/health`
   keeps it warm.
