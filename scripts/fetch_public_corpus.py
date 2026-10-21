"""Download the public documents listed in data/corpus/public_manifest.json into data/raw/public/.

    python scripts/fetch_public_corpus.py

Files are not committed (see .gitignore); the script records size and SHA-256 so a later run can
tell whether FDA has replaced a document.
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/corpus/public_manifest.json"
OUT = ROOT / "data/raw/public"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    lock = {}
    for doc in manifest["documents"]:
        path = OUT / doc["file"]
        if not path.exists():
            req = urllib.request.Request(doc["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if not data.startswith(b"%PDF"):
                sys.exit(f"{doc['doc_id']}: not a PDF ({doc['url']})")
            path.write_bytes(data)
        data = path.read_bytes()
        lock[doc["doc_id"]] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        print(f"{doc['doc_id']:16s} {len(data):>9,d} bytes")
    (OUT / "lock.json").write_text(json.dumps(lock, indent=2))


if __name__ == "__main__":
    main()
