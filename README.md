# Ghost Space — AI Accessibility Barrier Mapper + ghost-room release engine

**Live:** https://accessibility-mapper-sandy.vercel.app

> Campus space and campus accessibility are one problem. Ghost Space finds
> booked-but-empty rooms and releases them. The Barrier Mapper knows which routes
> are blocked today. Together: a student who needs a step-free room gets only
> rooms that are actually free **and** actually reachable right now.

Two systems that were built separately, sharing one clock and one router:

| | |
|---|---|
| **Barrier Mapper** | Citizen-reported accessibility barriers with on-device face/plate redaction, live A\* step-free routing that degrades rather than 404s, and a facilities ticket queue. |
| **Ghost Space** | Booked-but-empty rooms, released automatically, with a reachability-aware matcher so a released room is only ever offered to someone who can physically get there. |

---

## Architecture

```
                     ┌──────────────────────────────────────────┐
   Browser  ────────▶│  Vercel: static Vite build  (index.html)  │
                     └──────────────────────────────────────────┘
                                        │ same-origin, no CORS
                     ┌──────────────────▼───────────────────────┐
                     │  /api/*  →  api/index.py  (FastAPI app)   │
                     │  ┌────────────────────────────────────┐  │
                     │  │ api/          routes, deps, auth   │  │
                     │  │ services/     space_service         │  │
                     │  │               graph_service (A*)   │  │
                     │  │               cv_service (blur)    │  │
                     │  │               barrier_service      │  │
                     │  │               classifier (heuristic)│  │
                     │  │ db/           models + seed         │  │
                     │  │ core/         settings, database    │  │
                     │  └────────────────────────────────────┘  │
                     └──────────────────┬───────────────────────┘
                                        │
              ┌─────────────────────────▼──────────────────────────┐
              │ Neon Postgres (NullPool, no local writes)           │
              │ rooms · bookings · occupancy_signals · noshow_stats │
              │ space_requests · barriers · tickets · media(bytea)  │
              │ app_state  ← the demo clock + graph_version         │
              └────────────────────────────────────────────────────┘
```

**Serverless constraints are design constraints here.** There is no background
work, no local media directory, and no in-process graph that survives a request:

- **Graph is stateless.** The NetworkX graph is rebuilt from the database on
  cold start and reloaded only when `app_state.graph_version` moves. Nothing is
  trusted across requests.
- **Media lives in Postgres.** Photos are redacted, re-encoded and stored as
  `bytea`, then streamed from `GET /api/v1/media/{id}`. Only the redacted bytes
  are ever kept.
- **One clock.** Every time comparison in Ghost Space goes through
  `space_service.now(db)`, which reads the demo clock from `app_state`. That is
  what lets a judge watch a full campus day in three minutes.

---

## The two engines

### Ghost Space

1. **No-show probability.** A Beta-smoothed historical rate for
   `(organizer_type, weekday, hour)` combined with live evidence as
   `p_noshow = 1 − (1 − prior) × still_coming`, where `still_coming` halves every
   12 minutes past the grace period while headcount stays 0.
2. **Release rule.** Release only when *all* of: grace period passed (10 min),
   `p_noshow ≥ 0.7`, and live headcount is exactly 0.
3. **Reclaim.** The organiser has a 5-minute window to take the room back. A
   reclaim is recorded as a **false release** and subtracted from the accuracy
   metric.
4. **Reachability-aware matching.** A step-free request runs the real router
   with live barrier penalties. A room behind a broken lift is excluded *and the
   barrier is named*.

Every decision returns `decision`, `probability`, `evidence`,
`constraints_applied`, `timestamp`.

### Barrier Mapper

Barrier reports are classified by a `BarrierClassifier` interface. The default is
`HeuristicBarrierClassifier` — a deterministic feature scorer (edge density,
stripe score, hazard-colour ratio, ground darkness), **not a trained model**.
Point `CV_ENDPOINT_URL` at your own inference service to swap in a real detector;
the app says so in `GET /api/v1/cv/status` and in the UI.

---

## What is real vs what is simulated

Being blunt about this, because the distinction matters more than the demo.

**Real**
- The routing engine: NetworkX A\* with an admissible haversine heuristic, real
  edge weights, real barrier penalties, real graceful degradation to a stepped
  route with a warning.
- The privacy pipeline: OpenCV Haar cascades blur faces and licence plates,
  re-encode to JPEG under ~300 KB, strip EXIF, and store only the redacted image.
- The Ghost Space decision logic, the no-show probability, the reachability
  exclusion and the metrics. Every number in the UI is computed from the seeded
  day and what the engine actually did.
- Postgres persistence, media storage, quota enforcement, the admin gate.

**Simulated**
- **Occupancy signals.** Check-in headcounts come from a simulator, not sensors.
  Headcount only — there is deliberately no identity column, no image and no
  camera in `occupancy_signals`.
