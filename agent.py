#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无趣的探针 - agent 采集端（Linux，零依赖，仅 Python 标准库）
适用: 美国 VPS / fnOS NAS 等任何 Debian 系机器
用法: python3 agent.py  (建议配 systemd 常驻)
"""
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request

# ============ 配置区（支持环境变量覆盖，Docker 部署无需改文件） ============
def _env(k, default):
    v = os.environ.get(k)
    return v if v not in (None, "") else default

SERVER = _env("PROBE_SERVER", "http://127.0.0.1:25777")  # 如 http://1.2.3.4:25777
TOKEN = _env("PROBE_TOKEN", "change-me-2026")            # 与 server.py 一致
NAME = _env("PROBE_NAME", socket.gethostname())          # 面板显示名
FLAG = _env("PROBE_FLAG", "🇺🇸")                          # 国旗 emoji: 🇺🇸 / 🇨🇳
LOCATION = _env("PROBE_LOCATION", "")                    # 位置描述(面板暂只显示国旗)
PRICE = _env("PROBE_PRICE", "-")                         # 月租, 如 "€7.4/月"
DISK_PATH = _env("PROBE_DISK", "/")                      # 挂载点; Docker 里用 /host
INTERVAL = int(_env("PROBE_INTERVAL", 15))               # 上报间隔(秒)
PING_MODE = _env("PROBE_PING_MODE", "icmp")              # icmp(默认, 自动降级) / tcp

# 三网 ping 目标, 可用 PROBE_CARRIERS="电信:1.2.3.4,联通:5.6.7.8" 覆盖
_DEFAULT_CARRIERS = [
    ("电信", "202.96.209.133"),      # 上海电信
    ("联通", "202.106.0.20"),        # 北京联通
    ("移动", "120.196.165.244"),     # 广东移动
]
CARRIERS = [tuple(x.split(":", 1)) for x in _env(
    "PROBE_CARRIERS", "").split(",") if ":" in x] or _DEFAULT_CARRIERS
# =========================================================================


def read_cpu():
    with open("/proc/stat") as f:
        parts = [int(x) for x in f.readline().split()[1:]]
    return sum(parts), parts[3] + parts[4]  # (total, idle)


def cpu_percent(prev):
    total, idle = read_cpu()
    dt, di = total - prev[0], idle - prev[1]
    pct = 100.0 * (dt - di) / dt if dt > 0 else 0.0
    return max(0.0, min(100.0, pct)), (total, idle)


def mem_info():
    d = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            d[k] = int(v.split()[0]) * 1024
    used = d["MemTotal"] - d["MemAvailable"]
    return used, d["MemTotal"]


def load_avg():
    with open("/proc/loadavg") as f:
        parts = f.read().split()
    return [round(float(x), 2) for x in parts[:3]]


def net_counters():
    """所有非 lo 网卡的累计收发字节数"""
    rx = tx = 0
    with open("/proc/net/dev") as f:
        for line in f.readlines()[2:]:
            if ":" not in line:
                continue
            iface, dat = line.split(":", 1)
            if iface.strip() == "lo":
                continue
            fl = dat.split()
            rx += int(fl[0])
            tx += int(fl[8])
    return rx, tx


def disk_usage(path):
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return total - free, total


def tcp_ping(name, ip, port=80, count=4, timeout=2.0):
    """ping 不可用时的兜底：TCP 握手耗时(近似延迟)"""
    ok, times = 0, []
    for _ in range(count):
        t0 = time.time()
        try:
            s = socket.create_connection((ip, port), timeout=timeout)
            s.close()
            times.append((time.time() - t0) * 1000)
            ok += 1
        except Exception:
            pass
    avg = round(sum(times) / len(times), 1) if times else 0.0
    return {"name": name, "avg": avg, "loss": round(100.0 * (count - ok) / count, 1)}


def ping_one(name, ip):
    """单运营商 ping: 4 包, 返回 {name, avg, loss}"""
    if PING_MODE == "tcp":
        return tcp_ping(name, ip)
    try:
        r = subprocess.run(["ping", "-c", "4", "-W", "2", ip],
                           capture_output=True, text=True, timeout=20)
        out = r.stdout
        m = re.search(r"([\d.]+)/([\d.]+)/", out)          # rtt min/avg
        lm = re.search(r"(\d+)% packet loss", out)
        avg = float(m.group(2)) if m else 0.0
        loss = float(lm.group(1)) if lm else 100.0
        if loss >= 100 and m is None:
            avg = 0.0
        return {"name": name, "avg": avg, "loss": loss}
    except FileNotFoundError:
        return tcp_ping(name, ip)     # 容器里没装 ping，自动降级
    except Exception:
        return {"name": name, "avg": 0.0, "loss": 100.0}


def ping_all():
    """三网并行 ping"""
    results, ths = {}, []
    for name, ip in CARRIERS:
        t = threading.Thread(target=lambda n=name, i=ip: results.__setitem__(
            n, ping_one(n, i)), daemon=True)
        t.start()
        ths.append(t)
    for t in ths:
        t.join()
    return [results[n] for n, _ in CARRIERS if n in results]


def report(payload):
    req = urllib.request.Request(
        SERVER.rstrip("/") + "/api/report",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Token": TOKEN},
        method="POST")
    urllib.request.urlopen(req, timeout=10)


def main():
    if os.name != "nt" and not os.path.exists("/proc/stat"):
        raise SystemExit("仅支持 Linux (/proc)")
    prev_cpu = read_cpu()
    prev_rx, prev_tx = net_counters()
    prev_t = time.time()
    print("[agent] 上报目标 %s, 间隔 %ds, 名称 %s" % (SERVER, INTERVAL, NAME))
    while True:
        time.sleep(INTERVAL)
        try:
            cpu, prev_cpu = cpu_percent(prev_cpu)
            rx, tx = net_counters()
            now = time.time()
            dt = max(now - prev_t, 0.1)
            mem_used, mem_total = mem_info()
            disk_used, disk_total = disk_usage(DISK_PATH)
            with open("/proc/uptime") as f:
                uptime = float(f.read().split()[0])
            payload = {
                "name": NAME, "flag": FLAG, "location": LOCATION, "price": PRICE,
                "cpu": round(cpu, 1), "load": load_avg(),
                "mem_used": mem_used, "mem_total": mem_total,
                "disk_used": disk_used, "disk_total": disk_total,
                "rx_rate": max(0, (rx - prev_rx) / dt),
                "tx_rate": max(0, (tx - prev_tx) / dt),
                "rx_total": rx, "tx_total": tx,
                "uptime": uptime, "net": ping_all(),
            }
            prev_rx, prev_tx, prev_t = rx, tx, now
            report(payload)
            print("[%s] 已上报 CPU %.1f%% ping %s" % (
                time.strftime("%H:%M:%S"), cpu,
                " ".join("%s:%.0fms/%.0f%%" % (x["name"], x["avg"], x["loss"])
                         for x in payload["net"])))
        except Exception as e:
            print("[agent] 出错(下轮重试): %r" % e)


if __name__ == "__main__":
    main()
