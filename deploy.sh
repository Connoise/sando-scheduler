#!/usr/bin/env bash
# deploy.sh - Set up the Sando Scheduler reminder daemon on Benten-do
set -e

SCHEDULE_DIR="/home/connoise/Schedule"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Creating Schedule directory..."
mkdir -p "$SCHEDULE_DIR"

echo "==> Copying daemon script..."
cp "$REPO_DIR/reminder_daemon.py" "$SCHEDULE_DIR/reminder_daemon.py"

echo "==> Installing dependencies..."
pip3 install -r "$REPO_DIR/requirements.txt" --quiet

echo "==> Provisioning secrets file..."
ENV_DIR="/etc/sando-scheduler"
ENV_FILE="$ENV_DIR/reminder-daemon.env"
sudo install -d -m 700 "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
    sudo install -m 600 "$REPO_DIR/reminder-daemon.env.example" "$ENV_FILE"
    echo ""
    echo "    Created $ENV_FILE from the template."
    echo "    Edit it to add the real TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID,"
    echo "    then re-run this script to start the service:"
    echo ""
    echo "        sudo \"\${EDITOR:-vi}\" $ENV_FILE"
    echo ""
    exit 0
fi
if sudo grep -q 'replace-with-' "$ENV_FILE"; then
    echo "    ERROR: $ENV_FILE still has placeholder values." >&2
    echo "    Fill in the real secrets, then re-run this script." >&2
    exit 1
fi

echo "==> Installing systemd service..."
sudo cp "$REPO_DIR/reminder-daemon.service" /etc/systemd/system/reminder-daemon.service
sudo systemctl daemon-reload

echo "==> Enabling and starting service..."
sudo systemctl enable reminder-daemon.service
sudo systemctl start reminder-daemon.service

echo ""
echo "==> Status:"
sudo systemctl status reminder-daemon.service --no-pager
