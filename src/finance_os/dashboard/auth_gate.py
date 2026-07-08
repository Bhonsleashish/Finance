"""Login gate shown before any dashboard page renders. Session state is
shared across every page within one browser session, so logging in once
unlocks the whole app until the tab/session ends.

If no password has been configured (`finance auth set-password`), this is a
no-op — that matches the "localhost only, trusted machine" default. Once a
password exists, every page requires it, whether reached via localhost or
--network.
"""

from __future__ import annotations

import time

import streamlit as st

from finance_os import auth

MAX_ATTEMPTS_BEFORE_DELAY = 3
LOCKOUT_DELAY_SECONDS = 2


def require_login() -> None:
    if not auth.is_password_set():
        return

    if st.session_state.get("authenticated"):
        return

    st.title("🔒 Finance OS")
    st.write("Enter the dashboard password to continue.")

    attempts = st.session_state.get("auth_attempts", 0)
    if attempts >= MAX_ATTEMPTS_BEFORE_DELAY:
        time.sleep(LOCKOUT_DELAY_SECONDS)

    with st.form("login_form"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if submitted:
        if auth.verify_password(password):
            st.session_state["authenticated"] = True
            st.session_state["auth_attempts"] = 0
            st.rerun()
        else:
            st.session_state["auth_attempts"] = attempts + 1
            st.error("Incorrect password.")

    st.stop()
