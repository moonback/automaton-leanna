import re
import subprocess
import sys
from .config import ROOT, AUTO_IMPROVE_ENABLED

REPO = ROOT.parent

def validate_and_apply(patch: str):
    if not AUTO_IMPROVE_ENABLED:
        raise PermissionError("Auto-amélioration désactivée. Active AUTO_IMPROVE_ENABLED=true après sauvegarde.")
    if len(patch.encode("utf-8")) > 50000:
        raise ValueError("Patch trop volumineux (50 Ko maximum).")
    paths = re.findall(r"^(?:\+\+\+ b/|--- a/)(.+)$", patch, flags=re.MULTILINE)
    if not paths or any(not p.startswith("backend/app/") or ".." in p.split("/") for p in paths):
        raise ValueError("Seuls les fichiers backend/app/ peuvent être modifiés par auto-amélioration.")
    if not (REPO / ".git").exists():
        raise RuntimeError("Le dépôt Git local est introuvable.")
    status = subprocess.run(["git","status","--porcelain"], cwd=REPO,
                            capture_output=True, text=True, timeout=10)
    if status.returncode or status.stdout.strip():
        raise RuntimeError("Le dépôt doit être propre avant toute auto-amélioration.")
    check = subprocess.run(["git","apply","--check","--whitespace=error","-"],
                           cwd=REPO, input=patch, capture_output=True, text=True, timeout=15)
    if check.returncode:
        raise ValueError(check.stderr[-4000:] or "Patch invalide.")
    apply = subprocess.run(["git","apply","--whitespace=error","-"],
                           cwd=REPO, input=patch, capture_output=True, text=True, timeout=15)
    if apply.returncode:
        raise RuntimeError(apply.stderr[-4000:])
    tests = subprocess.run([sys.executable,"-m","compileall","-q","backend/app"],
                           cwd=REPO, capture_output=True, text=True, timeout=60)
    if tests.returncode:
        subprocess.run(["git","apply","-R","-"], cwd=REPO, input=patch,
                       capture_output=True, text=True, timeout=15)
        raise RuntimeError("Compilation échouée ; patch annulé. " + tests.stderr[-3000:])
    diff = subprocess.run(["git","diff","--stat"], cwd=REPO,
                          capture_output=True, text=True, timeout=10)
    return {"applied":True,"validation":"compileall passed","diff":diff.stdout,
            "note":"Modifications non commitées ; revue humaine et commit requis."}
