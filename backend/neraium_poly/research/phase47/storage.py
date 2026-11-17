"""Lossless new evidence only. Legacy originals and raw-byte hashes are unchanged."""
import gzip
from pathlib import Path

from neraium_poly.research.phase46.file_budget import BudgetPath

MAX_DECODED=8*1024**2


def read(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('unsafe_native_evidence_path')
    if path.exists():
        if path.stat().st_size>MAX_DECODED:raise ValueError('bounded_native_evidence_required')
        return path.read_bytes()
    compressed=path.with_name(path.name+'.gz')
    if compressed.is_symlink() or compressed.stat().st_size>MAX_DECODED:raise ValueError('unsafe_or_oversized_compressed_evidence')
    with gzip.open(compressed,'rb') as stream:
        result=stream.read(MAX_DECODED+1)
    if len(result)>MAX_DECODED:raise ValueError('native_decoding_budget_exhausted')
    return result


class CompressedPath(BudgetPath):
    def write_bytes(self,data):
        if len(data)>MAX_DECODED:raise ValueError('native_encoding_budget_exhausted')
        # gzip CRC and original manifest SHA both verified on recovery. Reserve
        # compressed bytes BEFORE writes, including manifest replacements.
        encoded=gzip.compress(data,compresslevel=6,mtime=0)
        target=Path(str(self));target=target.with_name(target.name+'.gz')
        self.budget.write(target,encoded)
        return len(data)
