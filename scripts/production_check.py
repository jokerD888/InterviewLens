"""Local readiness/backup-age monitor; optional explicitly configured webhook.

No secrets or resolved Compose config are printed. systemd invokes this every
minute and sends failures to a separately configured alert unit.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import urllib.request

from production_ops import compose, invoke


def check(root: Path, backups: Path):
    prefix=compose(root)
    configuration=json.loads(invoke(prefix+["config","--format","json"],text=True))
    from urllib.parse import urlsplit
    database=urlsplit(configuration["services"]["api"]["environment"]["DATABASE_URL"]).path.lstrip('/')
    invoke(prefix+["exec","-T","api","curl","-fsS","--max-time","5","http://127.0.0.1:8000/health/ready"],timeout=15)
    eligible=[]
    for path in backups.glob('interviewlens-*.json'):
        try:
            metadata=json.loads(path.read_text(encoding='utf-8'))
            if metadata.get('database')==database and metadata.get('counts_stable') and path.with_suffix('.dump').is_file():
                eligible.append(path.stat().st_mtime)
        except (ValueError,OSError):
            continue
    if not eligible or datetime.now(timezone.utc).timestamp()-max(eligible)>26*3600:
        raise RuntimeError('No recent verified-source backup for the active database')
    print(json.dumps({'status':'ready','recent_backup':True,'database':database}))


def notify(unit: str):
    url=os.environ.get('IL_ALERT_WEBHOOK_URL','')
    if not url.startswith('https://'):
        raise ValueError('Configure a private HTTPS alert webhook first')
    payload=json.dumps({'text':f'InterviewLens operation failed: {unit[:150]}. Inspect systemd journal on the server.'}).encode()
    request=urllib.request.Request(url,data=payload,headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(request,timeout=10) as response:
        if response.status >=300:
            raise RuntimeError('Alert delivery failed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deploy-root',type=Path,default=Path(__file__).resolve().parents[1]/'deploy')
    parser.add_argument('--backups',type=Path,default=Path('/var/backups/interviewlens'))
    parser.add_argument('--notify-unit')
    args=parser.parse_args()
    try:
        if args.notify_unit:
            notify(args.notify_unit)
        else:
            check(args.deploy_root,args.backups)
    except Exception as error:
        print(f'Production check failed ({type(error).__name__}); inspect local readiness and backup configuration. Credentials withheld.')
        raise SystemExit(1) from None
