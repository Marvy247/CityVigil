# CityVigil — Build Plan

Autonomous protective intelligence for extreme heat. Decides who gets protected
first when cooling resources are scarce, and reports both the human and the
estimated economic consequence of each choice.

## Verified platform facts

Everything below was read from the official quickstart
(`FortyGuard-Tech/temperature-api-quickstart`) and the hackathon site, not assumed.

| Fact | Value | Consequence for CityVigil |
|---|---|---|
| Base URL | `https://api.fortyguard.com` | — |
| Auth | `api-key` request header | — |
| Pattern | async: `POST /v1/<endpoint>` → `activity_id` → poll `GET /v1/status/{id}` | Every call needs submit+poll+timeout handling |
| Status 404 right after submit | eventual consistency | Must retry, not fail |
| Billing | credits charged only on `Completed`; failed tasks free | Cache aggressively; failures are cheap |
| Endpoints | `/v1/heatmap`, `/v1/env_params`, `/v1/satellite`*, `/v1/streetview`*, `/v1/heat_intelligence`*, `/v1/status/{id}`, 2× `/v1/system/fetch-api-key-*usage` | *Premium tier only — do not put them on the critical path |
| `analytic_type` | `tcm`, `time_of_measure`, `exceedance`, `persistence` | The four analysis layers |
| `exceedance` | **count of hours** past threshold — NOT degree-hours | Maps directly onto our primary metric |
| `persistence` | longest **continuous run** of such hours | Overnight non-relief risk |
| `threshold` | **°C**, while `tcm` tiles report `average/min/max_temperature` | Mixed-unit trap — handled explicitly |
| `granularity` | 60, 80 or 100 metres | Site markets ~20 m²; the API exposes 60–100 m |
| `filter_type` | 1=single hour, 2=hour range, 3=single day, 4=day range (+`end_date`) | Wrong value = wrong question answered |
| Max range span | **31 days** (measured, undocumented) | Longer analyses must be split into month windows |
| Coverage | United States only | AOI guard rejects non-US early |
| Time range | 2021-01-01 → now, forecast ≤ 12 h ahead | **Our 6–48 h claim is not sourceable from the API** |

### Two facts that change the original concept

1. **The 48-hour horizon does not exist.** Forecast is capped at 12 hours. We
   either stay inside that window or build our own extension trained on
   2021→present history and label it as ours. Plan does the latter (Phase 5).
2. **`exceedance` returns hours above a threshold.** That is *literally*
   person-hours of exposure once multiplied by population. Our headline metric
   becomes a native API unit rather than an invented score. This is the single
   luckiest alignment in the project and the pitch should lean on it.

### Measured cost model (this changes the spatial strategy)

Heatmap generation costs a **flat 4,220 credits per call**, independent of area
or tile count. Measured directly:

| AOI | Tiles returned | Credits | Per tile |
|---|---|---|---|
| 1.1 km² @ 100 m | 81 | 4,220 | 52.1 |
| 101.7 km² @ 100 m | 10,177 | 4,220 | 0.415 |

Consequences:

* **Never tile a city into small AOIs.** Always request the largest footprint the
  plan allows (~129.5 km²). Small AOIs waste credits by a factor of 100+.
* Budget is ~468 heatmap calls from the 2,000,000-credit hackathon grant.
* Full Phoenix metro (~1,340 km²) at one time window ≈ 11 calls ≈ 46k credits.
  A multi-day, multi-layer backtest is therefore comfortably affordable.
* Large AOIs take longer (70 s for 10k tiles vs 22 s for 81), so the async
  polling budget matters more than the credit budget.
* **`filter_type=4` ranges are capped at 31 days.** Undocumented; found by probing.
  31 days succeeds, 32 fails as a task error, and 46 or 53 days are rejected at
  submit with a 500. Probing cost nothing, because failed tasks are free. A
  May-September season analysis must be assembled from month-sized windows.

## Competitive reality

A GitHub scan of the hackathon cohort shows the "agentic heat triage" concept is
already occupied — `TeamXOF/HeatSentinel` describes layering hyperlocal data
against population vulnerability and resource gaps to rank who needs help first,
which is CityVigil's core loop. Also present: several cool-route planners, worker
safety agents, and heat command centres.

So novelty cannot be the differentiator. **Verification is.** Nobody else is
likely to backtest against a real historical heatwave and publish the error bars.
That is where we win Technical Execution (35%) and Impact (40%).

## Architecture

Four layers, bottom-up. Each is independently testable.

