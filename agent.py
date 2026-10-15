#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无趣的探针 - agent 采集端（Linux，零依赖，仅 Python 标准库）
适用: 美国 VPS / fnOS NAS 等任何 Debian 系机器
用法: python3 agent.py  (建议配 systemd 常驻)
"""
import json
import os
import platform
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
DISK_PATH = _env("PROBE_DISK", "/")                      # 挂载点; Docker 里用 /host, 或 "all" 汇总所有挂载点
INTERVAL = int(_env("PROBE_INTERVAL", 15))               # 上报间隔(秒)
PING_MODE = _env("PROBE_PING_MODE", "icmp")              # icmp(默认, 自动降级) / tcp

# 三网 ping 目标: 每个运营商可配多个候选 IP, agent 并行测完自动选丢包最低的那个
# 也可用环境变量 PROBE_CARRIERS="电信:1.2.3.4|5.6.7.8,联通:3.3.3.3" 覆盖
# 注: 2026-10 实测——老基准(北京联通 202.106.0.20 / 广东移动 120.196.165.244)已不回 ICMP;
#     移动各基准 IP 从电信线路测普遍有 20%~50% 丢包(跨网真实丢包, 非 bug)
_DEFAULT_CARRIERS = [
    ("电信", ["202.96.209.133", "61.139.2.69"]),              # 上海电信 / 四川电信
    ("联通", ["221.228.255.1", "202.106.0.20"]),              # 江苏联通 / 北京联通
    ("移动", ["112.4.0.55", "211.138.180.2", "211.136.192.6"]),  # 江苏移动 / 浙江移动 / 北京移动
]
CARRIERS = []
for _part in _env("PROBE_CARRIERS", "").split(","):
    if ":" in _part:
        _n, _ips = _part.split(":", 1)
        _lst = [x for x in _ips.split("|") if x]
        if _n and _lst:
            CARRIERS.append((_n, _lst))
if not CARRIERS:
    CARRIERS = _DEFAULT_CARRIERS
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


REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs", "zfs", "jfs", "reiserfs",
           "vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "hfsplus", "apfs", "udf", "bcachefs"}


def disk_usage(path):
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return total - free, total, 1


def disk_usage_all():
    """汇总所有真实挂载点的容量（同一设备只计一次），返回 (used, total, mounts)

    PROBE_DISK="all" 时使用。容器里若挂了 -v /:/host:ro，会自动读宿主机的挂载表，
    因此统计到的是 NAS 上全部数据盘，而不是容器自己的叠加层。
    """
    prefix, mf = "", "/proc/mounts"
    if os.path.exists("/host/proc/mounts"):
        prefix, mf = "/host", "/host/proc/mounts"
    used = total = mounts = 0
    seen = set()
    try:
        with open(mf) as f:
            lines = f.readlines()
    except Exception:
        return disk_usage("/")
    for line in lines:
        p = line.split()
        if len(p) < 3:
            continue
        dev, mnt, fst = p[0], p[1], p[2]
        if fst not in REAL_FS or dev.startswith("/dev/loop"):
            continue
        key = dev if dev.startswith("/dev/") else "%s:%s" % (fst, mnt)
        if key in seen:
            continue
        seen.add(key)
        try:
            st = os.statvfs(prefix + mnt)
        except Exception:
            continue
        t = st.f_blocks * st.f_frsize
        if t <= 0:
            continue
        used += t - st.f_bavail * st.f_frsize
        total += t
        mounts += 1
    if total <= 0:                      # 没扫到，兜底用根分区
        return disk_usage("/")
    return used, total, mounts


def cpu_info():
    """CPU 型号 + 逻辑核心数"""
    model = ""
    try:
        with open("/proc/cpuinfo") as f:
            txt = f.read()
        m = (re.search(r"^model name\s*:\s*(.+)$", txt, re.M)
             or re.search(r"^(?:Hardware|Model|cpu model)\s*:\s*(.+)$", txt, re.M))
        if m:
            model = m.group(1).strip()
    except Exception:
        pass
    if not model:
        try:
            model = platform.processor() or ""
        except Exception:
            model = ""
    try:
        cores = os.cpu_count() or 0
    except Exception:
        cores = 0
    return model[:80], cores


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


def ping_carrier(name, ips):
    """并行测试该运营商所有候选 IP, 返回丢包最低(相同则延迟最低)的结果"""
    results, ths = {}, []
    for ip in ips:
        t = threading.Thread(
            target=lambda i=ip: results.__setitem__(i, ping_one(name, i)),
            daemon=True)
        t.start()
        ths.append(t)
    for t in ths:
        t.join()
    if not results:
        return {"name": name, "avg": 0.0, "loss": 100.0}
    best = min(results.values(), key=lambda r: (r["loss"], r["avg"]))
    return best


def ping_all():
    """三网并行 ping"""
    results, ths = {}, []
    for name, ips in CARRIERS:
        t = threading.Thread(
            target=lambda n=name, i=ips: results.__setitem__(n, ping_carrier(n, i)),
            daemon=True)
        t.start()
        ths.append(t)
    for t in ths:
        t.join()
    return [results[n] for n, _ in CARRIERS if n in results]


def _read_kv_file(path):
    d = {}
    try:
        with open(path) as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    d[k] = v.strip().strip('"')
    except Exception:
        pass
    return d


def os_info():
    """采集系统标识: 发行版 id / 完整名称 / 版本 / 架构 (用于面板显示系统图标)

    fnOS(飞牛)的 /etc/os-release 就是 Debian 原样, 这里优先探测 fnOS 特征:
    /usr/trim 目录(fnOS 核心组件) 或 /etc/fnos-release
    """
    d = _read_kv_file("/etc/os-release")
    arch = ""
    try:
        arch = platform.machine()
    except Exception:
        pass
    # --- fnOS 识别 ---
    if os.path.isdir("/usr/trim") or os.path.exists("/etc/fnos-release"):
        ver = ""
        for vf in ("/etc/fnos-release", "/usr/trim/etc/version"):
            try:
                with open(vf) as f:
                    ver = f.read().strip().strip('"')
                if ver:
                    break
            except Exception:
                pass
        if not ver:
            ver = d.get("VERSION_ID", "")
        name = "fnOS " + ver if ver else "fnOS"
        return {"id": "fnos", "name": name, "ver": ver, "arch": arch}
    oid = (d.get("ID") or ("windows" if os.name == "nt" else "linux")).lower()
    pretty = d.get("PRETTY_NAME") or d.get("NAME") or oid
    return {"id": oid, "name": pretty, "ver": d.get("VERSION_ID", ""), "arch": arch}


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
            if DISK_PATH == "all":
                disk_used, disk_total, disk_mounts = disk_usage_all()
            else:
                disk_used, disk_total, disk_mounts = disk_usage(DISK_PATH)
            with open("/proc/uptime") as f:
                uptime = float(f.read().split()[0])
            model, cores = cpu_info()
            payload = {
                "name": NAME, "flag": FLAG, "location": LOCATION, "price": PRICE,
                "cpu": round(cpu, 1), "load": load_avg(),
                "cpu_model": model, "cpu_cores": cores,
                "mem_used": mem_used, "mem_total": mem_total,
                "disk_used": disk_used, "disk_total": disk_total,
                "disk_mounts": disk_mounts,
                "rx_rate": max(0, (rx - prev_rx) / dt),
                "tx_rate": max(0, (tx - prev_tx) / dt),
                "rx_total": rx, "tx_total": tx,
                "uptime": uptime, "net": ping_all(), "os": os_info(),
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
