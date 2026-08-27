# CityVigil — project summary

**FortyGuard Hackathon'26** · Track 06 (Agentic AI), secondary Track 01 (Resilient
Cities & Infrastructure)

- **Live demo:** https://city-vigil.vercel.app
- **Repository:** https://github.com/Marvy247/CityVigil
- **API usage documentation:** [API_USAGE.md](API_USAGE.md)

---

## The problem

Phoenix publishes a Heat Relief Network of 264 sites every summer, and Maricopa
County still recorded 563 heat-associated deaths in 2023. Heat maps and generic
warnings already exist. What no one tells a city operations team is **which of their
existing decisions is failing, and which fix is cheap**.

## The finding

Central Phoenix spent **13.1 hours a day above 100 °F** during 1–7 August 2026 —
85.5 to 95.7 hours across the week, measured at 100 m resolution over 10,177 tiles.

Of the 110 indoor cooling sites in the network:

| Hour | Sites open | Share of peak |
|---|---|---|
| 15:00 | 103 | 100% |
| 17:00 | 69 | 67% |
| 18:00 | 48 | 47% |
| **19:00** | **25** | **24%** |
| 20:00 | 7 | 7% |

**Provision collapses exactly as the evening danger period begins.** By 19:00, when
it is still well above 100 °F outside, three-quarters of the network has closed.

That gap has two distinct causes, and CityVigil reports them separately because they
have completely different price tags:

- **Siting.** Only **14 of 57** tracts have a cooling site within an 800 m walk even
  at full capacity. Closing that needs new or relocated buildings.
- **Hours.** **9 tracts — 33,954 residents, 3.11M person-hours** — *have* walkable
  cooling in the afternoon and lose it by 19:00. Closing that needs **424 additional
  site-hours of staffing and no capital spend at all.**

Collapsing both into one "uncovered" figure would hide the free fix. That separation
is the project's central contribution.

## How it works

CityVigil runs on FortyGuard's Temperature API and three real federal/county
datasets, with no mocked inputs anywhere.

**1. Exposure.** `exceedance` returns a *count of hours* past a threshold. Multiplied
by the exposed population that is **person-hours** — in the API's own unit, with no
invented index in between. Across the study area: **18,407,328 person-hours above
100 °F**, of which 1.65M fall on residents aged 65+.

**2. Who is exposed.** 10,177 heat tiles joined to real census geography — all
10,177 matched, none dropped — across 57 of Maricopa County's 1,009 tracts (202,025
residents, 18,100 aged 65+, 54,070 jobs in outdoor-exposed sectors). Sources: CDC/ATSDR
SVI 2022, Census TIGERweb, LEHD LODES8 workplace counts.

**3. What protection exists.** The Maricopa Heat Relief Network's real site
locations, types and per-weekday opening hours. Coverage is evaluated *at a given
hour*, which is the difference between counting map pins and describing protection.

**4. What to do.** A what-if engine costs each remedy: extending hours (staffing) or
placing pop-up sites (capital), reported with the person-hours each recovers and an
explicit, tunable uptake assumption.

**5. An agent decides the sequence.** Six tools, a written rationale for every
decision, and real branch points: it stops early if there is no heat event, degrades
to a partial answer rather than failing when a source is missing, and **chooses which
remedy to cost based on which cause dominates**. On the live run it found closing
times explain only 18% of uncovered person-hours, declined to stop at the cheap fix,
and planned capacity as well. 17 steps, 7 decisions, fully visible in the UI.

The planner is a **deterministic policy, not an LLM** — deliberately. Layer selection
cannot be hallucinated, every decision is unit-tested, and the audit trail records
reasons that are actually the reasons.

## Validation — and an honest null

We tested the ranking against something it was never given: Maricopa County's
uncensored 2023 heat-death release, across 92 ZIPs of which 33 are high-mortality.

| Ranking by | AUC | 95% CI | Spearman vs counts | P@10 |
|---|---|---|---|---|
| **Heat exposure alone** | **0.824** | 0.724–0.911 | +0.561 | **0.80** |
| Vulnerability-weighted person-hours | 0.754 | 0.640–0.859 | **+0.571** | 0.60 |
| Person-hours (heat × population) | 0.696 | 0.574–0.806 | +0.465 | 0.60 |
| Population alone | 0.681 | 0.557–0.794 | +0.433 | 0.50 |

**Our vulnerability weighting is not validated. Plain heat exposure scores higher.**
Bootstrap intervals overlap, so the gap is not established either — but nothing here
supports claiming the weighting improves targeting, and we do not claim it.

What can be said: every ranking beats chance by a wide margin, and against *actual
death counts* the weighted model and heat alone are effectively tied (+0.571 vs
+0.561), so the vulnerability layer carries similar information rather than adding to
it. Adding population alone made things distinctly worse.

The outcome measure is also structurally hostile to the model: 77% of Maricopa heat
deaths occur outdoors and are recorded by *place of injury*, so the label largely
encodes where it is hottest outdoors rather than who is vulnerable indoors. The
discriminating test is the county's indoor subset, which is not published at ZIP
level in any source we could reach.

We report this because a tool that decides who gets protected should be held to
evidence, including when the evidence is unflattering.

## Contributions back to FortyGuard

Five API behaviours measured during development that the documentation does not
mention, all detailed in [API_USAGE.md](API_USAGE.md):

1. `tcm` tile readings are **Celsius**, not the Fahrenheit the quickstart documents.
2. Heatmap generation costs a **flat 4,220 credits per call regardless of area** — 81
   tiles and 10,177 tiles cost identically. This inverts the obvious tiling strategy.
3. `filter_type=4` ranges are **capped at 31 days**, undocumented, failing two
   different ways above it.
4. `persistence` returns a **saturated constant 8.0 h for every tile** across three
   separate 2026 windows, while 2024 windows vary normally.
5. `time_of_measure` is **not interpretable as an hour of peak** — 16–17 for a 2024
   window, 4–5 for 2026, reconcilable under neither timezone.

## Reproducibility

Every figure above can be reproduced with **no API key and no network**:

```bash
CITYVIGIL_CACHE_MODE=replay python3 scripts/analyze_phoenix.py
CITYVIGIL_CACHE_MODE=replay python3 scripts/coverage_gap.py
CITYVIGIL_CACHE_MODE=replay python3 scripts/validate.py
CITYVIGIL_CACHE_MODE=replay python3 scripts/agent.py --show-trace
python3 -m pytest                    # 280 tests
```

44 FortyGuard responses are committed to the repository, content-addressed and
gzipped. The deployed demo serves a static capture of the entire API surface, so it
runs with no backend and no credentials — and says so in the UI when it does.

## Known limits

- **One city, one week.** A deliberate scope decision. The FortyGuard layer works
  anywhere in the US; adding a city needs one per-state SVI and LODES source.
- Population is assumed uniform within a tract; coverage uses straight-line distance
  from tract centres, so coverage is optimistic and the gap understated.
- Cooling sites have no published capacity, so "covered" means open, not roomy.
- Worker exposure-hours are an unscheduled upper bound — LODES has no shift data.
- Vulnerability weights are a **stated prior, not a fitted result**, and every
  response echoes them alongside that caveat.

## What we would build next

The county's indoor-death subset, to run the test this outcome measure cannot
settle. Then a real allocation optimiser under capacity and dollar budgets, and
computing persistence ourselves to replace the layer that saturates.
