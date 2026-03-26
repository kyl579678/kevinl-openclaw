"""
FastAPI backend — OpenClaw Tutorial with simulated-agent chat.
Serves:
  GET  /              → split-panel page (tutorial left + chat right 30%)
  POST /api/chat      → agent loop with tool calling
  GET  /shared/<file> → serve shared assets (chat.css, chat.js, marked.min.js)
  POST /api/tools/<name> → execute individual tool
"""

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from agent import run_agent, TOOLS

# ── App ────────────────────────────────────────────────────────────────
app = FastAPI(title="OpenClaw Tutorial Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE         = Path(__file__).parent
TUTORIAL_HTML = BASE.parent / "openclaw" / "tutorial.html"
SHARED_DIR    = Path(os.environ.get("SHARED_DIR", "/home/lin/homelab/_shared"))

# ── Models ───────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []

class ToolRequest(BaseModel):
    input: dict
    tool_call_id: str = ""

# ── Routes ───────────────────────────────────────────────────────────

@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    """Run the agent loop and return final response."""
    try:
        result = await run_agent(req.message, req.history)
        return {"response": result, "content": [{"type": "text", "text": result}]}
    except Exception as e:
        return {"response": f"錯誤：{str(e)}", "content": [{"type": "text", "text": f"錯誤：{str(e)}"}]}

@app.post("/api/tools/{tool_name}")
async def api_tool(tool_name: str, req: ToolRequest):
    """Execute a single tool directly."""
    fn = TOOLS.get(tool_name)
    if not fn:
        return JSONResponse(status_code=404, content={"error": f"未知工具：{tool_name}"})

    try:
        import asyncio
        result = await fn(req.input)
        return {"content": result}
    except Exception as e:
        return {"content": f"工具執行錯誤：{str(e)}"}

@app.get("/api/tools/list")
async def list_tools():
    """Return available tools."""
    return {"tools": [{"name": name, "doc": fn.__doc__ or ""} for name, fn in TOOLS.items()]}

@app.get("/api/health")
async def health():
    return {"status": "ok", "tools": list(TOOLS.keys())}

# ── Serve tutorial (split panel) ────────────────────────────────────
@app.get("/")
async def serve_tutorial():
    if not TUTORIAL_HTML.exists():
        return JSONResponse(status_code=404, content={"error": "tutorial.html not found"})

    tutorial_html = TUTORIAL_HTML.read_text(encoding="utf-8")
    inner = tutorial_html
    for tag in ("<!DOCTYPE html>", "<html lang=\"zh-TW\">", "</html>",
                "<head>", "</head>", "<body>", "</body>"):
        inner = inner.replace(tag, "")

    panel_html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenClaw 安裝與使用完全指南</title>
<link rel="stylesheet" href="/shared/chat.css">
<link rel="stylesheet" href="/shared/chat-panel.css">
<style>
:root {{ --chat-accent: #c0392b; }}
</style>
</head>
<body>
  <div class="tutorial-panel">
{inner}
  </div>
  <div class="chat-panel">
    <div class="chat-panel-header">
      <span class="header-icon">🦞</span>
      <span>OpenClaw 安裝助教</span>
      <span class="header-sub">AI 客服</span>
    </div>
    <div id="chat-messages" class="chat-messages"></div>
    <div class="chat-input-area">
      <input id="chat-input" class="chat-input" type="text"
             placeholder="問我關於 OpenClaw 安裝的問題…" autocomplete="off" />
      <button id="chat-send" class="chat-send">送出</button>
    </div>
  </div>
<script src="/shared/marked.min.js?v=6"></script>
<script src="/shared/chat.js?v=6"></script>
<script>initChat({{ accentColor: '#c0392b', welcomeMsg: '👋 嗨！我是 OpenClaw 安裝助教。\\n有什麼關於安裝或設定的問題，歡迎問我！' }});</script>
</body>
</html>"""
    return HTMLResponse(content=panel_html, media_type="text/html; charset=utf-8")

# ── Serve shared assets ───────────────────────────────────────────────
# /shared/chat.css → _shared/chat.css
# /shared/chat.js  → _shared/chat.js
# /shared/marked.min.js → _shared/marked.min.js

@app.get("/shared/{filename}")
async def serve_shared(filename: str):
    safe = SHARED_DIR / filename
    # Security: ensure path is within SHARED_DIR
    if not str(safe.resolve()).startswith(str(SHARED_DIR.resolve())):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    if not safe.exists():
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return FileResponse(path=str(safe))

# ── Run ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("CHATBOT_PORT", "9200"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
