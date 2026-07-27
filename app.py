"""Streamlit UI for the Personal AI Assistant (Strategic Intelligence)."""
from __future__ import annotations

#fix for azure
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

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
from logigramme import generate_logigramme_from_eb, get_logigramme
from rag import clear_index, index_file, list_sources
from voice import synthesize, transcribe
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

st.set_page_config(
    page_title="Amaris DFI Assistant",
    page_icon="🤖",
    layout="wide",
)

# ---------- Auth gate ----------
if not login_form():
    st.stop()


st.title("Amaris Consulting — DFI Intelligence Assistant")
st.caption(
    "Assistant stratégique pour le département DFI (Automation & AI) · "
    "RAG sur vos documents internes + recherche web Tavily · Powered by Groq (llama-3.3-70b-versatile) + ONNX embeddings"
)


# ---------- Sidebar ----------

with st.sidebar:
    logout_button(location=st.sidebar)
    st.divider()

    st.header("Base de connaissances")
    st.caption("Upload vos documents internes : expressions de besoin, polices d'assurance, rapports DFI (PDF/DOCX/PPTX/TXT/MD).")

    uploads = st.file_uploader(
        "Upload documents",
        type=["pdf", "docx", "pptx", "txt", "md"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    if uploads:
        if st.button("Indexer les fichiers", type="primary", use_container_width=True):
            import traceback

            errors = []
            successes = []
            progress = st.progress(0.0, text="Indexing…")
            for i, f in enumerate(uploads, start=1):
                try:
                    progress.progress((i - 0.5) / len(uploads), text=f"Traitement de {f.name}…")
                    data = f.getvalue()
                    n = index_file(f.name, data)
                    if n == 0:
                        errors.append({"name": f.name, "msg": "Aucun texte extrait — PDF scanné ?", "tb": ""})
                    else:
                        successes.append(f"{f.name} ({n} chunks)")
                    progress.progress(i / len(uploads), text=f"✓ {f.name}")
                except Exception as e:
                    tb = traceback.format_exc()
                    errors.append({"name": f.name, "msg": str(e), "tb": tb})
                    print(f"[index] ERROR on {f.name}: {e}\n{tb}")

            progress.empty()
            st.session_state["index_results"] = {"successes": successes, "errors": errors}
            st.rerun()

    # Show indexing results persisted across rerun
    results = st.session_state.get("index_results")
    if results:
        for s in results["successes"]:
            st.success(f"✅ {s}")
        for err in results["errors"]:
            st.error(f"❌ **{err['name']}** — {err['msg']}")
            if err["tb"]:
                with st.expander("Voir le détail de l'erreur"):
                    st.code(err["tb"], language="python")

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
    f"📅 Daily Consulting Briefing — {today.isoformat()}",
    expanded=bool(today_brief),
):
    if today_brief is None:
        st.caption(
            "Six daily intelligence areas: AI & automation news, consulting market trends, "
            "competitor moves, regulatory updates, DFI project alerts, HR & employee benefits."
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


# ---------- Main: logigramme EB ----------

with st.expander("📊 Générateur de Logigramme — Expression de Besoin", expanded=False):
    st.caption(
        "Uploadez un fichier Expression de Besoin (EB) pour générer automatiquement "
        "un logigramme du processus décrit. Résultat téléchargeable en PNG."
    )
    
    eb_upload = st.file_uploader(
        "Choisir un fichier EB",
        type=["pdf", "docx", "txt"],
        key="eb_uploader",
        label_visibility="collapsed",
    )
    
    if eb_upload:
        col_gen, col_info = st.columns([1, 2])
        with col_gen:
            if st.button("🔄 Générer le logigramme", type="primary", use_container_width=True):
                with st.spinner(f"Analyse de {eb_upload.name} et génération du logigramme…"):
                    try:
                        result = generate_logigramme_from_eb(eb_upload.name, eb_upload.getvalue())
                        st.session_state["current_logigramme_id"] = result["logigramme_id"]
                        st.session_state["current_logigramme_error"] = None
                        st.rerun()
                    except Exception as e:
                        st.session_state["current_logigramme_error"] = str(e)
                        st.session_state["current_logigramme_id"] = None
                        st.rerun()
        with col_info:
            st.info(f"📄 **{eb_upload.name}** — prêt pour analyse")

    # Afficher erreur si présente
    logi_err = st.session_state.get("current_logigramme_error")
    if logi_err:
        st.error(f"❌ {logi_err}")

    # Afficher logigramme si généré
    logi_id = st.session_state.get("current_logigramme_id")
    if logi_id:
        logi = get_logigramme(logi_id)
        if logi:
            st.success(f"✅ Logigramme généré depuis **{logi['source_file']}**")
            
            # Afficher le titre et les acteurs
            structure = logi.get("structure", {})
            if structure.get("titre"):
                st.markdown(f"**Processus :** {structure['titre']}")
            if structure.get("acteurs"):
                st.markdown(f"**Acteurs :** {', '.join(structure['acteurs'])}")
            
            # Afficher l'image
            st.image(logi["bytes"], use_container_width=True)
            
            # Bouton téléchargement PNG
            st.download_button(
                label=f"⬇ Télécharger {logi['filename']}",
                data=logi["bytes"],
                file_name=logi["filename"],
                mime="image/png",
                key=f"dl_logi_{logi_id}",
                use_container_width=True,
            )
            
            # Optionnel: afficher le code DOT (pour debug ou import dans d'autres outils)
            with st.expander("🔧 Code source Graphviz (DOT)", expanded=False):
                st.code(logi["dot_code"], language="dot")
            
            # Résumé des étapes
            etapes = structure.get("etapes", [])
            if etapes:
                with st.expander(f"📋 Étapes du processus ({len(etapes)} étapes)", expanded=False):
                    for e in etapes:
                        icon = {"debut": "⚫", "fin": "⚫", "decision": "◇", "action": "▭"}.get(e.get("type", "action"), "▭")
                        acteur = f" *({e.get('acteur', '')})*" if e.get("acteur") else ""
                        st.markdown(f"{icon} **{e['id']}** — {e['label']}{acteur}")


# ---------- Main: chat ----------

if "history" not in st.session_state:
    st.session_state.history = []

# Quick-start prompts (shown only on an empty conversation).
if not st.session_state.history:
    st.subheader("Essayez une question rapide")
    quick = [
        "Quels sont les principaux concurrents d'Amaris en automatisation et IA en 2026 ?",
        "Résume les exigences du projet dans les documents uploadés.",
        "Quelles sont mes garanties d'assurance en tant qu'employé Amaris ?",
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
    "Posez votre question sur vos projets DFI, l'assurance, ou l'actualité consulting…"
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
