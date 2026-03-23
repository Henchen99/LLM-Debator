# LLM Debator

Pit two LLMs against each other in a structured debate — no API keys needed. The app automates your **real browser sessions** (ChatGPT, Gemini, Claude, Grok, DeepSeek) using Playwright, so you use your existing free-tier accounts.

## How It Works

1. Playwright opens a real Chromium browser with a persistent profile (logins are saved).
2. You log into your LLM accounts once through that browser.
3. Pick two LLMs, enter a debate topic, set the number of rounds, and hit Start.
4. The app types the topic into LLM 1, grabs the response, passes it to LLM 2, grabs that response, and keeps going back and forth for N rounds.
5. On the final round, both LLMs are asked to find common ground.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Install the Chromium browser for Playwright
playwright install chromium
```

## Usage

```bash
streamlit run app.py
```

This opens a web UI where you can:
- **Login Setup** — Opens the Playwright browser so you can log into your LLM accounts. Sessions persist in the `browser_data/` folder.
- **Test Selectors** — Checks if the CSS selectors in `providers.json` still match each site's DOM. Useful when a site updates its UI.
- **Start Debate** — Runs the automated debate.
- **Download Transcript** — Saves the debate as a Markdown file.

## Adding or Updating Providers

All provider configs live in `providers.json`. Each entry has:

```json
{
    "ProviderName": {
        "url": "https://example.com/chat",
        "selectors": {
            "input": "CSS selector for the text input/editor",
            "send_button": "CSS selector for the send button",
            "response_container": "CSS selector for response message elements",
            "stop_button": "CSS selector for the stop/cancel generation button"
        },
        "input_method": "fill | type | keyboard",
        "stability_seconds": 4,
        "max_wait_seconds": 180
    }
}
```

### Selector tips

- Use your browser's DevTools (F12 > Elements) to inspect the chat input, send button, and response containers.
- Multiple fallback selectors can be comma-separated: `"button.send, button[aria-label='Send']"`.
- `input_method` options:
  - `fill` — Playwright's built-in fill (works for most inputs and contenteditable).
  - `type` — Simulates keystrokes one by one (slower but more compatible with rich editors).
  - `keyboard` — Uses `keyboard.insert_text()` (fast, dispatches input events).
- `stability_seconds` — How many seconds the response text must remain unchanged before it's considered complete.
- `max_wait_seconds` — Maximum time to wait for any single response.

### Finding selectors with DevTools

1. Open the LLM site in Chrome.
2. Right-click the text input area and select **Inspect**.
3. Look for a unique `id`, `data-testid`, `aria-label`, or `class` on the element.
4. Do the same for the send button and the response message containers.
5. Update `providers.json` with the new selectors.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Input not found" | Your selectors are stale. Run **Test Selectors** or update `providers.json`. |
| `fill()` doesn't trigger the send button | Change `input_method` to `"type"` or `"keyboard"` in `providers.json`. |
| Response detection times out | Increase `stability_seconds` or `max_wait_seconds`. |
| Login not persisting | Make sure the `browser_data/` folder isn't being deleted between runs. |
| Browser opens but is empty | Run `playwright install chromium` to install browser binaries. |

## Project Structure

```
LLM Debator/
├── app.py                 # Streamlit web UI and debate orchestration
├── browser_controller.py  # Playwright browser automation
├── providers.json         # LLM provider configurations (selectors, URLs)
├── requirements.txt       # Python dependencies
├── browser_data/          # Persistent browser profile (auto-created, gitignored)
└── README.md
```
