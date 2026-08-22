#!/usr/bin/env python3
"""
dashboard-server.py — Local HTTP server for live dashboard refresh.
Runs on 127.0.0.1:9787 (local-only, no auth required).
Endpoints:
  GET /           → serve dashboard.html
  GET /refresh    → regenerate metrics, respond with new HTML fragment or JSON
  GET /metrics.json → raw metrics dict
Usage: python3 dashboard-server.py [--port 9787]
"""
import http.server
import json
import pathlib
import subprocess
import sys
import argparse
import urllib.parse
from io import StringIO

DASHBOARD_SCRIPT = pathlib.Path(__file__).parent / "dashboard.py"
DASHBOARD_HTML = pathlib.Path.home() / "RavenVault" / "dashboard.html"
PORT = 9787


def run_dashboard_script() -> dict:
    """Execute dashboard.py and parse output."""
    try:
        result = subprocess.run(
            ["python3", str(DASHBOARD_SCRIPT), "--html"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {"error": f"dashboard.py failed: {result.stderr}"}

        # If it outputs JSON, parse it
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            # Otherwise just return success
            return {"html_generated": True}
    except Exception as e:
        return {"error": str(e)}


def render_html_with_refresh() -> str:
    """Serve the dashboard HTML with a refresh bar injected."""
    if not DASHBOARD_HTML.exists():
        return "<h1>Dashboard not found</h1>"

    html = DASHBOARD_HTML.read_text(errors="ignore")

    # Inject refresh bar at the top
    refresh_bar = """
    <div style="background: #2d3748; color: #white; padding: 12px 20px;
                display: flex; justify-content: space-between; align-items: center;
                font-family: monospace; font-size: 14px;">
        <span>🔄 Dashboard Server (auto-refresh available)</span>
        <button onclick="location.reload()" style="padding: 6px 12px; background: #4299e1;
                color: white; border: none; border-radius: 4px; cursor: pointer;">
            Refresh
        </button>
    </div>
    <script>
    // Auto-refresh every 30 seconds if enabled
    if (localStorage.getItem('auto-refresh') === 'true') {
        setInterval(() => location.reload(), 30000);
    }
    </script>
    """

    # Insert after opening body tag
    html = html.replace("<body>", f"<body>{refresh_bar}", 1)
    return html


VAULT_DASH = pathlib.Path.home() / "RavenVault" / "dashboard"
_SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
if str(_SCRIPTS / "dashboard") not in sys.path:
    sys.path.insert(0, str(_SCRIPTS / "dashboard"))


class DashboardRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler for dashboard server."""

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/settings":
            self.send_response(404)
            self.end_headers()
            return
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            patch = json.loads(raw.decode() or "{}")
            from dash_settings import save
            out = save(patch)
            body = json.dumps({"ok": True, "settings": out}).encode()
            self.send_response(200)
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self.send_response(400)
        self.send_header("Content-type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        """Handle GET requests."""
        path = urllib.parse.urlparse(self.path).path

        if path in ("/", "/raven-dashboard.html"):
            target = VAULT_DASH / "raven-dashboard.html"
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(target.read_bytes() if target.is_file() else b"missing raven-dashboard.html")
            return

        if path == "/api/settings":
            from dash_settings import public_view
            body = json.dumps(public_view()).encode()
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/refresh":
            data = run_dashboard_script()
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
            return

        rel = path.lstrip("/")
        fpath = (VAULT_DASH / rel).resolve()
        if str(fpath).startswith(str(VAULT_DASH.resolve())) and fpath.is_file():
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(fpath.read_bytes())
            return
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not found")

    def log_message(self, format: str, *args) -> None:
        """Suppress default logging."""
        pass


def main() -> None:
    """Start the dashboard server."""
    parser = argparse.ArgumentParser(description="Raven Dashboard Server")
    parser.add_argument("--port", type=int, default=9787, help="Port to listen on")
    args = parser.parse_args()

    server_address = ("127.0.0.1", args.port)
    httpd = http.server.HTTPServer(server_address, DashboardRequestHandler)

    print(f"🚀 Dashboard server running on http://127.0.0.1:{args.port}")
    print(f"   Endpoints:")
    print(f"   • GET /           → serve dashboard.html with refresh bar")
    print(f"   • GET /refresh    → regenerate + return JSON")
    print(f"   • GET /metrics.json → raw metrics")
    print(f"")
    print(f"   Press Ctrl+C to stop")
    print(f"")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n✅ Server stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
