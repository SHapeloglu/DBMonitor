# DWH İzleme Sistemi (DBMonitor) — Proje Kuralları

Çok veritabanlı DWH sağlık izleme: adapter'lar → CollectorEngine → PostgreSQL (`monitor.dwh_health_log`) → FastAPI `/metrics` → Prometheus/Alertmanager. Ayrıntı: `architect.md`. Görevler: `task.md`. Fikirler: `backlog.md`. Oturum günlüğü: `session.md`.

## Çalışma kuralları
- `main`'e doğrudan push yok. Özellik dalı + taslak PR (`gh pr create --draft`). `gh pr edit` Projects classic hatası verir: `gh api -X PATCH repos/SHapeloglu/DBMonitor/pulls/N -F body=@dosya`.
- Kodda şifre/token yok. `DB_PASS` zorunlu ortam değişkenidir; `.env` ve `config/databases.yaml` sunucuda mod 600 olmalı. Sır içeren dosyalar git'e girmemeli: `config/databases.yaml` ve `.env` `.gitignore`'da (PR #18, `587146d`); git'teki şablon `config/databases.example.yaml` yalnızca yer tutucu içerir. Geçmiş commit'lerde düz metin parolalar hâlâ görünür (repo herkese açık); döndürme bekliyor (bkz. `task.md`).
- Testler: `pytest` (`tests/test_api.py`, `tests/test_collector_engine.py`, `tests/test_retention_manager.py`, `tests/test_config_example.py`), lint: `ruff check .` (CI: `.github/workflows/ci.yml`). Yerelde Docker/helm olmayabilir.
- Doküman değişince `task.md` durumu, `session.md` günlüğü ve ilgili PR numarası birlikte güncellenir. Durum yazarken kodu/`git log`'u kontrol et; hafızadan yazma.
- Sunucu (Contabo): `/opt/dwh-db-monitor`, compose proje adı aynı klasör. Servis adları `postgres`, `dwh-monitor`, `prometheus`, `alertmanager`, `vault`. `dwh-monitor` imajı yerel build'dir (`build: .`); kod değişince `docker compose build dwh-monitor` gerekir, değişmediyse `up -d --no-build` yeterli.

## Güncel durum (2026-11-25)
- main (`b0c0e5c`): PR #1, #2, #4, #6, #7, #9, #10, #11, #12, #13, #14, #16, #17, #18 birleşti (`gh pr list --state merged`, 2026-11-25). #2 retention tek CTE + `batch_size` doğrulaması (`b0c0e5c`); #18 sır dosyaları git'ten çıkarıldı (`587146d`).
- Açık taslak PR'lar (2026-11-25, DRAFT): #3 MSSQL (CI geçti, gerçek MSSQL testi yok), #8 Helm (CI geçti, `helm lint` yok), #15 ajan kapsam koruyucusu (CI test başarısız). #5 kapatıldı (#18 ile değiştirildi). Ayrıntı: `task.md`.
- Sunucu (Contabo) 2026-11-25'te `origin/main` `b0c0e5c` ile dağıtıldı. Compose parolaları `.env`'den okuyor (`DQ_DB_PASSWORD`, `VAULT_TOKEN`). Dağıtım öncesi yedek: `/root/yedekler/pre-deploy-20261125-1308`. Parolalar henüz döndürülmedi.
- main'de `DB_USER` varsayılanı `apache` (`api/main.py`, PR #9). Döndürme sonrası `.env` güncellenip `dwh-monitor` yeniden başlatılmalı.
- Adapter'lar (PostgreSQL hariç) `enabled: false` (`task.md` Faz 4–5); uzak DB şifreleri placeholder.

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
- Oturum 11 döneminde kimlik bilgileri `config/databases.yaml` içinde düz metindi. 2026-11-25 itibarıyla dosya git'ten çıkarıldı (PR #18, `587146d`), sunucuda yalnızca disk üzerindeki kopyası var (mod 600). K-02 kısmen kapandı: düz metin git'te değil, ama Vault kararı ve döndürme açık.
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
