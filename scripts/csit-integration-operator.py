#!/usr/bin/env python3
"""Trusted host administrative command. SSH/Unix identity maps to an existing KM admin.
No service token, shared secret, browser session forging or public endpoint is involved.
The management account's Docker access is a privileged capability; restrict it as such.
"""
import argparse,json,os,pathlib,pwd,stat,subprocess,sys,uuid

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['resume']);p.add_argument('--job-id',type=uuid.UUID,required=True)
    p.add_argument('--event-id',required=True);p.add_argument('--source-system',choices=['CSIT'],required=True)
    p.add_argument('--document-id',required=True);p.add_argument('--version',type=int,required=True)
    p.add_argument('--reason',required=True)
    p.add_argument('--operator-bindings',type=pathlib.Path,default=pathlib.Path.home()/'.km-control/csit-operator-bindings.json')
    a=p.parse_args();login=pwd.getpwuid(os.getuid()).pw_name
    try:
        f=a.operator_bindings.resolve();st=f.stat();parent=f.parent.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid not in (0,os.getuid()) or st.st_mode&0o077 or parent.st_mode&0o022:
            raise ValueError('Unsafe operator binding file')
        config=json.loads(f.read_text());actor=config['operators'][login]
        container=config['api_container']
        if not isinstance(actor,str) or not isinstance(container,str) or not container:raise ValueError('Invalid binding')
        command={'action':a.action,'job_id':str(a.job_id),'event_id':a.event_id,'source_system':a.source_system,
          'document_id':a.document_id,'version':a.version,'reason':a.reason,'actor_user_id':actor,'operator_login':login}
        r=subprocess.run(['docker','exec','-i',container,'python','-m','src.csit_integration_v1.operator'],input=json.dumps(command),text=True,capture_output=True)
        print(r.stdout.strip() if r.stdout else json.dumps({'error':'OPERATOR_TRANSPORT_FAILED'}));return r.returncode
    except Exception:
        print(json.dumps({'error':'OPERATOR_NOT_AUTHORIZED','message':'Authenticated host operator binding required'}));return 2

if __name__=='__main__':raise SystemExit(main())
