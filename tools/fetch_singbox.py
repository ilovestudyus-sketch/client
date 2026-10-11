#!/usr/bin/env python3
"""Download the latest sing-box release for this runner into ./singbox."""
import io, json, os, platform, tarfile, urllib.request, zipfile
from pathlib import Path

rel = json.load(urllib.request.urlopen("https://api.github.com/repos/SagerNet/sing-box/releases/latest", timeout=30))
system = {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}[platform.system()]
arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "amd64"
suffix = ".zip" if system == "windows" else ".tar.gz"
asset = next(a for a in rel["assets"] if a["name"].endswith(f"-{system}-{arch}{suffix}"))
data = urllib.request.urlopen(asset["browser_download_url"], timeout=60).read()
target = Path("singbox"); target.mkdir(exist_ok=True)
name = "sing-box.exe" if system == "windows" else "sing-box"
if suffix == ".zip":
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        member = next(m for m in z.namelist() if m.endswith("/" + name))
        (target / name).write_bytes(z.read(member))
else:
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        member = next(m for m in t.getmembers() if m.name.endswith("/" + name))
        (target / name).write_bytes(t.extractfile(member).read())
os.chmod(target / name, 0o755)
print("sing-box", rel.get("tag_name"), system, arch)
