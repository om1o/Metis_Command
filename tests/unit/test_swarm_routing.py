"""Verify the local agent route without a model download or outside request."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import swarm_agents


def test_manager_calls_configured_local_ollama_endpoint(monkeypatch, tmp_path) -> None:
    seen: list[tuple[str, dict, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            seen.append((self.path, body, self.headers.get("Authorization")))
            response = {
                "id": "chatcmpl-local-test",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "local route works"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 3, "total_tokens": 6},
            }
            payload = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GLM_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setattr(swarm_agents, "OLLAMA_BASE", f"http://127.0.0.1:{server.server_port}")
        stamp = tmp_path / "setup.json"
        stamp.write_text('{"tier":"Pro"}', encoding="utf-8")
        monkeypatch.setattr(swarm_agents, "STAMP_FILE", stamp)

        result = swarm_agents._llm_for("manager").call(
            messages=[{"role": "user", "content": "Say the test phrase"}]
        )

        assert result == "local route works"
        assert len(seen) == 1
        path, body, authorization = seen[0]
        assert path == "/v1/chat/completions"
        assert body["model"] == "qwen2.5-coder:7b"
        assert authorization == "Bearer ollama"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_lite_tier_uses_model_in_lite_manifest(monkeypatch, tmp_path) -> None:
    stamp = tmp_path / "setup.json"
    stamp.write_text('{"tier":"Lite"}', encoding="utf-8")
    monkeypatch.setattr(swarm_agents, "STAMP_FILE", stamp)

    assert swarm_agents._local_model_for("manager") == "qwen2.5-coder:1.5b"
    assert swarm_agents._local_model_for("coder") == "qwen2.5-coder:1.5b"
    assert swarm_agents._local_model_for("thinker") == "deepseek-r1:1.5b"
