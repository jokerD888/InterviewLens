"""Start only this trial's native services; never load the PC .env."""
import json, os, pathlib, pwd, subprocess, sys
ROOT=pathlib.Path('/opt/interviewlens-trial');USER=pwd.getpwnam('iltrial')
os.environ.update(PATH='/usr/bin:/bin',HOME=str(ROOT),TZ='Asia/Shanghai')
sys.path.insert(0,str(ROOT/'app/src'))
secrets=json.loads((ROOT/'private/secrets.json').read_text())
from interviewlens.db.provision import provision
provision('postgresql://il_bootstrap@/interviewlens_trial?host=/opt/interviewlens-trial/run&port=15433',secrets['database'],secrets['migration'])

def identity():
    os.setgroups([3003]);os.setgid(USER.pw_gid);os.setuid(USER.pw_uid)

statefile=ROOT/'run/services.json'
state=json.loads(statefile.read_text()) if statefile.exists() else {}
def launch(name,args,env):
    previous=state.get(name)
    if previous:
        proc=pathlib.Path('/proc')/str(previous)
        if proc.exists() and 'State:\tZ' not in (proc/'status').read_text():
            actual_exe=os.readlink(proc/'exe')
            if actual_exe!=str(pathlib.Path(args[0]).resolve()):raise RuntimeError('PID reused; refusing to act')
            expected_cwd=ROOT/name if name.startswith('redis-') else ROOT/'web' if name=='web' else ROOT
            if os.readlink(proc/'cwd')!=str(expected_cwd):raise RuntimeError('Unexpected process directory')
            print(name,'already running',previous,flush=True);return
    log=(ROOT/'logs'/f'{name}.log').open('ab',buffering=0)
    p=subprocess.Popen(args,env=env,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                       start_new_session=True,preexec_fn=identity)
    state[name]=p.pid;statefile.write_text(json.dumps(state));os.chmod(statefile,0o600)
    print(name,'started',p.pid,flush=True)

env={**os.environ,'PYTHONPATH':str(ROOT/'app/src'),'PYTHONUNBUFFERED':'1','APP_ENV':'production',
 'DATABASE_URL':f"postgresql+asyncpg://il_app:{secrets['database']}@127.0.0.1:15433/interviewlens_trial",
 'DATABASE_URL_SYNC':f"postgresql+psycopg://il_app:{secrets['database']}@127.0.0.1:15433/interviewlens_trial",
 'ADMIN_API_TOKEN':secrets['admin'],'APP_ORIGINS':'["https://interview.819266.xyz"]',
 'REDIS_URL':f"redis://:{secrets['redis']}@127.0.0.1:16380/0",
 'CACHE_REDIS_URL':f"redis://:{secrets['cache']}@127.0.0.1:16381/0",
 'CELERY_BROKER_URL':f"redis://:{secrets['redis']}@127.0.0.1:16380/1",
 'CELERY_RESULT_BACKEND':f"redis://:{secrets['redis']}@127.0.0.1:16380/2",
 'DEEPSEEK_API_KEY':'sk-REPLACE_ME','LANGFUSE_PUBLIC_KEY':'pk-REPLACE_ME','LANGFUSE_SECRET_KEY':'sk-REPLACE_ME',
 'INFERPILOT_SERVER_URL':'','EMBEDDING_DEVICE':'cpu','TOKENIZERS_PARALLELISM':'false',
 'OMP_NUM_THREADS':'3','MKL_NUM_THREADS':'3','SEARCH_CONCURRENCY':'1',
 'TRUSTED_SEARCH_PROXY':'','HF_HUB_OFFLINE':'1'}
env.update(json.loads((ROOT/'private/integrations.json').read_text()) if (ROOT/'private/integrations.json').exists() else {})
privateenv=ROOT/'private/api-env.json';privateenv.write_text(json.dumps(env));os.chmod(privateenv,0o600)
for name,port,password,cap,persist in [('redis-state',16380,secrets['redis'],'48mb',True),('redis-cache',16381,secrets['cache'],'48mb',False)]:
    config=ROOT/'private'/f'{name}.conf'
    # This Android kernel fails Valkey's ARM64 fork/COW test. Trial instances
    # never fork: no snapshots, no manual or automatic AOF rewrite, no CONFIG.
    # The narrow warning override is safe only with this no-fork configuration.
    config.write_text(f'bind 127.0.0.1\nport {port}\nprotected-mode yes\nrequirepass {password}\nmaxmemory {cap}\nmaxmemory-policy '+('noeviction' if persist else 'allkeys-lru')+f'\ndir {ROOT/name}\nsave ""\nappendonly '+('yes' if persist else 'no')+'\nappendfsync everysec\nauto-aof-rewrite-percentage 0\nignore-warnings ARM64-COW-BUG\nrename-command BGSAVE ""\nrename-command BGREWRITEAOF ""\nrename-command SAVE ""\nrename-command CONFIG ""\n')
    os.chown(config,USER.pw_uid,USER.pw_gid);os.chmod(config,0o600)
    launch(name,['/usr/bin/valkey-server',str(config)],env)

for name in ['server.js','.next/routes-manifest.json','.next/required-server-files.json']:
    path=ROOT/'web'/name
    if path.exists():
        original=path.read_text();updated=original.replace('http://api:8000','http://127.0.0.1:18800')
        if original!=updated:path.write_text(updated)
for path in [ROOT/'onnx_adapter.py',ROOT/'trial_api.py',ROOT/'model/model.onnx',ROOT/'model/model.onnx.data']:
    os.chown(path,USER.pw_uid,USER.pw_gid)
launch('api',[str(ROOT/'venv/bin/python'),str(ROOT/'trial_api.py')],env)
web_env={**os.environ,'NODE_ENV':'production','NEXT_TELEMETRY_DISABLED':'1','HOSTNAME':'127.0.0.1','PORT':'13013','API_BASE':'http://127.0.0.1:18800'}
launch('web',['/usr/bin/node',str(ROOT/'web/server.js')],web_env)

launch('worker',[str(ROOT/'venv/bin/python'),str(ROOT/'worker.py')],env)
launch('gateway',['/usr/bin/caddy','run','--config',str(ROOT/'Caddyfile'),'--adapter','caddyfile'],env)
launch('tunnel',['/usr/bin/cloudflared','tunnel','--config',str(ROOT/'private/tunnel.yml'),'run'],env)
