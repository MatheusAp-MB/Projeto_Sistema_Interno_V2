# agenda_videos/tests/test_nivel_4__view_portal_drive_filtros.py

# SUT: agenda_videos/views.py::view_portal_drive (os 5 filtros: Marca,
#      Progresso de envio, Fase atual, Urgente, Sincronização com o Drive)
# DOC: banco real (Produto/IndicadoresAgendaProduto/ParticipacaoAgenda/
#      SnapshotArquivosDrive) + client HTTP real do Django — Nível 4.
#      Nenhuma chamada ao Drive acontece nesta view (leitura pura de
#      banco), então nada aqui precisa mockar rede.

import pytest
from django.urls import reverse

from produtos.models import Produto
from agenda_videos.models import Fase, IndicadoresAgendaProduto, ParticipacaoAgenda, SnapshotArquivosDrive
from agenda_videos.funcoes_auxiliares.drive.arquivador import montar_nome_arquivo
from agenda_videos.views import FASES_E_NUMEROS_PRINCIPAIS, TOTAL_ARQUIVOS_ESPERADOS
from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — view_portal_drive(): filtros de 5 dimensões'


# * [EXPLICAÇÃO] → Sem isso, obter_empresa_ativa() devolve None até a
#                  PRIMEIRA requisição passar pelo EmpresaMiddleware —
#                  e com None, o EmpresaRouter cai no alias 'default'.
#                  Setup que roda ANTES de qualquer client.get() (o caso
#                  de qualquer teste que crie dado próprio antes de pedir
#                  a página) grava no banco errado, e o client.get() lê
#                  de 'magazine' — 2 bancos diferentes, sem erro nenhum,
#                  só resultado vazio. Achado real (21/08/2026) testando
#                  o filtro de Fase, o 1º teste deste arquivo em ordem
#                  alfabética — os outros passavam "por acidente", porque
#                  o client.get() de um teste anterior já tinha fixado a
#                  empresa pro resto do arquivo.
@pytest.fixture(autouse=True)
def _empresa_ativa_magazine():
    definir_empresa_ativa(EMPRESA_MAGAZINE)


def _criar_produto(sku, ean, marca='Marca Teste'):
    return Produto.objects.create(ean=ean, sku=sku, titulo=f'Produto {sku}', marca=marca)


def _arquivos_completos():
    arquivos = []
    for fase, numero in FASES_E_NUMEROS_PRINCIPAIS:
        for tipo in ('base', 'roteiro', 'completo'):
            nome = montar_nome_arquivo(fase, numero, tipo)
            arquivos.append({'id': f'id-{nome}', 'name': nome})
    return arquivos


def _obter_produtos_da_pagina(resposta):
    return {produto.id for produto in resposta.context['pagina'].object_list}


def test_sem_filtro_mostra_todos(client, tabela_resultados):
    # Setup:
    p1 = _criar_produto('SKU-601', 'EAN-601')
    p2 = _criar_produto('SKU-602', 'EAN-602')

    # Exercise:
    resposta = client.get(reverse('agenda_videos_portal_drive'))

    # Assert:
    encontrados = _obter_produtos_da_pagina(resposta)
    passou = resposta.status_code == 200 and {p1.id, p2.id} <= encontrados
    registrar_resultado(
        tabela_resultados, teste='Sem filtro nenhum — mostra todos os produtos ativos',
        entrada='GET /portal-drive/ sem querystring',
        esperado='os 2 produtos criados aparecem na página',
        motivo='Baseline — sem isso funcionando, nenhum teste de filtro abaixo faz sentido',
        obtido=f'status={resposta.status_code}, encontrados={encontrados}',
        passou=passou,
    )
    assert passou


def test_filtro_marca_isola_produtos_da_marca_selecionada(client, tabela_resultados):
    # Setup:
    alvo = _criar_produto('SKU-603', 'EAN-603', marca='Marca Alvo')
    outro = _criar_produto('SKU-604', 'EAN-604', marca='Outra Marca')

    # Exercise:
    resposta = client.get(reverse('agenda_videos_portal_drive'), {'marca': 'Marca Alvo'})

    # Assert:
    encontrados = _obter_produtos_da_pagina(resposta)
    passou = alvo.id in encontrados and outro.id not in encontrados
    registrar_resultado(
        tabela_resultados, teste='Filtro de Marca isola só a marca selecionada',
        entrada='?marca=Marca Alvo',
        esperado='só o produto da marca selecionada aparece',
        motivo='Marca é multi-checkbox (getlist) — precisa filtrar por igualdade exata, não substring',
        obtido=f'encontrados={encontrados}',
        passou=passou,
    )
    assert passou


