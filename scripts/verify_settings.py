"""Check server-side token persistence only on an isolated, keyless verification project."""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit
import httpx

parser=argparse.ArgumentParser()
parser.add_argument('--project',required=True)
parser.add_argument('--url',default='http://localhost:8081')
args=parser.parse_args()
assert re.fullmatch(r'alfa-context-check-\d{14}',args.project),'Only isolated verification projects are supported'
assert urlsplit(args.url).hostname in ('localhost','127.0.0.1'),'Only loopback verification URLs are supported'
root=Path(__file__).resolve().parents[1]

def docker(*parts):
    return subprocess.run(['docker',*parts],cwd=root,check=True,capture_output=True,text=True).stdout

client=httpx.Client(base_url=args.url,headers={'X-Alfa-Request':'1'},timeout=30)
response=client.post('/api/auth/login',json={'username':'demo','password':'demo-alfa-2026'})
response.raise_for_status()
before=client.get('/api/admin/llm-settings').json()
metrics=client.get('/api/admin/metrics').json()['llm_allowance']
assert before['source']=='environment' and not before['enabled'] and not before['api_key_configured']
assert metrics['requests_used']==0 and metrics['spent_rub']==0
body={k:v for k,v in before.items() if k not in {'source','api_key_configured','approved_models'}}
body.update(enabled=False,automatic=False,provider_mode='remote',base_url='https://example.invalid/v1',api_key='fake-restart-credential')

try:
    response=client.post('/api/admin/llm-settings',json=body);response.raise_for_status()
    assert response.json()['api_key_configured'] and 'fake-restart-credential' not in response.text
    code="from app.config import settings; from pathlib import Path; c=settings(); assert c.demo_mode and c.llm_api_key=='fake-restart-credential'; assert Path(c.llm_settings_path).stat().st_mode & 0o777 == 0o600; print('Worker reloaded protected settings')"
    print(docker('exec',args.project+'-worker-1','python','-c',code).strip())
    docker('restart',args.project+'-api-1',args.project+'-worker-1')
    for _ in range(30):
        try:
            response=client.get('/api/admin/llm-settings')
            if response.status_code==200:break
        except httpx.HTTPError:pass
        time.sleep(1)
    response.raise_for_status()
    restored=response.json()
    assert restored['api_key_configured'] and not restored['enabled'] and restored['base_url']==body['base_url']
    print(docker('exec',args.project+'-worker-1','python','-c',code).strip())
finally:
    current=client.get('/api/admin/llm-settings');current.raise_for_status()
    response=client.post('/api/admin/llm-settings/reset',json={'revision':current.json()['revision']})
    response.raise_for_status()

assert client.get('/api/admin/metrics').json()['llm_allowance']==metrics
assert client.get('/api/admin/llm-settings').json()==before
print(json.dumps({'hot_reload':True,'restart_persistence':True,'mode_0600':True,'paid_calls':0}))
