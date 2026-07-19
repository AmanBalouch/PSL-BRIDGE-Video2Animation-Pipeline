#!/usr/bin/env bash
#
# setup.sh -- one-time setup on a fresh Ubuntu EC2 instance.
#
#   chmod +x setup.sh
#   ./setup.sh
#
# Installs Python + a virtualenv + Google Chrome (+ Xvfb), then installs the
# Python deps. After it finishes:
#
#   source .venv/bin/activate
#   xvfb-run -a python run.py
#
set -euo pipefail

echo "==> Updating apt and installing system packages..."
sudo apt-get update -y
sudo apt-get install -y \
    python3 python3-venv python3-pip \
    wget curl unzip \
    xvfb fonts-liberation

echo "==> Installing Google Chrome (stable)..."
if ! command -v google-chrome >/dev/null 2>&1; then
    wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
        -O /tmp/google-chrome.deb
    # apt resolves Chrome's dependencies for us; -f fixes any that are missing.
    sudo apt-get install -y /tmp/google-chrome.deb || sudo apt-get -f install -y
    rm -f /tmp/google-chrome.deb
fi
echo "    $(google-chrome --version)"

echo "==> Creating Python virtualenv (.venv) and installing requirements..."
cd "$(dirname "$0")"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo
echo "==> Setup complete."
echo "    Run the pipeline with:"
echo "        source .venv/bin/activate"
echo "        xvfb-run -a python run.py"
