import os
import re
import subprocess
import sys
from .config import ROOT, AUTO_IMPROVE_ENABLED

REPO = ROOT.parent
# Every header git apply uses to pick a target path, not only ---/+++ (renames/copies have none).
PATH_LINE = re.compile(r"^(?:\+\+\+ b/|--- a/|rename from |rename to |copy from |copy to )(.+)$", re.MULTILINE)
DIFF_GIT = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.MULTILINE)
SYMLINK_MODE = re.compile(r"mode 120000\s*$", re.MULTILINE)


def check_patch_paths(patch: str):
    """Fail closed unless every touched path is a plain file under backend/app/."""
    paths = PATH_LINE.findall(patch)
    for old, new in DIFF_GIT.findall(patch):
        paths += [old, new]
    if not paths or any(not p.startswith("backend/app/") or ".." in p.split("/") for p in paths):
        raise ValueError("Seuls les fichiers backend/app/ peuvent être modifiés par auto-amélioration.")
    if SYMLINK_MODE.search(patch):
        raise ValueError("Les liens symboliques sont refusés.")
    return paths


def _revert(patch):
    subprocess.run(["git","apply","-R","-"], cwd=REPO, input=patch,
                   capture_output=True, text=True, timeout=15)


def validate_and_apply(patch: str):
    if not AUTO_IMPROVE_ENABLED:
        raise PermissionError("Auto-amélioration désactivée. Active AUTO_IMPROVE_ENABLED=true après sauvegarde.")
    if len(patch.encode("utf-8")) > 50000:
        raise ValueError("Patch trop volumineux (50 Ko maximum).")
    check_patch_paths(patch)
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
    compiled = subprocess.run([sys.executable,"-m","compileall","-q","backend/app"],
                              cwd=REPO, capture_output=True, text=True, timeout=60)
    if compiled.returncode:
        _revert(patch)
        raise RuntimeError("Compilation échouée ; patch annulé. " + compiled.stderr[-3000:])
    try:
        tests = subprocess.run([sys.executable,"-m","unittest","discover","-s","tests"],
                               cwd=REPO / "backend", env={**os.environ, "PYTHONPATH": "."},
                               capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        _revert(patch)
        raise RuntimeError("Tests trop longs (> 300 s) ; patch annulé.")
    if tests.returncode:
        _revert(patch)
        raise RuntimeError("Tests en échec ; patch annulé. " + tests.stderr[-3000:])
    diff = subprocess.run(["git","diff","--stat"], cwd=REPO,
                          capture_output=True, text=True, timeout=10)
    return {"applied":True,"validation":"compileall + unittest passed","diff":diff.stdout,
            "note":"Modifications non commitées ; revue humaine et commit requis."}
