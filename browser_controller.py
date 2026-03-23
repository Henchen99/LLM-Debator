import time
import sys
import os
import logging
import asyncio
import subprocess
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logger = logging.getLogger(__name__)


class BrowserController:
    """Controls a Playwright browser to interact with LLM web interfaces."""

    def __init__(self, user_data_dir=None):
        if user_data_dir is None:
            user_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_data")
        self.user_data_dir = user_data_dir
        self.pw = None
        self.context = None
        self.pages = {}
        self.providers = {}
        self._pre_send_response_counts = {}
        self._available_pages = []

    def _kill_stale_playwright(self):
        """Kill leftover Playwright Chromium processes only (never the user's own browser)."""
        if sys.platform != "win32":
            return
        try:
            subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                    "Where-Object { $_.ExecutablePath -like '*ms-playwright*' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
                ],
                capture_output=True, timeout=15,
            )
            time.sleep(1)
        except Exception:
            pass

    def _remove_lock_files(self):
        """Remove Chromium lock files that prevent reuse of the profile."""
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"):
            lock_file = os.path.join(self.user_data_dir, name)
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except OSError:
                    pass

    def launch(self):
        """Start the Playwright browser with persistent login session."""
        self._kill_stale_playwright()
        self._remove_lock_files()
        self.pw = sync_playwright().start()
        self.context = self.pw.chromium.launch_persistent_context(
            self.user_data_dir,
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
            ignore_default_args=["--enable-automation"],
        )
        self._available_pages = [p for p in self.context.pages if p.url == "about:blank"]

    def open_provider(self, name, config):
        """Open a new tab for an LLM provider and navigate to its URL."""
        self.providers[name] = config
        if self._available_pages:
            page = self._available_pages.pop(0)
        else:
            page = self.context.new_page()
        page.goto(config["url"], wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        self.pages[name] = page
        return page

    def select_model(self, name, model_name):
        """Select a specific model variant in the provider's model picker."""
        config = self.providers[name]
        page = self.pages[name]

        model_selector = config.get("model_selector")
        if not model_selector or not model_name:
            return False

        try:
            trigger = self._find_first_visible(page, model_selector, timeout=5000)
            if not trigger:
                logger.warning(f"Model selector trigger not found for {name}")
                return False

            trigger.click()
            page.wait_for_timeout(1000)

            model_option = page.get_by_text(model_name, exact=False).first
            model_option.click(timeout=5000)
            page.wait_for_timeout(500)
            logger.info(f"Selected model '{model_name}' for {name}")
            return True
        except Exception as e:
            logger.warning(f"Could not select model '{model_name}' for {name}: {e}")
            return False

    def detect_models(self, name):
        """Try to detect available model options from the provider's UI."""
        config = self.providers[name]
        page = self.pages[name]
        model_selector = config.get("model_selector")
        if not model_selector:
            return []

        try:
            trigger = self._find_first_visible(page, model_selector, timeout=5000)
            if not trigger:
                return []

            trigger.click()
            page.wait_for_timeout(1500)

            options = []
            option_selectors = [
                "[role='option']", "[role='menuitem']", "[role='menuitemradio']",
                "[role='radio']", "[role='tab']",
            ]
            for sel in option_selectors:
                try:
                    for el in page.locator(sel).all():
                        if el.is_visible():
                            text = el.inner_text().strip().split("\n")[0].strip()
                            if text and 1 < len(text) < 40:
                                options.append(text)
                except Exception:
                    continue

            if not options:
                try:
                    parent = trigger.locator("..").locator("..")
                    for el in parent.locator("button, label, [class*='option'], [class*='item'], [class*='segment']").all():
                        if el.is_visible():
                            text = el.inner_text().strip().split("\n")[0].strip()
                            if text and 1 < len(text) < 40 and text not in options:
                                options.append(text)
                except Exception:
                    pass

            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

            seen = set()
            deduped = []
            for o in options:
                if o not in seen:
                    seen.add(o)
                    deduped.append(o)
            return deduped
        except Exception:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return []

    def check_input_ready(self, name, timeout=10000):
        """Check if the provider's input element is visible (i.e. user is logged in)."""
        config = self.providers[name]
        page = self.pages[name]
        try:
            for selector in config["selectors"]["input"].split(", "):
                try:
                    if page.locator(selector.strip()).first.is_visible(timeout=timeout):
                        return True
                except PlaywrightTimeout:
                    continue
            return False
        except Exception:
            return False

    def send_message(self, name, message):
        """Type a message into the provider's input and click send."""
        config = self.providers[name]
        page = self.pages[name]
        selectors = config["selectors"]

        self._pre_send_response_counts[name] = self._count_responses(name)

        input_selector = selectors["input"]
        input_el = self._find_first_visible(page, input_selector, timeout=15000)
        if input_el is None:
            raise RuntimeError(f"Could not find input element for {name} using: {input_selector}")

        input_el.click()
        page.wait_for_timeout(300)

        method = config.get("input_method", "fill")
        try:
            if method == "type":
                input_el.type(message, delay=2)
            elif method == "keyboard":
                modifier = "Meta" if sys.platform == "darwin" else "Control"
                page.keyboard.press(f"{modifier}+a")
                page.keyboard.press("Backspace")
                page.keyboard.insert_text(message)
            else:
                input_el.fill(message)
        except Exception:
            logger.warning(f"Primary input method '{method}' failed for {name}, falling back to keyboard.type()")
            input_el.click()
            page.wait_for_timeout(200)
            input_el.type(message, delay=2)

        page.wait_for_timeout(500)

        send_selector = selectors["send_button"]
        send_btn = self._find_first_visible(page, send_selector, timeout=5000)
        if send_btn is None:
            logger.warning(f"Send button not visible for {name}, trying Enter key")
            page.keyboard.press("Enter")
        else:
            try:
                send_btn.click(timeout=3000)
            except Exception:
                logger.warning(f"Send button click failed for {name}, trying Enter key")
                page.keyboard.press("Enter")

    def wait_for_response(self, name, on_progress=None):
        """Wait for the LLM to finish generating and return the response text."""
        config = self.providers[name]
        page = self.pages[name]
        selectors = config["selectors"]

        max_wait = config.get("max_wait_seconds", 180)
        stability_seconds = config.get("stability_seconds", 4)

        pre_count = self._pre_send_response_counts.get(name, 0)

        page.wait_for_timeout(2000)

        start = time.time()
        while time.time() - start < 30:
            current_count = self._count_responses(name)
            if current_count > pre_count:
                break
            time.sleep(0.5)

        last_text = ""
        stable_ticks = 0
        start = time.time()

        while time.time() - start < max_wait:
            time.sleep(1)

            stop_selector = selectors.get("stop_button")
            if stop_selector:
                try:
                    is_generating = self._any_visible(page, stop_selector, timeout=500)
                    if is_generating:
                        stable_ticks = 0
                        try:
                            current_text = self._get_last_response_text(name)
                            if current_text:
                                last_text = current_text
                                if on_progress:
                                    on_progress(last_text)
                        except Exception:
                            pass
                        continue
                except Exception:
                    pass

            try:
                current_text = self._get_last_response_text(name)
                if current_text and current_text == last_text:
                    stable_ticks += 1
                    if stable_ticks >= stability_seconds:
                        return current_text
                else:
                    stable_ticks = 0
                    if current_text:
                        last_text = current_text
                        if on_progress:
                            on_progress(last_text)
            except Exception:
                continue

        return last_text if last_text else "[No response detected — check the browser window]"

    def test_selectors(self, name):
        """Test which selectors are found on the current page. Returns {selector_name: count}."""
        config = self.providers[name]
        page = self.pages[name]
        results = {}

        for key, selector_str in config["selectors"].items():
            total = 0
            for selector in selector_str.split(", "):
                try:
                    total += page.locator(selector.strip()).count()
                except Exception:
                    pass
            results[key] = total

        return results

    def close(self):
        """Shut down the browser and Playwright."""
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.pw:
                self.pw.stop()
        except Exception:
            pass
        self.pages = {}
        self.providers = {}
        self._available_pages = []

    def _count_responses(self, name):
        config = self.providers[name]
        page = self.pages[name]
        selector_str = config["selectors"]["response_container"]
        total = 0
        for selector in selector_str.split(", "):
            try:
                total += page.locator(selector.strip()).count()
            except Exception:
                pass
        return total

    def _get_last_response_text(self, name):
        config = self.providers[name]
        page = self.pages[name]
        selector_str = config["selectors"]["response_container"]

        for selector in selector_str.split(", "):
            try:
                elements = page.locator(selector.strip()).all()
                if elements:
                    text = elements[-1].inner_text()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return ""

    def _find_first_visible(self, page, selector_str, timeout=5000):
        for selector in selector_str.split(", "):
            try:
                el = page.locator(selector.strip()).first
                el.wait_for(state="visible", timeout=timeout)
                return el
            except (PlaywrightTimeout, Exception):
                continue
        return None

    def _any_visible(self, page, selector_str, timeout=500):
        for selector in selector_str.split(", "):
            try:
                if page.locator(selector.strip()).first.is_visible(timeout=timeout):
                    return True
            except Exception:
                continue
        return False
