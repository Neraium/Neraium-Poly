"""Controlled archive files only; no production archive mutation."""
import os
from pathlib import Path

import pytest
from neraium_poly.data.segmented import _active_sqlite_bytes
from test_segmented_archive import managed, record


def test_active_bytes_include_only_known_sqlite_files_without_directory_scan(tmp_path,monkeypatch):
    path=tmp_path/'segment-00000001.sqlite'
    expected=0
    for suffix,size in [('',111),('-wal',222),('-shm',333),('-journal',444)]:
        Path(str(path)+suffix).write_bytes(b'x'*size);expected+=size
    # Simulate a large retained segment directory without allocating large data.
    for i in range(1000): (tmp_path/f'segment-{i+2:08d}.sqlite.manifest.json').touch()
    def forbidden(*args,**kwargs):raise AssertionError('active footprint must never enumerate directory')
    monkeypatch.setattr(Path,'glob',forbidden);monkeypatch.setattr(Path,'iterdir',forbidden)
    monkeypatch.setattr(os,'scandir',forbidden)
    assert _active_sqlite_bytes(path)==expected


@pytest.mark.parametrize('suffix',['','-wal','-shm','-journal'])
@pytest.mark.parametrize('kind',['symlink','directory'])
def test_active_sqlite_nonregular_files_fail_closed(tmp_path,suffix,kind):
    path=tmp_path/'segment-00000001.sqlite'
    if suffix:path.write_bytes(b'CONTROLLED')
    candidate=Path(str(path)+suffix)
    if kind=='directory':candidate.mkdir()
    else:
        other=tmp_path/'CONTROLLED-target';other.write_bytes(b'CONTROLLED');candidate.symlink_to(other)
    with pytest.raises(ValueError,match='nonregular'):_active_sqlite_bytes(path)


@pytest.mark.parametrize('suffix',['.gz','.gz.pending','.manifest.json','.manifest.json.pending','.cold-proof.json','.cold-proof.json.pending'])
def test_active_completion_artifacts_fail_closed(tmp_path,suffix):
    path=tmp_path/'segment-00000001.sqlite';path.write_bytes(b'CONTROLLED')
    Path(str(path)+suffix).touch()
    with pytest.raises(ValueError,match='completion artifact'):_active_sqlite_bytes(path)


def test_missing_active_db_is_not_silently_counted_as_zero(tmp_path):
    with pytest.raises(ValueError,match='source missing'):_active_sqlite_bytes(tmp_path/'segment-00000001.sqlite')


def test_optional_sidecar_disappearance_is_safe(tmp_path,monkeypatch):
    path=tmp_path/'segment-00000001.sqlite';path.write_bytes(b'CONTROLLED');original=os.stat
    def vanished(name,*a,**kw):
        if str(name).endswith('-wal'):raise FileNotFoundError('CONTROLLED removed sidecar')
        return original(name,*a,**kw)
    monkeypatch.setattr(os,'stat',vanished)
    assert _active_sqlite_bytes(path)==len(b'CONTROLLED')


def test_append_rotation_uses_constant_footprint_while_global_admission_remains(tmp_path,monkeypatch):
    store=managed(tmp_path/'events.sqlite',segment_bytes=4*1024**2,compress=False)
    check=store._check_budget;calls=[]
    def admission(*a,**kw):calls.append(a);return check(*a,**kw)
    monkeypatch.setattr(store,'_check_budget',admission)
    def forbidden(*args,**kwargs):raise AssertionError('per-record Path.glob must not run')
    monkeypatch.setattr(Path,'glob',forbidden)
    try:
        assert store.append(record(1)) and store.append(record(2))
        assert len(calls)>=2 and store.count()==2
    finally:store.close()
