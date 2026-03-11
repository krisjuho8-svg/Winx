"""
Winx Browser - Main entry point
Handles: certificate installation, system proxy setup, tray icon, proxy thread, startup
"""

import sys
import os
import subprocess
import threading
import ctypes
import winreg
import time
from pathlib import Path

# ── Ensure running as admin ───────────────────────────────────────────────────
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    exe = sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, "", None, 1)
    sys.exit()

# ── Startup registry ──────────────────────────────────────────────────────────
STARTUP_KEY_NAME = "WinxBrowser"

def is_in_startup():
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_READ
        )
        winreg.QueryValueEx(key, STARTUP_KEY_NAME)
        winreg.CloseKey(key)
        return True
    except:
        return False

def add_to_startup():
    try:
        exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, STARTUP_KEY_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
        winreg.CloseKey(key)
        print("[+] Added to Windows startup")
        return True
    except Exception as e:
        print(f"[!] Startup registry error: {e}")
        return False

# ── Certificate management ────────────────────────────────────────────────────
CERT_NAME = "WinxBrowser"

def get_mitmproxy_cert():
    return Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.cer"

def is_cert_installed():
    result = subprocess.run(
        ["certutil", "-store", "Root", CERT_NAME],
        capture_output=True, text=True
    )
    return CERT_NAME in result.stdout

def install_cert(cert_path: Path):
    result = subprocess.run(
        ["certutil", "-addstore", "-f", "Root", str(cert_path)],
        capture_output=True, text=True
    )
    return result.returncode == 0

# ── System proxy management ───────────────────────────────────────────────────
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 8080

def set_system_proxy(enable: bool):
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0, winreg.KEY_SET_VALUE
        )
        if enable:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{PROXY_HOST}:{PROXY_PORT}")
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "<local>")
        else:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
        return True
    except Exception as e:
        print(f"[!] Proxy set error: {e}")
        return False

# ── First run setup ───────────────────────────────────────────────────────────
def first_run_setup():
    from proxy import run_proxy

    print("[*] Generating certificate...")
    t = threading.Thread(target=run_proxy, daemon=True)
    t.start()
    time.sleep(3)

    cert_path = get_mitmproxy_cert()
    if not cert_path.exists():
        print("[!] Certificate not generated")
        return False

    print("[*] Installing certificate...")
    if not install_cert(cert_path):
        print("[!] Certificate installation failed")
        return False

    print("[+] Certificate installed")

    if not is_in_startup():
        add_to_startup()

    return True

# ── Tray icon ─────────────────────────────────────────────────────────────────
def create_tray_icon(stop_event: threading.Event):
    try:
        import pystray
        from PIL import Image, ImageDraw

        def create_icon_image():
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([8, 8, 56, 56], fill=(0, 120, 215, 255))
            return img

        def on_quit(icon, item):
            set_system_proxy(False)
            stop_event.set()
            icon.stop()

        icon = pystray.Icon(
            "WinxBrowser",
            create_icon_image(),
            "Winx Browser",
            menu=pystray.Menu(
                pystray.MenuItem("Winx Browser", lambda: None, enabled=False),
                pystray.MenuItem("Quit", on_quit)
            )
        )
        icon.run()
    except Exception as e:
        print(f"[!] Tray error: {e}")
        stop_event.wait()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not is_admin():
        run_as_admin()
        return

    cert_path = get_mitmproxy_cert()
    is_first_run = not cert_path.exists() or not is_cert_installed()

    if is_first_run:
        # First run: generate cert, install it, add to startup
        # proxy already started inside first_run_setup
        success = first_run_setup()
        if not success:
            sys.exit(1)
    else:
        # Subsequent runs including after reboot: just start proxy
        from proxy import run_proxy
        proxy_thread = threading.Thread(target=run_proxy, daemon=True)
        proxy_thread.start()

        # Re-add to startup if removed
        if not is_in_startup():
            add_to_startup()

    set_system_proxy(True)

    stop_event = threading.Event()
    create_tray_icon(stop_event)

    # Cleanup on exit
    set_system_proxy(False)

if __name__ == "__main__":
    main()
