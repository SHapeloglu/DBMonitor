#!/usr/bin/env python3
"""yaml_check.py <dosya...> — YAML sözdizimi + temel Prometheus kural ve Alertmanager yapısı denetimi (promtool yok)."""
import sys, yaml
bad = 0
for f in sys.argv[1:]:
    try:
        d = yaml.safe_load(open(f, encoding="utf-8"))
    except Exception as e:
        print(f"HATA {f}: {e}"); bad += 1; continue
    if isinstance(d, dict) and "groups" in d:
        for g in d["groups"]:
            for r in g.get("rules", []):
                miss = [k for k in ("alert", "expr") if k not in r]
                if miss: print(f"HATA {f}: kural {r.get('alert')} eksik alan {miss}"); bad += 1
    if isinstance(d, dict) and "route" in d:
        names = {x.get("name") for x in d.get("receivers", [])}
        if d["route"].get("receiver") not in names: print(f"HATA {f}: route.receiver tanımsız"); bad += 1
    print(f"OK {f}")
sys.exit(1 if bad else 0)
