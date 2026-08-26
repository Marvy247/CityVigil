# Deploying the demo

The submission needs a live demo link. This describes the two ways to get one, and
why the default is the boring one.

## The constraint

The dashboard normally talks to a FastAPI service that holds a FortyGuard API key.
**That service cannot be exposed publicly.** It has no authentication, so an open
instance would let anyone spend the key's credits. Putting it behind a public URL
as-is would be handing out the key.

## Option A — static frontend only (recommended)

The whole API surface is captured to static JSON under
`dashboard/public/snapshot/`. When no live API is reachable, the client falls back
to it and shows a banner saying so. The deployed site is fully functional, contains
no credentials, and costs nothing to run.

Every figure in the snapshot is real — it comes from the committed FortyGuard
response cache. What it cannot do is respond to changed parameters, and the banner
says exactly that.

Regenerate after any data change:

```bash
CITYVIGIL_CACHE_MODE=replay python3 scripts/export_snapshot.py
```

Deploy the `dashboard/` directory to any static-capable host. On Vercel:

```bash
cd dashboard
npx vercel --prod
```

Set **Root Directory** to `dashboard` in the project settings. No environment
variables are required — leaving `NEXT_PUBLIC_CITYVIGIL_API` unset means the client
tries localhost, fails immediately, and falls back to the snapshot, which is the
desired behaviour for a public deployment.

## Option B — also deploy the API in replay mode

Genuinely interactive for any window already in the cache, and still ships no key,
because `CITYVIGIL_CACHE_MODE=replay` never calls FortyGuard. Requests for
uncached windows return a clear 409 explaining why, which doubles as a live
demonstration of the agent's degraded path.

```bash
# On the API host
CITYVIGIL_CACHE_MODE=replay \
CITYVIGIL_ALLOWED_ORIGINS=https://your-dashboard.vercel.app \
python3 scripts/serve.py
```

Then point the frontend at it:

```bash
NEXT_PUBLIC_CITYVIGIL_API=https://your-api-host npm run build
```

Notes if you take this route:

- Keep `CITYVIGIL_CACHE_MODE=replay`. In `live` mode a public instance spends real
  credits on every request.
- Do **not** set `FORTYGUARD_API_KEY` in the deployment. Replay mode does not need
  it, and its absence is the guarantee.
- `scripts/serve.py` binds to `127.0.0.1`. A host that needs `0.0.0.0` should run
  uvicorn directly, and only with replay mode set.
- Add the deployed origin to `CITYVIGIL_ALLOWED_ORIGINS`. The CORS list is
  explicit on purpose; there is no wildcard.

## Verifying either option

```bash
# Frontend serves and falls back with no API running
cd dashboard && npm run build && npm run start
curl -s -o /dev/null -w "%{http_code}\n" localhost:3000/dashboard
curl -s -o /dev/null -w "%{http_code}\n" localhost:3000/snapshot/api_agent.json
```

Both should return 200 with nothing listening on port 8000.
