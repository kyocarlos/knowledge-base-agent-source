"""Fail-closed OAuth access-token policies; test handlers only injected by test code."""
from dataclasses import dataclass
from typing import Protocol
from pathlib import Path
import threading,time
import httpx
from fastapi import HTTPException, Request
from .errors import IntegrationError

SUBMIT_SCOPE="km.ingestion.submit"
OUTBOUND_SCOPES=("csit.document.read","csit.ingestion.status.write")
def scope_set(raw):
    """The scopes of a token claim: OAuth writes them space-delimited, but many identity servers put a JSON array in a JWT (RFC 9068 allows both readings in practice)."""
    if isinstance(raw,str):return frozenset(raw.split())
    if isinstance(raw,(list,tuple)):return frozenset(x for x in raw if isinstance(x,str) and x)
    return frozenset()
@dataclass(frozen=True)
class ServiceIdentity:
    client_id: str
    scopes: frozenset[str]
class TokenValidator(Protocol):
    def validate(self, token: str) -> ServiceIdentity: ...

class JwtServiceTokenValidator:
    def __init__(self, settings):
        import jwt
        self.jwt=jwt
        self.settings=settings
        self.keys=jwt.PyJWKClient(settings.jwks_uri, timeout=settings.timeout)
    def validate(self, token, diagnostics=None):
        s=self.settings
        d=diagnostics if diagnostics is not None else {}
        try:
            key=self.keys.get_signing_key_from_jwt(token).key
            d['signing_key']='PASS'
            claims=self.jwt.decode(token,key,algorithms=[s.algorithm],issuer=s.authority,audience=s.audience,
                options={"require":["exp","iat","iss","aud"]})
            d.update(signature='PASS',issuer='PASS',audience='PASS',token_time='PASS',jwt_principal_created=True)
            client=claims.get(s.client_claim)
            if s.service_marker_required and claims.get(s.service_claim)!=s.service_claim_value:
                d.update(principal_type='FAIL',failure_check='SERVICE_MARKER_MISMATCH')
                raise ValueError()
            d['principal_type']='PASS'
            if client not in s.service_clients:
                d.update(service_identity='FAIL',failure_check='CLIENT_NOT_ALLOWED')
                raise ValueError()
            d['service_identity']='PASS'
            return ServiceIdentity(client,scope_set(claims.get('scope','')))
        except self.jwt.ExpiredSignatureError:
            d.update(signature='PASS',token_time='FAIL',failure_check='TOKEN_EXPIRED')
        except self.jwt.ImmatureSignatureError:
            d.update(signature='PASS',token_time='FAIL',failure_check='TOKEN_NOT_YET_VALID')
        except self.jwt.InvalidIssuedAtError:
            d.update(signature='PASS',token_time='FAIL',failure_check='INVALID_IAT')
        except self.jwt.InvalidIssuerError:
            d.update(signature='PASS',token_time='PASS',issuer='FAIL',failure_check='ISSUER_MISMATCH')
        except self.jwt.InvalidAudienceError:
            d.update(signature='PASS',token_time='PASS',issuer='PASS',audience='FAIL',failure_check='AUDIENCE_MISMATCH')
        except self.jwt.MissingRequiredClaimError:
            d.update(signature='PASS',failure_check='REQUIRED_CLAIM_MISSING')
        except (self.jwt.InvalidSignatureError,self.jwt.InvalidAlgorithmError):
            d.update(signature='FAIL',failure_check='SIGNATURE_OR_ALGORITHM_INVALID')
        except self.jwt.PyJWKClientError:
            d.update(signing_key='FAIL',failure_check='JWKS_KEY_UNAVAILABLE')
        except self.jwt.DecodeError:
            d.update(failure_check='JWT_FORMAT_INVALID')
        except Exception:
            d.setdefault('failure_check','JWT_VALIDATION_FAILED')
        raise HTTPException(401,'Invalid service access token',headers={'WWW-Authenticate':'Bearer error="invalid_token"'}) from None

