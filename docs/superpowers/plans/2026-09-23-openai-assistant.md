# GPT-6 Sol assistant implementation plan

## Goal and constraints

Replace the deterministic UI helper with the requested external OpenAI Responses API (`gpt-6-sol`). Keep calculations local, launch with `node server.mjs`, add no dependencies, keep secrets exclusively in server environment. No external enrichment; roles remain hypotheses and scores remain calculated by the pipeline.

## Implementation

- [x] Build `src/assistant-context.mjs`: whitelist anonymized calculated fields, select bounded graph context, preserve exact string GIDs and witnessed common recipients. Test privacy, bounds and unknown IDs.
- [x] Build `src/openai-assistant.mjs`: validate input, read environment key, POST Responses API with strict JSON schema and `store:false`, validate cited GIDs, map errors without upstream secrets. Test successful mocked request, missing key, malformed output and API errors.
- [x] Extend `server.mjs`: status and assistant endpoints, JSON size limit, same-origin restriction, one concurrent request, no key exposed.
- [x] Change `src/app.js` and `index.html`: real asynchronous server call, progress/errors, clickable GIDs, external transmission disclosure, configuration status.
- [x] Update README with secure PowerShell environment setup, endpoint contract and context/model limitations. Run Node and Python suites. Documentation publication coordinated with the concurrent README task.

## Verification

22 Node tests and 5 Python tests passed. Browser verified graph loading and missing-key configuration message on the updated server. An independent review caught missing dataset-scope metadata; fixed and regression-tested. Live OpenAI response remains unverified until the user sets the server environment key and restarts the server.

## Review focus

Unknown IDs must not select another node silently. No personal or arbitrary fields enter context. Truncated context is disclosed. Unavailable key/API/model never triggers a fake local AI answer. Client-side events cannot issue duplicate requests while waiting. Live verification requires the user's server environment key.
