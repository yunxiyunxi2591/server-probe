# 无趣的探针 · Server Probe

[![Build and Push Docker Images](https://github.com/yunxiyunxi2591/server-probe/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/yunxiyunxi2591/server-probe/actions/workflows/docker-publish.yml)
![License](https://img.shields.io/badge/license-MIT-green">
![Python](https://img.shields.io/badge/python-3.8%2B-blue)

一个**零依赖**的轻量服务器监控探针：一台机器跑服务端出面板，其它机器跑采集端定时上报。只用 Python 3 标准库，没有 pip 依赖，没有数据库，重启即用。

- **服务端** `server.py`：接收上报 + 内置网页面板（单文件内嵌 HTML/CSS/JS）
- **采集端** `agent.py`：读取 `/proc` 采集指标，并行 ping 三网测延迟丢包，每 15 秒上报

## 面板效果

每台机器一张卡片，含 CPU / 内存 / 硬盘彩色进度条、负载、实时上下行速率、累计流量、在线时长、月租费用、三网延迟（电信/联通/移动）与丢包可视化，5 秒自动刷新，离线机器自动置灰。

```
┌──────────────────────────────────────────┐
│ ● Netcup G9.5 Pro                   🇺🇸   │
│ CPU  98.9% ████████████████████          │
│ 5.77, 5.91, 5.92                         │
│ 内存 56.2% ███████████                   │
│ 4.4 GB / 7.8 GB                          │
│ 硬盘 93.1% ██████████████████            │
│ 293.1 GB / 314.8 GB                      │
│ 速率    ^ 92.3 MB/s   v 16.3 MB/s        │
│ 在线    43 天 3 小时      费用 €3/月      │
│ 三网    171ms · 202ms · 173ms            │
│ 延迟 110 ms        丢包 4.2%             │
└──────────────────────────────────────────┘
```

## 功能

- **浅色 / 深色主题**：右上角按钮一键切换（快捷键 `T`），选择记在浏览器本地
- **系统图标**：agent 自动读取 `/etc/os-release`，面板在国旗后显示发行版徽标（悬停看完整名称与架构）
- CPU 使用率（`/proc/stat` 差值计算）、型号与核心数、1/5/15 分钟负载
- 内存使用率（`MemAvailable` 口径，比 `free` 更贴近真实可用）
- 硬盘使用率（可指定挂载点；`PROBE_DISK=all` 汇总所有真实挂载点，容器里通过只读挂载统计宿主机磁盘）
- 实时上下行速率 + 累计流量（`/proc/net/dev`，排除 lo）
- 在线时长（`/proc/uptime`）
- 三网延迟与丢包（默认目标：上海电信 / 江苏联通 / 北京移动，每网可配多个备用 IP，测不通自动换下一个）
- 离线判定（默认 45 秒无上报即置灰）
- 上报接口带 Token 鉴权，错误 Token 返回 403

## 快速开始

### 方式一：Docker（推荐）

```bash
git clone https://github.com/yunxiyunxi2591/server-probe.git
cd server-probe

# 改 docker-compose.yml 里两处 PROBE_TOKEN 为同一个随机串
docker compose up -d --build
```

浏览器打开 `http://服务器IP:25777/`。

NAS 等只需要采集端的机器：

```bash
docker compose -f docker-compose.nas.yml up -d
```

已经有构建好的镜像时，可以直接用 `docker-compose.hub.yml`（不用本地构建）。

> ⚠️ agent 容器**必须使用 `--network host`**，否则读到的是容器虚拟网卡，速率会一直是 0；
> 统计宿主机磁盘需要 `-v /:/host:ro` 并设 `PROBE_DISK=/host`（填 `all` 则汇总所有挂载点，NAS 多盘推荐）。

### 方式二：裸机直接跑

```bash
# 服务端（VPS）
python3 server.py            # 默认 25777 端口

# 采集端（VPS / NAS 各一个）
python3 agent.py
```

细节与 systemd 配置见 [README-部署说明.md](README-部署说明.md)，Docker 排错见 [README-Docker说明.md](README-Docker说明.md)。

## 配置（全部支持环境变量，无需改代码）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PROBE_TOKEN` | `change-me-2026` | 上报鉴权，服务端/agent 必须一致，**务必修改** |
| `PROBE_PORT` | `25777` | 服务端监听端口 |
| `PROBE_TITLE` | `无趣的探针` | 面板标题 |
| `PROBE_OFFLINE_AFTER` | `45` | 超过多少秒没上报判定离线 |
| `PROBE_SERVER` | `http://127.0.0.1:25777` | agent 上报地址 |
| `PROBE_NAME` | 主机名 | 面板显示名 |
| `PROBE_FLAG` | `🇺🇸` | 国旗 emoji |
| `PROBE_PRICE` | `-` | 月租显示，如 `€7.4/月` |
| `PROBE_DISK` | `/` | 统计哪个挂载点；容器里填 `/host`；填 **`all`** 汇总所有挂载点（NAS 多盘推荐） |
| `PROBE_INTERVAL` | `15` | 上报间隔秒数 |
| `PROBE_CARRIERS` | 电信/联通/移动 | 每个运营商可配多个 IP（`|` 分隔，不通自动切换）：`电信:1.1.1.1|2.2.2.2,联通:3.3.3.3` |
| `PROBE_PING_MODE` | `icmp` | 设 `tcp` 则用 TCP 握手近似延迟（无需 ping 命令） |

## Docker Hub 镜像

推 tag 后由 GitHub Actions 自动构建并发布（amd64 + arm64）：

```bash
docker pull chensen2591/probe-server:latest
docker pull chensen2591/probe-agent:latest
```

需要在仓库 `Settings → Secrets and variables → Actions` 里配置：

- `DOCKERHUB_USERNAME`：Docker Hub 用户名
- `DOCKERHUB_TOKEN`：Docker Hub 的 Access Token（不是登录密码）

## API

| 接口 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 监控面板 |
| `/api/data` | GET | 所有节点最新数据（JSON） |
| `/api/report` | POST | 上报接口，需 Header `X-Token` |

## 安全建议

面板本身为只读无认证页面，建议：使用足够随机的 `PROBE_TOKEN`；不要把端口直接暴露在公网而毫无防护，可套 Nginx 反代加 Basic Auth，或只监听内网 + 反代。

## 更新日志

### v1.1.2
- **CPU 显示型号与核心数**：面板 CPU 那格下面显示 `Intel N100 · 4 核 · 负载 0.x/0.x/0.x`（旧版仅显示负载数字）
- **硬盘支持汇总所有挂载点**：`PROBE_DISK=all` 时统计全部真实挂载点（自动跳过 tmpfs/proc/docker 叠加层，同一设备只计一次），NAS 多数据盘场景不再只显示根分区

### v1.1.1
- 修复 **fnOS（飞牛）被识别成 Debian**：优先探测 `/usr/trim`、`/etc/fnos-release`，面板现在显示 `fnOS` 徽标
- 三网测速：每个运营商的多个候选 IP **并行测试并自动选丢包最低**的目标（相同则选延迟最低）
- 移动基准 IP 更新为实测更优目标（江苏 / 浙江 / 北京移动）

### v1.1.0
- 界面重做：点线引导行（`速率 ┈┈┈ ↑ ↓`）、细渐变进度条、延迟/丢包分段色条、整体更紧凑
- 新增**浅色 / 深色主题切换**（右上角按钮，快捷键 `T`，记忆选择）
- 新增**系统图标**：agent 自动上报发行版与架构，面板在国旗后显示徽标
- 三网测速基准 IP 改为实测可用目标，且每个运营商支持多个备用 IP 自动切换
- 修复浏览器断开长连接时服务端日志刷屏的问题

### v1.0.0
- 首个版本：CPU / 内存 / 硬盘 / 速率 / 流量 / 在线时长 / 费用 / 三网延迟丢包

## License

MIT
