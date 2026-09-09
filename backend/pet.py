from __future__ import annotations
import time

import db  # 코인 잔액은 users 테이블 걸 그대로 씀 (탭게임과 같은 지갑)

# ==== 펫 밸런스 상수 ====
GROWTH_PER_SEC = 1 / 60  # 방치해도 분당 1씩 자동 성장
FEED_BASE_COST = 20
FEED_COST_STEP = 15  # 먹일 때마다 비용이 이만큼씩 늘어남
FEED_GROWTH_GAIN = 50

STAGES = [
    (0, "알", "🥚"),
    (100, "새끼", "🐣"),
    (500, "청소년", "🐥"),
    (2000, "성체", "🐓"),
    (8000, "전설", "🦅"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS pets (
    telegram_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '반려동물',
    growth REAL NOT NULL DEFAULT 0,
    times_fed INTEGER NOT NULL DEFAULT 0,
    last_update REAL NOT NULL DEFAULT 0
);
"""


async def init_schema(client) -> None:
    await client.execute(SCHEMA)


def feed_cost(times_fed: int) -> int:
    return FEED_BASE_COST + times_fed * FEED_COST_STEP


def _stage_info(growth: float) -> dict:
    current = STAGES[0]
    next_stage = None
    for i, s in enumerate(STAGES):
        if growth >= s[0]:
            current = s
            next_stage = STAGES[i + 1] if i + 1 < len(STAGES) else None
        else:
            break
    return {
        "name": current[1],
        "emoji": current[2],
        "next_threshold": next_stage[0] if next_stage else None,
        "next_name": next_stage[1] if next_stage else None,
        "is_max": next_stage is None,
    }


def _public_pet_state(row: dict) -> dict:
    return {
        "name": row["name"],
        "growth": round(row["growth"], 1),
        "times_fed": row["times_fed"],
        "stage": _stage_info(row["growth"]),
        "feed_cost": feed_cost(row["times_fed"]),
        "growth_per_sec": GROWTH_PER_SEC,
    }


def _recompute(row: dict, now: float) -> dict:
    elapsed = max(0.0, now - row["last_update"])
    row = dict(row)
    row["growth"] += elapsed * GROWTH_PER_SEC
    row["last_update"] = now
    return row


async def _fetch_pet(client, telegram_id: int) -> dict | None:
    rs = await client.execute("SELECT * FROM pets WHERE telegram_id = ?", [telegram_id])
    if not rs.rows:
        return None
    return rs.rows[0].asdict()


async def _save_pet(client, row: dict) -> None:
    await client.execute(
        "UPDATE pets SET name=?, growth=?, times_fed=?, last_update=? WHERE telegram_id=?",
        [row["name"], row["growth"], row["times_fed"], row["last_update"], row["telegram_id"]],
    )


async def get_or_create_pet(client, telegram_id: int) -> dict:
    now = time.time()
    row = await _fetch_pet(client, telegram_id)
    if row is None:
        await client.execute(
            "INSERT INTO pets (telegram_id, name, growth, times_fed, last_update) VALUES (?, '반려동물', 0, 0, ?)",
            [telegram_id, now],
        )
        row = await _fetch_pet(client, telegram_id)

    row = _recompute(row, now)
    await _save_pet(client, row)
    return _public_pet_state(row)


async def feed_pet(client, telegram_id: int) -> dict:
    now = time.time()
    pet_row = await _fetch_pet(client, telegram_id)
    if pet_row is None:
        raise ValueError("펫이 없음 (먼저 /api/pet 호출 필요)")
    pet_row = _recompute(pet_row, now)

    user_row = await db._fetch_row(client, telegram_id)
    if user_row is None:
        raise ValueError("유저 없음 (먼저 탭게임 화면을 한번 열어줘)")
    user_row = db._recompute(user_row, now)

    cost = feed_cost(pet_row["times_fed"])
    if user_row["coins"] < cost:
        raise ValueError(f"코인이 부족해 ({cost - user_row['coins']:.0f}개 더 필요)")

    user_row["coins"] -= cost
    await db._save_row(client, user_row)

    pet_row["growth"] += FEED_GROWTH_GAIN
    pet_row["times_fed"] += 1
    await _save_pet(client, pet_row)

    return {"pet": _public_pet_state(pet_row), "coins": user_row["coins"]}


async def rename_pet(client, telegram_id: int, name: str) -> dict:
    name = name.strip()[:20]
    if not name:
        raise ValueError("이름이 비어있어")
    now = time.time()
    row = await _fetch_pet(client, telegram_id)
    if row is None:
        raise ValueError("펫이 없음 (먼저 /api/pet 호출 필요)")
    row = _recompute(row, now)
    row["name"] = name
    await _save_pet(client, row)
    return _public_pet_state(row)


async def get_leaderboard(client, limit: int = 20) -> list[dict]:
    rs = await client.execute(
        "SELECT telegram_id, name, growth FROM pets ORDER BY growth DESC LIMIT ?", [limit]
    )
    result = []
    for i, r in enumerate(rs.rows):
        d = r.asdict()
        stage = _stage_info(d["growth"])
        result.append({
            "rank": i + 1,
            "telegram_id": d["telegram_id"],
            "name": d["name"],
            "stage": stage["name"],
            "emoji": stage["emoji"],
            "growth": round(d["growth"]),
        })
    return result
