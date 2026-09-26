#!/usr/bin/env python3
"""
Clawli 云中继服务端 —— 把「手机 ↔ PC」的 WebSocket 流量原样转发（穿透 NAT）。

架构：
    手机 App ──ws──▶ 中继(本程序) ◀──ws── PC 端 relay_client.py ──ws──▶ 本机 Clawli (127.0.0.1:9079)

协议（极简、透明转发，Clawli 自己的密码鉴权帧原样穿过中继）：
    连接 URL:  ws://<host>:<port>/ws?room=<房间码>&role=<pc|phone>
    - room: 房间码（自选密串，PC 与手机一致），每个房间最多 2 个对端
    - role: pc=主机端（每房间仅一个），phone=手机端（每房间仅一个）
    - 任一端发来的文本/二进制帧原样转发给房间内另一端，中继不解析内容

运行：
    python relay_server.py --host 0.0.0.0 --port 8900
    # 可选：--auth-token <令牌>  连接方需带 &token=<令牌>（部署在公网时建议开启）
"""
import argparse
import asyncio
import json
import logging
import time
from urllib.parse import parse_qs, urlparse

import websockets

try:  # websockets >= 13 新式 asyncio API
    from websockets.asyncio.server import serve
except ImportError:  # 旧版 fallback
    from websockets.server import serve

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("clawli-relay")

# room -> {"pc": ws|None, "phone": ws|None}
ROOMS = {}
ROOMS_LOCK = asyncio.Lock()


def _is_open(ws):
    """兼容新旧 websockets 的连接存活判断"""
    if ws is None:
        return False
    state = getattr(ws, "state", None)
    if state is not None:
        try:
            return state.name == "OPEN"
        except Exception:
            return True
    return bool(getattr(ws, "open", False))


def _path(websocket):
    """兼容新旧 API 取请求路径"""
    req = getattr(websocket, "request", None)
    if req is not None and getattr(req, "path", None):
        return req.path
    return getattr(websocket, "path", "") or ""


def _query(websocket):
    qs = parse_qs(urlparse(_path(websocket)).query)
    # 同名参数出现多个不同值 → 视为非法（防参数走私/客户端拼接事故）
    for key in ("room", "role", "token"):
        vals = qs.get(key) or []
        if len(set(vals)) > 1:
            return "", "", "\x00conflict"
    get = lambda k, d="": (qs.get(k) or [d])[0]
    return get("room"), get("role"), get("token")


async def _pair(room, role, ws):
    """登记对端；返回房间内的另一端（没有则 None）。同角色重复连接踢掉旧的。"""
    async with ROOMS_LOCK:
        slot = ROOMS.setdefault(room, {"pc": None, "phone": None})
        old = slot.get(role)
        peer = slot.get("phone" if role == "pc" else "pc")
        slot[role] = ws
    if _is_open(old):
        log.info("room=%s role=%s 顶替旧连接", room, role)
        try:
            await old.close(4000, "replaced by new connection")
        except Exception:
            pass
    return peer


async def _unpair(room, role, ws):
    async with ROOMS_LOCK:
        slot = ROOMS.get(room)
        if not slot:
            return
        if slot.get(role) is ws:
            slot[role] = None
        if slot.get("pc") is None and slot.get("phone") is None:
            ROOMS.pop(room, None)


async def handler(websocket):
    room, role, token = _query(websocket)
    # ── 基础校验 ──
    if not room or len(room) < 4:
        await websocket.close(4001, "room required (>=4 chars)")
        return
    if role not in ("pc", "phone"):
        await websocket.close(4002, "role must be pc|phone")
        return
    if AUTH_TOKEN and token != AUTH_TOKEN:
        await websocket.close(4003, "bad token")
        return

    peer = await _pair(room, role, websocket)
    log.info("room=%s %s 已连接 (peer=%s)", room, role, "在" if peer else "无")
    try:
        if _is_open(peer):
            await peer.send(json.dumps({"type": "relay", "event": "peer_joined",
                                        "role": role, "ts": time.time()}))
        async for frame in websocket:
            target = peer
            if target is None or not _is_open(target):
                # 重新取一次房间对端（对端可能已重连）
                async with ROOMS_LOCK:
                    slot = ROOMS.get(room) or {}
                    target = slot.get("phone" if role == "pc" else "pc")
                peer = target
            if _is_open(target):
                await target.send(frame)
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        log.warning("room=%s %s 转发异常: %s", room, role, e)
    finally:
        await _unpair(room, role, websocket)
        log.info("room=%s %s 断开", room, role)
        if _is_open(peer):
            try:
                await peer.send(json.dumps({"type": "relay", "event": "peer_left",
                                            "role": role, "ts": time.time()}))
            except Exception:
                pass


async def main(host, port):
    log.info("Clawli 云中继启动: ws://%s:%d/ws?room=<房间码>&role=<pc|phone>  auth=%s",
             host, port, "开" if AUTH_TOKEN else "关")
    async with serve(handler, host, port, ping_interval=20, ping_timeout=20,
                     max_size=64 * 1024 * 1024):  # 支持大文件帧（base64 图片/文件）
        await asyncio.Future()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Clawli 云中继服务端")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8900)
    ap.add_argument("--auth-token", default="",
                    help="可选连接令牌（公网部署建议开启，两端都要带 &token=）")
    args = ap.parse_args()
    AUTH_TOKEN = args.auth_token
    try:
        asyncio.run(main(args.host, args.port))
    except KeyboardInterrupt:
        log.info("中继关闭")
