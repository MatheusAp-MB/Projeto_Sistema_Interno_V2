import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

# * [RESUMO] → Script de USO ÚNICO — marca reestruturacao_manual=True nos 73
# produtos com histórico legado (Drive antigo não estruturado + planilha de
# agenda antiga), união das 2 listas, conferida programaticamente em 27/07.
# Não importa nenhum dado de agenda — só liga o badge informativo.

from produtos.models import Produto
from agenda_videos.models import RoadmapAgenda

EANS_LEGADO = [
    '0070341902806', '0789888395957', '7891117006961', '7891117051985',
    '7891117101307', '7891117102687', '7891117103936', '7891117108009',
    '7891988003199', '7891988006480', '7891988006671', '7891988010432',
    '7891988038306', '7891988044178', '7891988052159', '7891988054306',
    '7891988055341', '7891988063780', '7891988071518', '7895293437342',
    '7895293546662', '7895293684708', '7895293684715', '7895293695636',
    '7895293790454', '7895293908057', '7895572102275', '7896660874258',
    '7896660874272', '7896692148310', '7896821500279', '7897154291377',
    '7898026080587', '7898026082116', '7898026083229', '7898026083359',
    '7898026086237', '7898632330663', '7898632332155', '7898632332162',
    '7898632332223', '7898632339543', '7898635051602', '7898635052319',
    '7898635052326', '7899009119775', '7899296599199', '7899612724472',
    '7908050719121', '7908050719534', '7908050734483', '7908276603655',
    '7908276605376', '7908276607578', '7908276608605', '7908276608612',
    '7908276622236', '7908276625664', '7908276643316', '7908276645501',
    '7908276645556', '7908276653209', '7908276656156', '7908276656163',
    '7908276656248', '7908276662348', '7908276665974', '7908276665981',
    '7908276682759', '7908276684319', '7909436939669', '7909439011089',
    '7909439011096',
]

marcados = 0
nao_encontrados = []

for ean in EANS_LEGADO:
    produto = Produto.objects.filter(ean=ean).first()
    if produto is None:
        nao_encontrados.append(ean)
        continue

    roadmap_agenda, _ = RoadmapAgenda.objects.get_or_create(produto=produto)
    roadmap_agenda.reestruturacao_manual = True
    roadmap_agenda.save()
    marcados += 1

print(f'{marcados} produto(s) marcado(s) com Reestruturação Manual.')
if nao_encontrados:
    print(f'\n{len(nao_encontrados)} EAN(s) da lista NÃO encontrados no banco:')
    for ean in nao_encontrados:
        print(f'  {ean}')