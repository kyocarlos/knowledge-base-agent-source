"""One-off: recompute the vectors of the passages that carry page-snapshot / image reference lines, from the text without those lines (src/csit_integration_v1/embedding_text.py).
Only the vector of those points changes; ids, payload, passage text and citations stay as they are. No document is downloaded again and CSIT is not contacted.

  python tools/reembed_zone_documents.py --backup-dir DIR                 dry run: counts and how far each vector moves
  python tools/reembed_zone_documents.py --backup-dir DIR --apply         writes the old vectors to DIR first, then updates
  python tools/reembed_zone_documents.py --backup-dir DIR --restore FILE  puts the old vectors back
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.csit_integration_v1.embedding_text import embedding_text  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", default=os.getenv("KM_CSIT_DOCLIB_QDRANT_COLLECTION", "km_csit_docs"))
    ap.add_argument("--backup-dir", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore")
    a = ap.parse_args()
    from qdrant_client.models import PointVectors
    from src.vector_store import VectorStore
    store = VectorStore()
    client = store.client

    if a.restore:
        rows = json.loads(Path(a.restore).read_text(encoding="utf-8"))
        for i in range(0, len(rows), 64):
            client.update_vectors(a.collection, points=[PointVectors(id=r["id"], vector=r["vector"]) for r in rows[i:i + 64]], wait=True)
        print("restored", len(rows), "vectors from", a.restore)
        return

    points, offset = [], None
    while True:
        pts, offset = client.scroll(a.collection, limit=256, offset=offset, with_payload=True, with_vectors=True)
        points += pts
        if offset is None:
            break
    todo = [p for p in points if embedding_text((p.payload or {}).get("content") or "") != ((p.payload or {}).get("content") or "")]
    print(f"{a.collection}: {len(points)} points, {len(todo)} carry reference lines", "(dry run)" if not a.apply else "")
    if not todo:
        return
    named = isinstance(todo[0].vector, dict)
    vec_name = next(iter(todo[0].vector)) if named else None
    old = [(p.vector[vec_name] if named else p.vector) for p in todo]
    new = store.encode([embedding_text(p.payload["content"]) for p in todo])
    sims = []
    for o, n in zip(old, new):
        o, n = np.array(o, dtype=float), np.array(n, dtype=float)
        sims.append(float(o @ n / max(np.linalg.norm(o) * np.linalg.norm(n), 1e-9)))
    print("cosine between the old and the new vector of each changed point: min %.3f, mean %.3f, max %.3f" % (min(sims), sum(sims) / len(sims), max(sims)))
    docs = {}
    for p in todo:
        docs[(p.payload or {}).get("doc_name")] = docs.get((p.payload or {}).get("doc_name"), 0) + 1
    for name, n in sorted(docs.items(), key=lambda kv: str(kv[0])):
        print("   ", n, "passages of", name)
    if not a.apply:
        return
    Path(a.backup_dir).mkdir(parents=True, exist_ok=True)
    backup = Path(a.backup_dir) / f"{a.collection}-vectors-before-{time.strftime('%Y%m%d-%H%M%S')}.json"
    backup.write_text(json.dumps([{"id": p.id, "vector": list(map(float, o))} for p, o in zip(todo, old)]), encoding="utf-8")
    print("old vectors saved to", backup)
    for i in range(0, len(todo), 64):
        client.update_vectors(a.collection, points=[PointVectors(id=p.id, vector=({vec_name: list(map(float, n))} if named else list(map(float, n))))
                                                    for p, n in zip(todo[i:i + 64], new[i:i + 64])], wait=True)
    after, _ = client.scroll(a.collection, limit=1, with_payload=False, with_vectors=False)
    print("updated", len(todo), "vectors; collection still has", client.count(a.collection).count, "points (was", len(points), ")")


if __name__ == "__main__":
    main()
