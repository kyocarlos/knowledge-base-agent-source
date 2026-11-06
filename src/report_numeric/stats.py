"""Statistics over the measurements of any report type, computed by the database with one fixed query.

Every measurement row carries the same condition columns (band, bandwidth, direction, attenuation ...), so one query serves every report type; what differs
per type is which conditions must never be averaged together. SERIES lists them: they are always grouped on, so a mean never mixes 5 GHz with 2.4 GHz,
uplink with downlink, or one attenuation point with another. A report type that is not listed (a new kind of report CSIT starts sending) is grouped on every
condition: more rows, never a mixed number. Optional dimensions (channel ...) are grouped on only when asked for.

Everything the question can name (report types, products, metrics, condition values, test cases) is read from the database by `catalog`, so a new report
shows up without a code change. Identifiers in the SQL come from the constants below, values are bound parameters.
"""
from __future__ import annotations

import re
from typing import Any

from .query import BANDS, DEFAULT_ROLES, DIRECTIONS, QueryError, _check, _product_ids, _rows

CONDITIONS = ("band", "center_freq_mhz", "bandwidth_mhz", "channel", "direction", "attenuation_db", "angle_deg", "traffic_mode", "protocol", "statistic", "time_slot")
# test_case_id is in the series where it is the only place a condition is recorded (the handover mode and count)
SERIES = {
    "wifi_throughput": ("band", "bandwidth_mhz", "direction", "protocol"),
    "wifi_rvr": ("band", "bandwidth_mhz", "direction", "attenuation_db", "angle_deg"),
    "cellular_throughput": ("test_case_id", "band", "center_freq_mhz", "bandwidth_mhz", "time_slot", "direction", "protocol", "traffic_mode", "statistic"),
    "cellular_handover": ("test_case_id",),
}
STRICT = ("test_case_id",) + CONDITIONS          # a report type nobody has described yet
CATEGORICAL = {"direction": DIRECTIONS, "traffic_mode": {"unidirectional", "bidirectional"}, "protocol": {"tcp", "udp"}, "statistic": {"value", "peak", "average", "min", "max"}}
INTEGERS = ("bandwidth_mhz", "channel", "center_freq_mhz")
FLOATS = ("attenuation_db", "angle_deg")
NAME = re.compile(r"^[A-Za-z0-9_]{1,60}$")
CASE = re.compile(r"^[\w:.@+#*, \-/()]{1,160}$")        # what a test case id holds: band@frequency, a time slot such as DDDSU+UDSUU (4:4), #case4
MAX_ROWS = 240
MAX_CASES = 60


def series_of(report_type: str) -> tuple[str, ...]:
    return SERIES.get(report_type, STRICT)


def optional_dims(report_type: str) -> list[str]:
    return [d for d in CONDITIONS if d not in series_of(report_type)]


def catalog(conn, roles=DEFAULT_ROLES) -> dict:
    """What can be asked: per report type its products, metrics (with unit), the values each condition takes, and (where it matters) the test cases."""
    roles = list(roles)
    out: dict[str, dict] = {}
    # the CSIT names are read through to_jsonb so a database that has not got the name columns yet (nothing ingested since they were added) still answers
    for r in _rows(conn, """SELECT report_type, product_id, dut_model, document_id, project_id, to_jsonb(r) ->> 'project_name' AS project_name, to_jsonb(r) ->> 'case_name' AS case_name,
                                   to_jsonb(r) ->> 'task_name' AS task_name FROM km_test.test_run r WHERE access_roles && %(roles)s AND publish_status = 'published'
                            ORDER BY report_type, product_id""", {"roles": roles}):
        t = out.setdefault(r["report_type"], {"products": [], "metrics": [], "dims": {}, "cases": [], "series": list(series_of(r["report_type"]))})
        t["products"].append({"id": r["product_id"], "model": r["dut_model"], "document_id": r["document_id"], "project_code": r["project_id"], "project_name": r["project_name"],
                              "case_name": r["case_name"], "task_name": r["task_name"]})
    if not out:
        return out
    arrays = ", ".join(f"array_agg(DISTINCT m.{d}) FILTER (WHERE m.{d} IS NOT NULL) AS {d}" for d in CONDITIONS)
    for r in _rows(conn, f"""SELECT r.report_type, m.metric_name, m.unit, md.description, {arrays}, min(m.sample_index) AS first_no, max(m.sample_index) AS last_no
        FROM km_test.test_measurement m JOIN km_test.test_run r USING (test_run_id) LEFT JOIN km_test.metric_dictionary md ON md.metric_name = m.metric_name
        WHERE r.access_roles && %(roles)s AND r.publish_status = 'published' GROUP BY r.report_type, m.metric_name, m.unit, md.description""", {"roles": roles}):
        t = out[r["report_type"]]
        t["metrics"].append({"name": r["metric_name"], "unit": r["unit"], "description": r["description"], "numbered": r["last_no"] is not None})
        for d in CONDITIONS:
            if r.get(d):
                t["dims"][d] = sorted(set(t["dims"].get(d, [])) | set(r[d]))
    for r in _rows(conn, """SELECT r.report_type, m.test_case_id, max(m.test_case_name) AS name FROM km_test.test_measurement m JOIN km_test.test_run r USING (test_run_id)
        WHERE r.access_roles && %(roles)s AND r.publish_status = 'published' GROUP BY r.report_type, m.test_case_id ORDER BY r.report_type, m.test_case_id""", {"roles": roles}):
        t = out[r["report_type"]]
        if "test_case_id" in t["series"] and len(t["cases"]) < MAX_CASES:
            t["cases"].append({"id": r["test_case_id"], "name": r["name"]})
    return out


