# Deploying to Vercel (demo from cache)

The deployment ships the local `data/` folder (caches and finished runs) with the code. Portfolios already analysed
locally replay instantly; new analyses run inside one streamed request and reuse every cached company and country.

## How it differs from a local server

| | Local (`uvicorn`) | Vercel |
|---|---|---|
| Data | `./data` | `data/` shipped with the deploy, copied to `/tmp/data` per instance (`core/config.py`) |
| New analysis | background task, page polls `/runs/<id>/events` | runs inside `POST /runs/stream`, progress streamed (`STREAM_RUNS=1`) |
| Filing deadlines | none (reads everything to the end) | 45 s filings / 60 s filing text (a request stops after 300 s on Hobby) |
| What a run saves | kept | kept on that instance only, lost on redeploy or a cold start |

## 1. Fill the cache locally

With the patches applied, run each portfolio you want to demo once through the local app (same profile settings you
will use in the demo), until it replays on the second submit. Only runs made after `run-cache.patch` are indexed for
reuse (`data/runs/index/`).

## 2. Deploy with the CLI (not Git)

`data/` is gitignored, so a Git deployment would ship no cache. The CLI uploads the folder on disk; `.vercelignore`
keeps `.env`, tests and traces out.

```bash
npm i -g vercel                 # CLI >= 54.17.2 for --dry
vercel link                     # once, from polyfinances-datathon/
vercel deploy --dry             # check: data/ included, no .env, total well under 500 MB
vercel env add SEC_IDENTITY     # "Your Name you@domain.com"
vercel env add AWS_ACCESS_KEY_ID
vercel env add AWS_SECRET_ACCESS_KEY
vercel env add AWS_SESSION_TOKEN   # only for temporary credentials; they expire, update before the demo
vercel env add AWS_REGION
vercel env add BEDROCK_MODEL_ID    # if not the default
vercel deploy --prod
```

Dependencies are ~410 MB (pyarrow, pulled in by edgartools, is 165 MB) plus ~30 MB of cache: under the 500 MB Python
limit, without much room. Keep `data/traces` out (already in `.vercelignore`).

## Limits of the demo

- A new analysis must finish in 300 s. Companies not read within the deadlines count as unknown for that run.
- New runs and new cache entries live on one instance's `/tmp`: another instance or a redeploy does not see them.
  To make them permanent, run the analysis locally and redeploy.
- "Refresh scenarios" on a report starts a background job: unreliable on Vercel.
- For a fully live deployment, set `STORAGE=s3` (caches in S3) and move run state off local disk.
