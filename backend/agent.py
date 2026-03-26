"""
Simulated Agent Loop — MiniMax structured-output tool calling.

MiniMax doesn't support native tool_use, so we use a system prompt that
instructs the model to output tool calls as structured text markers:

  [TOOL_CALL]
  {"name": "...", "id": "...", "input": {...}}
  [/TOOL_CALL]

We parse these from the response, execute tools, then feed results back
and loop until the model stops emitting tool calls.
"""

import os, re, json, asyncio, httpx
from typing import Optional

# ── Tool Registry ──────────────────────────────────────
TOOLS = {}  # name -> async function(input_dict) -> str

def register_tool(name: str):
    """Decorator to register a tool."""
    def deco(fn):
        TOOLS[name] = fn
        return fn
    return deco

# ── Tool: fetch OpenClaw docs ──────────────────────────
@register_tool("fetch_docs")
async def fetch_docs(input_dict: dict) -> str:
    """Fetch content from OpenClaw official docs."""
    url = input_dict.get("url") or input_dict.get("path", "")
    if not url:
        return "錯誤：未提供 URL"

    # Normalize path to full URL
    if not url.startswith("http"):
        url = "https://docs.openclaw.ai/" + url.lstrip("/")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            text = resp.text

        # Extract readable text (basic HTML stripping)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # Truncate to first 2000 chars
        return text[:2000] if len(text) > 2000 else text
    except Exception as e:
        return f"抓取文件失敗：{str(e)}"

# ── Tool: web search ──────────────────────────────────
@register_tool("web_search")
async def web_search(input_dict: dict) -> str:
    """Search the web using DuckDuckGo HTML (no API key needed)."""
    query = input_dict.get("query", "")
    if not query:
        return "錯誤：未提供搜尋關鍵字"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()

        text = resp.text
        # Parse DuckDuckGo HTML snippets
        snippets = re.findall(
            r'<a class="result__snippet"[^>]*>(.*?)</a>',
            text, re.DOTALL
        )
        results = []
        for s in snippets[:4]:
            s = re.sub(r'<[^>]+>', '', s).strip()
            if s:
                results.append(s)

        if not results:
            return f"找不到「{query}」的相關結果"

        out = f"🔍 搜尋「{query}」結果：\n\n"
        for i, r in enumerate(results, 1):
            out += f"{i}. {r}\n\n"
        return out.strip()
    except Exception as e:
        return f"搜尋失敗：{str(e)}"

# ── Tool: fetch tutorial ───────────────────────────────
@register_tool("fetch_tutorial")
async def fetch_tutorial(input_dict: dict) -> str:
    """Fetch a section from the tutorial by keyword search."""
    keyword = input_dict.get("keyword", "").lower()
    if not keyword:
        return "錯誤：未提供關鍵字"

    # Read tutorial HTML and search
    tutorial_path = os.path.join(
        os.path.dirname(__file__), "..", "openclaw", "tutorial.html"
    )
    if not os.path.exists(tutorial_path):
        return "找不到 tutorial.html"

    with open(tutorial_path, encoding="utf-8") as f:
        html = f.read()

    # Strip tags and extract text
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # Find sections containing keyword
    sentences = re.split(r'(?<=[。！？\n])\s*', text)
    matches = [s for s in sentences if keyword in s.lower()]
    if not matches:
        return f"在教學文件中找不到「{keyword}」相關內容"

    return "📄 教學文件相關內容：\n\n" + "\n\n".join(matches[:3])

# ── Agent Loop ─────────────────────────────────────────
async def run_agent(
    user_message: str,
    history: list[dict],
    max_loops: int = 3,
) -> str:
    """
    Run the agent: first call with tutorial knowledge.
    Only loop for tools if user explicitly asks for live search.
    """
    api_key = get_api_key()
    if not api_key:
        return "⚠️ API Key 未設定，請聯絡站長。"

    system_prompt = build_system_prompt()

    # Build message history
    recent = history[-10:] if len(history) > 10 else history
    messages = []
    for turn in recent:
        if turn.get("role") == "user":
            content = str(turn.get("content", ""))
            # Skip tool result markers from previous calls
            if content.startswith("[TOOL_RESULT]"):
                continue
            messages.append({"role": "user", "content": [{"type": "text", "text": content}]})
        elif turn.get("role") == "assistant":
            messages.append({"role": "assistant", "content": [{"type": "text", "text": str(turn.get("content", ""))}]})

    messages.append({"role": "user", "content": [{"type": "text", "text": user_message}]})

    # ── First call: use tutorial knowledge ─────────────────
    response_text = await call_minimax(api_key, system_prompt, messages)
    if not response_text:
        return "⚠️ 無法取得回應，請稍後再試。"

    # Check if user explicitly wants live search
    live_keywords = ["搜", "查", "最新", "最近", "2024", "2025", "2026", "更新"]
    wants_live = any(k in user_message for k in live_keywords)

    # Detect tool calls
    tool_calls = parse_tool_calls(response_text)

    # Only loop for tools if: (a) user asked for live info, or (b) model emitted tool calls
    if not tool_calls or not (wants_live or tool_calls):
        return strip_tool_markers(response_text).strip()

    # ── Tool loop (only for explicit live search) ───────────
    if wants_live and not tool_calls:
        # User wants live but no tools called → do web search automatically
        query = user_message
        async with httpx.AsyncClient(timeout=15.0) as client:
            result = await web_search({"query": query})
        messages.append({"role": "assistant", "content": [{"type": "text", "text": response_text}]})
        messages.append({"role": "user", "content": [{"type": "text", "text": f"[TOOL_RESULT]{{\"name\": \"web_search\", \"content\": \"{result}\"}}"}]})
        response_text = await call_minimax(api_key, system_prompt, messages)
        return strip_tool_markers(response_text).strip()

    # Tool calls present → execute and continue
    loop_count = 0
    full_text_parts = [strip_tool_markers(response_text)]
    messages.append({"role": "assistant", "content": [{"type": "text", "text": response_text}]})

    while loop_count < max_loops and tool_calls:
        loop_count += 1

        # Execute all tools in parallel
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = [execute_tool(client, tc) for tc in tool_calls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for tc, result in zip(tool_calls, results):
            result_str = str(result) if isinstance(result, Exception) else result
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": f"[TOOL_RESULT]{{\"name\": \"{tc['name']}\", \"tool_call_id\": \"{tc['id']}\", \"content\": \"{result_str}\"}}"}],
            })

        # Next call
        response_text = await call_minimax(api_key, system_prompt, messages)
        messages.append({"role": "assistant", "content": [{"type": "text", "text": response_text}]})
        tool_calls = parse_tool_calls(response_text)

        if not tool_calls:
            full_text_parts.append(strip_tool_markers(response_text))
            break

        full_text_parts.append(strip_tool_markers(response_text))

    return "\n\n".join(full_text_parts).strip()

        # Detect tool call blocks
