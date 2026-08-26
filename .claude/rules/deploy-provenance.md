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

## Dependabot scans the MANIFEST, not the ARTIFACT (2026-08-26, KB #296224)

The image-baked trap has a third door, and this one actively reports success.

**On an image-baked product, merging a Dependabot bump patches the file GitHub scans
and leaves the image that runs untouched.** Measured: `standalone/media_hub/requirements.txt`
carried `cryptography==50.0.0` from 2026-08-05 (`141decb85`, Dependabot PR #2568, merged)
while `mediahub_app` ran **48.0.1** — because the image was built **2026-07-30, six days
before the bump**. The alert closed. Nothing was patched.

⚠️ **A repo can show ZERO open Dependabot alerts while every image in the fleet is months
behind.** Alert count measures manifests. It says nothing about what is running.

`deploy_drift_check.py` already caught this one — media_hub sat at `🔴 DRIFT`, baked
`aae737a86` vs expected `141decb85`, and that expected SHA *is* the cryptography commit.
**Two independent systems reported it and neither caused a rebuild**, because a drift row
and a closed alert each look like someone else's problem.

The only comparison that means anything:

```bash
grep '^<pkg>' <product>/requirements.txt                                  # what was REQUESTED
docker exec <container> python3 -c "import <pkg>; print(<pkg>.__version__)"  # what RUNS
```

⚠️ **A version in a manifest is a request, not an observation.** In this same session
"media_hub already runs 50.0.0" was asserted off the manifest and used as safety evidence
for the bump; the container printed 48.0.1 and nothing in the fleet had ever run 50.0.0.
Verify a new pin against a real interpreter (`docker run --rm python:3.12-slim`) before
relying on it.

**Also grep for the vulnerable API before treating a CVSS score as a severity.** CVE-2026-69247
scored 8.2, and `pkcs7_decrypt`/`PKCS7`/`EnvelopedData`/`smime` appear nowhere in this repo —
`archie-browser` uses `cryptography` for Fernet only. Exposure was nil. Bump anyway so the
alert closes honestly, but size the urgency from the call sites, not the score.


## The OTHER half: volume-mounted hub code — a merge deploys NOTHING

Everything above is about image-baked products, where the risk is a stale image. The hub has
the opposite hazard and it is not obvious.

`archie_platform` and `archie_scheduler` **bind-mount the working tree**:

```
/mnt/archie_brain/platform_v2  ->  /app   (rw)
```

So they execute **whatever branch is checked out on the host right now** — not `origin/main`,
not the merge commit. Two consequences, and both bit on 2026-08-20:

**1. Merging on GitHub deploys nothing.** PRs #2718/#2721 were merged, `origin/main` advanced,
and the containers went on running the feature branch that was still checked out. Verifying with
`git log origin/main` said "shipped"; the container disagreed:

```
ImportError: cannot import name 'is_permanent_auth_failure' from 'tools.email_manager.idle_worker'
```

**`git checkout main && git pull --ff-only` IS the deploy step for hub code.** Then restart the
affected container — Python modules are already imported, so a file change alone changes nothing
in a running process (templates and static JS are re-read per request, but browsers cache the JS).

**2. While you sit on a feature branch, the LIVE platform is running your branch.** That is how
live-testing an unmerged change works here at all — and it is also why an unmerged, half-finished
edit is served to every user of the hub until you switch back. Prefer short-lived branches, and
return to `main` when you stop working on one.

### Verify through the RUNNING process, never through git

`git log` describes the repository. The question is what the container has loaded:

```bash
# does the running process actually have the symbol?
docker exec archie_scheduler python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.email_manager.idle_worker import is_permanent_auth_failure
print('live:', is_permanent_auth_failure('[AUTHENTICATIONFAILED] x'))"

# or, for a route: read the SOURCE the process has, not the file on disk
docker exec archie_platform python3 -c "
import sys, inspect; sys.path.insert(0,'/app')
import tools.repair_bay.github_routes as m
print('verdict_refusal' in inspect.getsource(m))"
```

⚠️ **`grep` on the file — even inside the container — is not this check.** The bind mount means
the file is always current; the *imported module* may not be. On 2026-08-20 host and container
greps both matched at the same line number while the running route still returned the old
payload. Same family as the image-baked drift above: the artifact is not the source.

## In the merge flow
`merge-pr` **Step 7.5** rebuilds the affected product from `main` + runs the drift check + re-verifies
the merged features **together** (not the stale per-branch checks). Never skip it for an image-baked change.

## Rolling out to a new product
Add the Dockerfile ARG/ENV + compose `build.args` + `/version` route, add the product's `/version`
URL to `PRODUCTS` in `deploy_drift_check.py`, and deploy via `deploy_with_sha.sh`. Open follow-ups:
watch-products `/version` adoption + a Repair Bay "Deploy Provenance" tab + a scheduled
`deploy_drift_monitor` observer job (tasks under project #385).
