# ASG Lead Command Center

ASG Lead Command Center is the internal lead command center for ASG Dropshipping. V1 focuses on controlled lead intake, deduplication, scoring, outreach draft preparation, human review, sales follow-up logging, daily reporting, and content opportunity extraction.

This project is intentionally not a full SaaS and does not send outreach automatically. Feishu Base is the control surface, n8n is the workflow scheduler, and all AI-generated outreach stays in draft/review status until a salesperson approves it.

## V1 Scope

- Design Feishu Base tables for leads, contacts, scoring, outreach tasks, conversations, content opportunities, daily reports, and prompt versions.
- Import and clean leads from CSV, manual entry, or workflow payloads.
- Deduplicate by domain, email, source URL, and similar company names.
- Score leads with a structured ASG fit model.
- Generate review-only outreach drafts for Email, LinkedIn, WhatsApp, and website forms.
- Classify replies and recommend next actions.
- Generate daily command reports for the owner and sales team.
- Extract content opportunities from real customer pain points.

## Safety Rules

- No automatic mass email.
- No automatic LinkedIn, Facebook, Reddit, or Quora private messaging.
- No bypassing login, captcha, rate limits, or platform restrictions.
- No fabricated customer pain points, testimonials, or case studies.
- No AI draft can be sent without human review.
- No secrets are committed to the repository.

## Project Layout

```text
docs/             V1 specification, schemas, SOPs, architecture, compliance.
prompts/          Versioned prompts with JSON output requirements.
n8n-workflows/    Importable workflow skeletons for n8n.
scripts/          Local Python tools for Feishu, cleaning, dedupe, scoring, reports.
data-samples/     Safe sample data for local testing.
tests/            Unit tests for core local logic.
dashboard/        Future dashboard notes. V1 uses Feishu as the dashboard.
```

## Local Verification

```bash
cd /Users/janson/Documents/自动化/asg-lead-command-center
python3 -m unittest discover -s tests
python3 scripts/clean_leads.py data-samples/sample_leads.csv
python3 scripts/generate_daily_report.py --sample
```

## Feishu Client Example

The Feishu client reads credentials from environment variables and does not hard-code table IDs.

```bash
export FEISHU_APP_ID=...
export FEISHU_APP_SECRET=...
export FEISHU_BASE_APP_TOKEN=...
export FEISHU_LEAD_TABLE_ID=...

python3 scripts/feishu_client.py doctor
python3 scripts/feishu_client.py list-records --table-id "$FEISHU_LEAD_TABLE_ID" --limit 5
```

For this first implementation, run the client only after you intentionally provide credentials. Tests do not call the real Feishu API.

