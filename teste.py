"""
CONFIRMAÇÃO EM ESCALA — Pausados trazem dado de promoção de verdade?
==========================================================================
Usa o dataset completo (5.615 MLBs) para responder com precisão: pausados
têm HTTP 200? Têm promoção de verdade (lista não vazia)? Têm rebate?
Compara contra ativos para decidir se vale manter pausados no escopo.

Só leitura — nenhuma chamada de API.
"""

import json
from pathlib import Path
from collections import Counter

ARQUIVO_DETALHES = Path("Arquivos_API/detalhes_mlbs.json")
ARQUIVO_PROMOCOES = Path("Arquivos_API/promocoes_completo.json")


def main():
    with open(ARQUIVO_DETALHES, encoding="utf-8") as f:
        detalhes = json.load(f)
    status_por_mlb = {r["mlb"]: r.get("status") for r in detalhes["registros"]}

    with open(ARQUIVO_PROMOCOES, encoding="utf-8") as f:
        promocoes = json.load(f)
    fase2 = promocoes["fase2_promocoes_por_item"]

    stats = {
        "active": {"total": 0, "http_ok": 0, "com_promo": 0, "com_rebate": 0, "total_promocoes": 0, "total_rebates": 0},
        "paused": {"total": 0, "http_ok": 0, "com_promo": 0, "com_rebate": 0, "total_promocoes": 0, "total_rebates": 0},
    }

    for mlb, resultado in fase2.items():
        status = status_por_mlb.get(mlb)
        if status not in stats:
            continue

        stats[status]["total"] += 1

        if resultado.get("http") != 200:
            continue
        stats[status]["http_ok"] += 1

        promos = resultado.get("dados") or []
        if promos:
            stats[status]["com_promo"] += 1
            stats[status]["total_promocoes"] += len(promos)

        tem_rebate = any(p.get("meli_percentage") is not None for p in promos)
        if tem_rebate:
            stats[status]["com_rebate"] += 1
            stats[status]["total_rebates"] += sum(1 for p in promos if p.get("meli_percentage") is not None)

    print(f"{'Status':<10} {'Total':<8} {'HTTP 200':<10} {'Com promoção':<14} {'Com rebate':<12} {'Média promo/item':<18} {'Média rebates/item'}")
    print("-" * 100)

    for status, s in stats.items():
        media_promo = s["total_promocoes"] / s["http_ok"] if s["http_ok"] else 0
        media_rebate = s["total_rebates"] / s["http_ok"] if s["http_ok"] else 0
        pct_com_promo = s["com_promo"] / s["http_ok"] * 100 if s["http_ok"] else 0
        pct_com_rebate = s["com_rebate"] / s["http_ok"] * 100 if s["http_ok"] else 0

        print(f"{status:<10} {s['total']:<8} {s['http_ok']:<10} "
              f"{s['com_promo']} ({pct_com_promo:.1f}%){'':<3} "
              f"{s['com_rebate']} ({pct_com_rebate:.1f}%){'':<3} "
              f"{media_promo:.2f}{'':<12} {media_rebate:.2f}")


if __name__ == "__main__":
    main()