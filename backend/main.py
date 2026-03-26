"""
FastAPI backend for OpenClaw Tutorial — split panel with integrated chat.
Serves:
  - GET /  → tutorial page (left) + chat panel (right 30%)
  - POST /api/chat → { message, history } → { response }
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
app = FastAPI(title="OpenClaw Tutorial")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE = Path(__file__).parent
TUTORIAL_HTML = BASE.parent / "openclaw" / "tutorial.html"
CHAT_CSS = BASE / "chat-widget.css"
CHAT_JS  = BASE / "chat-widget.js"

# ── API Models ──────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []

class ChatResponse(BaseModel):
    response: str
    error: Optional[str] = None

# ── Routes ─────────────────────────────────────────────────────────────
@app.post("/api/chat", response_model=ChatResponse)
async def api_chat(req: ChatRequest):
    result = await chat(req.message, req.history)
    return ChatResponse(response=result)

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def serve_tutorial():
    """Split-panel layout: tutorial left (70%) + chat right (30%)."""
    if not TUTORIAL_HTML.exists():
        return JSONResponse(status_code=404, content={"error": "tutorial.html not found"})

    tutorial_html = TUTORIAL_HTML.read_text(encoding="utf-8")
    css = CHAT_CSS.read_text(encoding="utf-8") if CHAT_CSS.exists() else ""
    js  = CHAT_JS.read_text(encoding="utf-8")  if CHAT_JS.exists()  else ""

    # Strip tutorial.html's own <head> and <body> wrapper tags to extract inner content
    # Remove doctype, html, head, body tags
    inner = tutorial_html
    for tag in ("<!DOCTYPE html>", "<html lang=\"zh-TW\">", "</html>",
                "<head>", "</head>", "<body>", "</body>"):
        inner = inner.replace(tag, "")

    # Inject our layout: CSS in <head>, tutorial in left panel, chat in right
    panel_html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
/* Inherited tutorial styles (no reset — preserve page styles) */
{css}
</style>
</head>
<body>
  <!-- Tutorial content (left 70%) -->
  <div class="tutorial-panel">
{inner}
  </div>

  <!-- Chat panel (right 30%) -->
  <div class="chat-panel">
    <div class="chat-panel-header">
      <span class="header-icon">🦞</span>
      <span>OpenClaw 安裝助教</span>
      <span class="header-sub">AI 客服</span>
    </div>
    <div id="chat-messages" class="chat-messages"></div>
    <div class="chat-input-area">
      <input id="chat-input" class="chat-input"
             type="text"
             placeholder="問我關於 OpenClaw 安裝的問題…"
             autocomplete="off" />
      <button id="chat-send" class="chat-send">送出</button>
    </div>
  </div>

<script>
{js}
</script>
</body>
</html>"""

    return HTMLResponse(content=panel_html, media_type="text/html; charset=utf-8")

# ── Run ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("CHATBOT_PORT", "9200"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
