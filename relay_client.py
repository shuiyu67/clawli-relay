#!/usr/bin/env python3
"""
Clawli 云中继 PC 端桥接 —— 跑在你的电脑上，把本机 Clawli 挂到云中继。

链路：本机 Clawli(127.0.0.1:9079) ◀─ws─ 本程序 ─ws─▶ 云中继 ─ws─▶ 手机 App

运行：
    python relay_client.py --relay ws://<你的服务器>:8900/ws --room <房间码> \
        [--token <令牌>] [--local ws://127.0.0.1:9079]

说明：
- 双向透明转发（Clawli 的密码鉴权帧原样穿过），两端断线都会自动重连。
- 房间码自选（>=4 字符），手机端填同一个房间码即可。
"""
import argparse
import asyncio
import itertools
import json
import logging
import time

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("clawli-bridge")

_seq = itertools.count(1)


async def pipe(reader, writer, tag):
    """把 reader 的每一帧原样转发给 writer；任一端断开则抛出以重建链路。"""
    try:
        async for frame in reader:
            await writer.send(frame)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        log.info("%s 链路断开", tag)


async def bridge(relay_url, local_url):
    """连上中继(role=pc) + 本机 Clawli，双向转发；返回于任一端断开时。"""
    relay_full = relay_url + ("&" if "?" in relay_url else "?") + "role=pc"
    attempt = next(_seq)
    log.info("第 %d 次接入中继: %s", attempt, relay_full.split("?")[0])
    async with websockets.connect(relay_full, max_size=64 * 1024 * 1024,
                                  ping_interval=20, ping_timeout=20) as relay_ws:
        log.info("中继已连，接入本机 Clawli: %s", local_url)
        async with websockets.connect(local_url, max_size=64 * 1024 * 1024,
                                      ping_interval=20, ping_timeout=20) as local_ws:
            log.info("链路就绪（手机端填同一房间码即可）")
            done, pending = await asyncio.wait(
                [asyncio.create_task(pipe(relay_ws, local_ws, "中继→本机")),
                 asyncio.create_task(pipe(local_ws, relay_ws, "本机→中继"))],
                return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc:
                    log.warning("转发任务异常: %s", exc)


async def main(args):
    relay_url = args.relay.rstrip("/")
    if "room=" not in relay_url:
        relay_url += ("&" if "?" in relay_url else "?") + f"room={args.room}"
    if args.token:
        relay_url += f"&token={args.token}"
    while True:
        try:
            await bridge(relay_url, args.local)
        except Exception as e:
            log.warning("链路失败: %s", e)
        log.info("%.0f 秒后自动重连…", args.reconnect)
        await asyncio.sleep(args.reconnect)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Clawli 云中继 PC 端桥接")
    ap.add_argument("--relay", required=True, help="中继地址，如 ws://1.2.3.4:8900/ws")
    ap.add_argument("--room", required=True, help="房间码（手机端填一样的，>=4 字符）")
    ap.add_argument("--token", default="", help="中继令牌（服务端开了 --auth-token 时必填）")
    ap.add_argument("--local", default="ws://127.0.0.1:9079", help="本机 Clawli 地址")
    ap.add_argument("--reconnect", type=float, default=5.0, help="重连间隔秒")
    args = ap.parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        log.info("桥接退出")
