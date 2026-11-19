import os
import platform
import shutil
from datetime import datetime
from .config import WORKSPACE, DATA

import psutil


def _workspace_inventory():
    files = []
    total_bytes = 0
    for path in WORKSPACE.rglob("*"):
        if path.is_file():
            try:
                size = path.stat().st_size
                total_bytes += size
                files.append({"path": str(path.relative_to(WORKSPACE)), "size": size})
            except OSError:
                continue
    files.sort(key=lambda item: item["path"])
    return {"file_count": len(files), "total_bytes": total_bytes, "files": files[:500]}


def snapshot(settings=None):
    """Read-only system telemetry; it never changes or terminates processes."""
    settings = settings or {"cpu_warning": 85.0, "memory_warning": 85.0, "disk_warning": 90.0}
    disk = shutil.disk_usage(DATA)
    cpu_percent = psutil.cpu_percent(interval=0.12)
    memory = psutil.virtual_memory()
    disk_percent = psutil.disk_usage(DATA).percent
    try:
        net = psutil.net_io_counters()
        network = {"bytes_sent": net.bytes_sent, "bytes_received": net.bytes_recv,
                   "packets_sent": net.packets_sent, "packets_received": net.packets_recv}
    except (OSError, AttributeError):
        network = None

    processes = []
    for proc in psutil.process_iter(["pid", "name", "memory_info", "memory_percent", "cpu_percent"]):
        try:
            info = proc.info
            mem = info.get("memory_info")
            processes.append({
                "pid": info["pid"], "name": (info.get("name") or "Inconnu")[:120],
                "cpu_percent": round(float(info.get("cpu_percent") or 0.0), 1),
                "memory_percent": round(float(info.get("memory_percent") or 0.0), 1),
                "memory_bytes": int(mem.rss) if mem else 0,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue
    processes.sort(key=lambda item: item["memory_bytes"], reverse=True)

    alerts = []
    for metric, value, threshold, label in (
        ("cpu", cpu_percent, settings["cpu_warning"], "CPU"),
        ("memory", memory.percent, settings["memory_warning"], "Mémoire"),
        ("disk", disk_percent, settings["disk_warning"], "Disque"),
    ):
        if value >= threshold:
            alerts.append({"metric": metric, "value": round(value, 1), "threshold": threshold,
                           "message": f"{label} au-dessus du seuil ({value:.1f} %)"})

    return {
        "platform": platform.platform(), "python": platform.python_version(), "pid": os.getpid(),
        "sampled_at": datetime.now().astimezone().isoformat(),
        "cpu": {"percent": round(cpu_percent, 1), "logical_cores": psutil.cpu_count(),
                "physical_cores": psutil.cpu_count(logical=False)},
        "memory": {"total_bytes": memory.total, "available_bytes": memory.available,
                   "used_bytes": memory.used, "percent": round(memory.percent, 1)},
        "storage": {"total_bytes": disk.total, "free_bytes": disk.free,
                    "used_bytes": disk.used, "percent": round(disk_percent, 1)},
        "network": network,
        "gpu": {"available": False, "reason": "Mesure GPU non prise en charge sur cette plateforme."},
        "processes": processes[:10], "alerts": alerts, "settings": settings,
        "workspace": _workspace_inventory(),
        "limits": {"workspace_only": True, "managed_process_control": True,
                   "python_execution": "Windows Job Objects et Windows Sandbox selon le profil",
                   "arbitrary_process_control": False},
    }
