"""Exercise durable queued work on the isolated, keyless acceptance stack only."""
import argparse
import json
import re
import subprocess
import time
from datetime import datetime, timezone
import httpx

parser = argparse.ArgumentParser()
parser.add_argument('--project', required=True)
args = parser.parse_args()
if not re.fullmatch(r'alfa-context-check-\d{14}', args.project):
    raise SystemExit('Only an isolated generated acceptance project is permitted')
compose = ['docker','compose','-p',args.project,'--env-file','deploy/verify.env','-f','compose.yaml','-f','compose.verify.yaml']
def command(*parts):
    subprocess.run(compose+list(parts),check=True)

with httpx.Client(base_url='http://localhost:8081',headers={'X-Alfa-Request':'1'},timeout=30) as client:
    client.post('/api/auth/login',json={'username':'demo','password':'demo-alfa-2026'}).raise_for_status()
    metrics=client.get('/api/admin/metrics').json()
    assert metrics['mode']=='demo' and metrics['llm_allowance']['requests_used']==0
    command('stop','worker')
    try:
        title='Проверка восстановления платежного календаря '+datetime.now(timezone.utc).isoformat()
        body={'title':title,'publisher':'Учебная проверка восстановления','content':'Синтетическая новость: изменение сроков платежей требует сверки договоров, обязательств и резерва ликвидности. Проверочный материал не содержит реальных данных.',
              'synthetic':True,'published_at':datetime.now(timezone.utc).isoformat()}
        client.post('/api/admin/news',json=body).raise_for_status()
        event=client.get('/api/feed',params={'company_id':'demo-metal','role':'CFO','corpus':'synthetic','q':title}).json()['items'][0]
        response=client.post('/api/analyses',json={'company_id':'demo-metal','event_id':event['id'],'role':'CFO'})
        response.raise_for_status();run_id=response.json()['run_id']
        assert client.get('/api/runs/'+run_id).json()['status']=='queued'
        command('restart','api')
        command('up','-d','--wait','api')
        command('restart','web')
        assert client.get('/api/runs/'+run_id).json()['status']=='queued'
    finally:
        command('start','worker')
    for _ in range(60):
        run=client.get('/api/runs/'+run_id).json()
        if run['status'] not in ('queued','running'):
            break
        time.sleep(1)
    assert run['status']=='completed' and run['result']['mode']=='demo', run.get('error')
    after=client.get('/api/admin/metrics').json()['llm_allowance']
    assert after['requests_used']==0 and after['spent_rub']==0
    print(json.dumps({'queue_survived_api_restart':True,'worker_completed':True,'paid_calls':0}))