- **Energy figures.** `wasted_kwh = power_kw × empty booked hours`, where
  `power_kw` is an *estimated* lighting + HVAC load. This is an estimate, not a
  meter reading, and the UI labels it as one everywhere it appears.
- **Barrier classification.** The heuristic feature scorer, not a learned model.
- **The campus and the day.** A fictional campus and one synthetic teaching day
  of 49 bookings (16 of them ghosts, 32.7%).

---

## Known limitations

- **The no-show model is a heuristic.** A Beta-smoothed historical rate plus a
  decay curve. It is explainable and recomputed from data, but it has not been
  fitted against a real campus's history, so treat the probabilities as
  illustrative.
- **Occupancy is headcount-only and simulated.** There is no sensor integration.
  A real deployment would need the same normalized event shape the simulator
  emits (`{room_id, headcount, ts, source}`).
- **Reclaim is a soft window, not a notification.** The organiser is *modeled*
  as reclaiming; no SMS/push actually goes out.
- **Energy numbers are order-of-magnitude estimates** driven by a `power_kw`
  figure we chose, not measured. They are useful for comparing baseline against
  Ghost Space and not for a utility bill.
- **Classification confidence is not calibrated.** 0.85 is a policy threshold we
  chose, not a measured ROC point.
- **Single-region, single-function deployment.** The Python bundle sits at
  249 MB against Vercel's 250 MB ceiling, so adding a heavy dependency (a real
  detector, for instance) means removing something else.
- **The demo clock is shared global state.** It is meant for a single demo; two
  viewers would fight over it.

---

## Running locally

```bash
# 1. backend deps + database (SQLite by default — no Postgres needed)
cd accessibility-mapper/backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2. frontend
cd ../../accessibility-mapper/frontend
npm install

# 3. run the API (from accessibility-mapper/backend)
.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# 4. run the UI (second terminal, from accessibility-mapper/frontend)
npm run dev
```

Then seed and open http://localhost:5173:

```bash
curl -X POST http://localhost:8000/api/v1/admin/seed \
  -H "X-Admin-Token: $(grep ADMIN_TOKEN ../.env.local | cut -d= -f2)"
```

Tests:

```bash
cd accessibility-mapper/backend && .venv/bin/python -m pytest -q
```

---

## Deploying to Vercel

One project serves both halves: Vite builds to static output, FastAPI runs as a
single Python function, and `vercel.json` rewrites `/api/*` to it. Same origin,
so there is no CORS configuration and the frontend uses relative URLs.

```bash
git init && git add -A && git commit -m "Ghost Space"
git remote add origin git@github.com:<you>/accessibility-mapper.git && git push -u origin main

vercel link
vercel --prod          # attach Neon from the Marketplace when prompted
```

Environment variables (set them as **secrets**):

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | Neon Postgres URL. Also supplied automatically by the Neon integration. |
| `ENVIRONMENT` | yes | `production`. This is what makes the admin token mandatory. |
| `ADMIN_TOKEN` | yes | Value operators send as `X-Admin-Token`. Never bundled into the JS. |
| `JWT_SECRET` | yes | Signs admin JWTs (the local-dev path). |
| `CV_ENDPOINT_URL` | no | External classifier. Unset ⇒ built-in heuristic. |

```bash
printf '%s' "$TOKEN" | vercel env add ADMIN_TOKEN production --yes
echo production            | vercel env add ENVIRONMENT production --yes
```

Then seed the deployment:

```bash
curl -X POST https://<your-domain>/api/v1/admin/seed -H "X-Admin-Token: $ADMIN_TOKEN"
```

`scripts/smoke_test.py` exercises the deployed URL end to end:

```bash
python scripts/smoke_test.py --base-url https://<your-domain> --admin-token "$ADMIN_TOKEN"
```

---

## API surface

```
GET    /api/v1/health                      GET    /api/v1/system/status
GET    /api/v1/overview                    GET    /api/v1/cv/status
GET    /api/v1/campus/network              GET    /api/v1/barriers/active
POST   /api/v1/routes/plan                 POST   /api/v1/barriers/report
GET    /api/v1/media/{id}

GET    /api/v1/spaces/rooms                GET    /api/v1/spaces/bookings
GET    /api/v1/spaces/board                GET    /api/v1/spaces/available
POST   /api/v1/spaces/request              POST   /api/v1/spaces/checkin
POST   /api/v1/spaces/bookings/{id}/reclaim
POST   /api/v1/spaces/simulate             POST   /api/v1/spaces/release-pass
GET    /api/v1/spaces/metrics              GET    /api/v1/demo/clock
POST   /api/v1/demo/clock

POST   /api/v1/admin/seed                  POST   /api/v1/admin/demo/reset
POST   /api/v1/admin/ghost-space/bookings/{id}/force-release
GET    /api/v1/admin/analytics             GET    /api/v1/admin/tickets
GET    /api/v1/admin/policies              GET    /api/v1/admin/audit
```

Everything except the admin routes is public read-only. Admin routes require
`X-Admin-Token` and are refused in production without it.
