from __future__ import annotations
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# 루트 .env(텔레그램 토큰 등 공용 시크릿이 있는 곳)를 명시적으로 로드
load_dotenv(Path(__file__).resolve().parent.parent / '.env')
# 배포 URL은 로컬 tap_game/.env에 따로 둠 (배포할 때마다 바뀔 수 있어서)
load_dotenv(Path(__file__).resolve().parent / '.env')

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GAME_URL = os.environ["GAME_URL"]  # 예: https://tap-game-backend.onrender.com
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

TRIGGER_COMMANDS = {"/game", "/게임", "/탭게임"}


def send_game_button(chat_id: int) -> None:
    requests.post(f"{API_BASE}/sendMessage", json={
        "chat_id": chat_id,
        "text": "🪙 탭게임 시작하려면 아래 버튼을 눌러!",
        "reply_markup": {
            "inline_keyboard": [[{"text": "🎮 게임 열기", "web_app": {"url": GAME_URL}}]]
        },
    }, timeout=10)


def main() -> None:
    print(f"🚀 게임 봇 시작 (트리거: {', '.join(TRIGGER_COMMANDS)}) → {GAME_URL}")
    offset = 0
    while True:
        try:
            resp = requests.get(
                f"{API_BASE}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35,
            )
            resp.raise_for_status()
            for update in resp.json().get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message")
                if not message:
                    continue
                text = (message.get("text") or "").strip().split("@")[0]  # "/game@봇이름" 형태 대응
                if text in TRIGGER_COMMANDS:
                    chat_id = message["chat"]["id"]
                    print(f"  → 트리거 감지 (chat_id={chat_id})")
                    send_game_button(chat_id)
        except requests.RequestException as e:
            print(f"  ⚠️ 폴링 오류, 3초 후 재시도: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
