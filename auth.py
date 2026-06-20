"""Simple password gate for the CSO Intelligence Assistant.

Set APP_PASSWORD in your .env file. Anyone with the password can sign in.

    APP_PASSWORD=demo123
"""
from __future__ import annotations

import hmac
import os

import streamlit as st


def _expected_password() -> str:
    return os.getenv("APP_PASSWORD", "").strip()


def _login_stage() -> None:
    st.title("🔒 CSO Intelligence Assistant")
    st.caption("Enter the access password to continue.")

    with st.form("auth_password_form"):
        password = st.text_input("Password", type="password", placeholder="••••••••")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

    if not submitted:
        return

    expected = _expected_password()
    if not hmac.compare_digest(expected, password.strip()):
        st.error("Incorrect password.")
        return

    st.session_state["authed"] = True
    st.rerun()


def login_form() -> bool:
    """Render the login form. Returns True when authenticated."""
    if st.session_state.get("authed"):
        return True

    if not _expected_password():
        st.error(
            "**Access password is not configured.** "
            "Add `APP_PASSWORD=your_password` to your `.env`, then restart the app."
        )
        return False

    _login_stage()
    return False


def logout_button(location=None) -> None:
    """Render a logout button. Pass st.sidebar to dock it there."""
    target = location if location is not None else st
    if target.button("Sign out", use_container_width=True):
        st.session_state.pop("authed", None)
        st.rerun()
