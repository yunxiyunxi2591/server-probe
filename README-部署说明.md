# 无趣的探针 · 自建轻量服务器探针

零依赖（纯 Python 3 标准库），两个文件搞定：

| 文件 | 部署位置 | 作用 |
|---|---|---|
| `server.py` | 美国 VPS | 接收上报 + 网页面板 |
| `agent.py`  | 美国 VPS + 本地 NAS 各跑一个 | 采集 CPU/内存/硬盘/网速/负载/在线时长，并行 ping 三网测延迟丢包 |

面板功能：CPU / 内存 / 硬盘彩色进度条、实时上下行速率、累计流量、在线时长、月租费用、三网延迟（电信/联通/移动）、平均延迟与丢包可视化，每 5 秒自动刷新，离线机器置灰。

---

## 第 1 步：改 Token（必做）

两个文件顶部的 `TOKEN` 改成同一个随机字符串，例如：

```
TOKEN = "g8Xk2pQ9wR4tY7uB"
```

## 第 2 步：VPS 上启动服务端

```bash
# 上传 server.py 到 VPS，比如 /opt/probe/
python3 server.py            # 默认监听 25777 端口
# 或指定端口: python3 server.py 8080
```

放行防火墙端口（按你的实际防火墙）：

```bash
# ufw:   sudo ufw allow 25777/tcp
# 阿里云/腾讯云等还要去控制台安全组放行
```

浏览器访问 `http://VPS的IP:25777/` 即可看到面板。

### systemd 常驻（服务端）

```ini
# /etc/systemd/system/probe-server.service
[Unit]
Description=Probe Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/probe/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now probe-server
```

## 第 3 步：VPS 和 NAS 上启动 agent

修改 `agent.py` 顶部配置：

```python
SERVER = "http://你的VPS公网IP:25777"
TOKEN = "和服务端一致"
NAME = "Netcup VPS"          # 面板显示名
FLAG = "🇺🇸"                  # NAS 用 🇨🇳
PRICE = "€7.4/月"             # NAS 可写 "-"
DISK_PATH = "/"               # fnOS NAS 建议改成数据盘如 "/vol1"
```

先手动跑一次看输出：`python3 agent.py`，正常会每 15 秒打印上报结果。三网延迟用的是公共基准 IP（上海电信 / 北京联通 / 广东移动），想换成你家宽运营商的 DNS/网关 IP 直接改 `CARRIERS` 列表即可。

### systemd 常驻（agent）

```ini
# /etc/systemd/system/probe-agent.service
[Unit]
Description=Probe Agent
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/probe/agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### fnOS NAS 说明

- fnOS 是 Debian 底层，自带 `python3`，SSH 进去直接跑即可；
- 如果想把 agent.py 放到 `/vol1` 下的某个目录再挂 systemd，注意系统升级可能清掉非应用目录，可改用 `nohup python3 agent.py &` 或放进 Docker。

## 安全建议

- 面板本身只读无密码，建议不要用弱 token，且可在前面套 Nginx 反代加 Basic Auth 或只绑 localhost + 反代；
- 上报接口有 token 校验，错误 token 返回 403；
- NAS 在内网无需开任何入站端口（agent 是出站上报）。

## 已验证

- ✅ 上报/拉取 API 正常，错误 token 被 403 拒绝
- ✅ 面板渲染正常（本机 127.0.0.1:25777 用模拟数据测试通过）
