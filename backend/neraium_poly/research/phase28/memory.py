"""Bounded read-only allocator/process observations, never a memory remedy."""
import ctypes
import gc
import os
import sys
import time
from collections import deque
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from threading import RLock

_FIELDS = ('arena', 'ordblks', 'smblks', 'hblks', 'hblkhd', 'usmblks',
           'fsmblks', 'uordblks', 'fordblks', 'keepcost')
_STATUS = {'VmRSS': 'rss_bytes', 'VmHWM': 'vm_hwm_bytes', 'RssAnon': 'anon_rss_bytes',
           'RssFile': 'file_rss_bytes', 'RssShmem': 'shmem_rss_bytes', 'VmSize': 'vm_size_bytes'}


class _Mallinfo2(ctypes.Structure):
    # GNU malloc.h struct mallinfo2, ten size_t fields, not old int mallinfo ABI.
    _fields_ = [(name, ctypes.c_size_t) for name in _FIELDS]


@lru_cache(maxsize=1)
def _allocator_function():
    # Cache one symbol/library reference, not one new ctypes owner per sample.
    try:
        libc = os.confstr('CS_GNU_LIBC_VERSION')
        if not isinstance(libc, str) or not libc.startswith('glibc '):
            return None, None
        function = ctypes.CDLL(None).mallinfo2
        function.argtypes = []
        function.restype = _Mallinfo2
        return libc, function
    except (AttributeError, OSError, ValueError, TypeError):
        return None, None


def allocator_snapshot():
    """Read GNU allocator counters, not live-object bytes or total RSS.

    Concurrent allocations/mmap/foreign allocators make comparisons approximate.
    No malloc_trim, garbage collection or mutable heap interventions occur.
    """
    try:
        libc, function = _allocator_function()
        if function is None:
            return {'status': 'unavailable', 'reason': 'mallinfo2_not_supported'}
        value = function()
        return {'status': 'available', 'provider': libc,
                **{name: int(getattr(value, name)) for name in _FIELDS},
                'scope': 'GNU allocator counters, not independently measured live heap or total RSS'}
    except (AttributeError, OSError, ValueError, TypeError):
        return {'status': 'unavailable', 'reason': 'mallinfo2_not_supported'}


def _read(path):
    with path.open('r', encoding='utf-8', errors='replace') as handle:
        value = handle.read(16385)
    if len(value) > 16384:
        raise ValueError('process_diagnostic_byte_budget_exceeded')
    return value


def _proc_snapshot(root):
    values = {name: None for name in _STATUS.values()}
    values.update(threads=None, minor_page_faults=None, major_page_faults=None,
                  user_cpu_ticks=None, system_cpu_ticks=None)
    errors = []
    try:
        lines = _read(root/'status').splitlines()
        for line in lines:
            key, separator, payload = line.partition(':')
            if not separator or key not in (*_STATUS, 'Threads'):
                continue
            fields = payload.split()
            if not fields or not fields[0].isdigit():
                errors.append('invalid_proc_status_counter');continue
            number = int(fields[0])
            if key == 'Threads':
                values['threads'] = number
            elif len(fields) == 2 and fields[1] == 'kB':
                values[_STATUS[key]] = number*1024
            else:
                errors.append('unsupported_proc_status_unit')
    except (OSError, ValueError, UnicodeError):
        errors.append('proc_status_unavailable')
    if values['rss_bytes'] is None and 'proc_status_unavailable' not in errors:
        errors.append('proc_rss_counter_missing')
    try:
        # comm may contain spaces or parentheses; numeric fields follow final ')'.
        fields = _read(root/'stat').rsplit(')', 1)[1].split()
        for label, index in [('minor_page_faults', 7), ('major_page_faults', 9),
                             ('user_cpu_ticks', 11), ('system_cpu_ticks', 12)]:
            raw = fields[index]
            if not raw.isdigit():
                raise ValueError('invalid_proc_stat_counter')
            values[label] = int(raw)
    except (OSError, ValueError, IndexError, UnicodeError):
        errors.append('proc_stat_unavailable')
    return values, errors


