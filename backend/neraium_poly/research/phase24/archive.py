"""Bounded read views of the shared archive, never an index or data rewrite."""
from pathlib import Path

from neraium_poly.research.phase17.provenance import ReadonlyArchive


def latest(store,kind,limit=256):
    directory=getattr(store,'directory',None)
    if directory is None or not (Path(directory)/'events-archive.sqlite').is_file():
        return store.latest(kind,limit=limit)
    with ReadonlyArchive(directory,max_payload_bytes=16*1024**2,max_query_bytes=32*1024**2) as reader:
        while limit:
            try:return reader.latest(kind,limit=limit)
            except ValueError as error:
                if str(error)!='archive query byte budget exceeded':raise
                limit//=2
    raise ValueError('bounded research archive view unavailable')
