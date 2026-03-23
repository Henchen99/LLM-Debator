import streamlit as st
import json
import os
import time
import logging
from datetime import datetime
from browser_controller import BrowserController

logging.basicConfig(level=logging.INFO)

st.set_page_config(page_title="LLM Debator", page_icon="\u2694\ufe0f", layout="wide")

PROVIDERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers.json")


@st.cache_data
def load_providers():
    with open(PROVIDERS_FILE) as f:
        return json.load(f)


def build_prompt(round_num, total_rounds, topic, opponent_response=None, is_opener=True):
    """Build the debate prompt for a given round."""
    if round_num == 1 and is_opener:
        return (
            f'We are having a structured debate on this topic:\n\n'
            f'"{topic}"\n\n'
            f'Present your opening argument. Be clear, concise, and persuasive.'
        )

    if round_num == 1 and not is_opener:
        return (
            f'We are having a structured debate on this topic:\n\n'
            f'"{topic}"\n\n'
            f'Your opponent\'s opening argument:\n\n'
            f'---\n{opponent_response}\n---\n\n'
            f'Present your counter-argument. Address their points directly.'
        )

    if round_num == total_rounds:
        return (
            f'Your opponent responded:\n\n'
            f'---\n{opponent_response}\n---\n\n'
            f'This is the FINAL round. Summarize your strongest points, '
            f'acknowledge any valid arguments from your opponent, and '
            f'propose areas of common ground or consensus.'
        )

    return (
        f'Your opponent responded:\n\n'
        f'---\n{opponent_response}\n---\n\n'
        f'Provide your rebuttal. Address their specific points and strengthen your position.'
    )


SPEAKER_COLORS = {
    1: {"border": "#3b82f6", "bg": "#eff6ff", "label": "#1e40af"},
    2: {"border": "#f97316", "bg": "#fff7ed", "label": "#c2410c"},
}

PROMPT_STYLE = "color: #6b7280; font-size: 0.88em; border-left: 3px solid #d1d5db; padding-left: 12px; margin-bottom: 8px;"


