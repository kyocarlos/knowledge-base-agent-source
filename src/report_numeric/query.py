"""Fixed, read-only query templates over km_test. Every value comes back with the document, sheet and cell it was read from;
the LLM never writes SQL. Parameters are matched against allow-lists or bound as values."""
from __future__ import annotations

import re
from typing import Any

METRICS = {"throughput", "rssi", "pass_count", "fail_count", "total_count", "pass_rate", "latency_rtt", "rsrp", "rsrq", "sinr", "udp_lost_ratio"}
DIRECTIONS = {"dl", "ul", "total"}
REPORT_TYPES = {"wifi_throughput", "wifi_rvr", "cellular_throughput"}
BANDS = re.compile(r"^(2\.4GHz|5GHz|6GHz|n\d+\w*)$")
MAX_ROWS = 200
DEFAULT_ROLES = ("CSIT_ENGINEER",)


class QueryError(ValueError):
    """A parameter outside the allow-list: reported back to the model as an error, never executed."""


def _rows(conn, sql: str, params: dict) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _check(value, allowed, name):
    if value is not None and value not in allowed:
        raise QueryError(f"{name} 必須是 {sorted(allowed)} 之一，收到 {value!r}")
    return value


def _limit(n: int | None, default: int = 60) -> int:
    return max(1, min(int(n or default), MAX_ROWS))


