"""Reversible, quiescent native migration. Logical bytes and proofs never change.

Journal uses the existing FULL/WAL append-only EventStore. All filesystem
transitions are idempotent; intent is durable before mutation. A stopped owner
is required on live data. Failed temporary bytes are retained, never called proof.
"""
import gzip
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from neraium_poly.contracts import Record
from neraium_poly.data import EventStore
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase47.storage import read

LIMIT=64*1024**2
MAX_FILE=16*1024**2


def sha(raw):return hashlib.sha256(raw).hexdigest()


def allocation(root):
    seen=set();logical=unique=blocks=0;count=0
    for p in Path(root).rglob('*'):
        if p.is_symlink():raise ValueError('native symlink forbidden')
        if not p.is_file():continue
        s=p.stat();logical+=s.st_size;count+=1;key=(s.st_dev,s.st_ino)
        if key not in seen:unique+=s.st_size;blocks+=s.st_blocks*512;seen.add(key)
    return {'logical_bytes':logical,'unique_bytes':unique,'allocated_bytes':blocks,'files':count,'unique_inodes':len(seen),'limit_bytes':LIMIT}


def bounded(path):
    p=Path(path)
    if p.is_symlink() or p.stat().st_size>MAX_FILE:raise ValueError('bounded regular original required')
    return p.read_bytes()


def syncdir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def durable(path,data):
    with Path(path).open('xb') as out:out.write(data);out.flush();os.fsync(out.fileno())
    syncdir(Path(path).parent)


def proofs(root):
    from neraium_poly.research.phase35.native import replay_native_directory
    from neraium_poly.research.phase44.native import replay
    root=Path(root);out={}
    dirs={p.parent for p in root.rglob('*') if p.name in ('proof.json','proof.json.gz')}
    for p in sorted(dirs):
        bundle=json.loads(read(p/'bundle.json'))
        verified=replay_native_directory(p) if 'parent_event' in bundle else replay(p)
        original=json.loads(read(p/'proof.json'))
        if verified!=original:raise ValueError('stored proof replay mismatch')
        out[str(p.relative_to(root))]=digest(verified)
    return out


def snapshot(root):
    root=Path(root);allocation(root);files={}
    for p in sorted(root.rglob('*')):
        if not p.is_file():continue
        name=str(p.relative_to(root));raw=bounded(p)
        files[name]={'bytes':len(raw),'sha256':sha(raw),'compress':p.parent.name=='raw' and p.suffix=='.json' and p.relative_to(root).parts[0].startswith('v44-')}
        if len(files)>4096:raise ValueError('migration file bound exceeded')
    return {'version':'native48-v1','implementation_sha256':sha(Path(__file__).read_bytes()),'files':files,'proofs':proofs(root),'scope':'same logical bytes; raw v44 gzip compatibility; byte-identical raw hardlinks across immutable captures'}


class MigrationEvent48(Record):
    sequence:int
    plan_sha256:str
    previous_id:str|None
    previous_sha256:str|None
    operation:str
    detail:dict


def live_guard():
    import shutil
    import sqlite3
    import subprocess
    unit='neraium-poly-experimental.service'
    fields=dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show',unit,'-p','MainPID','-p','ActiveState'],text=True,timeout=5).splitlines())
    if fields!={'MainPID':'0','ActiveState':'inactive'}:raise ValueError('experimental must be stopped for live native migration')
    base=Path('/home/ubuntu/Neraium-Poly')
    if shutil.disk_usage(base).free<100*1024**3+MAX_FILE:raise ValueError('100GiB filesystem reserve')
    with __import__('contextlib').closing(sqlite3.connect('file:'+str(base/'data/experimental-paper/risk.sqlite')+'?mode=ro',uri=True,timeout=2)) as db:
        if db.execute('select kill from account where id=1').fetchone()[0]!=1:raise ValueError('latched stop required')


