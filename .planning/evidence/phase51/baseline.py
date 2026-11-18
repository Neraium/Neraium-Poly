import json
import os
import shutil
import sys
from pathlib import Path

from neraium_poly.research.phase17.provenance import ReadonlyArchive
from state import accounts,journal_heads,native,trials

root=Path(sys.argv[1])
seed=root/'seed'
baseline={'accounts':accounts(seed),'journals':journal_heads(seed/'experimental-paper'),
          'native':native(seed/'experimental-paper'),
          'trials':trials(ReadonlyArchive(seed/'experimental-paper').get)}
out=root/'baseline.json'
out.write_text(json.dumps(baseline,indent=2)+'\n')
os.chmod(out,0o644)
# The account store rejects aliased top-level SQLite files. Physically clone the
# legacy file into the test seed while leaving its original inode/content intact.
legacy=seed/'experimental-paper/events.sqlite'
if legacy.stat().st_nlink != 1:
    fresh=legacy.with_name('events.sqlite.private')
    shutil.copyfile(legacy,fresh)
    metadata=legacy.stat()
    os.chown(fresh,metadata.st_uid,metadata.st_gid)
    os.chmod(fresh,0o600)
    os.replace(fresh,legacy)
print({'accounts':baseline['accounts'],'proofs':len(baseline['native']['proofs']),'trials':len(baseline['trials'])})
