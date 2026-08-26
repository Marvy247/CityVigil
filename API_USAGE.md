# FortyGuard Temperature API — how CityVigil uses it

Submission artifact for FortyGuard Hackathon'26. Everything below was measured
against `api.fortyguard.com` during development, not inferred from documentation.
Where our measurements disagree with the published client or docs, both readings are
given.

- **Plan:** Hackathon, 2,000,000 credits
- **Consumed during development:** 188,580 (9.4%)
- **Endpoints used:** `/v1/heatmap`, `/v1/env_params`, `/v1/status/{id}`, `/v1/system/fetch-api-key-usage`

---

## 1. Endpoints, and why each is used

| Endpoint | Calls | Purpose in CityVigil |
|---|---|---|
| `POST /v1/heatmap` | 44 | Every exposure surface. The analytic layer varies; see §2. |
| `GET /v1/status/{activity_id}` | ~180 | Polling. Each heatmap needs several. |
| `POST /v1/env_params` | 1 | Hourly diurnal series, used to test the `time_of_measure` timezone question (§4.5). |
| `POST /v1/system/fetch-api-key-usage` | many | Credit accounting; not credit-charged. |

**Deliberately not used:** `/v1/satellite`, `/v1/streetview` and `/v1/heat_intelligence`
are Premium-tier. They are excluded from the critical path so the project runs on a
Basic key, and so a judge without Premium access can reproduce every figure.

### Request pattern

All analysis endpoints are asynchronous. Implementation lives in
[`src/cityvigil/fg_client.py`](src/cityvigil/fg_client.py):

```
POST /v1/heatmap  ->  { data: { activity_id } }
GET  /v1/status/{activity_id}  ->  { data: { status, result } }   # poll until terminal
```

Terminal states observed: `Completed` / `succeeded` for success, `failed` / `error`
for failure. Status strings are matched case-insensitively.

Three behaviours the client handles explicitly:

1. **The status endpoint 404s briefly after submission** while the activity
   propagates. Treated as "not ready yet" and retried, not as failure.
2. **Failed tasks cost nothing.** Verified repeatedly — a rejected 153-day request
   consumed 0 credits. This makes probing undocumented limits free (§4.3).
3. **5xx and 429 are retried** with exponential backoff and jitter; 4xx is not,
   because a client error will not fix itself.

---

## 2. Layer selection

`/v1/heatmap` returns four different things depending on `analytic_type`. Choosing
wrongly returns a confidently wrong answer, so CityVigil never selects a layer by
name — callers state the question and the mapping is recorded with its reason
([`src/cityvigil/layers.py`](src/cityvigil/layers.py)).

| Question asked | `analytic_type` | Returns | Our calls |
|---|---|---|---|
| How hot is it? | `tcm` | per-tile min/mean/max temperature | 5 |
| How long is it dangerous? | `exceedance` | **count of hours** past threshold | 28 |
| Is there any relief? | `persistence` | longest **unbroken** run of such hours | 6 |
| When does it peak? | `time_of_measure` | hour-of-day of peak | 4 |

### Why `exceedance` carries the project

`exceedance` returns *hours*, not degrees. Multiplied by the exposed population that
is **person-hours** — in the API's own unit, with no invented index in between. This
is the single most important property we found in the API and the reason the
headline metric is defensible:

```
person-hours at risk = tract population × mean exceedance hours
```

### Why `persistence` is kept separate

Both `exceedance` and `persistence` are measured in hours, and adding them would be
arithmetically easy and wrong: persistence is a *subset* of exceedance hours, so
summing double-counts. They answer different questions — total exposure versus
whether heat ever breaks overnight — and heat mortality tracks the second. CityVigil
carries persistence alongside and never merges it.

---

## 3. Credit model (measured)

**Heatmap generation costs a flat 4,220 credits per call, independent of area or
tile count.** Measured directly:

