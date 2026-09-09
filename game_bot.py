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
BOT_USERNAME = os.environ["BOT_USERNAME"]  # 예: Gambleelanciabot (앞에 @ 없이)
MINI_APP_SHORT_NAME = os.environ["MINI_APP_SHORT_NAME"]  # BotFather /newapp 에서 정한 short name
# web_app 인라인 버튼은 봇과의 1:1 채팅에서만 허용되고 그룹에서는 BUTTON_TYPE_INVALID 에러가 남.
# 대신 BotFather로 등록한 미니앱의 다이렉트 링크(t.me/봇이름/앱이름)는 그냥 URL이라 그룹에서도 열림.
GAME_DIRECT_LINK = f"https://t.me/{BOT_USERNAME}/{MINI_APP_SHORT_NAME}"
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

TRIGGER_COMMANDS = {"/game", "/게임", "/탭게임"}


def send_game_button(chat_id: int) -> None:
    resp = requests.post(f"{API_BASE}/sendMessage", json={
        "chat_id": chat_id,
        "text": "🪙 탭게임 시작하려면 아래 버튼을 눌러!",
        "reply_markup": {
            "inline_keyboard": [[{"text": "🎮 게임 열기", "url": GAME_DIRECT_LINK}]]
        },
    }, timeout=10)
    if not resp.ok:
        print(f"  ⚠️ sendMessage 실패: {resp.status_code} {resp.text}")


def main() -> None:
    print(f"🚀 게임 봇 시작 (트리거: {', '.join(TRIGGER_COMMANDS)}) → {GAME_DIRECT_LINK}")
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
