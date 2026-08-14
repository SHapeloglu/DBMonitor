"""
core/notifier.py
================
DB'den bağımsız bildirim modülü.
SMTP, Slack, PagerDuty, Teams, generic webhook destekler.
DB'ye özgü mail SP'lerine (sp_send_dbmail, UTL_MAIL vb.) bağımlılık yok.
"""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import requests
import yaml

from core.metric_schema import MetricSchema

logger = logging.getLogger(__name__)


class NotifierError(Exception):
    pass


class Notifier:
    """
    notifications.yaml'dan kural listesi okur.
    CollectorEngine her koleksiyon sonrası evaluate() çağırır.
    """

    def __init__(self, config_path: str = "config/notifications.yaml"):
        self._config_path = Path(config_path)
        self._rules: list[dict] = []

        if self._config_path.exists():
            self._load_config()
        else:
            logger.warning("notifications.yaml bulunamadı, bildirim devre dışı.")

    def _load_config(self) -> None:
        with open(self._config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        self._rules = cfg.get("notifications", [])
        logger.info("Notifier hazır: %d kural yüklendi.", len(self._rules))

    # ------------------------------------------------------------------
    # Ana giriş noktası
    # ------------------------------------------------------------------

    def evaluate(self, metrics: list[MetricSchema]) -> dict:
        """
        Metrik listesini kurallara göre değerlendir, eşleşenlere bildirim gönder.

        Dönüş:
          {"sent": int, "failed": int, "skipped": int}
        """
        result = {"sent": 0, "failed": 0, "skipped": 0}

        if not self._rules:
            return result

        for rule in self._rules:
            if not rule.get("enabled", True):
                result["skipped"] += 1
                continue

            channel   = rule.get("channel", "")
            threshold = rule.get("threshold", "severity >= 3")

            matched = self._filter(metrics, threshold)
            if not matched:
                continue

            try:
                self._dispatch(channel, rule, matched)
                result["sent"] += 1
                logger.info(
                    "Bildirim gönderildi: channel=%s, eşleşen=%d",
                    channel, len(matched),
                )
            except Exception as exc:
                result["failed"] += 1
                logger.error("Bildirim hatası [%s]: %s", channel, exc)

        return result

    # ------------------------------------------------------------------
    # Threshold değerlendirme
    # ------------------------------------------------------------------

    def _filter(self, metrics: list[MetricSchema], threshold: str) -> list[MetricSchema]:
        """
        Threshold string'ini güvenli eval ile değerlendir.

        Desteklenen ifadeler:
          "severity >= 3"
          "severity == 3 and kategori == 'guvenlik'"
          "sonuc == 'ERROR'"
        """
        result = []
        for m in metrics:
            try:
                match = eval(
                    threshold,
                    {"__builtins__": {}},
                    {
                        "severity": m.severity,
                        "kategori": m.kategori,
                        "sonuc":    m.sonuc,
                        "db_type":  m.db_type,
                    },
                )
                if match:
                    result.append(m)
            except Exception as exc:
                logger.warning("Threshold eval hatası '%s': %s", threshold, exc)
        return result

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, channel: str, rule: dict, metrics: list[MetricSchema]) -> None:
        dispatch_map = {
            "smtp":           self._send_smtp,
            "slack_webhook":  self._send_slack,
            "pagerduty":      self._send_pagerduty,
            "teams_webhook":  self._send_teams,
            "webhook":        self._send_webhook,
        }
        fn = dispatch_map.get(channel)
        if fn is None:
            raise NotifierError(f"Bilinmeyen bildirim kanalı: '{channel}'")
        fn(rule, metrics)

    # ------------------------------------------------------------------
    # SMTP
    # ------------------------------------------------------------------

    def _send_smtp(self, rule: dict, metrics: list[MetricSchema]) -> None:
        host     = rule["smtp_host"]
        port     = rule.get("smtp_port", 587)
        user     = rule.get("smtp_user", "")
        password = rule.get("smtp_password", "")
        from_    = rule["from"]
        to_list  = rule["to"] if isinstance(rule["to"], list) else [rule["to"]]

        subject = f"[DWH Monitor] {len(metrics)} uyarı — " \
                  f"{sum(1 for m in metrics if m.severity == 3)} kritik"

        body = self._build_html_body(metrics)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = from_
        msg["To"]      = ", ".join(to_list)
        msg.attach(MIMEText(body, "html", "utf-8"))

        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls(context=context)
            if user and password:
                server.login(user, password)
            server.sendmail(from_, to_list, msg.as_string())

        logger.debug("SMTP gönderildi → %s", to_list)

    # ------------------------------------------------------------------
    # Slack
    # ------------------------------------------------------------------

    def _send_slack(self, rule: dict, metrics: list[MetricSchema]) -> None:
        webhook_url = rule["webhook_url"]
        critical    = [m for m in metrics if m.severity == 3]
        warning     = [m for m in metrics if m.severity == 2]

        emoji = "🚨" if critical else "⚠️"
        text  = (
            f"{emoji} *DWH Health Alert*\n"
            f"Kritik: {len(critical)} | Uyarı: {len(warning)}"
        )

        attachments = []
        for m in metrics[:10]:
            color = "#FF0000" if m.severity == 3 else "#FFA500"
            attachments.append({
                "color": color,
                "fields": [
                    {"title": "Kontrol",  "value": m.kontrol_kodu, "short": True},
                    {"title": "DB",       "value": f"{m.db_type}/{m.db_name}", "short": True},
                    {"title": "Sonuç",    "value": m.sonuc, "short": True},
                    {"title": "Severity", "value": str(m.severity), "short": True},
                    {"title": "Detay",    "value": m.detay or "-", "short": False},
                ],
            })

        payload = {"text": text, "attachments": attachments}
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # PagerDuty
    # ------------------------------------------------------------------

    def _send_pagerduty(self, rule: dict, metrics: list[MetricSchema]) -> None:
        integration_key = rule["integration_key"]
        top = metrics[0]

        payload = {
            "routing_key": integration_key,
            "event_action": "trigger",
            "payload": {
                "summary":   f"DWH Monitor: {top.kontrol_kodu} — {top.db_type}/{top.db_name}",
                "severity":  "critical" if top.severity == 3 else "warning",
                "source":    top.host,
                "custom_details": {
                    "kontrol_kodu":  top.kontrol_kodu,
                    "sonuc":         top.sonuc,
                    "detay":         top.detay,
                    "toplam_uyari":  len(metrics),
                },
            },
        }

        resp = requests.post(
            "https://events.pagerduty.com/v2/enqueue",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Microsoft Teams
    # ------------------------------------------------------------------

    def _send_teams(self, rule: dict, metrics: list[MetricSchema]) -> None:
        webhook_url = rule["webhook_url"]
        critical    = [m for m in metrics if m.severity == 3]

        facts = [
            {"name": m.kontrol_kodu, "value": f"{m.db_type}/{m.db_name} — {m.sonuc}"}
            for m in metrics[:8]
        ]

        payload = {
            "@type":      "MessageCard",
            "@context":   "http://schema.org/extensions",
            "themeColor": "FF0000" if critical else "FFA500",
            "summary":    f"DWH Monitor: {len(metrics)} uyarı",
            "sections": [{
                "activityTitle":    "🚨 DWH Health Monitor",
                "activitySubtitle": f"{len(critical)} kritik, {len(metrics)-len(critical)} uyarı",
                "facts":            facts,
            }],
        }

        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Generic Webhook
    # ------------------------------------------------------------------

    def _send_webhook(self, rule: dict, metrics: list[MetricSchema]) -> None:
        webhook_url = rule["webhook_url"]
        headers     = rule.get("headers", {"Content-Type": "application/json"})

        payload = {
            "source":    "dwh-monitor",
            "timestamp": metrics[0].ts.isoformat() if metrics else "",
            "count":     len(metrics),
            "alerts": [
                {
                    "kontrol_kodu":  m.kontrol_kodu,
                    "db_type":       m.db_type,
                    "db_name":       m.db_name,
                    "host":          m.host,
                    "sonuc":         m.sonuc,
                    "severity":      m.severity,
                    "detay":         m.detay,
                }
                for m in metrics
            ],
        }

        resp = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # HTML body
    # ------------------------------------------------------------------

    def _build_html_body(self, metrics: list[MetricSchema]) -> str:
        rows = ""
        for m in metrics:
            color = "#ffcccc" if m.severity == 3 else "#fff3cc"
            rows += (
                f"<tr style='background:{color}'>"
                f"<td>{m.kontrol_kodu}</td>"
                f"<td>{m.db_type}</td>"
                f"<td>{m.db_name}</td>"
                f"<td>{m.sonuc}</td>"
                f"<td>{m.severity}</td>"
                f"<td>{m.detay or '-'}</td>"
                f"</tr>"
            )

        return f"""
        <html><body>
        <h2>DWH Health Monitor Uyarıları</h2>
        <table border='1' cellpadding='5' cellspacing='0'>
          <tr>
            <th>Kontrol Kodu</th><th>DB Tipi</th><th>DB Adı</th>
            <th>Sonuç</th><th>Severity</th><th>Detay</th>
          </tr>
          {rows}
        </table>
        </body></html>
        """
