#!/usr/bin/env python3
"""Reach the web through each proxy in PROXY_URLS (and sing-box if configured).

Prints only masked hosts. Never prints credentials.
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

URLS = ("https://www.google.com/generate_204", "https://www.gstatic.com/generate_204", "https://api.ipify.org")


def mask_host(host: str) -> str:
    host = str(host or "")
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host):
        return ".".join(host.split(".")[:2] + ["x", "x"])
    parts = host.split(".")
    return ("*." + ".".join(parts[-1:])) if len(parts) > 1 else "*"


def curl() -> str:
    return shutil.which("curl.exe") or shutil.which("curl") or "curl"


def probe(proxy: str, url: str) -> dict:
    fmt = "%{http_code} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total}"
    start = time.time()
    proc = subprocess.run([curl(), "-sS", "-o", os.devnull if "ipify" not in url else "-", "-w", "\n" + fmt,
                           "--proxy", proxy, "--connect-timeout", "8", "--max-time", "20", url],
                          capture_output=True, text=True, timeout=30)
    lines = (proc.stdout or "").strip().splitlines()
    stats = lines[-1].split() if lines else []
    body = lines[0].strip() if len(lines) > 1 else ""
    ok = proc.returncode == 0 and bool(stats) and stats[0] in ("200", "204")
    return {
        "url": url.split("/")[2],
        "ok": ok,
        "code": stats[0] if stats else "-",
        "total": float(stats[4]) if len(stats) == 5 else round(time.time() - start, 2),
        "exit": mask_host(body) if ok and "ipify" in url else "",
        "error": "" if ok else re.sub(r"\S+@\S+|\d+\.\d+\.\d+\.\d+", "x", (proc.stderr or "").strip())[:80],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rounds = int(os.environ.get("ROUNDS") or 5)
    proxies = []
    for i, line in enumerate((os.environ.get("PROXY_URLS") or "").splitlines()):
        line = line.strip()
        if line and not line.startswith("#"):
            parts = urlsplit(line)
            proxies.append((f"{parts.scheme}://{mask_host(parts.hostname)}:{parts.port} (#{i + 1})", line))
    singbox = Path("singbox/sing-box.exe" if os.name == "nt" else "singbox/sing-box")
    proc = None
    if os.environ.get("SINGBOX_CONFIG") and singbox.exists():
        cfg = Path("singbox/config.json")
        cfg.write_text(os.environ["SINGBOX_CONFIG"], encoding="utf-8")
        proc = subprocess.Popen([str(singbox), "run", "-c", str(cfg)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        proxies.append(("sing-box 配置", "socks5h://127.0.0.1:2080"))
    lines = [f"# 代理连通实测（{platform.system()}）", ""]
    if not proxies:
        lines.append("没有设置 PROXY_URLS 或 SINGBOX_CONFIG，跳过。")
        (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("no proxies configured")
        return
    lines += ["| 代理 | 地址 | 成功/次数 | 中位数秒 | 最大秒 | 出口 | 错误 |", "|---|---|---|---|---|---|---|"]
    try:
        for label, proxy in proxies:
            for url in URLS:
                results = [probe(proxy, url) for _ in range(rounds)]
                ok = [r["total"] for r in results if r["ok"]]
                exits = sorted({r["exit"] for r in results if r["exit"]})
                errors = sorted({r["error"] for r in results if r["error"]})
                lines.append(f"| {label} | {results[0]['url']} | {len(ok)}/{len(results)} | {statistics.median(ok) if ok else '-'} | {max(ok) if ok else '-'} | {', '.join(exits)} | {'; '.join(errors)[:100]} |")
    finally:
        if proc:
            proc.terminate()
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
