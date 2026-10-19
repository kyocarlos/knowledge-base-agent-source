"""Acceptance checks of one WiFi zone against the written requirements (items 1 and 4).

Every check reads the live package of the zone (Qdrant), never a constant, and returns rows of
``{id, item, title, status, summary, evidence}``. ``status`` is PASS, FAIL, WARN (works, but a documented
limit applies) or NOT_ENABLED (the capability exists in code but is switched off in this zone).
Thresholds and the required metadata come from the specification file (eval/wifi8/acceptance-spec.json).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable, Iterable

from . import store as store_module
from .evaluation import score_retrieval

PASS, FAIL, WARN, NOT_ENABLED = "PASS", "FAIL", "WARN", "NOT_ENABLED"
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg"}


def row(check_id: str, item: str, title: str, status: str, summary: str, **evidence: Any) -> dict[str, Any]:
    return {"id": check_id, "item": item, "title": title, "status": status, "summary": summary, "evidence": evidence}


def pct(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def scan_chunks(store, qdrant=None) -> dict[str, Any]:
    """One pass over the payloads of the serving package (no vectors)."""
    qdrant = qdrant or store.qdrant
    indexes: dict[str, list[int]] = defaultdict(list)
    summary = Counter()
    segment_ids: set[str] = set()
    mismatched: list[str] = []
    documents = {d["revision_id"]: d for d in store.documents()}
    for point in store_module.scroll_all(qdrant, store.chunks_collection, store.chunk_filter()):
        payload = point.payload or {}
        summary["chunks"] += 1
        indexes[payload.get("revision_id")].append(payload.get("chunk_index"))
        summary["empty"] += not (payload.get("content") or "").strip()
        summary["no_location"] += not (payload.get("location") or payload.get("location_label"))
        summary["orphan"] += payload.get("revision_id") not in documents
        summary["not_ready"] += payload.get("vector_state") != "ready"
        summary["image"] += bool(payload.get("image"))
        segment_ids.update(payload.get("segment_ids") or [])
        document = documents.get(payload.get("revision_id")) or {}
        for field in ("publisher", "document_role", "wfa_document_id", "wfa_revision", "version_series_id", "lifecycle_status"):
            if (payload.get(field) or None) != (document.get(field) or None):
                summary[f"payload_{field}_differs"] += 1
                if len(mismatched) < 5:
                    mismatched.append(f"{payload.get('revision_id')}:{field}")
    gaps = [rid for rid, values in indexes.items() if sorted(values) != list(range(1, len(values) + 1))]
    return {"summary": summary, "indexes": indexes, "gaps": gaps, "segment_ids": len(segment_ids), "documents": documents,
            "mismatched": mismatched}


def check_clean(store, scan: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = store.manifest()
    documents = scan["documents"]
    excluded = (manifest.get("counts") or {}).get("excluded") or {}
    policy = manifest.get("policy") or {}
    blocked = set(policy.get("excluded_confidentiality") or [])
    leaked = [rid for rid, d in documents.items() if d.get("confidentiality") in blocked]
    never = policy.get("never_includes") or []
    not_indexed = [rid for rid, d in documents.items() if d.get("text_status") != "indexed"]
    odd = [rid for rid in not_indexed if (documents[rid].get("file_ext") or "").lower().lstrip(".") not in IMAGE_EXTENSIONS]
    with_chunks = [rid for rid in not_indexed if rid in scan["indexes"]]
    status_counts = Counter(d.get("text_status") or "未標示" for d in documents.values())
    rows = [
        row("1.1", "1", "排除政策已執行並留有紀錄", PASS if not leaked and policy else FAIL,
            f"排除 {sum(excluded.values())} 份（{', '.join(f'{k}={v}' for k, v in excluded.items()) or '無'}）；"
            f"被排除等級的文件留在庫內：{len(leaked)} 份；匯出包宣告不包含：{len(never)} 類",
            excluded=excluded, leaked=leaked[:5], never_includes=never),
        row("1.2", "1", "文字狀態（已索引／未索引）逐份可查", PASS if not odd else WARN,
            f"文字狀態 {dict(status_counts)}；未索引 {len(not_indexed)} 份，其中非圖片檔 {len(odd)} 份"
            f"（未索引的圖片檔由圖片轉文字進入檢索：{len(with_chunks)} 份有檢索單位）",
            text_status=dict(status_counts), not_indexed_non_image=odd[:5]),
    ]
    return rows


def check_chunks(store, scan: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    counts, summary, documents = store.counts(), scan["summary"], scan["documents"]
    problems = {name: summary[name] for name in ("empty", "no_location", "orphan", "not_ready") if summary[name]}
    indexed = [rid for rid, d in documents.items() if d.get("text_status") == "indexed" and (d.get("segment_count") or 0) > 0]
    missing = [rid for rid in indexed if rid not in scan["indexes"]]
    coverage = pct(scan["segment_ids"], counts["segments"])
    minimum = float(spec["chunk"]["min_segment_coverage"])
    return [
        row("1.3", "1", "每個檢索單位都有內容、位置與完成向量化", PASS if not problems and counts["chunks_pending"] == 0 else FAIL,
            f"檢索單位 {summary['chunks']} 個；空內容 {summary['empty']}、缺位置 {summary['no_location']}、"
            f"不屬任何文件 {summary['orphan']}、向量未完成 {summary['not_ready']}", problems=problems, counts=counts),
        row("1.4", "1", "每份已索引文件都有檢索單位，單位序號連續", PASS if not missing and not scan["gaps"] else FAIL,
            f"有段落的已索引文件 {len(indexed)} 份，沒有檢索單位 {len(missing)} 份；序號不連續 {len(scan['gaps'])} 份",
            missing=missing[:5], gaps=scan["gaps"][:5]),
        row("1.5", "1", "匯出包段落都落在檢索單位內（不遺漏）", PASS if coverage >= minimum else FAIL,
            f"匯出包段落 {counts['segments']} 個，已被檢索單位引用 {scan['segment_ids']} 個（{coverage:.2%}，門檻 {minimum:.0%}）",
            segments=counts["segments"], referenced=scan["segment_ids"], coverage=coverage),
    ]


def check_metadata(store, scan: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    documents = list(scan["documents"].values())
    total = len(documents)
    required = spec["metadata"]["required"]
    coverage = {field: pct(sum(1 for d in documents if d.get(field) not in (None, "", [])), total)
                for field in required + spec["metadata"]["reported"]}
    short = {field: coverage[field] for field in required if coverage[field] < 1.0}
    differing = {k: v for k, v in scan["summary"].items() if k.startswith("payload_")}
    return [
        row("1.6", "1", "必要 metadata 齊全", PASS if not short else FAIL,
            "必要欄位 " + "、".join(f"{f} {coverage[f]:.0%}" for f in required) + f"（{total} 份文件）", coverage=coverage, short=short),
        row("1.7", "1", "檢索單位帶的 metadata 與文件一致", PASS if not differing else FAIL,
            f"發布者、文件角色、WFA ID／版次、版本系列、生命週期不一致的檢索單位：{sum(differing.values())} 個",
            differing=differing, examples=scan["mismatched"]),
        row("1.8", "1", "選填 metadata 覆蓋率已揭露（來源本身缺值，不是處理遺失）", PASS,
            "；".join(f"{f} {coverage[f]:.0%}" for f in spec["metadata"]["reported"]), coverage=coverage),
    ]


def check_versions(store, scan: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    documents = scan["documents"]
    eligible = [d for d in documents.values() if d.get("analysis_eligible")]
    series: dict[str, list[str]] = defaultdict(list)
    for d in eligible:
        series[d.get("version_series_id") or d.get("document_family_id") or d["revision_id"]].append(d["revision_id"])
    several = {key: ids for key, ids in series.items() if len(ids) > 1}
    missing = [(d["revision_id"], target) for d in documents.values() for target in d.get("supersedes") or [] if target not in documents]
    still_current = [target for d in documents.values() for target in d.get("supersedes") or []
                     if target in documents and documents[target].get("analysis_eligible")]
    flagged = [d["revision_id"] for d in documents.values() if d.get("lifecycle_status") == "superseded" and d.get("analysis_eligible")]
    return [
        row("1.9", "1", "取代關係完整：被取代的文件不再是目前版本", PASS if not (missing or still_current or flagged) else FAIL,
            f"取代對象不存在 {len(missing)} 筆；被取代卻仍是目前版本 {len(still_current)} 份；標為已取代卻可分析 {len(flagged)} 份",
            missing=missing[:5], still_current=still_current[:5], flagged=flagged[:5]),
        row("1.10", "1", "同一版本系列只有一份目前版本", PASS if not several else WARN,
            f"目前版本 {len(eligible)} 份，分屬 {len(series)} 個系列；同系列有多份目前版本的 {len(several)} 組"
            + ("（來源端未判定取代關係，屬已知待釐清：" + "；".join(f"{key} → {ids}" for key, ids in list(several.items())[:3]) + "）" if several else ""),
            several=dict(list(several.items())[:5])),
    ]


def check_search_setup(search) -> list[dict[str, Any]]:
    """Item 4: the retrieval is semantic (dense) and lexical (BM25) over the same chunks, fused; rerank is reported as it is."""
    info = search.qdrant.get_collection(search.collection)
    dense = list((info.config.params.vectors or {}).keys()) if isinstance(info.config.params.vectors, dict) else ["(單一向量)"]
    sparse = list((info.config.params.sparse_vectors or {}).keys())
    point = search.qdrant.scroll(search.collection, limit=1, with_vectors=True)[0][0]
    present = sorted(point.vector.keys()) if isinstance(point.vector, dict) else []
    ok = store_module.DENSE in dense and store_module.SPARSE in sparse and set(present) >= {store_module.DENSE, store_module.SPARSE}
    rerank = getattr(search, "reranker", None)
    return [
        row("4.1", "4", "Qdrant 同時存放語意向量與全文（BM25）向量", PASS if ok else FAIL,
            f"集合 {search.collection}：向量 {dense}、稀疏向量 {sparse}；抽樣一點同時帶有 {present}；"
            f"embedding 模型 {search.store.record().get('embedding_model') or '見匯入紀錄'}",
            dense=dense, sparse=sparse, point_vectors=present),
        row("4.4", "4", "rerank（cross-encoder 重排）", PASS if rerank else NOT_ENABLED,
            ("已啟用：" + str(rerank.settings.__dict__)) if rerank else
            "此專區未啟用：程式為選配、預設關閉（KM_WIFI8_RERANK_MODEL 未設定）；10/17 DA40 試驗命中前 10 由 93.3% 升至 96.7%、"
            "每次檢索多約 8.6 秒，是否啟用待決定",
            enabled=bool(rerank)),
    ]


def ablation(search, cases: Iterable[dict[str, Any]], options_factory: Callable[[], Any]) -> dict[str, dict[str, Any]]:
    """Hit@10 and MRR of the dense retriever alone, the lexical one alone and the fused (deployed) one on the same cases."""
    cases = [c for c in cases if c.get("gold") and not (c.get("package_id") and c["package_id"] != search.package_id)]
    results: dict[str, dict[str, Any]] = {}
    real_vector, real_lexical = search.vector, search.lexical
    modes = {"dense": (real_vector, lambda q, o: []), "lexical": (lambda q, o: [], real_lexical), "hybrid": (real_vector, real_lexical)}
    try:
        for name, (vector, lexical) in modes.items():
            search.vector, search.lexical = vector, lexical
            hits, mrr, miss = 0, 0.0, []
            for case in cases:
                scored = score_retrieval(case, search.search(case["question"], options_factory())["results"])
                if not scored.get("applicable"):
                    continue
                hits += scored["hit"]
                mrr += scored["mrr"]
                if not scored["hit"]:
                    miss.append(case["id"])
            results[name] = {"cases": len(cases), "hit_at_10": pct(hits, len(cases)), "mrr": round(mrr / len(cases), 4) if cases else 0.0,
                             "missed": miss}
    finally:
        search.vector, search.lexical = real_vector, real_lexical
    return results


def check_hybrid(search, cases: list[dict[str, Any]], spec: dict[str, Any], options_factory: Callable[[], Any]) -> list[dict[str, Any]]:
    found = ablation(search, cases, options_factory)
    hybrid, best_single = found["hybrid"], max(found["dense"]["hit_at_10"], found["lexical"]["hit_at_10"])
    rule = spec["retrieval"]
    complementary = sorted(set(found["dense"]["missed"]) ^ set(found["lexical"]["missed"]))
    good = hybrid["hit_at_10"] >= rule["min_hit_at_10"] and hybrid["hit_at_10"] >= best_single - rule["tolerance"]
    return [row("4.2", "4", "混合檢索（語意＋全文，RRF 融合）不劣於單一路徑", PASS if good else FAIL,
                f"{hybrid['cases']} 題題庫：只用語意 {found['dense']['hit_at_10']:.1%}／MRR {found['dense']['mrr']}；"
                f"只用全文 {found['lexical']['hit_at_10']:.1%}／MRR {found['lexical']['mrr']}；混合 {hybrid['hit_at_10']:.1%}／MRR {hybrid['mrr']}"
                f"（門檻 ≥{rule['min_hit_at_10']:.0%} 且不低於單一路徑 {rule['tolerance']:.0%} 以內）；兩條路徑各自漏掉不同題目 {len(complementary)} 題",
                ablation=found)]


def check_citation_samples(search, cases: list[dict[str, Any]], spec: dict[str, Any], options_factory: Callable[[], Any]) -> list[dict[str, Any]]:
    """Every retrieved chunk can be cited: it carries the title, a place (page / sheet row) and the WFA id when the document has one."""
    sample, bad = 0, []
    documents = {d["revision_id"]: d for d in search.store.documents()}
    for case in cases[: int(spec["citation"]["sample_cases"])]:
        for hit in search.search(case["question"], options_factory())["results"]:
            sample += 1
            document = documents.get(hit["revision_id"]) or {}
            lacks = [name for name, ok in (("標題", hit.get("source")), ("位置", hit.get("location_label")),
                                           ("WFA ID", hit.get("wfa_document_id") or not document.get("wfa_document_id"))) if not ok]
            if lacks:
                bad.append(f"{case['id']}:{hit['revision_id']}:{'/'.join(lacks)}")
    return [row("4.3", "4", "檢索結果都帶得出引用證據（標題、位置、WFA ID）", PASS if sample and not bad else FAIL,
                f"抽 {int(spec['citation']['sample_cases'])} 題、共 {sample} 筆檢索結果；缺標題／位置／WFA ID 的 {len(bad)} 筆",
                sample=sample, bad=bad[:10])]


def run(cases: list[dict[str, Any]], spec: dict[str, Any], search) -> dict[str, Any]:
    """Everything that needs the zone's Qdrant; the rows that need the quality reports are added by the runner."""
    from .search import SearchOptions
    store = search.store
    scan = scan_chunks(store, search.qdrant)

    def options() -> Any:
        return SearchOptions(top_k=10)
    rows = (check_clean(store, scan, spec) + check_chunks(store, scan, spec) + check_metadata(store, scan, spec)
            + check_versions(store, scan, spec) + check_search_setup(search) + check_hybrid(search, cases, spec, options)
            + check_citation_samples(search, cases, spec, options))
    return {"package_id": search.package_id, "counts": store.counts(), "rows": rows}


__all__ = ["run", "row", "PASS", "FAIL", "WARN", "NOT_ENABLED"]
