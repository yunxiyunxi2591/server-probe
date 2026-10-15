# Docker 部署说明（最简单方式）

前置：机器上已装 Docker。VPS 建议用官方脚本装：`curl -fsSL https://get.docker.com | sh`

## 先说明：`probe-server` / `probe-agent` 是什么

这两个是**我给自建镜像起的本地名字**，Docker Hub 上并不存在，永远不会从网上拉别人做好的东西。它们由 `Dockerfile` / `Dockerfile.agent` 用本目录的 `server.py` / `agent.py` **现场构建**出来（就是前面给你写的那些代码）。

唯一联网下载的是**基础镜像 `python:3.12-slim`**（Python 官方），以及 agent 镜像里通过 apt 装的 `iputils-ping`。整个探针的业务代码 100% 是本地的这两个 py 文件。

自己验证一下：

```bash
docker compose up -d --build     # 构建
docker images | grep probe       # 能看到 probe-server / probe-agent 两个本地镜像, 不是 pull 来的
docker run --rm probe-agent true # 若没构建过, 会报 Unable to find image ... locally（证明它不是网上的镜像）
```

如果你想让名字更"私有"一点，把 `image:` 改成 `myprobe-server:1.0` 之类任意名字都行，只要 build 段不变就不影响使用。

## 方式一：docker compose（推荐，VPS 用）

VPS 上建个目录，把这几个文件放进去：

```
probe/
├── server.py
├── agent.py
├── Dockerfile           # 服务端镜像
├── Dockerfile.agent     # 采集端镜像
└── docker-compose.yml
```

改 `docker-compose.yml` 里两处 `PROBE_TOKEN`（改成同一个随机串），agent 段里的 `PROBE_NAME` / `PROBE_FLAG` / `PROBE_PRICE` 按需改，然后：

```bash
docker compose up -d --build
docker compose logs -f probe-agent     # 看上报是否正常
```

浏览器打开 `http://VPS的IP:25777/` 就是面板。记得放行 25777 端口（云服务商安全组也要放）。

## 方式二：NAS 上只跑采集端

NAS 一般不需要开面板，只要 agent。把 `agent.py` + `Dockerfile.agent` + `docker-compose.nas.yml` 拷过去：

```bash
# 1) 构建镜像（NAS 上直接构建）
docker build -t probe-agent -f Dockerfile.agent .

# 2) 改 docker-compose.nas.yml 里的 PROBE_SERVER 和 PROBE_TOKEN，然后启动
docker compose -f docker-compose.nas.yml up -d
```

NAS 不方便构建的话，从 VPS 把镜像搬过去：

```bash
# VPS 上导出
docker save probe-agent:latest | gzip > probe-agent.tgz
# 传到 NAS 后导入
gunzip -c probe-agent.tgz | docker load
```

## 方式三：不想写 compose，直接 docker run

先构建镜像（VPS 和 NAS 上都可执行，一次即可）：

```bash
docker build -t probe-server -f Dockerfile .
docker build -t probe-agent  -f Dockerfile.agent .
```

```bash
# 服务端（VPS）
docker run -d --name probe-server --restart unless-stopped \
  -p 25777:25777 \
  -e PROBE_TOKEN=你的随机串 \
  -v /opt/probe/server.py:/app/server.py:ro \
  probe-server:latest

# 采集端（VPS 或 NAS 都行）
docker run -d --name probe-agent --restart unless-stopped \
  --network host -v /:/host:ro \
  -e PROBE_SERVER=http://VPS公网IP:25777 \
  -e PROBE_TOKEN=你的随机串 \
  -e PROBE_NAME=fnOS NAS -e PROBE_FLAG=🇨🇳 -e PROBE_PRICE=- \
  -e PROBE_DISK=/host \
  probe-agent:latest
```

## 环境变量一览（不必再改代码）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PROBE_TOKEN` | `change-me-2026` | 上报鉴权，服务端/agent 必须一致 |
| `PROBE_PORT` | `25777` | 服务端监听端口 |
| `PROBE_TITLE` | `无趣的探针` | 面板标题 |
| `PROBE_OFFLINE_AFTER` | `45` | 超过多少秒没上报判定离线 |
| `PROBE_SERVER` | `http://127.0.0.1:25777` | agent 上报地址 |
| `PROBE_NAME` | 主机名 | 面板显示名 |
| `PROBE_FLAG` | `🇺🇸` | 国旗 |
| `PROBE_PRICE` | `-` | 月租显示，如 `€7.4/月` |
| `PROBE_DISK` | `/` | 统计哪个挂载点，容器里填 `/host` |
| `PROBE_INTERVAL` | `15` | 上报间隔秒数 |
| `PROBE_CARRIERS` | 电信/联通/移动 | 自定义：`电信:1.1.1.1,联通:2.2.2.2` |
| `PROBE_PING_MODE` | `icmp` | 设 `tcp` 则用 TCP 握手近似延迟（无需 ping 命令） |

## 为什么 agent 一定要用 host 网络

容器有独立网络命名空间，默认模式下 `/proc/net/dev` 读到的是容器 veth 网卡的流量（只有几十字节），面板上的速率会一直是 0。用 `network_mode: host` 后读到的才是宿主机真实网卡。硬盘同理，靠 `-v /:/host:ro` 只读挂载 + `PROBE_DISK=/host` 才能统计到宿主机磁盘。

## 常见问题

- **面板显示离线**：`docker logs probe-agent` 看是否连不上；确认服务端端口已放行、`PROBE_SERVER` 地址和 token 正确。
- **网速一直是 0**：没加 `--network host`。
- **硬盘是容器的小容量**：没挂 `-v /:/host:ro` 或没设 `PROBE_DISK=/host`。
- **三网延迟全是 100% 丢包**：镜像里没装 ping（用官方 `python:3.12-slim` 裸跑时会发生），设 `PROBE_PING_MODE=tcp`，或改用本目录的 `Dockerfile.agent`（已装 iputils-ping）。
- **NAS 想只统计数据盘**：把挂载改成 `-v /vol1:/host:ro`。
- **更新代码**：`docker compose up -d --build` 重建即可，数据在内存里，重启后 agent 会自动重新上报。
- 在 Windows 的 Git Bash 里敲命令时，`/host` 这类值可能被自动改写成 `C:/...`，加 `MSYS_NO_PATHCONV=1` 前缀或在容器/Linux 上执行即可。
