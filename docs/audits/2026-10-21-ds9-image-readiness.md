# DS9 image gateway readiness — task 7407

**NOT READY — image-provider authentication is missing.** Tested 2026-10-21
from inside `archie_platform` against the live DS9 gateway on port 20129.
No images were generated and no bulk portrait job was started.

## Observed results

| Request | HTTP | Result | Elapsed |
|---|---|---|---|
| Generate with `codex/gpt-image-2` | 400 | No credentials for image provider: codex | 0.038 s |
| Generate with `openai/gpt-image-1.5` | 400 | No credentials for image provider: openai | 0.024 s |

The active text app-server connection is not an image-provider credential.
DS9 has neither a Codex image connection nor an OpenAI image connection.
The unrestricted catalog returned 165 image-model entries, but no GPT Image IDs;
this was not merely filtering by a restricted client key.

A temporary diagnostic key had restricted models and the existing app-server
connection. `allowedEndpoints: ["images"]` required a subsequent key PATCH;
creation alone did not retain that restriction. The stored fields were checked.
A non-image request returned a model/path validation error before endpoint access
could be tested, so images-only enforcement is **not** proven by that response.
The diagnostic key was revoked afterward. It is not a Media Studio credential.

## Required next actions

1. The owner must choose and authenticate an image-capable provider through DS9's
   secure provider UI: a separate Codex ChatGPT OAuth connection or an OpenAI API
   connection. Do not paste credentials into chat or copy the owner's CLI auth.
   The existing app-server login does not satisfy this requirement.
2. Verify the authenticated provider's actual model catalog. The installed Codex
   image registry includes GPT Image 2 but not GPT Image 1.5; the OpenAI registry
   includes both. Do not claim subscription access to Image 1.5 without testing.
3. Mint a dedicated Media Studio inference key via `/api/keys`, using camelCase
   restrictions for only the selected image models and image-capable connection.
   PATCH its allowed endpoints to images, re-read the stored row, and demonstrate
   rejection of a valid text-model request on a non-image endpoint.
4. Rehearse at most the small image budget in the plan: generation, reference
   editing, model/size/quality/count handling, latency and useful errors. Record
   actual quota and policy outcomes; missing credentials are not a policy refusal.
5. Only after those gates pass should the Media Studio adapter work proceed.
   Do not restart the platform or scheduler while the portrait job is running.

Generation quality, reference editing, supported request combinations, image
latency, quota handling and content-policy behavior remain untested. No permanent
Media Studio key has been provisioned. Provider choice is pending owner input.

## Minimal generation example after authentication

Run inside the platform environment after securely provisioning the dedicated key
in its process environment. Set DS9_IMAGE_MODEL to a verified, authorized model.
Do not use the platform's shared management key.

```python
import os
import requests

response = requests.post(
    "http://host.docker.internal:20129/v1/images/generations",
    headers={"Authorization": "Bearer " + os.environ["DS9_IMAGE_API_KEY"]},
    json={
        "model": os.environ["DS9_IMAGE_MODEL"],
        "prompt": "A friendly fictional space-station botanist, portrait illustration",
        "size": "1024x1024",
        "n": 1,
    },
    timeout=180,
)
response.raise_for_status()
# Inspect/save the provider's response without logging credentials or image payloads.
result = response.json()
```

Local preflight evidence: `codex/patches/ds9-7407-image-preflight-final.json`
and `codex/patches/ds9-7407-image-catalog-metadata.json` in the originating
workspace. These contain diagnostic metadata, not usable credentials.
