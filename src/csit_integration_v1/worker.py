import json,logging,threading,uuid,time,signal
from concurrent.futures import ThreadPoolExecutor
from .errors import IntegrationError, LeaseLost

logger=logging.getLogger("km.csit.integration")
class LeaseHeartbeat:
    def __init__(self,repo,job,seconds):
        self.repo,self.job,self.seconds=repo,job,seconds
        self.stop_event=threading.Event()
        self.lost=threading.Event()
    def __enter__(self):
        def run():
            while not self.stop_event.wait(max(.05,self.seconds/3)):
                try:self.repo.renew(self.job,self.seconds)
                except Exception:self.lost.set();return
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()
        return self
    def __exit__(self,*args):
        self.stop_event.set();self.thread.join()
class Worker:
    def __init__(self,settings,repository,client,pipeline):
        self.settings,self.repo,self.client,self.pipeline=settings,repository,client,pipeline
        self.id=uuid.uuid4().hex
    def process_one(self):
        s=self.settings
        job=self.repo.claim(self.id,s.lease_seconds)
        if not job:return False
        start=time.monotonic()
        try:
            with LeaseHeartbeat(self.repo,job,s.lease_seconds):
                if job["attempt_count"]-job.get("_resume_attempt_base",0)>len(s.retry_delays)+1:
                    raise IntegrationError("WORKER_RECOVERY_EXHAUSTED","Worker recovery attempt budget exhausted")
                self.pipeline.run(job)
        except LeaseLost:pass # a newer worker owns this source version; no stale state update
        except Exception as e:
            error=e if isinstance(e,IntegrationError) else IntegrationError("PROCESSING_FAILED","KM processing unavailable",True)
            try:self.repo.fail(job,error,s.retry_delays)
            except LeaseLost:pass
        r=self.repo.get(job["job_id"])
        logger.info(json.dumps({"jobId":str(job["job_id"]),"eventId":job["event_id"],"documentId":job["document_id"],
            "version":job["version"],"phase":r["phase"],"status":r["status"],"attempt":r["attempt_count"],
            "downloadAttempt":r["download_attempt_count"],"lastErrorCode":r["last_error_code"],
            "durationMs":int((time.monotonic()-start)*1000)}))
        return True
    def callback_one(self):
        s=self.settings
        delivery=self.repo.claim_callback(max(s.lease_seconds,3*s.timeout))
        if not delivery:return False
        error=None
        try:self.client.callback(delivery["payload"])
        except Exception as e:
            error=e if isinstance(e,IntegrationError) else IntegrationError("CALLBACK_FAILED","Status callback unavailable",True)
        try:self.repo.callback_result(delivery,error,s.callback_retry_delays)
        except LeaseLost:pass
        logger.info(json.dumps({"jobId":str(delivery["job_id"]),"callbackAttempt":delivery["attempt_count"],
            "status":delivery["payload"]["status"],"lastErrorCode":error.code if error else None}))
        return True
    def run(self,stop_event):
        def job_loop():
            while not stop_event.is_set():
                try:
                    if not self.process_one():stop_event.wait(self.settings.poll_seconds)
                except Exception:
                    logger.warning("KM CSIT worker metadata store unavailable")
                    stop_event.wait(self.settings.poll_seconds)
        def callback_loop():
            while not stop_event.is_set():
                try:
                    if not self.callback_one():stop_event.wait(self.settings.poll_seconds)
                except Exception:
                    logger.warning("KM CSIT callback metadata store unavailable")
                    stop_event.wait(self.settings.poll_seconds)
        # Callback delivery is independent of long-running parsing/indexing.
        with ThreadPoolExecutor(max_workers=self.settings.worker_concurrency+1) as pool:
            futures=[pool.submit(job_loop) for _ in range(self.settings.worker_concurrency)]
            futures.append(pool.submit(callback_loop))
            for future in futures:future.result()
