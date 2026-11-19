"""Read-only, deterministic workspace verification primitives."""
import hashlib
import py_compile
from pathlib import Path

MAX_FILE_BYTES = 2_000_000
ALLOWED_KINDS = {"exists", "contains", "sha256", "python_syntax", "changed_since"}


def _safe_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("Le chemin du fichier est obligatoire.")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError("Le chemin doit être relatif au workspace.")
    base = root.resolve()
    target = (base / candidate).resolve()
    if target == base or base not in target.parents:
        raise ValueError("Chemin refusé : accès limité au workspace.")
    return target


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_workspace(checks, workspace_root=None):
    """Evaluate explicit checks without executing workspace code or modifying files."""
    root = Path(workspace_root) if workspace_root is not None else Path(__file__).resolve().parents[1] / "workspace"
    if not isinstance(checks, list) or not 1 <= len(checks) <= 50:
        raise ValueError("Fournis entre 1 et 50 contrôles.")
    results = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ValueError(f"Contrôle {index + 1} invalide.")
        kind = check.get("kind")
        if kind not in ALLOWED_KINDS:
            raise ValueError(f"Type de contrôle non autorisé : {kind}")
        path = _safe_file(root, check.get("path"))
        item = {"index": index, "kind": kind, "path": check["path"], "passed": False}
        if not path.is_file():
            item["message"] = "Fichier absent."
            results.append(item)
            continue
        size = path.stat().st_size
        item["size_bytes"] = size
        if size > MAX_FILE_BYTES:
            item["message"] = f"Fichier trop volumineux pour vérification ({MAX_FILE_BYTES} octets max)."
            results.append(item)
            continue
        data = path.read_bytes()
        digest = _digest(data)
        item["sha256"] = digest
        if kind == "exists":
            item["passed"] = True
            item["message"] = "Fichier présent."
        elif kind == "contains":
            expected = check.get("text")
            if not isinstance(expected, str) or not expected:
                raise ValueError("Le contrôle contains exige un champ text non vide.")
            try:
                content = data.decode("utf-8")
            except UnicodeDecodeError:
                content = ""
            item["passed"] = expected in content
            item["message"] = "Texte trouvé." if item["passed"] else "Texte attendu absent."
        elif kind == "sha256":
            expected = check.get("expected")
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError("Le contrôle sha256 exige un hash expected de 64 caractères.")
            item["passed"] = digest.lower() == expected.lower()
            item["message"] = "Empreinte conforme." if item["passed"] else "Empreinte différente."
        elif kind == "changed_since":
            expected = check.get("baseline_sha256")
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError("Le contrôle changed_since exige baseline_sha256 (64 caractères).")
            item["passed"] = digest.lower() != expected.lower()
            item["message"] = "Le contenu a changé." if item["passed"] else "Aucun changement détecté."
        elif kind == "python_syntax":
            if path.suffix.lower() != ".py":
                item["message"] = "Le contrôle de syntaxe exige un fichier .py."
            else:
                try:
                    source = data.decode("utf-8")
                    compile(source, str(path), "exec")
                    item["passed"] = True
                    item["message"] = "Syntaxe Python valide (code non exécuté)."
                except (UnicodeDecodeError, SyntaxError) as exc:
                    item["message"] = f"Syntaxe Python invalide : {exc}"
        results.append(item)
    passed = sum(1 for item in results if item["passed"])
    return {"passed": passed, "failed": len(results) - passed, "total": len(results),
            "success": passed == len(results), "checks": results}
