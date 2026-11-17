"""Real archive COPY only; full proof replay, interrupted resume and reversal."""
import hashlib,json,shutil,tarfile,tempfile
from datetime import UTC,datetime
from pathlib import Path

from neraium_poly.research.phase48.migration import Migration,allocation,snapshot

HERE=Path(__file__).resolve().parent;LIVE=Path('/home/ubuntu/Neraium-Poly/data/experimental-paper/phase42-native')
with tempfile.TemporaryDirectory(prefix='phase48-copy-',dir=HERE) as tmp:
    temp=Path(tmp);root=temp/'native';shutil.copytree(LIVE,root);initial=snapshot(root);baseline=allocation(root)
    # Bind copies of every published proof to the existing immutable journal.
    from neraium_poly.research.phase17.provenance import ReadonlyArchive
    from neraium_poly.research.phase14.relationships import digest
    source=ReadonlyArchive(LIVE.parent);anchored={}
    for row in source.latest('NativePayout44',512):
        if row['verified'] and row['directory'] in initial['proofs']:
            assert digest(row['proof'])==initial['proofs'][row['directory']];anchored[row['directory']]=row['id']
    assert set(anchored)==set(initial['proofs']),'every proof must have existing published identity'
    fired=[]
    def interrupt(stage):
        if stage=='gzip_installed' and not fired:fired.append(stage);raise RuntimeError('CONTROLLED simulated power interruption')
    m=Migration(root,temp/'journal',hook=interrupt)
    try:
        try:m.migrate()
        except RuntimeError as e:assert str(e).startswith('CONTROLLED')
    finally:m.close()
    assert fired
    recovered=Migration(root,temp/'journal');migrated=recovered.migrate();after=recovered.verify();restored=recovered.restore();recovered.verify();recovered.migrate();recovered.verify();events=recovered.sequence;recovered.close()
    result={'at':datetime.now(UTC).isoformat(),'live_archive_modified':False,'isolated_original_files':len(initial['files']),'original_proof_identities':initial['proofs'],'published_anchors':anchored,'before':baseline,'after':after,'restored':restored,'interrupted_then_resumed':True,'restoration_byte_exact':True,'journal_events':events,'guard_bytes':64*1024**2,'scope':'real copied archive, all proofs and logical hashes checked; temporary fixture removed after tests; no live mutation'}
    (HERE/'migration-rehearsal.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('isolated_original_files','before','after','restored','interrupted_then_resumed')}))
