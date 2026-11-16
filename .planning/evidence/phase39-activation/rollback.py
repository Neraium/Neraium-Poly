"""Authorized experimental-only, source-only rollback. No financial restoration."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=Path('/home/ubuntu/Neraium-Poly')
UNIT='neraium-poly-experimental.service'
DROP=Path('/etc/systemd/system/neraium-poly-experimental.service.d/60-phase39-source.conf')

def check():
    subprocess.run(['git','-C',str(ROOT),'diff','--exit-code','1342482','--','backend','config','pyproject.toml','uv.lock'],check=True,capture_output=True)
    if DROP.exists():assert DROP.read_bytes()==(HERE/'experimental-source.conf').read_bytes()
    subprocess.run(['sudo','-n','true'],check=True)
    return {'rollback_source':'1342482fd9431f4e2e69d8788d864cb32fd1d4e9','dropin_sha256':hashlib.sha256((HERE/'experimental-source.conf').read_bytes()).hexdigest(),'financial_restore':False,'reference_restart':False}

if __name__=='__main__':
    result=check()
    if '--execute' in sys.argv:
        assert DROP.exists(), 'owned activation drop-in required'
        subprocess.run(['sudo','-n','systemctl','stop',UNIT],check=True,timeout=45)
        subprocess.run(['sudo','-n','rm','--',str(DROP)],check=True,timeout=10)
        subprocess.run(['sudo','-n','systemctl','daemon-reload'],check=True,timeout=30)
        subprocess.run(['sudo','-n','systemctl','start',UNIT],check=True,timeout=30)
        result['executed']=True
    else:result['executed']=False
    (HERE/'rollback-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
