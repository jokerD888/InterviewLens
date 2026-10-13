import json, os, pathlib, pwd, signal, subprocess, time
ROOT=pathlib.Path('/opt/interviewlens-trial');u=pwd.getpwnam('iltrial')
def identity():os.setgroups([3003]);os.setgid(u.pw_gid);os.setuid(u.pw_uid)
statefile=ROOT/'run/services.json'
state=json.loads(statefile.read_text()) if statefile.exists() else {}
for name in ['tunnel','gateway','worker','web','api','redis-cache','redis-state']:
    pid=state.get(name)
    if not pid:continue
    p=pathlib.Path('/proc')/str(pid)
    if not p.exists() or 'State:\tZ' in (p/'status').read_text():continue
    expected=ROOT/name if name.startswith('redis-') else ROOT/'web' if name=='web' else ROOT
    if os.readlink(p/'cwd')!=str(expected):raise RuntimeError('Process scope differs; no signal sent')
    uid=int(next(l for l in (p/'status').read_text().splitlines() if l.startswith('Uid:')).split()[1])
    if uid!=u.pw_uid:raise RuntimeError('Process owner differs; no signal sent')
    os.kill(pid,signal.SIGTERM)
    for _ in range(50):
        if not p.exists() or 'State:\tZ' in (p/'status').read_text():break
        time.sleep(.1)
    else:raise RuntimeError(f'{name} did not stop cleanly; no force kill')
    print(name,'stopped',flush=True)
env={**os.environ,'PATH':'/usr/bin:/bin','HOME':str(ROOT),'LD_PRELOAD':str(ROOT/'libandroid-shmem-glibc.so')}
if (ROOT/'pgdata/postmaster.pid').exists():
    subprocess.run(['/usr/bin/pg_ctl','-D',str(ROOT/'pgdata'),'-m','fast','-w','stop'],env=env,preexec_fn=identity,check=True,timeout=30)
print('Trial stopped. Original PC database and tablet desktop untouched.',flush=True)
