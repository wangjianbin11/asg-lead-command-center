# ASG Lead Command Center — V1 Build-out Design & Contracts

Date: 2026-06-21
Status: Approved (user said 继续 / continue)
Author: Claude Code (system architect)

This document is the **single source of truth** for the multi-agent build-out. Every
agent reads this file plus the referenced docs before writing code, so that file
paths, function signatures, JSON field names, and safety rules stay aligned.

## 0. Ground rules (non-negotiable)

1. Work ONLY in `/Users/janson/Documents/自动化/asg-lead-command-center` (absolute paths).
2. Read `docs/02-feishu-base-schema.md` and `docs/00-project-spec.md` for field names and rules.
3. Field names in payloads MUST match `docs/02` exactly (e.g. `Lead ID`, `ASG Fit Score`, `Approval Status`, `Send Status`, `Priority`, `Status`).
4. Outreach drafts are **draft-only**: `Approval Status = Pending Review`, `Send Status = Not Sent`. Never auto-send.
5. No real Feishu calls unless credentials are explicitly configured. No hardcoded secrets / table ids.
6. No AI API call unless a key is present. If absent, fall back to a deterministic local rule/heuristic and set `review_needed = True`.
7. AI output must be parsed as JSON and validated; on failure, mark for human review (never crash the pipeline).
8. Stdlib only (urllib, csv, json, argparse). Python 3.9 compatible. No third-party imports.
9. Each agent owns its files exclusively — do not edit files owned by another agent (see §6 ownership table).
10. After writing, each agent runs `python3 -m py_compile <file>` and its own unit test and reports the result. Do not run the full suite.

## 1. Goal & scope

Take the existing scaffold to a locally-verifiable V1: a working lead pipeline
(CSV → clean → dedupe → score → outreach drafts), Feishu base setup/doctor,
reply classification, content-opportunity extraction, daily report, hardened
importable n8n workflows, and a full test suite.

### Locally completable now
All scripts, all tests, n8n JSON hardening, full dry-run acceptance.

### Blocked (hand off with exact commands — do NOT fake)
- **B1. Live Feishu `ensure` of 8 tables** — needs user's `FEISHU_APP_ID / APP_SECRET / BASE_APP_TOKEN`.
- **B2. n8n import verification** — host has no `n8n` and no `docker`.

## 2. File-by-file contracts

