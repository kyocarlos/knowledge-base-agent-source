import json
from src.web_api import app
paths=sorted(p for p in app.openapi()["paths"] if "/rca/" in p)
print("rca paths:",paths)
from src.web_api.rca_routes import default_connect,default_roles
from src.report_numeric import compare
print("roles:",default_roles())
with default_connect() as c:
    runs=[r[0] for r in c.execute("select test_run_id from km_test.test_run where report_type='wifi_throughput' and access_roles && %s order by product_id limit 3",(default_roles(),)).fetchall()]
    print("throughput runs:",len(runs))
    p=compare.compare_runs(compare.load_runs(c,runs[:2],default_roles()),compare.load_directions(c))
    print("compare:",p["counts"],"confounded:",p["confounded"])
    try:c.execute("create table km_test.should_fail(x int)")
    except Exception as e:print("write attempt ->",type(e).__name__)
