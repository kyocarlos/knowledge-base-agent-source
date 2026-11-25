"""Report CSIT documents that KM holds more than once with identical content (same SHA256). Read only.

Why this exists: CSIT is the authority on what a document is. KM identifies a document by (source type, source entity, document id, version) and, by contract
(v1.4.1 section 3.1), never merges records because their bytes are equal: the same file may legitimately be attached to two different applications.
So two CSIT records with equal content are ingested as two documents. This report only makes that visible. It never blocks, merges, deletes or
changes anything, and it does not touch the intake path.

It reads the three job tables (v1 Test Report jobs, v1 document-library jobs, v2 jobs) in one read-only session and groups the live jobs by SHA256.
A job is live when it is not Failed or Deleted and, for v2, its index is not Superseded (a replaced version holding the same bytes is not a duplicate).
"""
import argparse
import json
import logging
import sys
from collections import defaultdict

LIVE_EXCLUDED = ("Failed", "Deleted")
LOG = logging.getLogger("km.csit.duplicate_content")

# One SELECT per lane, all returning the same columns.
LANE_SQL = {
    "v1-testreport": """SELECT 'v1-testreport' AS lane, job_id::text AS km_job_id, 'TestReport' AS source_type, document_id::text AS source_entity_id,
                               document_id::text AS document_id, version::int AS version, file_name, size_bytes::bigint AS size_bytes,
                               content_sha256 AS sha256, status, NULL::text AS index_state, created_at
                        FROM km_csit_ingestion_jobs WHERE content_sha256 IS NOT NULL AND status NOT IN ('Failed','Deleted')""",
    "v1-doclib": """SELECT 'v1-doclib' AS lane, km_job_id::text AS km_job_id, 'DocumentLibraryFile' AS source_type, document_file_id::text AS source_entity_id,
                           document_file_id::text AS document_id, NULL::int AS version, original_file_name AS file_name, file_size_bytes::bigint AS size_bytes,
                           expected_sha256 AS sha256, status, NULL::text AS index_state, created_at
                    FROM km_csit_doclib_jobs WHERE expected_sha256 IS NOT NULL AND status NOT IN ('Failed','Deleted')""",
    "v2": """SELECT 'v2' AS lane, km_job_id::text AS km_job_id, source_type, source_entity_id::text AS source_entity_id, document_id::text AS document_id,
                    version::int AS version, original_file_name AS file_name, file_size_bytes::bigint AS size_bytes, expected_sha256 AS sha256,
                    status, index_state, created_at
             FROM km_csit_v2_jobs WHERE expected_sha256 IS NOT NULL AND status NOT IN ('Failed','Deleted')
              AND COALESCE(index_state,'') <> 'Superseded'""",
}


# The same three lanes, narrowed to one SHA256 (used at intake time).
PEER_SQL = "SELECT * FROM (" + " UNION ALL ".join(LANE_SQL.values()) + ") lanes WHERE lower(sha256) = %s"


def _identity(row):
    """What makes two rows the same CSIT document: a retry of one document must not count as a second copy."""
    return (row["source_type"], str(row["source_entity_id"]), str(row["document_id"]), row.get("version"))


def group_duplicates(rows):
    """Pure grouping. rows: dicts with lane, km_job_id, source_type, source_entity_id, document_id, version, file_name, size_bytes, sha256, status, created_at.
    Returns groups of two or more distinct CSIT documents with the same SHA256, largest group first."""
    by_sha = defaultdict(dict)
    for r in rows:
        sha = str(r.get("sha256") or "").strip().lower()
        if not sha or r.get("status") in LIVE_EXCLUDED or r.get("index_state") == "Superseded":
            continue
        by_sha[sha].setdefault(_identity(r), r)     # keep the first row per distinct document
    groups = []
    for sha, docs in by_sha.items():
        if len(docs) < 2:
            continue
        members = sorted(docs.values(), key=lambda r: (str(r.get("created_at")), str(r.get("km_job_id"))))
        sizes = {m.get("size_bytes") for m in members if m.get("size_bytes") is not None}
        groups.append({
            "sha256": sha,
            "count": len(members),
            "size_mismatch": len(sizes) > 1,     # equal SHA256 with different sizes should be impossible: report it, do not hide it
            "source_types": sorted({m["source_type"] for m in members}),
            "members": [{k: (str(m.get(k)) if m.get(k) is not None else None) for k in
                         ("lane", "km_job_id", "source_type", "source_entity_id", "document_id", "version", "file_name", "size_bytes", "status", "created_at")}
                        for m in members],
        })
    groups.sort(key=lambda g: (-g["count"], g["sha256"]))
    return groups


def fetch_rows(conn):
    """All live jobs of the three lanes. conn must already be a read-only session."""
    rows = []
    for sql in LANE_SQL.values():
        rows.extend(conn.execute(sql).fetchall())
    return rows


def warn_if_duplicate(connect, sha256, km_job_id, log=LOG):
    """Log one warning when a live job of another CSIT document has the same bytes as km_job_id. Read only; never blocks, merges or changes anything.
    connect: a callable returning a new connection (the intake transaction must already be committed)."""
    sha = str(sha256 or "").strip().lower()
    if not sha:
        return []
    with connect() as c:
        c.execute("SET TRANSACTION READ ONLY")      # first statement of this transaction: the server refuses any write
        groups = group_duplicates(c.execute(PEER_SQL, (sha,)).fetchall())
    mine = [g for g in groups if any(m["km_job_id"] == km_job_id for m in g["members"])]
    for g in mine:
        others = [m["km_job_id"] for m in g["members"] if m["km_job_id"] != km_job_id]
        log.warning("duplicate content: %s has the same SHA256 (%s...) as %d other CSIT document(s): %s; kept as independent documents",
                    km_job_id, sha[:12], len(others), ", ".join(others))
    return mine


def render_text(groups):
    if not groups:
        return "沒有內容相同的重複文件。"
    out = ["內容相同(SHA256 相同)的文件共 %d 組;KM 把它們當成各自獨立的文件,沒有合併、也沒有阻擋。" % len(groups)]
    for i, g in enumerate(groups, 1):
        out.append("")
        out.append("第 %d 組:%d 份,SHA256 %s…%s" % (i, g["count"], g["sha256"][:12], "  ⚠ 檔案大小不一致" if g["size_mismatch"] else ""))
        for m in g["members"]:
            out.append("  - %s | %s | %s | 來源 %s:%s | 文件 %s%s | %s" % (
                m["km_job_id"], m["lane"], m["status"], m["source_type"], str(m["source_entity_id"])[:8], str(m["document_id"])[:8],
                (" v" + m["version"]) if m.get("version") else "", m["file_name"]))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="List documents KM holds more than once with identical content (read only).")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args(argv)
    import psycopg
    from psycopg.rows import dict_row
    from .config import Settings
    conn = psycopg.connect(Settings.from_env().db_url, autocommit=True, row_factory=dict_row)
    conn.execute("SET default_transaction_read_only = on")      # enforced by the server: this command cannot write even by mistake
    try:
        groups = group_duplicates(fetch_rows(conn))
    finally:
        conn.close()
    print(json.dumps({"groups": groups}, ensure_ascii=False, indent=2) if args.json else render_text(groups))
    return 0


if __name__ == "__main__":
    sys.exit(main())
