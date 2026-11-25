# DWH DB Monitor

> Çok veritabanlı Veri Ambarı sağlık izleme platformu (prod: tek sunucuda Docker Compose; açık kararlar için bkz. `task.md`)

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://postgresql.org)
[![Prometheus](https://img.shields.io/badge/Prometheus-2.x-orange.svg)](https://prometheus.io)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://docker.com)
Lisans: henüz belirlenmedi

DWH DB Monitor, Veri Ambarı veritabanlarınızın kalitesini, maliyetini, pipeline bütünlüğünü, güvenliğini ve kullanıcı davranışını sürekli kontrol eden eklenti tabanlı bir sağlık izleme platformudur. PostgreSQL, MSSQL, MySQL, MariaDB, Oracle ve genel ODBC kaynakları için adaptör içerir (PostgreSQL dışındakiler henüz gerçek bağlantı bilgileriyle etkinleştirilmedi) — yeni bir veritabanı eklemek kabaca 150 satır Python ve 3 satır YAML gerektirir.

---

## İçindekiler

- [Mimari](#mimari)
- [Özellikler](#özellikler)
- [Sağlık Kontrolü Kategorileri](#sağlık-kontrolü-kategorileri)
- [Hızlı Başlangıç](#hızlı-başlangıç)
- [Yapılandırma](#yapılandırma)
- [API Endpoint'leri](#api-endpointleri)
- [Alarmlar](#alarmlar)
- [Yeni Veritabanı Ekleme](#yeni-veritabanı-ekleme)
- [Proje Durumu](#proje-durumu)

---

## Mimari

```
+----------------------------------------------------------------+
|  Source Databases                                              |
|  PostgreSQL  MSSQL  MySQL  MariaDB  Oracle  ODBC              |
+-------------------------+--------------------------------------+
                          |  native drivers
+-------------------------v--------------------------------------+
|  Collector Engine  (Python / FastAPI / APScheduler)          |
|                                                                 |
|  AdapterRegistry -----> DBAdapter ABC                         |
|  (YAML-driven,          connect()                              |
|   importlib)            collect_metrics()  --> MetricSchema  |
|                         health_check()                         |
|                                                                 |
|  CollectorEngine  (circuit breaker + scheduler)               |
|  Notifier         (SMTP / Slack / PagerDuty / Teams)          |
|  RetentionManager (24-month active + cold archive)            |
+----------+--------------------+------------------------------+
           |                    |
+----------v------+   +---------v---------+
|  dwh_health_log |   |  /metrics         |
|  PostgreSQL 16  |   |  Prometheus format|
|  24-month       |   |  port 8005        |
|  partitioned    |   +---+---------------+
+----------+------+       |
           |                +---> Prometheus (9090)
           |                          |
           |                      Alertmanager (9093)
           |
           +---> Power BI / Tableau / Superset / super_bi
                  (direct SQL connection to dwh_health_log)
```

(Kaynak veritabanları yerel sürücülerle Collector Engine'e bağlanır. Engine, YAML ile yönetilen AdapterRegistry üzerinden adaptörleri yükler; sonuçlar 24 ay bölümlenmiş `dwh_health_log` tablosuna ve Prometheus formatındaki `/metrics` endpoint'ine yazılır. Raporlama araçları tabloya doğrudan SQL ile bağlanır.)

**Temel tasarım ilkesi:** Collector Engine veritabanı türünü asla bilmez; yalnızca `adapter.collect_metrics()` çağırır. Yeni veritabanı eklemek engine'de değişiklik gerektirmez.

---

## Özellikler

- **Eklenti mimarisi** — DBAdapter ABC + AdapterRegistry; yeni DB = ~150 satır Python + 3 satır YAML
- **İki çıkış noktası** — `dwh_health_log` PostgreSQL tablosu (SQL ile sorgulanabilir) + `/metrics` HTTP endpoint'i (Prometheus formatı); belirli bir panele bağımlılık yok
- **5 kontrol kategorisi** — Maliyet, Veri Kalitesi, Pipeline, Kullanıcı Davranışı, Güvenlik
- **Bağımsız Notifier** — SMTP, Slack, PagerDuty, Teams, genel webhook; DB'ye özgü stored procedure yok
- **Merkezi RetentionManager** — 24 ay aktif saklama + soğuk arşiv (yerel; S3 / Azure Blob planlandı, henüz uygulanmadı)
- **Circuit breaker** — adaptör başına hata yalıtımı; ardışık 3 hata devreyi açar, 300 sn bekler
- **Prometheus + Alertmanager** — hazır 6 alarm kuralı (kritik, güvenlik, pipeline, uyarı, kriz, tüm adaptörler kapalı)
- **HashiCorp Vault (isteğe bağlı)** — `vault://` URI ile kimlik bilgisi çözümleme; düz metin kimlik bilgisi de kabul edilir (K-02 açık)

---

## Sağlık Kontrolü Kategorileri

| Kod | Kategori | Neyi Kontrol Eder |
|------|----------|----------------|
| **FR-COST** | Maliyet | Kullanılmayan tablolar (30+ gün), tablo şişmesi, bölümlenmemiş büyük tablolar |
| **FR-DQ** | Veri Kalitesi | Yüksek NULL oranı (>%50), eksik PK/UNIQUE, format ihlalleri |
| **FR-PIPE** | Pipeline | Günlük yükleme yok, şema değişiklikleri, mükerrer yüklemeler |
| **FR-USER** | Kullanıcı Davranışı | Uzun süren sorgular, mesai dışı büyük sorgular |
| **FR-SEC** | Güvenlik | Maskelenmemiş hassas kolonlar, yetkisiz erişim |

Önem derecesi (severity): 1 = bilgi | 2 = uyarı | 3 = kritik

---

## Hızlı Başlangıç

### Ön koşullar

- Docker + Docker Compose v2
- Git

### 1. Klonla

```bash
git clone https://github.com/SHapeloglu/DBMonitor.git
cd DBMonitor
```

### 2. Yapılandır

```bash
cp docs/config/databases.yaml config/databases.yaml
# UYARI: `config/databases.yaml` ve `.env` git'e girmez (`.gitignore`). Kopyadaki değerler yer tutucudur; gerçek parolayı yalnızca yerel dosyada tutun. Mümkünse vault:// referansı kullanın (bkz. Vault bölümü).
# config/databases.yaml dosyasını düzenle:
#   - veritabanın için host, port, db_name ve kimlik bilgilerini gir
#   - etkin olmasını istediğin adaptörlerde enabled: true yap
```

### 3. Ortam dosyasını oluştur

`.env` dosyası oluşturun: `DQ_DB_PASSWORD=<güçlü parola>` ve `VAULT_TOKEN=<token>` (compose `DQ_DB_PASSWORD`'ü zorunlu tutar; `.env` git'e girmez, sunucuda mod 600 olmalı).

### 4. Başlat

```bash
export VAULT_TOKEN=<your-vault-token>   # Vault kullanmıyorsan boş bırak
docker compose up -d --build
```

### 5. Doğrula

```bash
# Sağlık kontrolü
curl http://localhost:8005/health

# Prometheus metrikleri
curl http://localhost:8005/metrics

# Prometheus arayüzü
open http://localhost:9090

# Alertmanager arayüzü
open http://localhost:9093
```

---

## Yapılandırma

Tüm yapılandırma `config/` altındadır. Açıklamalı referans kopyalar `docs/config/` içindedir.

### databases.yaml

```yaml
databases:
  - name: prod-postgresql
    adapter: adapters.postgresql_adapter.PostgreSQLAdapter
    host: postgres
    port: 5432
    db_name: dwhmonitor
    db_type: postgresql
    connect_timeout_s: 10
    query_timeout_s: 30
    enabled: true
    credentials:
      user: apache
      password: <APACHE_PAROLASI>        # veya: vault://db/postgres-local

  - name: prod-mssql
    adapter: adapters.mssql_adapter.MSSQLAdapter
    host: <DB_HOST>
    port: 1433
    db_name: DWH_PROD
    db_type: mssql
    enabled: false             # kimlik bilgilerini girdikten sonra true yap
    credentials:
      user: etl_svc
      password: <ETL_SVC_PAROLASI>
```

### notifications.yaml

```yaml
notifications:
  - channel: smtp
    enabled: false
    threshold: "severity >= 3"
    smtp_host: mail.company.com
    to: [dwh-team@company.com]

  - channel: slack_webhook
    enabled: false
    threshold: "severity >= 2"
    webhook_url: https://hooks.slack.com/services/XXX/YYY/ZZZ
```

### Yapılandırma Dosyaları

| Dosya | Amaç |
|------|---------|
| `config/databases.yaml` | DB adaptör tanımları |
| `config/notifications.yaml` | Alarm kanalları (SMTP, Slack, PagerDuty, Teams, webhook) |
| `config/retention.yaml` | 24 ay saklama + soğuk arşiv backend'i |
| `config/prometheus/prometheus.yml` | Prometheus scrape yapılandırması |
| `config/prometheus/rules/dwh-health.yml` | 6 Prometheus alarm kuralı |
| `config/alertmanager.yml` | Alertmanager yönlendirme ve alıcıları |

---

## API Endpoint'leri

| Endpoint | Metot | Açıklama |
|----------|--------|-------------|
| `/health` | GET | Adaptör durumu ve engine sağlığı (kimlik doğrulama yok) |
| `/metrics` | GET | Prometheus exposition formatı |
| `/collect` | GET | Toplamayı elle tetikler (toplama zaten sürüyorsa HTTP 409) |
| `/logs` | GET | Filtreli JSON liste: `db_name`, `kontrol_kodu`, `sonuc`, `severity`, `since`, `until`, `limit` (varsayılan 100, en çok 1000), `offset` |
| `/logs/summary` | GET | Kategori bazlı özet |
| `/adapters` | GET | Adaptörlerin circuit breaker durumu |

**API anahtarı:** `API_KEY` ortam değişkeni tanımlıysa `/health` dışındaki endpoint'ler `X-API-Key` başlığı ister (yanlışsa 401). Tanımlı değilse kimlik doğrulama kapalıdır ve başlangıçta uyarı loglanır. Üretimde tanımla; Prometheus kullanıyorsan scrape yapılandırmasına başlık ekle.

### /metrics Örnek Çıktısı

```
# HELP dwh_health_check DWH saglık kontrol sonucu (0=OK, 2=WARNING, 3=ERROR)
# TYPE dwh_health_check gauge
dwh_health_check{db_type="postgresql",host="postgres",db_name="dwhmonitor",kategori="maliyet",kontrol_kodu="FR-COST-01",kontrol_adi="<kontrol adı>",sonuc="WARNING"} 2
dwh_health_check{db_type="postgresql",host="postgres",db_name="dwhmonitor",kategori="guvenlik",kontrol_kodu="FR-SEC-01",kontrol_adi="<kontrol adı>",sonuc="OK"} 0
```

---

## Alarmlar

Hazır 6 Prometheus alarm kuralı:

| Alarm | Koşul | Süre | Önem |
|--------|-----------|-----|----------|
| `DWHCriticalHealthIssue` | `last_over_time(dwh_health_check[70m]) == 3` | 5m | critical |
| `DWHSecurityThreat` | `last_over_time(dwh_health_check{kategori="guvenlik"}[70m]) == 3` | 1m | critical |
| `DWHPipelineBreakdown` | `last_over_time(dwh_health_check{kategori="pipeline"}[70m]) == 3` | 10m | critical |
| `DWHWarningIssue` | `last_over_time(dwh_health_check[70m]) == 2` | 15m | warning |
| `DWHMultipleCategoriesCritical` | 3'ten fazla kategoride değer 3 (pencereli, 70m) | 10m | critical |
| `DWHAllAdaptersDown` | `absent_over_time(dwh_health_check[2h])` veya scrape hedefi düşük | 5m | critical |

Alıcıları `config/alertmanager.yml` içinde yapılandır. Şu an 16. satırdaki alıcı `http://localhost:5001/alerts` olup compose'da bu portu dinleyen servis yok; gerçek alıcı karar bekliyor (2026-11-25).

---

## Veritabanı Şeması

`dwh_health_log` — PostgreSQL 16, `monitor` şeması

Sadeleştirilmiş özet; tam DDL `sql/dwh_health_log.sql` (CHECK kısıtları bu özette yok).

```sql
CREATE TABLE monitor.dwh_health_log (
    id               BIGSERIAL,
    kontrol_tarihi   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    db_type          VARCHAR(20)  NOT NULL,
    host             VARCHAR(255) NOT NULL,
    db_name          VARCHAR(255) NOT NULL,
    kategori         kategori_tip NOT NULL,
    kontrol_kodu     VARCHAR(30)  NOT NULL,
    kontrol_adi      VARCHAR(100) NOT NULL,
    sonuc            sonuc_tip    NOT NULL,
    severity         SMALLINT     NOT NULL,
    etkilenen_obje   VARCHAR(255),
    etkilenen_sayi   INTEGER,
    detay            TEXT,
    PRIMARY KEY (id, kontrol_tarihi)
) PARTITION BY RANGE (kontrol_tarihi);
```

- **24 aylık bölüm** (2025-01'den 2026-12'ye); 2027 bölümleri retention işiyle eklenir; bkz. `task.md` F0-02
- Panel ve alarm sorguları için optimize edilmiş **5 index**
- **3 view:** `v_son_24s_ozet`, `v_aktif_sorunlar`, `v_trend_7gun`
- **Arşiv tablosu:** 24 aydan eski satırlar için `dwh_health_log_archive`
- **Stored procedure:** RetentionManager'ın çağırdığı `add_monthly_partition(date)`

Tam DDL: [`docs/sql/dwh_health_log.sql`](docs/sql/dwh_health_log.sql)

---

## Yeni Veritabanı Ekleme

### Adım 1 - Adaptörü yaz (~150 satır)

```python
# adapters/teradata_adapter.py
from core.base_adapter import DBAdapter, HealthResult, DBMetadata
from core.metric_schema import MetricSchema, Kategori, Sonuc

class TeradataAdapter(DBAdapter):
    def connect(self): ...
    def disconnect(self): ...
    def health_check(self) -> HealthResult: ...
    def get_metadata(self) -> DBMetadata: ...
    def collect_metrics(self) -> list[MetricSchema]:
        metrics = []
        metrics.extend(self._check_amp_skew())
        metrics.extend(self._check_perm_space())
        metrics.extend(self._check_slow_queries())
        return metrics
```

### Adım 2 - databases.yaml'a blok ekle

```yaml
  - name: prod-teradata
    adapter: adapters.teradata_adapter.TeradataAdapter
    host: <DB_HOST>
    db_type: teradata
    enabled: true
    credentials:
      user: etl_svc
      password: <ETL_SVC_PAROLASI>
```

### Adım 3 - Yeniden başlat

```bash
docker compose restart dwh-monitor
```

Engine kodunda değişiklik yok. Yeni adaptör AdapterRegistry üzerinden otomatik bulunur.

---

## Portlar

| Servis | Port | Amaç |
|---------|------|---------|
| dwh-monitor | 8005 | FastAPI - /health, /metrics, /logs, /adapters |
| Prometheus | 9090 | Metrik toplama + alarm kuralı değerlendirme |
| Alertmanager | 9093 | Alarm yönlendirme ve tekilleştirme |
| PostgreSQL | 5433 | dwh_health_log depolama (host portu) |
| Vault | 8200 | Sır yönetimi (dev modu) |

---

## Vault Entegrasyonu

Kimlik bilgileri HashiCorp Vault'tan (KV v2, `secret/data/db/<ad>`) `vault://` URI ile çözülebilir. Düz metin kimlik bilgisi de desteklenir; bu K-02 kapsamında açık bir konudur.

```yaml
# tüm kimlik bilgisi sözlüğü Vault'tan:
credentials: vault://db/<ad>

# veya alan bazında:
credentials:
  user: etl_svc
  password: vault://db/<ad>
```

Vault konteyneri yeniden başladıktan sonra (dev modu):

```bash
export VAULT_TOKEN=<new-token>
python scripts/vault-init.py   # host üzerinden çalıştır
docker compose restart dwh-monitor
```

---

## Saklama (Retention)

RetentionManager, DB'nin kendi TTL'inden veya bölümlemesinden bağımsız çalışır:

- **Aktif:** `dwh_health_log` içinde 24 ay
- **Arşiv:** 24 aydan eski satırlar tek bir SQL ifadesiyle (`DELETE ... RETURNING` → `INSERT`) `dwh_health_log_archive`'a taşınır; batch'ler `batch_size` ile bölünür (PR #2, `b0c0e5c`)
- **Backend'ler:** yerel dosya sistemi (varsayılan); S3 ve Azure Blob planlandı (henüz uygulanmadı)

---

## Proje Durumu

| Aşama | Açıklama | Durum |
|--------|-------------|--------|
| F0 | Altyapı - DDL, Docker, ön kontrol | Bitti |
| F0-05 | CI - GitHub Actions (ruff, pytest, docker build) | Bitti |
| F1 | Çekirdek engine - registry, scheduler, notifier, retention | Kısmi (retention yalnızca yerel arşiv; F1-06) |
| F2 | PostgreSQL adaptörü (referans uygulama) | Bitti |
| F3 | API katmanı - /health, /metrics, /logs, /adapters, API anahtarı | Bitti |
| F4 | MSSQL adaptörü - 8 FR kontrolü, ODBC Driver 18 | Bitti, kimlik bilgisi bekleniyor; mantık düzeltmeleri PR #3 (taslak) |
| F5 | MySQL, MariaDB, Oracle, Genel ODBC adaptörleri | Bitti, kimlik bilgisi bekleniyor |
| F6-02 | HashiCorp Vault entegrasyonu | Kısmi: dev modda, sunucuda durmuş. Düz metin git'ten çıktı (PR #18); döndürme ve Vault kararı açık (K-02) |
| F6-04 | Prometheus alarm kuralları (6 kural) + Alertmanager | Bitti (kurallar PR #11 ile düzeltildi) |
| F6-06 | Belgeler - yapılandırma dosyaları, SQL şeması | Bitti |
| F6-01 | Kubernetes Helm chart | Taslak PR (#8), test bekliyor |
| F6-03 | Grafana panel JSON'u | Ertelendi |
| F6-05 | Yatay ölçekleme - Redis koordinasyonu | Planlandı |
| - | IBM DB2 adaptörü | Rakip analizi bekleniyor |
| - | MongoDB adaptörü | Rakip analizi bekleniyor |
| - | Teradata adaptörü | Rakip analizi bekleniyor |

---

## Teknoloji Yığını

| Katman | Teknoloji |
|-------|------------|
| API Engine | Python 3.12, FastAPI, APScheduler |
| Veri doğrulama | Pydantic v2 |
| DB sürücüleri | psycopg2, pyodbc, pymysql, python-oracledb |
| Metrikler | Prometheus, Alertmanager |
| Sırlar | HashiCorp Vault |
| Depolama | PostgreSQL 16 (bölümlenmiş) |
| Kurulum | Docker Compose (şu an prod dahil tek sunucuda); Helm chart planlı (PR #8) |
