# dwh-monitor Helm Chart

DWH Health Monitor'ü (FastAPI + in-process APScheduler collector) Kubernetes üzerinde çalıştırmak için Helm chart'ı. Roadmap: F6-01.

> **Durum:** Taslak. `helm lint` / `helm template` bu commit'te çalıştırılmadı (helm kurulu değil). Bir cluster'a kurmadan önce `helm lint` ve `helm template` çalıştırın.

## Önkoşullar

- Helm 3.x
- Image: `image.repository` ile gösterilen registry'de yayınlanmış dwh-monitor image'ı (varsayılan `REPLACE_ME/dwh-monitor` bir placeholder'dır)
- Metrik (PostgreSQL) veritabanı için şifreyi içeren bir Secret

## Gerekli Secret

Chart şifreyi değer olarak almaz. Namespace içinde önceden bir Secret oluşturun ve adını `existingSecret` ile verin (varsayılan: `dwh-monitor-db`):

```bash
kubectl -n <namespace> create secret generic dwh-monitor-db \
  --from-literal=DB_PASS='<metrik-db-sifresi>'
```

| Secret adı | Anahtar | Kullanım |
|---|---|---|
| `dwh-monitor-db` (`existingSecret`) | `DB_PASS` | Metrik DB parolası, `secretKeyRef` ile `DB_PASS` env değişkenine bağlanır |

Başka anahtar beklenmez. İzleme hedeflerinin (databases.yaml içindeki) kimlik bilgileri de bu chart'ta yönetilmez; bkz. "Kapsam dışı".

## Kurulum

```bash
helm install dwh-monitor ./helm/dwh-monitor \
  --namespace dwh-monitor --create-namespace \
  --set image.repository=<registry>/dwh-monitor \
  --set image.tag=<tag> \
  --set env.DB_HOST=<metrik-db-host>
```

Gerçek izleme için kendi config dizininizden bir ConfigMap oluşturup chart'a bağlayın:

```bash
kubectl -n dwh-monitor create configmap dwh-monitor-config \
  --from-file=databases.yaml=config/databases.yaml \
  --from-file=notifications.yaml=config/notifications.yaml \
  --from-file=retention.yaml=config/retention.yaml

helm upgrade --install dwh-monitor ./helm/dwh-monitor -n dwh-monitor \
  --set config.existingConfigMap=dwh-monitor-config
```

Doğrulama:

```bash
kubectl -n dwh-monitor port-forward svc/dwh-monitor 8005:8005
curl -s http://127.0.0.1:8005/health
```

## Config dosyaları

`files/config/` altındaki `databases.yaml`, `notifications.yaml`, `retention.yaml` chart ile birlikte gelir. Bunlar `config/` klasöründeki dosyaların **temizlenmiş kopyalarıdır**:

- Tüm `password`, `user`, `smtp_*`, `Authorization` değerleri `REPLACE_ME` yapıldı.
- Tüm izleme hedefleri ve bildirim kanalları `enabled: false`.

Bu varsayılanlar yalnızca chart'ın render edilebilmesi ve pod'un açılabilmesi içindir; gerçek izleme için `config.existingConfigMap` ile kendi ConfigMap'inizi verin. Gerçek parola veya token'ı `values.yaml`, chart dosyaları veya Git'e koymayın.

Not: `files/config/` ile `config/` dizini ayrı tutulur (Helm `.Files.Get` chart dizini dışındaki dosyaları okuyamaz). `config/` değiştiğinde `files/config/` da güncellenmelidir.

## Önemli değerler

| Anahtar | Varsayılan | Açıklama |
|---|---|---|
| `replicaCount` | `1` | Collector pod içinde çalışır. 1'den fazla replica aynı toplamayı iki kez yapar. F6-05 (Redis koordinasyonu) yapılmadan artırmayın. |
| `image.repository` / `image.tag` | `REPLACE_ME/dwh-monitor` / `""` | Boş tag, `Chart.appVersion` kullanır |
| `service.port` | `8005` | Uygulama portu (`uvicorn ... --port 8005`) |
| `env.*` | DB_HOST, DB_PORT, DB_NAME, DB_USER, COLLECT_CRON, RETENTION_CRON | Secret olmayan ortam değişkenleri |
| `existingSecret` | `dwh-monitor-db` | `DB_PASS` anahtarını içeren Secret |
| `config.existingConfigMap` | `""` | Boşsa `files/config/` ConfigMap'i üretilir |
| `ingress.enabled` | `false` | Ingress isteğe bağlı |
| `serviceMonitor.enabled` | `false` | Prometheus Operator CRD'si gerektirir |
| `probes.*` | `/health` port `8005` | Liveness ve readiness |

Deployment `strategy: Recreate` kullanır; rollout sırasında iki collector'ın aynı anda çalışmasını önler.

## Kapsam dışı

Bu chart şunları **içermez**:

- **Vault:** `VAULT_ADDR` / `VAULT_TOKEN` değişkenleri eklenmedi. Vault entegrasyonu (F6-02) için Kubernetes auth veya ayrı bir secret yönetimi gerekir.
- **Prometheus alert kuralları:** F6-04 dosyaları (`config/prometheus/`) chart'a dahil değil. ServiceMonitor yalnızca scrape tanımlar.
- **Grafana dashboard:** F6-03 ertelendi.
- **Redis / yatay ölçekleme:** F6-05 yapılmadı; `replicaCount` 1 olmalı.
- **Arşiv depolama:** `retention.yaml` varsayılan olarak `/opt/dwh-db-monitor/archive` yerel yolunu kullanır. Bu yol için kalıcı volume bağlanmaz.
- **Image güvenliği:** Dockerfile'da `USER` tanımlı değil; pod root olarak çalışır. `runAsNonRoot` bu nedenle ayarlanmadı.

## Şablonları kontrol etme

```bash
helm lint ./helm/dwh-monitor
helm template test ./helm/dwh-monitor --set image.repository=example/dwh-monitor
```
