#!/usr/bin/env bash
# Build the commit history in the order the project was actually developed:
# foundation first, then data layers, then analysis, then interfaces.
# One commit per logical unit — no padding.
set -euo pipefail
cd "$(dirname "$0")/.."

c() { # c "<message>" <paths...>
  local msg="$1"; shift
  git add -- "$@" 2>/dev/null || true
  if git diff --cached --quiet; then
    echo "  skip (nothing staged): $msg"
  else
    git commit -q -m "$msg"
    printf '  %-3s %s\n' "$(git rev-list --count HEAD)" "$msg"
  fi
}

echo "Building commit history…"

# ── Foundation ───────────────────────────────────────────────────────────────
c "chore: project scaffold, gitignore and dependency pins" .gitignore requirements.txt pytest.ini .env.example
c "docs: build plan with verified FortyGuard API facts" PLAN.md
c "feat(errors): split exception hierarchy into our faults and theirs" src/cityvigil/errors.py
c "feat(units): explicit C/F handling that refuses to guess" src/cityvigil/units.py
c "test(units): cover the mixed C/F trap and the -999-style sentinels" tests/test_units.py

# ── Guards ───────────────────────────────────────────────────────────────────
c "feat(guards): pre-flight validation so bad requests never reach the API" src/cityvigil/guards.py
c "test(guards): assert every rejection happens before a credit is spent" tests/test_guards.py

# ── Cache and provenance ─────────────────────────────────────────────────────
c "feat(cache): content-addressed gzipped response cache for offline replay" src/cityvigil/cache.py
c "test(cache): digest stability, replay mode and atomic writes" tests/test_cache.py
c "feat(audit): append-only trail that requires a rationale per layer choice" src/cityvigil/audit.py
c "feat(config): environment-driven settings with optional dotenv" src/cityvigil/config.py

# ── API client ───────────────────────────────────────────────────────────────
c "feat(client): guarded, cached, audited submit-and-poll client" src/cityvigil/fg_client.py
c "test(client): 404 window, retries, task failure and cache reuse" tests/test_client.py

# ── Layers ───────────────────────────────────────────────────────────────────
c "feat(layers): question-shaped access to the four analysis layers" src/cityvigil/layers.py
c "test(layers): reject a tcm payload parsed as exceedance" tests/test_layers.py
c "feat(cities): study-area registry sized to the plan area cap" src/cityvigil/cities.py

# ── Geometry ─────────────────────────────────────────────────────────────────
c "feat(geometry): dependency-free point-in-polygon, area and grid index" src/cityvigil/geometry.py
c "test(geometry): holes, concave shapes and a known county area" tests/test_geometry.py

# ── Real data ────────────────────────────────────────────────────────────────
c "feat(sources): external dataset registry with SHA-256 provenance" src/cityvigil/sources.py
c "feat(tracts): join CDC SVI, TIGERweb geometry and LODES workplace counts" src/cityvigil/tracts.py
c "feat(vulnerability): transparent weighted model with stated priors" src/cityvigil/vulnerability.py
c "feat(exposure): person-hours at risk from exceedance hours and population" src/cityvigil/exposure.py
c "test(exposure): person-hours arithmetic and the rank-shift comparison" tests/test_exposure.py

# ── Supply ───────────────────────────────────────────────────────────────────
c "feat(supply): cooling-site hours, walkable coverage and the unmet-need gap" src/cityvigil/supply.py
c "test(supply): clock parsing, hydration exclusion and the evening collapse" tests/test_supply.py

# ── Validation ───────────────────────────────────────────────────────────────
c "feat(validation): AUC against recorded heat deaths, censoring handled" src/cityvigil/validation.py
c "test(validation): verdict reports a null result plainly" tests/test_validation.py

# ── Service layer ────────────────────────────────────────────────────────────
c "feat(api): HTTP service exposing surfaces, exposure, supply and coverage" src/cityvigil/api.py
c "feat(core): package exports" src/cityvigil/__init__.py

