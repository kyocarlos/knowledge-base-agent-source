import threading,time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import pytest
from src.csit_integration_v1.models import IngestionRequest
from src.csit_integration_v1.errors import LeaseLost
from test_client_pipeline import prepare

def test_callback_claim_concurrency_and_recovery(repo,settings,payload):
    worker,server,r,_=prepare(repo,settings,payload);worker.process_one()
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims=list(pool.map(lambda _:repo.claim_callback(60),range(8)))
    owned=[c for c in claims if c]
    assert len(owned)==1 # Completed cannot overtake an in-flight Processing delivery.
    old=owned[0]
    with repo.connect() as c:c.execute("UPDATE km_csit_callback_deliveries SET lease_until=clock_timestamp()-interval '1 second' WHERE delivery_id=%s",(old["delivery_id"],))
    new=repo.claim_callback(60)
    assert new["delivery_id"]==old["delivery_id"] and new["lease_token"]!=old["lease_token"]
    with pytest.raises(LeaseLost):repo.callback_result(old,None,settings.callback_retry_delays)
    repo.callback_result(new,None,settings.callback_retry_delays)
    assert repo.claim_callback(60)["payload"]["status"]=="Completed"

def test_background_processing_callback_during_ingestion(repo,settings,payload):
    entered=threading.Event();release=threading.Event();seen=threading.Event()
    worker,server,r,_=prepare(repo,replace(settings,poll_seconds=.02),payload)
    original=worker.pipeline.parser.parse
    def slow(path,suffix):
        entered.set();assert release.wait(5);return original(path,suffix)
    worker.pipeline.parser.parse=slow
    callback=worker.client.callback
    def notify(p):
        if p["status"]=="Processing":seen.set()
        return callback(p)
    worker.client.callback=notify
    stop=threading.Event()
    thread=threading.Thread(target=worker.run,args=(stop,));thread.start()
    try:
        assert entered.wait(3)
        assert seen.wait(3)
        assert repo.get(r["job_id"])["status"]=="Processing"
        release.set()
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and repo.get(r["job_id"])["status"]!="Completed":time.sleep(.02)
        assert repo.get(r["job_id"])["status"]=="Completed"
    finally:release.set();stop.set();thread.join(5)
    assert not thread.is_alive()

def test_heartbeat_prevents_second_worker_claim(repo,settings,payload):
    from src.csit_integration_v1.worker import LeaseHeartbeat
    repo.submit(IngestionRequest(**payload));job=repo.claim("first",1)
    with LeaseHeartbeat(repo,job,1):
        time.sleep(1.2)
        assert repo.claim("second",1) is None

def test_retry_budget_exhaustion(repo,settings,payload):
    worker,server,r,_=prepare(repo,settings,payload);server.download_status=503
    for _ in range(3):assert worker.process_one()
    final=repo.get(r["job_id"])
    assert final["status"]=="Failed" and final["attempt_count"]==3 and final["next_retry_at"] is None
    assert not worker.process_one()

def test_callback_permanent_auth_failure_no_ingestion_rerun(repo,settings,payload):
    worker,server,r,_=prepare(repo,settings,payload);worker.process_one()
    server.callback_status=403;worker.callback_one()
    assert repo.get(r["job_id"])["status"]=="Completed"
    assert server.downloads==1 and not worker.process_one()

def test_immutable_content_change_detected(repo,settings,payload):
    worker,server,r,(q,n,t)=prepare(repo,settings,payload)
    q.fail_once=True;worker.process_one()
    server.content=b"other text!!" # same size; committed version may not change contents
    worker.process_one()
    final=repo.get(r["job_id"])
    assert final["status"]=="Failed" and final["last_error_code"]=="SOURCE_VERSION_CHANGED" and final["next_retry_at"] is None

def test_repeated_worker_crash_budget_terminal_failure(repo,settings,payload):
    worker,server,r,_=prepare(repo,settings,payload)
    with repo.connect() as c:
        c.execute("UPDATE km_csit_ingestion_jobs SET status='Processing',attempt_count=3,lease_token=gen_random_uuid(),lease_until=clock_timestamp()-interval '1 second'")
    worker.process_one()
    final=repo.get(r["job_id"])
    assert final["status"]=="Failed" and final["last_error_code"]=="WORKER_RECOVERY_EXHAUSTED"
    assert final["next_retry_at"] is None and server.downloads==0