class Migration:
    def __init__(self,root,journal,*,quiescent=lambda:None,hook=lambda _:None):
        self.root=Path(root).resolve();self.journal=Path(journal).resolve();self.quiescent=live_guard if self.root==Path('/home/ubuntu/Neraium-Poly/data/experimental-paper/phase42-native').resolve() else quiescent;self.hook=hook
        if self.journal.is_relative_to(self.root):raise ValueError('administrative journal must be outside native payload root')
        self.quiescent();self.journal.mkdir(parents=True,exist_ok=True)
        import fcntl
        self.lease=(self.root.parent/('.'+self.root.name+'.migration48.lock')).open('a+b')
        try:fcntl.flock(self.lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lease.close();raise ValueError('another native migration owns this root') from None
        try:self._open()
        except BaseException:
            self.close();raise
    def _open(self):
        p=self.journal/'plan.json'
        if p.exists():self.plan=json.loads(bounded(p))
        else:
            self.plan=snapshot(self.root);durable(p,json.dumps(self.plan,sort_keys=True,separators=(',',':')).encode())
        if self.plan.get('implementation_sha256')!=sha(Path(__file__).read_bytes()):raise ValueError('migration implementation changed; reviewed source required')
        self.plan_sha=digest(self.plan);self.store=EventStore(self.journal/'migration.sqlite');self.last=None;self.sequence=0
        rows=self.store.connection.execute("SELECT payload,digest FROM events ORDER BY json_extract(payload,'$.sequence') LIMIT 32769").fetchall()
        if len(rows)>32768:raise ValueError('bounded migration journal exhausted')
        for raw,h in rows:
            if sha(raw.encode())!=h:raise ValueError('migration journal row hash mismatch')
            r=json.loads(raw)
            if (r['sequence']!=self.sequence or r['plan_sha256']!=self.plan_sha or r['previous_id']!=(self.last['id'] if self.last else None) or r['previous_sha256']!=(digest(self.last) if self.last else None)):raise ValueError('migration chain or plan mismatch')
            self.last=r;self.sequence+=1
        self.verify_bytes()
    def close(self):
        if getattr(self,'store',None) is not None:self.store.close()
        if getattr(self,'lease',None) is not None:self.lease.close()
    def event(self,op,detail):
        if self.sequence>=32768:raise ValueError('migration journal bound')
        now=datetime.now(UTC);r=MigrationEvent48(id=digest([self.plan_sha,self.sequence,op,detail]),timestamp=now,available_at=now,source='neraium-poly/native-representation48',sequence=self.sequence,plan_sha256=self.plan_sha,previous_id=self.last['id'] if self.last else None,previous_sha256=digest(self.last) if self.last else None,operation=op,detail=detail)
        self.store.append(r);self.last=json.loads(self.store.get(r.id)[1]);self.sequence+=1
    def verify_bytes(self):
        for name,expected in self.plan['files'].items():
            p=self.root/name
            if p.is_symlink() or not p.resolve().is_relative_to(self.root):raise ValueError('unsafe native original path')
            raw=read(p) if expected['compress'] else bounded(p)
            if len(raw)!=expected['bytes'] or sha(raw)!=expected['sha256']:raise ValueError('original logical byte identity changed: '+name)
    def verify(self):
        self.verify_bytes()
        if proofs(self.root)!=self.plan['proofs']:raise ValueError('native proof identity changed')
        return allocation(self.root)
    def migrate(self):
        self.quiescent();before=self.verify();self.event('begin',before);canon={}
        # Hardlinks preserve every path and byte; replacing an identical copy
        # needs no new data blocks. Only closed raw captures are candidates.
        for name,meta in self.plan['files'].items():
            p=self.root/name
            if p.parent.name!='raw' or not p.exists():continue
            self.quiescent();key=meta['sha256'];other=canon.get(key)
            if other is None:canon[key]=p;continue
            if (p.stat().st_dev,p.stat().st_ino)==(other.stat().st_dev,other.stat().st_ino):continue
            if bounded(p)!=bounded(other):raise ValueError('dedup collision or mutation')
            temp=p.with_name(p.name+'.48-link.tmp');self.event('dedup_intent',{'path':name,'canonical':str(other.relative_to(self.root)),'sha256':key})
            if not temp.exists():os.link(other,temp);syncdir(p.parent)
            if bounded(temp)!=bounded(other):raise ValueError('unsafe existing migration link')
            self.hook('linked');os.replace(temp,p);syncdir(p.parent);self.hook('dedup_switched')
            self.event('dedup_complete',{'path':name,'sha256':key})
        encoded={}
        for name,meta in self.plan['files'].items():
            if not meta['compress']:continue
            self.quiescent();p=self.root/name;dest=p.with_name(p.name+'.gz');temp=p.with_name(p.name+'.48-gzip.tmp')
            if not dest.exists():
                raw=bounded(p);data=gzip.compress(raw,compresslevel=6,mtime=0)
                if temp.exists():
                    try:
                        if gzip.decompress(bounded(temp))!=raw:raise ValueError('incomplete temp')
                    except (OSError,EOFError,ValueError):
                        # Preserve incomplete crash artifacts explicitly, never
                        # overwrite them or publish them as native evidence.
                        failed=temp.with_name(temp.name+'.partial-'+sha(bounded(temp)))
                        os.replace(temp,failed);syncdir(p.parent)
                self.event('gzip_intent',{'path':name,'sha256':meta['sha256'],'encoded_sha256':sha(data)})
                if not temp.exists():
                    shared=encoded.get(meta['sha256'])
                    if shared is not None:os.link(shared,temp);syncdir(p.parent)
                    else:
                        if allocation(self.root)['unique_bytes']+len(data)>LIMIT:raise ValueError('64MiB staging capacity unavailable; originals retained')
                        durable(temp,data)
                self.hook('gzip_staged')
                if gzip.decompress(bounded(temp))!=raw:raise ValueError('gzip staged byte mismatch')
                os.replace(temp,dest);syncdir(p.parent);self.hook('gzip_installed')
            with gzip.open(dest,'rb') as stream:decoded=stream.read(MAX_FILE+1)
            if len(decoded)!=meta['bytes'] or sha(decoded)!=meta['sha256']:raise ValueError('compressed original identity mismatch')
            encoded[meta['sha256']]=dest
            if p.exists():
                if bounded(p)!=decoded:raise ValueError('original changed before switch')
                p.unlink();syncdir(p.parent);self.hook('raw_switched')
            self.event('gzip_complete',{'path':name,'sha256':meta['sha256']})
        after=self.verify();self.quiescent()
        if after['unique_bytes']>LIMIT:raise ValueError('native guard exceeded')
        self.event('complete',after);return {'before':before,'after':after,'plan_sha256':self.plan_sha,'proofs_verified':len(self.plan['proofs']),'journal_events':self.sequence}
    def restore(self):
        """Restore original physical names/bytes; retain encoded copies as evidence.

        Quota is never waived. If later acquisitions leave insufficient room,
        stop with the still-readable compressed representation intact.
        """
        self.quiescent();self.verify();self.event('restore_begin',{});canon={}
        for name,meta in self.plan['files'].items():
            p=self.root/name
            if p.exists() and p.parent.name=='raw':canon.setdefault(meta['sha256'],p)
        for name,meta in self.plan['files'].items():
            if not meta['compress']:continue
            self.quiescent();p=self.root/name
            if p.exists():continue
            raw=read(p)
            if sha(raw)!=meta['sha256']:raise ValueError('restore input identity mismatch')
            temp=p.with_name(p.name+'.48-restore.tmp');other=canon.get(meta['sha256']);self.event('restore_intent',{'path':name,'sha256':meta['sha256']})
            if not temp.exists():
                if other is not None:os.link(other,temp);syncdir(p.parent)
                else:
                    if allocation(self.root)['unique_bytes']+len(raw)>LIMIT:raise ValueError('64MiB restore staging capacity unavailable; compressed evidence retained')
                    durable(temp,raw)
            if bounded(temp)!=raw:raise ValueError('restore staged byte mismatch')
            self.hook('restore_staged');os.replace(temp,p);syncdir(p.parent);self.hook('restore_switched');canon.setdefault(meta['sha256'],p)
            self.event('restore_complete_file',{'path':name,'sha256':meta['sha256']})
        after=self.verify();self.event('restore_complete',after);return after


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('migrate','restore','verify'));parser.add_argument('--root',required=True);parser.add_argument('--journal',required=True);args=parser.parse_args()
    m=Migration(args.root,args.journal)
    try:
        result=m.migrate() if args.action=='migrate' else m.restore() if args.action=='restore' else m.verify()
        (Path(args.journal)/('result-'+args.action+'.json')).write_text(json.dumps(result,indent=2)+'\n')
        (Path(args.journal)/'journal-export.json').write_text(json.dumps(m.store.replay(),indent=2)+'\n')
        print(json.dumps(result))
    finally:m.close()


if __name__=='__main__':main()
