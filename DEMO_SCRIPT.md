# Ghost Space — 3-minute demo script

**URL:** https://accessibility-mapper-sandy.vercel.app
**Admin token:** paste into **Admin** in the app (or `export ADMIN_TOKEN=…`). It is
never bundled into the JavaScript.

Before you start: open the app, go to **Admin**, paste the token, then go to
**Ghost Space** and press **Reset** so you start from the seeded day.

---

## 0:00 — The problem

> "Students with mobility limits can't trust a static map or a static room list.
> Both are wrong twice a day. The map says the ramp is fine — a scooter was
> dumped on it this morning. The room list says Suzzallo 305 is free from 3pm —
> it has been booked since 1pm by someone who never turned up."

> "Two systems solve half of that each. We're showing you both, on one clock."

On screen: the **Map** view, step-free routing already on.

---

## 0:30 — Report a barrier with a photo

Press **Report barrier**, drop in any photo, submit.

Point at the response:

> "The classifier ran, then the privacy pass ran *before* storage — faces and
> plates are blurred, the image is re-encoded under 300 KB, EXIF is stripped, and
> only the redacted bytes are saved. It came in as a public report, so it starts
> **unverified** and expires — public reports never auto-verify."

> "Classification is a deterministic heuristic feature detector, not a trained
> model. `GET /cv/status` says exactly that."

---

## 1:00 — The route changes around the barrier

Click the barrier that lands on the path, then plan a step-free route to a
destination behind it.

> "The router didn't 404. It found a route and marked it *degraded* — it would
> have to send me via steps. The warning says `step_free_severed`, and the blocked
> edge is named. A student sees that before they start walking, not after."

---

## 1:30 — Ghost Space board on the demo clock

Switch to **Ghost Space**. Press **Reset**, then set the clock to **x300** and
**Play**.

> "This is a full campus day in about three minutes. Every booking holds its room
> for its whole window even when nobody shows up. Watch the amber bars — booked
> and empty. Ten minutes after start, if the room is still empty and the
> historical no-show rate plus live evidence say it's a ghost, the engine
> releases it and it turns violet."

Open the **Simulated data** badge with a glance:

> "Occupancy is simulated, and it's headcount only — there is no identity column,
> no camera, no image. That's the privacy contract, and it's enforced by the
> schema, not by convention."

Click any violet bar to open the decision drawer:

> "This is the decision the engine actually stored — probability, the evidence
> behind it, and the constraints that had to be true. It's not reconstructed in
> the browser."

---

## 2:15 — A step-free student asks for a room

Switch to **Find a Room**, set seats to 16, keep **I need step-free access** on,
press **Find rooms**.

> "Health Sciences 302 is the closest room that fits. It's excluded — and it says
> why: *lift L2 reported broken, verified 14:05*. Not 'unavailable'. The specific
> barrier, and when a human last confirmed it."

> "And that's only possible because Ghost Space and the Barrier Mapper share one
> router. Reachability is checked *before* the booking calendar — a room you
> can't reach isn't an option whether or not it's free."

Press **Route** on the top match: the path draws on the map.

---

## 2:45 — Baseline vs Ghost Space

Scroll to **Baseline vs Ghost Space**.

> "Same seeded day, same bookings. The baseline just never releases anything."

- Recovered room-hours and kWh saved — **computed**, with the energy figure
  labelled as an estimate, not a meter reading.
- Release accuracy — `1 − false release rate`. Reclaims count as failures on
  purpose.
- Requests fulfilled, and the step-free subset.

Close on:

> "A room list tells you what was booked. A routing map tells you what was
> blocked. Neither tells you what you'd actually get if you walked over there
> right now."

---

## If you have 30 seconds left

> "Every number on that screen was computed from the seeded day and what the
> engine actually did. There's not one hardcoded metric in the UI."

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Clock controls greyed out | No admin token. **Admin** → paste token → **Save**. |
| Board shows "Live clock" | Same — set the token, then press **Reset**. |
| No releases appear | Press **Reset**, then **Simulate occupancy**, then set **x300** + **Play**. |
| Everything 500s | Check you're on `accessibility-mapper-sandy.vercel.app`, not a stale per-deployment URL. |
