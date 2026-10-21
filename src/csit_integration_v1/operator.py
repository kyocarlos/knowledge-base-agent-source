"""Internal operator command. Invoked only by the authenticated SSH host wrapper; no HTTP/M2M entry."""
import json,sys
from .config import Settings
from .repository import Repository
from .errors import IntegrationError

def main():
    try:
        command=json.load(sys.stdin)
        if command.get('action')!='resume':raise IntegrationError('OPERATOR_ACTION_INVALID','Unsupported operator action')
        s=Settings.from_env()
        if not s.enabled:raise IntegrationError('INTEGRATION_DISABLED','Enable DEV runtime before operator resume')
        identity={k:command[k] for k in ['event_id','source_system','document_id','version']}
        result=Repository(s.db_url).resume(command['job_id'],identity,command['actor_user_id'],command['operator_login'],command['reason'])
        print(json.dumps(result));return 0
    except IntegrationError as e:
        print(json.dumps({'error':e.code,'message':e.message}));return 2
    except Exception:
        print(json.dumps({'error':'OPERATOR_COMMAND_FAILED','message':'Operator command failed; inspect audit before any retry'}));return 2

if __name__=='__main__':raise SystemExit(main())
