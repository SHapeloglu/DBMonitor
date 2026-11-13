#!/usr/bin/env python3
"""
scope_check.py <görev> [taban-ref]  — bitiş sonrası mekanik kapsam denetimi (ajan değil, script).

.claude/worktrees/<görev> içindeki dal farkını (taban-ref..HEAD + çalışma ağacı) .claude/scope/<görev>.json
sözleşmesinin "write" / "deny_write" desenleriyle karşılaştırır. Dışarı taşan dosya varsa exit 1.
Taban varsayılanı: origin/main.
"""
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from scope_guard import SCOPES, WORKTREES, matches_any  # noqa: E402

def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__); return 2
    task, base = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "origin/main")
    wt = WORKTREES / task
    sc = SCOPES / f"{task}.json"
    if not wt.is_dir() or not sc.is_file():
        print(f"HATA: worktree ({wt}) ya da sözleşme ({sc}) yok"); return 2
    scope = json.loads(sc.read_text(encoding="utf-8"))
    def git(*a): return subprocess.run(["git", "-C", str(wt), *a], capture_output=True, text=True).stdout.split("\n")
    files = {f for f in git("diff", "--name-only", f"{base}...HEAD") + git("diff", "--name-only") + git("ls-files", "--others", "--exclude-standard") if f}
    bad = sorted(f for f in files if matches_any(f, scope.get("deny_write", [])) or not matches_any(f, scope.get("write", [])))
    print(f"görev={task} değişen={len(files)} kapsam dışı={len(bad)}")
    for f in bad: print("  KAPSAM DIŞI:", f)
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