```
                    ┌──────────────────────────────┐
                    │  Interfaces: CLI / API / UI  │
                    └──────────────┬───────────────┘
                    ┌──────────────▼───────────────┐
                    │  Agent loop (real branching)  │
                    └──────────────┬───────────────┘
        ┌──────────────────────────┼──────────────────────────┐
   ┌────▼─────┐             ┌──────▼──────┐            ┌──────▼──────┐
   │ Exposure │             │ Allocation  │            │  Impact &   │
   │ + Vuln.  │             │ optimiser   │            │  economics  │
   └────┬─────┘             └─────────────┘            └─────────────┘
   ┌────▼──────────────────────────────────────────────────────────┐
   │ Foundation: FG client · guards · units · cache · audit log    │  ← Phase 1
   └───────────────────────────────────────────────────────────────┘
```

## Phases

**Phase 1 — Foundation. DONE.** Typed API client with submit-and-poll, retry, and
404-tolerance. Pre-flight guards that refuse invalid requests *before* spending
credits. Explicit unit handling for the °C/°F split. Content-addressed gzipped
disk cache so the whole system replays offline with zero credits. Audit log that
records every layer choice and its rationale from the very first call.

**Phase 2 — Exposure surface. DONE.** The four analytic types are wrapped in
intent-named functions (`how_hot`, `when_peak`, `how_long_dangerous`,
`any_relief`), each recording *why* it was selected. Tile grid exports to GeoJSON.

**Phase 3 — Real vulnerability data. DONE.** No mocks. CDC/ATSDR SVI 2022 at tract
level, LEHD LODES8 workplace counts for outdoor workers, Census TIGERweb tract
polygons, and the Maricopa Heat Relief Network for cooling-centre supply. All
cited, SHA-256 pinned in `data/sources/manifest.json`, joined to heat tiles by a
dependency-free point-in-polygon index. 1,009 Maricopa tracts, 4,430,871
residents; 57 tracts and 202,025 residents inside the Phoenix study area, with all
10,177 tiles matched and none dropped.

Supply is now included, which turns the output from a demand map into an unmet-need
map. Constraint discovered and documented: the Heat Relief Network service
publishes only the **current season**, so it cannot describe what was open during
the 2024 episode. It is used strictly for the counterfactual "where would today's
network leave gaps during an event like that one".

**Phase 4 — Allocation + economics.** Equity-weighted person-hours of exceedance
avoided, maximised under capacity constraints. Economic parameters live in one
cited TOML file with ranges; every output carries a sensitivity band. Uptake /
compliance is an explicit tunable, never hidden.

**Phase 5 — Forecast extension.** Our own short-horizon model trained on
2021→present, evaluated honestly against persistence and climatology baselines.
Clearly labelled as CityVigil's model, not FortyGuard's.

**Phase 6 — Validation. DONE, with a negative result.** Tested against Maricopa
County's uncensored 2023 heat-death release (137 ZIPs, 563 deaths, real zeros) using
July 2023 exposure over 24 AOI tiles, aggregated to 92 ZIPs with 33 high-mortality.

| Ranking | AUC | 95% CI | rho vs counts | P@10 |
|---|---|---|---|---|
| Heat alone | **0.824** | 0.724-0.911 | +0.561 | 0.80 |
| Vulnerability-weighted | 0.754 | 0.640-0.859 | +0.571 | 0.60 |
| Heat x population | 0.696 | 0.574-0.806 | +0.465 | 0.60 |
| Population alone | 0.681 | 0.557-0.794 | +0.433 | 0.50 |

**The weighting did not clear the baseline; heat alone scored higher.** Intervals
overlap so neither direction is established, but the claim that weighting improves
targeting is unsupported and is not made. On actual counts the two are effectively
tied (+0.571 vs +0.561), so the vulnerability layer carries similar information to
heat rather than adding to it.

Method upgrades over the first attempt: uncensored counts instead of a binary
above-threshold test, Spearman correlation against real magnitudes, and bootstrap
confidence intervals so differences are not over-read.

Diagnosis rather than excuse: 77% of Maricopa heat deaths occur outdoors and are
recorded by place of injury, so the label mostly encodes where it is hottest
outdoors. The discriminating experiment is the indoor subset, unavailable at ZIP
level.

Do not claim validated targeting improvement. Claim a substantially
better-than-chance ranking, a real and quantified cooling-hours gap, and an honest
null on the weighting.

**Phase 7 — Agent loop.** Genuine decision points: which layer answers this
question, whether to zoom, what to do when a task returns empty, when to
escalate. The tool-call trace is a first-class visible output.

**Phase 8 — Surfaces + submission.** Map UI, exports (GeoJSON / briefing / alert
drafts), 2–5 min video, written summary, `fortyguard` added as repo collaborator.

## Non-negotiables

- No fabricated inputs presented as real. Synthetic data is labelled synthetic.
- No single-point economic figures. Ranges with cited coefficients only.
- Every number traceable to the API call and parameters that produced it.
- Offline replay must always work, so judges can run it without a key.
- Scope discipline: one city, one heat event, one decision type, done properly.
