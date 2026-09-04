#!/usr/bin/env python3
"""GitHub Actions runner 专用：分片下载 Wayback 上的 army.mil.ph 标书 PDF。

用法: python runner_dl.py <shard_index> <shard_count>
输入: bids.json (与仓库同目录)
输出: out/<年>/<文件名>.pdf + failed.txt + manifest.json
"""
import json
import re
import sys
import time
import hashlib
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")
REQ_GAP_S = 4.0
RETRIES = 5
MAX_BYTES = 500 * 1024 * 1024


def wayback_url(rec: dict) -> str:
    snaps = [s for s in rec.get("cdx_snapshots", []) if s.get("status") == "200"] \
        or rec.get("cdx_snapshots", [])
    ts = max((s["ts"] for s in snaps if s.get("ts")), default="")
    return f"https://web.archive.org/web/{ts}id_/{rec['url']}"


def fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                if resp.status == 200:
                    data = resp.read(MAX_BYTES + 1)
                    return data, resp.headers.get("Content-Length")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                wait = min(60 * (attempt + 1), 300)
                print(f"  [{e.code}] 冷却 {wait}s", flush=True)
                time.sleep(wait)
                continue
            print(f"  [{e.code}]", flush=True)
        except Exception as e:
            print(f"  [{type(e).__name__}]", flush=True)
        time.sleep(2 ** attempt)
    return None, None


def validate(data: bytes, clen) -> tuple[bool, str]:
    if not data:
        return False, "空"
    if not data.startswith(b"%PDF"):
        return False, f"非PDF({data[:15]!r})"
    if b"%%EOF" not in data[-2048:]:
        return False, "缺EOF"
    if clen and clen.isdigit() and int(clen) != len(data):
        return False, f"长度不符 {clen}!={len(data)}"
    return True, ""


def main() -> None:
    shard, count = int(sys.argv[1]), int(sys.argv[2])
    records = json.loads(Path("bids.json").read_text())
    todo = records[shard::count]
    print(f"shard {shard}/{count}: {len(todo)} 条", flush=True)

    out_root = Path("out")
    manifest, failed = [], []
    t0 = time.time()
    for i, rec in enumerate(todo, 1):
        url = rec["url"]
        name = re.sub(r"[^\w.\-() ]", "_", rec.get("filename") or "unnamed.pdf")[:200]
        year = rec.get("year") or "unknown"
        dest = out_root / year / name
        if dest.exists() and dest.stat().st_size > 0:
            data = dest.read_bytes()
            ok, _ = validate(data, None)
            if ok:
                manifest.append({"url": url, "file": str(dest), "size": len(data), "status": "ok"})
                continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        data, clen = fetch(wayback_url(rec))
        ok, why = validate(data, clen) if data else (False, "下载失败")
        if ok:
            dest.write_bytes(data)
            manifest.append({"url": url, "file": str(dest), "size": len(data),
                             "sha256": hashlib.sha256(data).hexdigest(), "status": "ok"})
            print(f"  [{i}/{len(todo)}] ✅ {year}/{name[:50]} ({len(data)}B)", flush=True)
        else:
            failed.append(url)
            manifest.append({"url": url, "status": "failed", "reason": why})
            print(f"  [{i}/{len(todo)}] ❌ {name[:50]} ({why})", flush=True)
        time.sleep(REQ_GAP_S)
        if i % 50 == 0:
            Path(f"manifest_shard{shard}.json").write_text(json.dumps(manifest))

    Path(f"manifest_shard{shard}.json").write_text(json.dumps(manifest))
    Path(f"failed_shard{shard}.txt").write_text("\n".join(failed))
    ok_n = sum(1 for m in manifest if m["status"] == "ok")
    print(f"\nshard {shard} 完成: ok {ok_n}/{len(todo)}, failed {len(failed)}, "
          f"用时 {(time.time()-t0)/60:.0f}min", flush=True)


if __name__ == "__main__":
    main()
