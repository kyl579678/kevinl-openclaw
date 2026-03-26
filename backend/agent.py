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
    max_loops: int = 5,
) -> str:
    """
    Run the agent loop: call MiniMax, detect tool calls, execute,
    feed results back, repeat until done.
    """
    api_key = get_api_key()
    if not api_key:
        return "⚠️ API Key 未設定，請聯絡站長。"

    # Build conversation with tool-aware system prompt
    system_prompt = build_system_prompt()

    # Recent history (last 10 turns)
    recent = history[-20:] if len(history) > 20 else history
    messages = [{"role": "user", "content": [{"type": "text", "text": user_message}]}]

    # Inject tool result history
    tool_turns = []
    for turn in recent:
        if turn.get("role") == "user" and str(turn.get("content", "")).startswith("[TOOL_RESULT]"):
            tool_turns.append({
                "role": "user",
                "content": [{"type": "text", "text": turn["content"]}],
            })

    # Prepend tool results
    if tool_turns:
        messages = tool_turns + messages

    loop_count = 0
    full_text_parts = []

    while loop_count < max_loops:
        loop_count += 1

        response_text = await call_minimax(api_key, system_prompt, messages)
        if not response_text:
            return "⚠️ 無法取得回應，請稍後再試。"

        # Detect tool call blocks
        tool_calls = parse_tool_calls(response_text)

        if not tool_calls:
            # No more tools → final response
            clean = strip_tool_markers(response_text)
            full_text_parts.append(clean)
            return "\n\n".join(full_text_parts).strip()

        # Strip tool markers before appending to display (tools execute silently)
        clean = strip_tool_markers(response_text)
        if clean.strip():
            full_text_parts.append(clean)

        # Execute all tools in parallel
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = [execute_tool(client, tc) for tc in tool_calls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build tool result messages
        for tc, result in zip(tool_calls, results):
            if isinstance(result, Exception):
                result_str = f"工具執行錯誤：{result}"
            else:
                result_str = result
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": f"[TOOL_RESULT]{json.dumps({'name': tc['name'], 'tool_call_id': tc['id'], 'content': result_str}, ensure_ascii=False)}"}],
            })

    return "\n\n".join(full_text_parts).strip() + "\n\n⚠️ 工具執行次數過多，已停止。"

# ── MiniMax API Call ───────────────────────────────────
MINIMAX_ENDPOINT = "https://api.minimax.io/anthropic/v1/messages"
MINIMAX_MODEL = "MiniMax-M2.5"

async def call_minimax(api_key: str, system: str, messages: list[dict]) -> str:
    payload = {
        "model": MINIMAX_MODEL,
        "max_tokens": 1024,
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
    tool_list = "\n".join(
        f'- `{name}`: {fn.__doc__ or ""}'
        for name, fn in TOOLS.items()
    )
    return f"""你是 OpenClaw 安裝助教，可以回答關於 OpenClaw 安裝、設定、使用的問題。

你擁有以下工具。**當使用者問的問題涉及你不知道的內容時，主動使用工具搜尋資料再回答。**

可用工具：
{tool_list}

重要原則：
- 優先使用 fetch_tutorial 回答教學內容相關問題
- 涉及 OpenClaw 官網文件時使用 fetch_docs
- 涉及最新資訊、安裝疑難排解、上網搜尋時使用 web_search
- **不要猜測**，遇到不確定的資訊就用工具確認
- 回答時 Markdown 格式（## 標題、**粗體**、`程式碼`、表格）
- 表格用標準 Markdown 語法（| col | col |）

工具呼叫格式（**嚴格遵守**）：
```
[TOOL_CALL]
{{"name": "工具名稱", "id": "call_1", "input": {{"參數": "值"}}}}
[/TOOL_CALL]
```

**每次最多呼叫 2 個工具**，不要一口氣呼叫 3 個以上。

如果不需要工具，直接回答即可，不要輸出 [TOOL_CALL] 區塊。"""

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
