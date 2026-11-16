"""Read-only matched fixture benchmark. No real research or performance evidence."""
import json
import resource
import sqlite3
import sys
import time
from types import SimpleNamespace

from neraium_poly.research.phase20.continuous import ProspectiveABResearch
from neraium_poly.research.phase39.recovery import recovery_sources

db=sqlite3.connect('file:'+sys.argv[2]+'?mode=ro',uri=True)
checkpoint=json.loads(db.execute("SELECT payload FROM events WHERE kind='PairedForecastStudy' ORDER BY available_at,id LIMIT 1").fetchone()[0])
started=time.monotonic();cpu=time.process_time();count=0;status='completed';report=None
if sys.argv[1]=='baseline':
    rows=db.execute("SELECT payload FROM events WHERE kind='EventProbabilityStudy' ORDER BY available_at DESC,id DESC LIMIT 1000").fetchall()
    originals=[json.loads(r[0]) for r in rows]
    obj=ProspectiveABResearch.__new__(ProspectiveABResearch);obj.state=checkpoint['checkpoint']
    try:obj.catch_up(originals)
    except ValueError as error:status=str(error)
    count=len(originals)
else:
    cutoff=db.execute("SELECT max(available_at) FROM events WHERE kind='EventProbabilityStudy'").fetchone()[0]
    originals,report=recovery_sources(SimpleNamespace(connection=db),frontier=checkpoint['checkpoint']['declared_at'],cutoff=cutoff)
    count=len(originals)
print(json.dumps({'mode':sys.argv[1],'fixture_only':True,'status':status,'returned_rows':count,
    'elapsed_seconds':time.monotonic()-started,'cpu_seconds':time.process_time()-cpu,
    'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'coverage':report}))
db.close()
