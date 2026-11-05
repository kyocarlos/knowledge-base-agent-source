import json,logging,threading,uuid,time
from concurrent.futures import ThreadPoolExecutor
from .errors import IntegrationError,LeaseLost

logger=logging.getLogger("km.csit.doclib")

class _Heartbeat:
    def __init__(self,renew,seconds):
        self.renew,self.seconds=renew,seconds
        self.stop_event=threading.Event()
    def __enter__(self):
        def run():
            while not self.stop_event.wait(max(.05,self.seconds/3)):
                try:self.renew()
                except Exception:return
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()
        return self
    def __exit__(self,*a):
        self.stop_event.set();self.thread.join()

class DocLibWorker:
    """Ingestion, deletion and callback delivery loops for spec v1.3."""
    def __init__(self,settings,repo,client,pipeline,executor,extra_steps=()):
        self.settings,self.repo,self.client,self.pipeline,self.executor=settings,repo,client,pipeline,executor
        self.extra_steps=tuple(extra_steps) # (step, label) pairs run in their own loops (spec v1.4 work)
        self.id=uuid.uuid4().hex
    def process_one(self):
        s=self.settings
        job=self.repo.claim(self.id,s.lease_seconds)
        if not job:return False
        try:
            with _Heartbeat(lambda:self.repo.renew(job,s.lease_seconds),s.lease_seconds):
                self.pipeline.run(job)
        except LeaseLost:pass
        except Exception as e:
            error=e if isinstance(e,IntegrationError) else IntegrationError("PROCESSING_FAILED","KM processing unavailable",True)
            try:self.repo.fail(job,error,s.retry_delays)
            except LeaseLost:pass
        logger.info(json.dumps({"kmJobId":job["km_job_id"],"attempt":job["attempt_count"]}))
        return True
    def delete_one(self):
        s=self.settings
        job=self.repo.claim_deletion(self.id,s.lease_seconds)
        if not job:return False
        try:
            with _Heartbeat(lambda:self.repo.renew_deletion(job,s.lease_seconds),s.lease_seconds):
                result=self.executor.run(job)
            self.repo.finish_deletion(job,result)
        except LeaseLost:pass
        except Exception as e:
            error=e if isinstance(e,IntegrationError) else IntegrationError("CLEANUP_FAILED","Deletion cleanup unavailable",True)
            try:self.repo.fail_deletion(job,error,s.retry_delays)
            except LeaseLost:pass
        logger.info(json.dumps({"kmDeletionJobId":job["km_deletion_job_id"],"attempt":job["attempt_count"]}))
        return True
    def callback_one(self):
        s=self.settings
        delivery=self.repo.claim_callback(max(s.lease_seconds,3*s.timeout))
        if not delivery:return False
        error=None
        try:self.client.post_status(delivery["kind"],delivery["payload"])
        except Exception as e:
            error=e if isinstance(e,IntegrationError) else IntegrationError("CALLBACK_FAILED","Status callback unavailable",True)
        try:self.repo.callback_result(delivery,error,s.callback_retry_delays)
        except LeaseLost:pass
        p=delivery["payload"]
        ids={k:p[k] for k in ("eventId","csitJobId","kmJobId","changeId","kmChangeJobId","deletionRequestId","kmDeletionJobId","analysisResultId","documentId","version") if k in p}
        entry={"callbackId":str(delivery["callback_id"]),"kind":delivery["kind"],"attempt":delivery["attempt_count"],
               "status":p.get("status"),"lastErrorCode":error.code if error else None,**({"ids":ids} if error else {})}
        (logger.warning if error else logger.info)(json.dumps(entry))
        return True
    def run(self,stop_event):
        def loop(step,label):
            while not stop_event.is_set():
                try:
                    if not step():stop_event.wait(self.settings.poll_seconds)
                except Exception:
                    logger.warning("KM CSIT doclib "+label+" store unavailable")
                    stop_event.wait(self.settings.poll_seconds)
        with ThreadPoolExecutor(max_workers=self.settings.worker_concurrency+2+len(self.extra_steps)) as pool:
            futures=[pool.submit(loop,self.process_one,"ingest") for _ in range(self.settings.worker_concurrency)]
            futures.append(pool.submit(loop,self.delete_one,"deletion"))
            futures.append(pool.submit(loop,self.callback_one,"callback"))
            futures.extend(pool.submit(loop,step,label) for step,label in self.extra_steps)
            for f in futures:f.result()
