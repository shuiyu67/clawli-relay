# Clawli 云中继（clawli-relay）

把「手机 ↔ 电脑上的 Lix CLI（Clawli）」的 WebSocket 流量经自建服务器**原样转发**，穿透 NAT——外网也能用。

```
局域网模式:  手机 ──────────────ws──────────────▶ 电脑 Clawli (127.0.0.1:9079)
云模式:      手机 ──ws──▶ 云中继(本仓库) ◀─ws── relay_client.py(电脑) ──▶ 本机 Clawli
```

- **透明转发**：Clawli 自己的密码鉴权帧原样穿过中继，中继不解析、不存储任何聊天内容
- **房间码隔离**：每个 `room` 只配对一对端（一个 PC + 一个手机），同角色重连自动顶掉旧连接
- **大帧支持**：`max_size=64MB`，base64 图片/文件上传不成问题

## 组成

| 文件 | 跑在哪 | 作用 |
|---|---|---|
| `relay_server.py` | 你的公网服务器 | WebSocket 中继（唯一需要部署的东西） |
| `relay_client.py` | 你的电脑 | 把本机 Clawli(9079) 桥接到中继 |
| `deploy/clawli-relay.service` | 服务器 | systemd 服务模板 |
| `Dockerfile` / `docker-compose.yml` | 服务器 | Docker 部署（二选一） |

## 部署（服务器，二选一）

### A. Docker（推荐）

```bash
git clone <本仓库> && cd clawli-relay
CLAWLI_RELAY_TOKEN='换一串强随机值' docker compose up -d --build
```

### B. 裸机 + systemd

```bash
sudo mkdir -p /opt/clawli-relay && sudo cp relay_server.py requirements.txt /opt/clawli-relay/
pip3 install -r requirements.txt
sudo cp deploy/clawli-relay.service /etc/systemd/system/
sudo sed -i 's/CHANGE-ME/换一串强随机值/' /etc/systemd/system/clawli-relay.service
sudo systemctl daemon-reload && sudo systemctl enable --now clawli-relay
```

放行防火墙端口（默认 `8900/tcp`）。

## 使用

1. **电脑端**（Clawli 保持运行，`/clawli` 启动 9079 服务后）：

   ```bash
   python relay_client.py --relay ws://<服务器IP>:8900/ws --room myroom123 --token <令牌>
   ```

2. **手机端（Clawli 安卓 App）**：连接模式选「云模式」，填：
   - 中继地址：`ws://<服务器IP>:8900/ws`
   - 房间码：`myroom123`（与 PC 端一致）
   - 令牌：`<令牌>`（服务端没开 `--auth-token` 可留空）
   - Clawli 密码：PC 上设置的那个（这一层是 Clawli 协议自己的鉴权，照常生效）

局域网内直接用「局域网模式」（`IP:9079` + 密码），不用部署中继。

## 安全注意

- 公网部署**务必**开 `--auth-token`，否则任何知道端口的人都能尝试连入房间
- 房间码当密码用：自选长随机串，别用 `1234`
- 中继全程不落盘；但 WebSocket 本身是明文 `ws://`，介意的话在服务器前面套一层 nginx + TLS（`wss://`，客户端地址相应改成 `wss://`）
- Clawli 层的密码鉴权独立于中继令牌，两层都开着才最稳

## 协议（给二次开发）

连接 `ws://host:port/ws?room=<房间码>&role=<pc|phone>[&token=<令牌>]`：

- 之后双向收发的**所有文本/二进制帧原样转发**给房间对端
- 中继只额外发一种控制帧（对端上下线通知，可忽略）：
  `{"type":"relay","event":"peer_joined"|"peer_left","role":"pc"|"phone","ts":...}`
- 关闭码：`4001` 房间码缺失/过短，`4002` role 非法，`4003` 令牌错误，`4000` 被新连接顶替