def resolve_products(conn, text: str, roles=DEFAULT_ROLES) -> list[dict]:
    """Exact (case-insensitive) product id or model first; otherwise products whose id or model contains the text."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        return []
    base = """SELECT DISTINCT product_id, dut_model FROM km_test.test_run WHERE access_roles && %(roles)s AND publish_status = 'published' AND """
    exact = _rows(conn, base + "(lower(product_id) = lower(%(t)s) OR lower(dut_model) = lower(%(t)s))", {"t": t, "roles": list(roles)})
    if exact:
        return exact
    like = "%" + t.replace("%", "").replace("_", r"\_") + "%"
    return _rows(conn, base + "(product_id ILIKE %(l)s OR dut_model ILIKE %(l)s)", {"l": like, "roles": list(roles)})


def _product_ids(conn, names, roles) -> list[str]:
    out = []
    for name in names:
        found = resolve_products(conn, name, roles)
        if not found:
            raise QueryError(f"知識庫沒有找到設備「{name}」")
        if len(found) > 1 and len({f["product_id"] for f in found}) > 1:
            raise QueryError(f"「{name}」符合多個設備：{', '.join(sorted({f['product_id'] for f in found}))}，請指定完整型號")
        out.append(found[0]["product_id"])
    return out


def list_products(conn, roles=DEFAULT_ROLES) -> list[dict]:
    return _rows(conn, """SELECT product_id, dut_model, report_type, technology, npi_stage, firmware_version, hardware_version, chipset_vendor, test_date, overall_result,
                                 document_id, quality_status FROM km_test.test_run WHERE access_roles && %(roles)s AND publish_status = 'published'
                          ORDER BY product_id, report_type""", {"roles": list(roles)})


def get_run_info(conn, product: str, roles=DEFAULT_ROLES) -> list[dict]:
    pid = _product_ids(conn, [product], roles)[0]
    runs = _rows(conn, """SELECT test_run_id, product_id, dut_model, report_type, document_id, document_version, npi_stage, firmware_version, hardware_version, chipset_vendor,
                                 ethernet_type, test_date, overall_result, quality_status, formula_error_count, approval_basis
                          FROM km_test.test_run WHERE product_id = %(p)s AND access_roles && %(roles)s ORDER BY report_type""", {"p": pid, "roles": list(roles)})
    for r in runs:
        r["conditions"] = _rows(conn, "SELECT name, value, text_value, unit, band, bandwidth_mhz, source_sheet, source_cell_range FROM km_test.test_condition WHERE test_run_id = %(r)s",
                                {"r": r["test_run_id"]})
    return runs


_MEASURE_COLS = """m.metric_name, m.value, m.unit, m.value_basis, m.band, m.bandwidth_mhz, m.channel, m.center_freq_mhz, m.direction, m.direction_source_label, m.attenuation_db,
    m.angle_deg, m.traffic_mode, m.protocol, m.statistic, m.sample_index, m.time_slot, m.test_case_name, r.product_id, r.dut_model, r.report_type, r.document_id,
    r.quality_status, m.source_sheet, m.source_cell_range"""


def get_measurements(conn, product: str, metric: str | None = None, band: str | None = None, bandwidth_mhz: int | None = None, channel: int | None = None,
                     direction: str | None = None, attenuation_db: float | None = None, angle_deg: float | None = None, protocol: str | None = None,
                     statistic: str | None = None, report_type: str | None = None, limit: int | None = None, roles=DEFAULT_ROLES) -> list[dict]:
    _check(metric, METRICS, "metric"); _check(direction, DIRECTIONS, "direction"); _check(report_type, REPORT_TYPES, "report_type")
    _check(protocol, {"tcp", "udp"}, "protocol"); _check(statistic, {"value", "peak", "average", "min", "max"}, "statistic")
    if band is not None and not BANDS.match(band):
        raise QueryError(f"band 格式不合法：{band!r}")
    pid = _product_ids(conn, [product], roles)[0]
    return _rows(conn, f"""SELECT {_MEASURE_COLS} FROM km_test.test_measurement m JOIN km_test.test_run r USING (test_run_id)
        WHERE r.product_id = %(p)s AND r.access_roles && %(roles)s AND r.publish_status = 'published'
          AND (%(metric)s::text IS NULL OR m.metric_name = %(metric)s) AND (%(band)s::text IS NULL OR m.band = %(band)s)
          AND (%(bw)s::int IS NULL OR m.bandwidth_mhz = %(bw)s) AND (%(ch)s::int IS NULL OR m.channel = %(ch)s) AND (%(dir)s::text IS NULL OR m.direction = %(dir)s)
          AND (%(att)s::float IS NULL OR m.attenuation_db = %(att)s) AND (%(ang)s::float IS NULL OR m.angle_deg = %(ang)s)
          AND (%(proto)s::text IS NULL OR m.protocol = %(proto)s) AND (%(stat)s::text IS NULL OR m.statistic = %(stat)s OR (%(stat)s = 'value' AND m.statistic IS NULL)) AND (%(rt)s::text IS NULL OR r.report_type = %(rt)s)
        ORDER BY r.report_type, m.band, m.bandwidth_mhz, m.channel, m.attenuation_db NULLS FIRST, m.angle_deg NULLS FIRST, m.metric_name, m.direction
        LIMIT %(lim)s""",
                 {"p": pid, "roles": list(roles), "metric": metric, "band": band, "bw": bandwidth_mhz, "ch": channel, "dir": direction, "att": attenuation_db, "ang": angle_deg,
                  "proto": protocol, "stat": statistic, "rt": report_type, "lim": _limit(limit)})


def count_measurements(conn, product: str, metric: str | None = None, band: str | None = None, bandwidth_mhz: int | None = None, channel: int | None = None,
                       direction: str | None = None, attenuation_db: float | None = None, angle_deg: float | None = None, protocol: str | None = None,
                       statistic: str | None = None, report_type: str | None = None, roles=DEFAULT_ROLES) -> dict:
    """How many rows match, per report type, so a truncated or mixed result is visible to the caller."""
    pid = _product_ids(conn, [product], roles)[0]
    rows = _rows(conn, """SELECT r.report_type, count(*) AS n FROM km_test.test_measurement m JOIN km_test.test_run r USING (test_run_id)
        WHERE r.product_id = %(p)s AND r.access_roles && %(roles)s AND r.publish_status = 'published'
          AND (%(metric)s::text IS NULL OR m.metric_name = %(metric)s) AND (%(band)s::text IS NULL OR m.band = %(band)s)
          AND (%(bw)s::int IS NULL OR m.bandwidth_mhz = %(bw)s) AND (%(ch)s::int IS NULL OR m.channel = %(ch)s) AND (%(dir)s::text IS NULL OR m.direction = %(dir)s)
          AND (%(att)s::float IS NULL OR m.attenuation_db = %(att)s) AND (%(ang)s::float IS NULL OR m.angle_deg = %(ang)s)
          AND (%(proto)s::text IS NULL OR m.protocol = %(proto)s) AND (%(stat)s::text IS NULL OR m.statistic = %(stat)s OR (%(stat)s = 'value' AND m.statistic IS NULL)) AND (%(rt)s::text IS NULL OR r.report_type = %(rt)s)
        GROUP BY r.report_type ORDER BY r.report_type""",
                 {"p": pid, "roles": list(roles), "metric": metric, "band": band, "bw": bandwidth_mhz, "ch": channel, "dir": direction, "att": attenuation_db, "ang": angle_deg,
                  "proto": protocol, "stat": statistic, "rt": report_type})
    return {r["report_type"]: r["n"] for r in rows}


def compare_metric(conn, products: list[str], metric: str, band: str, bandwidth_mhz: int, direction: str | None = None, channel: int | None = None,
                   report_type: str | None = None, attenuation_db: float | None = None, angle_deg: float | None = None, protocol: str | None = None,
                   roles=DEFAULT_ROLES) -> dict:
    """Per-product statistics for one fully specified condition. Band and bandwidth are required: different conditions are never mixed."""
    _check(metric, METRICS, "metric"); _check(direction, DIRECTIONS, "direction"); _check(report_type, REPORT_TYPES, "report_type")
    if not products or len(products) > 10:
        raise QueryError("products 需要 1 到 10 個設備")
    if not BANDS.match(str(band or "")) or not bandwidth_mhz:
        raise QueryError("比較必須指定 band 與 bandwidth_mhz")
    if metric in ("throughput", "rssi") and report_type is None:
        raise QueryError("Throughput 與 RvR 的量測條件不同，比較必須指定 report_type（wifi_throughput 或 wifi_rvr）")
    if report_type == "wifi_rvr" and metric in ("throughput", "rssi") and attenuation_db is None:
        raise QueryError("RvR 的量測隨衰減變化，比較必須指定 attenuation_db")
    pids = _product_ids(conn, products, roles)
    rows = _rows(conn, """SELECT r.product_id, r.dut_model, r.report_type, r.document_id, r.quality_status, m.unit, count(*) AS n, round(avg(m.value)::numeric, 4)::float AS average,
                                 min(m.value) AS minimum, max(m.value) AS maximum, array_agg(DISTINCT m.source_sheet) AS sheets
        FROM km_test.test_measurement m JOIN km_test.test_run r USING (test_run_id)
        WHERE r.product_id = ANY(%(p)s) AND r.access_roles && %(roles)s AND m.metric_name = %(metric)s AND m.band = %(band)s AND m.bandwidth_mhz = %(bw)s
          AND (%(dir)s::text IS NULL OR m.direction = %(dir)s) AND (%(ch)s::int IS NULL OR m.channel = %(ch)s) AND (%(rt)s::text IS NULL OR r.report_type = %(rt)s)
          AND (%(att)s::float IS NULL OR m.attenuation_db = %(att)s) AND (%(ang)s::float IS NULL OR m.angle_deg = %(ang)s) AND (%(proto)s::text IS NULL OR m.protocol = %(proto)s)
        GROUP BY r.product_id, r.dut_model, r.report_type, r.document_id, r.quality_status, m.unit ORDER BY r.product_id, r.report_type""",
                 {"p": pids, "roles": list(roles), "metric": metric, "band": band, "bw": bandwidth_mhz, "dir": direction, "ch": channel, "rt": report_type, "att": attenuation_db,
                  "ang": angle_deg, "proto": protocol})
    missing = sorted(set(pids) - {r["product_id"] for r in rows})
    units = {r["unit"] for r in rows}
    return {"condition": {"metric": metric, "band": band, "bandwidth_mhz": bandwidth_mhz, "direction": direction, "channel": channel, "report_type": report_type,
                          "attenuation_db": attenuation_db, "angle_deg": angle_deg, "protocol": protocol},
            "rows": rows, "products_without_data": missing, "comparable": len(units) <= 1,
            "note": "各設備數值取自同一條件；higher_is_better 尚未定義，不得用『較佳／較差』描述。" + ("" if len(units) <= 1 else " 單位不一致，不可比較。")}


def list_results(conn, product: str, band: str | None = None, bandwidth_mhz: int | None = None, result: str | None = None, report_type: str | None = None,
                 limit: int | None = None, roles=DEFAULT_ROLES) -> list[dict]:
    _check(result, {"pass", "fail", "n/a"}, "result"); _check(report_type, REPORT_TYPES, "report_type")
    pid = _product_ids(conn, [product], roles)[0]
    return _rows(conn, """SELECT x.item_label, x.result, x.criteria_value, x.criteria_unit, x.band, x.bandwidth_mhz, x.channel, r.product_id, r.dut_model, r.report_type, r.document_id,
                                 r.quality_status, x.source_sheet, x.source_cell_range
        FROM km_test.test_item_result x JOIN km_test.test_run r USING (test_run_id)
        WHERE r.product_id = %(p)s AND r.access_roles && %(roles)s AND (%(band)s::text IS NULL OR x.band = %(band)s) AND (%(bw)s::int IS NULL OR x.bandwidth_mhz = %(bw)s)
          AND (%(res)s::text IS NULL OR x.result = %(res)s) AND (%(rt)s::text IS NULL OR r.report_type = %(rt)s)
        ORDER BY r.report_type, x.band, x.bandwidth_mhz, x.channel NULLS FIRST, x.item_label LIMIT %(lim)s""",
                 {"p": pid, "roles": list(roles), "band": band, "bw": bandwidth_mhz, "res": result, "rt": report_type, "lim": _limit(limit, 100)})


def get_criteria(conn, product: str, band: str | None = None, bandwidth_mhz: int | None = None, report_type: str | None = None, roles=DEFAULT_ROLES) -> list[dict]:
    _check(report_type, REPORT_TYPES, "report_type")
    pid = _product_ids(conn, [product], roles)[0]
    return _rows(conn, """SELECT c.band, c.bandwidth_mhz, c.spatial_stream, c.wireless_mode, c.attenuation_range, c.reference_rate_mbps, c.criteria_value, c.criteria_unit,
                                 r.product_id, r.dut_model, r.report_type, r.document_id, c.source_sheet, c.source_cell_range
        FROM km_test.criteria_reference c JOIN km_test.test_run r USING (test_run_id)
        WHERE r.product_id = %(p)s AND r.access_roles && %(roles)s AND (%(band)s::text IS NULL OR c.band = %(band)s) AND (%(bw)s::int IS NULL OR c.bandwidth_mhz = %(bw)s)
          AND (%(rt)s::text IS NULL OR r.report_type = %(rt)s) ORDER BY r.report_type, c.band, c.bandwidth_mhz, c.attenuation_range NULLS FIRST LIMIT 120""",
                 {"p": pid, "roles": list(roles), "band": band, "bw": bandwidth_mhz, "rt": report_type})