# ── Scripts ──────────────────────────────────────────────────────────────────
c "feat(scripts): live verification across all four analysis layers" scripts/verify_live.py
c "feat(scripts): fetch and fingerprint the external datasets" scripts/fetch_data.py
c "feat(scripts): rank Phoenix tracts by vulnerability-weighted person-hours" scripts/analyze_phoenix.py
c "feat(scripts): cooling coverage gap, siting versus hours" scripts/coverage_gap.py
c "feat(scripts): validate the ranking against recorded heat deaths" scripts/validate.py
c "feat(scripts): local development server bound to localhost" scripts/serve.py
c "chore(scripts): commit history builder" scripts/build_history.sh

# ── Cached evidence ──────────────────────────────────────────────────────────
c "data: committed API responses so the project replays with no key" data/cache
c "data: CDC SVI 2022 for Arizona" data/sources/svi_arizona_2022.csv
c "data: Census TIGERweb tract boundaries for Maricopa County" data/sources/tracts_maricopa.geojson
c "data: LEHD LODES8 workplace area characteristics" data/sources/az_wac_S000_JT00_2021.csv.gz
c "data: Maricopa Heat Relief Network cooling sites" data/sources/hrn_sites.geojson
c "data: recorded heat deaths by ZIP code, 2022" data/sources/heat_deaths_zip_2022.geojson
c "data: source provenance manifest with SHA-256 digests" data/sources/manifest.json

# ── Frontend: config and primitives ──────────────────────────────────────────
c "chore(dashboard): Next.js project configuration" dashboard/package.json dashboard/package-lock.json dashboard/pnpm-lock.yaml dashboard/tsconfig.json dashboard/next.config.js dashboard/postcss.config.js dashboard/components.json dashboard/next-env.d.ts dashboard/.gitignore
c "feat(dashboard): light-first design tokens and Tailwind theme" dashboard/tailwind.config.js dashboard/app/globals.css
c "feat(dashboard): root layout with self-hosted fonts for offline builds" dashboard/app/layout.tsx
c "feat(dashboard): shadcn/ui primitives" dashboard/components/ui dashboard/hooks dashboard/lib/utils.ts dashboard/components/theme-provider.tsx
c "chore(dashboard): static assets" dashboard/public

# ── Frontend: CityVigil surface ──────────────────────────────────────────────
c "feat(dashboard): typed API client and per-layer colour ramps" dashboard/lib/cityvigil.ts
c "feat(dashboard): MapLibre heat surface with native 3D extrusion" dashboard/components/cityvigil/HeatMap.tsx
c "feat(dashboard): layer picker labelled by the question each layer answers" dashboard/components/cityvigil/LayerPicker.tsx
c "feat(dashboard): provenance panel exposing the recorded rationale" dashboard/components/cityvigil/ProvenancePanel.tsx
c "feat(dashboard): protection priority table with weighted-versus-raw ranks" dashboard/components/cityvigil/PriorityPanel.tsx
c "feat(dashboard): compose the exposure explorer" dashboard/components/cityvigil/CityVigilDashboard.tsx
c "feat(dashboard): mount CityVigil on the dashboard route" dashboard/app/dashboard/page.tsx dashboard/components/dashboard-layout.tsx dashboard/components/dashboard-overview.tsx

# ── Frontend: landing ────────────────────────────────────────────────────────
c "feat(landing): hero stating the cooling-hours gap" dashboard/components/landing/HeroSection.tsx
c "feat(landing): the four analysis layers as questions" dashboard/components/landing/LayersSection.tsx
c "feat(landing): capability cards including the honest validation result" dashboard/components/landing/FeaturesSection.tsx
c "feat(landing): about section and headline figures" dashboard/components/landing/AboutSection.tsx
c "feat(landing): pipeline walkthrough with real measurements" dashboard/components/landing/DemoSection.tsx
c "feat(landing): navbar, footer and data attribution" dashboard/components/landing/Navbar.tsx dashboard/components/landing/Footer.tsx
c "feat(landing): particle field recoloured for a light background" dashboard/components/landing/ShaderBackground.tsx
c "feat(landing): landing route and sign-in placeholder" dashboard/app/page.tsx dashboard/app/login/page.tsx

# ── Docs ─────────────────────────────────────────────────────────────────────
c "test: shared fixtures emulating the async API and its 404 window" tests/conftest.py
c "docs: README with measured API facts and honest limitations" README.md

# Anything not explicitly staged above.
c "chore: remaining project files" .

echo
echo "Total commits: $(git rev-list --count HEAD)"
