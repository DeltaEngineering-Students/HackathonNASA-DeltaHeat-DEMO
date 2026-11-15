#!/usr/bin/env python3
"""Parallel ranged HTTP download (servers here give ~1 MB/s per connection). Resumable per part.
usage: pget.py URL DEST [connections]
"""
import os, sys, subprocess, time
from concurrent.futures import ThreadPoolExecutor

url, dest = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 16
head = subprocess.run(["curl", "-sIL", "--max-time", "60", url], capture_output=True, text=True).stdout
size = int([l.split(":")[1] for l in head.lower().splitlines() if l.startswith("content-length")][-1])
part = -(-size // n)
pdir = dest + ".parts"
os.makedirs(pdir, exist_ok=True)


def get(i):
    a, b = i * part, min(size, (i + 1) * part) - 1
    p = f"{pdir}/{i:03d}"
    want = b - a + 1
    for attempt in range(20):
        have = os.path.getsize(p) if os.path.exists(p) else 0
        if have == want:
            return
        if have > want:
            os.remove(p); have = 0
        with open(p, "ab") as f:  # stream straight to disk; partial bytes stay valid for resume
            r = subprocess.run(["curl", "-sfL", "--max-time", "7200", "-r", f"{a + have}-{b}", url], stdout=f)
        if r.returncode:
            time.sleep(min(300, 15 * (attempt + 1)))
    raise RuntimeError(f"part {i} failed")


with ThreadPoolExecutor(n) as ex:
    list(ex.map(get, range(n)))
with open(dest + ".tmp", "wb") as out:
    for i in range(n):
        with open(f"{pdir}/{i:03d}", "rb") as f:
            while chunk := f.read(64 << 20):
                out.write(chunk)
assert os.path.getsize(dest + ".tmp") == size
os.replace(dest + ".tmp", dest)
for i in range(n):
    os.remove(f"{pdir}/{i:03d}")
os.rmdir(pdir)
print(f"ok {size} bytes")
