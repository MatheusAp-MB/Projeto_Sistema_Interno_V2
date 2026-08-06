# agenda_videos/tests/test_nivel_4__view_agenda_videos.py

# Função Objetivo: Testa view_agenda_videos() — Nível 4 (view HTTP real).
# A lógica de filtro/contagem por tela já foi exaustivamente testada nos
# Níveis 3 (listar_produtos_agenda_filtrados, contar_por_condicoes) — aqui
# o foco é confirmar que a VIEW entrega esse resultado certo de ponta a
# ponta pelo navegador: tela padrão, fallback de tela inválida, contadores
# de chip chegando no contexto, e paginação.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse

from produtos.models import Produto
from agenda_videos.models import CicloVideo, ConfiguracaoFase, Fase
from agenda_videos.funcoes_auxiliares.filtros_agenda_videos import Tela
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_indicadores_agenda_produto
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 4 — view_agenda_videos(): tela principal via HTTP'


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste')


@pytest.fixture
def regua_de_fases():
    # Setup: o card de cada produto na grade da tela principal renderiza o
    # roadmap (templatetag roadmap_produto -> calcular_roadmap_produto),
    # que sempre consulta ConfiguracaoFase(fase=Simples) pra montar o
    # caminho completo — a mesma régua real que precisa ser semeada em todo
    # banco novo (ver "Regua de Fases Precisa Ser Semeada em Todo Ambiente
    # Novo" no vault). Sem isso, qualquer teste que renderize >= 1 produto
    # na grade quebra com ConfiguracaoFase.DoesNotExist — não é bug de
    # produção, é dependência real da página.
    trimestral = ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_TRIMESTRAL, periodo_continuo=True,
        distancia_dias_corridos=90, distancia_dias_ao_entrar_na_fase=90,
    )
    mensal = ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_MENSAL, periodo_continuo=False, periodo=4,
        distancia_dias_corridos=30, distancia_dias_ao_entrar_na_fase=0,
        proxima_fase=trimestral,
    )
    ConfiguracaoFase.objects.create(
        fase=Fase.SIMPLES, periodo_continuo=False, periodo=1,
        proxima_fase=mensal,
    )


def test_sem_querystring_usa_a_fazer_hoje_como_tela_padrao(client, tabela_resultados):
    # Exercise:
    resposta = client.get(reverse('agenda_videos_principal'))

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['tela_atual'] == Tela.A_FAZER_HOJE
    registrar_resultado(
        tabela_resultados, teste='sem querystring → tela padrão é A Fazer Hoje',
        entrada='GET / (sem parâmetros)', esperado=f'tela_atual == {Tela.A_FAZER_HOJE!r}',
        motivo='Comportamento padrão documentado em ParametrosBuscaAgendaVideos',
        obtido=f'status={resposta.status_code}, tela_atual={resposta.context.get("tela_atual")}',
        passou=passou,
    )
    assert passou


def test_tela_todos_mostra_produto_sem_cache_de_indicadores(client, tabela_resultados, regua_de_fases):
    # Função Objetivo: regressão do bug real já documentado no vault (cache
    # IndicadoresAgendaProduto nunca populado automaticamente) — a tela
    # Todos precisa ser a única que NUNCA exige esse cache, mesmo via HTTP.
    # Setup:
    produto = _criar_produto('SKU-TODOS-01')  # nunca sincronizado, de propósito

    # Exercise:
    resposta = client.get(reverse('agenda_videos_principal'), {'tela': Tela.TODOS})

    # Assert:
    ids_na_pagina = [p.id for p in resposta.context['pagina']]
    passou = (
        resposta.status_code == 200 and resposta.context['tela_atual'] == Tela.TODOS
        and resposta.context['contadores_chips'] == {} and produto.id in ids_na_pagina
    )
    registrar_resultado(
        tabela_resultados, teste='tela Todos mostra produto sem cache de indicadores',
        entrada='produto sem IndicadoresAgendaProduto, ?tela=todos', esperado='produto aparece, contadores_chips={}',
        motivo='Todos é a única tela sem depender do cache via INNER JOIN — regressão do bug real de 03/08',
        obtido=f'status={resposta.status_code}, contadores_chips={resposta.context.get("contadores_chips")}, produto_na_pagina={produto.id in ids_na_pagina}',
        passou=passou,
    )
    assert passou


