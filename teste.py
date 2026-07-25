import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from datetime import date
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import listar_a_fazer_hoje

# ==== CONFIGURA AQUI ANTES DE RODAR ====
DATA_SIMULADA = date(2026, 7, 27)  # segunda-feira — troque pra qualquer data de teste
# ========================================

produtos = listar_a_fazer_hoje(data_referencia=DATA_SIMULADA)
print(f"Simulando 'hoje' = {DATA_SIMULADA} ({DATA_SIMULADA.strftime('%A')})")
print(f"{len(produtos)} produto(s) apareceriam em 'A Fazer Hoje'\n")

for produto in produtos:
    situacao = "ATRASADO" if produto.a_fazer_hoje_atrasado else ("RISCO" if produto.a_fazer_hoje_risco else "normal")
    print(f"[{situacao}] {produto.sku or produto.ean} — {produto.titulo[:40]} | vence {produto.a_fazer_hoje_vencimento}")