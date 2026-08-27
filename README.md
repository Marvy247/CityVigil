# CityVigil

**Live demo: https://city-vigil.vercel.app** · **[Project summary](SUMMARY.md)** · **[API usage](API_USAGE.md)** — runs from a committed snapshot of
real FortyGuard responses, so it needs no API key and no backend.

Protective intelligence for extreme heat. Decides who gets protected first when
cooling resources are scarce, and reports both the human and the estimated
economic consequence of each choice.

Built on the [FortyGuard Temperature API](https://docs-api.fortyguard.com) for
FortyGuard Hackathon'26. Primary track: **06 — Agentic AI**. Secondary:
Resilient Cities & Infrastructure.

> **Status: Phases 1–3 of 8 complete.** The API foundation, guards, caching,
> audit trail, exposure explorer UI, and the **real vulnerability data join** are
> built, tested and verified. Allocation, economics, the forecast extension and the
> historical backtest are specified in [`PLAN.md`](PLAN.md) but not yet built.
> Nothing in this repo reports a number it cannot source, and no population data
> is mocked.

## What works today

Four FortyGuard analysis layers over a 101.7 km² study area in central Phoenix,
each selected by the *question it answers* rather than by its API name, with the
reasoning recorded as the call is made.

| Question | Layer | Real result (Phoenix, 1–7 Aug 2026, >100 °F) |
|---|---|---|
| How hot is it? | `tcm` | 38.8 – 39.3 °C across 10,177 tiles |
| When does it peak? | `time_of_measure` | 4–5 — **not usable**, see below |
| How long is it dangerous? | `exceedance` | 85.5 – 95.7 hours (13.1 per day) |
| Is there any relief? | `persistence` | flat 8.0 h in 2026; 6.8 – 8.3 h in the 2024 window |

That last pair is the point. Both are hours; they are not interchangeable. A block
logging 91 dangerous hours that cools every night is a different emergency from one
that never cools, and ranking on the total alone systematically under-protects the
areas where heat actually kills.

**Two measured API caveats, reported rather than hidden:**

- `persistence` returns a saturated **flat 8.0 h for every tile** across three
  separate 2026 windows, which cannot be a real spatial field. The 2024 reference
  window returns 6.79–8.27 h and varies sensibly, so the relief distinction is
  demonstrated there (`phoenix-2024` in the city registry).
- `time_of_measure` is **not usable as an hour of peak**. It returned 16–17 for the
  2024 window and 4–5 for 2026. Neither timezone reading reconciles those: as local
  time 4–5 is pre-dawn, as UTC it is 21:00–22:00 local. CityVigil therefore does not
  use it for scheduling, and says so.

### Who gets protected first — from real data, not mocks

Those tiles are joined to **1,009 real Maricopa County census tracts** and ranked
by vulnerability-weighted person-hours:

| Measure | Value |
|---|---|
| Tracts intersecting the study area | 57 |
| Residents covered | 202,025 (18,100 aged 65+) |
| Jobs in outdoor-exposed sectors | 54,070 |
| Tiles joined to a tract | 10,177 of 10,177 (0 unmatched) |
| **Person-hours above 100 °F** | **18,407,328** |
| Of which borne by residents aged 65+ | 1,650,153 |
| Vulnerability-weighted person-hours | 11,232,238 |

Person-hours are not an invented index. `exceedance` returns *hours past a
threshold*; multiplying by the residents exposed gives person-hours in the API's
own units.

The weighting demonstrably changes the answer. Tract 04013114900 ranks **35th by
raw exposure and 18th once who lives there is counted** — a 17-place promotion.
The dashboard shows both orderings side by side, because presenting a weighted
metric without the unweighted one hides the modelling choice inside the headline.

## Data sources

All real, all cited, all publicly published.

| Source | Contributes |
|---|---|
| CDC/ATSDR **SVI 2022** (Arizona) | Tract population, residents 65+, below 150% poverty, no vehicle, disability, uninsured, and CDC's overall percentile |
| Census **TIGERweb** | Tract polygons for the spatial join |
| LEHD **LODES8 WAC 2021** | Jobs by NAICS sector *at the workplace*, so outdoor workers are counted where they work, not where they sleep |
| Maricopa **Heat Relief Network** | Cooling, respite and hydration sites with per-weekday opening hours and ADA access |

`data/sources/manifest.json` records the URL, byte size and SHA-256 of every file,
so any result can be tied to the exact bytes behind it.

## The finding that matters most

Cooling capacity collapses exactly as the evening danger period begins.

Central Phoenix averaged **13.1 hours per day above 100 °F** during the study
episode, so the dangerous window runs well into the evening. But of the 110 indoor
cooling sites in the network:

| Hour | Sites open | Share of peak |
|---|---|---|
| 15:00 | 103 | 100% |
| 17:00 | 69 | 67% |
| 18:00 | 48 | 47% |
| **19:00** | **25** | **24%** |
| 20:00 | 7 | 7% |

The gap has two distinct causes, and CityVigil reports them separately because
they have different price tags:

- **Siting.** Only **14 of 57** tracts have a walkable cooling site even at full
  capacity. Fixing that needs new or relocated sites.
- **Hours.** **9 tracts — 33,954 residents, 3.11M person-hours** — have walkable
  cooling in the afternoon and lose it by 19:00. Fixing that needs later closing
  times and no capital spend at all.

Collapsing both into one "uncovered" number would have hidden the cheap fix. That
is the whole argument for the tool.

## Validation against recorded deaths

Everything above is a model. `scripts/validate.py` tests it against something it
was never given: where people actually died of heat.

Maricopa County publishes heat-associated deaths by ZIP code. Counts below the
disclosure threshold are suppressed with `-999` — 116 of 140 ZIPs are censored and
the smallest published count is 6. That rules out a death-rate regression, but it
defines a clean **binary test**: did this ZIP record at least 6 heat deaths? A
suppressed ZIP is *known* to be below the threshold, so a negative label is an
observation rather than missing data.

### The result

Validated against Maricopa County's **2023** heat-death release, which publishes
uncensored counts — 137 ZIPs, 563 deaths, real zeros. The 2022 release suppressed
116 of 142 ZIPs, which is what made the earlier version of this test statistically
weak. July 2023 exposure across 24 AOI tiles, aggregated to 92 ZIPs of which 33 are
high-mortality:

| Ranking by | AUC | 95% CI | Spearman vs counts | P@10 |
|---|---|---|---|---|
| **Heat exposure alone** | **0.824** | 0.724–0.911 | +0.561 | **0.80** |
| Vulnerability-weighted person-hours | 0.754 | 0.640–0.859 | **+0.571** | 0.60 |
| Person-hours (heat × population) | 0.696 | 0.574–0.806 | +0.465 | 0.60 |
| Population alone | 0.681 | 0.557–0.794 | +0.433 | 0.50 |

**The vulnerability weighting is not validated, and plain heat exposure scores
higher.** On the binary test heat alone leads by 0.070 AUC and finds 8 of the top 10
high-mortality ZIPs against the weighted model's 6. The bootstrap intervals overlap,
so the gap is not established either — but nothing here supports claiming the
weighting improves targeting, and we do not claim it.

One nuance worth stating: against *actual death counts* rather than the binary
label, the two are effectively tied (+0.571 weighted, +0.561 heat alone). So the
vulnerability layer is not noise — it carries similar information to heat exposure
rather than adding to it.

Three things belong next to that:

- **Every ranking beats chance by a wide margin** (0.68–0.82 against 0.5). The
  system is not guessing.
- **Adding population alone made things worse** (0.696 vs 0.824). Weighting by
  vulnerability recovered most of that loss but did not surpass the baseline.
- **The outcome measure is structurally hostile to this model.** 77% of Maricopa
  heat deaths occur outdoors and are recorded by *place of injury*, so the label
  largely encodes where it is hottest outdoors — not who is vulnerable indoors. A
  residence-based vulnerability index is being graded on a test it cannot win.

The discriminating test is the county's **indoor** death subset (23% of deaths),
where residence-based vulnerability should predict and heat alone should not. It is
not published at ZIP level in the sources we reached.

### Other limits, printed with every result

- 33 high-mortality ZIPs of 92 is a modest sample; bootstrap intervals are reported
  for every candidate so small AUC gaps are not over-read.
- Tracts are assigned to ZIPs by centre containment, which is approximate.
- Exposure uses July only, because the API caps ranges at 31 days, while deaths
  accrue across the whole May–September season.
- The study region covers 60% of recorded deaths. Extending to 80% would need 72 AOI
  tiles over mostly empty desert for little added signal.
- One year, one county. Nothing here shows the ranking transfers.

## Quick start

```bash
# 1. Backend
python3 -m pip install -r requirements.txt
cp .env.example .env          # add FORTYGUARD_API_KEY
python3 scripts/fetch_data.py # download CDC / Census / LODES / HRN sources (~8 MB)
python3 scripts/serve.py      # http://127.0.0.1:8000

# 2. Frontend, in another shell
cd dashboard && npm install && npm run dev   # http://localhost:3000/dashboard
```

Run without an API key by serving the committed responses:

```bash
CITYVIGIL_CACHE_MODE=replay python3 scripts/serve.py
```

Verify the whole stack and print the audit trail:

```bash
python3 scripts/verify_live.py                              # all four layers, live
CITYVIGIL_CACHE_MODE=replay python3 scripts/analyze_phoenix.py  # full ranking, offline
CITYVIGIL_CACHE_MODE=replay python3 scripts/coverage_gap.py      # cooling gap, offline
python3 -m pytest                                           # 201 tests, no network
```

## How it is built

```
src/cityvigil/
  units.py          C/F handling — never guesses, refuses ambiguity
  guards.py         pre-flight validation; rejects bad requests before spending credits
  cache.py          content-addressed gzipped responses; offline, credit-free replay
  audit.py          append-only trail; layer choices require a written rationale
  fg_client.py      submit-and-poll client with retry, caching and auditing
  layers.py         question-shaped access to the four analytics + GeoJSON export
  cities.py         study areas, sized to the plan's area cap
  geometry.py       dependency-free point-in-polygon, area, and a grid index
  sources.py        external dataset registry with citations and SHA-256 provenance
  tracts.py         CDC + TIGERweb + LODES joined into tract profiles
  vulnerability.py  the weighted indicator model, with every component exposed
  exposure.py       person-hours at risk and the priority ranking
  supply.py         cooling-site hours, walkable coverage, and the unmet-need gap
  api.py            HTTP API the dashboard consumes
dashboard/          Next.js 15 + Tailwind + shadcn/ui + MapLibre
```

### Design decisions worth defending

**Guards run before the network.** A request that returns a plausible answer to
the wrong question is worse than one that is rejected, so `filter_type`
companions, the 2021 archive floor, the 12-hour forecast ceiling, US-only
coverage, granularity and threshold units are all checked locally first. Errors
name the offending field so the caller can repair rather than retry.

**Units are never inferred silently.** The API takes `threshold` in Celsius while
tile readings are Celsius too — despite the official quickstart docstring
describing them as Fahrenheit. Verified live: Phoenix on 2024-07-15 returned a
mean of 36.06, which is 97 °F. Inference is attempted only where it is provably
safe and raises otherwise.

**CDC's missing-value sentinel is −999, not NaN.** Eighteen Maricopa tracts carry
`RPL_THEMES = -999`. Read naively that is a vulnerability percentile of minus nine
hundred, which would silently dominate the index. Those tracts fall back to
component indicators with the weights renormalised, and are flagged in the UI.

**No geopandas.** The only spatial operation needed is point-in-polygon, which is
about 150 lines. Adding a compiled GDAL/PROJ toolchain to a project whose whole
credibility argument is "clone it and run it" was the wrong trade. The area
function is validated against a known quantity: summed tract areas come to
23,798 km² against Maricopa County's actual 23,889 km², a 0.4% error.

**Vulnerability weights are visible and adjustable.** Defaults put 0.50 on CDC's
published composite, 0.30 on the 65+ share and 0.20 on outdoor-worker density.
They are a stated prior, *not* fitted to heat-outcome data, and every response
echoes the weights used plus that caveat. The API accepts different weights and
the ranking changes accordingly.

**Every layer choice carries a written reason.** `AuditLog.layer_choice` rejects
an empty rationale. If a caller cannot say why `exceedance` rather than `tcm`,
that is the reasoning gap the organisers warned about.

**Replay is a first-class mode.** Cached responses are committed, so the project
runs with no key, no credits and no network. A demo that only works on the
author's machine is not evidence.

## Measured API facts

Full detail, including five undocumented behaviours we measured, is in
**[API_USAGE.md](API_USAGE.md)** — the submission's "documentation of FortyGuard
API usage".

Established by direct measurement, not assumption:

- **Heatmap cost is flat at 4,220 credits per call**, independent of area. An
  81-tile 1.1 km² AOI and a 10,177-tile 101.7 km² AOI cost exactly the same.
  Therefore: always request the largest footprint the plan allows; never tile a
  city into small AOIs. Doing so wastes credits by a factor of 100+.
- Granularity is selectable at 60/80/100 m. The ~20 m figure in the marketing
  material is not an accepted parameter value.
- `exceedance` returns a **count of hours** past the threshold, not degree-hours.
  Multiplied by exposed population that is person-hours directly, so the headline
  metric is in the API's own units rather than an invented index.
- **`filter_type=4` ranges are capped at 31 days**, which is undocumented. 31 days
  succeeds, 32 fails as a task error, 46 and 53 are rejected at submit. Found by
  probing, which cost nothing because failed tasks are free. Longer periods must be
  assembled from month-sized windows.
- Large AOIs are slow rather than expensive: 70 s for 10k tiles vs 22 s for 81.
  Budget polling time, not credits.
- Failed tasks are free; credits are charged only on completion.

## Honest limitations

- **Cooling-site data is the current season, not 2024.** The Heat Relief Network
  service publishes no historical snapshots. Coverage results are the counterfactual
  "where would today's network leave gaps during an event like July 2024", never a
  claim about what was actually open then.
- **Coverage uses straight-line distance from a tract's centre.** Street-network
  distance is longer, typically 20–40%, so coverage is overstated and the gap
  understated. A large tract can also have its centre far from a site while its
  edge is next door.
- **Opening hours are hand-entered free text.** Sites whose hours cannot be parsed
  are treated as closed, because overstating availability in a heat-safety tool is
  the more dangerous error. All 110 cooling sites parsed cleanly.
- **`time_of_measure` timezone is unresolved.** The quickstart calls it a UTC hour.
  Measurement disagrees: it returns 16–17 for Phoenix, while `env_params` reports
  `GMT-7` with apparent temperature peaking at 15:00 local. A UTC reading would put
  the peak at 09:00 local, which is not credible in July. CityVigil treats it as
  local and applies no conversion, but flags the ambiguity rather than hiding it.
- **No site capacity data.** The network publishes locations and hours but not how
  many people each site can hold, so "covered" means a site exists and is open, not
  that it has room.
- **Population is assumed uniform within a tract.** Tracts are the finest geography
  with published age and poverty counts, and nothing says where inside one people
  live. Under that assumption a tract's total is exactly `population × mean hours`,
  which is how it is computed. A tract total is therefore far more reliable than
  any claim about a single tile.
- **Vulnerability weights are a prior, not a finding.** They were not fitted to
  heat-mortality data. Reasonable people would choose differently, which is why
  they are configurable and echoed with every result.
- **Outdoor-worker hours are an unscheduled upper bound.** LODES has no shift
  information, so attributing the full window to workers overstates real exposure.
  The figure is reported separately and never folded into the resident total.
- **The outdoor-sector proxy is imperfect.** NAICS 11/21/22/23/48-49 over-counts
  warehouse staff in cooled buildings and under-counts outdoor work in retail,
  services and landscaping.
- **No allocation or economics yet.** When they arrive, economic figures will be
  ranges from a cited parameter file with sensitivity analysis, never single
  headline numbers, and the uptake assumption will be explicit and tunable.
- **The forecast horizon is 12 hours, not 48.** The original concept overstated
  this. Longer horizons must come from CityVigil's own model trained on
  2021→present history, clearly labelled as ours (Phase 5).
- **No cooling-centre supply data yet.** The ranking says where need is greatest,
  not where capacity already exists. Until published centre locations and hours are
  joined, this is a demand map, not a gap map.
- **US coverage only.** Non-US AOIs are rejected before the request is sent.
- **Not validated against a real response.** Phase 6 backtests one historical
  heatwave against a uniform-distribution baseline and against what the city
  actually did, and publishes the deltas including unflattering ones. Until then
  the ranking is a defensible model, not a demonstrated improvement.

## Security

The API service has **no authentication** and holds your FortyGuard key, so it
binds to `127.0.0.1` only. Do not expose it publicly as-is — an open instance
lets anyone spend your credits. Put an authenticating proxy in front of it if it
ever needs to be reachable. `.env` is git-ignored; the committed cache contains
temperature responses only, no credentials.

## Attribution

Temperature data © FortyGuard. Vulnerability and geography data from CDC/ATSDR and
the US Census Bureau (public domain; see `/api/sources` for full citations).
Basemap tiles © OpenStreetMap contributors, © CARTO. The `dashboard/` directory
began as a Next.js starter template.
