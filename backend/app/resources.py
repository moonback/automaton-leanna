import os
import platform
import shutil
from pathlib import Path
from .config import WORKSPACE, DATA

def snapshot():
    disk = shutil.disk_usage(DATA)
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
        "limits": {"workspace_only": True, "managed_process_control": True, "python_execution": "resource-limited subprocess; not an OS sandbox", "arbitrary_process_control": False}
    }
