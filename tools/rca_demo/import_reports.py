"""Import a folder of SIT test-report workbooks into km_test using KM's own parser and writer (the same code the report import uses).

    python -m tools.rca_demo.import_reports <folder> --database-url postgresql://...   [--replace]

Prints one line per file (type, product, firmware, counts) and a summary. A file whose name matches no registered template is skipped and listed.
"""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import psycopg
from src.report_numeric import parser,timescale

def import_folder(conn,folder,*,replace=False,only=None):
    rows=[]
    for path in sorted(Path(folder).glob("*.xlsx")):
        if only and only not in path.name:continue
        name=path.name
        if name.startswith(("~$",)):continue
        # copies such as "type2_wifi_<original>" are test duplicates; the template is chosen from the original name
        source_name=name.split("_",2)[-1] if name.startswith("type2_wifi_") else name
        if parser.classify_or_none(source_name) is None:
            rows.append((name,"skipped","no registered template"));continue
        try:
            pkg=parser.parse_report(path,source_name=source_name)
            result=timescale.write_package(conn,pkg,accept_source_errors=True,replace=replace)
            run=pkg["test_run"]
            rows.append((name,result["status"],f"{pkg['document']['report_type']} {run['product_id']} fw={run['firmware_version']} hw={run['hardware_version']} "
                         f"{result.get('measurements','-')}m/{result.get('results','-')}r errors={len(pkg['quality']['formula_errors'])}"))
        except Exception as exc:  # noqa: BLE001 - report every failure, keep importing the rest
            rows.append((name,"FAILED",f"{type(exc).__name__}: {str(exc)[:160]}"))
    return rows

def main():
    p=argparse.ArgumentParser();p.add_argument("folder");p.add_argument("--database-url",required=True);p.add_argument("--replace",action="store_true");p.add_argument("--only")
    a=p.parse_args()
    try:sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    except Exception:pass
    with psycopg.connect(a.database_url,autocommit=True) as conn:
        rows=import_folder(conn,a.folder,replace=a.replace,only=a.only)
    for r in rows:print(f"{r[1]:10} {r[0]}\n           {r[2]}")
    bad=[r for r in rows if r[1]=="FAILED"]
    print(f"\n{len(rows)-len(bad)} ok, {len(bad)} failed")
    sys.exit(1 if bad else 0)

if __name__=="__main__":main()
