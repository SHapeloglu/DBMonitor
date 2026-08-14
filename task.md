# DWH İzleme Sistemi — Görev Listesi

Durum simgeleri: ⬜ Yapılmadı · 🔄 Devam ediyor · ✅ Tamamlandı · 🔴 Bloker

---

## Faz 6 — Production hazırlık

### Hemen yap (Kritik)
| # | Görev | Durum |
|---|---|---|
| F6-02 | ✅ Secrets yönetimi — Vault kuruldu | Tamamlandı. Vault dev mode, credentials Vault'ta |
| F6-04 | 🔄 Prometheus alert rules — severity=3 → Alertmanager | Devam ediyor |
| F6-06 | ⬜ Dokümantasyon — adapter README + örnek config | Yapılmadı |

### Gerekirse yap (Düşük)
| # | Görev | Neden |
|---|---|---|
| F6-01 | Kubernetes Helm chart | Prod migrate kararı verilince |
| F6-05 | Horizontal scaling — Redis | Şu an single instance yeterli |

---

## Açık kararlar

| # | Karar | Durum | Not |
|---|---|---|---|
| K-02 | Secrets yönetimi | ✅ Vault | Dev mode, production için sealed mode gerekir |

---

## Tamamlanan görevler — Bu oturum

| Görev | Detay |
|---|---|
| F6-02 Vault Setup | Docker container, hvac client, 5 DB credential'ı Vault'ta, adapter_registry.py entegrasyonu |
