# * [RESUMO] → INVESTIGAÇÃO, SÓ LEITURA — não toca no banco, não
#              grava nada. Varre os 3 arquivos JSON gerados pela API
#              (detalhes_mlbs.json, dados_completos_por_sku.json,
#              promocoes_completo.json) e mede, pra CADA campo que
#              existir em QUALQUER nível de aninhamento, quantas
#              vezes aparece e quantas vezes vem preenchido de
#              verdade (não None/vazio) — pra achar campo útil que
#              nunca usamos, sem precisar adivinhar a estrutura na
#              mão. Genérico o bastante pra funcionar em qualquer
#              formato de JSON, não é específico de 1 arquivo só.

import json
from pathlib import Path
from collections import defaultdict
from django.core.management.base import BaseCommand

ARQUIVOS = [
    Path('Arquivos_API/detalhes_mlbs.json'),
    Path('Arquivos_API/dados_completos_por_sku.json'),
    Path('Arquivos_API/promocoes_completo.json'),
]


def _achatar(obj, caminho, contador):
    """Percorre estrutura JSON aninhada (dict/list) recursivamente e
    conta, por 'caminho' (string tipo 'a.b[].c'), quantas vezes cada
    campo folha aparece e quantas vezes vem preenchido.

    '[]' no caminho indica 'dentro de uma lista' — o percentual nesse
    caso é sobre quantos ITENS DA LISTA têm aquele campo preenchido,
    não sobre o total de registros do arquivo (ex: um campo dentro de
    uma lista de promoções conta sobre o total de promoções, não
    sobre o total de MLBs)."""
    if isinstance(obj, dict):
        for chave, valor in obj.items():
            novo_caminho = f'{caminho}.{chave}' if caminho else chave
            _achatar(valor, novo_caminho, contador)
    elif isinstance(obj, list):
        for item in obj:
            _achatar(item, caminho + '[]', contador)
    else:
        info = contador[caminho]
        info['total'] += 1
        if obj not in (None, '', [], {}):
            info['preenchido'] += 1
            if info['exemplo'] is None:
                info['exemplo'] = obj


class Command(BaseCommand):
    help = (
        'INVESTIGAÇÃO — varre todos os arquivos JSON da API e mede o '
        'preenchimento de TODOS os campos, em qualquer nível de '
        'aninhamento. Só leitura, não toca no banco.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--ordenar-por', choices=['nome', 'percentual'], default='percentual',
            help='Como ordenar a lista de campos na saída (padrão: percentual, do mais preenchido pro menos).'
        )

    def handle(self, *args, **options):
        resultado_geral = {}

        for caminho in ARQUIVOS:
            self.stdout.write(f'Processando {caminho}...')

            if not caminho.exists():
                self.stdout.write(self.style.WARNING(f'  Arquivo não encontrado — pulando.'))
                resultado_geral[str(caminho)] = {'erro': 'arquivo não encontrado'}
                continue

            with open(caminho, encoding='utf-8') as f:
                dados = json.load(f)

            contador = defaultdict(lambda: {'total': 0, 'preenchido': 0, 'exemplo': None})
            _achatar(dados, '', contador)

            linhas = []
            for campo, info in contador.items():
                pct = round((info['preenchido'] / info['total'] * 100) if info['total'] else 0, 1)
                exemplo = str(info['exemplo'])
                if len(exemplo) > 80:
                    exemplo = exemplo[:80] + '...'
                linhas.append({
                    'campo': campo,
                    'total': info['total'],
                    'preenchido': info['preenchido'],
                    'percentual': pct,
                    'exemplo': exemplo,
                })

            if options['ordenar_por'] == 'percentual':
                linhas.sort(key=lambda l: l['percentual'], reverse=True)
            else:
                linhas.sort(key=lambda l: l['campo'])

            resultado_geral[str(caminho)] = {
                'total_campos_distintos': len(linhas),
                'campos': linhas,
            }
            self.stdout.write(f'  {len(linhas)} campo(s) distinto(s) encontrado(s).')

        caminho_saida = Path('investigacao_campos_api.json')
        with open(caminho_saida, 'w', encoding='utf-8') as f:
            json.dump(resultado_geral, f, ensure_ascii=False, indent=2)

        self.stdout.write(self.style.SUCCESS(f'\nResultado salvo em: {caminho_saida.resolve()}'))
        self.stdout.write('Suba esse arquivo na conversa pra eu analisar.')