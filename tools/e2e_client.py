#!/usr/bin/env python3
"""End-to-end leg test, client side (Windows / macOS / Linux runners).

Waits for the server job (public `service` repo) to post its relay address on a private
ntfy.sh topic, then connects to that SOCKS5 proxy and times each leg separately:

  relay_tcp     TCP connect to the public relay (client -> relay)
  greet         SOCKS greeting round trip (client -> relay -> server runner -> back)
  auth          SOCKS user/pass round trip (same path again)
  connect       SOCKS CONNECT by name: server resolves through the tunnel and
                connects to the target through the tunnel, then answers
  tls           TLS handshake to the target, end to end
  ttfb          HTTP GET to first response byte, end to end
  total         until 64 KB or the end of the response
plus a curl run per target through socks5h for comparison. Topic and password are secrets.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import ssl
import statistics
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

TARGETS = ["www.google.com", "www.youtube.com", "ilovestudyip.com"]


def ntfy(topic, since="2h"):
    try:
        raw = urllib.request.urlopen(f"https://ntfy.sh/{topic}/json?poll=1&since={since}", timeout=15).read().decode()
    except Exception:
        return []
    return [json.loads(l).get("message", "") for l in raw.splitlines() if l.strip()]


def post(topic, text):
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{topic}", data=text.encode(), method="POST"), timeout=15).read()
    except Exception:
        pass


def recv_exact(s, n):
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c:
            raise OSError("closed")
        b += c
    return b


def one(relay_host, relay_port, pw, host) -> dict:
    r: dict = {}
    t = time.perf_counter()
    s = socket.create_connection((relay_host, relay_port), timeout=20)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    r["relay_tcp"] = (time.perf_counter() - t) * 1000
    try:
        t = time.perf_counter(); s.sendall(b"\x05\x01\x02"); recv_exact(s, 2); r["greet"] = (time.perf_counter() - t) * 1000
        u = b"e2e"; p = pw.encode()
        t = time.perf_counter(); s.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        if recv_exact(s, 2)[1] != 0:
            raise OSError("auth refused")
        r["auth"] = (time.perf_counter() - t) * 1000
        h = host.encode()
        t = time.perf_counter(); s.sendall(b"\x05\x01\x00\x03" + bytes([len(h)]) + h + struct.pack(">H", 443))
        rep = recv_exact(s, 10)
        if rep[1] != 0:
            raise OSError("connect refused")
        r["connect"] = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        ss = ssl.create_default_context().wrap_socket(s, server_hostname=host)
        r["tls"] = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        ss.sendall(f"GET / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: Mozilla/5.0\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n".encode())
        ss.settimeout(20)
        first = ss.recv(1)
        r["ttfb"] = (time.perf_counter() - t) * 1000
        got = len(first)
        while got < 65536:
            c = ss.recv(16384)
            if not c:
                break
            got += len(c)
        r["total"] = (time.perf_counter() - t) * 1000 + r["tls"] + r["connect"] + r["auth"] + r["greet"] + r["relay_tcp"]
        ss.close()
    except Exception as exc:
        r["error"] = str(exc)[:80]
        s.close()
    return r


def curl(relay, pw, host):
    fmt = "%{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total} %{http_code}"
    exe = "curl.exe" if os.name == "nt" else "curl"
    try:
        out = subprocess.run([exe, "-s", "-o", os.devnull, "--max-time", "25", "-w", fmt, "-x", f"socks5h://e2e:{pw}@{relay}", f"https://{host}/"],
                             capture_output=True, text=True, timeout=30).stdout.split()
        return {"tcp": float(out[0]) * 1000, "tls": float(out[1]) * 1000, "ttfb": float(out[2]) * 1000, "total": float(out[3]) * 1000, "code": out[4]}
    except Exception:
        return {"error": "curl"}


def st(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return "-"
    return f"{statistics.median(v):.0f} / {v[min(len(v) - 1, int(round(0.9 * (len(v) - 1))))]:.0f}"


def main():
    pw, topic = os.environ["E2E_PASS"], os.environ["E2E_TOPIC"]
    rounds = int(os.environ.get("ROUNDS") or 6)
    tag = os.environ.get("TAG") or "t"
    out = Path("out"); out.mkdir(exist_ok=True)
    relay = ""
    t0 = time.time()
    while time.time() - t0 < 25 * 60 and not relay:
        for m in reversed(ntfy(topic, since="40m")):
            if m.startswith(f"{tag} RELAY "):
                relay = m.split()[2]
                break
            if m.startswith(f"{tag} FAIL"):
                (out / "summary.md").write_text(f"# 端到端（客户端 {platform.system()}）\n\n服务端没有拨通节点。\n")
                return
        if not relay:
            time.sleep(10)
    if not relay:
        (out / "summary.md").write_text(f"# 端到端（客户端 {platform.system()}）\n\n25 分钟内没等到服务端。\n")
        return
    rh, rp = relay.rsplit(":", 1)
    rows = {h: [] for h in TARGETS}
    curls = {h: [] for h in TARGETS}
    for _ in range(rounds):
        for h in TARGETS:
            rows[h].append(one(rh, int(rp), pw, h))
            curls[h].append(curl(relay, pw, h))
            time.sleep(0.5)
    post(topic, f"{tag} DONE {platform.system()}")
    lines = [f"# 端到端分段实测（客户端 {platform.system()} {platform.release()}，GitHub 托管机器）", "",
             "中继是公共的 bore.pub，所以「客户端→服务端」比真实手机到服务器多绕一跳。单位 ms，中位 / P90。", "",
             "| 目标 | 次数 | 失败 | 客户端→中继 TCP | 问候往返（客户端↔服务端） | 认证往返 | CONNECT（服务端经隧道解析+建连） | TLS | 首字节 | 合计 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for h, rs in rows.items():
        ok = [r for r in rs if "error" not in r]
        lines.append(f"| {h} | {len(rs)} | {len(rs) - len(ok)} | " + " | ".join(st([r.get(k) for r in ok]) for k in ("relay_tcp", "greet", "auth", "connect", "tls", "ttfb", "total")) + " |")
    lines += ["", "curl 经 socks5h（同一代理）：", "", "| 目标 | 次数 | 失败 | 到代理建连+SOCKS | TLS 完成 | 首字节 | 总计 |", "|---|---|---|---|---|---|---|"]
    for h, rs in curls.items():
        ok = [r for r in rs if "error" not in r and r.get("code") not in ("000", None)]
        lines.append(f"| {h} | {len(rs)} | {len(rs) - len(ok)} | " + " | ".join(st([r.get(k) for r in ok]) for k in ("tcp", "tls", "ttfb", "total")) + " |")
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    (out / "client.json").write_text(json.dumps({"rows": rows, "curl": curls}, indent=1))


if __name__ == "__main__":
    main()
