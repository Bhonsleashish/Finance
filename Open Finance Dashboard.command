#!/bin/bash
# =============================================================================
# Finance Dashboard — double-click this file (in Finder) to open it.
# No terminal commands to type, ever — this also checks for and installs
# updates automatically, so you never need to run `git pull` yourself.
# Everything about your finances still runs on this Mac only and is never
# sent anywhere; the only thing this ever fetches over the network is new
# versions of the app's own code (like any app auto-updating itself).
#
# First time: this sets itself up (takes a minute or two) and asks you to
# choose a password so only you can open the dashboard. After that, just
# double-click this file whenever you want to open it.
# =============================================================================

cd "$(dirname "$0")" || exit 1
PORT=8501

clear
echo "💶  Finance Dashboard"
echo "======================"
echo ""

# --- check for updates (silently skipped if offline or not a git checkout) --
if [ -z "$FINANCE_LAUNCHER_RELAUNCHED" ] && command -v git >/dev/null 2>&1 && [ -d ".git" ]; then
    echo "Checking for updates..."
    BEFORE_COMMIT=$(git rev-parse HEAD 2>/dev/null)
    BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
    if [ -n "$BRANCH" ] && git pull --quiet origin "$BRANCH" >/dev/null 2>&1; then
        AFTER_COMMIT=$(git rev-parse HEAD 2>/dev/null)
        if [ "$BEFORE_COMMIT" != "$AFTER_COMMIT" ]; then
            echo "Found an update — installing it, then restarting..."
            echo ""
            export FINANCE_LAUNCHER_RELAUNCHED=1
            exec "$0" "$@"
        else
            echo "Already up to date."
        fi
    else
        echo "Couldn't check for updates (offline?) — continuing with what's already here."
    fi
    echo ""
fi

# --- first-time setup -------------------------------------------------------
if [ ! -d ".venv" ]; then
    echo "Setting things up for the first time — this takes a minute or two..."
    echo ""
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Python wasn't found on this Mac. Please install it from python.org, then double-click this file again."
        read -r -p "Press Return to close this window..."
        exit 1
    fi
    python3 -m venv .venv
    # shellcheck disable=SC1091
    source .venv/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet -e .
    finance init >/dev/null
    echo "Setup complete."
    echo ""
else
    # shellcheck disable=SC1091
    source .venv/bin/activate
    # Keep installed dependencies in sync in case an update changed them.
    pip install --quiet -e . >/dev/null 2>&1
fi

# --- already running? just open it ------------------------------------------
if curl -s -o /dev/null "http://localhost:$PORT"; then
    echo "Your dashboard is already running — opening it now..."
    open "http://localhost:$PORT"
    sleep 1
    exit 0
fi

# --- first-time password ------------------------------------------------------
if ! finance auth status >/dev/null 2>&1; then
    echo "One more thing before we start: choose a password so only you can open"
    echo "the dashboard (you'll type it twice — it won't show on screen, that's normal)."
    echo ""
    finance auth set-password
    echo ""
fi

# --- launch --------------------------------------------------------------------
echo "Starting your dashboard — your browser will open automatically in a few seconds."
echo ""
echo "You can also open it from your phone: on your phone's browser (same Wi-Fi as"
echo "this Mac), go to the network address printed below once it starts."
echo ""
echo "Leave this window open while you use the dashboard."
echo "When you're done, just close this window."
echo ""

( sleep 4 && open "http://localhost:$PORT" ) &

finance dashboard --network --port "$PORT"
