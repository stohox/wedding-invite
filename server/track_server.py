#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""婚礼邀请函埋点服务（零依赖 stdlib 实现，与主项目隔离）

POST /track            写入事件（sendBeacon text/plain 载体，同域无 CORS）
GET  /stats?token=XXX  只读统计汇总（token 保护）
GET  /health           健康检查

数据文件：同目录 track.db（SQLite）；IP 归属地：同目录 ip2region.xdb（可选，缺失则留空）
"""
import json
import hashlib
import os
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "track.db")
TOKEN = os.environ.get("TRACK_TOKEN", "")  # stats token, set via systemd env
IP_SALT = os.environ.get("TRACK_IP_SALT", "")  # ip hash salt, set via systemd env
XDB = os.path.join(BASE, "ip2region_v4.xdb")

_db_lock = threading.Lock()


def init_db():
    con = sqlite3.connect(DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        sid TEXT NOT NULL,
        event TEXT NOT NULL,
        payload TEXT,
        ip_hash TEXT,
        province TEXT,
        device TEXT,
        ua TEXT)"""
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_event ON events(event)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_sid ON events(sid)")
    con.commit()
    con.close()


# ---- IP 归属地（可选：ip2region xdb 离线库） ----
_searcher = None
_searcher_tried = False


def get_searcher():
    global _searcher, _searcher_tried
    if _searcher_tried:
        return _searcher
    _searcher_tried = True
    if os.path.exists(XDB):
        try:
            import ip2region.util as util
            import ip2region.searcher as xdb
            cbuf = util.load_content_from_file(XDB)  # 全量进内存，线程安全
            _searcher = xdb.new_with_buffer(util.IPv4, cbuf)
        except Exception as e:
            print("xdb init failed:", e)
            _searcher = None
    return _searcher


def province_of(ip):
    if not ip or ip.startswith(("10.", "192.168.", "127.", "172.16.", "172.17.")):
        return "内网"
    s = get_searcher()
    if s is None:
        return ""
    try:
        region = s.search(ip) or ""
        # 新版 region 形如：中国|广东省|深圳市|电信|CN
        parts = region.split("|")
        country = parts[0] if parts else ""
        prov = parts[1] if len(parts) > 1 else ""
        if country and country != "中国":
            return country
        return prov or country or ""
    except Exception:
        return ""


def parse_device(ua):
    ua = ua or ""
    if "iPad" in ua or "iPhone" in ua:
        dev = "iOS"
    elif "Android" in ua:
        dev = "Android"
    else:
        dev = "PC/其他"
    if "MicroMessenger" in ua:
        net = "微信"
    elif "QQ/" in ua:
        net = "QQ"
    else:
        net = "浏览器"
    return dev + "/" + net


def insert_event(ts, sid, event, payload, ip_hash, province, device, ua):
    con = sqlite3.connect(DB)
    with _db_lock:
        con.execute(
            "INSERT INTO events (ts, sid, event, payload, ip_hash, province, device, ua) VALUES (?,?,?,?,?,?,?,?)",
            (ts, sid, event, payload, ip_hash, province, device, ua),
        )
        con.commit()
    con.close()


def build_stats():
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT ts, sid, event, payload, province, device FROM events ORDER BY id"
    ).fetchall()
    con.close()

    page_uv = {}
    event_count = {}
    hours = [0] * 24
    sid_province = {}
    sid_device = {}
    sids = set()
    for ts, sid, event, payload, province, device in rows:
        sids.add(sid)
        event_count[event] = event_count.get(event, 0) + 1
        hours[time.localtime(ts).tm_hour] += 1
        if province and sid not in sid_province:
            sid_province[sid] = province
        if device and sid not in sid_device:
            sid_device[sid] = device
        if event == "page_view":
            try:
                page = (json.loads(payload) or {}).get("page", "unknown")
            except Exception:
                page = "unknown"
            page_uv.setdefault(page, set()).add(sid)

    order = ["cover", "info", "story", "gallery", "memories", "danmaku", "tree", "ending"]
    funnel = [{"page": p, "uv": len(page_uv[p])} for p in order if p in page_uv]
    for p, s in sorted(page_uv.items()):
        if p not in order:
            funnel.append({"page": p, "uv": len(s)})

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pv": event_count.get("page_view", 0),
        "uv": len(sids),
        "funnel_uv": funnel,
        "events": dict(sorted(event_count.items(), key=lambda kv: -kv[1])),
        "nav_clicks": event_count.get("nav_click", 0),
        "hours": hours,
        "provinces": top_counts(sid_province, 10),
        "devices": top_counts(sid_device, 10),
    }


def top_counts(mapping, limit):
    counts = {}
    for v in mapping.values():
        counts[v] = counts.get(v, 0) + 1
    return [{"name": k, "uv": c} for k, c in sorted(counts.items(), key=lambda kv: -kv[1])[:limit]]


class Handler(BaseHTTPRequestHandler):
    server_version = "WTrack/1.0"

    def log_message(self, fmt, *args):
        pass  # 静默访问日志（数据已入库，避免占磁盘）

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/track":
            return self._json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(min(length, 4096))
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})
        sid = str(data.get("sid", ""))[:64]
        event = re.sub(r"[^a-z0-9_]", "", str(data.get("event", "")))[:32]
        if not sid or not event:
            return self._json(400, {"error": "missing fields"})
        try:
            payload = json.dumps(data.get("data", {}), ensure_ascii=False)[:512]
        except Exception:
            payload = "{}"
        ip = self.headers.get("X-Real-IP") or self.client_address[0]
        ip_hash = hashlib.sha256((IP_SALT + ip).encode()).hexdigest()[:16]
        province = province_of(ip)
        device = parse_device(self.headers.get("User-Agent", ""))
        ua = (self.headers.get("User-Agent") or "")[:200]
        insert_event(int(time.time()), sid, event, payload, ip_hash, province, device, ua)
        self._json(200, {"ok": 1})

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/health":
            return self._json(200, {"ok": 1})
        if path == "/stats":
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            if params.get("token") != TOKEN:
                return self._json(403, {"error": "forbidden"})
            return self._json(200, build_stats())
        self._json(404, {"error": "not found"})


if __name__ == "__main__":
    init_db()
    srv = ThreadingHTTPServer(("127.0.0.1", 8899), Handler)
    print("wtrack listening on 127.0.0.1:8899, db:", DB)
    srv.serve_forever()
