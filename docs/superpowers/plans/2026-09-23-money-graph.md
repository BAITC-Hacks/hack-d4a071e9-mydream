# Money Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Build a reproducible local AML analyst workflow from three parquet files to explainable roles, clusters, ranked leads, CSV exports and a searchable directed graph.

**Architecture:** A Python batch pipeline calculates graph and transaction features, assigns hypotheses and exports CSV/JSON. A dependency-free Node server hosts the dashboard and starts a repeatable local rebuild. The browser reads JSON and lets the analyst inspect any gid.

**Tech Stack:** Python, pandas, pyarrow, networkx, scikit-learn if used for anomaly detection; Node.js standard library; browser HTML/CSS/JavaScript.

**Spec:** [Track 02 case](https://docs.google.com/document/d/1JPLU-G6R25Ge2hVaY2J9cqvrx7FGExj87XKwJPaMz3o/edit?usp=sharing) and `track02/materials/dataset-README.md`.

## Global Constraints

- Inputs are `nodes.parquet`, `edges.parquet`, `transactions.parquet`; no external enrichment or client identity claims.
- Outputs are `nodes_roles.csv`, `clusters.csv`, `top_nodes.csv`, plus JSON for the dashboard.
- Role labels are `consolidator`, `transit`, `distributor`, `terminal`, `coordinator`, `peripheral`.
- Full run must finish within five minutes; the app must start with `node server.mjs`.
- The observations stop at depth 4 and show only outgoing paths from 81 seeds; missing edges are not proof of terminal behavior.
- Run `node --test` after changes.

## Review Focus

- An isolated seed with no edges must still appear in `nodes_roles.csv` and search.
- A depth 4 node with no outgoing edges must carry a truncation warning instead of an unqualified terminal claim.
- Every CSV must have the exact required header and the nodes CSV must include all 2 248 gids.
- Arbitrary gids should open a card even if absent from the visible graph overview.
- Rebuild errors should be surfaced in the interface without silently showing stale output.

---

### Task 1: Data and reproducible pipeline

**Files:** `track02/data/*`, `track02/pipeline.py`, `track02/requirements.txt`, `tests/pipeline*`.

**Interfaces:** Consumes three parquet files. Produces three specified CSVs and `network.json` with `nodes`, `edges`, `clusters`, `top`, `meta` arrays/object.

- [ ] Verify input row counts, columns and totals against the supplied dataset README.
- [ ] Write a failing test for exact CSV headers, all 2 248 nodes, at least 20 top nodes and bounded evidence.
- [ ] Implement explainable directed graph features, role rules, clusters and priority calculation.
- [ ] Check clipped depth 4 and seed nodes in a failing test; implement explicit data gap critique.
- [ ] Run the complete dataset and record elapsed time and output invariants.

### Task 2: Local service and analyst interface

**Files:** `server.mjs`, `index.html`, `styles.css`, `src/app.js`, `tests/server.test.mjs`.

**Interfaces:** `GET /api/health`, `GET /api/network`, `POST /api/rebuild`, and three `GET /api/export/…` routes. The UI consumes the Task 1 JSON contract.

- [ ] Write a failing local HTTP test for status, app page and unknown export.
- [ ] Serve only needed static files; execute the pipeline locally on rebuild.
- [ ] Render top leads, clusters, directed role colored graph and arbitrary gid search.
- [ ] Show evidence and data limits in the selected node card.
- [ ] Run `node --check` and `node --test`.

### Task 3: Reproduction and demonstration

**Files:** `README.md`, `PITCH.md`, `HACKATHON.md`, `package.json`, `.vscode/tasks.json`.

**Interfaces:** A fresh user follows setup instructions, runs the app, rebuilds results, verifies CSVs and repeats the same main scenario.

- [ ] Document Python setup, exact commands, source and output schemas, and limits of interpretation.
- [ ] Describe the AI or agentic component only to the extent verified by implementation.
- [ ] Check the evaluator criteria against the UI, pipeline and README.
- [ ] Run the full main scenario and all automated tests.
- [ ] Publish the verified local files to the user supplied `test-arman` branch using the authenticated GitHub connection.
