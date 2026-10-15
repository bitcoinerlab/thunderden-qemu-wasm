"""Start the actual generated Wasm in Chromium; no guest boot is claimed here.

Requires the Python playwright package and Chromium (installed by Playwright or
selected with --chromium). Serves artifacts on an ephemeral localhost port only.
"""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("artifacts", type=Path)
parser.add_argument("--chromium")
args = parser.parse_args()
artifacts = args.artifacts.resolve()
assert (artifacts / "qemu-system-x86_64.wasm").is_file(), "Build Wasm first"
harness = Path(__file__).with_name("wasm-smoke.html").read_bytes()


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/smoke.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(harness)
        else:
            super().do_GET()

    def log_message(self, *_):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(artifacts)))
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium, headless=True)
        try:
            for mode in ["help", "device"]:
                page = browser.new_page()
                page_errors = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/smoke.html?mode={mode}")
                try:
                    page.wait_for_function("window.smoke && (window.smoke.output.includes('frame-file') || window.smoke.output.includes('QMP') || window.smoke.errors.length || /not supported|failed|cannot|could not/i.test(window.smoke.output))", timeout=120000)
                    state = page.evaluate("({output: smoke.output, errors: smoke.errors})")
                    assert not state["errors"], state
                    assert not page_errors, page_errors
                    if mode == "help":
                        assert "frame-file" in state["output"], state
                        assert "\nv4l2\n" not in state["output"], state
                    else:
                        page.evaluate("smoke.send(JSON.stringify({execute: 'qmp_capabilities'}))")
                        page.wait_for_function("smoke.output.includes('return')", timeout=10000)
                        page.evaluate("smoke.send(JSON.stringify({execute: 'human-monitor-command', arguments: {'command-line': 'info usb'}}))")
                        page.wait_for_function("smoke.output.includes('QEMU USB Video Interface')", timeout=10000)
                        assert not page_errors, page_errors
                    print(f"PASS: browser Wasm {mode}", flush=True)
                except Exception:
                    print(json.dumps(page.evaluate("({output: window.smoke?.output, errors: window.smoke?.errors, pageErrors: []})"), indent=2))
                    print("Browser errors:", page_errors)
                    raise
                finally:
                    page.close()
        finally:
            browser.close()
finally:
    server.shutdown()
    server.server_close()
    thread.join()
