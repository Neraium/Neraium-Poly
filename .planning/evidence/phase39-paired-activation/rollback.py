"""Restore only experimental source57b75a5; never restore financial state."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
DROP=Path('/etc/systemd/system/neraium-poly-experimental.service.d/60-phase39-source.conf')
UNIT='neraium-poly-experimental.service'
old_manifest=HERE.parent/'phase39-activation'/'release-manifest.json'
manifest=json.loads(old_manifest.read_text());release=Path(manifest['release'])
assert manifest['source']=='57b75a50f78d8df93ac15c06deaf626c255deb6b'
assert all(hashlib.sha256((release/name).read_bytes()).hexdigest()==sha for name,sha in manifest['files'].items())
assert DROP.read_bytes() in ((HERE/'previous-source.conf').read_bytes(),(HERE/'experimental-source.conf').read_bytes())
subprocess.run(['sudo','-n','true'],check=True)
result={'source':manifest['source'],'verified_files':len(manifest['files']),'financial_restore':False,'reference_restart':False,'executed':False}
if '--execute' in sys.argv:
    subprocess.run(['sudo','-n','systemctl','stop',UNIT],check=True,timeout=45)
    subprocess.run(['sudo','-n','install','-m','644',str(HERE/'previous-source.conf'),str(DROP)],check=True,timeout=10)
    subprocess.run(['sudo','-n','systemctl','daemon-reload'],check=True,timeout=30)
    subprocess.run(['sudo','-n','systemctl','start',UNIT],check=True,timeout=30)
    result['executed']=True
(HERE/'rollback-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
