#!/usr/bin/env bash
# ASG Lead Command Center — host-side deploy helper for the n8n server.
#
# Run this ON THE N8N HOST (the machine running the n8n Docker container),
# NOT inside the container. It clones the repo, sets up the inbox dir, and
# prints the exact docker-compose volume mount to add so the n8n container can
# execute the scripts at /home/node/asg-lcc with the mounted .env.
#
# Usage:  ./ops/deploy-on-host.sh [/srv/asg-lcc]
set -euo pipefail

INSTALL_DIR="${1:-/srv/asg-lcc}"
REPO="https://github.com/wangjianbin11/asg-lead-command-center.git"
IN_CONTAINER_PATH="/home/node/asg-lcc"

echo "==> ASG Lead Command Center — deploy to host dir: $INSTALL_DIR"

if [ ! -d "$INSTALL_DIR/.git" ]; then
  git clone "$REPO" "$INSTALL_DIR"
else
  echo "    (existing repo found; pulling latest)"
  git -C "$INSTALL_DIR" pull --ff-only
fi

# inbox: where the operator drops real lead CSVs (read by the scoring workflow).
mkdir -p "$INSTALL_DIR/inbox"
if [ ! -f "$INSTALL_DIR/inbox/README.txt" ]; then
  cat > "$INSTALL_DIR/inbox/README.txt" <<'EOF'
Drop real lead CSVs here. The scoring workflow reads
  /home/node/asg-lcc/inbox/leads.csv
(inside the n8n container) — i.e. this directory after the volume mount.
EOF
fi

# .env holds all secrets (FEISHU_* / ANTHROPIC_*). Never committed. The operator
# fills it from .env.example with real credentials. The n8n workflows `source`
# this file at runtime so secrets stay here and never enter the n8n database.
if [ ! -f "$INSTALL_DIR/.env" ]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  echo
  echo "!! Created $INSTALL_DIR/.env from .env.example."
  echo "!! EDIT IT NOW and fill in FEISHU_APP_ID / FEISHU_APP_SECRET /"
  echo "!! FEISHU_BASE_APP_TOKEN / FEISHU_*_TABLE_ID / ANTHROPIC_API_KEY."
else
  echo "    (.env already present — keeping it)"
fi

echo
echo "==> Host smoke test (hermetic unit tests; needs python3 on host):"
if command -v python3 >/dev/null 2>&1; then
  ( cd "$INSTALL_DIR" && python3 -m unittest discover -s tests 2>&1 | tail -3 ) || true
else
  echo "    python3 not found on host — skipping (scripts run inside the container, which has python3)"
fi

cat <<EOF

==> DONE on host. Now mount this directory into the n8n container.

   1. Find n8n's docker-compose.yml (often ~/n8n/docker-compose.yml or where
      the n8n service is defined).
   2. Under the n8n service, add to "volumes:":
        - $INSTALL_DIR:$IN_CONTAINER_PATH
   3. Recreate n8n so the mount takes effect:
        docker compose up -d --force-recreate n8n
      (or:  docker restart <n8n-container>  if not using compose)

   The n8n workflows already run:
        cd $IN_CONTAINER_PATH && set -a && . ./.env && set +a && python3 scripts/<x>.py ...
   so the mounted .env is sourced at runtime (secrets never stored in n8n).

   Then tell Claude n8n has been recreated — it will activate the read/generate
   workflows and run one verification execution.
EOF