| AOI | Tiles returned | Credits | Per tile |
|---|---|---|---|
| 1.1 km² @ 100 m | 81 | 4,220 | 52.1 |
| 101.7 km² @ 100 m | 10,177 | 4,220 | 0.415 |

Confirmed across 44 calls: 185,680 credits / 44 = exactly 4,220 each.
`env_params` cost 2,900 for one call.

**Consequence for anyone building on this API:** request the largest AOI the plan
allows, never tile a city into small footprints. A naive tiling strategy wastes
credits by a factor of 100 or more. CityVigil's
[`tile_bbox()`](src/cityvigil/guards.py) sizes AOIs just under the plan cap for
this reason.

Large AOIs are slower rather than costlier — 70 s for 10,177 tiles versus 22 s for
81 — so the polling timeout matters more than the credit budget.

---

## 4. Undocumented behaviour we measured

Five findings the published documentation does not mention. Each changed our
implementation.

### 4.1 `tcm` tile readings are Celsius, not Fahrenheit

The official quickstart client documents tile temperatures as Fahrenheit. They are
Celsius.

Central Phoenix, 2024-07-15, returned `average_temperature` values of 35.9–36.2 with
a max of 40.5. As Fahrenheit that would be a cold day in a desert city in July; as
Celsius it is 97–105 °F, which is correct. The August 2026 window returns
38.8–39.3 °C, likewise consistent.

Note the mixed units: `threshold` on `exceedance`/`persistence` is **Celsius** while
the same API's tile fields are also Celsius, but a US-facing tool naturally works in
Fahrenheit. CityVigil converts at the boundary
([`units.py`](src/cityvigil/units.py)) and refuses to infer a unit when inference
would be ambiguous, because a silent guess produces a plausible number wrong by
about 30 degrees.

### 4.2 `filter_type=4` ranges are capped at 31 days

Undocumented. Found by probing, which was free because failed tasks cost nothing.

| Span | Result |
|---|---|
| 14 days | OK |
| 31 days | OK |
| 32 days | task failure |
| 46 days | HTTP 500 at submit |
| 153 days | HTTP 500 at submit |

Two distinct rejection paths: 32 days is accepted then fails as a task, longer spans
are rejected at submission. Any season-length analysis must be assembled from
month-sized windows client-side. CityVigil rejects over-long ranges locally with a
message saying so.

### 4.3 Failed tasks are free

Stated in the quickstart, and we can confirm it in practice: every 500 and every
task failure during limit-probing left the credit balance unchanged. This makes
exploratory probing of undocumented limits essentially costless, which is how §4.2
was established.

### 4.4 `persistence` saturates in 2026 windows

For our 101.7 km² central Phoenix AOI, `persistence` returns **exactly 8.0 hours for
every one of 10,177 tiles** in 2026 windows. A perfectly uniform spatial field is not
a physical result.

| Window | `persistence` across tiles |
|---|---|
| 15–21 Jul 2024 | 6.79 – 8.27 h (varies sensibly) |
| 15–21 Jun 2026 | flat 8.0 |
| 8–14 Jul 2026 | flat 8.0 |
| 1–7 Aug 2026 | flat 8.0 |

Three separate 2026 windows, all identical, while the 2024 window behaves normally.
CityVigil therefore keeps a 2024 reference window (`phoenix-2024`) purely to
demonstrate the relief signal, and reports the saturation rather than presenting a
constant as a finding. **Possible API-side issue worth investigating.**

### 4.5 `time_of_measure` cannot be interpreted as an hour of peak

The quickstart documents this as a UTC hour. Neither UTC nor local reconciles what
we measured:

| Window | Returned | As UTC → Phoenix local | As local |
|---|---|---|---|
| 15–21 Jul 2024 | 16–17 | 09:00–10:00 | 16:00–17:00 |
| 1–7 Aug 2026 | 4–5 | 21:00–22:00 (prev. day) | 04:00–05:00 |

A genuine peak hour should not move twelve hours between two summer weeks in the
same city. We tested independently with `env_params`, which returns explicit
`timezone: GMT-7` metadata and local timestamps: apparent temperature for the same
point and day peaks at **15:00 local**, consistent with a late-afternoon peak.

