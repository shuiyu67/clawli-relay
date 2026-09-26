"""clawli-relay 端到端冒烟（逐步打点）"""
import asyncio
import json
import subprocess
import sys

import websockets

PY = sys.executable
KW = dict(max_size=64 * 1024 * 1024)


async def main(port):
    srv = subprocess.Popen([PY, "relay_server.py", "--port", str(port), "--auth-token", "T0K"],
                           stdout=open(f"relay_smoke_{port}.log", "w"), stderr=subprocess.STDOUT)
    await asyncio.sleep(1.2)
    try:
        base = f"ws://127.0.0.1:{port}/ws?room=room-abc&token=T0K"
        pc = await websockets.connect(base + "&role=pc", **KW)
        ph = await websockets.connect(base + "&role=phone", **KW)
        print("step: 双端已连接", flush=True)

        n1 = json.loads(await asyncio.wait_for(pc.recv(), 5))
        assert n1["event"] == "peer_joined", n1
        print("step: peer_joined OK", flush=True)

        await ph.send(json.dumps({"type": "auth", "password": "pw"}))
        got = json.loads(await asyncio.wait_for(pc.recv(), 5))
        assert got == {"type": "auth", "password": "pw"}, got
        print("step: 手机→PC 透明转发 OK", flush=True)

        await pc.send(json.dumps({"type": "text", "content": "你好"}))
        got2 = json.loads(await asyncio.wait_for(ph.recv(), 5))
        assert got2["content"] == "你好", got2
        print("step: PC→手机 透明转发 OK", flush=True)

        big = "A" * (1024 * 1024)
        await ph.send(json.dumps({"type": "file", "file": big, "filename": "a.bin"}))
        got3 = json.loads(await asyncio.wait_for(pc.recv(), 15))
        assert got3["file"] == big, "大帧被截断"
        print("step: 1MB 大帧 OK", flush=True)

        bad_url = f"ws://127.0.0.1:{port}/ws?room=room-abc&role=pc&token=BAD"
        bad = await websockets.connect(bad_url, **KW)
        try:
            await asyncio.wait_for(bad.recv(), 4)
            raise AssertionError("错误令牌没被拒")
        except websockets.exceptions.ConnectionClosed as e:
            assert e.rcvd and e.rcvd.code == 4003, e
        print("step: 错误令牌拒绝 OK", flush=True)

        await pc.close()
        await ph.close()

        pc1 = await websockets.connect(base + "&role=pc", **KW)
        await asyncio.sleep(0.2)
        pc2 = await websockets.connect(base + "&role=pc", **KW)
        try:
            await asyncio.wait_for(pc1.recv(), 4)
            raise AssertionError("顶替没生效")
        except websockets.exceptions.ConnectionClosed as e:
            assert e.rcvd and e.rcvd.code == 4000, e
        await pc2.close()
        print("step: 同角色顶替 OK", flush=True)

        print("中继冒烟全过: 转发/鉴权/顶替/1MB 大帧", flush=True)
    finally:
        srv.terminate()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(int(sys.argv[1])), 60))
