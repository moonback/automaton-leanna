import subprocess
from pathlib import Path
from .config import ROOT

REPO = ROOT.parent

def validate_and_apply(patch: str):
    if len(patch.encode("utf-8")) > 50000:
        raise ValueError("Patch trop volumineux (50 Ko maximum).")
    if not (REPO / ".git").exists():
        raise RuntimeError("Le dépôt Git local est introuvable.")
    status = subprocess.run(["git","status","--porcelain"], cwd=REPO,
                            capture_output=True, text=True, timeout=10)
    if status.returncode != 0:
        raise RuntimeError(status.stderr)
    if status.stdout.strip():
        raise RuntimeError("Le dépôt contient déjà des modifications : commit ou stash requis.")
    check = subprocess.run(["git","apply","--check","--whitespace=error","-"],
                           cwd=REPO, input=patch, capture_output=True, text=True, timeout=15)
    if check.returncode:
        raise ValueError(check.stderr[-4000:] or "Patch invalide.")
    apply = subprocess.run(["git","apply","--whitespace=error","-"],
                           cwd=REPO, input=patch, capture_output=True, text=True, timeout=15)
    if apply.returncode:
        raise RuntimeError(apply.stderr[-4000:])
    tests = subprocess.run(["python","-m","compileall","-q","backend/app"],
                           cwd=REPO, capture_output=True, text=True, timeout=60)
    if tests.returncode:
        subprocess.run(["git","apply","-R","-"], cwd=REPO, input=patch,
                       capture_output=True, text=True, timeout=15)
        raise RuntimeError("Compilation échouée ; patch annulé. " + tests.stderr[-3000:])
    diff = subprocess.run(["git","diff","--stat"], cwd=REPO,
                          capture_output=True, text=True, timeout=10)
    return {"applied": True, "validation": "compileall passed",
            "diff": diff.stdout, "note": "Modifications non commitées ; revue humaine requise."}
