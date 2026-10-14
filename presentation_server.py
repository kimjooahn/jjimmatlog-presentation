"""Presentation server for the restaurant review scoring demo."""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIRECTORY = PROJECT_ROOT / "data"
APP_HTML = PROJECT_ROOT / "project_ui.html"
MAX_REQUEST_BYTES = 20_000
MAX_PHOTO_BYTES = 6_000_000

sys.path.insert(0, str(PROJECT_ROOT))

from scoring.new_review import score_new_review


def load_review_photo_urls() -> dict[str, list[str]]:
    photos = {}
    for source_path in sorted(DATA_DIRECTORY.glob("*-reviews.json")):
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        for review in payload.get("reviews", []):
            review_id = str(review.get("id") or review.get("review_id") or "")
            has_photo = bool(review.get("has_photo", review.get("hasImage", False)))
            urls = review.get("imageUrls") or review.get("image_urls") or []
            valid_urls = [
                url for url in urls
                if isinstance(url, str) and url.startswith("https://")
            ] if isinstance(urls, list) else []
            if review_id and has_photo and valid_urls:
                photos[review_id] = valid_urls
    return photos


class PresentationHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        request_path = urlsplit(self.path).path
        if request_path == "/api/review-photos":
            try:
                self._send_json(200, {"photos": load_review_photo_urls()})
            except (OSError, json.JSONDecodeError):
                self._send_json(500, {"error": "리뷰 사진 정보를 읽을 수 없습니다."})
            return

        if request_path == "/api/review-photo":
            query = parse_qs(urlsplit(self.path).query)
            review_id = query.get("review_id", [""])[0]
            try:
                photo_index = int(query.get("index", ["0"])[0])
                urls = load_review_photo_urls().get(review_id, [])
                if not review_id or photo_index < 0 or photo_index >= len(urls):
                    self.send_error(404)
                    return
                request = Request(urls[photo_index], headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(request, timeout=15) as response:
                    content_type = response.headers.get_content_type()
                    if not content_type.startswith("image/"):
                        self.send_error(502, "Source did not return an image")
                        return
                    image_data = response.read(MAX_PHOTO_BYTES + 1)
                if len(image_data) > MAX_PHOTO_BYTES:
                    self.send_error(413, "Image response is too large")
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(image_data)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(image_data)
            except (OSError, ValueError, json.JSONDecodeError):
                self.send_error(502, "Could not load the source review image")
            return

        if request_path != "/":
            self.send_error(404)
            return
        try:
            body = APP_HTML.read_bytes()
        except OSError:
            self.send_error(500, "App HTML file is unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/score-new-review":
            self._send_json(404, {"error": "요청한 API를 찾을 수 없습니다."})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
                self._send_json(413, {"error": "요청 크기가 올바르지 않습니다."})
                return
            payload = json.loads(self.rfile.read(content_length))
            if not isinstance(payload, dict):
                raise ValueError("요청 본문은 JSON 객체여야 합니다.")

            result = score_new_review(payload)
            review = result["review"]
            criteria = review["text_analysis"]["criteria"]
            mentioned_aspects = [
                aspect for aspect, analysis in criteria.items()
                if analysis["sentiment"] != "not_mentioned"
            ]
            self._send_json(200, {
                "review_id": review["review_id"],
                "original_rating": review["original_rating"],
                "review_adjusted_score": review["review_adjusted_score"],
                "text_analysis": review["text_analysis"],
                "mentioned_aspects": mentioned_aspects,
            })
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json(400, {"error": str(error)})
        except Exception:
            self._send_json(500, {"error": "점수 계산 중 서버 오류가 발생했습니다."})


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer(("0.0.0.0", port), PresentationHandler)
    print(f"찐맛로그 발표 서버 listening on port {port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()