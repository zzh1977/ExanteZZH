#!/usr/bin/env python3
"""测试用的假 Ollama 服务：不需要真模型，按固定规则返回分类结果。

  python tests/fake_ollama.py            # 监听 127.0.0.1:11434
  python tests/fake_ollama.py --port 11500

只实现整理工具用到的两个接口：GET /api/tags（列出模型）、POST /api/chat（返回 JSON）。
返回值一定在请求的 category 枚举里，用来检查流程，不检查分类质量。
"""
import argparse
import http.server
import json

MODELS = ["qwen3:8b", "llama3.1:8b", "qwen3-vl:4b", "gemma3:12b", "qwen3-vl:8b"]


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send({"models": [{"name": m} for m in MODELS]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msg = body["messages"][0]
        cats = body["format"]["properties"]["category"]["enum"]
        if msg.get("images"):  # 照片
            ans = {"category": cats[1], "title": "测试照片", "summary": "测试", "tags": ["照片"],
                   "confidence": "高"}
        elif "language" in body["format"]["properties"]:  # 英德文
            content = msg["content"].split("Content (beginning):", 1)[-1]
            de = any(w in content for w in ("Sehr geehrte", " und ", " der ", "Rechnung"))
            ans = {"category": cats[0], "language": "de" if de else "en",
                   "title": "Testdokument" if de else "Test document", "summary": "测试文档",
                   "tags": ["test"], "date": "2024-03-01", "confidence": "高"}
        else:  # 中文
            ans = {"category": cats[0], "title": "测试文档", "summary": "测试", "tags": ["测试"],
                   "date": "", "confidence": "中"}
        assert ans["category"] in cats
        self._send({"message": {"content": json.dumps(ans, ensure_ascii=False)}})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=11434)
    a = ap.parse_args()
    http.server.HTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
