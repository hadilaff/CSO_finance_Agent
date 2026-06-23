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
    "RAG over your documents + Tavily web search · Powered by Groq (llama-4-scout-17b-16e-instruct) + ONNX embeddings"
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
                        print(f"[index]   WARNING: no text extracted from {f.name} (scanned PDF or empty)")
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


# ---------- Main: chat ----------

if "history" not in st.session_state:
    st.session_state.history = []

# Quick-start prompts (shown only on an empty conversation).
if not st.session_state.history:
    st.subheader("Try a quick prompt")
    quick = [
        "What are today's most important developments across global financial centers?",
        "How is DIFC Dubai positioning itself for digital asset businesses, and what should we learn from it?",
        "Summarise the strategic priorities in my uploaded documents.",
    ]
    cols = st.columns(len(quick))
    for col, prompt in zip(cols, quick):
        if col.button(prompt, use_container_width=True):
            st.session_state.pending = prompt
            st.rerun()


def _render_tool_calls(tool_calls: list[dict], key_prefix: str = "") -> None:
    if not tool_calls:
        return
    # Surface any generated decks as download buttons first.
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
    """Per-message TTS — synthesises only when the user clicks Speak."""
    if text.startswith(":warning:"):
        return
    cache_key = f"tts_{key}"
    play_key = f"tts_play_{key}"
    if st.button("🔊 Speak", key=f"speak_{key}"):
        with st.spinner("Speaking…"):
            try:
                st.session_state[cache_key] = synthesize(text)
                st.session_state[play_key] = True
            except Exception as e:
                print(f"[tts] synthesize failed: {e}")
                st.session_state[cache_key] = b""
    audio = st.session_state.get(cache_key)
    if audio:
        autoplay = st.session_state.pop(play_key, False)
        st.audio(audio, format="audio/mp3", autoplay=autoplay)


for i, turn in enumerate(st.session_state.history):
    with st.chat_message(turn["role"]):
        st.markdown(turn["text"])
        _render_tool_calls(turn.get("tool_calls", []), key_prefix=f"hist{i}")
        if turn["role"] == "assistant":
            _render_speak_button(turn["text"], key=f"hist{i}")


pending = st.session_state.pop("pending", None)
chat_input = st.chat_input(
    "Ask about markets, competitors, regulation, or your uploaded docs…"
)

# Voice input — record once, transcribe via Gemini Flash audio, treat as user input.
voice_text = None
with st.expander("🎤 Speak your question", expanded=False):
    mic = st.audio_input("Record", label_visibility="collapsed", key="mic")
    if mic is not None:
        audio_bytes = mic.getvalue()
        audio_hash = hash(audio_bytes)
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
                result = run_agent(
                    user_input,
                    history=st.session_state.history[:-1],
                )
                answer = result["answer"]
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
        _render_tool_calls(tool_calls, key_prefix="new")

    st.session_state.history.append({
        "role": "assistant",
        "text": answer,
        "tool_calls": tool_calls,
    })
    st.rerun()
