"""Verified memory-only checkpoint encoding; never touches source files or SQLite."""
import base64
import gzip
import hashlib
import io
import json
import math
import zlib

CODEC = "phase16-canonical-json-gzip-v1"
MAX_RAW_BYTES = 8 * 1024**2
MAX_ENCODED_BYTES = 2 * 1024**2
CHUNK = 65536
FIELDS = {"codec", "raw_sha256", "raw_bytes", "gzip_sha256", "gzip_bytes", "gzip_base64"}


def _json_only(value):
    """Reject lossy coercions, cycles and pathological shared-container expansion."""
    pending, active, visited = [(value, False)], set(), 0
    while pending:
        item, exiting = pending.pop()
        if exiting:
            active.remove(id(item))
            continue
        visited += 1
        if visited > 1000000:
            raise ValueError("checkpoint structural node budget exceeded")
        if type(item) in (dict, list):
            if len(item) > 250000:
                raise ValueError("checkpoint container item budget exceeded")
            if id(item) in active:
                raise ValueError("checkpoint cannot contain cyclic containers")
            active.add(id(item))
            pending.append((item, True))
            if type(item) is dict:
                if any(type(key) is not str for key in item):
                    raise ValueError("checkpoint dictionary keys must be strings")
                pending.extend((child, False) for child in item.values())
            else:
                pending.extend((child, False) for child in item)
        elif (item is None or type(item) in (str, bool, int)
              or type(item) is float and math.isfinite(item)):
            continue
        else:
            raise ValueError("checkpoint must contain finite JSON-native values only")


def _canonical(value):
    if type(value) is not dict:
        raise ValueError("checkpoint must be a JSON object")
    _json_only(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False,
                          ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("checkpoint cannot be encoded as canonical JSON") from error


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def pack_checkpoint(checkpoint):
    """Encode and independently verify a bounded JSON-native checkpoint in memory."""
    raw = _canonical(checkpoint)
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("checkpoint decoded byte budget exceeded")
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", compresslevel=1, mtime=0) as stream:
        stream.write(raw)
    compressed = output.getvalue()
    encoded = base64.b64encode(compressed).decode("ascii")
    if len(encoded) > MAX_ENCODED_BYTES:
        raise ValueError("checkpoint encoded byte budget exceeded")
    envelope = {"codec": CODEC, "raw_sha256": _sha(raw), "raw_bytes": len(raw),
                "gzip_sha256": _sha(compressed), "gzip_bytes": len(compressed), "gzip_base64": encoded}
    if _canonical(unpack_checkpoint(envelope)) != raw:
        raise ValueError("checkpoint independent roundtrip verification failed")
    return envelope


def _nonfinite_constant(_value):
    raise ValueError("nonfinite checkpoint JSON constant")


def unpack_checkpoint(envelope):
    """Verify both byte identities before restoring exactly one bounded gzip member."""
    if type(envelope) is not dict or set(envelope) != FIELDS or envelope.get("codec") != CODEC:
        raise ValueError("unsupported checkpoint envelope schema")
    for key, maximum in (("raw_bytes", MAX_RAW_BYTES), ("gzip_bytes", MAX_ENCODED_BYTES * 3 // 4)):
        if type(envelope[key]) is not int or not 1 <= envelope[key] <= maximum:
            raise ValueError("checkpoint declared byte bounds invalid")
    for key in ("raw_sha256", "gzip_sha256"):
        if (type(envelope[key]) is not str or len(envelope[key]) != 64
            or set(envelope[key])-set("0123456789abcdef")):
            raise ValueError("checkpoint hash encoding invalid")
    encoded = envelope["gzip_base64"]
    if type(encoded) is not str or not 1 <= len(encoded) <= MAX_ENCODED_BYTES:
        raise ValueError("checkpoint encoded byte budget exceeded")
    try:
        compressed = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeError) as error:
        raise ValueError("checkpoint base64 is malformed") from error
    if base64.b64encode(compressed).decode("ascii") != encoded:
        raise ValueError("checkpoint base64 is not canonical")
    if len(compressed) != envelope["gzip_bytes"] or _sha(compressed) != envelope["gzip_sha256"]:
        raise ValueError("checkpoint compressed hash or length mismatch")
    decoder, raw = zlib.decompressobj(16 + zlib.MAX_WBITS), bytearray()
    try:
        for offset in range(0, len(compressed), CHUNK):
            chunk = compressed[offset:offset+CHUNK]
            while chunk:
                previous = chunk
                part = decoder.decompress(chunk, min(CHUNK, envelope["raw_bytes"]-len(raw)+1))
                raw.extend(part)
                if len(raw) > envelope["raw_bytes"] or len(raw) > MAX_RAW_BYTES:
                    raise ValueError("checkpoint decompression exceeds declared bound")
                if decoder.unused_data:
                    raise ValueError("checkpoint contains trailing gzip members or garbage")
                chunk = decoder.unconsumed_tail
                if chunk == previous and not part:
                    raise ValueError("checkpoint decompressor made no progress")
        if not decoder.eof:
            raise ValueError("checkpoint gzip stream is incomplete")
    except zlib.error as error:
        raise ValueError("checkpoint gzip stream is corrupt") from error
    raw = bytes(raw)
    if len(raw) != envelope["raw_bytes"] or _sha(raw) != envelope["raw_sha256"]:
        raise ValueError("checkpoint decoded hash or length mismatch")
    try:
        checkpoint = json.loads(raw.decode("utf-8"), parse_constant=_nonfinite_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("checkpoint decoded JSON is invalid") from error
    if _canonical(checkpoint) != raw:
        raise ValueError("checkpoint decoded JSON is not canonical")
    return checkpoint