# ── MiniMax API Call ───────────────────────────────────
MINIMAX_ENDPOINT = "https://api.minimax.io/anthropic/v1/messages"
MINIMAX_MODEL = "MiniMax-M2.5"

async def call_minimax(api_key: str, system: str, messages: list[dict]) -> str:
    payload = {
        "model": MINIMAX_MODEL,
        "max_tokens": 2048,
        "messages": messages,
        "system": [{"type": "text", "text": system}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(MINIMAX_ENDPOINT, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    content = data.get("content", [])
    if isinstance(content, list) and len(content) > 1:
        return content[1].get("text", str(content[-1]))
    elif isinstance(content, list) and len(content) == 1:
        return content[0].get("text", str(content[0]))
    return str(data.get("content", ""))

# ── Tool Call Parsing ─────────────────────────────────
TOOL_CALL_RE = re.compile(
    r'\[TOOL_CALL\]\s*(\{.*?\})\s*\[/TOOL_CALL\]',
    re.DOTALL
)

def strip_tool_markers(text: str) -> str:
    """Remove tool call blocks from display text."""
    text = re.sub(r'\[TOOL_CALL\]\s*\{.*?\}\s*\[/TOOL_CALL\]\s*', '', text, flags=re.DOTALL)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text

def parse_tool_calls(text: str) -> list[dict]:
    """Extract tool calls from model output text."""
    matches = TOOL_CALL_RE.findall(text)
    results = []
    for m in matches:
        try:
            parsed = json.loads(m)
            name = parsed.get("name", "")
            if name in TOOLS:
                results.append({
                    "id": parsed.get("id", ""),
                    "name": name,
                    "input": parsed.get("input", {}),
                })
        except json.JSONDecodeError:
            pass
    return results

async def execute_tool(client: httpx.AsyncClient, tool_call: dict) -> str:
    name = tool_call["name"]
    inp = tool_call["input"]
    fn = TOOLS.get(name)
    if fn:
        return await fn(inp)
    return f"未知工具：{name}"

# ── System Prompt Builder ──────────────────────────────
def build_system_prompt() -> str:
    # Read tutorial content to embed as knowledge base
    tutorial_path = os.path.join(
        os.path.dirname(__file__), "..", "openclaw", "tutorial.html"
    )
    tutorial_text = ""
    if os.path.exists(tutorial_path):
        with open(tutorial_path, encoding="utf-8") as f:
            html = f.read()
        # Strip HTML tags to get plain text
        tutorial_text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        tutorial_text = re.sub(r'<style[^>]*>.*?</style>', '', tutorial_text, flags=re.DOTALL)
        tutorial_text = re.sub(r'<[^>]+>', ' ', tutorial_text)
        tutorial_text = re.sub(r'\s+', ' ', tutorial_text).strip()
        # Take first 8000 chars (roughly covers all key tutorial content)
        tutorial_text = tutorial_text[:8000]

    tool_list = "\n".join(
        f'- `{name}`: {fn.__doc__ or ""}'
        for name, fn in TOOLS.items()
    )
    return f"""你是 OpenClaw 安裝助教，**用以下教學文件內容回答問題**。

## 教學文件知識庫（回答時以此為準，**不要自行臆測**）

{tutorial_text}

## 可用工具（用於查網路最新資料，不要臆測）

{tool_list}

## 工具呼叫格式（嚴格遵守）
```
[TOOL_CALL]
{{"name": "工具名", "id": "call_1", "input": {{"參數": "值"}}}}
[/TOOL_CALL]
```

## 回答原則
- **嚴格根據上方教學文件內容回答**，不要摻雜自己的猜測
- 教學文件沒有的內容 → 用 web_search 搜尋
- OpenClaw 官網細節 → 用 fetch_docs
- **不要臆測 Step/指令/URL**，有疑慮就用工具查
- 回覆格式：Markdown（## 標題、**粗體**、`程式碼`、表格）
- 表格語法：| 欄1 | 欄2 |"""

# ── API Key ────────────────────────────────────────────
def get_api_key() -> Optional[str]:
    for path in (
        os.path.join(os.path.dirname(__file__), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
    ):
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or not line:
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() in ("ANTHROPIC_API_KEY", "MINIMAX_API_KEY"):
                            return v.strip()
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MINIMAX_API_KEY")
