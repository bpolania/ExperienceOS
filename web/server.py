"""Local web server for the ExperienceOS ledger demo.

A thin, stdlib-only HTTP wrapper around the real ExperienceOS SDK: the
canonical adopted lifecycle composition (deterministic update/forget
controllers, bounded runtime transition authority, planner precedence)
with a switchable response provider — Alibaba Cloud Qwen when configured,
the offline deterministic provider otherwise.

Serves the static front-end from this directory and a small JSON API:

    GET  /api/state     provider + composition posture (booleans, no secrets)
    GET  /api/ledger    current memory lifecycle state for the demo user
    GET  /api/turns     accumulated per-turn traces (engine room)
    POST /api/chat      {message, session_id} -> reply + turn trace + ledger
    POST /api/provider  {provider: "qwen"|"offline"} -> rebuild agent, keep memory
    POST /api/reset     clear the demo user's memory and turn history

Binds to 127.0.0.1 only. Never returns or logs a credential.

Run:  PYTHONPATH=. python web/server.py   ->  http://localhost:8517
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
ROOT = WEB_DIR.parent
sys.path.insert(0, str(ROOT))

from demo.env import load_local_env  # noqa: E402

load_local_env()

from demo.support import (  # noqa: E402
    create_agent,
    forgotten_rows,
    reset_demo_state,
    superseded_rows,
)
from demo.transition_diagnostics import transition_trace  # noqa: E402
from experienceos.memory import InMemoryMemoryStore  # noqa: E402
from experienceos.providers import MockProvider  # noqa: E402
from experienceos.providers.qwen_cloud import QwenCloudProvider  # noqa: E402

# Bind config from environment so the same server runs locally (127.0.0.1)
# or in a container/VM (0.0.0.0). No secret is read here.
HOST = os.environ.get("EXPERIENCEOS_WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("EXPERIENCEOS_WEB_PORT", "8517"))
USER = "you"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
}


def _build_provider(name: str):
    if name == "qwen":
        return QwenCloudProvider(timeout=90)
    return MockProvider()


class _State:
    """One agent over one shared store; provider switches keep the memory."""

    def __init__(self):
        self.lock = threading.Lock()
        self.store = InMemoryMemoryStore()
        self.provider_name = "qwen" if QwenCloudProvider().is_configured else "offline"
        self.agent = create_agent(_build_provider(self.provider_name), self.store)
        self.turns: list[dict] = []
        self.turn_seq = 0

    def rebuild(self, provider_name: str):
        self.provider_name = provider_name
        self.agent = create_agent(_build_provider(provider_name), self.store)

    def reset(self):
        reset_demo_state(self.agent, USER)
        self.store = InMemoryMemoryStore()
        self.agent = create_agent(_build_provider(self.provider_name), self.store)
        self.turns = []
        self.turn_seq = 0


STATE = _State()


# --- payload builders --------------------------------------------------------


def _state_payload() -> dict:
    qwen = QwenCloudProvider()
    return {
        "provider": STATE.provider_name,
        "qwen_configured": qwen.is_configured,
        "model": qwen.model if STATE.provider_name == "qwen" else "deterministic",
        "backend": "Alibaba Cloud DashScope" if STATE.provider_name == "qwen" else "offline",
        "transition_mode": "adopted",
        "user_id": USER,
    }


def _ledger_payload() -> dict:
    agent = STATE.agent
    by_replaced = {r["Memory"]: r.get("Replaced by") for r in superseded_rows(agent, USER)}
    by_reason = {r["Memory"]: r.get("Reason") for r in forgotten_rows(agent, USER)}

    def entries(status: str) -> list[dict]:
        out = []
        for m in agent.memories_for_user(USER, status=status):
            d = {"id": m.id, "kind": m.kind, "text": m.text}
            if status == "superseded":
                d["replaced_by"] = by_replaced.get(m.text)
            if status == "forgotten":
                d["reason"] = by_reason.get(m.text)
            out.append(d)
        return out

    return {
        "active": entries("active"),
        "superseded": entries("superseded"),
        "forgotten": entries("forgotten"),
    }


def _turn_payload(events, session_id: str, message: str) -> dict:
    created, superseded, forgotten, planner = [], [], [], []
    context: dict = {}
    for e in events:
        p = e.payload
        if e.type == "memory_created":
            created.append({"kind": p.get("kind"), "text": p.get("text")})
        elif e.type == "memory_superseded":
            if not any(s["text"] == p.get("text") for s in superseded):
                superseded.append({"text": p.get("text")})
        elif e.type == "memory_forgotten":
            if not any(f["text"] == p.get("text") for f in forgotten):
                forgotten.append({"text": p.get("text"), "reason": p.get("reason")})
        elif e.type == "memory_action_planned":
            planner = [
                {"action": a.get("action"), "text": a.get("text")}
                for a in p.get("planned_actions", [])
            ]
        elif e.type == "context_built":
            context = {
                "records": [
                    {
                        "text": r.get("text"),
                        "kind": r.get("kind"),
                        "selected": bool(r.get("selected")),
                        "reason": r.get("reason"),
                    }
                    for r in (p.get("selection_records") or [])
                ],
                "budget": p.get("memory_budget"),
                "selected_count": p.get("selected_memory_count"),
                "skipped_count": p.get("skipped_memory_count"),
            }

    transition = None
    trace = transition_trace(events)
    if trace:
        t = trace[-1]
        rep = t.get("replacement") or {}
        transition = {
            "effect": t.get("canonical_action_effect"),
            "type": t.get("transition_type"),
            "route": t.get("route"),
            "verifier": t.get("verifier_status"),
            "authority_checked": bool(t.get("runtime_authority_checked")),
            "authority_reason": t.get("runtime_authority_reason") or "",
            "receipt": t.get("runtime_authorization_receipt_digest") or "",
            "authorized": t.get("authorized"),
            "auth_reason": t.get("authorization_reason") or "",
            "replacement": {
                "applied": bool(rep.get("applied")),
                "receipt_issued": bool(rep.get("runtime_replacement_receipt_issued")),
                "plan_status": rep.get("plan_status"),
            },
        }

    return {
        "session_id": session_id,
        "message": message,
        "created": created,
        "superseded": superseded,
        "forgotten": forgotten,
        "planner": planner,
        "context": context,
        "transition": transition,
    }


# --- HTTP handler ------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "ExperienceOSWeb/1.0"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str):
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_DIR / name).resolve()
        if not str(target).startswith(str(WEB_DIR)) or not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type", _CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def do_GET(self):
        if self.path == "/api/state":
            self._json(_state_payload())
        elif self.path == "/api/ledger":
            with STATE.lock:
                self._json(_ledger_payload())
        elif self.path == "/api/turns":
            with STATE.lock:
                self._json({"turns": STATE.turns})
        elif self.path.startswith("/api/"):
            self.send_error(404)
        elif self.path == "/favicon.ico":
            self._static("/favicon.svg")
        else:
            self._static(self.path.split("?")[0])

    def do_POST(self):
        if self.path == "/api/chat":
            data = self._body()
            message = (data.get("message") or "").strip()
            session_id = data.get("session_id") or "session-1"
            if not message:
                self._json({"error": "empty_message"}, 400)
                return
            with STATE.lock:
                agent = STATE.agent
                n = len(agent.events)
                try:
                    reply = agent.chat(
                        user_id=USER, session_id=session_id, message=message
                    )
                except Exception as exc:  # provider failure: type name only
                    self._json({"error": type(exc).__name__}, 502)
                    return
                turn = _turn_payload(agent.events[n:], session_id, message)
                STATE.turn_seq += 1
                turn["seq"] = STATE.turn_seq
                STATE.turns.append(turn)
                self._json(
                    {"reply": reply, "turn": turn, "ledger": _ledger_payload()}
                )
        elif self.path == "/api/provider":
            name = self._body().get("provider")
            if name not in ("qwen", "offline"):
                self._json({"error": "unknown_provider"}, 400)
                return
            if name == "qwen" and not QwenCloudProvider().is_configured:
                self._json({"error": "qwen_not_configured"}, 409)
                return
            with STATE.lock:
                STATE.rebuild(name)
                self._json(_state_payload())
        elif self.path == "/api/reset":
            with STATE.lock:
                STATE.reset()
                self._json({"ok": True, "ledger": _ledger_payload()})
        else:
            self.send_error(404)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    where = "localhost" if HOST in ("127.0.0.1", "localhost") else HOST
    print(f"ExperienceOS ledger demo -> http://{where}:{PORT}  (bind {HOST}:{PORT})")
    print(f"provider: {STATE.provider_name} (qwen configured: "
          f"{QwenCloudProvider().is_configured})")
    server.serve_forever()


if __name__ == "__main__":
    main()
