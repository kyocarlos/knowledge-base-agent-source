from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse

@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    db_url: str = field(default="", repr=False)
    csit_base_url: str = ""
    authority: str = ""
    audience: str = ""
    outbound_audience: str = ""
    jwks_uri: str = ""
    token_url: str = ""
    client_id: str = ""
    secret_file: str = ""
    service_clients: tuple[str,...] = ()
    service_claim: str = "principal_type"
    service_claim_value: str = "service"
    client_claim: str = "client_id"
    algorithm: str = "RS256"
    timeout: float = 30
    max_file_size: int = 50*1024*1024
    lease_seconds: int = 120
    poll_seconds: float = 2
    worker_concurrency: int = 1
    retry_delays: tuple[int,...] = (10,60,300)
    callback_retry_delays: tuple[int,...] = (10,60,300,900)
    storage_root: str = ""
    chunk_size: int = 1200
    zip_max_expanded: int = 200*1024*1024
    zip_max_ratio: float = 100
    zip_max_members: int = 10000
    max_table_cells: int = 1000000
    max_text_chars: int = 10000000
    @classmethod
    def from_env(cls):
        defaults=cls()
        values={}
        for name in cls.__dataclass_fields__:
            key="KM_CSIT_"+name.upper()
            if key not in os.environ: continue
            raw=os.environ[key]
            default=getattr(defaults,name)
            if isinstance(default,bool): values[name]=raw.lower()=="true"
            elif isinstance(default,tuple):
                values[name]=tuple(int(x) for x in raw.split(",") if x.strip()) if name.endswith("delays") else tuple(x.strip() for x in raw.split(",") if x.strip())
            elif isinstance(default,int): values[name]=int(raw)
            elif isinstance(default,float): values[name]=float(raw)
            else: values[name]=raw
        return cls(**values)
    def validate_inbound(self):
        for key in ("authority","audience","jwks_uri","service_claim","service_claim_value","client_claim"):
            if not getattr(self,key):raise ValueError("inbound auth configuration required: "+key)
        if not self.service_clients:raise ValueError("approved service clients required")
        if self.algorithm not in ("RS256","ES256"):raise ValueError("asymmetric token algorithm required")
        for key in ("authority","jwks_uri"):
            p=urlparse(getattr(self,key))
            if p.scheme!="https" or not p.netloc or p.username or p.password or p.query or p.fragment:
                raise ValueError("protected inbound HTTPS URL required: "+key)
    def validate(self):
        try:
            from psycopg.conninfo import conninfo_to_dict
            parsed=conninfo_to_dict(self.db_url)
            if not parsed.get("dbname") or not parsed.get("host"):raise ValueError()
        except Exception:raise ValueError("existing PostgreSQL metadata DB required") from None
        for key in ("timeout","max_file_size","lease_seconds","poll_seconds","worker_concurrency","chunk_size","zip_max_expanded","zip_max_ratio","zip_max_members","max_table_cells","max_text_chars"):
            if getattr(self,key)<=0: raise ValueError("positive setting required: "+key)
        if not self.retry_delays or not self.callback_retry_delays or any(x<0 for x in self.retry_delays+self.callback_retry_delays):
            raise ValueError("retry delays must be configured")
        if self.enabled:
            for key in ("csit_base_url","authority","audience","outbound_audience","jwks_uri","token_url","client_id","secret_file","storage_root"):
                if not getattr(self,key): raise ValueError("M2M configuration required: "+key)
            if not self.service_clients: raise ValueError("approved service clients required")
            for key in ("csit_base_url","authority","jwks_uri","token_url"):
                p=urlparse(getattr(self,key))
                if p.scheme!="https" or not p.netloc or p.username or p.password or p.query or p.fragment:
                    raise ValueError("protected HTTPS URL required: "+key)
            if self.algorithm not in ("RS256","ES256"): raise ValueError("asymmetric token algorithm required")
            p=Path(self.secret_file)
            if not p.is_file() or p.stat().st_mode&0o077:
                raise ValueError("protected outbound service secret file required")
