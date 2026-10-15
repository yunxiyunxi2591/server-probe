#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无趣的探针 - 轻量自建探针服务端（零依赖，仅 Python 标准库）
用法: python3 server.py [端口]
面板: http://0.0.0.0:25777/
API : GET /api/data   (面板拉取)
      POST /api/report (agent 上报, Header: X-Token)
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ============ 配置区（支持环境变量覆盖，Docker 部署无需改文件） ============
TOKEN = os.environ.get("PROBE_TOKEN", "change-me-2026")   # 与 agent 一致，务必修改！
PORT = int(os.environ.get("PROBE_PORT") or (sys.argv[1] if len(sys.argv) > 1 else 25777))
TITLE = os.environ.get("PROBE_TITLE", "无趣的探针")
OFFLINE_AFTER = int(os.environ.get("PROBE_OFFLINE_AFTER", 45))  # 超时判定离线(秒)
# ========================================================================

nodes = {}          # name -> {"data": {...}, "last_seen": ts}
lock = threading.Lock()

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --bg1:#e6f4ea;--bg2:#f4faf4;--bg3:#edf3ed;--card:#fff;
  --ink:#1f2937;--sub:#4b5563;--faint:#9ca3af;--sep:#c9cfc9;
  --track:#edf0ed;--green:#22c55e;--lime:#a3e635;--amber:#f59e0b;
  --red:#ef4444;--pink:#ec4899;--blue:#3b82f6;
  --glass:rgba(255,255,255,.72);--glass-b:rgba(255,255,255,.9);
  --shadow:0 4px 18px rgba(23,58,40,.07);--card-b:rgba(255,255,255,.65);
}
html[data-theme="dark"]{
  --bg1:#0e1712;--bg2:#0b120e;--bg3:#0a0f0c;--card:#151f19;
  --ink:#e6efe8;--sub:#a4b8ab;--faint:#71857a;--sep:#3d4b42;
  --track:#25312a;--green:#34d399;--lime:#bef264;--amber:#fbbf24;
  --red:#f87171;--pink:#f472b6;--blue:#60a5fa;
  --glass:rgba(255,255,255,.07);--glass-b:rgba(255,255,255,.09);
  --shadow:0 4px 18px rgba(0,0,0,.42);--card-b:rgba(255,255,255,.05);
}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{min-height:100vh;
  background:linear-gradient(168deg,var(--bg1) 0%,var(--bg2) 46%,var(--bg3) 100%);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI","Microsoft YaHei",sans-serif;
  color:var(--ink);padding:12px 10px 38px;transition:background .35s,color .35s}
.wrap{max-width:780px;margin:0 auto}
/* ---------- 顶栏 ---------- */
.top{display:flex;align-items:center;gap:8px;padding:0 4px 10px}
.sp{flex:1}
.theme{width:34px;height:34px;border-radius:11px;flex:none;padding:0;cursor:pointer;
  border:1px solid var(--glass-b);background:var(--glass);box-shadow:var(--shadow);
  color:var(--sub);display:flex;align-items:center;justify-content:center;
  transition:transform .16s,background .25s,border-color .25s}
.theme:hover{transform:translateY(-1px)}
.theme:active{transform:translateY(0)}
.theme svg{width:17px;height:17px;stroke:currentColor;fill:none;
  stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.icon-sun{display:none}
html[data-theme="dark"] .icon-sun{display:block}
html[data-theme="dark"] .icon-moon{display:none}
.top .st{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--sub);
  background:var(--glass);border:1px solid var(--glass-b);
  padding:5px 11px;border-radius:999px;backdrop-filter:blur(4px);
  box-shadow:var(--shadow);font-variant-numeric:tabular-nums}
.pulse{width:8px;height:8px;border-radius:50%;background:var(--green);
  box-shadow:0 0 0 0 rgba(34,197,94,.45);animation:pulse 2.2s infinite}
@keyframes pulse{70%{box-shadow:0 0 0 7px rgba(34,197,94,0)}}
/* ---------- 卡片 ---------- */
.card{background:var(--card);border-radius:18px;padding:13px 15px 11px;margin-bottom:11px;
  box-shadow:var(--shadow);border:1px solid var(--card-b);transition:background .35s,box-shadow .35s}
