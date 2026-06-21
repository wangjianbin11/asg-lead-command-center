# Codex Task List

## Task 1: Feishu Client

Status: implemented in `scripts/feishu_client.py`.

Requirements:
- Get tenant access token.
- Read records.
- Create records.
- Update records.
- Support pagination.
- Handle errors clearly.
- Use environment variables.
- Do not hard-code any table ID.

## Task 2: Lead Cleaner

Build and maintain `scripts/clean_leads.py`.

Requirements:
- Normalize URLs.
- Extract domains.
- Detect missing fields.
- Standardize country and platform values.
- Return structured JSON.

## Task 3: Lead Deduplication

Build and maintain `scripts/dedupe_leads.py`.

Requirements:
- Detect duplicate domains.
- Detect duplicate emails.
- Detect similar company names.
- Return duplicate type and master lead ID.

## Task 4: AI Lead Scoring

Build and maintain `scripts/score_leads.py`.

Requirements:
- Read new leads from Feishu.
- Load prompt from `prompts/lead-scoring/lead-scoring-v1.md`.
- Call AI API only when credentials are explicitly configured.
- Validate JSON.
- Write scoring result to Feishu.
- Update lead priority and status.

## Task 5: Outreach Draft Generator

Build and maintain `scripts/generate_outreach.py`.

Requirements:
- Read A/B leads with contact info.
- Select prompt by channel.
- Generate outreach draft.
- Write to Outreach Task.
- Set `Approval Status = Pending Review`.
- Never send the message automatically.

## Task 6: Daily Report Generator

Build and maintain `scripts/generate_daily_report.py`.

Requirements:
- Collect daily metrics.
- Generate concise boss report.
- Write to Daily Report table.
- Output markdown summary.

## Task 7: Tests

Create tests for:
- URL normalization.
- Domain extraction.
- Deduplication.
- AI JSON validation.
- Score to priority mapping.
- Feishu pagination behavior with a fake transport.