def authorize(request: Request, validator: TokenValidator|None, accepted=None):
    accepted=frozenset(accepted) if accepted else frozenset({SUBMIT_SCOPE})
    header=request.headers.get('authorization','')
    d={'authorization_header_present':bool(header),'bearer_scheme':header.startswith('Bearer '),
       'jwt_principal_created':False,'signing_key':'NOT_CHECKED','signature':'NOT_CHECKED',
       'issuer':'NOT_CHECKED','audience':'NOT_CHECKED','token_time':'NOT_CHECKED',
       'principal_type':'NOT_CHECKED','service_identity':'NOT_CHECKED','scope':'NOT_CHECKED','endpoint_authorization':'FAIL'}
    request.state.csit_auth_evidence=d
    if not header.startswith('Bearer ') or len(header)>16384:
        d['failure_check']='BEARER_SCHEME_REQUIRED'
        raise HTTPException(401,'Service bearer authentication required',headers={'WWW-Authenticate':'Bearer'})
    if validator is None:
        d['failure_check']='INBOUND_AUTH_NOT_CONFIGURED'
        raise HTTPException(503,'M2M client credentials configuration pending')
    identity=validator.validate(header[7:],d) if isinstance(validator,JwtServiceTokenValidator) else validator.validate(header[7:])
    if not isinstance(identity,ServiceIdentity) or not identity.client_id:
        d['failure_check']='SERVICE_IDENTITY_REQUIRED'
        raise HTTPException(401,'Service identity required')
    if not accepted&identity.scopes:
        d.update(scope='FAIL',failure_check='SUBMIT_SCOPE_MISSING')
        raise HTTPException(403,'Missing required scope')
    d.update(scope='PASS',endpoint_authorization='PASS')
    return identity

