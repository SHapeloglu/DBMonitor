# Alt ajan kapsam sözleşmesi

Lider her yazan alt ajan için şunu yapar:

1. Worktree açar: `git worktree add .claude/worktrees/<görev> -b agent/<görev> origin/main`
2. `.claude/scope/<görev>.json` yazar (örnek: `_ornek.json`). Dosya adı worktree klasör adıyla aynı olmalı.
3. Ajanı o worktree'de çalıştırır (görev metnine izinli yolları ve bitiş koşulunu da yazar).
4. Ajan bitince `python3 .claude/hooks/scope_check.py <görev> origin/main` çalıştırır; çıkış 0 değilse iş reddedilir.

Hook (`.claude/hooks/scope_guard.py`) yalnızca alt ajanlara (girdide `agent_id` olan çağrılar) kapsam uygular:
kapsam içi = izin sorulmaz, kapsam dışı = onay sorulur, sırlar / main'e push / korunan `.claude` dosyaları = sert engel.
Lider için yalnızca main'e push, force push ve main üzerinde commit engellidir.
Sözleşmesi olmayan worktree'de yazma yoktur. Analiz ajanları yalnızca `.claude/findings/` içine yazar.
İhlaller `.claude/scope/violations.jsonl` dosyasına eklenir. Bu bir korkuluktur, güvenlik sınırı değildir.
