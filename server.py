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
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ============ 配置区（支持环境变量覆盖，Docker 部署无需改文件） ============
import os  # noqa: E402

TOKEN = os.environ.get("PROBE_TOKEN", "change-me-2026")   # 与 agent 一致，务必修改！
PORT = int(os.environ.get("PROBE_PORT") or (sys.argv[1] if len(sys.argv) > 1 else 25777))
TITLE = os.environ.get("PROBE_TITLE", "无趣的探针")
OFFLINE_AFTER = int(os.environ.get("PROBE_OFFLINE_AFTER", 45))  # 超时判定离线(秒)
# ========================================================================

nodes = {}          # name -> {"data": {...}, "last_seen": ts}
lock = threading.Lock()

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#eef3ee;--card:#fff;--txt:#1f2937;--sub:#6b7280;--green:#22c55e;--lime:#a3e635;
--orange:#f59e0b;--red:#ef4444;--pink:#ec4899;--bar-bg:#e5e7eb}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
color:var(--txt);padding:20px 12px 60px}
.wrap{max-width:980px;margin:0 auto}
h1{font-size:22px;padding:8px 4px 18px;display:flex;align-items:center;gap:8px}
h1 .dot{width:10px;height:10px;border-radius:50%;background:var(--green)}
.meta{color:var(--sub);font-size:12px;margin-left:auto;font-weight:400}
.card{background:var(--card);border-radius:16px;padding:18px 20px;margin-bottom:16px;
box-shadow:0 1px 3px rgba(0,0,0,.06)}
.card.offline{opacity:.45;filter:grayscale(.6)}
.head{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.head .st{width:11px;height:11px;border-radius:50%;background:var(--green);flex:none}
.offline .head .st{background:#9ca3af}
.head .name{font-size:17px;font-weight:700}
.head .flag{font-size:18px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px 22px}
@media(max-width:560px){.grid{grid-template-columns:1fr}}
.blk{min-width:0}
.lbl{display:flex;justify-content:space-between;font-size:13px;color:var(--sub);margin-bottom:5px}
.lbl b{color:var(--txt);font-weight:600}
.bar{height:7px;border-radius:4px;background:var(--bar-bg);overflow:hidden}
.fill{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--green),var(--lime));
transition:width .6s ease}
.fill.warn{background:linear-gradient(90deg,#f97316,var(--orange))}
.fill.bad{background:linear-gradient(90deg,#dc2626,var(--red))}
.small{font-size:11px;color:var(--sub);margin-top:4px}
.row2{display:flex;justify-content:space-between;font-size:13px;color:var(--sub);margin:10px 0 4px}
.row2 b{color:var(--txt)}
.rate{display:flex;justify-content:flex-end;gap:14px;font-size:13px}
.up{color:var(--green)}.down{color:#0ea5e9}
.carriers{display:flex;gap:6px;justify-content:flex-end;font-size:13px;flex-wrap:wrap}
.c-item{padding:1px 6px;border-radius:6px;background:#f3f4f6;font-weight:600}
.sum{display:flex;justify-content:space-between;margin-top:12px;font-size:14px}
.lg-bar{display:flex;gap:3px;height:10px;margin-top:6px}
.seg{flex:1;border-radius:3px;background:var(--green)}
.seg.w{background:var(--orange)}.seg.b{background:var(--red)}
.seg.off{background:var(--bar-bg)}
.foot{text-align:center;color:var(--sub);font-size:12px;margin-top:24px}
</style>
</head>
<body>
<div class="wrap">
<h1><span class="dot"></span>__TITLE__<span class="meta" id="meta"></span></h1>
<div id="list"></div>
<div class="foot">自建轻量探针 · 数据每 15 秒更新</div>
</div>
<script>
let sortMode = localStorage.sortMode || "online";
function fmtRate(b){if(b>=1048576)return (b/1048576).toFixed(1)+" MB/s";
if(b>=1024)return (b/1024).toFixed(1)+" KB/s";return Math.round(b)+" B/s"}
function fmtSize(b){if(b>=1099511627776)return (b/1099511627776).toFixed(2)+" TB";
if(b>=1073741824)return (b/1073741824).toFixed(1)+" GB";return (b/1048576).toFixed(0)+" MB"}
function fmtUp(s){s=Math.floor(s);const d=Math.floor(s/86400),h=Math.floor(s%86400/3600);
if(d>0)return d+" 天 "+h+" 小时";const m=Math.floor(s%3600/60);return h>0?h+" 小时 "+m+" 分":m+" 分钟"}
function latColor(ms){return ms<150?"var(--green)":ms<250?"var(--orange)":"var(--red)"}
function lossColor(l){return l<=0?"var(--green)":l<5?"var(--orange)":"var(--pink)"}
function barCls(p){return p>85?"fill bad":p>65?"fill warn":"fill"}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function card(n){
 const cpu=n.cpu||0, mem=n.mem_total?n.mem_used/n.mem_total*100:0,
 disk=n.disk_total?n.disk_used/n.disk_total*100:0;
 const nets=n.net||[];
 const avgL=nets.length?nets.reduce((s,x)=>s+(x.avg||0),0)/nets.length:0;
 const avgP=nets.length?nets.reduce((s,x)=>s+(x.loss||0),0)/nets.length:0;
 const lv=Math.min(99,Math.round(avgL/30));
 let segs="";for(let i=0;i<10;i++){
  let cls=n.online?(i<lv?(avgP>5?"b":avgL>200?"w":""):"off"):"off";
  segs+='<div class="seg '+cls+'"></div>'}
 const cars=nets.map(x=>'<span class="c-item" style="color:'+latColor(x.avg)+'">'+
 esc(x.name)+' '+Math.round(x.avg)+'ms</span>').join("");
 return '<div class="card'+(n.online?'':' offline')+'">'+
 '<div class="head"><span class="st"></span><span class="name">'+esc(n.name)+'</span>'+
 '<span class="flag">'+esc(n.flag||"")+'</span></div>'+
 '<div class="grid">'+
 '<div class="blk"><div class="lbl">CPU<b>'+cpu.toFixed(1)+'%</b></div>'+
 '<div class="bar"><div class="'+barCls(cpu)+'" style="width:'+cpu+'%"></div></div>'+
 '<div class="small">'+esc((n.load||[]).join(", "))+'</div></div>'+
 '<div class="blk"><div class="lbl">内存<b>'+mem.toFixed(1)+'%</b></div>'+
 '<div class="bar"><div class="'+barCls(mem)+'" style="width:'+mem+'%"></div></div>'+
 '<div class="small">'+fmtSize(n.mem_used||0)+' / '+fmtSize(n.mem_total||0)+'</div></div>'+
 '<div class="blk"><div class="lbl">硬盘<b>'+disk.toFixed(1)+'%</b></div>'+
 '<div class="bar"><div class="'+barCls(disk)+'" style="width:'+disk+'%"></div></div>'+
 '<div class="small">'+fmtSize(n.disk_used||0)+' / '+fmtSize(n.disk_total||0)+'</div></div>'+
 '<div class="blk"><div class="lbl">流量<b>0.0%</b></div>'+
 '<div class="bar"><div class="fill" style="width:2%"></div></div>'+
 '<div class="small">↑ '+fmtSize(n.tx_total||0)+' · ↓ '+fmtSize(n.rx_total||0)+'</div></div>'+
 '<div class="blk"><div class="lbl">速率</div><div class="rate">'+
 '<span class="up">^ '+fmtRate(n.tx_rate||0)+'</span><span class="down">v '+fmtRate(n.rx_rate||0)+
 '</span></div></div>'+
 '<div class="blk"><div class="lbl">在线</div><div class="rate"><b>'+
 (n.online?fmtUp(n.uptime||0):"离线")+'</b></div></div>'+
 '<div class="blk"><div class="lbl">费用</div><div class="rate"><b>'+esc(n.price||"-")+
 '</b></div></div>'+
 '<div class="blk"><div class="lbl">三网</div><div class="rate cars-con">'+cars+'</div></div>'+
 '<div class="sum"><span>延迟 <b>'+(n.online?Math.round(avgL)+" ms":"-")+'</b></span>'+
 '<span>丢包 <b>'+(n.online?avgP.toFixed(1)+"%":"-")+'</b></span></div>'+
 '<div class="lg-bar">'+segs+'</div>'+
 '</div></div>'
}
async function refresh(){
 try{
  const r=await fetch("/api/data");const data=await r.json();
  data.sort((a,b)=>{
   if(sortMode==="online"&&(a.online!==b.online))return a.online?-1:1;
   return (b.cpu||0)-(a.cpu||0)});
  document.getElementById("list").innerHTML=data.map(card).join("");
  const on=data.filter(x=>x.online).length;
  document.getElementById("meta").textContent=on+"/"+data.length+" 在线 · "+
  new Date().toLocaleTimeString("zh-CN");
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

    def log_message(self, fmt, *args):
        pass  # 静默日志，避免撑爆磁盘


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("[%s] 探针服务端已启动: 端口 %d, Token: %s" % (TITLE, PORT, TOKEN))
    srv.serve_forever()
