#!/usr/bin/env python3
"""
scope_guard.py — PreToolUse kapsam koruyucusu (agentic loop mimarisi).

Girdi: Claude Code'un hook JSON'u (stdin). Çıktı: izin kararı JSON'u (stdout), her zaman exit 0.
Hook çökerse karar verilmez (varsayılan izin akışı çalışır); kasıtlı "deny" yalnızca burada üretilir.

Kimin için ne:
  * LİDER (girdide agent_id yok): yalnızca iki sert kural — main'e push/force push ve main üzerinde commit.
  * ALT AJAN (agent_id var): tam kapsam denetimi.
      - Yazma: yalnızca scratchpad, .claude/findings/ ve kendi worktree'si içinde, scope sözleşmesinin
        "write" desenleriyle eşleşen dosyalar. Sözleşme yoksa worktree'de yazma yok.
      - Okuma: yalnızca repo ve /tmp/claude-1000 altı. Sırlar (.env, secrets/, config/databases.yaml,
        config/notifications.yaml, restic parolası, ssh anahtarları) hiçbir koşulda okunamaz.
      - Bash: izinli komut listesi (salt okunur + test/lint + sınırlı git). Listede olmayan komut onay ister.
      - ssh: yalnızca "contabo" sunucusuna ve yalnızca salt okunur komutlar. scp/rsync/sftp onay ister.
      - git: push, pull, checkout/reset/clean/rebase/merge yok; commit main üzerinde yok.

Kararlar:
  deny  -> sert engel (sırlar, main'e push, korunan .claude dosyaları, main'de commit)
  ask   -> kapsam dışı; kullanıcıya onay sorulur
  allow -> kapsam içi; izin istenmez
  (boş) -> karar verme, normal izin akışı

Bu bir güvenlik sınırı değil, korkuluktur: kabuk komutlarını statik inceler, her yolu kapatamaz.
Gerçek yalıtım worktree + bitiş sonrası scope_check.py farkı ile sağlanır.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLAUDE_DIR = REPO / ".claude"
WORKTREES = CLAUDE_DIR / "worktrees"
FINDINGS = CLAUDE_DIR / "findings"
SCOPES = CLAUDE_DIR / "scope"
VIOLATIONS = SCOPES / "violations.jsonl"
TMP_ROOT = Path("/tmp/claude-1000")
SSH_HOST = "contabo"

SECRET_PATH_RE = re.compile(
    r"(^|/)\.env(\.[\w.-]+)?$"
    r"|(^|/)secrets?(/|$)"
    r"|(?:^|/)(?<!docs/)config/(databases|notifications)\.yaml$"
    r"|restic_parola"
    r"|(^|/)\.ssh(/|$)|id_(rsa|ed25519|ecdsa)"
    r"|\.(pem|key|p12|pfx)$"
)
# Bash komut metninde sır ipuçları (komut içindeki yollar için).
SECRET_CMD_RE = re.compile(
    r"(^|[\s/='\"])\.env(\.[\w.-]+)?(\s|$|['\"])"
    r"|/secrets?/|(?<!docs/)config/(databases|notifications)\.yaml"
    r"|restic_parola|\.ssh/|id_(rsa|ed25519|ecdsa)|\.pem\b|\.restic_"
    r"|\$\{?(RESTIC_PASS\w*|VAULT_TOKEN|DB_PASS|DQ_DB_PASSWORD|API_KEY)\b|\b(printenv|env)\s*($|[|;&])"
)

READONLY_CMDS = {
    "ls", "pwd", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "sort", "uniq", "cut", "tr",
    "diff", "stat", "file", "basename", "dirname", "realpath", "echo", "printf", "true", "false", "test", "[",
    "nl", "date", "which", "column", "paste", "comm", "du", "df", "id", "whoami",
}
GIT_ALLOWED = {
    "status", "diff", "log", "show", "rev-parse", "ls-files", "blame", "grep", "add", "commit",
    "branch", "describe", "shortlog", "cat-file", "ls-tree", "merge-base", "name-rev", "rev-list",
    "fetch",
}
GIT_BRANCH_RO = {"--show-current", "-vv", "-v", "--list", "-a", "-r", "--contains", "--merged", "--no-merged"}
SSH_REMOTE_OK = {
    "ls", "cat", "head", "tail", "wc", "grep", "stat", "file", "df", "du", "date", "uptime", "hostname", "whoami",
    "id", "find", "pwd", "echo", "sort", "uniq", "cut", "tr", "diff", "sed", "crontab", "docker", "restic",
    "systemctl", "journalctl", "ps", "free", "ss", "git",
}
DOCKER_RO = {"ps", "logs", "inspect", "images", "version", "info", "stats", "top", "port", "diff"}
RESTIC_RO = {"snapshots", "ls", "stats", "check", "cat", "find", "diff", "version"}


# ----------------------------------------------------------------------------- yardımcılar

def glob_to_re(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        c = pattern[i]
        if pattern[i:i + 3] == "**/":
            out += "(?:.*/)?"
            i += 3
        elif pattern[i:i + 2] == "**":
            out += ".*"
            i += 2
        elif c == "*":
            out += "[^/]*"
            i += 1
        elif c == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(c)
            i += 1
    return re.compile("^" + out + "$")


def matches_any(rel: str, patterns: list[str]) -> bool:
    return any(glob_to_re(p).match(rel) for p in patterns)


def resolve(path: str, cwd: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(cwd) / p
    return Path(os.path.realpath(p))


def under(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def log_violation(data: dict, decision: str, reason: str, target: str) -> None:
    try:
        SCOPES.mkdir(parents=True, exist_ok=True)
        with open(VIOLATIONS, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "agent_id": data.get("agent_id"), "agent_type": data.get("agent_type"),
                "tool": data.get("tool_name"), "decision": decision, "reason": reason, "target": target[:300],
            }, ensure_ascii=False) + "\n")
    except OSError:
        pass


def emit(data: dict, decision: str | None, reason: str = "", target: str = "") -> None:
    if decision is None:
        return
    if decision in ("deny", "ask"):
        log_violation(data, decision, reason, target)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False))


def current_branch(cwd: str) -> str:
    try:
        return subprocess.run(["git", "-C", cwd, "branch", "--show-current"], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def load_scope(task: str) -> dict | None:
    f = SCOPES / f"{task}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def task_of(p: Path) -> tuple[str, Path] | None:
    """p bir worktree içindeyse (görev adı, worktree kökü) döner."""
    if not under(p, WORKTREES):
        return None
    rel = p.relative_to(WORKTREES)
    if not rel.parts:
        return None
    return rel.parts[0], WORKTREES / rel.parts[0]


# ----------------------------------------------------------------------------- dosya araçları

def check_write(data: dict, path: str) -> None:
    cwd = data.get("cwd") or str(REPO)
    p = resolve(path, cwd)
    if under(p, TMP_ROOT) or under(p, FINDINGS):
        return emit(data, "allow", "scratchpad/findings")
    if SECRET_PATH_RE.search(str(p.relative_to(REPO)) if under(p, REPO) else str(p)):
        return emit(data, "deny", "Sır dosyalarına yazılamaz.", str(p))
    if under(p, CLAUDE_DIR):
        t = task_of(p)
        if t is None:
            return emit(data, "deny", ".claude altı (ayar, hook, sözleşme) alt ajana kapalı.", str(p))
        task, root = t
        scope = load_scope(task)
        if scope is None:
            return emit(data, "deny", f"'{task}' için kapsam sözleşmesi yok (.claude/scope/{task}.json). Lider yazmalı.", str(p))
        rel = str(p.relative_to(root))
        if matches_any(rel, scope.get("deny_write", [])) or not matches_any(rel, scope.get("write", [])):
            return emit(data, "ask", f"Kapsam dışı yazma: {rel} (izinli: {scope.get('write')})", str(p))
        return emit(data, "allow", f"kapsam içi: {task}")
    if under(p, REPO):
        return emit(data, "ask", "Ana checkout'a yazma kapsam dışı; görev worktree'sinde çalışın.", str(p))
    return emit(data, "ask", "Repo dışına yazma kapsam dışı.", str(p))


def check_read(data: dict, path: str | None) -> None:
    cwd = data.get("cwd") or str(REPO)
    p = resolve(path or cwd, cwd)
    shown = str(p.relative_to(REPO)) if under(p, REPO) else str(p)
    if SECRET_PATH_RE.search(shown):
        return emit(data, "deny", "Sır dosyası okunamaz.", str(p))
    if not (under(p, REPO) or under(p, TMP_ROOT)):
        return emit(data, "ask", "Repo dışı okuma kapsam dışı.", str(p))


# ----------------------------------------------------------------------------- bash

SED_UNSAFE_RE = re.compile(r"(^|[/;\s])[0-9,$]*[we]\s|/[a-zA-Z]*[we][a-zA-Z]*(;|\s|$)")
REDIR_OK_RE = re.compile(r"(?:\d?>\s*/dev/null|&>\s*/dev/null|2>&1|\d>&\d)")


def tokenize(cmd: str) -> list[list[str]] | None:
    """Komutu operatörlere göre bölüp argv listeleri döner. Yeniden yönlendirme ya da yerine koyma varsa None."""
    stripped = REDIR_OK_RE.sub(" ", cmd)
    if "$(" in stripped or "`" in stripped or "<<" in stripped or "<(" in stripped or ">(" in stripped:
        return None
    lex = shlex.shlex(stripped, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    segs: list[list[str]] = [[]]
    try:
        for tok in lex:
            if tok in (";", "&&", "||", "|", "&", "\n"):
                segs.append([])
            elif set(tok) <= set("<>()&;|") and tok:
                return None  # yeniden yönlendirme ya da alt kabuk
            else:
                segs[-1].append(tok)
    except ValueError:
        return None
    return [s for s in segs if s]


def git_check(argv: list[str], data: dict, cwd: str, subagent: bool) -> tuple[str, str] | None:
    """(karar, neden) ya da None (uygun)."""
    args = argv[1:]
    # -C <yol> / -c k=v seçeneklerini atla
    work = cwd
    while args and args[0].startswith("-"):
        if args[0] == "-C" and len(args) > 1:
            work = str(resolve(args[1], cwd))
            args = args[2:]
        elif args[0] == "-c" and len(args) > 1:
            args = args[2:]
        else:
            args = args[1:]
    if not args:
        return None
    sub, rest = args[0], args[1:]
    branch = current_branch(work)
    if sub == "push":
        refs = [a for a in rest if not a.startswith("-")]
        dest = [r.split(":")[-1].removeprefix("refs/heads/") for r in refs[1:]] or ([branch] if branch else [])
        if any(a in ("-f", "--force", "--force-with-lease") or a.startswith("--force") for a in rest):
            return "deny", "Force push yasak."
        if any(d in ("main", "master") for d in dest) or (not refs and branch in ("main", "master")):
            return "deny", "main'e doğrudan push yasak (tek onay kapısı: birleştirme)."
        if subagent:
            return "ask", "Alt ajan push yapmaz; lider doğrulamadan sonra iter."
        return None
    if sub == "commit" and branch in ("main", "master"):
        return "deny", "main üzerinde commit yasak; özellik dalı kullanın."
    if not subagent:
        return None
    if sub == "pull":
        return "ask", "git pull alt ajana kapalı."
    if sub not in GIT_ALLOWED:
        return "ask", f"git {sub} kapsam dışı."
    if sub == "branch" and not all(a in GIT_BRANCH_RO for a in rest):
        return "ask", "git branch yalnızca salt okunur kullanılabilir."
    if sub == "add" and any(a in (".", "-A", "--all", "-u") for a in rest):
        return "ask", "git add . / -A yerine açık dosya yolu verin (kapsam)."
    return None


def ssh_check(argv: list[str], data: dict) -> tuple[str, str]:
    args = argv[1:]
    host = None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "-i", "-p", "-l", "-F", "-J"):
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        host = a
        i += 1
        break
    if host != SSH_HOST:
        return "ask", f"ssh yalnızca '{SSH_HOST}' için; '{host}' kapsam dışı."
    remote = " ".join(args[i:])
    if not remote:
        return "ask", "Etkileşimli ssh oturumu kapsam dışı."
    if SECRET_CMD_RE.search(remote):
        return "deny", "Sunucuda sır dosyası okunamaz."
    remote_chk = REDIR_OK_RE.sub(" ", remote)
    if re.search(r"(^|[^&])>|<|\$\(|`|\brm\b|\bmv\b|\bcp\b|\bchmod\b|\bchown\b|\btee\b|\bsed\s+-i|\bdd\b|\bkill\b|\bsystemctl\s+(start|stop|restart|enable|disable)", remote_chk):
        return "ask", "Sunucuda yazma/değiştirme olabilecek komut."
    for seg in re.split(r"\s*(?:&&|\|\||;|\|)\s*", remote.strip()):
        try:
            w = shlex.split(seg)
        except ValueError:
            return "ask", "Uzak komut ayrıştırılamadı."
        if not w:
            continue
        c = w[0]
        if c == "crontab":
            if w[1:] != ["-l"]:
                return "ask", "Yalnızca crontab -l."
        elif c == "docker":
            sub = next((x for x in w[1:] if not x.startswith("-")), "")
            if sub == "compose":
                sub2 = [x for x in w[1:] if not x.startswith("-")][1:2]
                if not sub2 or sub2[0] not in ("ps", "logs", "config", "images"):
                    return "ask", "docker compose yalnızca ps/logs/config/images."
            elif sub == "exec":
                return "ask", "docker exec kapsam dışı."
            elif sub not in DOCKER_RO:
                return "ask", f"docker {sub} kapsam dışı."
        elif c == "restic":
            sub = next((x for x in w[1:] if not x.startswith("-") and not x.startswith("/")), "")
            if sub not in RESTIC_RO:
                return "ask", f"restic {sub} kapsam dışı."
        elif c == "sed":
            if "-n" not in w[1:]:
                return "ask", "sed yalnızca -n ile."
        elif c == "find":
            if any(x in w for x in ("-delete", "-exec", "-execdir", "-ok", "-fprint", "-fls")):
                return "ask", "find yazma/çalıştırma seçeneği içeriyor."
        elif c == "git":
            sub = next((x for x in w[1:] if not x.startswith("-") and not x.startswith("/")), "")
            if sub not in ("status", "log", "diff", "show", "branch", "rev-parse"):
                return "ask", f"uzak git {sub} kapsam dışı."
        elif c == "systemctl":
            if not (len(w) > 1 and w[1] in ("status", "is-active", "list-units", "list-timers", "show")):
                return "ask", "systemctl yalnızca salt okunur alt komutlar."
        elif c == "journalctl" or c in SSH_REMOTE_OK:
            pass
        else:
            return "ask", f"uzak komut '{c}' izinli listede değil."
    return "allow", "salt okunur ssh"


def check_bash(data: dict) -> None:
    cmd = (data.get("tool_input") or {}).get("command", "")
    cwd = data.get("cwd") or str(REPO)
    subagent = bool(data.get("agent_id"))
    segs = tokenize(cmd)

    # Lider: yalnızca git push/commit sert kuralları.
    if not subagent:
        if segs is None:
            return
        for argv in segs:
            if argv and argv[0] == "git":
                r = git_check(argv, data, cwd, False)
                if r:
                    return emit(data, r[0], r[1], cmd)
        return

    # --- alt ajan ---
    if SECRET_CMD_RE.search(cmd):
        return emit(data, "deny", "Komut sır dosyalarına/değişkenlerine dokunuyor.", cmd)
    task = task_of(resolve(cwd, cwd))
    if task is None:
        m = re.search(r"\.claude/worktrees/([\w.-]+)", cmd)
        task = (m.group(1), WORKTREES / m.group(1)) if m else None
    scope = load_scope(task[0]) if task else None
    if scope:
        for extra in scope.get("bash_extra", []):
            if cmd.strip() == extra or cmd.strip().startswith(extra + " "):
                return emit(data, "allow", "scope bash_extra")
    if segs is None:
        return emit(data, "ask", "Yeniden yönlendirme, alt kabuk veya heredoc içeren komut kapsam dışı.", cmd)
    if not segs:
        return
    for argv in segs:
        while argv and re.match(r"^[A-Za-z_]\w*=", argv[0]):  # W=/yol gibi değişken atamaları komut değildir
            argv = argv[1:]
        if not argv:
            continue
        c = Path(argv[0]).name
        if c == "cd":
            tgt = resolve(argv[1] if len(argv) > 1 else str(REPO), cwd)
            if not (under(tgt, REPO) or under(tgt, TMP_ROOT)):
                return emit(data, "ask", "cd repo dışına.", cmd)
        elif c == "git":
            r = git_check(argv, data, cwd, True)
            if r:
                return emit(data, r[0], r[1], cmd)
        elif c == "ssh":
            d, why = ssh_check(argv, data)
            if d != "allow":
                return emit(data, d, why, cmd)
        elif c in ("scp", "rsync", "sftp", "nc", "curl", "wget"):
            return emit(data, "ask", f"{c} kapsam dışı (ağ/dosya aktarımı).", cmd)
        elif c in ("pytest", "ruff"):
            if c == "ruff" and (argv[1:2] != ["check"] or "--fix" in argv or "--unsafe-fixes" in argv):
                return emit(data, "ask", "ruff yalnızca 'check' (düzeltmesiz).", cmd)
        elif c in ("python3", "python"):
            mods = ("pytest", "py_compile", "ruff")
            a = argv[1:]
            ok = (len(a) > 1 and a[0] == "-m" and a[1] in mods) or (len(a) > 2 and a[0] == "-I" and a[1] == "-m" and a[2] in mods)
            if not ok:
                return emit(data, "ask", "python yalnızca -m pytest/py_compile/ruff.", cmd)
        elif c == "bash":
            if argv[1:2] != ["-n"]:
                return emit(data, "ask", "bash yalnızca -n (sözdizimi).", cmd)
        elif c == "sed":
            if any(a.startswith("-i") or a == "--in-place" for a in argv[1:]) or any(SED_UNSAFE_RE.search(a) for a in argv[1:] if not a.startswith("-")):
                return emit(data, "ask", "sed yerinde düzenleme / w / e komutu içeremez.", cmd)
        elif c == "awk":
            if any(("system(" in a or "getline" in a or '| "' in a or "|&" in a or "> " in a) for a in argv[1:]) or "-i" in argv[1:2]:
                return emit(data, "ask", "awk betiği komut çalıştırma/yazma içeremez.", cmd)
        elif c == "find":
            if any(x in argv for x in ("-delete", "-exec", "-execdir", "-ok", "-fprint", "-fls")):
                return emit(data, "ask", "find yazma/çalıştırma seçeneği içeriyor.", cmd)
        elif c == "jq":
            if any(a in ("-i", "--in-place") for a in argv[1:]):
                return emit(data, "ask", "jq yerinde düzenleme.", cmd)
        elif c in READONLY_CMDS:
            pass
        else:
            return emit(data, "ask", f"'{c}' izinli komut listesinde yok.", cmd)
    return emit(data, "allow", "izinli salt okunur/test komutları")


# ----------------------------------------------------------------------------- giriş

def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    subagent = bool(data.get("agent_id"))
    if tool == "Bash":
        return check_bash(data)
    if not subagent:
        return
    if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        return check_write(data, ti.get("file_path") or ti.get("notebook_path") or "")
    if tool == "Read":
        return check_read(data, ti.get("file_path"))
    if tool in ("Grep", "Glob"):
        return check_read(data, ti.get("path"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # hook hatası işi engellemesin
        print(f"scope_guard hata: {exc!r}", file=sys.stderr)
    sys.exit(0)
