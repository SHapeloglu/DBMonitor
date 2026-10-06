# DWH DB Monitor

> Üretime hazır, çok veritabanlı Veri Ambarı sağlık izleme platformu

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://postgresql.org)
[![Prometheus](https://img.shields.io/badge/Prometheus-2.x-orange.svg)](https://prometheus.io)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

DWH DB Monitor, Veri Ambarı veritabanlarınızın kalitesini, maliyetini, pipeline bütünlüğünü, güvenliğini ve kullanıcı davranışını sürekli kontrol eden eklenti tabanlı bir sağlık izleme platformudur. PostgreSQL, MSSQL, MySQL, MariaDB, Oracle ve ODBC uyumlu her veritabanını kutudan çıktığı gibi destekler — yeni bir veritabanı eklemek kabaca 150 satır Python ve 3 satır YAML gerektirir.

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
- **Merkezi RetentionManager** — 24 ay aktif saklama + soğuk arşiv (yerel / S3 / Azure Blob)
- **Circuit breaker** — adaptör başına hata yalıtımı; ardışık 3 hata devreyi açar
- **Prometheus + Alertmanager** — hazır 6 alarm kuralı (kritik, güvenlik, pipeline, uyarı, kriz, tüm adaptörler kapalı)
- **HashiCorp Vault** — `vault://` URI formatıyla kimlik bilgisi çözümleme

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
# config/databases.yaml dosyasını düzenle:
#   - veritabanın için host, port, db_name ve kimlik bilgilerini gir
#   - etkin olmasını istediğin adaptörlerde enabled: true yap
```

### 3. Başlat

```bash
export VAULT_TOKEN=<your-vault-token>   # Vault kullanmıyorsan boş bırak
docker compose up -d --build
```

### 4. Doğrula

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
      user: dquser
      password: dqpass          # veya: vault://secret/dwh/postgresql

  - name: prod-mssql
    adapter: adapters.mssql_adapter.MSSQLAdapter
    host: 10.0.0.5
    port: 1433
    db_name: DWH_PROD
    db_type: mssql
    enabled: false             # kimlik bilgilerini girdikten sonra true yap
    credentials:
      user: etl_svc
      password: changeme
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
| `/health` | GET | Adaptör durumu ve engine sağlığı |
| `/metrics` | GET | Prometheus exposition formatı |

### /metrics Örnek Çıktısı

```
# HELP dwh_health_check DWH health check result
# TYPE dwh_health_check gauge
dwh_health_check{db_type="postgresql",host="postgres",db_name="dwhmonitor",kategori="maliyet",kontrol_kodu="FR-COST-01",sonuc="WARNING"} 2
dwh_health_check{db_type="postgresql",host="postgres",db_name="dwhmonitor",kategori="guvenlik",kontrol_kodu="FR-SEC-01",sonuc="OK"} 0
```

---

## Alarmlar

Hazır 6 Prometheus alarm kuralı:

| Alarm | Koşul | Süre | Önem |
|--------|-----------|-----|----------|
| `DWHCriticalHealthIssue` | severity=3 olan herhangi bir metrik | 5m | critical |
| `DWHSecurityThreat` | Güvenlik kategorisinde severity=3 | 1m | critical |
| `DWHPipelineBreakdown` | Pipeline kategorisinde severity=3 | 10m | critical |
| `DWHWarningIssue` | severity=2 olan herhangi bir metrik | 15m | warning |
| `DWHMultipleCategoriesCritical` | 3'ten fazla kritik sorun | 10m | critical |
| `DWHAllAdaptersDown` | Hiç metrik alınmıyor | 5m | critical |

Alıcıları `config/alertmanager.yml` içinde yapılandır.

---

## Veritabanı Şeması

`dwh_health_log` — PostgreSQL 16, `monitor` şeması

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

- **24 aylık bölüm** (2025-01'den 2026-12'ye)
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
    host: 10.0.0.10
    db_type: teradata
    enabled: true
    credentials:
      user: etl_svc
      password: changeme
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
| dwh-monitor | 8005 | FastAPI - /health, /metrics |
| Prometheus | 9090 | Metrik toplama + alarm kuralı değerlendirme |
| Alertmanager | 9093 | Alarm yönlendirme ve tekilleştirme |
| PostgreSQL | 5433 | dwh_health_log depolama (host portu) |
| Vault | 8200 | Sır yönetimi (dev modu) |

---

## Vault Entegrasyonu

Kimlik bilgileri `vault://` URI formatıyla HashiCorp Vault'ta saklanabilir:

```yaml
credentials:
  user: etl_svc
  password: vault://secret/dwh/postgresql
```

Vault konteyneri yeniden başladıktan sonra (dev modu):

```bash
export VAULT_TOKEN=<new-token>
python vault-init.py          # host üzerinden çalıştır
docker compose restart dwh-monitor
```

---

## Saklama (Retention)

RetentionManager, DB'nin kendi TTL'inden veya bölümlemesinden bağımsız çalışır:

- **Aktif:** `dwh_health_log` içinde 24 ay
- **Arşiv:** 24 aydan eski satırlar `dwh_health_log_archive`'a taşınır
- **Backend'ler:** yerel dosya sistemi (varsayılan), S3, Azure Blob

---

## Proje Durumu

| Aşama | Açıklama | Durum |
|--------|-------------|--------|
| F0 | Altyapı - DDL, Docker, ön kontrol | Bitti |
| F1 | Çekirdek engine - registry, scheduler, notifier, retention | Bitti |
| F2 | PostgreSQL adaptörü (referans uygulama) | Bitti |
| F3 | API katmanı - /health, /metrics | Bitti |
| F4 | MSSQL adaptörü - 8 FR kontrolü, ODBC Driver 18 | Bitti, kimlik bilgisi bekleniyor |
| F5 | MySQL, MariaDB, Oracle, Genel ODBC adaptörleri | Bitti, kimlik bilgisi bekleniyor |
| F6-02 | HashiCorp Vault entegrasyonu | Bitti |
| F6-04 | Prometheus alarm kuralları (6 kural) + Alertmanager | Bitti |
| F6-06 | Belgeler - yapılandırma dosyaları, SQL şeması | Bitti |
| F6-01 | Kubernetes Helm chart | Planlandı |
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
| Kurulum | Docker Compose (dev), Kubernetes + Helm (prod) |
