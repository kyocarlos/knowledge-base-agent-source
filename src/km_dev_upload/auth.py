from fastapi import HTTPException
from src.km_control import verify_entry_session,ControlError

class EntryAuthenticator:
    def __init__(self,zone,control,allowed_users):
        self.zone,self.control,self.allowed=zone,control,set(allowed_users)
    def __call__(self,cookie):
        try:
            claims=verify_entry_session(cookie,self.zone)
            self.control.validate_entry_claims(claims["sub"],self.zone,claims["role"],claims["epoch"])
            user=self.control.get_user(claims["sub"])
            if user.username not in self.allowed:raise HTTPException(403,"Account is not enabled for DEV upload")
            return {"user_id":user.user_id,"username":user.username}
        except HTTPException:raise
        except (ControlError,KeyError,ValueError,TypeError):raise HTTPException(401,"Login and select the current KM data zone")
