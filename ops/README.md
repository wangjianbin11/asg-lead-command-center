# Deploying ASG Lead Command Center to the n8n server

n8n runs in a **Docker container** on the host. The container filesystem is
**ephemeral** (lost on restart) and has none of the ASG secrets, so the scripts
+ `.env` must live on the **HOST** and be **mounted** into the container. Secrets
stay in the mounted `.env`; the workflows `source` it at runtime, so they **never
enter the n8n database or workflow JSON**.

## Operator steps (run on the n8n HOST — the machine running the n8n container)

### 1. Get the code + create `.env`
```bash
# (first time only) authenticate to GitHub on the host, e.g.:
#   gh auth login   OR   set up a SSH key / PAT for wangjianbin11
git clone https://github.com/wangjianbin11/asg-lead-command-center.git /srv/asg-lcc
bash /srv/asg-lcc/ops/deploy-on-host.sh /srv/asg-lcc
# Now edit /srv/asg-lcc/.env and fill in the real secrets:
#   FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_BASE_APP_TOKEN /
#   FEISHU_*_TABLE_ID / ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / DEFAULT_MODEL
```
Drop real lead CSVs at `/srv/asg-lcc/inbox/leads.csv` (the scoring workflow reads
this inside the container at `/home/node/asg-lcc/inbox/leads.csv`).

### 2. Mount it into n8n
In n8n's `docker-compose.yml`, under the n8n service `volumes:`, add:
```yaml
      - /srv/asg-lcc:/home/node/asg-lcc
```
Then recreate n8n so the mount takes effect:
```bash
docker compose up -d --force-recreate n8n   # or: docker restart <n8n-container>
```

### 3. Tell Claude n8n has been recreated
Claude then activates the read/generate workflows and runs one verification
execution end-to-end.

## What is already done (no host access needed)
- Code on GitHub (private): `wangjianbin11/asg-lead-command-center`
- The 7 n8n workflow source files rewired to run at `/home/node/asg-lcc` with the
  mounted `.env` sourced at runtime
- `03 Lead Scoring` no longer writes sample data — it reads `inbox/leads.csv`
  (real leads the operator drops), so it can't pollute the live base
- Verified the n8n API + webhook-trigger mechanism work against the live server
- Host deploy helper: `ops/deploy-on-host.sh` (clones, sets up inbox, smoke-tests)

## Security
- `.env` is gitignored; secrets only ever live in the host file you create.
- Workflows source `.env` at runtime — no secrets in n8n's DB or workflow JSON.
- Outreach is draft-only (`Approval Status = Pending Review`, `Send Status = Not
  Sent`); nothing is ever auto-sent.

## Notes / follow-ups
- Workflows `04 Outreach Draft`, `05 Reply Classification`, `07 Content
  Opportunity` carry placeholder inputs (manual / webhook-driven); wire real
  inputs before relying on them. `01/02/03` read `inbox/leads.csv`; `06` renders
  the sample report (switch to `--input <real> --feishu` when a real data source
  exists).