def test_filtro_fase_isola_produtos_da_fase_selecionada(client, tabela_resultados):
    # Setup:
    mensal = _criar_produto('SKU-605', 'EAN-605')
    IndicadoresAgendaProduto.objects.create(produto=mensal, fase_atual=Fase.VIDEO_MENSAL)
    simples = _criar_produto('SKU-606', 'EAN-606')
    IndicadoresAgendaProduto.objects.create(produto=simples, fase_atual=Fase.SIMPLES)

    # Exercise:
    resposta = client.get(reverse('agenda_videos_portal_drive'), {'fase': Fase.VIDEO_MENSAL})

    # Exercise:
    resposta = client.get(reverse('agenda_videos_portal_drive'), {'fase': Fase.VIDEO_MENSAL})

    # Assert:
    encontrados = _obter_produtos_da_pagina(resposta)
    passou = mensal.id in encontrados and simples.id not in encontrados
    registrar_resultado(
        tabela_resultados, teste='Filtro de Fase atual isola só a fase selecionada',
        entrada=f'?fase={Fase.VIDEO_MENSAL}',
        esperado='só o produto em Vídeo Mensal aparece',
        motivo='Fase vem de IndicadoresAgendaProduto.fase_atual, não do snapshot do Drive',
        obtido=f'encontrados={encontrados}',
        passou=passou,
    )
    assert passou


def test_filtro_urgente_isola_produtos_marcados(client, tabela_resultados):
    # Setup:
    urgente = _criar_produto('SKU-607', 'EAN-607')
    ParticipacaoAgenda.objects.create(produto=urgente, urgente=True)
    tranquilo = _criar_produto('SKU-608', 'EAN-608')

    # Exercise:
    resposta = client.get(reverse('agenda_videos_portal_drive'), {'urgente': '1'})

    # Assert:
    encontrados = _obter_produtos_da_pagina(resposta)
    passou = urgente.id in encontrados and tranquilo.id not in encontrados
    registrar_resultado(
        tabela_resultados, teste='Filtro "Só urgentes" isola só os marcados',
        entrada='?urgente=1',
        esperado='só o produto com participacao_agenda.urgente=True aparece',
        motivo='Produto sem ParticipacaoAgenda nenhuma precisa contar como "não urgente", não dar erro',
        obtido=f'encontrados={encontrados}',
        passou=passou,
    )
    assert passou


def test_filtro_sincronizado_sim_isola_produtos_com_snapshot(client, tabela_resultados):
    # Setup:
    com_snapshot = _criar_produto('SKU-609', 'EAN-609')
    SnapshotArquivosDrive.objects.create(produto=com_snapshot, pasta_encontrada=False, motivo_nao_encontrado='teste')
    sem_snapshot = _criar_produto('SKU-610', 'EAN-610')

    # Exercise:
    resposta = client.get(reverse('agenda_videos_portal_drive'), {'sincronizado': 'sim'})

    # Assert:
    encontrados = _obter_produtos_da_pagina(resposta)
    passou = com_snapshot.id in encontrados and sem_snapshot.id not in encontrados
    registrar_resultado(
        tabela_resultados, teste='Filtro "Sincronizados" isola quem já tem snapshot (achado ou não)',
        entrada='?sincronizado=sim',
        esperado='produto com snapshot aparece, mesmo se pasta_encontrada=False',
        motivo='"Sincronizado" é sobre TER SIDO VERIFICADO, não sobre ter sido encontrado — a distinção do bug corrigido',
        obtido=f'encontrados={encontrados}',
        passou=passou,
    )
    assert passou


def test_filtro_sincronizado_nao_isola_produtos_sem_snapshot(client, tabela_resultados):
    # Setup:
    com_snapshot = _criar_produto('SKU-611', 'EAN-611')
    SnapshotArquivosDrive.objects.create(produto=com_snapshot, pasta_encontrada=True)
    sem_snapshot = _criar_produto('SKU-612', 'EAN-612')

    # Exercise:
    resposta = client.get(reverse('agenda_videos_portal_drive'), {'sincronizado': 'nao'})

    # Assert:
    encontrados = _obter_produtos_da_pagina(resposta)
    passou = sem_snapshot.id in encontrados and com_snapshot.id not in encontrados
    registrar_resultado(
        tabela_resultados, teste='Filtro "Não sincronizados" isola quem nunca foi verificado',
        entrada='?sincronizado=nao',
        esperado='só o produto sem snapshot nenhum aparece',
        motivo='Complemento exato do teste anterior',
        obtido=f'encontrados={encontrados}',
        passou=passou,
    )
    assert passou


