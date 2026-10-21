import argparse
import json
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument('file', type=Path)
args = parser.parse_args()
claims = json.loads(args.file.read_text(encoding='utf8'))['claims']
facts = [c for c in claims if not c.get('assumption')]
if not facts or any(type(c.get('supported')) is not bool or not c.get('reviewer') for c in facts):
    print(json.dumps({'status':'incomplete','factual_claims':len(facts),'message':'Independent factual review required'}))
    raise SystemExit(2)
rate = sum(c['supported'] for c in facts)/len(facts)
print(json.dumps({'status':'reviewed','factual_claims':len(facts),'supported_fraction':rate,'target_met':rate>=.95}))
