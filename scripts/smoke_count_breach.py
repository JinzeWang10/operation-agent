"""Probe HostFeatures.breaches to understand sort/threshold discrepancies."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main() -> int:
    from big_data_model.incident.features import HOST_THRESHOLDS, extract

    payload = ast.literal_eval(
        (REPO / "big_data_model/incident/sample/text.txt").read_text(encoding="utf-8")
    )
    bag = extract(payload)
    hf = bag.hosts
    print(f"Total hosts: {hf.host_count}")
    print(f"Thresholds: {HOST_THRESHOLDS}")
    print()
    for k, ips in hf.breaches.items():
        print(f"  {k}: {len(ips)} host(s)")
    print()
    union = set()
    for ips in hf.breaches.values():
        union.update(ips)
    print(f"Union of breaches: {len(union)} host(s)")
    print(f"Active alarm hosts: {sum(1 for a in hf.alarms if a.is_active)}")

    print()
    print("Per-host breach detail (host: cpu/mem/iow/disk):")
    breached = []
    for h in hf.hosts:
        flags = []
        if h.cpu_pct > HOST_THRESHOLDS["cpu_high_pct"]: flags.append("CPU")
        if h.memory_pct > HOST_THRESHOLDS["memory_high_pct"]: flags.append("MEM")
        if h.iowait_pct > HOST_THRESHOLDS["iowait_high_pct"]: flags.append("IOW")
        if h.disk_pct > HOST_THRESHOLDS["disk_high_pct"]: flags.append("DISK")
        if flags:
            breached.append((h.host, h.cpu_pct, h.memory_pct, h.iowait_pct, h.disk_pct, flags))
    print(f"  hosts breaching at least one threshold: {len(breached)}")
    for host, cpu, mem, iow, disk, flags in breached[:5]:
        print(f"    {host}  cpu={cpu:.1f} mem={mem:.1f} iow={iow:.4f} disk={disk:.0f}  {flags}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