def render_transcript(transcript):
    """Render the debate transcript with color-coded speakers and prompts."""
    current_round = 0
    for entry in transcript:
        if entry["round"] != current_round:
            current_round = entry["round"]
            st.markdown(f"---\n### Round {current_round}")

        colors = SPEAKER_COLORS[entry.get("speaker_num", 1)]

        if entry.get("prompt"):
            st.markdown(
                f'<details style="{PROMPT_STYLE}">'
                f'<summary><strong>Prompt sent to {entry["speaker"]}</strong></summary>'
                f'<p style="white-space: pre-wrap; margin-top: 6px;">{entry["prompt"]}</p>'
                f'</details>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<div style="border-left: 4px solid {colors["border"]}; '
            f'background: {colors["bg"]}; padding: 12px 16px; '
            f'border-radius: 0 8px 8px 0; margin-bottom: 16px;">'
            f'<strong style="color: {colors["label"]};">{entry["speaker"]}</strong>'
            f'<div style="margin-top: 8px; white-space: pre-wrap;">{entry["text"]}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def format_transcript_md(transcript):
    """Format the debate transcript as plain markdown (for export)."""
    md = ""
    current_round = 0
    for entry in transcript:
        if entry["round"] != current_round:
            current_round = entry["round"]
            md += f"\n---\n### Round {current_round}\n\n"
        if entry.get("prompt"):
            md += f"> **Prompt to {entry['speaker']}:**\n>\n"
            for line in entry["prompt"].split("\n"):
                md += f"> {line}\n"
            md += "\n"
        md += f"**{entry['speaker']}:**\n\n{entry['text']}\n\n"
    return md


def export_transcript(transcript, topic, llm1, llm2):
    """Export transcript as a markdown string for download."""
    header = (
        f"# LLM Debate Transcript\n\n"
        f"**Topic:** {topic}\n\n"
        f"**Debaters:** {llm1} vs {llm2}\n\n"
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"**Rounds:** {transcript[-1]['round'] if transcript else 0}\n\n"
        f"---\n\n"
    )
    return header + format_transcript_md(transcript)


# --- Session State ---
if "transcript" not in st.session_state:
    st.session_state.transcript = []
if "debate_running" not in st.session_state:
    st.session_state.debate_running = False
if "detected_models" not in st.session_state:
    st.session_state.detected_models = {}

providers = load_providers()
provider_names = list(providers.keys())

# --- Sidebar ---
with st.sidebar:
    st.header("Configuration")

    llm1 = st.selectbox("Debater 1", provider_names, index=0)
    models1 = (st.session_state.detected_models.get(llm1)
               or providers[llm1].get("models") or [])
    model1 = st.selectbox(
        "Mode 1",
        ["Default"] + models1,
        index=0,
        key="model1",
    ) if models1 else None

    llm2 = st.selectbox(
        "Debater 2",
        provider_names,
        index=min(1, len(provider_names) - 1),
    )
    models2 = (st.session_state.detected_models.get(llm2)
               or providers[llm2].get("models") or [])
    model2 = st.selectbox(
        "Mode 2",
        ["Default"] + models2,
        index=0,
        key="model2",
    ) if models2 else None

    if llm1 == llm2 and model1 == model2:
        st.warning("Pick two different LLMs/models for a real debate!")

    topic = st.text_area(
        "Debate Topic",
        placeholder="e.g., Is consciousness an emergent property of computation?",
        height=100,
    )

    rounds = st.slider("Number of Rounds", min_value=1, max_value=10, value=3)

    st.divider()

    start_btn = st.button(
        "Start Debate",
        use_container_width=True,
        type="primary",
        disabled=st.session_state.debate_running,
    )

    login_btn = st.button("Login Setup", use_container_width=True)

    test_btn = st.button("Test Selectors", use_container_width=True)

    if st.session_state.transcript:
        st.divider()
        st.download_button(
            "Download Transcript",
            data=export_transcript(st.session_state.transcript, topic, llm1, llm2),
            file_name=f"debate_{llm1}_vs_{llm2}_{datetime.now():%Y%m%d_%H%M}.md",
            mime="text/markdown",
            use_container_width=True,
        )
        if st.button("Clear Transcript", use_container_width=True):
            st.session_state.transcript = []
            st.rerun()

    st.divider()
    with st.expander("How it works"):
        st.markdown(
            "1. Click **Login Setup** to open a browser and log into your LLM accounts\n"
            "2. Sessions persist, so you only need to log in once\n"
            "3. Select two LLMs, enter a topic, set rounds\n"
            "4. Click **Start Debate** and watch the LLMs argue\n"
            "5. Selectors in `providers.json` may need updating if sites change their UI"
        )

# --- Main Area ---
st.title("LLM Debator")
label1 = f"{llm1} ({model1})" if model1 and model1 != "Default" else llm1
label2 = f"{llm2} ({model2})" if model2 and model2 != "Default" else llm2
st.caption(f"{label1} vs {label2} | {rounds} round{'s' if rounds != 1 else ''}")

# Show existing transcript
if st.session_state.transcript and not st.session_state.debate_running:
    render_transcript(st.session_state.transcript)

# --- Login Setup ---
if login_btn:
    with st.status("Opening browser for login...", expanded=True) as status:
        controller = BrowserController()
        controller.launch()

        status.write(f"Opening {llm1}...")
        controller.open_provider(llm1, providers[llm1])

        if llm1 != llm2:
            status.write(f"Opening {llm2}...")
            controller.open_provider(llm2, providers[llm2])

        status.update(
            label="Browser is open — log into your accounts, then close this status",
            state="complete",
        )
        st.info(
            "A browser window has opened. Log into your LLM accounts there. "
            "Your sessions will be saved for future debates. "
            "Close the browser window when you're done."
        )

# --- Test Selectors ---
if test_btn:
    with st.status("Testing selectors...", expanded=True) as status:
        controller = BrowserController()
        try:
            controller.launch()

            for name in set([llm1, llm2]):
                status.write(f"Opening {name}...")
                controller.open_provider(name, providers[name])
                time.sleep(3)

                results = controller.test_selectors(name)
                status.write(f"**{name}** selector results:")
                for key, count in results.items():
                    icon = "found" if count > 0 else "NOT FOUND"
                    status.write(f"  - `{key}`: {icon} ({count} elements)")

            status.update(label="Selector test complete", state="complete")
        except Exception as e:
            status.update(label=f"Error: {e}", state="error")
        finally:
            controller.close()

# --- Debate ---
if start_btn:
    if not topic:
        st.error("Please enter a debate topic!")
        st.stop()

    if llm1 == llm2:
        st.error("Please select two different LLMs!")
        st.stop()

    st.session_state.transcript = []
    st.session_state.debate_running = True

    transcript_area = st.empty()
    status_area = st.status(f"Debate: {llm1} vs {llm2}", expanded=True)

    controller = BrowserController()
    error_occurred = False

    try:
        status_area.write("Launching browser...")
        controller.launch()

        status_area.write(f"Opening {llm1}...")
        controller.open_provider(llm1, providers[llm1])
        time.sleep(2)

        status_area.write(f"Opening {llm2}...")
        controller.open_provider(llm2, providers[llm2])
        time.sleep(2)

        # Check login status
        for name in [llm1, llm2]:
            status_area.write(f"Checking if {name} is ready...")
            if not controller.check_input_ready(name, timeout=8000):
                status_area.write(
                    f"**{name}**: Input not found — please log in via the browser window."
                )
                logged_in = False
                for _ in range(90):
                    time.sleep(2)
                    if controller.check_input_ready(name, timeout=3000):
                        logged_in = True
                        break
                if not logged_in:
                    st.error(
                        f"Could not detect input for {name} after 3 minutes. "
                        f"The selectors in providers.json may need updating."
                    )
                    error_occurred = True
                    st.stop()
            status_area.write(f"{name} is ready.")

        # Detect and select models
        for name, model in [(llm1, model1), (llm2, model2)]:
            detected = controller.detect_models(name)
            if detected:
                st.session_state.detected_models[name] = detected
                status_area.write(f"Detected modes for {name}: {', '.join(detected)}")

            if model and model != "Default":
                status_area.write(f"Selecting {model} for {name}...")
                if not controller.select_model(name, model):
                    status_area.write(
                        f"Could not auto-select {model} for {name} — "
                        f"please select it manually in the browser, or update model_selector in providers.json"
                    )
                    time.sleep(5)

        # --- Run the debate ---
        last_response = None

        for round_num in range(1, rounds + 1):
            is_final = round_num == rounds

            # --- LLM 1 ---
            status_area.write(f"**Round {round_num}/{rounds}** — Sending to {llm1}...")

            prompt1 = build_prompt(
                round_num, rounds, topic,
                opponent_response=last_response,
                is_opener=True if round_num == 1 else True,
            )
            if round_num > 1:
                prompt1 = build_prompt(
                    round_num, rounds, topic,
                    opponent_response=last_response,
                    is_opener=False,
                )

            controller.send_message(llm1, prompt1)
            status_area.write(f"Waiting for {llm1} to respond...")
            response1 = controller.wait_for_response(llm1)

            st.session_state.transcript.append({
                "speaker": label1,
                "speaker_num": 1,
                "round": round_num,
                "prompt": prompt1,
                "text": response1,
            })
            with transcript_area.container():
                render_transcript(st.session_state.transcript)

            # --- LLM 2 ---
            status_area.write(f"**Round {round_num}/{rounds}** — Sending to {llm2}...")

            prompt2 = build_prompt(
                round_num, rounds, topic,
                opponent_response=response1,
                is_opener=False,
            )

            controller.send_message(llm2, prompt2)
            status_area.write(f"Waiting for {llm2} to respond...")
            response2 = controller.wait_for_response(llm2)

            st.session_state.transcript.append({
                "speaker": label2,
                "speaker_num": 2,
                "round": round_num,
                "prompt": prompt2,
                "text": response2,
            })
            with transcript_area.container():
                render_transcript(st.session_state.transcript)

            last_response = response2

            status_area.write(f"Round {round_num} complete.")

        status_area.update(label="Debate complete!", state="complete")

    except Exception as e:
        st.error(f"Error during debate: {e}")
        error_occurred = True
        import traceback
        st.expander("Error details").code(traceback.format_exc())
    finally:
        st.session_state.debate_running = False
        try:
            controller.close()
        except Exception:
            pass
