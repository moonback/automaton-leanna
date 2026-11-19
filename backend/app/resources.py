import os
import platform
import shutil
import psutil
from .config import WORKSPACE, DATA

def snapshot():
    disk = shutil.disk_usage(str(DATA))
    memory = psutil.virtual_memory()
    network = psutil.net_io_counters()
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
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "pid": os.getpid(),
        "workspace": {"file_count": len(files), "total_bytes": total_bytes, "files": files[:500]},
        "storage": {"total_bytes": disk.total, "free_bytes": disk.free},
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": memory.percent,
            "memory_used_bytes": memory.used,
            "memory_total_bytes": memory.total,
            "disk_percent": round((disk.used / disk.total) * 100, 1) if disk.total else 0,
            "network_sent_bytes": network.bytes_sent,
            "network_received_bytes": network.bytes_recv,
            "gpu_available": False
        },
        "limits": {"workspace_only": True, "managed_process_control": True, "python_execution": "resource-limited subprocess; not an OS sandbox", "arbitrary_process_control": False}
    }
