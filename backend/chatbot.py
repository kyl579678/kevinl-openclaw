"""
MiniMax API client + RAG context from tutorial content.
"""

import os, re, httpx
from typing import Optional

MINIMAX_ENDPOINT = "https://api.minimax.io/anthropic/v1/messages"
MINIMAX_MODEL = "MiniMax-M2.5"

TUTORIAL_CONTEXT = """
你是 OpenClaw 安裝助教，專門幫助使用者解決 OpenClaw 安裝與使用的問題。
你只能回答與 OpenClaw 安裝、設定、有關的技術問題。
如果問題與 OpenClaw 無關，禮貌地說這不在你的專業範圍內。

以下是你知道的 OpenClaw 安裝知識：

## WSL2 安裝
- 在 PowerShell（系統管理員）執行：wsl --install
- 安裝完成後重啟電腦，Ubuntu 終端機會要求建立 Linux 帳密

## WSL2 DNS 修復（重要！第一個坑）
症狀：ping -c 2 google.com 出現 name resolution 錯誤
修復步驟：
1. 在 Ubuntu 執行：sudo sh -c 'echo "nameserver 8.8.8.8" > /etc/resolv.conf'
2. 再執行：sudo sh -c 'echo -e "[network]\\ngenerateResolvConf = false" > /etc/wsl.conf'
3. 在 PowerShell 執行：wsl --shutdown
4. 重新開啟 Ubuntu 終端機，再次測試 ping

## Node.js 22 安裝
指令：
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
驗證：node --version（需顯示 v22.x.x）

## OpenClaw 安裝
npm install -g openclaw
openclaw onboard --install-daemon
選擇 QuickStart，技能先 Skip

## Claude API 申請
1. 前往 console.anthropic.com 註冊
2. 左側 Billing → 加入信用卡，設定月消費上限
3. API Keys → Create Key → 複製（只顯示一次！）
模型：claude-sonnet-4-5 或 claude-opus-4-5

## MiniMax API 申請
1. 前往 platform.minimax.io/subscribe/token-plan 選購 TokenPlan
2. Dashboard → API Keys → 建立並複製 Key
3. 模型名稱：MiniMax-M2.5 或 MiniMax-M2.7

## Telegram Bot 設定
1. 在 Telegram 搜尋 @BotFather → /newbot → 設定名稱和 username
2. 儲存 Bot Token（不要公開！）
3. 搜尋 @userinfobot → /start → 記下 User ID

## 配對 Telegram 帳號
1. 在 Telegram 找到你的 bot → Start → 傳送任意訊息
2. 取得配對碼（如 84KXQ9XM）
3. 在 Ubuntu 執行：openclaw pairing approve telegram <配對碼>
配對碼有一小時有效期限

## 常見問題排解
- setMyCommands 網路請求失敗 → WSL2 DNS 沒修好，回到 DNS 修復步驟
- Token 有效但 bot 不回應 → 可能 webhook 衝突，執行 deleteWebhook 清除
- pairing required 迴圈 → 舊版 process 殘留，ps aux | grep openclaw 檢查後 restart
- allowFrom 不生效 → 只接受數字 User ID，不接受 @username，執行 openclaw doctor --fix
- 401 Unauthorized → Token 複製有隱藏字元，去 BotFather 重新產生

## Control UI 開啟方式
- 方法一：openclaw dashboard（自動打開瀏覽器）
- 方法二：瀏覽器直接輸入 http://127.0.0.1:18789/
- 方法三：SSH Tunnel

## 常用 CLI 指令
- openclaw gateway status → 查看 Gateway 狀態
- openclaw channels status → 查看訊息管道狀態
- openclaw logs --follow → 查看即時日誌
- openclaw doctor --fix → 自動健康檢查 + 修復
- openclaw update → 更新到最新版
- openclaw gateway restart → 重啟服務
"""


def strip_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def get_api_key() -> Optional[str]:
    # Try backend/.env first, then project root .env
    for path in [
        os.path.join(os.path.dirname(__file__), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
    ]:
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


async def chat(message: str, history: list[dict]) -> str:
    key = get_api_key()
    if not key:
        return "⚠️ API Key 未設定。請聯絡站長設定 MiniMax API Key。"

    # Build conversation history (last 6 turns to save tokens)
    recent = history[-12:] if len(history) > 12 else history
    messages = []
    for turn in recent:
        role = "user" if turn["role"] == "user" else "assistant"
        messages.append({"role": role, "content": [{"type": "text", "text": turn["content"]}]})

    system_msg = (
        "你是 OpenClaw 安裝助教，專門幫助使用者解決 OpenClaw 安裝與使用的問題。"
        "你只能回答與 OpenClaw 安裝、設定、有關的技術問題。"
        "如果問題與 OpenClaw 無關，禮貌地說這不在你的專業範圍內，"
        "建議使用者參考官方文件：https://docs.openclaw.ai\n\n"
        + TUTORIAL_CONTEXT
    )

    payload = {
        "model": MINIMAX_MODEL,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": [{"type": "text", "text": message}]}],
        "system": [{"type": "text", "text": system_msg}],
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(MINIMAX_ENDPOINT, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # MiniMax with thinking: content[0] = think block, content[1] = actual response
        content = data.get("content", [])
        if isinstance(content, list) and len(content) > 1:
            return content[1].get("text", str(content[-1]))
        elif isinstance(content, list) and len(content) == 1:
            return content[0].get("text", str(content[0]))
        return str(data.get("content", "無回應"))

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return "⚠️ API Key 無效或已過期。請聯絡站長更換 API Key。"
        return f"⚠️ API 錯誤：{e.response.status_code} — {e.response.text[:200]}"
    except Exception as e:
        return f"⚠️ 發生錯誤：{str(e)}"
