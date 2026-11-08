"""Incremental, source-anchored derived research metadata. Never an authority gate."""
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import Field

from neraium_poly.contracts import Record
from neraium_poly.research.phase14.relationships import digest
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase25.competition import cohort_key
from neraium_poly.research.phase25.dependencies import at, bound_forecasts, canonical_event

KINDS=('ChallengerStudy','DomainResearchStudy','ExpansionResearchStudy','ChallengerOutcomeStudy','DomainOutcomeStudy','ExpansionOutcomeStudy')
VERSION='phase26-source-projection-v1'
AUTHORITY={'research_only':True,'trading_authority':False,'certification_authority':False}
FORECAST_KEYS=('id','domain','model_id','model_version','model_sha256','feature_version','event_id','market_id','token_id',
    'probability','probability_semantics','outcome_probabilities','timestamp','evidence_cutoff','event_end_time',
    'target_conditioning','conditioning','unconditional_contract_probability','market_baseline_comparable','market_probability',
    'market_expected_payout','calibration_status','source_lineages','rules_sha256','book_sha256','lower_probability','upper_probability')


class ResearchProjectionAnchor(Record):
    index_id:str
    policy_sha256:str
    cursor:int=Field(ge=0)
    cursor_id:str
    cursor_digest:str
    chain:str|None=None
    entries:int=Field(ge=0)
    research_only:Literal[True]=True
    trading_authority:Literal[False]=False
    certification_authority:Literal[False]=False