### A1 — `scripts/prompt_utils.py` (NEW, no deps, shared by A2/A3/A4)
Public API (exact names):
- `load_prompt(rel_path: str) -> str` — read `prompts/<rel_path>` from repo root (Path(__file__).resolve().parents[1]).
- `render_prompt(template: str, variables: dict) -> str` — replace `{{key}}` tokens; leave unknown tokens as-is.
- `extract_json(raw: str) -> dict` — strip ```json fences / prose, `json.loads`, raise `ValueError` if not a dict.
- `build_ai_envelope(prompt: str, provider: str = "", model: str = "") -> dict` — request body dict (no secrets inside body; key used only in header at call time).
- `has_ai_key() -> bool` — True iff `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` set.
- `call_ai(prompt: str, provider: str = "", model: str = "", timeout: float = 60.0) -> str` — if no key, raise `AIConfigError("no AI API key configured")`. Calls OpenAI Chat Completions (`https://api.openai.com/v1/chat/completions`) when provider=openai/OPENAI_API_KEY set, or Anthropic Messages (`https://api.anthropic.com/v1/messages`) when provider=anthropic/ANTHROPIC_API_KEY set. Returns the raw text content. Use urllib only.
- Exceptions: `class AIConfigError(RuntimeError)`, `class AIRuntimeError(RuntimeError)`.
- Read keys from env: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEFAULT_AI_PROVIDER` (default "openai"), `DEFAULT_MODEL` (default "").
- **Self-test**: `python3 -m py_compile scripts/prompt_utils.py` and a tiny inline check that `extract_json('```json\n{"a":1}\n```')` == `{"a":1}`.

### A2 — `scripts/run_lead_pipeline.py` (NEW; deps: A1, clean_leads, dedupe_leads, score_leads, generate_outreach, feishu_client, config)
Public API:
- `generate_lead_id(index: int, date_str: str) -> str` → `LEAD-YYYYMMDD-0001` (zero-padded 4).
- `run_pipeline(csv_path: str, *, client=None, dry_run: bool = True, write_feishu: bool = False, ai_enabled: bool | None = None) -> dict`.
  - Returns `{"summary": {...counts...}, "leads": [...], "scores": [...], "outreach_tasks": [...], "dry_run": bool}`.
Steps (in order):
  1. Read CSV rows (`csv.DictReader`).
  2. `clean_leads.clean_rows(rows)`.
  3. `dedupe_leads.dedupe_rows(cleaned)`; non-duplicates proceed.
  4. Assign `Lead ID`; build Lead Pool field dicts (fields per docs/02 §6.1). If `write_feishu` and client: `client.create_record(lead_table, fields)`.
  5. For leads with `Status == "New"`: score. If AI enabled (key present and not overridden off): build prompt via `prompt_utils`, call AI, `score_leads.validate_scoring_output(score_leads.parse_ai_json(raw))`. On any AI error / JSON failure → fall back to `score_leads.local_heuristic_score(lead)` and set `review_needed=True`. If AI disabled → use `local_heuristic_score` directly with `review_needed=True`.
  6. Build Lead Scoring field dicts (docs/02 §6.3). If write_feishu: write to score table.
  7. Update Lead Pool fields `ASG Fit Score`, `Priority`, `Status` (Status → "Scored"). If write_feishu: `client.update_record`.
  8. For Priority A/B leads that have a usable contact (email/linkedin/whatsapp present in row OR a contact dict): `generate_outreach.build_outreach_task(...)` → Outreach Task dict (Approval=Pending Review, Send=Not Sent). If write_feishu: write to outreach table.
- CLI: `--input PATH` (required), `--dry-run` (default on; mutually exclusive with `--write-feishu`), `--write-feishu`, `--no-ai` (force heuristic). When `--dry-run`, print JSON summary and do NOT touch Feishu even if a client exists.
- `ai_enabled` resolution: True iff `--no-ai` not set AND `prompt_utils.has_ai_key()`.
- Module importable without env vars (no side effects at import).
- **Self-test**: `python3 -m py_compile`, then `python3 -m unittest tests.test_run_pipeline`.

### A3 — `scripts/classify_reply.py` (NEW; deps: A1)
- `REPLY_INTENTS = {"Inquiry","Quote Request","Objection","Not Interested","Need More Info","Meeting Request","Complaint","Cooperation","Other"}` (matches docs/00 §8.5).
- `URGENCIES = {"High","Medium","Low"}`.
- `validate_reply_output(payload: dict) -> dict` — ensure keys `intent, urgency, summary, customer_need, recommended_next_action, suggested_reply, should_follow_up, next_followup_days`; coerce types; intent/urgency must be in allowed sets (default Unknown→"Other"/"Medium"); Quote Request → force urgency High.
- `rule_based_classify(reply_text: str) -> dict` — keyword fallback when no AI key; set review flags.
- `classify_reply(reply_text: str, context: dict | None = None, ai_enabled: bool | None = None) -> dict` — AI if key+enabled (load `prompts/sales/reply-classifier-v1.md`), else rule-based. Always run through `validate_reply_output`.
- CLI: `--reply TEXT` prints validated JSON.
- **Self-test**: compile + `tests.test_classify_reply`.

### A4 — `scripts/generate_content_opportunities.py` (NEW; deps: A1)
- `PAIN_POINTS = {"Supplier","Shipping","QC","Packaging","MOQ","Price","Scaling"}`.
- `extract_from_pain_signals(signals: list[dict]) -> list[dict]` — each output dict preserves `source_lead_id` and/or `source_conversation_id`, plus `Pain Point`, `Topic`, `Search Intent`, `Recommended Format`, `Priority`, `Draft Brief`. (Fields per docs/02 §6.6.)
- `extract_content_opportunities(records: list[dict], source_type: str = "lead", ai_enabled: bool | None = None) -> list[dict]` — AI via `prompts/content/content-opportunity-extractor-v1.md` when enabled, else rule-based grouping of pain points. Every opportunity MUST carry a non-empty source id.
- CLI: `--input PATH` (JSON of records) prints list JSON.
- **Self-test**: compile + `tests.test_content_opportunities`.

### A5 — `scripts/setup_feishu_base.py` (NEW; deps: feishu_client)
- `TABLES` module-level dict: 8 tables keyed by logical name (`lead, contact, score, outreach, conversation, content, report, prompt`) → `{"name": "...", "fields": [ {name, type}, ... ]}` mirroring docs/02 exactly. Use Feishu Bitable field-type ints: `1`=Text, `2`=Number, `3`=SingleSelect, `4`=MultiSelect, `5`=DateTime, `7`=Checkbox, `11`=Person/User, `13`=Phone, `15`=URL/Link, `18`=Email. For Relation/lookup/other uncertain types, **default the type to `1` (Text)** and add `"note": "..."` rather than guess — correctness over completeness. `doctor` checks field *presence by name*; type perfection is not required for the blocked live step.
- `ensure(client) -> dict` — list existing tables; for each logical table, create if missing (POST `/bitable/v1/apps/{app_token}/tables` with `{table:{fields, name}}`); collect `table_id` per logical name. Idempotent.
- `doctor(client, *, live: bool = False) -> dict` — report: token presence, app_token presence, 8 tables present?, per-table key-field presence. `--live` also fetches a tenant token.
- `write_local_config(table_ids: dict, path="config/feishu_tables.local.json")` — write ids locally (gitignored).
- CLI subcommands: `doctor [--live]`, `ensure`, `ensure --dry-run`. Print JSON.
- Never print secrets.

### A6 — `scripts/generate_daily_report.py` (EXTEND existing; only A6 edits this file)
- Keep `compute_metrics`, `render_markdown`, `sample_payload`, `--sample`.
- ADD `--input PATH` to load a JSON file `{"leads":[...], "outreach_tasks":[...], "conversations":[...]}` and render the report from it.
- ADD `--feishu` flag stub: if set without a configured client, raise a clear `ConfigError` ("Feishu wiring requires credentials"); do NOT silently call the API.
- Keep stdlib-only; no new third-party deps.

### A7 — config files + `.gitignore` (only A7 edits `.gitignore`)
- `config/feishu_tables.example.json` — the 8-table schema (names + field specs) with NO ids. (Mirror A5.TABLES.)
- `config/feishu_tables.local.json.example` — template with empty `table_id` fields for the user to fill.
- `.gitignore`: add `config/*.local.json` (keep `*.example.json` and `*.local.json.example`). Keep existing entries.

## 3. Test matrix (required cases — spec acceptance §7)

| Case | File | Status |
|---|---|---|
| URL normalization | tests/test_clean_leads.py | extend if needed |
| Source URL preserves path | tests/test_clean_leads.py | extend if needed |
| domain dedup | tests/test_dedupe_leads.py | extend if needed |
| email dedup | tests/test_dedupe_leads.py | extend if needed |
| score→priority | tests/test_score_leads.py | extend if needed |
| AI JSON parse | tests/test_score_leads.py | extend if needed |
| Feishu pagination fake transport | tests/test_feishu_client.py | exists — keep |
| pipeline dry-run | tests/test_run_pipeline.py | NEW (A2) |
| prompt JSON schema | tests/test_prompt_output_schema.py | extend if needed |
| n8n JSON parse | tests/test_n8n_json.py | NEW (dedicated) |
| classify_reply rule fallback | tests/test_classify_reply.py | NEW (A3) |
| content opportunity source id preserved | tests/test_content_opportunities.py | NEW (A4) |

The audit-tests agent ensures 1–7,9 are fully covered; A2/A3/A4 own their new tests;
a dedicated agent writes test_n8n_json.py.

## 4. n8n workflow contracts (one agent per file)

For each `n8n-workflows/0X-*.json`:
- Keep `"name"`, `"active": false`, `"settings": {"executionOrder": "v1"}`.
- Nodes MUST include: (a) a **trigger** (manualTrigger / scheduleTrigger / webhook), (b) an **executeCommand** or **httpRequest** node calling the relevant `python3 scripts/<script>.py ...`, (c) a **success path** writing back to Feishu (HTTP node) or outputting a report, (d) an **error path** — an `n8n-nodes-base.execute`/set + the workflow's `errorTrigger` or an explicit error-handling node, (e) any secret via `$env`/credentials, never literal.
- Map: 01→clean+import (scripts/clean_leads.py, run_lead_pipeline.py dry-run), 02→dedup (dedupe_leads.py), 03→scoring (score_leads.py / pipeline), 04→outreach (generate_outreach.py), 05→reply (classify_reply.py), 06→daily report (generate_daily_report.py --sample), 07→content (generate_content_opportunities.py).
- MUST pass `python3 -m json.tool <file>` (valid JSON).
- Add `"meta": {"asg_boundary": "..."}` describing boundary (draft/no-auto-send).

## 5. Acceptance commands (run by orchestrator after Workflow)

```
cd /Users/janson/Documents/自动化/asg-lead-command-center
python3 -m unittest discover -s tests
python3 scripts/feishu_client.py doctor
python3 scripts/run_lead_pipeline.py --input data-samples/sample_leads.csv --dry-run
python3 scripts/generate_daily_report.py --sample
python3 -m compileall -q scripts tests
```
(Live variants gated on user credentials — documented as blockers.)

## 6. File ownership (no overlapping writes)

- A1: scripts/prompt_utils.py
- A2: scripts/run_lead_pipeline.py, tests/test_run_pipeline.py
- A3: scripts/classify_reply.py, tests/test_classify_reply.py
- A4: scripts/generate_content_opportunities.py, tests/test_content_opportunities.py
- A5: scripts/setup_feishu_base.py
- A6: scripts/generate_daily_report.py
- A7: config/feishu_tables.example.json, config/feishu_tables.local.json.example, .gitignore
- AUDIT: tests/test_clean_leads.py, test_dedupe_leads.py, test_score_leads.py, test_feishu_client.py, test_prompt_output_schema.py
- N8NTEST: tests/test_n8n_json.py
- C1..C7: n8n-workflows/01..07-*.json (one each)
