"""
Roblox Monitor - Main entry point
Handles: certificate installation, system proxy setup, tray icon, proxy thread
"""

import sys
import os
import subprocess
import threading
import ctypes
import winreg
import tempfile
import time
from pathlib import Path

# ── Ensure running as admin (needed for cert install + proxy settings) ────────
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    """Re-launch self as administrator"""
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(sys.argv), None, 1
    )
    sys.exit()

# ── Certificate management ────────────────────────────────────────────────────
CERT_NAME = "RobloxMonitor"
CERT_PATH = Path(os.environ.get("APPDATA", "")) / "RobloxMonitor" / "cert.p12"

def get_mitmproxy_cert():
    """Get the mitmproxy CA cert path (generated on first run)"""
    mitmproxy_cert = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.cer"
    return mitmproxy_cert

def is_cert_installed():
    """Check if our cert is already in Windows trusted root store"""
    result = subprocess.run(
        ["certutil", "-store", "Root", CERT_NAME],
        capture_output=True, text=True
    )
    return CERT_NAME in result.stdout

def install_cert(cert_path: Path):
    """Install cert to Windows trusted root store"""
    result = subprocess.run(
        ["certutil", "-addstore", "-f", "Root", str(cert_path)],
        capture_output=True, text=True
    )
    return result.returncode == 0

def uninstall_cert():
    """Remove cert from Windows trusted root store"""
    subprocess.run(
        ["certutil", "-delstore", "Root", CERT_NAME],
        capture_output=True
    )

# ── System proxy management ───────────────────────────────────────────────────
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 8080

def set_system_proxy(enable: bool):
    """Enable or disable Windows system proxy"""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0, winreg.KEY_SET_VALUE
        )
        if enable:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{PROXY_HOST}:{PROXY_PORT}")
            # Bypass local addresses
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "<local>")
        else:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        # Notify Windows of proxy change
        ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
        return True
    except Exception as e:
        print(f"[!] Proxy set error: {e}")
        return False

# ── First run setup ───────────────────────────────────────────────────────────
def first_run_setup():
    """Generate mitmproxy cert and install it"""
    from mitmproxy.certs import Cert
    import mitmproxy.proxy.server

    # Start proxy briefly to generate cert
    print("[*] Generating certificate...")
    from proxy import run_proxy
    t = threading.Thread(target=run_proxy, daemon=True)
    t.start()
    time.sleep(3)  # Wait for cert to generate

    cert_path = get_mitmproxy_cert()
    if not cert_path.exists():
        print("[!] Certificate not generated")
        return False

    print("[*] Installing certificate to Windows trusted store...")
    print("[!] Windows will ask for confirmation - please click Yes")
    
    if not install_cert(cert_path):
        print("[!] Certificate installation failed")
        return False

    print("[+] Certificate installed successfully")
    return True

# ── Tray icon ─────────────────────────────────────────────────────────────────
def create_tray_icon(stop_event: threading.Event):
    """Create system tray icon with right-click menu"""
    try:
        import pystray
        from PIL import Image, ImageDraw

        # Create a simple icon (green circle)
        def create_icon_image():
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([8, 8, 56, 56], fill=(0, 200, 100, 255))
            return img

        def on_quit(icon, item):
            print("[*] Shutting down...")
            set_system_proxy(False)
            stop_event.set()
            icon.stop()

        icon = pystray.Icon(
            "RobloxMonitor",
            create_icon_image(),
            "Roblox Monitor - Running",
            menu=pystray.Menu(
                pystray.MenuItem("Roblox Monitor - Active", lambda: None, enabled=False),
                pystray.MenuItem("Quit", on_quit)
            )
        )
        icon.run()
    except Exception as e:
        print(f"[!] Tray error: {e}")
        # Fallback — just keep running without tray
        stop_event.wait()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Require admin
    if not is_admin():
        print("[*] Requesting administrator privileges...")
        run_as_admin()
        return

    print("[*] Roblox Monitor starting...")

    # First run — install cert if needed
    cert_path = get_mitmproxy_cert()
    if not cert_path.exists() or not is_cert_installed():
        success = first_run_setup()
        if not success:
            input("[!] Setup failed. Press Enter to exit.")
            sys.exit(1)
    else:
        # Start proxy normally
        from proxy import run_proxy
        proxy_thread = threading.Thread(target=run_proxy, daemon=True)
        proxy_thread.start()
        print("[+] Proxy started on 127.0.0.1:8080")

    # Enable system proxy
    set_system_proxy(True)
    print("[+] System proxy enabled")

    # Run tray icon (blocks until quit)
    stop_event = threading.Event()
    create_tray_icon(stop_event)

    # Cleanup on exit
    set_system_proxy(False)
    print("[*] Proxy disabled. Goodbye.")


if __name__ == "__main__":
    main()
