#!/bin/sh
# One-time setup: creates .venv in this folder and installs the dependencies into it.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
echo "Setup done. Test: .venv/bin/python -m pytest   Record: .venv/bin/python -m meetrec record"
