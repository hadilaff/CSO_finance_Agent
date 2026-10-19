"""Streamlit UI for the Personal AI Assistant (Strategic Intelligence)."""
from __future__ import annotations

from datetime import date as _date

import streamlit as st

from agent import run_agent
from auth import login_form, logout_button
from briefing import (
    briefing_to_deck_spec,
    generate_briefing,
    load_briefing,
)
from deck import get_deck, store_deck
from market_data import (
    fetch_market_data,
    fetch_macro_data,
    PRESET_WATCHLIST,
    PRESET_MACRO,
)
from forecasting import run_forecast, FORECASTABLE_TICKERS
from rag import clear_index, index_file, list_sources
from voice import synthesize, transcribe

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

st.set_page_config(
    page_title="CSO Intelligence Assistant",
    page_icon=":bar_chart:",
    layout="wide",
)

# ---------- Auth gate ----------
if not login_form():
    st.stop()


st.title("CSO of an international financial center")
st.caption(
    "Secure intelligence layer for a Chief Strategy Officer · "
    "RAG over your documents + Tavily web search + Live market data · "
    "Powered by Groq (llama-3.3-70b-versatile) + ONNX embeddings"
)


# ---------- Sidebar ----------

with st.sidebar:
    logout_button(location=st.sidebar)
    st.divider()

    st.header("Institutional Knowledge")
    st.caption("Upload board papers, strategy memos, performance reports (PDF/DOCX/PPTX/TXT/MD).")

    uploads = st.file_uploader(
        "Upload documents",
        type=["pdf", "docx", "pptx", "txt", "md"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    if uploads:
        if st.button("Index uploaded files", type="primary", use_container_width=True):
            import traceback
            from rag import parse_file, chunk_text

            errors = []
            progress = st.progress(0.0, text="Indexing…")
            for i, f in enumerate(uploads, start=1):
                try:
                    progress.progress((i - 0.5) / len(uploads), text=f"Processing {f.name}…")
                    data = f.getvalue()
                    print(f"[index] {f.name} — {len(data):,} bytes")
                    text = parse_file(f.name, data)
                    print(f"[index]   parsed — {len(text):,} chars")
                    chunks = chunk_text(text)
                    print(f"[index]   chunked — {len(chunks)} chunks")
                    if not chunks:
                        print(f"[index]   WARNING: no text extracted from {f.name}")
                        errors.append(f.name)
                        continue
                    n = index_file(f.name, data)
                    print(f"[index]   stored — {n} chunks in ChromaDB")
                    progress.progress(i / len(uploads), text=f"Done: {f.name}")
                except Exception as e:
                    errors.append(f.name)
                    print(f"[index]   ERROR on {f.name}: {e}")
                    print(traceback.format_exc())

            progress.empty()
            if errors:
                print(f"[index] {len(uploads) - len(errors)}/{len(uploads)} succeeded. Failed: {', '.join(errors)}")
            else:
                print(f"[index] All {len(uploads)} file(s) indexed.")
            st.rerun()

    st.divider()
    try:
        sources = list_sources()
    except Exception as e:
        sources = []
        st.error(f"Index error: {e}")

    st.subheader(f"Indexed sources ({len(sources)})")
    if sources:
        for s in sources:
            st.write(f"• {s}")
        if st.button("Clear index", use_container_width=True):
            clear_index()
            st.rerun()
    else:
        st.caption("No documents indexed yet.")

    st.divider()
    if st.button("Reset chat", use_container_width=True):
        st.session_state.history = []
        st.rerun()


# ---------- Main: daily briefing ----------

today = _date.today()
today_brief = load_briefing(today)

with st.expander(
    f"📅 Today's Strategic Briefing — {today.isoformat()}",
    expanded=bool(today_brief),
):
    if today_brief is None:
        st.caption(
            "Six daily intelligence areas: overnight news, market signals, "
            "competitor moves, regulatory shifts, performance alerts, risk indicators."
        )
        if st.button("Generate today's briefing", type="primary", use_container_width=True):
            progress = st.progress(0.0, text="Starting…")
            def _tick(i, total, title):
                progress.progress(i / total, text=f"{i}/{total} — {title}")
            with st.spinner("Generating briefing — this can take 1–2 minutes…"):
                generate_briefing(today, progress=_tick)
            progress.empty()
            st.rerun()
    else:
        st.caption(f"Generated {today_brief['generated_at']}")
        for s in today_brief["sections"]:
            with st.container(border=True):
                st.markdown(f"**{s['icon']}  {s['title']}**")
                st.markdown(s["answer"])

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🔄 Refresh briefing", use_container_width=True):
                progress = st.progress(0.0, text="Starting…")
                def _tick(i, total, title):
                    progress.progress(i / total, text=f"{i}/{total} — {title}")
                with st.spinner("Regenerating…"):
                    generate_briefing(today, progress=_tick)
                progress.empty()
                st.rerun()
        with col_b:
            if st.button("📊 Build deck from briefing", use_container_width=True):
                with st.spinner("Building deck…"):
                    spec = briefing_to_deck_spec(today_brief)
                    deck_info = store_deck(spec)
                    st.session_state["briefing_deck_id"] = deck_info["deck_id"]
                    st.rerun()

        deck_id = st.session_state.get("briefing_deck_id")
        if deck_id:
            deck = get_deck(deck_id)
            if deck:
                st.download_button(
                    label=f"⬇ Download {deck['filename']}",
                    data=deck["bytes"],
                    file_name=deck["filename"],
                    mime=PPTX_MIME,
                    key=f"dl_briefing_{deck_id}",
                    use_container_width=True,
                )


# ---------- Main: market data dashboard ----------

with st.expander("📈 Market Data — Live Time Series", expanded=False):
    try:
        import plotly.graph_objects as go
        import pandas as pd
        _plotly_ok = True
    except ImportError:
        _plotly_ok = False
        st.warning("plotly and pandas are required for charts. They will be available inside Docker.")

    if _plotly_ok:
        # ── Controls ────────────────────────────────────────────────────────
        tab_market, tab_macro, tab_forecast = st.tabs(["📊 Markets", "🏦 Macro (FRED)", "🔮 Forecast"])

        with tab_market:
            ctrl1, ctrl2 = st.columns([3, 1])
            with ctrl1:
                # Flatten watchlist into labelled options
                ticker_options = {
                    f"{label} ({ticker})": ticker
                    for group in PRESET_WATCHLIST.values()
                    for ticker, label in group.items()
                }
                chosen_labels = st.multiselect(
                    "Select instruments",
                    options=list(ticker_options.keys()),
                    default=[
                        "S&P 500 (^GSPC)",
                        "EUR/USD (EURUSD=X)",
                        "Gold ($/oz) (GC=F)",
                        "Bitcoin (BTC-USD)",
                    ],
                    key="mkt_tickers",
                )
            with ctrl2:
                mkt_period = st.selectbox(
                    "Period",
                    options=["1mo", "3mo", "6mo", "ytd", "1y", "2y"],
                    index=1,
                    key="mkt_period",
                )

            if st.button("Fetch market data", type="primary", key="mkt_fetch"):
                tickers = [ticker_options[l] for l in chosen_labels]
                if tickers:
                    with st.spinner("Fetching from Yahoo Finance…"):
                        mkt_result = fetch_market_data(tickers, period=mkt_period)
                    st.session_state["mkt_result"] = mkt_result
                else:
                    st.info("Select at least one instrument.")

            mkt_result = st.session_state.get("mkt_result")
            if mkt_result and mkt_result.series:
                # ── Metric cards ────────────────────────────────────────────
                card_cols = st.columns(min(len(mkt_result.series), 4))
                for col, s in zip(card_cols, mkt_result.series):
                    delta_color = "normal"
                    col.metric(
                        label=s.label,
                        value=f"{s.latest:,.4f} {s.currency}",
                        delta=f"{s.pct_change:+.2f}% ({mkt_result.period})",
                        delta_color=delta_color,
                    )

                st.divider()

                # ── Normalised line chart (base = 100 at start of period) ──
                fig = go.Figure()
                for s in mkt_result.series:
                    if not s.dates or not s.values:
                        continue
                    base = s.values[0]
                    normalised = [round(v / base * 100, 4) for v in s.values]
                    fig.add_trace(go.Scatter(
                        x=s.dates,
                        y=normalised,
                        mode="lines",
                        name=s.label,
                        hovertemplate=(
                            f"<b>{s.label}</b><br>"
                            "Date: %{x}<br>"
                            "Indexed: %{y:.2f}<br>"
                            "<extra></extra>"
                        ),
                    ))

                fig.update_layout(
                    title=f"Normalised performance (base = 100) — {mkt_result.period}",
                    xaxis_title="Date",
                    yaxis_title="Indexed value (100 = start)",
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    height=420,
                    margin=dict(l=40, r=20, t=60, b=40),
                    plot_bgcolor="white",
                    paper_bgcolor="white",
                )
                fig.update_xaxes(showgrid=True, gridcolor="#e8ecf1")
                fig.update_yaxes(showgrid=True, gridcolor="#e8ecf1")
                st.plotly_chart(fig, use_container_width=True)

                # ── Raw price chart toggle ───────────────────────────────────
                if st.checkbox("Show raw prices", key="mkt_raw"):
                    fig2 = go.Figure()
                    for s in mkt_result.series:
                        if not s.dates:
                            continue
                        fig2.add_trace(go.Scatter(
                            x=s.dates, y=s.values,
                            mode="lines", name=f"{s.label} ({s.currency})",
                        ))
                    fig2.update_layout(
                        title="Raw prices",
                        hovermode="x unified",
                        height=380,
                        margin=dict(l=40, r=20, t=50, b=40),
                        plot_bgcolor="white",
                        paper_bgcolor="white",
                    )
                    fig2.update_xaxes(showgrid=True, gridcolor="#e8ecf1")
                    fig2.update_yaxes(showgrid=True, gridcolor="#e8ecf1")
                    st.plotly_chart(fig2, use_container_width=True)

                # Show errors if any tickers failed
                if mkt_result.errors:
                    with st.expander("⚠️ Fetch errors"):
                        for ticker, err in mkt_result.errors.items():
                            st.caption(f"**{ticker}**: {err}")

            elif mkt_result and not mkt_result.series:
                st.warning("No data returned. Check ticker symbols or try a different period.")
                if mkt_result.errors:
                    for t, e in mkt_result.errors.items():
                        st.caption(f"**{t}**: {e}")

        with tab_macro:
            ctrl3, ctrl4 = st.columns([3, 1])
            with ctrl3:
                macro_options = {f"{v} ({k})": k for k, v in PRESET_MACRO.items()}
                chosen_macro_labels = st.multiselect(
                    "Select macro indicators",
                    options=list(macro_options.keys()),
                    default=[
                        "Fed Funds Rate (FEDFUNDS)",
                        "US 10Y Treasury Yield (DGS10)",
                        "US CPI (YoY inflation) (CPIAUCSL)",
                        "VIX (Volatility Index) (VIXCLS)",
                    ],
                    key="macro_series",
                )
            with ctrl4:
                macro_period = st.selectbox(
                    "Period",
                    options=["3mo", "6mo", "1y", "2y", "5y"],
                    index=2,
                    key="macro_period",
                )

            if st.button("Fetch macro data", type="primary", key="macro_fetch"):
                series_ids = [macro_options[l] for l in chosen_macro_labels]
                if series_ids:
                    with st.spinner("Fetching from FRED…"):
                        macro_result = fetch_macro_data(series_ids, period=macro_period)
                    st.session_state["macro_result"] = macro_result
                else:
                    st.info("Select at least one indicator.")

            macro_result = st.session_state.get("macro_result")

            # Show FRED key missing warning gracefully
            if macro_result and "_all" in macro_result.errors:
                err_msg = macro_result.errors["_all"]
                if "FRED_API_KEY" in err_msg:
                    st.info(
                        "**FRED macro data** requires a free API key. "
                        "Get one at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) "
                        "and add `FRED_API_KEY=your_key` to your `.env` file."
                    )
                else:
                    st.error(err_msg)
            elif macro_result and macro_result.series:
                # Metric cards
                card_cols = st.columns(min(len(macro_result.series), 4))
                for col, s in zip(card_cols, macro_result.series):
                    col.metric(
                        label=s.label,
                        value=f"{s.latest:.3f}",
                        delta=f"{s.pct_change:+.2f}% ({macro_period})",
                    )

                st.divider()

                # One line per series on a shared axis
                fig3 = go.Figure()
                for s in macro_result.series:
                    if not s.dates:
                        continue
                    fig3.add_trace(go.Scatter(
                        x=s.dates, y=s.values,
                        mode="lines", name=s.label,
                        hovertemplate="<b>" + s.label + "</b><br>%{x}<br>%{y:.3f}<extra></extra>",
                    ))

                fig3.update_layout(
                    title=f"Macro indicators — {macro_period}",
                    xaxis_title="Date",
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    height=420,
                    margin=dict(l=40, r=20, t=60, b=40),
                    plot_bgcolor="white",
                    paper_bgcolor="white",
                )
                fig3.update_xaxes(showgrid=True, gridcolor="#e8ecf1")
                fig3.update_yaxes(showgrid=True, gridcolor="#e8ecf1")
                st.plotly_chart(fig3, use_container_width=True)

                if macro_result.errors:
                    with st.expander("⚠️ Fetch errors"):
                        for sid, err in macro_result.errors.items():
                            if sid != "_all":
                                st.caption(f"**{sid}**: {err}")

        with tab_forecast:
            st.caption(
                "Prophet time series model — trained on historical daily prices, "
                "forecasts future values with an 80% confidence band."
            )

            fc_col1, fc_col2, fc_col3 = st.columns([3, 1, 1])
            with fc_col1:
                fc_ticker_options = {
                    f"{label} ({ticker})": ticker
                    for ticker, label in FORECASTABLE_TICKERS.items()
                }
                fc_chosen_label = st.selectbox(
                    "Instrument to forecast",
                    options=list(fc_ticker_options.keys()),
                    index=list(fc_ticker_options.keys()).index("Gold ($/oz) (GC=F)")
                    if "Gold ($/oz) (GC=F)" in fc_ticker_options
                    else 0,
                    key="fc_ticker",
                )
            with fc_col2:
                fc_periods = st.selectbox(
                    "Forecast horizon",
                    options=[7, 14, 30, 60, 90],
                    index=2,
                    format_func=lambda x: f"{x} days",
                    key="fc_periods",
                )
            with fc_col3:
                fc_history = st.selectbox(
                    "Training history",
                    options=["6mo", "1y", "2y", "5y"],
                    index=2,
                    key="fc_history",
                )

            if st.button("Run forecast", type="primary", key="fc_run"):
                ticker_sym = fc_ticker_options[fc_chosen_label]
                with st.spinner(
                    f"Fetching {fc_history} of history and fitting Prophet model "
                    f"for {fc_chosen_label}… (15–30 seconds)"
                ):
                    fc_result = run_forecast(
                        ticker_sym,
                        periods=fc_periods,
                        history_period=fc_history,
                    )
                st.session_state["fc_result"] = fc_result

            fc_result = st.session_state.get("fc_result")

            if fc_result:
                if fc_result.error:
                    st.error(f"Forecast failed: {fc_result.error}")
                else:
                    # ── Summary metrics ──────────────────────────────────────
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Last actual",      f"{fc_result.last_actual:,.4f} {fc_result.currency}")
                    m2.metric(
                        f"Forecast (+{fc_result.forecast_days}d)",
                        f"{fc_result.fc_end_value:,.4f}",
                        delta=f"{fc_result.fc_pct_change:+.2f}%",
                    )
                    m3.metric(
                        "80% confidence band",
                        f"{fc_result.fc_lower[-1]:,.4f} – {fc_result.fc_upper[-1]:,.4f}"
                        if fc_result.fc_lower and fc_result.fc_upper else "—",
                    )
                    trend_icon = {"upward": "↑", "downward": "↓", "flat": "→"}.get(
                        fc_result.trend_direction, ""
                    )
                    m4.metric("Trend direction", f"{trend_icon} {fc_result.trend_direction.capitalize()}")

                    st.divider()

                    # ── Main forecast chart ──────────────────────────────────
                    fig_fc = go.Figure()

                    # Historical actual prices
                    fig_fc.add_trace(go.Scatter(
                        x=fc_result.hist_dates,
                        y=fc_result.hist_values,
                        mode="lines",
                        name="Actual",
                        line=dict(color="#0A2540", width=1.5),
                        hovertemplate="<b>Actual</b><br>%{x}<br>%{y:,.4f}<extra></extra>",
                    ))

                    # Confidence band (filled area between lower and upper)
                    fig_fc.add_trace(go.Scatter(
                        x=fc_result.fc_dates + fc_result.fc_dates[::-1],
                        y=fc_result.fc_upper + fc_result.fc_lower[::-1],
                        fill="toself",
                        fillcolor="rgba(46,125,221,0.15)",
                        line=dict(color="rgba(0,0,0,0)"),
                        hoverinfo="skip",
                        name="80% confidence band",
                        showlegend=True,
                    ))

                    # Point forecast line
                    fig_fc.add_trace(go.Scatter(
                        x=fc_result.fc_dates,
                        y=fc_result.fc_yhat,
                        mode="lines",
                        name=f"Forecast ({fc_result.forecast_days}d)",
                        line=dict(color="#2E7DDD", width=2, dash="dash"),
                        hovertemplate="<b>Forecast</b><br>%{x}<br>%{y:,.4f}<extra></extra>",
                    ))

                    # Vertical line at forecast start
                    if fc_result.hist_dates:
                        fig_fc.add_vline(
                            x=fc_result.hist_dates[-1],
                            line_dash="dot",
                            line_color="#6E6E6E",
                            annotation_text="Today",
                            annotation_position="top right",
                        )

                    fig_fc.update_layout(
                        title=f"{fc_result.label} — {fc_result.forecast_days}-day Prophet Forecast",
                        xaxis_title="Date",
                        yaxis_title=f"Price ({fc_result.currency})",
                        hovermode="x unified",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        height=460,
                        margin=dict(l=40, r=20, t=65, b=40),
                        plot_bgcolor="white",
                        paper_bgcolor="white",
                    )
                    fig_fc.update_xaxes(showgrid=True, gridcolor="#e8ecf1")
                    fig_fc.update_yaxes(showgrid=True, gridcolor="#e8ecf1")
                    st.plotly_chart(fig_fc, use_container_width=True)

                    # ── Trend decomposition chart ────────────────────────────
                    if st.checkbox("Show trend component", key="fc_trend_toggle"):
                        fig_trend = go.Figure()
                        fig_trend.add_trace(go.Scatter(
                            x=fc_result.trend_dates,
                            y=fc_result.trend_values,
                            mode="lines",
                            name="Trend",
                            line=dict(color="#E07B00", width=2),
                            hovertemplate="%{x}<br>Trend: %{y:,.4f}<extra></extra>",
                        ))
                        # Mark history/forecast boundary
                        if fc_result.hist_dates:
                            fig_trend.add_vline(
                                x=fc_result.hist_dates[-1],
                                line_dash="dot",
                                line_color="#6E6E6E",
                                annotation_text="Forecast start",
                            )
                        fig_trend.update_layout(
                            title=f"{fc_result.label} — Underlying trend (Prophet component)",
                            xaxis_title="Date",
                            yaxis_title=f"Trend ({fc_result.currency})",
                            height=300,
                            margin=dict(l=40, r=20, t=50, b=35),
                            plot_bgcolor="white",
                            paper_bgcolor="white",
                        )
                        fig_trend.update_xaxes(showgrid=True, gridcolor="#e8ecf1")
                        fig_trend.update_yaxes(showgrid=True, gridcolor="#e8ecf1")
                        st.plotly_chart(fig_trend, use_container_width=True)

                    st.caption(
                        f"Model trained on {len(fc_result.hist_dates)} trading days "
                        f"({fc_result.history_period} of history). "
                        "Prophet captures weekly and yearly seasonality + trend changepoints. "
                        "⚠️ This is a statistical model, not financial advice."
                    )


# ---------- Main: chat ----------

if "history" not in st.session_state:
    st.session_state.history = []

# Quick-start prompts (shown only on an empty conversation).
if not st.session_state.history:
    st.subheader("Try a quick prompt")
    quick = [
        "Forecast Gold price for the next 30 days.",
        "How is DIFC Dubai positioning itself for digital asset businesses?",
        "Summarise the strategic priorities in my uploaded documents.",
    ]
    cols = st.columns(len(quick))
    for col, prompt in zip(cols, quick):
        if col.button(prompt, use_container_width=True):
            st.session_state.pending = prompt
            st.rerun()


# ── Chat rendering helpers ────────────────────────────────────────────────────

def _render_market_chart(tool_calls: list[dict], key_prefix: str) -> None:
    """Render an inline Plotly chart if the agent called market_data or macro_data."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        return

    for i, tc in enumerate(tool_calls):
        name   = tc.get("name", "")
        result = tc.get("result") or {}

        if name not in ("market_data", "macro_data"):
            continue
        if "error" in result or not result.get("series"):
            continue

        series_list = result["series"]
        period      = result.get("period", "")

        fig = go.Figure()
        for s in series_list:
            dates  = s.get("dates") or s.get("dates_", [])
            values = s.get("values") or []
            label  = s.get("label") or s.get("series_id", "")

            if not dates or not values:
                continue

            # Normalise only when multiple series, so they're comparable
            if len(series_list) > 1 and values[0]:
                y = [round(v / values[0] * 100, 4) for v in values]
                y_label = "Indexed (100 = start)"
            else:
                y = values
                y_label = s.get("currency", "")

            fig.add_trace(go.Scatter(
                x=dates, y=y,
                mode="lines",
                name=label,
                hovertemplate=f"<b>{label}</b><br>%{{x}}<br>%{{y:.4f}}<extra></extra>",
            ))

        if not fig.data:
            continue

        fig.update_layout(
            title=f"{'Normalised performance' if len(series_list) > 1 else series_list[0].get('label', '')} — {period}",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            height=380,
            margin=dict(l=40, r=20, t=55, b=35),
            plot_bgcolor="white",
            paper_bgcolor="white",
        )
        fig.update_xaxes(showgrid=True, gridcolor="#e8ecf1")
        fig.update_yaxes(showgrid=True, gridcolor="#e8ecf1")
        st.plotly_chart(fig, use_container_width=True, key=f"chart_{key_prefix}_{i}")


def _render_forecast_chart(tool_calls: list[dict], key_prefix: str) -> None:
    """Render an inline Prophet forecast chart when the agent called forecast_market."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        return

    for i, tc in enumerate(tool_calls):
        if tc.get("name") != "forecast_market":
            continue
        args   = tc.get("args") or {}
        result = tc.get("result") or {}

        if result.get("error") or not args.get("ticker"):
            continue

        # The agent tool returns only the summary dict — we need to re-run the
        # forecast to get the full arrays for charting. Cache by (ticker, periods,
        # history_period) so re-renders don't re-fit.
        ticker         = args.get("ticker", "")
        periods        = args.get("periods", 30)
        history_period = args.get("history_period", "2y")
        cache_key      = f"fc_chat_{ticker}_{periods}_{history_period}"

        fc = st.session_state.get(cache_key)
        if fc is None:
            with st.spinner(f"Building forecast chart for {ticker}…"):
                fc = run_forecast(ticker, periods=periods, history_period=history_period)
            st.session_state[cache_key] = fc

        if fc.error:
            st.caption(f"⚠️ Chart unavailable: {fc.error}")
            continue

        fig = go.Figure()

        # Actual prices
        fig.add_trace(go.Scatter(
            x=fc.hist_dates, y=fc.hist_values,
            mode="lines", name="Actual",
            line=dict(color="#0A2540", width=1.5),
            hovertemplate="<b>Actual</b><br>%{x}<br>%{y:,.4f}<extra></extra>",
        ))

        # Confidence band
        fig.add_trace(go.Scatter(
            x=fc.fc_dates + fc.fc_dates[::-1],
            y=fc.fc_upper + fc.fc_lower[::-1],
            fill="toself",
            fillcolor="rgba(46,125,221,0.15)",
            line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="skip",
            name="80% confidence band",
        ))

        # Point forecast
        fig.add_trace(go.Scatter(
            x=fc.fc_dates, y=fc.fc_yhat,
            mode="lines",
            name=f"Forecast ({fc.forecast_days}d)",
            line=dict(color="#2E7DDD", width=2, dash="dash"),
            hovertemplate="<b>Forecast</b><br>%{x}<br>%{y:,.4f}<extra></extra>",
        ))

        # Today marker
        if fc.hist_dates:
            fig.add_vline(
                x=fc.hist_dates[-1],
                line_dash="dot", line_color="#6E6E6E",
                annotation_text="Today", annotation_position="top right",
            )

        trend_icon = {"upward": "↑", "downward": "↓", "flat": "→"}.get(
            fc.trend_direction, ""
        )
        fig.update_layout(
            title=(
                f"{fc.label} — {fc.forecast_days}-day Forecast  |  "
                f"Last: {fc.last_actual:,.4f}  →  "
                f"Target: {fc.fc_end_value:,.4f} ({fc.fc_pct_change:+.2f}%)  "
                f"{trend_icon} {fc.trend_direction}"
            ),
            xaxis_title="Date",
            yaxis_title=f"Price ({fc.currency})",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            height=400,
            margin=dict(l=40, r=20, t=75, b=35),
            plot_bgcolor="white",
            paper_bgcolor="white",
        )
        fig.update_xaxes(showgrid=True, gridcolor="#e8ecf1")
        fig.update_yaxes(showgrid=True, gridcolor="#e8ecf1")
        st.plotly_chart(fig, use_container_width=True, key=f"fc_chart_{key_prefix}_{i}")
        st.caption(
            f"Prophet model · {len(fc.hist_dates)} training days · "
            "80% confidence band · ⚠️ Not financial advice."
        )


def _render_tool_calls(tool_calls: list[dict], key_prefix: str = "") -> None:
    if not tool_calls:
        return
    # Deck download buttons
    for i, tc in enumerate(tool_calls):
        if tc.get("name") != "generate_deck":
            continue
        result = tc.get("result") or {}
        deck_id = result.get("deck_id")
        if not deck_id:
            continue
        deck = get_deck(deck_id)
        if not deck:
            continue
        st.download_button(
            label=f"⬇ Download {deck['filename']}",
            data=deck["bytes"],
            file_name=deck["filename"],
            mime=PPTX_MIME,
            key=f"dl_{key_prefix}_{deck_id}_{i}",
        )
    with st.expander(f"Tool calls ({len(tool_calls)})", expanded=False):
        for tc in tool_calls:
            st.markdown(f"**`{tc['name']}`** — args: `{tc['args']}`")
            st.json(tc["result"], expanded=False)


def _render_speak_button(text: str, key: str) -> None:
    if text.startswith(":warning:"):
        return
    cache_key = f"tts_{key}"
    play_key  = f"tts_play_{key}"
    if st.button("🔊 Speak", key=f"speak_{key}"):
        with st.spinner("Speaking…"):
            try:
                st.session_state[cache_key] = synthesize(text)
                st.session_state[play_key]  = True
            except Exception as e:
                print(f"[tts] synthesize failed: {e}")
                st.session_state[cache_key] = b""
    audio = st.session_state.get(cache_key)
    if audio:
        autoplay = st.session_state.pop(play_key, False)
        st.audio(audio, format="audio/mp3", autoplay=autoplay)


# ── Render history ────────────────────────────────────────────────────────────

for i, turn in enumerate(st.session_state.history):
    with st.chat_message(turn["role"]):
        st.markdown(turn["text"])
        if turn["role"] == "assistant":
            _render_market_chart(turn.get("tool_calls", []), key_prefix=f"hist{i}")
            _render_forecast_chart(turn.get("tool_calls", []), key_prefix=f"hist{i}")
            _render_tool_calls(turn.get("tool_calls", []), key_prefix=f"hist{i}")
            _render_speak_button(turn["text"], key=f"hist{i}")


# ── Input ─────────────────────────────────────────────────────────────────────

pending    = st.session_state.pop("pending", None)
chat_input = st.chat_input(
    "Ask about markets, competitors, regulation, or your uploaded docs…"
)

voice_text = None
with st.expander("🎤 Speak your question", expanded=False):
    mic = st.audio_input("Record", label_visibility="collapsed", key="mic")
    if mic is not None:
        audio_bytes = mic.getvalue()
        audio_hash  = hash(audio_bytes)
        if st.session_state.get("last_audio_hash") != audio_hash:
            st.session_state["last_audio_hash"] = audio_hash
            with st.spinner("Transcribing…"):
                try:
                    voice_text = transcribe(audio_bytes, "voice.wav")
                except Exception as e:
                    st.error(f"Transcription failed: {e}")
            if voice_text:
                st.caption(f"Heard: _{voice_text}_")

user_input = pending or voice_text or chat_input

if user_input:
    st.session_state.history.append({"role": "user", "text": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                result     = run_agent(user_input, history=st.session_state.history[:-1])
                answer     = result["answer"]
                tool_calls = result["tool_calls"]
            except Exception as e:
                err_str = str(e)
                if "503" in err_str or "UNAVAILABLE" in err_str or "502" in err_str:
                    answer = ":warning: **Groq is temporarily unavailable.** Please wait a moment and try again."
                elif "429" in err_str or "rate_limit" in err_str:
                    answer = (
                        ":warning: **Groq rate limit hit.** "
                        "Wait a minute and retry, or check [console.groq.com](https://console.groq.com)."
                    )
                else:
                    answer = f":warning: Error: {e}"
                tool_calls = []

        st.markdown(answer)
        _render_market_chart(tool_calls, key_prefix="new")
        _render_forecast_chart(tool_calls, key_prefix="new")
        _render_tool_calls(tool_calls, key_prefix="new")

    st.session_state.history.append({
        "role":       "assistant",
        "text":       answer,
        "tool_calls": tool_calls,
    })
    st.rerun()
