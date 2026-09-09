from __future__ import annotations
import time

# ==== 게임 밸런스 상수 ====
BASE_MAX_ENERGY = 1000
ENERGY_PER_LEVEL = 500
ENERGY_REGEN_PER_SEC = 1 / 3  # 3초당 에너지 1 회복

UPGRADES = {
    "tap": {"name": "탭 파워", "emoji": "👊", "base_cost": 100, "cost_mult": 1.5, "desc": "탭당 코인 +1"},
    "energy": {"name": "에너지 확장", "emoji": "🔋", "base_cost": 150, "cost_mult": 1.6, "desc": "최대 에너지 +500"},
    "miner": {"name": "자동 채굴기", "emoji": "⛏️", "base_cost": 300, "cost_mult": 1.8, "desc": "초당 코인 +1 (방치 수익)"},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    username TEXT,
    coins REAL NOT NULL DEFAULT 0,
    total_earned REAL NOT NULL DEFAULT 0,
    tap_level INTEGER NOT NULL DEFAULT 0,
    energy_level INTEGER NOT NULL DEFAULT 0,
    miner_level INTEGER NOT NULL DEFAULT 0,
    energy REAL NOT NULL DEFAULT 1000,
    last_update REAL NOT NULL DEFAULT 0
);
"""


def upgrade_cost(upgrade_id: str, current_level: int) -> int:
    cfg = UPGRADES[upgrade_id]
    return round(cfg["base_cost"] * (cfg["cost_mult"] ** current_level))


def coins_per_tap(tap_level: int) -> int:
    return 1 + tap_level


def max_energy_for(energy_level: int) -> int:
    return BASE_MAX_ENERGY + energy_level * ENERGY_PER_LEVEL


def passive_per_sec(miner_level: int) -> int:
    return miner_level


async def init_schema(client) -> None:
    await client.execute(SCHEMA)
    try:
        # 기존에 배포되어 있던 테이블에는 이 컬럼이 없을 수 있어 마이그레이션으로 추가 (이미 있으면 에러 무시)
        await client.execute("ALTER TABLE users ADD COLUMN total_earned REAL NOT NULL DEFAULT 0")
    except Exception:
        pass


def _public_state(row: dict) -> dict:
    return {
        "telegram_id": row["telegram_id"],
        "first_name": row["first_name"],
        "coins": row["coins"],
        "energy": row["energy"],
        "max_energy": max_energy_for(row["energy_level"]),
        "coins_per_tap": coins_per_tap(row["tap_level"]),
        "passive_per_sec": passive_per_sec(row["miner_level"]),
        "energy_regen_per_sec": ENERGY_REGEN_PER_SEC,
        "server_time": row["last_update"],
        "upgrades": {
            uid: {
                **cfg,
                "level": row[f"{uid}_level"],
                "next_cost": upgrade_cost(uid, row[f"{uid}_level"]),
            }
            for uid, cfg in UPGRADES.items()
        },
    }


def _recompute(row: dict, now: float) -> dict:
    """마지막 갱신 이후 지난 시간만큼 에너지 회복 + 자동채굴 수익을 반영한다 (저장은 호출자 책임)."""
    elapsed = max(0.0, now - row["last_update"])
    row = dict(row)
    row["energy"] = min(max_energy_for(row["energy_level"]), row["energy"] + elapsed * ENERGY_REGEN_PER_SEC)
    passive_gain = elapsed * passive_per_sec(row["miner_level"])
    row["coins"] = row["coins"] + passive_gain
    row["total_earned"] = row.get("total_earned", 0) + passive_gain
    row["last_update"] = now
    return row


async def _fetch_row(client, telegram_id: int) -> dict | None:
    rs = await client.execute("SELECT * FROM users WHERE telegram_id = ?", [telegram_id])
    if not rs.rows:
        return None
    return rs.rows[0].asdict()


async def _save_row(client, row: dict) -> None:
    await client.execute(
        "UPDATE users SET coins=?, total_earned=?, energy=?, last_update=?, tap_level=?, energy_level=?, miner_level=?, "
        "first_name=?, username=? WHERE telegram_id=?",
        [
            row["coins"], row["total_earned"], row["energy"], row["last_update"],
            row["tap_level"], row["energy_level"], row["miner_level"],
            row["first_name"], row["username"], row["telegram_id"],
        ],
    )


async def get_or_create_user(client, tg_user: dict) -> dict:
    tg_id = tg_user["id"]
    now = time.time()
    row = await _fetch_row(client, tg_id)
    if row is None:
        await client.execute(
            "INSERT INTO users (telegram_id, first_name, username, coins, total_earned, tap_level, energy_level, miner_level, energy, last_update) "
            "VALUES (?, ?, ?, 0, 0, 0, 0, 0, ?, ?)",
            [tg_id, tg_user.get("first_name", "플레이어"), tg_user.get("username"), BASE_MAX_ENERGY, now],
        )
        row = await _fetch_row(client, tg_id)

    row["first_name"] = tg_user.get("first_name", row["first_name"])
    row["username"] = tg_user.get("username", row["username"])
    row = _recompute(row, now)
    await _save_row(client, row)
    return _public_state(row)


async def apply_tap(client, telegram_id: int, tap_count: int) -> dict:
    now = time.time()
    row = await _fetch_row(client, telegram_id)
    if row is None:
        raise ValueError("유저 없음 (먼저 /api/state 호출 필요)")
    row = _recompute(row, now)

    available = int(row["energy"])
    accepted = min(tap_count, available)
    gain = accepted * coins_per_tap(row["tap_level"])
    row["energy"] -= accepted
    row["coins"] += gain
    row["total_earned"] = row.get("total_earned", 0) + gain

    await _save_row(client, row)
    state = _public_state(row)
    state["accepted_taps"] = accepted
    return state


async def apply_upgrade(client, telegram_id: int, upgrade_id: str) -> dict:
    now = time.time()
    row = await _fetch_row(client, telegram_id)
    if row is None:
        raise ValueError("유저 없음 (먼저 /api/state 호출 필요)")
    row = _recompute(row, now)

    level_key = f"{upgrade_id}_level"
    cost = upgrade_cost(upgrade_id, row[level_key])
    if row["coins"] < cost:
        raise ValueError(f"코인이 부족해 ({cost - row['coins']:.0f}개 더 필요)")

    row["coins"] -= cost
    row[level_key] += 1

    await _save_row(client, row)
    return _public_state(row)


async def get_leaderboard(client, limit: int = 20) -> list[dict]:
    # 현재 잔액(coins)이 아니라 역대 누적 획득량(total_earned, 상점에서 소모한 것도 포함) 기준으로 순위를 매김
    rs = await client.execute(
        "SELECT telegram_id, first_name, total_earned FROM users ORDER BY total_earned DESC LIMIT ?", [limit]
    )
    result = []
    for i, r in enumerate(rs.rows):
        d = r.asdict()
        result.append({
            "rank": i + 1,
            "telegram_id": d["telegram_id"],
            "first_name": d["first_name"],
            "coins": round(d["total_earned"]),
        })
    return result
