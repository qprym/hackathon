"""Restore a dump to a separate database on an isolated, keyless test stack."""
import argparse
import json
import re
import subprocess

p=argparse.ArgumentParser();p.add_argument('--project',required=True);a=p.parse_args()
if not re.fullmatch(r'alfa-context-check-\d{14}',a.project):
    raise SystemExit('Only an isolated generated acceptance project is permitted')
base=['docker','compose','-p',a.project,'--env-file','deploy/verify.env','-f','compose.yaml','-f','compose.verify.yaml']
def command(*args):
    return subprocess.run(base+list(args),check=True,capture_output=True,text=True,encoding='utf8').stdout.strip()
def sql(database,query):return command('exec','-T','db','psql','-U','alfa','-d',database,'-At','-c',query)
command('exec','-T','api','python','-c','from app.config import settings; c=settings(); assert c.demo_mode and not c.llm_api_key and not c.auto_fetch_rss')
target='restore_verification_'+a.project.rsplit('-',1)[-1]
created=False
command('stop','worker')
try:
    command('exec','-T','db','pg_dump','-U','alfa','-d','alfa','-Fc','-f','/tmp/alfa-verification.dump')
    command('exec','-T','db','createdb','-U','alfa',target);created=True
    command('exec','-T','db','pg_restore','-U','alfa','--no-owner','--dbname',target,'/tmp/alfa-verification.dump')
    tables=sql('alfa',"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
    for name in tables:
        assert re.fullmatch(r'[a-z_]+',name),name
        query=f'''SELECT count(*), md5(coalesce(string_agg(row_to_json(t)::text, E'\\n' ORDER BY row_to_json(t)::text),'')) FROM "{name}" t'''
        assert sql('alfa',query)==sql(target,query),'Restored table differs: '+name
    # A temporary upload exercises the same binary backup path even on an empty demo.
    script='''import hashlib, pathlib, tarfile, tempfile
root=pathlib.Path('/app/uploads');root.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='backup-check-',dir=root) as source, tempfile.TemporaryDirectory() as tmp:
    original=pathlib.Path(source)/'page.pdf';original.write_bytes(b'%PDF-1.4\\n% binary round-trip \\x00\\xff\\n%%EOF')
    archive=pathlib.Path(tmp)/'sources.tar';restored=pathlib.Path(tmp)/'restored';restored.mkdir()
    with tarfile.open(archive,'w') as tar:tar.add(original,arcname='page.pdf')
    with tarfile.open(archive) as tar:tar.extractall(restored,filter='data')
    assert hashlib.sha256(original.read_bytes()).digest()==hashlib.sha256((restored/'page.pdf').read_bytes()).digest()
'''
    command('exec','-T','api','python','-c',script)
    print(json.dumps({'database_restored':True,'tables_compared':len(tables),'binary_upload_round_trip':True,'paid_calls':0}))
finally:
    if created:command('exec','-T','db','dropdb','-U','alfa',target)
    command('exec','-T','db','rm','-f','--','/tmp/alfa-verification.dump')
    command('start','worker')
