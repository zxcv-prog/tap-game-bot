from __future__ import annotations
import os
from contextlib import asynccontextmanager
from pathlib import Path

import libsql_client
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db as db_module
import pet as pet_module
from telegram_auth import InvalidInitData, validate_init_data

load_dotenv()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# libsql:// (웹소켓) 스킴은 환경에 따라 핸드셰이크가 막히는 경우가 있어 https(HTTP 기반 Hrana)로 강제 변환
TURSO_URL = os.environ["TURSO_DATABASE_URL"].replace("libsql://", "https://")
TURSO_AUTH_TOKEN = os.environ["TURSO_AUTH_TOKEN"]

db_client: libsql_client.Client | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_client
    db_client = libsql_client.create_client(url=TURSO_URL, auth_token=TURSO_AUTH_TOKEN)
    await db_module.init_schema(db_client)
    await pet_module.init_schema(db_client)
    yield
    await db_client.close()


app = FastAPI(lifespan=lifespan)


class TapRequest(BaseModel):
    initData: str
    count: int


class UpgradeRequest(BaseModel):
    initData: str
    upgrade: str


class RenameRequest(BaseModel):
    initData: str
    name: str


class InitDataOnlyRequest(BaseModel):
    initData: str


def _authenticate(init_data: str) -> dict:
    try:
        return validate_init_data(init_data, BOT_TOKEN)
    except InvalidInitData as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/api/state")
async def api_state(initData: str):
    user = _authenticate(initData)
    return await db_module.get_or_create_user(db_client, user)


@app.post("/api/tap")
async def api_tap(payload: TapRequest):
    user = _authenticate(payload.initData)
    if not (0 < payload.count <= 1000):
        raise HTTPException(status_code=400, detail="잘못된 탭 횟수")
    return await db_module.apply_tap(db_client, user["id"], payload.count)


@app.post("/api/upgrade")
async def api_upgrade(payload: UpgradeRequest):
    user = _authenticate(payload.initData)
    if payload.upgrade not in db_module.UPGRADES:
        raise HTTPException(status_code=400, detail="잘못된 업그레이드 종류")
    try:
        return await db_module.apply_upgrade(db_client, user["id"], payload.upgrade)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/leaderboard")
async def api_leaderboard():
    return await db_module.get_leaderboard(db_client)


@app.get("/api/pet")
async def api_pet(initData: str):
    user = _authenticate(initData)
    await db_module.get_or_create_user(db_client, user)  # 코인 지갑(users row)이 없으면 먹이주기가 안 되므로 보장해둠
    return await pet_module.get_or_create_pet(db_client, user["id"])


@app.post("/api/pet/feed")
async def api_pet_feed(payload: InitDataOnlyRequest):
    user = _authenticate(payload.initData)
    await db_module.get_or_create_user(db_client, user)
    try:
        return await pet_module.feed_pet(db_client, user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/pet/rename")
async def api_pet_rename(payload: RenameRequest):
    user = _authenticate(payload.initData)
    await db_module.get_or_create_user(db_client, user)
    try:
        return await pet_module.rename_pet(db_client, user["id"], payload.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/pet/leaderboard")
async def api_pet_leaderboard():
    return await pet_module.get_leaderboard(db_client)


# 정적 프론트엔드(탭게임 화면) 서빙 - API 라우트들 뒤에 마운트해야 /api/*가 먼저 매칭됨
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