def test_filtro_progresso_completo_isola_produtos_com_18_de_18(client, tabela_resultados):
    # Setup:
    completo = _criar_produto('SKU-613', 'EAN-613')
    SnapshotArquivosDrive.objects.create(produto=completo, pasta_encontrada=True, arquivos_videos=_arquivos_completos())
    pendente = _criar_produto('SKU-614', 'EAN-614')
    SnapshotArquivosDrive.objects.create(produto=pendente, pasta_encontrada=True, arquivos_videos=_arquivos_completos()[:3])

    # Exercise:
    resposta = client.get(reverse('agenda_videos_portal_drive'), {'progresso': 'completo'})

    # Assert:
    encontrados = _obter_produtos_da_pagina(resposta)
    passou = completo.id in encontrados and pendente.id not in encontrados
    registrar_resultado(
        tabela_resultados, teste='Filtro de Progresso "Completo" isola quem tem os 18 arquivos',
        entrada=f'?progresso=completo (1 produto com {TOTAL_ARQUIVOS_ESPERADOS} arquivos, outro com só 3)',
        esperado='só o produto com todos os arquivos aparece',
        motivo='Progresso não é campo de banco — calculado do JSON do snapshot em Python, avaliado antes de paginar',
        obtido=f'encontrados={encontrados}',
        passou=passou,
    )
    assert passou


def test_filtro_progresso_pendente_isola_produtos_incompletos(client, tabela_resultados):
    # Setup:
    completo = _criar_produto('SKU-615', 'EAN-615')
    SnapshotArquivosDrive.objects.create(produto=completo, pasta_encontrada=True, arquivos_videos=_arquivos_completos())
    pendente = _criar_produto('SKU-616', 'EAN-616')
    SnapshotArquivosDrive.objects.create(produto=pendente, pasta_encontrada=True, arquivos_videos=_arquivos_completos()[:3])
    nunca_sincronizado = _criar_produto('SKU-617', 'EAN-617')

    # Exercise:
    resposta = client.get(reverse('agenda_videos_portal_drive'), {'progresso': 'pendente'})

    # Assert:
    encontrados = _obter_produtos_da_pagina(resposta)
    passou = completo.id not in encontrados and pendente.id in encontrados and nunca_sincronizado.id in encontrados
    registrar_resultado(
        tabela_resultados, teste='Filtro de Progresso "Com pendência" inclui parcial e nunca sincronizado',
        entrada='1 produto completo, 1 com 3 de 18, 1 sem snapshot nenhum',
        esperado='os 2 incompletos aparecem, o completo não',
        motivo='Produto nunca sincronizado tem 0 arquivos presentes — é pendência também, não caso à parte',
        obtido=f'encontrados={encontrados}',
        passou=passou,
    )
    assert passou


def test_filtros_combinados_sao_and_nao_or(client, tabela_resultados):
    # Setup:
    bate_os_2 = _criar_produto('SKU-618', 'EAN-618', marca='Marca Alvo')
    ParticipacaoAgenda.objects.create(produto=bate_os_2, urgente=True)
    _criar_produto('SKU-619', 'EAN-619', marca='Marca Alvo')
    so_urgente = _criar_produto('SKU-620', 'EAN-620', marca='Outra Marca')
    ParticipacaoAgenda.objects.create(produto=so_urgente, urgente=True)

    # Exercise:
    resposta = client.get(reverse('agenda_videos_portal_drive'), {'marca': 'Marca Alvo', 'urgente': '1'})

    # Assert:
    encontrados = _obter_produtos_da_pagina(resposta)
    passou = encontrados == {bate_os_2.id}
    registrar_resultado(
        tabela_resultados, teste='Filtros de dimensões diferentes se combinam em E, não em OU',
        entrada='?marca=Marca Alvo&urgente=1, com 1 produto batendo os 2 e 2 batendo só 1 cada',
        esperado='só o produto que bate os 2 filtros ao mesmo tempo aparece',
        motivo='Cada dimensão precisa restringir mais o resultado, nunca expandir',
        obtido=f'encontrados={encontrados}',
        passou=passou,
    )
    assert passou