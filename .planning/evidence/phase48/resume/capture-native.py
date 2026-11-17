"""Copy only committed, verified new native proof; no RPC or live writes."""
import json,shutil
from pathlib import Path
from neraium_poly.research.phase17.provenance import ReadonlyArchive
from neraium_poly.research.phase44.native import replay
from neraium_poly.research.phase14.relationships import digest
HERE=Path(__file__).resolve().parent;root=Path('/home/ubuntu/Neraium-Poly/data/experimental-paper');old=json.loads((HERE.parent/'ending-native-identities.json').read_text())['snapshot']['proofs'];source=ReadonlyArchive(root);saved=[]
for row in source.latest('NativePayout44',16):
 if not row['verified'] or row['directory'] in old:continue
 dest=HERE/'new-native'/row['directory'];dest.parent.mkdir(exist_ok=True)
 if not dest.exists():shutil.copytree(root/'phase42-native'/row['directory'],dest)
 assert replay(dest)==row['proof'];saved.append(row)
(HERE/'new-native-publications.json').write_text(json.dumps({'records':saved,'independent_replay_matches_published_proof':True,'live_archive_modified':False,'scope':'published proofs only; positive payout does not establish profitable strategy; preserve original forecast and source hashes'},indent=2)+'\n');print({'published_proofs_copied_and_replayed':len(saved)})
