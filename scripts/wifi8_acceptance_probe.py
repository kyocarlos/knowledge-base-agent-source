"""Zone-side part of the WiFi acceptance (scripts/wifi8_acceptance.py copies this and the module into the search worker).

  docker exec -w /app kb-celery-search python /tmp/x/wifi8_acceptance_probe.py \
      --cases /tmp/x/golden-set.v1.jsonl --spec /tmp/x/acceptance-spec.json --module-dir /tmp/x/wifi8 --out /tmp/x/probe.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--module-dir", required=True, help="directory holding acceptance.py (and evaluation.py), shadowing the deployed src.wifi8")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    import src.wifi8
    src.wifi8.__path__.insert(0, str(Path(args.module_dir).resolve()))
    from src.vector_store import VectorStore
    from src.wifi8 import acceptance
    from src.wifi8.evaluation import load_cases
    from src.wifi8.importer import Wifi8Importer, Wifi8Settings
    from src.wifi8.search import Wifi8Search

    vector_store = VectorStore()
    search = Wifi8Search.for_current(Wifi8Importer(Wifi8Settings.from_environment()), qdrant=vector_store.client,
                                     encoder=vector_store.encode, embedding_model=vector_store.model_name)
    result = acceptance.run(load_cases(args.cases), json.loads(Path(args.spec).read_text(encoding="utf-8")), search)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({r["id"]: r["status"] for r in result["rows"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
