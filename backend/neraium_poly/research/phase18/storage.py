"""Conservative shared-filesystem budget admission; no allocation or configuration writes."""

import os
from pathlib import Path

GIB = 1024**3


def _bytes(value):
    return type(value) is int and value >= 0


def budget_capacity(service_roots, *, target_budgets, filesystem_free_bytes,
                    filesystem_capacity_bytes, reserve_bytes, temporary_headroom_bytes,
                    shared_growth_reserve_bytes):
    """Prove incremental capacity without charging already-used service bytes twice.

    Each service root is {path,current_usage_bytes,filesystem_device?}. Usage must
    conservatively include all files below that root (active/WAL, warm, cold,
    temporary, manifests, indexes, journals and caches). Free means f_bavail: do
    not add privileged ext4 reserved blocks to allocatable capacity. Other project
    use is already deducted from this free measurement. Their future growth and
    rotation overhead are explicitly withheld again as additional headroom.
    """
    fields = (filesystem_free_bytes, filesystem_capacity_bytes, reserve_bytes,
              temporary_headroom_bytes, shared_growth_reserve_bytes)
    if (not all(_bytes(v) for v in fields) or filesystem_capacity_bytes == 0
        or filesystem_free_bytes > filesystem_capacity_bytes
        or not isinstance(service_roots, dict) or not 1 <= len(service_roots) <= 16
        or not isinstance(target_budgets, dict) or set(service_roots) != set(target_budgets)):
        raise ValueError("known bounded service roots and filesystem byte observations required")
    floor = max(100*GIB, reserve_bytes)
    roots, reasons = {}, []
    for name, value in service_roots.items():
        if not isinstance(name, str) or not name or not isinstance(value, dict):
            raise ValueError("service root mapping required")
        usage, budget = value.get("current_usage_bytes"), target_budgets[name]
        if not _bytes(usage) or not _bytes(budget) or budget == 0:
            raise ValueError("finite nonnegative accounted usage and positive budgets required")
        raw = Path(value["path"]).absolute()
        if raw.is_symlink() or any(p.is_symlink() for p in raw.parents) or not raw.is_dir():
            raise ValueError("existing non-symlink service directories required")
        path, stat = raw.resolve(), raw.stat()
        if value.get("filesystem_device", stat.st_dev) != stat.st_dev:
            raise ValueError("service filesystem identity changed")
        if usage > budget:
            reasons.append("current_service_usage_exceeds_target:"+name)
        roots[name] = {"path": str(path), "device": stat.st_dev, "inode": stat.st_ino,
                       "current_usage_bytes": usage, "target_budget_bytes": budget}
    for name, left in roots.items():
        for other, right in roots.items():
            if name >= other:
                continue
            a, b = Path(left["path"]), Path(right["path"])
            if a == b or a.is_relative_to(b) or b.is_relative_to(a):
                reasons.append("overlapping_service_roots:"+name+":"+other)
    if len({r["device"] for r in roots.values()}) != 1:
        reasons.append("service_roots_not_on_one_verified_filesystem")
    current = sum(r["current_usage_bytes"] for r in roots.values())
    targets = sum(target_budgets.values())
    used_allocatable = filesystem_capacity_bytes-filesystem_free_bytes
    if current > used_allocatable:
        reasons.append("accounted_service_usage_exceeds_filesystem_used_capacity")
    incremental = sum(max(0, r["target_budget_bytes"]-r["current_usage_bytes"]) for r in roots.values())
    after_targets = filesystem_free_bytes-incremental
    protected_after = after_targets-temporary_headroom_bytes-shared_growth_reserve_bytes
    if protected_after < floor:
        reasons.append("targets_cannot_preserve_protected_free_reserve")
    return {"schema_version": "phase18-shared-capacity-v1", "approved": not reasons,
            "status": "admissible" if not reasons else "blocked", "reasons": sorted(set(reasons)),
            "service_roots": roots, "filesystem_capacity_bytes": filesystem_capacity_bytes,
            "filesystem_available_bytes": filesystem_free_bytes, "protected_free_reserve_bytes": floor,
            "current_combined_service_bytes": current, "target_combined_service_bytes": targets,
            "incremental_maximum_service_growth_bytes": incremental,
            "projected_free_at_service_caps_bytes": after_targets,
            "temporary_headroom_bytes": temporary_headroom_bytes,
            "shared_growth_reserve_bytes": shared_growth_reserve_bytes,
            "projected_free_after_all_headrooms_bytes": protected_after,
            "headroom_above_protected_floor_bytes": protected_after-floor,
            "nonservice_and_filesystem_overhead_used_bytes": max(0, used_allocatable-current),
            "accounting_scope": "all service-root logical file bytes; existing shared use already in available-space observation",
            "other_workload_warning": "Future unrelated growth can invalidate this snapshot; live global floor must remain enforced",
            "preallocation_performed": False, "configuration_changed": False,
            "infrastructure_change_authority": False, "deletion_authority": False}


def measure_service_tree(path, *, max_entries=200000):
    """Read-only bounded all-file accounting including temporary and hidden names.

    Hardlinks are conservatively charged for each pathname, matching the existing
    managed store. Cross-root hardlinks cannot reduce the capacity proof. Nested
    mounts/symlinks/unsupported files fail rather than evade byte accounting.
    """
    if type(max_entries) is not int or not 1 <= max_entries <= 2000000:
        raise ValueError("bounded service inventory required")
    root = Path(path).absolute()
    if root.is_symlink() or any(p.is_symlink() for p in root.parents) or not root.is_dir():
        raise ValueError("existing non-symlink service root required")
    device, count, logical, allocated = root.stat().st_dev, 0, 0, 0
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                count += 1
                if count > max_entries:
                    raise ValueError("service inventory entry budget exceeded")
                try:
                    if entry.is_symlink():
                        raise ValueError("symlink inside service accounting root")
                    stat = entry.stat(follow_symlinks=False)
                    if stat.st_dev != device:
                        raise ValueError("nested filesystem requires independent capacity proof")
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        logical += stat.st_size
                        allocated += stat.st_blocks*512
                    else:
                        raise ValueError("unsupported service filesystem entry")
                except FileNotFoundError:
                    # SQLite may remove its WAL/SHM after a checkpoint. Missing
                    # entries are bounded only by concurrent production activity.
                    continue
    return {"path": str(root.resolve()), "filesystem_device": device, "entries": count,
            "current_usage_bytes": logical, "allocated_path_bytes": allocated,
            "includes_active_warm_cold_temporary_manifest_and_hidden": True,
            "hardlink_pathnames_charged_conservatively": True,
            "snapshot_warning": "Concurrent writes require final remeasurement before configuration"}