def _clean_filters(filters: dict | None) -> dict:
    f = dict(filters or {})
    unknown = set(f) - set(CONDITIONS) - {"test_cases"}
    if unknown:
        raise QueryError(f"不支援的篩選條件：{sorted(unknown)}")
    if f.get("band") is not None and not BANDS.match(str(f["band"])):
        raise QueryError(f"band 格式不合法：{f['band']!r}")
    for key, allowed in CATEGORICAL.items():
        _check(f.get(key), allowed, key)
    for key in INTEGERS:
        if f.get(key) is not None:
            f[key] = int(f[key])
            if not 0 <= f[key] <= 100000:
                raise QueryError(f"{key} 超出範圍")
    for key in FLOATS:
        if f.get(key) is not None:
            f[key] = float(f[key])
            if not -1000 <= f[key] <= 1000:
                raise QueryError(f"{key} 超出範圍")
    cases = [str(c) for c in f.get("test_cases") or []]
    if len(cases) > 12 or not all(CASE.match(c) for c in cases):
        raise QueryError("test_cases 最多 12 個，且必須是報告中的測試項目代碼")
    f["test_cases"] = cases or None
    return f


def measurement_stats(conn, report_type: str, products: list[str] | None = None, metrics: list[str] | None = None, filters: dict | None = None,
                      group_by: list[str] | None = None, from_no: int | None = None, to_no: int | None = None, roles=DEFAULT_ROLES) -> dict:
    """Count, sum, mean, min, max, median and 95th percentile of each metric, one row per product, document, metric and series (see SERIES) of one report type,
    optionally split further on `group_by` and limited to repetitions from_no..to_no. Returns {"rows", "truncated", "series", "group_by"}."""
    if not NAME.match(str(report_type or "")):
        raise QueryError("必須指定 report_type")
    metrics = [m for m in metrics or []]
    if len(metrics) > 12 or not all(NAME.match(m) for m in metrics):
        raise QueryError("metrics 最多 12 個，且必須是指標名稱")
    if len(products or []) > 5:
        raise QueryError("一次最多 5 個設備")
    extra = [d for d in group_by or [] if d in optional_dims(report_type)]
    if set(group_by or []) - set(extra):
        raise QueryError(f"group_by 只能是 {optional_dims(report_type)}")
    for bound in (from_no, to_no):
        if bound is not None and not 1 <= int(bound) <= 10000:
            raise QueryError("from_no / to_no 必須在 1 到 10000 之間")
    f = _clean_filters(filters)
    pids = _product_ids(conn, products, roles) if products else None
    series = [d for d in series_of(report_type)] + extra
    cols = ["r.product_id", "r.dut_model", "r.report_type", "r.document_id", "m.metric_name", "m.unit", "m.value_basis"] + [f"m.{d}" for d in series]
    if "test_case_id" in series:
        cols.append("m.test_case_name")
    # cases whose frequency could not be read (template leftovers) come last, so a result cut at MAX_ROWS loses them rather than the real ones
    order = cols[:7] + (["(m.center_freq_mhz IS NULL)"] if "center_freq_mhz" in series else []) + cols[7:]
    where = [f"(m.{d} = %({d})s)" for d in CONDITIONS if d in f and f[d] is not None and d != "statistic"]
    if f.get("statistic") is not None:
        where.append("(m.statistic = %(statistic)s OR (%(statistic)s::text = 'value' AND m.statistic IS NULL))")
    sql = f"""SELECT {', '.join(cols)}, count(*) AS n, sum(m.value) AS total, round(avg(m.value)::numeric, 4)::float AS average, min(m.value) AS minimum, max(m.value) AS maximum,
                     percentile_cont(0.5) WITHIN GROUP (ORDER BY m.value) AS median, percentile_cont(0.95) WITHIN GROUP (ORDER BY m.value) AS p95,
                     min(m.sample_index) AS first_no, max(m.sample_index) AS last_no
        FROM km_test.test_measurement m JOIN km_test.test_run r USING (test_run_id)
        WHERE r.report_type = %(rt)s AND r.access_roles && %(roles)s AND r.publish_status = 'published'
          AND (%(p)s::text[] IS NULL OR r.product_id = ANY(%(p)s)) AND (%(metrics)s::text[] IS NULL OR m.metric_name = ANY(%(metrics)s))
          AND (%(cases)s::text[] IS NULL OR m.test_case_id = ANY(%(cases)s))
          AND (%(lo)s::int IS NULL OR m.sample_index >= %(lo)s) AND (%(hi)s::int IS NULL OR m.sample_index <= %(hi)s)
          {''.join(' AND ' + w for w in where)}
        GROUP BY {', '.join(cols)}
        ORDER BY {', '.join(order)} LIMIT %(lim)s"""
    params: dict[str, Any] = {"rt": report_type, "roles": list(roles), "p": pids, "metrics": metrics or None, "cases": f["test_cases"], "lo": from_no, "hi": to_no, "lim": MAX_ROWS + 1}
    params.update({d: f[d] for d in CONDITIONS if f.get(d) is not None})
    rows = _rows(conn, sql, params)
    return {"rows": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS, "series": list(series_of(report_type)), "group_by": extra}
