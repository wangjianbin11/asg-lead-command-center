# n8n Workflows

The JSON files in `n8n-workflows/` are safe skeletons. They document triggers, payloads, and expected script boundaries. They do not contain production credentials.

## Workflow List

| File | Purpose |
|---|---|
| `01-manual-lead-import.json` | Receive manual lead payloads, clean, dedupe, and write to Lead Pool. |
| `02-lead-cleaning-dedup.json` | Periodically process `Status = New` leads. |
| `03-lead-scoring.json` | Score new or scoring-needed leads. |
| `04-outreach-draft-generation.json` | Generate review-only outreach drafts for A/B leads. |
| `05-reply-classification.json` | Classify pasted customer replies and suggest next action. |
| `06-daily-command-report.json` | Generate and post the daily command report. |
| `07-content-opportunity-generation.json` | Extract content opportunities from real daily signals. |

## Wiring Principle

n8n should call local scripts or webhooks, then write back to Feishu. Any external customer-facing action remains manual in V1.