class ResearchIndex:
    def __init__(self,path,*,source_directory,readonly=False):
        self.path=Path(path).absolute();self.source_directory=Path(source_directory).absolute()
        if any(p.is_symlink() for p in [self.path,*self.path.parents,self.source_directory,*self.source_directory.parents]):raise ValueError('projection paths cannot be symlinks')
        self.path=self.path.resolve();self.source_directory=self.source_directory.resolve()
        if readonly and not self.path.is_file():raise ValueError('existing projection required for readonly report')
        if not readonly:self.path.parent.mkdir(parents=True,exist_ok=True)
        self.readonly=readonly
        self.policy_sha256=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('competition.py').read_bytes()).hexdigest()
        self.index_id=digest([VERSION,str(self.path),str(self.source_directory)])
        self.lock=RLock();self.closed=False
        self.db=sqlite3.connect(self.path.as_uri()+'?mode=ro' if readonly else str(self.path),uri=readonly,check_same_thread=False,timeout=3);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA cache_size=-2048')
        if readonly:self.db.execute('PRAGMA query_only=ON')
        else:
            self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entries(chain TEXT PRIMARY KEY,previous TEXT,payload TEXT NOT NULL,sha TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS projection_no_update BEFORE UPDATE ON entries BEGIN SELECT RAISE(ABORT,'append-only projection'); END;
            CREATE TRIGGER IF NOT EXISTS projection_no_delete BEFORE DELETE ON entries BEGIN SELECT RAISE(ABORT,'append-only projection'); END;''')
        identity=digest([self.index_id,self.policy_sha256])
        if not readonly:self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('identity',?)",(identity,))
        row=self.db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
        if row is None or row['value']!=identity:raise ValueError('projection source/path/policy identity mismatch')
        self.db.commit();self.last_progress=None

    def close(self):
        with self.lock:
            self.closed=True;self.db.close()

    def _anchor(self,reader):
        prefix='projection:'+self.index_id+':'
        rows=reader._catalog_rows("SELECT * FROM records WHERE kind='ResearchProjectionAnchor' AND id>=? AND id<? ORDER BY rowid DESC LIMIT 1",(prefix,prefix+'z'))
        for row in rows:
            anchor=ResearchProjectionAnchor.model_validate(json.loads(reader._fetch(row)[1]))
            if anchor.index_id!=self.index_id:continue
            if anchor.policy_sha256!=self.policy_sha256:raise ValueError('projection policy changed; explicit new index required')
            witness=reader._catalog_rows('SELECT id,digest FROM records WHERE rowid=?',(anchor.cursor,))
            if not witness or witness[0]['id']!=anchor.cursor_id or witness[0]['digest']!=anchor.cursor_digest:raise ValueError('projection source cursor witness mismatch')
            return anchor
        return None

    def _entries(self,anchor):
        if anchor is None:return []
        found=[];chain=anchor.chain;size=0
        while chain is not None:
            if len(found)>=50000:raise ValueError('projection bounded inventory exceeded; paginate explicitly')
            row=self.db.execute('SELECT * FROM entries WHERE chain=?',(chain,)).fetchone()
            if row is None:raise ValueError('source anchor ahead of missing derived projection')
            size+=len(row['payload'].encode())
            if size>64*1024**2:raise ValueError('projection metadata byte budget exceeded')
            value=json.loads(row['payload'])
            if digest(value)!=row['sha'] or digest([row['previous'],row['sha']])!=chain:raise ValueError('projection checksum/chain mismatch')
            found.append(value);chain=row['previous']
        if len(found)!=anchor.entries:raise ValueError('projection anchor entry count mismatch')
        return list(reversed(found))

    def _append(self,payload,chain):
        sha=digest(payload);identity=digest([chain,sha]);encoded=json.dumps(payload,sort_keys=True,separators=(',',':'))
        self.db.execute('INSERT OR IGNORE INTO entries VALUES (?,?,?,?)',(identity,chain,encoded,sha))
        row=self.db.execute('SELECT * FROM entries WHERE chain=?',(identity,)).fetchone()
        if row['payload']!=encoded or row['previous']!=chain or row['sha']!=sha:raise ValueError('derived projection collision')
        return identity

    def _source(self,reader,row):
        kind,raw,sha=reader._fetch(row)
        if sha!=row['digest'] or kind!=row['kind']:raise ValueError('source archive binding mismatch')
        return json.loads(raw),len(raw.encode())

    def _project(self,row,study,*,as_of,forecast_verifier,outcome_verifier,forecasts,declarations,reader):
        common={'source_id':study['id'],'source_payload_sha256':row['digest'],'source_study_sha256':digest(study),'source_rowid':row['source_rowid'],'source_kind':row['kind']}
        if row['kind'] in KINDS[:3]:
            result=[]
            for definition in study.get('enrollment',[]):
                if not isinstance(definition.get('model_id'),str):continue
                key=(study.get('enrollment_id'),definition['model_id']);declarations[key]=definition
                result.append({**common,'type':'declaration','enrollment_id':key[0],'definition':definition,'available_at':study['available_at']})
            found,rejected=bound_forecasts([study],as_of=as_of)
            for identity,value in found.items():
                f=value['forecast']
                if not isinstance(f.get('model_id',f.get('model_version')),str) or not f.get('model_id',f.get('model_version')):
                    result.append({**common,'type':'rejection','reason':'original forecast model identity required','count':1});continue
                entry={**common,'type':'forecast','forecast_id':identity,'forecast_sha256':digest(f),'available_at':study['available_at'],
                    'forecast':{k:f[k] for k in FORECAST_KEYS if k in f},'review':None,'cohort_id':None,'replay_verified':False,'rejection':None}
                try:
                    declaration=declarations.get((study.get('enrollment_id'),f.get('model_id',f.get('model_version'))))
                    if declaration is None or declaration.get('model_sha256')!=f.get('model_sha256'):raise ValueError('original declared model and enrollment required')
                    if not callable(forecast_verifier):raise TypeError('independent source/model replay callback required')
                    proof=forecast_verifier(study,f,as_of=as_of)
                    if not isinstance(proof,dict) or proof.get('verified') is not True:raise ValueError('independent source/model replay failed')
                    descriptor,group,tags=canonical_event(f)
                    entry.update(replay_verified=True,proof_sha256=digest(proof),review={'canonical_group_id':group,'descriptor':descriptor,'dependency_tags':tags,
                        'evidence_lineages':sorted(set(f.get('source_lineages',[])))},cohort_id=cohort_key(f,group))
                except (ValueError,TypeError,KeyError,StopIteration) as error:entry['rejection']=str(error)[:160]
                result.append(entry);forecasts.setdefault(identity,[]).append(entry)
            for reason,count in rejected.items():result.append({**common,'type':'rejection','reason':reason,'count':count})
            return result
        result=study.get('result',study);identity=result.get('forecast_id');entry={**common,'type':'outcome','forecast_id':identity,'verified':False,'proof':None,'rejection':None,'status':result.get('status')}
        if not (result.get('status')=='verified' or result.get('verified') is True or study.get('outcome')):return [entry]
        try:
            candidates=forecasts.get(identity,[])
            if not candidates or len({r['forecast_sha256'] for r in candidates})!=1:raise ValueError('unique indexed original forecast required')
            frow=candidates[0];raw=reader.get(frow['source_id'])
            if raw is None:raise ValueError('original outcome study unavailable')
            original=json.loads(raw[1]);f=next(f for f in original['forecasts'] if f['id']==identity)
            if digest(original)!=frow['source_study_sha256'] or digest(f)!=frow['forecast_sha256']:raise ValueError('original outcome source hash mismatch')
            if not callable(outcome_verifier):raise TypeError('independent terminal replay callback required')
            proof=outcome_verifier(study,f)
            if (not isinstance(proof,dict) or proof.get('verified') is not True or proof.get('forecast_id')!=identity
                or any(proof.get(k)!=f[k] for k in ('event_id','market_id','token_id','rules_sha256'))
                or not at(original['available_at'])<at(proof['resolved_at'])<=at(proof['available_at'])<=as_of):raise ValueError('exact prospective independent outcome replay required')
            entry.update(verified=True,proof=proof)
        except (ValueError,TypeError,KeyError,StopIteration) as error:entry['rejection']=str(error)[:160]
        return [entry]

    def step(self,store,*,as_of=None,forecast_verifier=None,outcome_verifier=None,max_records=32,max_bytes=16*1024**2):
        now=at(as_of or datetime.now(UTC))
        if type(max_records) is not int or not 1<=max_records<=256 or not 1024<=max_bytes<=32*1024**2:raise ValueError('bounded projection work required')
        with self.lock,ReadonlyArchive(self.source_directory,max_payload_bytes=16*1024**2,max_query_bytes=32*1024**2) as reader:
            if self.readonly:raise ValueError('readonly projection cannot ingest')
            anchor=self._anchor(reader)
            if anchor and anchor.available_at>now:raise ValueError('projection clock regression/future anchor')
            entries=self._entries(anchor);cursor=anchor.cursor if anchor else 0;chain=anchor.chain if anchor else None
            forecasts={};declarations={}
            for e in entries:
                if e['type']=='forecast':forecasts.setdefault(e['forecast_id'],[]).append(e)
                elif e['type']=='declaration':declarations[(e['enrollment_id'],e['definition']['model_id'])]=e['definition']
            placeholders=','.join('?' for _ in KINDS)
            rows=reader._catalog_rows(f'SELECT rowid AS source_rowid,* FROM records WHERE kind IN ({placeholders}) AND rowid>? ORDER BY rowid LIMIT ?',(*KINDS,cursor,max_records+1))
            used=processed=added=0;witness=None
            with self.db:
                for row in rows[:max_records]:
                    if at(row['available_at'])>now:break
                    study,length=self._source(reader,row)
                    if processed and used+length>max_bytes:break
                    if length>max_bytes:raise ValueError('single research record exceeds projection work budget')
                    projected=self._project(row,study,as_of=now,forecast_verifier=forecast_verifier,outcome_verifier=outcome_verifier,forecasts=forecasts,declarations=declarations,reader=reader)
                    for payload in projected:chain=self._append(payload,chain);added+=1
                    cursor=row['source_rowid'];witness=row;processed+=1;used+=length
            if witness:
                fields={'index_id':self.index_id,'policy_sha256':self.policy_sha256,'cursor':cursor,'cursor_id':witness['id'],'cursor_digest':witness['digest'],'chain':chain,'entries':len(entries)+added}
                record=ResearchProjectionAnchor(id='projection:'+self.index_id+':'+digest([VERSION,fields]),timestamp=now,available_at=now,source='neraium-poly/research-projection/v26',**fields)
                # Cache commits first. A crash before this append leaves an orphan
                # content-addressed branch; reports follow only an original anchor.
                store.append(record)
                confirmed=reader.get(record.id)
                if confirmed is None or digest(json.loads(confirmed[1]))!=digest(record.model_dump(mode='json')):raise ValueError('source projection anchor append not confirmed')
            head=reader._catalog_rows(f'SELECT max(rowid) AS head FROM records WHERE kind IN ({placeholders})',KINDS)[0]['head'] or 0
            self.last_progress={'processed_records':processed,'read_bytes':used,'source_cursor':cursor,'source_head':head,'caught_up':cursor>=head,'anchor_id':record.id if witness else anchor.id if anchor else None}
            return dict(self.last_progress)

    def snapshot(self):
        with self.lock,ReadonlyArchive(self.source_directory) as reader:
            anchor=self._anchor(reader);entries=self._entries(anchor)
            # Cheap catalog witnesses bind compact rows; no original payload replay.
            witnesses=dict({(e['source_id'],e['source_payload_sha256']) for e in entries})
            identities=list(witnesses)
            for offset in range(0,len(identities),128):
                batch=identities[offset:offset+128];marks=','.join('?' for _ in batch)
                rows=reader._catalog_rows(f'SELECT id,digest FROM records WHERE id IN ({marks})',tuple(batch))
                if len(rows)!=len(batch) or any(row['digest']!=witnesses[row['id']] for row in rows):raise ValueError('indexed source catalog witness mismatch')
            return entries,anchor.model_dump(mode='json') if anchor else None

    def report(self,*,as_of=None):
        from .competition import projection_report
        now=at(as_of or datetime.now(UTC));entries,anchor=self.snapshot()
        if anchor and at(anchor['available_at'])>now:raise ValueError('projection report predates its trusted anchor')
        report=projection_report(entries,as_of=now)
        with ReadonlyArchive(self.source_directory) as reader:
            placeholders=','.join('?' for _ in KINDS)
            head=reader._catalog_rows(f'SELECT max(rowid) AS head FROM records WHERE kind IN ({placeholders})',KINDS)[0]['head'] or 0
        cursor=anchor['cursor'] if anchor else 0
        progress={**(self.last_progress or {}),'source_cursor':cursor,'source_head':head,'caught_up':cursor>=head}
        report['projection']={'anchor':anchor,'progress':progress,'scope':'all indexed P23/P24/P25 model registries; legacy Phase18/13 separate; bootstrap explicit',
            'status':'caught_up' if progress['caught_up'] else 'bootstrapping',
            'source_replay_policy':'independent replay on ingestion, checksummed original-source-anchored projection on render; not a full archive integrity scan'}
        return report