.card.off{opacity:.55;filter:grayscale(.85)}
.head{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.dot{width:10px;height:10px;border-radius:50%;flex:none;background:var(--green);
  box-shadow:0 0 0 3px rgba(34,197,94,.15)}
.off .dot{background:#9ca3af;box-shadow:none}
.name{font-size:15.5px;font-weight:750;letter-spacing:.2px}
.offline-badge{font-size:11px;color:#fff;background:#9ca3af;border-radius:999px;
  padding:2.5px 9px;margin-left:2px;font-weight:600}
.hd-r{margin-left:auto;display:flex;align-items:center;gap:7px}
.os{display:flex;align-items:center;gap:4px;font-size:11px;line-height:1;
  color:var(--sub);background:var(--glass);border:1px solid var(--glass-b);
  border-radius:999px;padding:3px 8px 3px 6px;font-weight:600;letter-spacing:.2px;white-space:nowrap}
.os i{font-style:normal;font-size:12px;line-height:1}
.flags{font-size:17px;letter-spacing:2px;filter:drop-shadow(0 1px 1px rgba(0,0,0,.08))}
/* ---------- 指标格 ---------- */
.grid{display:grid;grid-template-columns:1fr 1fr;gap:9px 22px}
@media(max-width:440px){.grid{grid-template-columns:1fr}}
.m .lr{display:flex;justify-content:space-between;align-items:baseline;font-size:13.5px}
.m .lb{color:var(--sub);font-weight:600}
.m .v{font-weight:700;font-variant-numeric:tabular-nums}
.bar{height:5px;border-radius:3px;background:var(--track);margin:5px 0 3.5px;overflow:hidden}
.fill{height:100%;border-radius:3px;width:0;
  background:linear-gradient(90deg,#34d399,#a3e635);
  transition:width .8s cubic-bezier(.22,1,.36,1)}
.fill.w{background:linear-gradient(90deg,#fcd34d,#f59e0b)}
.fill.b{background:linear-gradient(90deg,#f87171,#ef4444)}
.tip{font-size:11px;color:var(--faint);font-variant-numeric:tabular-nums;letter-spacing:.2px}
/* ---------- 点线引导行 ---------- */
.dl{display:flex;align-items:baseline;font-size:13.5px;margin-top:7.5px}
.dl .lb{color:var(--sub);font-weight:600;flex:none}
.dl .lead{flex:1;border-bottom:1.5px dotted #d3d9d3;margin:0 10px;transform:translateY(-3px)}
.dl .val{font-weight:700;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.up{color:var(--green)}.down{color:var(--blue)}
.sep{color:var(--sep);font-weight:400;margin:0 5px}
/* ---------- 延迟 / 丢包 ---------- */
.sum{display:grid;grid-template-columns:1fr 1fr;gap:9px 22px;margin-top:9px}
@media(max-width:440px){.sum{grid-template-columns:1fr}}
.s .lr{display:flex;justify-content:space-between;align-items:baseline;font-size:13.5px}
.s .lr .v{font-weight:700;font-variant-numeric:tabular-nums}
.seg-bar{display:flex;gap:3px;margin-top:5.5px}
.seg-bar i{flex:1;height:4px;border-radius:2px;background:var(--track);transition:background .5s}
.seg-bar i.g{background:var(--green)}
.seg-bar i.a{background:var(--amber)}
.seg-bar i.r{background:var(--red)}
.seg-bar i.p{background:var(--pink)}
/* ---------- 页脚 ---------- */
.foot{text-align:center;color:#8ba392;font-size:11.5px;margin-top:14px;letter-spacing:.4px}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="st"><span class="pulse"></span><span id="meta">加载中…</span></div>
    <div class="sp"></div>
    <button class="theme" id="themeBtn" title="切换浅色 / 深色（快捷键 T）" aria-label="切换主题">
      <svg class="icon-moon" viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
      <svg class="icon-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
    </button>
  </div>
  <div id="list"></div>
  <div class="foot">自建轻量探针 · agent 每 15 秒上报 · 面板 5 秒自动刷新</div>
</div>
<script>
/* ---------- 主题切换 ---------- */
const root=document.documentElement;
function setTheme(t,save){
  root.setAttribute("data-theme",t);
  if(save!==false){try{localStorage.setItem("probe-theme",t)}catch(e){}}
}
(function(){
  let saved=null;
  try{saved=localStorage.getItem("probe-theme")}catch(e){}
  const dark=window.matchMedia&&matchMedia("(prefers-color-scheme: dark)").matches;
  setTheme(saved||(dark?"dark":"light"),false);
})();
document.getElementById("themeBtn").addEventListener("click",function(){
  setTheme(root.getAttribute("data-theme")==="dark"?"light":"dark");
});
document.addEventListener("keydown",function(e){
  if((e.key==="t"||e.key==="T")&&!e.metaKey&&!e.ctrlKey&&!e.altKey){
    document.getElementById("themeBtn").click();
  }
});
/* ---------- 渲染 ---------- */
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
/* 系统图标 */
function osIcon(id){
  const m={ubuntu:"🐧",debian:"🐧",centos:"🐧",almalinux:"🐧",rocky:"🐧",fedora:"🐧",
    alpine:"🐧",arch:"🐧",opensuse:"🐧",fnos:"🐧",linux:"🐧",windows:"🪟",darwin:"🍎",macos:"🍎",freebsd:"😈"};
  return m[String(id||"").toLowerCase()]||"🐧";
}
function osChip(o){
  if(!o||!o.name)return "";
  const short=String(o.name).replace(/GNU\/Linux/gi,"").replace(/\s+/g," ").trim().split(" ").slice(0,2).join(" ");
  return '<span class="os" title="'+esc(o.name+(o.arch?" · "+o.arch:""))+'"><i>'+osIcon(o.id)+'</i>'+esc(short)+'</span>';
}
function fmtRate(b){if(b>=1048576)return (b/1048576).toFixed(1)+" MB/s";
  if(b>=1024)return (b/1024).toFixed(1)+" KB/s";return Math.round(b)+" B/s"}
function fmtSize(b){if(b>=1099511627776)return (b/1099511627776).toFixed(2)+" TB";
  if(b>=1073741824)return (b/1073741824).toFixed(1)+" GB";return (b/1048576).toFixed(0)+" MB"}
function fmtUp(s){s=Math.floor(s);const d=Math.floor(s/86400),h=Math.floor(s%86400/3600);
  if(d>0)return d+" 天 "+h+" 小时";const m=Math.floor(s%3600/60);
  return h>0?h+" 小时 "+m+" 分":m+" 分钟"}
function latColor(ms){return ms<150?"var(--green)":ms<250?"var(--amber)":"var(--red)"}
function lossColor(l){return l<=0?"var(--green)":l<5?"var(--amber)":"var(--pink)"}
function barCls(p){return p>85?"fill b":p>65?"fill w":"fill"}
function mRow(lb,pct,val,tip){
  const w=Math.max(pct,2.5).toFixed(1);
  return '<div class="m"><div class="lr"><span class="lb">'+lb+'</span><span class="v">'+val+
    '</span></div><div class="bar"><div class="'+barCls(pct)+'" style="width:'+w+
    '%"></div></div><div class="tip">'+tip+'</div></div>';
}
function dlRow(lb,val){
  return '<div class="dl"><span class="lb">'+lb+'</span><span class="lead"></span><span class="val">'+
    val+'</span></div>';
}
function segBar(n,fn){
  let h='<div class="seg-bar">';
  for(let i=0;i<n;i++)h+='<i class="'+fn(i,n)+'"></i>';
  return h+'</div>';
}
function card(n){
  const cpu=n.cpu||0;
  const memPct=n.mem_total?n.mem_used/n.mem_total*100:0;
  const diskPct=n.disk_total?n.disk_used/n.disk_total*100:0;
  const nets=n.net||[];
  const alive=nets.filter(x=>(x.loss||0)<100&&x.avg>0);
  const avgL=alive.length?alive.reduce((s,x)=>s+x.avg,0)/alive.length:0;
  const avgP=nets.length?nets.reduce((s,x)=>s+(x.loss||0),0)/nets.length:0;
  const online=!!n.online;

  // 三网小徽标
  const chips=nets.map(x=>{
    if(!online||(x.loss||0)>=100)
      return '<span style="color:var(--faint)">'+esc(x.name)+' -</span>';
    return '<span class="lat" style="color:'+latColor(x.avg)+'">'+
      esc(x.name)+' '+Math.round(x.avg)+'ms</span>';
  }).join('<span class="sep">·</span>');

  // 延迟分段条: 0-300ms 映射到 12 格
  const lv=Math.min(12,Math.round(avgL/300*12));
  const latCls=(i)=>!online?'':(i<lv?(avgL>=250?'r':avgL>=150?'a':'g'):'g');
  // 丢包分段条: 丢包占比映射到 12 格
  const lb=Math.ceil(avgP/100*12);
  const lossCls=(i)=>!online?'':(i<lb?(avgP<10?'a':'r'):'g');

  const rate=dlRow('速率',
    '<span class="up">↑ '+fmtRate(n.tx_rate||0)+'</span><span class="sep"> </span>'+
    '<span class="down">↓ '+fmtRate(n.rx_rate||0)+'</span>');
  const up=dlRow('在线','<span style="color:'+(online?"var(--ink)":"var(--faint)")+'">'+
    (online?fmtUp(n.uptime||0):"离线")+'</span>');
  const price=dlRow('费用',n.price?esc(n.price):'<span style="color:var(--faint)">-</span>');
  const net3=dlRow('三网',chips);

  return '<div class="card'+(online?'':' off')+'">'+
    '<div class="head"><span class="dot"></span><span class="name">'+esc(n.name)+'</span>'+
    (online?'':'<span class="offline-badge">离线</span>')+
    '<span class="hd-r"><span class="flags">'+esc(n.flag||"")+'</span>'+osChip(n.os)+'</span></div>'+
    '<div class="grid">'+
      mRow('CPU',cpu,cpu.toFixed(1)+'%',(n.load||[]).join(', '))+
      mRow('内存',memPct,memPct.toFixed(1)+'%',fmtSize(n.mem_used||0)+' / '+fmtSize(n.mem_total||0))+
      mRow('硬盘',diskPct,diskPct.toFixed(1)+'%',fmtSize(n.disk_used||0)+' / '+fmtSize(n.disk_total||0))+
      mRow('流量',2.5,'0.0%','↑ '+fmtSize(n.tx_total||0)+' · ↓ '+fmtSize(n.rx_total||0)+' / ∞')+
    '</div>'+
    rate+up+price+net3+
    '<div class="sum">'+
      '<div class="s"><div class="lr"><span class="lb">延迟</span>'+
        '<span class="v" style="color:'+(online&&avgL?latColor(avgL):"var(--faint)")+'">'+
        (online&&avgL?Math.round(avgL)+" ms":"-")+'</span></div>'+segBar(12,latCls)+'</div>'+
      '<div class="s"><div class="lr"><span class="lb">丢包</span>'+
        '<span class="v" style="color:'+(online?lossColor(avgP):"var(--faint)")+'">'+
        (online?avgP.toFixed(1)+"%":"-")+'</span></div>'+segBar(12,lossCls)+'</div>'+
    '</div></div>';
}
async function refresh(){
  try{
    const r=await fetch("/api/data");
    const data=await r.json();
    data.sort((a,b)=>(a.online===b.online)?((b.cpu||0)-(a.cpu||0)):(a.online?-1:1));
    document.getElementById("list").innerHTML=data.map(card).join("");
    const on=data.filter(x=>x.online).length;
    document.getElementById("meta").textContent=on+"/"+data.length+" 在线 · "+
      new Date().toLocaleTimeString("zh-CN",{hour12:false});
  }catch(e){document.getElementById("meta").textContent="加载失败"}
}
refresh();setInterval(refresh,5000);
</script>
</body>
</html>""".replace("__TITLE__", TITLE)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/data":
            now = time.time()
            with lock:
                out = []
                for name, rec in nodes.items():
                    d = dict(rec["data"])
                    d["online"] = (now - rec["last_seen"]) < OFFLINE_AFTER
                    out.append(d)
            self._send(200, json.dumps(out))
        else:
            self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path != "/api/report":
            self._send(404, '{"error":"not found"}')
            return
        if self.headers.get("X-Token") != TOKEN:
            self._send(403, '{"error":"bad token"}')
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            name = str(data.get("name", "unnamed"))
            with lock:
                nodes[name] = {"data": data, "last_seen": time.time()}
            self._send(200, '{"ok":true}')
        except Exception as e:
            self._send(400, '{"error":"%s"}' % e)

    def handle_one_request(self):
        # 浏览器关闭长连接时静默处理，避免日志刷屏
        try:
            BaseHTTPRequestHandler.handle_one_request(self)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def log_message(self, fmt, *args):
        pass  # 静默日志，避免撑爆磁盘


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("[%s] 探针服务端已启动: 端口 %d" % (TITLE, PORT))
    srv.serve_forever()
