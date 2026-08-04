# agenda_videos/tests/test_nivel_4__view_historico_agenda_videos.py

# Função Objetivo: Testa view_historico_agenda_videos() — Nível 4 (view HTTP
# real). A lógica de filtro de listar_produtos_com_historico() já foi
# exaustivamente testada no Nível 3 (24 cenários) — aqui o foco é só a
# integração via HTTP: paginação, fallback de por_pagina inválido,
# marcas_disponiveis e a busca chegando via querystring até a página real.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse

from produtos.models import Produto
from agenda_videos.models import CicloVideo, Fase
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 4 — view_historico_agenda_videos(): relatório via HTTP'


def _criar_produto_com_ciclo(sku, marca=None, titulo='Produto Teste'):
    produto = Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo=titulo, marca=marca)
    CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)
    return produto


def test_sem_filtro_nenhum_lista_produto_com_ciclo(client, tabela_resultados):
    # Setup:
    produto = _criar_produto_com_ciclo('SKU-001')

    # Exercise:
    resposta = client.get(reverse('agenda_videos_historico'))

    # Assert:
    grupos = resposta.context['grupos']
    passou = resposta.status_code == 200 and len(grupos) == 1 and grupos[0].produto.id == produto.id
    registrar_resultado(
        tabela_resultados, teste='sem filtro nenhum → lista produto com ciclo',
        entrada='1 produto com 1 CicloVideo, GET sem parâmetros', esperado='200, 1 grupo, produto certo',
        motivo='Confirma que a view entrega o histórico do produto certo, ponta a ponta',
        obtido=f'status={resposta.status_code}, len(grupos)={len(grupos)}',
        passou=passou,
    )
    assert passou


def test_busca_via_querystring_filtra_o_produto_certo(client, tabela_resultados):
    # Setup:
    bate = _criar_produto_com_ciclo('SKU-002', titulo='Fone Bluetooth XPTO')
    _criar_produto_com_ciclo('SKU-003', titulo='Outro Produto Qualquer')

    # Exercise:
    resposta = client.get(reverse('agenda_videos_historico'), {'busca': 'XPTO'})

    # Assert:
    ids_nos_grupos = [g.produto.id for g in resposta.context['grupos']]
    passou = resposta.status_code == 200 and ids_nos_grupos == [bate.id]
    registrar_resultado(
        tabela_resultados, teste='busca via querystring filtra o produto certo',
        entrada='2 produtos, ?busca=XPTO', esperado='só o produto com XPTO no título aparece',
        motivo='Confirma que o parâmetro de busca da URL chega até listar_produtos_com_historico',
        obtido=f'status={resposta.status_code}, ids_nos_grupos={ids_nos_grupos}',
        passou=passou,
    )
    assert passou


def test_marcas_disponiveis_exclui_marca_vazia_e_nula(client, tabela_resultados):
    # Setup:
    _criar_produto_com_ciclo('SKU-004', marca='Samsung')
    _criar_produto_com_ciclo('SKU-005', marca='')
    _criar_produto_com_ciclo('SKU-006', marca=None)

    # Exercise:
    resposta = client.get(reverse('agenda_videos_historico'))

    # Assert:
    marcas = list(resposta.context['marcas_disponiveis'])
    passou = resposta.status_code == 200 and marcas == ['Samsung']
    registrar_resultado(
        tabela_resultados, teste='marcas_disponiveis exclui vazia e nula',
        entrada='marcas: Samsung, "" (vazia), None', esperado='marcas_disponiveis == ["Samsung"]',
        motivo='exclude(marca__isnull=True).exclude(marca="") precisa filtrar os 2 casos, não só 1',
        obtido=f'status={resposta.status_code}, marcas={marcas}',
        passou=passou,
    )
    assert passou


def test_paginacao_por_pagina_1_gera_2_paginas_com_2_produtos(client, tabela_resultados):
    # Setup:
    _criar_produto_com_ciclo('SKU-007')
    _criar_produto_com_ciclo('SKU-008')

    # Exercise:
    resposta = client.get(reverse('agenda_videos_historico'), {'por_pagina': '1'})

    # Assert:
    num_pages = resposta.context['pagina'].paginator.num_pages
    passou = resposta.status_code == 200 and num_pages == 2
    registrar_resultado(
        tabela_resultados, teste='por_pagina=1 com 2 produtos → 2 páginas',
        entrada='2 produtos com ciclo, ?por_pagina=1', esperado='paginator.num_pages == 2',
        motivo='Confirma que o parâmetro de paginação da URL chega até o Paginator real',
        obtido=f'status={resposta.status_code}, num_pages={num_pages}',
        passou=passou,
    )
    assert passou


def test_por_pagina_invalido_cai_no_padrao_25(client, tabela_resultados):
    # Setup:
    _criar_produto_com_ciclo('SKU-009')

    # Exercise:
    resposta = client.get(reverse('agenda_videos_historico'), {'por_pagina': 'abc'})

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['pagina'].paginator.per_page == 25
    registrar_resultado(
        tabela_resultados, teste='por_pagina inválido → fallback 25',
        entrada='?por_pagina=abc (não é número)', esperado='paginator.per_page == 25',
        motivo='int("abc") levanta ValueError — a view precisa capturar isso e cair no padrão, não quebrar',
        obtido=f'status={resposta.status_code}, per_page={resposta.context["pagina"].paginator.per_page}',
        passou=passou,
    )
    assert passou