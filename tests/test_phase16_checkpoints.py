"""Controlled memory bytes; no historical source file or active DB is modified."""
import base64
import gzip
import hashlib

import pytest
from neraium_poly.research.phase16.checkpoints import (
    CODEC,
    MAX_ENCODED_BYTES,
    MAX_RAW_BYTES,
    pack_checkpoint,
    unpack_checkpoint,
)


def envelope(raw, compressed=None):
    compressed = gzip.compress(raw, compresslevel=1, mtime=0) if compressed is None else compressed
    return {"codec": CODEC, "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_bytes": len(raw),
            "gzip_sha256": hashlib.sha256(compressed).hexdigest(), "gzip_bytes": len(compressed),
            "gzip_base64": base64.b64encode(compressed).decode("ascii")}


def test_roundtrip_is_deterministic_and_lossless_for_json_native_values():
    value = {"日本語": "evidence", "version": 1, "rows": [None, True, False, -0.0, 1.5, {"id": "x"}]}
    packed = pack_checkpoint(value)
    assert unpack_checkpoint(packed) == value
    assert pack_checkpoint(dict(reversed(list(value.items())))) == packed
    assert base64.b64decode(packed["gzip_base64"])[4:8] == b"\0" * 4
    assert base64.b64decode(packed["gzip_base64"])[8] == 4  # Fastest gzip compression level.


@pytest.mark.parametrize("value", [[1], {1: "lossy-key"}, {"tuple": (1, 2)}, {"nan": float("nan")}, {"inf": float("inf")}, {"set": {1}}])
def test_nonobject_or_lossy_nonfinite_input_rejected(value):
    with pytest.raises(ValueError):
        pack_checkpoint(value)


@pytest.mark.parametrize("field,value", [("raw_sha256", "0"*64), ("gzip_sha256", "0"*64),
                                        ("raw_bytes", 999), ("gzip_bytes", 999),
                                        ("raw_bytes", True), ("gzip_bytes", False),
                                        ("raw_bytes", MAX_RAW_BYTES+1), ("codec", "pickle")])
def test_identity_lengths_types_and_codec_fail_closed(field, value):
    packed = pack_checkpoint({"controlled": True}); packed[field] = value
    with pytest.raises(ValueError):
        unpack_checkpoint(packed)


@pytest.mark.parametrize("raw", [b'[]', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e309}',
                                 b'{"b":1,"a":2}', b'{ "x":1}', b'{"x":1,"x":2}', b'{}\n'])
def test_noncanonical_nonobject_duplicate_and_nonfinite_json_rejected(raw):
    with pytest.raises(ValueError):
        unpack_checkpoint(envelope(raw))


@pytest.mark.parametrize("extra", [b'garbage', gzip.compress(b'', mtime=0), gzip.compress(b'{}', mtime=0)])
def test_trailing_garbage_and_multiple_members_rejected(extra):
    raw = b'{}'; compressed = gzip.compress(raw, mtime=0) + extra
    with pytest.raises(ValueError, match="trailing"):
        unpack_checkpoint(envelope(raw, compressed))


def test_truncated_and_crc_corrupt_streams_rejected_even_with_matching_compressed_hash():
    raw = b'{"controlled":true}'; original = gzip.compress(raw, mtime=0)
    for compressed in (original[:-1], original[:-8]+b'\x00'*8):
        with pytest.raises(ValueError, match="incomplete|corrupt"):
            unpack_checkpoint(envelope(raw, compressed))


@pytest.mark.parametrize("encoded", ["====", "not-base64!", "aA==\n", "aA=", "日本語"])
def test_invalid_base64_is_rejected(encoded):
    packed = pack_checkpoint({}); packed["gzip_base64"] = encoded
    with pytest.raises(ValueError):
        unpack_checkpoint(packed)


def test_streaming_expansion_is_bounded_by_declared_uncompressed_size():
    compressed = gzip.compress(b'a'*(MAX_RAW_BYTES+1000), compresslevel=1, mtime=0)
    packed = envelope(b'{}', compressed)
    with pytest.raises(ValueError, match="decompression exceeds"):
        unpack_checkpoint(packed)


def test_raw_encoded_and_envelope_budgets_are_hard_limits():
    with pytest.raises(ValueError, match="decoded byte budget"):
        pack_checkpoint({"large": "x"*MAX_RAW_BYTES})
    packed = pack_checkpoint({}); packed["gzip_base64"] = "A"*(MAX_ENCODED_BYTES+1)
    with pytest.raises(ValueError, match="encoded byte budget"):
        unpack_checkpoint(packed)
    packed = pack_checkpoint({}); packed["unexpected_authority"] = True
    with pytest.raises(ValueError, match="schema"):
        unpack_checkpoint(packed)


def test_realistic_repeated_checkpoint_compacts_without_changing_any_value():
    rows = [{"token": "CONTROLLED", "bid": .4, "ask": .42, "quantity": 5.0,
             "source_at": f"2026-11-06T20:{i//60:02d}:{i%60:02d}+00:00",
             "evidence": "0"*64, "trading_authority": False} for i in range(1440)]
    value = {"schema_version": "CONTROLLED", "rows": rows, "labels": rows[-128:]}
    packed = pack_checkpoint(value)
    assert unpack_checkpoint(packed) == value
    assert packed["gzip_bytes"] < packed["raw_bytes"] / 10


def test_cyclic_or_exponentially_aliased_input_cannot_hang_encoder():
    value = {}; value["self"] = value
    with pytest.raises(ValueError, match="cyclic"):
        pack_checkpoint(value)
    value = []
    for _i in range(19):
        value = [value, value]
    with pytest.raises(ValueError, match="structural node budget"):
        pack_checkpoint({"expanded": value})


def test_noncanonical_base64_padding_bits_are_rejected():
    packed = pack_checkpoint({})
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    encoded = packed["gzip_base64"]
    offset = -3 if encoded.endswith("==") else -2
    encoded = encoded[:offset] + alphabet[alphabet.index(encoded[offset]) | 1] + encoded[offset+1:]
    packed["gzip_base64"] = encoded
    with pytest.raises(ValueError, match="canonical"):
        unpack_checkpoint(packed)


def test_incompressible_checkpoint_cannot_exceed_encoded_budget():
    import random

    value = {"controlled_noise": random.Random(0).randbytes(1600000).hex()}
    with pytest.raises(ValueError, match="encoded byte budget"):
        pack_checkpoint(value)
