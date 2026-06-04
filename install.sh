#!/usr/bin/env bash
set -e

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip setuptools wheel
pip install -e .

sudo ln -sf "$(pwd)/.venv/bin/yay" /usr/local/bin/yay

echo "yay installed"