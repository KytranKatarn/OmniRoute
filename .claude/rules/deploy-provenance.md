# Deploy Provenance — stamp the commit, deploy from main, monitor for drift

**Why this exists:** every standalone is image-baked (`COPY .` in the Dockerfile), so a
running container reflects **only the branch it was last built from**. Deploy two feature
branches to the same production container and the second rebuild silently reverts the first.
"Verified live" on a branch goes stale the instant another branch is built. This bit us for
real: project #385 shipped 5 PRs, each deployed on its own branch — the live `mediahub_app`
ended up with only the last one until it was rebuilt from integrated `main`. Same family as
the recurring watch-products drift (`reference_watch-products-deploy-drift`, KB #275549):
**the deployed artifact ≠ the git source.** Root cause + full write-up: KB mistake **#279350**.

## The three rules (all image-baked products: media_hub, wtf, gov/market/legal/civic, kbs, kso)

1. **Deploy the production container ONLY from a clean, integrated `main`.**
   Feature-branch smoke-tests use a throwaway image tag / container — never the prod
   container name. Enforced by `scripts/deploy_with_sha.sh` (refuses a non-main / dirty tree
   unless `ALLOW_DIRTY_DEPLOY=1`).

2. **Stamp the commit into every image and expose it at `/version`.**
   - Dockerfile (near the end, so a changing SHA doesn't bust the COPY/pip cache):
     ```dockerfile
     ARG GIT_SHA=unknown
     ARG BUILD_TIME=unknown
     LABEL org.opencontainers.image.revision="$GIT_SHA" org.opencontainers.image.created="$BUILD_TIME"
     ENV <PRODUCT>_GIT_SHA=$GIT_SHA <PRODUCT>_BUILD_TIME=$BUILD_TIME
     ```
   - compose `build.args: {GIT_SHA: ${GIT_SHA:-unknown}, BUILD_TIME: ${BUILD_TIME:-unknown}}`.
   - App: `GET /version → {product, git_sha, build_time}` (open, non-sensitive — mirrors `/health`).
   - Deploy with `scripts/deploy_with_sha.sh <compose-dir> <service>` (exports `GIT_SHA`+`BUILD_TIME`
     from git, then `up -d --build`). Media Hub is the reference implementation.

3. **Monitor for drift** with `scripts/deploy_drift_check.py` — compares each product's `/version`
   baked SHA against `origin/main` HEAD and alerts through A.R.C.H.I.E. (`POST /api/internal/notify`,
   Bearer `INTERNAL_API_KEY`, Telegram) on a concrete mismatch. **Fail-open:** unreachable /
   unstamped ("unknown") is never counted as drift. Endpoints are env-overridable (the hub
   host→own-published-port hairpin is unreliable under `userland-proxy=false`).

## In the merge flow
`merge-pr` **Step 7.5** rebuilds the affected product from `main` + runs the drift check + re-verifies
the merged features **together** (not the stale per-branch checks). Never skip it for an image-baked change.

## Rolling out to a new product
Add the Dockerfile ARG/ENV + compose `build.args` + `/version` route, add the product's `/version`
URL to `PRODUCTS` in `deploy_drift_check.py`, and deploy via `deploy_with_sha.sh`. Open follow-ups:
watch-products `/version` adoption + a Repair Bay "Deploy Provenance" tab + a scheduled
`deploy_drift_monitor` observer job (tasks under project #385).
