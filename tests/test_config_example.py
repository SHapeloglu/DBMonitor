"""Örnek yapılandırma ve gizlilik kurallarının doğrulanması.

Bu testler gerçek değer yazdırmaz; yalnızca yapısal kontrol yapar.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "config" / "databases.example.yaml"
GITIGNORE = ROOT / ".gitignore"
SECRET_CONFIG = "config/databases.yaml"

SENSITIVE_KEY_RE = re.compile(r"^\s*(user|password|connection_string):\s*(.*)$")
PLACEHOLDER_RE = re.compile(r'^(<[^<>"\s]+>|"<[^<>"\s]+>")$')


def test_example_parses_as_yaml():
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert isinstance(data.get("databases"), list)
    assert len(data["databases"]) > 0
    for entry in data["databases"]:
        assert "name" in entry
        assert "adapter" in entry


def test_example_sensitive_values_are_placeholders_only():
    bad_lines = []
    checked = 0
    for lineno, line in enumerate(
        EXAMPLE.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = SENSITIVE_KEY_RE.match(line)
        if not match:
            continue
        checked += 1
        value = match.group(2).split(" #", 1)[0].strip()
        if not PLACEHOLDER_RE.match(value):
            bad_lines.append(lineno)
    assert checked > 0, "örnekte user/password/connection_string satırı bulunamadı"
    assert not bad_lines, f"yer tutucu olmayan değer satırları: {bad_lines}"


def test_gitignore_excludes_secret_config():
    lines = [ln.strip() for ln in GITIGNORE.read_text(encoding="utf-8").splitlines()]
    assert SECRET_CONFIG in lines


def test_secret_config_not_tracked_by_git():
    git = shutil.which("git")
    if git is None:
        pytest.skip("git bulunamadı")
    result = subprocess.run(
        [git, "ls-files", SECRET_CONFIG],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("depo git deposu değil veya git komutu başarısız")
    assert result.stdout.strip() == "", "gerçek yapılandırma dosyası git'te izleniyor"
