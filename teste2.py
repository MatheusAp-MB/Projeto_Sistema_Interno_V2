import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

# * [RESUMO] → Testa cada filtro da Agenda de Vídeos isoladamente, contando
# quantos produtos de teste (criados por teste.py) cada 1 captura — não
# testa a TELA (isso é HTTP, fora do que dá pra fazer aqui), testa a
# FUNÇÃO de filtro (listar_produtos_agenda_filtrados) direto, com o mesmo
# dado real do banco. Rode teste.py ANTES deste.

from datetime import date
from produtos.models import Produto
from agenda_videos.funcoes_auxiliares.filtros_agenda_videos import listar_produtos_agenda_filtrados, OPCOES_PENDENTE_AGORA
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import listar_a_fazer_hoje

PREFIXO_TESTE = 'TESTE-AGENDA-'


def _titulos_dos_testados(queryset_ou_lista):
    eans_teste = set(Produto.objects.filter(ean__startswith=PREFIXO_TESTE).values_list('ean', flat=True))
    return sorted(p.titulo for p in queryset_ou_lista if p.ean in eans_teste)


def _imprimir_resultado(nome_filtro, filtros):
    produtos = listar_produtos_agenda_filtrados(filtros=filtros)
    titulos = _titulos_dos_testados(produtos)
    print(f'\n{nome_filtro}  →  {len(titulos)} produto(s) de teste encontrado(s)')
    for titulo in titulos:
        print(f'    - {titulo}')


def _imprimir_resultado_a_fazer_hoje(nome_filtro, filtros):
    produtos = listar_a_fazer_hoje(filtros=filtros)
    titulos = _titulos_dos_testados(produtos)
    print(f'\n[A Fazer Hoje] {nome_filtro}  →  {len(titulos)} produto(s) de teste encontrado(s)')
    for titulo in titulos:
        print(f'    - {titulo}')


if __name__ == '__main__':
    total_teste = Produto.objects.filter(ean__startswith=PREFIXO_TESTE).count()
    print(f'{total_teste} produto(s) de teste encontrado(s) no banco (rode teste.py antes, se for 0).\n')
    print('=' * 70)
    print('TESTANDO FILTROS — LISTAGEM PRINCIPAL (SQL)')
    print('=' * 70)

    _imprimir_resultado('Sem filtro nenhum (todos os de teste devem aparecer)', {})
    _imprimir_resultado('Urgente = Sim', {'urgente': ['sim']})
    _imprimir_resultado('Atrasado = Sim', {'atrasado': ['sim']})
    _imprimir_resultado('Risco de Atraso = Sim', {'risco': ['sim']})
    _imprimir_resultado('Sem Vídeo = Sim', {'sem_video': ['sim']})
    _imprimir_resultado('Status Manual = Pausado', {'status_manual': ['pausado']})
    _imprimir_resultado('Estágio = Não Agendado', {'estagio': ['nao_agendado']})
    _imprimir_resultado('Estágio = Diário', {'estagio': ['diaria']})
    _imprimir_resultado('Estágio = Semanal', {'estagio': ['semanal']})
    _imprimir_resultado('Estágio = Mensal', {'estagio': ['mensal']})
    _imprimir_resultado('Estágio = Otimizado', {'estagio': ['otimizado']})
    _imprimir_resultado('Status da postagem mais recente = Recusado', {'status_postagem': ['recusado']})
    _imprimir_resultado('Status da postagem mais recente = Aguardando aprovação', {'status_postagem': ['aguardando_aprovacao']})
    _imprimir_resultado('Status da postagem mais recente = Aprovado', {'status_postagem': ['aprovado']})

    print('\n' + '=' * 70)
    print('TESTANDO "PENDENTE AGORA" (9 categorias, 1 de cada vez)')
    print('=' * 70)
    for valor, label in OPCOES_PENDENTE_AGORA:
        _imprimir_resultado(f'Pendente Agora = {label}', {'pendente_agora': [valor]})

    print('\n' + '=' * 70)
    print('TESTANDO FILTROS — A FAZER HOJE (Python)')
    print('=' * 70)
    _imprimir_resultado_a_fazer_hoje('Sem filtro (tudo que já venceu ou vence hoje)', {})
    _imprimir_resultado_a_fazer_hoje('Atrasado = Sim', {'atrasado': ['sim']})
    _imprimir_resultado_a_fazer_hoje('Risco de Atraso = Sim', {'risco': ['sim']})
    for valor, label in OPCOES_PENDENTE_AGORA:
        _imprimir_resultado_a_fazer_hoje(f'Pendente Agora = {label}', {'pendente_agora': [valor]})

    print('\nConcluído — confira se cada contagem bate com o que você esperava pra cada cenário.')