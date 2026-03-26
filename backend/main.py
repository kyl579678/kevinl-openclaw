"""
FastAPI backend for OpenClaw Tutorial Chatbot.
Serves:
  - GET  /           → tutorial.html (the chat-enabled page)
  - POST /api/chat  → { message, history } → { response }
"""

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional

from chatbot import chat

# ── App ────────────────────────────────────────────────────────────────
app = FastAPI(title="OpenClaw Tutorial Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE = Path(__file__).parent
TUTORIAL_HTML = BASE.parent / "openclaw" / "tutorial.html"
CHAT_WIDGET_CSS = BASE / "chat-widget.css"
CHAT_WIDGET_JS = BASE / "chat-widget.js"

# ── API Models ──────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []

class ChatResponse(BaseModel):
    response: str
    error: Optional[str] = None

# ── API Routes ─────────────────────────────────────────────────────────
@app.post("/api/chat", response_model=ChatResponse)
async def api_chat(req: ChatRequest):
    result = await chat(req.message, req.history)
    return ChatResponse(response=result)

@app.get("/api/health")
async def health():
    return {"status": "ok"}

# ── Serve tutorial.html with chat widget injected ──────────────────────
@app.get("/")
async def serve_tutorial():
    """Serve tutorial.html with chat widget injected into the page."""
    if not TUTORIAL_HTML.exists():
        return JSONResponse(status_code=404, content={"error": "tutorial.html not found"})

    html = TUTORIAL_HTML.read_text(encoding="utf-8")

    # Inject CSS
    css = CHAT_WIDGET_CSS.read_text(encoding="utf-8") if CHAT_WIDGET_CSS.exists() else ""
    css_tag = f"<style>\n{css}\n</style>"

    # Inject JS
    js = CHAT_WIDGET_JS.read_text(encoding="utf-8") if CHAT_WIDGET_JS.exists() else ""
    js_tag = f"<script>\n{js}\n</script>"

    # Inject into <head> (before </head>)
    if "</head>" in html:
        html = html.replace("</head>", f"{css_tag}\n</head>")
    else:
        html = css_tag + html

    # Inject chat widget + JS before </body>
    widget_html = """
<!-- Chat Widget -->
<div id="chat-launcher" title="OpenClaw 安裝助教">💬</div>
<div id="chat-window">
  <div id="chat-header">
    <span>🦞 OpenClaw 安裝助教</span>
    <button id="chat-close">✕</button>
  </div>
  <div id="chat-messages"></div>
  <div id="chat-input-area">
    <input id="chat-input" type="text" placeholder="問我關於 OpenClaw 安裝的問題…" autocomplete="off" />
    <button id="chat-send">送出</button>
  </div>
</div>
"""
    if "</body>" in html:
        html = html.replace("</body>", f"{widget_html}{js_tag}\n</body>")
    else:
        html += f"{widget_html}{js_tag}"

    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")

# ── Run ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("CHATBOT_PORT", "9200"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
