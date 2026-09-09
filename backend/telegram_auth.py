from __future__ import annotations
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

# initData가 이보다 오래되면 재전송(리플레이) 공격으로 간주하고 거부
INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60


class InvalidInitData(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str) -> dict:
    """텔레그램 WebApp이 보낸 initData를 서명 검증하고 user 정보를 dict로 반환한다.
    검증 방법: https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app
    봇 토큰을 아는 서버만 정상적인 hash를 만들어낼 수 있으므로, 클라이언트가 user id를 위조할 수 없다."""
    if not init_data:
        raise InvalidInitData("initData가 비어있음")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InvalidInitData("hash 필드 없음")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise InvalidInitData("hash 불일치 (위조된 initData)")

    auth_date = int(pairs.get("auth_date", 0))
    if time.time() - auth_date > INIT_DATA_MAX_AGE_SECONDS:
        raise InvalidInitData("initData 만료됨")

    user_json = pairs.get("user")
    if not user_json:
        raise InvalidInitData("user 필드 없음")
    return json.loads(user_json)
