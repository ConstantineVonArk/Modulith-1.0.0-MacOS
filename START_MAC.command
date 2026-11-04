#!/bin/bash
# Modulith 1.0 macOS launcher: isolated environment with Pillow installed.
set -u
cd "$(dirname "$0")" || exit 1
export PIP_DISABLE_PIP_VERSION_CHECK=1

# Prefer a stable Python with Tk support instead of the newest system Python.
PYTHON=""
for candidate in python3.12 python3.11 python3.13 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys, tkinter; assert (3,10)<=sys.version_info[:2]<=(3,13)' >/dev/null 2>&1; then
            PYTHON="$(command -v "$candidate")"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    echo 'Python 3.10–3.13 with Tkinter was not found.'
    echo 'Install Python 3.12 from python.org.'
    echo 'https://www.python.org/downloads/release/python-31210/'
    read -r -p 'Press Enter to exit…' _
    exit 1
fi

echo "Modulith 1.0.0 — Python: $($PYTHON --version)"
VENV=".venv_sc3k347"
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c 'import tkinter' >/dev/null 2>&1; then
    rm -rf "$VENV"
    "$PYTHON" -m venv "$VENV" || {
        echo 'Could not create the Python environment.'
        read -r -p 'Press Enter to exit…' _
        exit 1
    }
fi
if ! "$VENV/bin/python" -c 'from PIL import Image, ImageTk, ImageColor' >/dev/null 2>&1; then
    echo 'Installing Pillow (internet required at first launch)…'
    "$VENV/bin/python" -m pip install 'Pillow>=10.0,<12' || {
        echo 'Pillow installation failed. Check internet access.'
        read -r -p 'Press Enter to exit…' _
        exit 1
    }
fi
if ! "$VENV/bin/python" -c 'import numpy' >/dev/null 2>&1; then
    echo 'Installing NumPy for faster zoom…'
    "$VENV/bin/python" -m pip install 'numpy>=1.26,<3' || {
        echo 'NumPy unavailable; Pillow fallback will be used.'
    }
fi
"$VENV/bin/python" facade_builder.py
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
    echo "The application exited with error $STATUS. Please share this Terminal output."
    read -r -p 'Press Enter to exit…' _
fi
exit "$STATUS"
