#!/bin/bash
# =============================================================================
# Finance Dashboard — double-click this file (in Finder) to open it.
# No terminal commands to type. Everything runs on this Mac only; nothing is
# ever sent anywhere else.
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
