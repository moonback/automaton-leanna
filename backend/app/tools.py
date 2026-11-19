import subprocess,sys
from .config import WORKSPACE
def safe_path(relative:str):
 p=(WORKSPACE/relative).resolve()
 if p!=WORKSPACE and WORKSPACE not in p.parents:raise ValueError("Chemin refusé : accès limité au workspace.")
 return p
def list_files():
 return [str(p.relative_to(WORKSPACE)) for p in WORKSPACE.rglob("*") if p.is_file()][:300]
def read_file(path:str):
 p=safe_path(path)
 if not p.is_file():raise FileNotFoundError(path)
 if p.stat().st_size>200000:raise ValueError("Fichier trop volumineux (limite 200 Ko).")
 return p.read_text(encoding="utf-8")
def write_file(path:str,content:str):
 p=safe_path(path);p.parent.mkdir(parents=True,exist_ok=True)
 if len(content.encode("utf-8"))>200000:raise ValueError("Contenu trop volumineux.")
 p.write_text(content,encoding="utf-8");return f"Fichier écrit : {p.relative_to(WORKSPACE)}"
def run_python(path:str):
 p=safe_path(path)
 if not p.is_file() or p.suffix.lower()!=".py":raise ValueError("Seuls les scripts .py existants du workspace sont exécutables.")
 r=subprocess.run([sys.executable,str(p)],cwd=WORKSPACE,capture_output=True,text=True,timeout=15,shell=False)
 return {"returncode":r.returncode,"stdout":r.stdout[-8000:],"stderr":r.stderr[-8000:]}