class ClientCredentialsProvider:
    def __init__(self, settings, transport=None):
        import jwt
        self.settings=settings
        self.jwt=jwt
        self.keys=jwt.PyJWKClient(settings.jwks_uri, timeout=settings.timeout)
        self.http=httpx.Client(timeout=settings.timeout,verify=True,follow_redirects=False,transport=transport)
        self._lock=threading.Lock()
        self._tokens={}   # sorted scope tuple -> (access token, monotonic expiry)

    @property
    def _token(self):
        """The cached ordinary token (None when there is none): what the provider tests look at."""
        cached=self._tokens.get(tuple(sorted(self.settings.outbound_scopes)))
        return cached[0] if cached else None

    def _response_error(self, code, message, response, secret, retryable=False):
        import base64,re
        from urllib.parse import quote,quote_plus
        diagnostic={"http_status":response.status_code,"oauth_error":None,"oauth_error_description":None}
        try:
            body=response.json()
            error=body.get("error")
            if isinstance(error,str) and re.fullmatch(r"[a-z_]{1,40}",error):diagnostic["oauth_error"]=error
            description=body.get("error_description")
            if isinstance(description,str):
                encoded=base64.b64encode((self.settings.client_id+":"+secret).encode()).decode()
                for value in (secret,quote(secret,safe=""),quote_plus(secret),encoded,body.get("access_token")):
                    if isinstance(value,str) and value:description=description.replace(value,"[REDACTED]")
                description=re.sub(r"(?i)(Basic|Bearer)\s+\S+",r"\1 [REDACTED]",description)
                description=re.sub(r"[A-Za-z0-9_+/.=-]{40,}","[REDACTED]",description)
                diagnostic["oauth_error_description"]=description[:300]
        except (ValueError,AttributeError,TypeError):pass
        exc=IntegrationError(code,message,retryable)
        exc.diagnostic=diagnostic
        return exc

    def _validate_relaxed(self, token, key, wanted=None):
        """What the CSIT specs actually fix (issuer, audience, expiry, scope): signature, issuer, audience containing ours, exp / iat, every requested scope granted.
        The claims the strict check also demands (principal_type, client_id, sub) were KM's own assumption from the Shared Identity design, not CSIT's: here they
        are checked only when the token carries them (under the claim names inbound uses), and a token that has extra scopes is fine."""
        s=self.settings
        claims=self.jwt.decode(token,key,algorithms=[s.algorithm],issuer=s.authority,audience=s.outbound_audience,options={"require":["exp","iat","iss","aud","scope"]})
        if not set(wanted or s.outbound_scopes)<=scope_set(claims["scope"]):
            raise IntegrationError("M2M_SCOPE_MISSING","Outbound service token scopes invalid")
        if s.client_claim in claims and claims[s.client_claim]!=s.client_id:raise ValueError()
        if s.service_claim in claims and claims[s.service_claim]!=s.service_claim_value:raise ValueError()
        return claims

    def _validate_token(self, token, wanted=None):
        s=self.settings
        wanted=tuple(wanted or s.outbound_scopes)
        try:
            if not s.outbound_audience:raise ValueError()
            key=self.keys.get_signing_key_from_jwt(token).key
            if not s.outbound_strict:return self._validate_relaxed(token,key,wanted)
            claims=self.jwt.decode(token,key,algorithms=[s.algorithm],issuer=s.authority,
                audience=s.outbound_audience,options={"require":["exp","iat","iss","aud","sub","client_id","principal_type","scope"]})
            audiences=claims["aud"] if isinstance(claims["aud"],list) else [claims["aud"]]
            if audiences!=[s.outbound_audience]:raise ValueError()
            if claims["principal_type"]!="service" or claims["client_id"]!=s.client_id or claims["sub"]!=s.client_id:raise ValueError()
            if not isinstance(claims["scope"],str) or set(claims["scope"].split())!=set(wanted):
                raise IntegrationError("M2M_SCOPE_MISSING","Outbound service token scopes invalid")
            return claims
        except IntegrationError:raise
        except Exception:
            raise IntegrationError("M2M_TOKEN_INVALID","Outbound service token validation failed") from None

    def headers(self,scopes=None):
        """The bearer header. scopes=None asks for the configured outbound scopes; a deletion callback passes its own (outbound + deletion) and gets its own token."""
        wanted=tuple(dict.fromkeys(scopes)) if scopes else tuple(self.settings.outbound_scopes)
        slot=tuple(sorted(wanted))
        with self._lock:
            cached=self._tokens.get(slot)
            if not cached or time.monotonic()>=cached[1]:
                s=self.settings
                secret=Path(s.secret_file).read_text().strip()
                try:
                    r=self.http.post(s.token_url,data={"grant_type":"client_credentials","scope":" ".join(wanted)},
                        auth=httpx.BasicAuth(s.client_id,secret))
                    if r.status_code in (401,403):
                        raise self._response_error("M2M_AUTH_FAILED","Outbound service authentication rejected",r,secret)
                    if r.status_code!=200:
                        raise self._response_error("M2M_UNAVAILABLE","Outbound service authentication unavailable",r,secret,r.status_code==429 or r.status_code>=500)
                    d=r.json()
                    if not isinstance(d,dict) or d.get("token_type","").lower()!="bearer" or not isinstance(d.get("access_token"),str):raise ValueError()
                    ttl=int(d["expires_in"])
                    if ttl<=0:raise ValueError()
                    # The response scope field is optional. Signed JWT claims remain mandatory.
                    if "scope" in d:
                        granted=set(d["scope"].split()) if isinstance(d["scope"],str) else None
                        if granted is None or (granted!=set(wanted) if s.outbound_strict else not set(wanted)<=granted):
                            raise IntegrationError("M2M_SCOPE_MISSING","Outbound response scopes invalid")
                    claims=self._validate_token(d["access_token"],wanted)
                    cached=(d["access_token"],time.monotonic()+max(0,min(ttl,claims["exp"]-time.time())-30))
                    self._tokens[slot]=cached
                except IntegrationError:raise
                except (httpx.HTTPError,ValueError,KeyError,TypeError,AttributeError):
                    raise IntegrationError("M2M_UNAVAILABLE","Outbound service token request failed",True) from None
                finally:secret=None
            return {"Authorization":"Bearer "+cached[0]}
    def close(self):
        self._tokens.clear()
        self.http.close()
