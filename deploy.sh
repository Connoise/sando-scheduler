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

echo "==> Installing systemd service..."
sudo cp "$REPO_DIR/reminder-daemon.service" /etc/systemd/system/reminder-daemon.service
sudo systemctl daemon-reload

echo "==> Enabling and starting service..."
sudo systemctl enable reminder-daemon.service
sudo systemctl start reminder-daemon.service

echo ""
echo "==> Status:"
sudo systemctl status reminder-daemon.service --no-pager