class MemorySampler:
    """At most32 bounded samples, >=5seconds apart, no heap interventions.

    RSS deltas span the previous ACCEPTED sample, not the named function alone.
    A throttled stage does not overwrite timestamps or manufacture observations.
    """
    def __init__(self, *, interval_seconds=5., capacity=32, clock=time.monotonic,
                 proc_root=Path('/proc/self'), allocator_reader=allocator_snapshot):
        if (type(interval_seconds) not in (int, float) or not 5 <= interval_seconds <= 3600
            or type(capacity) is not int or not 1 <= capacity <= 32):
            raise ValueError('bounded_memory_sampling_configuration_required')
        self.interval_seconds, self.clock = float(interval_seconds), clock
        self.proc_root, self.allocator_reader = Path(proc_root), allocator_reader
        self.history = deque(maxlen=capacity)
        self.last_at = None
        self.peak_rss_bytes = None
        self.lock = RLock()

    def sample(self, stage):
        label = ''.join(c for c in stage if 32 <= ord(c) <= 126)[:80] if type(stage) is str else 'invalid_stage'
        with self.lock:
            try:
                now = self.clock()
                if type(now) not in (int, float) or not float('-inf') < now < float('inf'):
                    raise ValueError('nonfinite_clock')
            except (OSError, ValueError, TypeError, RuntimeError):
                return {'status': 'unavailable', 'stage': label, 'reason': 'memory_clock_unavailable'}
            if self.last_at is not None:
                if now < self.last_at:
                    return {'status': 'unavailable', 'stage': label, 'reason': 'memory_clock_regression'}
                if now-self.last_at < self.interval_seconds:
                    return {'status': 'throttled', 'stage': label, 'last_sample_at': self.history[-1]['sampled_at']}
            counters, errors = _proc_snapshot(self.proc_root)
            try:
                allocated = sys.getallocatedblocks()
            except (AttributeError, RuntimeError):
                allocated = None;errors.append('allocated_blocks_unavailable')
            try:
                stats = [{k: row[k] for k in ('collections', 'collected', 'uncollectable')
                          if type(row.get(k)) is int} for row in gc.get_stats()[:3]]
            except (AttributeError, RuntimeError, TypeError):
                stats = [];errors.append('gc_stats_unavailable')
            try:
                allocator = self.allocator_reader()
                if not isinstance(allocator, dict):
                    raise TypeError('allocator_dictionary_required')
                # Only the documented fixed counters enter operational output.
                allocator = {k: v for k, v in allocator.items() if k in (*_FIELDS, 'status', 'provider', 'reason', 'scope')}
            except (OSError, ValueError, TypeError, AttributeError):
                allocator = {'status': 'unavailable', 'reason': 'allocator_diagnostic_failed'}
            previous = self.history[-1] if self.history else None
            rss = counters['rss_bytes']
            if rss is not None:
                self.peak_rss_bytes = max(rss, self.peak_rss_bytes or 0)
            sample = {'schema_version': 'phase28-memory-sample-v1', 'process_id': os.getpid(),
                      'proc_source': str(self.proc_root), 'status': 'partial' if errors else 'ok',
                      'stage': label, 'sampled_at': datetime.now(UTC).isoformat(),
                      'interval_since_previous_seconds': now-self.last_at if self.last_at is not None else None,
                      **counters, 'allocated_blocks': allocated, 'gc_stats': stats, 'allocator': allocator,
                      'rss_delta_bytes': rss-previous['rss_bytes'] if rss is not None and previous and previous['rss_bytes'] is not None else None,
                      'allocated_blocks_delta': allocated-previous['allocated_blocks'] if allocated is not None and previous and previous['allocated_blocks'] is not None else None,
                      'peak_observed_rss_bytes': self.peak_rss_bytes, 'errors': sorted(set(errors)),
                      'scope': 'read-only observation; deltas since prior accepted sample are not causal attribution'}
            self.history.append(sample)
            self.last_at = now
            return sample

    def status(self):
        with self.lock:
            return {'status': 'observed' if self.history else 'pending',
                    'sample_count_retained': len(self.history), 'maximum_samples_retained': self.history.maxlen,
                    'minimum_interval_seconds': self.interval_seconds, 'latest': self.history[-1] if self.history else None,
                    'history': list(self.history), 'peak_observed_rss_bytes': self.peak_rss_bytes,
                    'heap_interventions': False, 'risk_or_resource_limits_changed': False}
