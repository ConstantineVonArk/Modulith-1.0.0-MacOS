#!/bin/bash
LOG="$HOME/Library/Logs/Modulith/startup.log"
if [ -f "$LOG" ]; then
  open -a TextEdit "$LOG"
else
  osascript -e 'display dialog "No startup log yet. Please launch Modulith.app first." buttons {"OK"} default button "OK" with title "Modulith"' >/dev/null 2>&1 || true
fi
