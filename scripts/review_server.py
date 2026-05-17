"""
review_server.py

最新の review-report HTML をブラウザで表示し、
POST /save-review で processing/review-required/review-decisions.json を保存する
ローカル HTTP サーバー。

Usage:
    python scripts/review_server.py
    python scripts/review_server.py --port 8765
    python scripts/review_server.py --no-browser  # ブラウザ自動起動なし

保存後は apply_review_decisions.py で処理する:
    python scripts/apply_review_decisions.py
"""

import argparse
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
REVIEW_DIR = ROOT / "processing" / "review-required"
DECISIONS_FILE = REVIEW_DIR / "review-decisions.json"
DEFAULT_PORT = 8765


def get_latest_review_html() -> Optional[Path]:
    htmls = sorted(REVIEW_DIR.glob("review-report-*.html"), reverse=True)
    return htmls[0] if htmls else None


class ReviewHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  [{self.command}] {self.path}")

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, content: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html_path = get_latest_review_html()
            if not html_path:
                msg = (
                    "<html><head><meta charset='UTF-8'></head><body>"
                    "<h2>review-report HTML が見つかりません</h2>"
                    "<p>先に以下を実行してください:</p>"
                    "<pre>python scripts/process_inbox.py --dry-run</pre>"
                    "</body></html>"
                )
                self._send_html(msg.encode("utf-8"))
                return
            self._send_html(html_path.read_bytes())

        elif self.path == "/status":
            html_path = get_latest_review_html()
            self._send_json(200, {
                "status": "ok",
                "latest_report": str(html_path.name) if html_path else None,
                "decisions_exist": DECISIONS_FILE.exists(),
            })

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/save-review":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))

                DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
                DECISIONS_FILE.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                rel = DECISIONS_FILE.relative_to(ROOT)
                print(f"  [SAVED] {rel}  ({len(data.get('items', []))} 件)")
                self._send_json(200, {"ok": True, "path": str(rel)})

            except Exception as e:
                print(f"  [ERROR] {e}")
                self._send_json(500, {"ok": False, "error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()


def run(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    html_path = get_latest_review_html()
    if not html_path:
        print("警告: review-report HTML が見つかりません。")
        print("  python scripts/process_inbox.py --dry-run を先に実行してください。")
        print()
    else:
        print(f"  最新レポート: {html_path.relative_to(ROOT)}")

    try:
        server = HTTPServer(("localhost", port), ReviewHandler)
    except OSError as e:
        print(f"エラー: ポート {port} を使用できません — {e}")
        print(f"  別のポートを指定: python scripts/review_server.py --port {port + 1}")
        sys.exit(1)

    url = f"http://localhost:{port}"
    print(f"\nReview server running: {url}")
    print("終了するには Ctrl+C を押してください。\n")

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nサーバーを停止しました。")
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="review-report HTML をブラウザで表示し、保存ボタンで review-decisions.json に書き込む"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"ポート番号 (デフォルト: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="ブラウザを自動起動しない",
    )
    args = parser.parse_args()
    run(port=args.port, open_browser=not args.no_browser)
