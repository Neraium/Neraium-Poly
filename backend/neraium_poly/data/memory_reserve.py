"""Return unused GNU allocator pages after bounded archive/research work.

This does not collect Python objects, discard buffers, change limits or replace
streaming. It releases only memory libc reports as already free. Unsupported
allocators remain observable and never affect evidence or risk admission.
"""
import ctypes
from threading import Lock
from time import monotonic

from neraium_poly.research.phase28.memory import allocator_snapshot


class AllocatorReserve:
    def __init__(self, *, clock=monotonic):
        self.clock = clock
        self.last_at = None
        self.lock = Lock()
        self.report = {"status": "not_checked", "attempts": 0}

    def release(self):
        with self.lock:
            now = self.clock()
            if self.last_at is not None and now - self.last_at < 60:
                return dict(self.report)
            self.last_at = now
            before = allocator_snapshot()
            free, used = before.get('fordblks', 0), before.get('uordblks', 0)
            self.report = {**self.report, "status": "not_required", "free_before_bytes": free,
                           "allocated_before_bytes": used}
            if before.get('status') != 'available':
                self.report['status'] = 'unavailable'
            elif free >= 64 * 1024**2 and free > 2 * used:
                try:
                    trim = ctypes.CDLL(None).malloc_trim
                    trim.argtypes = [ctypes.c_size_t]
                    trim.restype = ctypes.c_int
                    start = monotonic()
                    changed = trim(0)
                    self.report.update(status='attempted', attempts=self.report['attempts'] + 1,
                                       pages_released=bool(changed), elapsed_seconds=monotonic() - start)
                except (AttributeError, OSError):
                    self.report['status'] = 'unavailable'
            return dict(self.report)
