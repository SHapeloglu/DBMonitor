# DWH İzleme Sistemi (DBMonitor) — Proje Kuralları

Çok veritabanlı DWH sağlık izleme: adapter'lar → CollectorEngine → PostgreSQL (`monitor.dwh_health_log`) → FastAPI `/metrics` → Prometheus/Alertmanager. Ayrıntı: `architect.md`. Görevler: `task.md`. Fikirler: `backlog.md`. Oturum günlüğü: `session.md`.

## Çalışma kuralları
- `main`'e doğrudan push yok. Özellik dalı + taslak PR (`gh pr create --draft`). `gh pr edit` Projects classic hatası verir: `gh api -X PATCH repos/SHapeloglu/DBMonitor/pulls/N -F body=@dosya`.
- Kodda şifre/token yok. `DB_PASS` zorunlu ortam değişkenidir; `.env` ve `config/databases.yaml` sunucuda mod 600 olmalı. Sır içeren dosyalar git'e girmemeli; mevcut durum: `config/databases.yaml` git'te izleniyor (PR #5 kapsamında çözülecek).
- Testler: `pytest` (`tests/test_api.py`, `tests/test_collector_engine.py`), lint: `ruff check .` (CI: `.github/workflows/ci.yml`). Yerelde Docker/helm olmayabilir.
- Doküman değişince `task.md` durumu, `session.md` günlüğü ve ilgili PR numarası birlikte güncellenir. Durum yazarken kodu/`git log`'u kontrol et; hafızadan yazma.
- Sunucu (Contabo): `/opt/dwh-db-monitor`, compose proje adı aynı klasör. Servis adları `postgres`, `dwh-monitor`, `prometheus`, `alertmanager`, `vault`. `dwh-monitor` imajı yerel build'dir (`build: .`); kod değişince `docker compose build dwh-monitor` gerekir, değişmediyse `up -d --no-build` yeterli.

## Güncel durum (2026-11-24)
- main (`12402de`): PR #1, #4, #6, #7, #9, #10, #11, #12, #13, #14, #16 birleşti (`gh pr list --state all`, 2026-11-24). PR #10 (`1301be4`) ve PR #16 (`12402de`) doküman birleşmeleri. Faz 0–5 görevlerinin çoğu ✅; F1-06 kısmi, F4 mantık düzeltmeleri PR #3'te (`task.md`). F0-05, F3-04, F3-07 bitti.
- Açık taslak PR'lar (2026-11-24, DRAFT): #2 retention, #3 MSSQL, #5 `${ENV}` açma (uyumsuz), #8 Helm, #15 ajan kapsam koruyucusu. Ayrıntı: `task.md`.
- main'de `DB_USER` varsayılanı `apache` (`api/main.py:53`, PR #9 birleşti). Sunucudaki DB kullanıcısı ve parola durumu 2026-11-14 itibarıyla (`.claude/findings/facts.json`); bugün doğrulanamadı.
- Adapter'lar (PostgreSQL hariç) `enabled: false` (`task.md` Faz 4–5); uzak DB şifreleri placeholder. `config/databases.yaml` bu turda okunamadı; doğrulanamadı.

---

## F6-02 Vault Entegrasyonu (Yeni)

Secrets merkezi yönetimi için HashiCorp Vault entegrasyonu yapıldı.

### Tasarım Kararı
- **Neden**: Şifreler düz metinde → güvenlik riski + Git'te ifşa
- **Nasıl**: Vault KV v2 + hvac istemcisi + adapter_registry kancası
- **Ne zaman**: Yükleme anında (kimlik bilgileri adapter registry'de çözümlenir)

### Kapsam
- Yalnızca veritabanı kimlik bilgileri (5 adaptör × {user, password})
- Uygulama sırları yok (henüz)
- Dinamik kimlik bilgisi yok (henüz)

### Dev ve Prod
- **Dev modu**: bellek içi, otomatik unseal, otomatik token üretimi
- **Prod modu**: sealed, file/Raft backend, servis hesabı token'ı, denetim logları

### Not
Vault token'ını koda gömmek anti-pattern'dir. Bunun yerine kullan:
- Kubernetes auth
- AWS IAM auth
- Ortam değişkeni + .gitignore

---

## F6-02 Vault Entegrasyonu (Oturum 11)

### Mevcut Durum (doğrulandı)
- Kimlik bilgileri şu an `config/databases.yaml` içinde düz metin. Dosya git'te izleniyor (`git ls-tree origin/main config/`); K-02 açık. Eski satır numaraları (13, 26, 39, 52, 65, 76) bu turda doğrulanamadı.
- Monitor'ün kendi DB bağlantısı ortam değişkenlerinden okunur: `DB_USER`, `DB_PASS` (`api/main.py:53-54`).
- Vault dev modda tanımlı (`docker-compose.yml`, `vault-dev`); 2026-11-14 itibarıyla sunucuda konteyner çalışmıyor (`facts.json`, `vault_running: 0`; bugün doğrulanamadı). Dev modda restart'ta veri kaybolduğu için kimlik bilgileri YAML'a taşındı (session.md, Oturum 12). `config/databases.yaml`'da `vault://` referansı olmadığı için monitor çalışma zamanında Vault okumuyor.

### Neden Vault?
Üretimde şifreler düz metin → güvenlik riski + Git'te ifşa.
Merkezi sır yönetimi gerekli.

### Neler Değişti
- Docker: Vault konteyneri (dev modu)
- Python: hvac istemcisi + adapter_registry entegrasyonu
- Yapılandırma: databases.yaml'da vault:// referansı yok; kimlik bilgileri düz metin (bkz. Mevcut Durum)
- Kurulum: VAULT_ADDR + VAULT_TOKEN ortam değişkenleri

### Nasıl Çalışır
1. adapter_registry.load_all() başladığında
2. Her DB config için _resolve_credentials() çağırılır
3. credentials: vault://... ise Vault'tan çeker (`core/adapter_registry.py:197-219`); mevcut config'te vault:// yok
4. DB adaptörü çözümlenen kimlik bilgileriyle connect() yapar

### Dev ve Prod
- Dev: bellek içi, otomatik unseal, kolay test
- Prod: sealed mod, kalıcı backend, denetim logları

### Sonraki
F6-04 tamamlandı. F6-01 Helm chart PR #8'de (taslak). Güncel liste: `task.md`.

---

## F6-06 Dokümantasyon — Tamamlandı ✅

**2026-08-16 — F6-06 Tamamlandı**

> Tarih doğrulandı (2026-11-24): commit `24ae3b7` tarihi 2026-08-16 (`git log`). session.md Oturum 11b kaydında tarih yok.

7 YAML config file + SQL schema + README:
- Tümü production-ready, fully annotated
- Vault secret path örnekleri, plain-text backup notları
- GitHub: docs/config/, docs/sql/
- Push: commit 24ae3b7

**Next:** güncel liste için `task.md`.

---

## GitHub README.md — Tamamlandı ✅

**2026-08-26 — Kapsamlı GitHub README push edildi**

Commit: e7a1183 — README.md (commit tarihi 2026-08-26, `git log`; o commit'te 389 satır. Bugünkü README.md 413 satır)

İçerik:
- Badges (Python, FastAPI, PostgreSQL, Prometheus, Docker)
- ASCII architecture diagram
- Health check categories tablosu (FR-COST/DQ/PIPE/USER/SEC)
- Supported adapters tablosu (6 adapter + driver + status)
- Quick start (4 adım)
- Configuration örnekleri (databases.yaml, notifications.yaml)
- API endpoints + Prometheus örnek çıktı
- Alert rules tablosu (6 kural)
- Database schema özeti (DDL, partitions, views)
- Adding a new database (3 adım, Teradata örneği)
- Vault integration notu
- Project status tablosu
- Tech stack tablosu

**Next:** güncel liste için `task.md` (F3-04/05/06 tamamlandı).
