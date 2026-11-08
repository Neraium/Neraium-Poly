"""Lossless future research-wire compression; no source file or retention actions.

Existing phase16 envelopes already verify compressed and canonical lengths and
hashes, reject trailing compressed data, and cap expansion before decoding. Dense
encoding changes compression effort, never the codec or reconstructed JSON.
"""
import base64
import gzip
import hashlib
import io

from neraium_poly.research.phase16.checkpoints import (
    CODEC,
    MAX_ENCODED_BYTES,
    MAX_RAW_BYTES,
    _canonical,
    unpack_checkpoint,
)


def _compressed(value):
    raw=_canonical(value)
    if len(raw)>MAX_RAW_BYTES:raise ValueError('research decoded byte budget exceeded')
    output=io.BytesIO()
    with gzip.GzipFile(fileobj=output,mode='wb',filename='',compresslevel=6,mtime=0) as writer:writer.write(raw)
    return raw,output.getvalue()


def _envelope(raw,compressed):
    if len(compressed)>(MAX_ENCODED_BYTES//4)*3:raise ValueError('research encoded byte budget exceeded')
    envelope={'codec':CODEC,'raw_sha256':hashlib.sha256(raw).hexdigest(),'raw_bytes':len(raw),
        'gzip_sha256':hashlib.sha256(compressed).hexdigest(),'gzip_bytes':len(compressed),
        'gzip_base64':base64.b64encode(compressed).decode('ascii')}
    if _canonical(unpack_checkpoint(envelope))!=raw:raise ValueError('independent dense research roundtrip failed')
    return envelope


def pack_dense_checkpoint(value):
    """Deterministic level6 gzip with unchanged independently verified codec."""
    return _envelope(*_compressed(value))


def encode_report(value):
    """Bounded physical envelope when smaller; keep incompressible legacy shape.

    The logical report is unchanged. A stored source must always be hashed from
    its actual immutable wire, not from a reserialized legacy model instance.
    """
    raw,compressed=_compressed(value)
    if len(compressed)>(MAX_ENCODED_BYTES//4)*3 or len(compressed)*4//3+512>=len(raw):return value
    return _envelope(raw,compressed)


def decode_report(value):
    if type(value) is not dict:raise ValueError('research report object required')
    if 'codec' in value:
        if value.get('codec')!=CODEC:raise ValueError('unsupported research report codec')
        return unpack_checkpoint(value)
    if len(_canonical(value))>MAX_RAW_BYTES:raise ValueError('research report decoded byte budget exceeded')
    return value