def test_tela_todos_mostra_botao_de_verificar_drive_mesmo_sem_ciclo(client, tabela_resultados, regua_de_fases):
    # Função Objetivo: regressão do Bug 1 (ver "Botao de Verificar Drive
    # Individual Tinha 3 Bugs Reais" no vault) — o botão de verificar Drive
    # não pode ficar escondido atrás do ciclo_atual, porque a view que ele
    # chama não depende de ciclo nenhum pra funcionar.
    # Setup:
    produto = _criar_produto('SKU-TODOS-02')  # sem nenhum CicloVideo, de propósito

    # Exercise:
    resposta = client.get(reverse('agenda_videos_principal'), {'tela': Tela.TODOS})

    # Assert:
    html = resposta.content.decode()
    passou = (
        resposta.status_code == 200
        and f'agenda-card-{produto.id}' in html
        and 'agenda-verificar-drive-toggle' in html
    )
    registrar_resultado(
        tabela_resultados, teste='card sem ciclo_atual ainda mostra o botão de verificar Drive',
        entrada='produto sem nenhum CicloVideo, ?tela=todos',
        esperado='card renderiza e contém o botão agenda-verificar-drive-toggle',
        motivo='view_verificar_produto_drive só depende de produto_id — botão não pode ficar preso ao ciclo_atual',
        obtido=f'status={resposta.status_code}, card_presente={f"agenda-card-{produto.id}" in html}, botao_presente={"agenda-verificar-drive-toggle" in html}',
        passou=passou,
    )
    assert passou


def test_tela_invalida_cai_no_padrao_a_fazer_hoje(client, tabela_resultados):
    # Exercise:
    resposta = client.get(reverse('agenda_videos_principal'), {'tela': 'essa-tela-nao-existe'})

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['tela_atual'] == Tela.A_FAZER_HOJE
    registrar_resultado(
        tabela_resultados, teste='tela inválida na querystring → cai no padrão',
        entrada='?tela=essa-tela-nao-existe', esperado=f'tela_atual == {Tela.A_FAZER_HOJE!r}',
        motivo='Fallback de segurança contra valor forjado/desatualizado na URL',
        obtido=f'status={resposta.status_code}, tela_atual={resposta.context.get("tela_atual")}',
        passou=passou,
    )
    assert passou


def test_tela_simples_contador_de_chip_base_chega_no_contexto(client, tabela_resultados, regua_de_fases):
    # Setup: produto sincronizado, parado em Base dentro da fase Simples.
    produto = _criar_produto('SKU-SIMPLES-01')
    CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)
    sincronizar_indicadores_agenda_produto(produto)

    # Exercise:
    resposta = client.get(reverse('agenda_videos_principal'), {'tela': Tela.SIMPLES})

    # Assert:
    contadores = resposta.context['contadores_chips']
    passou = resposta.status_code == 200 and contadores.get('base', 0) >= 1
    registrar_resultado(
        tabela_resultados, teste='tela Simples: chip "base" reflete produto real no contexto',
        entrada='1 produto sincronizado, etapa_atual=base, ?tela=simples', esperado='contadores_chips["base"] >= 1',
        motivo='Confirma que o pipeline de chip-contador chega inteiro na página via HTTP',
        obtido=f'status={resposta.status_code}, contadores_chips={contadores}',
        passou=passou,
    )
    assert passou


def test_paginacao_por_pagina_1_gera_2_paginas_com_2_produtos(client, tabela_resultados, regua_de_fases):
    # Setup: 2 produtos elegíveis pra tela Todos (não depende de cache).
    _criar_produto('SKU-PAG-01')
    _criar_produto('SKU-PAG-02')

    # Exercise:
    resposta = client.get(reverse('agenda_videos_principal'), {'tela': Tela.TODOS, 'por_pagina': '1'})

    # Assert:
    num_pages = resposta.context['pagina'].paginator.num_pages
    passou = resposta.status_code == 200 and num_pages == 2
    registrar_resultado(
        tabela_resultados, teste='por_pagina=1 com 2 produtos → 2 páginas',
        entrada='2 produtos na tela Todos, ?por_pagina=1', esperado='paginator.num_pages == 2',
        motivo='Confirma que o parâmetro de paginação da URL chega até o Paginator real',
        obtido=f'status={resposta.status_code}, num_pages={num_pages}',
        passou=passou,
    )
    assert passou