So 2024's 16–17 is plausible as local time, but 2026's 4–5 is not plausible under
either reading. **CityVigil does not use this layer for scheduling and says so in
the UI**, rather than guessing and shifting every operational recommendation by
several hours.

---

## 5. Guards: refusing bad requests before spending credits

[`src/cityvigil/guards.py`](src/cityvigil/guards.py) validates locally first,
because a successful call that answered the wrong question is worse than a rejected
one. Every rule below is enforced with a named field so a caller can repair the
request:

| Rule | Source |
|---|---|
| `granularity ∈ {60, 80, 100}` metres | API; the marketed ~20 m is not selectable |
| `filter_type` companions: 1 needs `start_time`, 2 needs both times, 4 needs `end_date` | API semantics |
| Extra companions rejected | passing `end_date` to `filter_type=3` silently changes the window |
| `start_date ≥ 2021-01-01` | archive floor (FAQ) |
| Window end ≤ now + 12 h | forecast ceiling (FAQ) |
| Range span ≤ 31 days | measured, §4.2 |
| `exceedance`/`persistence` require `threshold` + `direction`; others forbid them | API |
| AOI fully within US bounding boxes | coverage is US-only |
| AOI bbox area ≤ plan cap | 10 mi² Basic / 50 mi² Pro |

---

## 6. Caching, provenance and reproducibility

Responses are content-addressed on `sha256(endpoint + payload)` and stored gzipped
([`cache.py`](src/cityvigil/cache.py)). 43 heatmap responses and 1 env-params
response are **committed to this repository**: 15.5 MB compressed from 106.7 MB raw,
a 6.9× saving that is what makes committing them practical at all.

Consequences:

- `CITYVIGIL_CACHE_MODE=replay` reproduces every figure in the submission with **no
  API key and no network**. Judges can verify without spending credits.
- Each cache entry stores the exact request payload beside the response, so any
  number can be traced to the question that produced it.
- The AOI is canonicalised before hashing — cosmetic differences such as a `name`
  property are stripped. This was not premature: an unlabelled versus labelled AOI
  with identical geometry cost us a duplicate 4,220 credits before the fix.

Every call is also written to an append-only audit trail
([`audit.py`](src/cityvigil/audit.py)) recording endpoint, analytic type, payload
digest, cache hit or miss, activity id, duration, and — for layer choices — a
**mandatory written rationale**. `GET /api/audit` exposes it; the dashboard renders
it.

---

## 7. Reproducing our API usage

```bash
# No key needed — replays the committed responses
CITYVIGIL_CACHE_MODE=replay python3 scripts/analyze_phoenix.py
CITYVIGIL_CACHE_MODE=replay python3 scripts/coverage_gap.py
CITYVIGIL_CACHE_MODE=replay python3 scripts/validate.py
CITYVIGIL_CACHE_MODE=replay python3 scripts/agent.py --show-trace

# With a key — exercises all four layers live and prints credits spent
python3 scripts/verify_live.py
```

`scripts/verify_live.py` is the direct demonstration: it queries all four analytic
types over one AOI, prints each layer's units and range, shows the audit trail with
the reason each layer was chosen, and reports credits consumed.

---

## 8. Summary of what we would tell FortyGuard

1. `tcm` tile units are Celsius; the quickstart docstring says Fahrenheit.
2. Heatmap credits are flat per call — worth documenting, since it inverts the
   obvious tiling strategy.
3. The 31-day `filter_type=4` cap is undocumented and fails in two different ways.
4. `persistence` appears saturated for 2026 windows in our AOI while 2024 behaves
   normally.
5. `time_of_measure` is not interpretable as an hour of peak under either timezone
   reading, and the documented UTC interpretation does not hold.

Items 4 and 5 look like genuine API issues rather than misuse. We would be glad to
supply the exact request payloads — they are in `data/cache/`, each stored with its
response.
