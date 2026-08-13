"""
Nível 3 — listar_produtos_agenda_filtrados() / construir_queryset_tela() /
condicao_tela() / condicao_etapa() / _campos_ordenacao() / contar_por_condicoes()

Reescrita completa (13/08) — substitui a versão anterior (modelo de 5 telas:
Não Agendado/Simples/Vídeo Mensal/Vídeo Trimestral/A Fazer Hoje/Todos), que
ficou obsoleta com a reestruturação de 12/08 pras 6 telas de nível igual
(Geral/A Fazer Hoje/Aguardando Postar-Replicar/Aguardando Aprovação/Prontos
pra Agendar Mensal/Pausados na Agenda). Organizado em 9 blocos:

C0 — funções auxiliares "mecânicas" chamadas direto, sem cenário de produto
     (condicao_tela inválida, _campos_ordenacao, contar_por_condicoes).
C1 — escopo de cada uma das 6 telas (quem entra onde) + Geral é a única que
     mostra produto sem cache nenhum.
C2 — condicao_etapa(): a distinção completo x recusado (mesma etapa_atual,
     status diferente) e a soma base+nao_agendado.
C3 — A Fazer Hoje: Mensal/Trimestral entram em qualquer etapa de produção
     (têm prazo real); Simples só entra com Base já feito (Roteiro/Completo/
     Recusado) — decisão de 13/08. Postar/Aguardando Aprovação/Replicar/
     Concluído nunca entram (têm tela própria).
C4 — Aguardando Postar/Replicar: as 2 sub-abas (aba=postar/replicar), sem
     filtro de data.
C5 — Aguardando Aprovação: escopo fixo + ordenação fixa por tempo de espera,
     ignorando "ordenar".
C6 — Prontos pra Agendar Mensal: só Simples+concluído.
C7 — Pausados na Agenda: única tela onde Pausado/Descontinuado aparece;
     filtro interno pra separar só Pausado de só Descontinuado.
C8 — Geral: Período (com o fix de fase_atual='' pro Período=Simples), Etapa
     (8 chips, incluindo "concluido" novo) e ordenação escolhida pelo usuário.
C9 — filtros compartilhados (marca/urgente/sem_video/sincronizado_drive/
     status_postagem/atrasado/risco/faixa) — smoke test, a lógica em si não
     muda de tela pra tela, só de onde a query nasce.

DOC (sincronizar_indicadores_agenda_produto / status_manual_atual) já
validado nas camadas de baixo — aqui o cache (IndicadoresAgendaProduto/
ParticipacaoAgenda/SnapshotArquivosDrive) é preenchido manualmente por
cenário, nunca via sincronização de verdade.
"""
from datetime import date, datetime, timedelta

import pytest
from django.utils import timezone

from agenda_videos.funcoes_auxiliares.filtros_agenda_videos import (
    Tela, Periodo, OPCOES_ETAPA, ETAPAS_FABRICA,
    condicao_etapa, condicao_tela, contar_por_condicoes, _campos_ordenacao,
    construir_queryset_tela, listar_produtos_agenda_filtrados,
)
from agenda_videos.models.ciclo_video import CicloVideo, StatusPostagem
from agenda_videos.models.configuracao_fase import Fase
from agenda_videos.models.indicadores_agenda_produto import IndicadoresAgendaProduto
from agenda_videos.models.participacao_agenda import ParticipacaoAgenda, StatusManualAgenda
from agenda_videos.models.snapshot_arquivos_drive import SnapshotArquivosDrive, VALIDADE_SNAPSHOT_DRIVE
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 3 — listar_produtos_agenda_filtrados() e auxiliares (filtros_agenda_videos.py)'

# data_referencia fixa: quarta 12/08/2026. hoje=12/08, limite_risco=13/08.
DATA_REFERENCIA = date(2026, 8, 12)


def _criar_produto(rotulo, titulo=None, marca=None):
    return Produto.objects.create(
        ean=f'EAN{abs(hash(rotulo)) % 1000000}',
        titulo=titulo or f'Produto {rotulo}',
        marca=marca,
    )


def _criar_produto_com_ciclo(
    rotulo, fase=Fase.VIDEO_MENSAL, etapa_atual='base', data_devida=None,
    status_ciclo=None, aguardando_aprovacao_em=None, titulo=None, marca=None,
    **indicadores_overrides,
):
    # Monta um produto com CicloVideo + cache (IndicadoresAgendaProduto) já
    # preenchido — sincronização (DOC) já validada nas camadas de baixo, aqui
    # só se preenche o cache manualmente por cenário.
    produto = _criar_produto(rotulo, titulo=titulo, marca=marca)
    CicloVideo.objects.create(
        produto=produto, fase=fase, numero_ocorrencia=1,
        data_devida=data_devida, status=status_ciclo, aguardando_aprovacao_em=aguardando_aprovacao_em,
    )
    campos_indicadores = {
        'fase_atual': fase, 'etapa_atual': etapa_atual,
        'ciclo_atual_atrasado': False, 'tem_video_reprovado': False,
        'status_manual': StatusManualAgenda.ATIVO,
    }
    campos_indicadores.update(indicadores_overrides)
    IndicadoresAgendaProduto.objects.create(produto=produto, **campos_indicadores)
    return produto


def _criar_produto_nunca_tocado(rotulo, titulo=None, marca=None):
    # Sem NENHUM CicloVideo — cache sintético etapa_atual='nao_agendado',
    # fase_atual='' (nunca 'simples', mesmo sendo o ponto de entrada real).
    produto = _criar_produto(rotulo, titulo=titulo, marca=marca)
    IndicadoresAgendaProduto.objects.create(
        produto=produto, fase_atual='', etapa_atual='nao_agendado',
        ciclo_atual_atrasado=False, tem_video_reprovado=False, status_manual=StatusManualAgenda.ATIVO,
    )
    return produto


def _aparece(produto, resultado):
    return resultado.filter(pk=produto.pk).exists()


# ============================================================
# C0 — funções auxiliares mecânicas, chamadas direto
# ============================================================

def test_condicao_tela_valor_desconhecido_levanta_erro(tabela_resultados):
    # Setup: nenhum — condicao_tela não toca banco, só monta Q().
    with pytest.raises(ValueError) as excinfo:
        condicao_tela('essa-tela-nao-existe')

    levantou = True
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_condicao_tela_valor_desconhecido_levanta_erro',
        "tela='essa-tela-nao-existe'",
        esperado, 'guarda de segurança — nunca deve cair em silêncio pra um valor forjado',
        levantou, levantou == esperado,
        dado_bruto=str(excinfo.value),
    )
    assert levantou == esperado


def test_campos_ordenacao_aguardando_aprovacao_ignora_ordenar(tabela_resultados):
    resultado = _campos_ordenacao(Tela.AGUARDANDO_APROVACAO, ordenar='-titulo')
    esperado = ('-aguardando_aprovacao_em_ciclo_atual',)
    registrar_resultado(
        tabela_resultados, 'test_campos_ordenacao_aguardando_aprovacao_ignora_ordenar',
        "tela=aguardando_aprovacao, ordenar='-titulo' (deveria ser ignorado)",
        esperado, 'única tela ordenada só por tempo de espera — nunca por escolha do usuário',
        resultado, resultado == esperado,
    )
    assert resultado == esperado


@pytest.mark.parametrize('tela', [
    Tela.A_FAZER_HOJE, Tela.AGUARDANDO_POSTAR_REPLICAR, Tela.PRONTOS_AGENDAR, Tela.PAUSADOS,
], ids=['a_fazer_hoje', 'aguardando_postar_replicar', 'prontos_agendar', 'pausados'])
def test_campos_ordenacao_outras_4_telas_usa_ordenacao_fixa(tabela_resultados, tela):
    resultado = _campos_ordenacao(tela, ordenar='-titulo')
    esperado = ('prioridade_ordenacao', 'ordenacao_fase', 'data_devida_ciclo_atual')
    registrar_resultado(
        tabela_resultados, 'test_campos_ordenacao_outras_4_telas_usa_ordenacao_fixa',
        f"tela={tela}, ordenar='-titulo' (deveria ser ignorado)",
        esperado, 'prioridade→fase→prazo fixo — só Geral e Aguardando Aprovação escapam desta regra',
        resultado, resultado == esperado,
    )
    assert resultado == esperado


def test_campos_ordenacao_geral_ordenar_padrao(tabela_resultados):
    resultado = _campos_ordenacao(Tela.GERAL, ordenar='titulo')
    esperado = ('prioridade_ordenacao', 'ordenacao_fase', 'titulo')
    registrar_resultado(
        tabela_resultados, 'test_campos_ordenacao_geral_ordenar_padrao',
        "tela=geral, ordenar='titulo'",
        esperado, "sem '-', campo entra puro — mapeado por CAMPOS_ORDENACAO",
        resultado, resultado == esperado,
    )
    assert resultado == esperado


def test_campos_ordenacao_geral_ordenar_invertido(tabela_resultados):
    resultado = _campos_ordenacao(Tela.GERAL, ordenar='-marca')
    esperado = ('prioridade_ordenacao', 'ordenacao_fase', '-marca')
    registrar_resultado(
        tabela_resultados, 'test_campos_ordenacao_geral_ordenar_invertido',
        "tela=geral, ordenar='-marca'",
        esperado, "'-' na entrada precisa reaparecer no campo mapeado, não só sobreviver junto",
        resultado, resultado == esperado,
    )
    assert resultado == esperado


def test_campos_ordenacao_geral_ordenar_desconhecido_cai_no_titulo(tabela_resultados):
    resultado = _campos_ordenacao(Tela.GERAL, ordenar='campo_que_nao_existe')
    esperado = ('prioridade_ordenacao', 'ordenacao_fase', 'titulo')
    registrar_resultado(
        tabela_resultados, 'test_campos_ordenacao_geral_ordenar_desconhecido_cai_no_titulo',
        "tela=geral, ordenar='campo_que_nao_existe'",
        esperado, 'CAMPOS_ORDENACAO.get(..., "titulo") — chave fora do mapa nunca quebra, cai no padrão',
        resultado, resultado == esperado,
    )
    assert resultado == esperado


def test_contar_por_condicoes(tabela_resultados):
    # Setup: 2 produtos Mensal, 1 em base, 1 em roteiro.
    _criar_produto_com_ciclo('contar_a', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    _criar_produto_com_ciclo('contar_b', fase=Fase.VIDEO_MENSAL, etapa_atual='roteiro')

    qs, _ = construir_queryset_tela(Tela.GERAL, data_referencia=DATA_REFERENCIA)
    resultado = contar_por_condicoes(qs, {
        'base': condicao_etapa('base'), 'roteiro': condicao_etapa('roteiro'),
    })

    esperado = {'base': 1, 'roteiro': 1}
    registrar_resultado(
        tabela_resultados, 'test_contar_por_condicoes',
        '1 produto em base, 1 em roteiro, condições={base, roteiro}',
        esperado, 'wrapper fino sobre qs.aggregate(Count(pk, filter=...)) — 1 contagem por condição',
        resultado, resultado == esperado,
    )
    assert resultado == esperado


# ============================================================
# C1 — escopo de cada uma das 6 telas + Geral mostra sem-cache
# ============================================================

def test_produto_sem_cache_nenhum_so_aparece_em_geral(tabela_resultados):
    # Setup: produto "cru" — nem CicloVideo, nem IndicadoresAgendaProduto.
    # Geral é a única sem restrição nenhuma (condicao_tela devolve Q()); as
    # outras 5 filtram via indicadores_agenda__X, que exige o cache existir.
    produto = _criar_produto('cru_sem_cache')

    aparece_em = {
        tela: _aparece(produto, listar_produtos_agenda_filtrados(tela=tela, data_referencia=DATA_REFERENCIA))
        for tela in Tela.values
    }
    esperado = {tela: (tela == Tela.GERAL) for tela in Tela.values}
    registrar_resultado(
        tabela_resultados, 'test_produto_sem_cache_nenhum_so_aparece_em_geral',
        'produto sem CicloVideo e sem IndicadoresAgendaProduto, nas 6 telas',
        esperado, 'Geral não filtra nada (Q() puro) — as outras 5 exigem cache sincronizado',
        aparece_em, aparece_em == esperado,
    )
    assert aparece_em == esperado

    # TearDown: nada a desmontar.


def test_geral_exclui_pausado_e_descontinuado_por_padrao(tabela_resultados):
    # Setup: decisão de 12/08 — Pausado/Descontinuado só aparece na tela
    # própria, nunca em Geral (diferente do modelo antigo, onde as telas de
    # fase mostravam pausado por padrão).
    produto_pausado = _criar_produto_com_ciclo(
        'geral_pausado', fase=Fase.VIDEO_MENSAL, etapa_atual='base', status_manual=StatusManualAgenda.PAUSADO,
    )
    produto_descontinuado = _criar_produto_com_ciclo(
        'geral_descontinuado', fase=Fase.VIDEO_MENSAL, etapa_atual='base', status_manual=StatusManualAgenda.DESCONTINUADO,
    )
    produto_ativo = _criar_produto_com_ciclo('geral_ativo', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.GERAL, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_pausado, resultado), _aparece(produto_descontinuado, resultado), _aparece(produto_ativo, resultado))
    esperado = (False, False, True)
    registrar_resultado(
        tabela_resultados, 'test_geral_exclui_pausado_e_descontinuado_por_padrao',
        'Pausado | Descontinuado | Ativo, tela Geral, sem filtro nenhum',
        esperado, 'Pausado/Descontinuado só existem na tela própria — Geral exclui sempre, sem opção de trazer de volta',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_aguardando_aprovacao_pega_so_essa_etapa(tabela_resultados):
    produto_certo = _criar_produto_com_ciclo('aa_certo', fase=Fase.VIDEO_MENSAL, etapa_atual='aguardando_aprovacao')
    produto_errado = _criar_produto_com_ciclo('aa_errado', fase=Fase.VIDEO_MENSAL, etapa_atual='completo')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.AGUARDANDO_APROVACAO, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_certo, resultado), _aparece(produto_errado, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_aguardando_aprovacao_pega_so_essa_etapa',
        'A etapa=aguardando_aprovacao | B etapa=completo',
        esperado, 'escopo fixo — só quem está esperando resposta do marketplace',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_aguardando_aprovacao_ordena_por_tempo_de_espera_ignorando_ordenar(tabela_resultados):
    # Setup: 2 produtos aguardando aprovação, esperas diferentes.
    momento_antigo = timezone.make_aware(datetime(2026, 8, 1, 9, 0))
    momento_recente = timezone.make_aware(datetime(2026, 8, 10, 9, 0))
    produto_antigo = _criar_produto_com_ciclo(
        'aa_espera_antiga', fase=Fase.VIDEO_MENSAL, etapa_atual='aguardando_aprovacao',
        aguardando_aprovacao_em=momento_antigo, titulo='ZZZ Produto',
    )
    produto_recente = _criar_produto_com_ciclo(
        'aa_espera_recente', fase=Fase.VIDEO_MENSAL, etapa_atual='aguardando_aprovacao',
        aguardando_aprovacao_em=momento_recente, titulo='AAA Produto',
    )

    # Exercise: pede ordenar='titulo' de propósito — deve ser ignorado.
    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.AGUARDANDO_APROVACAO, ordenar='titulo', data_referencia=DATA_REFERENCIA,
    )

    ids_na_ordem = list(resultado.filter(
        pk__in=[produto_antigo.pk, produto_recente.pk],
    ).values_list('pk', flat=True))
    esperado = [produto_recente.pk, produto_antigo.pk]
    registrar_resultado(
        tabela_resultados, 'test_aguardando_aprovacao_ordena_por_tempo_de_espera_ignorando_ordenar',
        'A: espera desde 01/08 | B: espera desde 10/08. ordenar="titulo" pedido de propósito',
        'B antes de A (mais recente primeiro)',
        '"os mais recentes primeiro" — único critério desta tela, "ordenar" nunca tem efeito',
        ids_na_ordem, ids_na_ordem == esperado,
    )
    assert ids_na_ordem == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C2 — condicao_etapa(): completo x recusado (mesma etapa_atual, status
# diferente) e a soma base + nao_agendado
# ============================================================

def test_condicao_etapa_base_soma_nao_agendado(tabela_resultados):
    # Setup: 1 nunca tocado (nao_agendado sintético), 1 com ciclo real em base.
    produto_nunca_tocado = _criar_produto_nunca_tocado('etapa_base_nunca_tocado')
    produto_em_base = _criar_produto_com_ciclo('etapa_base_real', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.GERAL, filtros={'etapa': ['base']}, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_nunca_tocado, resultado), _aparece(produto_em_base, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'test_condicao_etapa_base_soma_nao_agendado',
        'nunca tocado (nao_agendado) | ciclo real em base, chip Etapa=[base]',
        esperado, "'base' soma as 2 situações — pedem a mesma ação (produzir a Base)",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_condicao_etapa_completo_exclui_recusado(tabela_resultados):
    # Setup: 2 produtos com etapa_atual()='completo' (mesmo valor!) — 1 sem
    # status (aguardando ser postado normalmente), 1 com status=Recusado
    # (voltou pra completo depois de reprovado). condicao_etapa('completo')
    # só deve pegar o 1º — o 2º é "recusado" de verdade, tem chip próprio.
    produto_completo_normal = _criar_produto_com_ciclo(
        'etapa_completo_normal', fase=Fase.VIDEO_MENSAL, etapa_atual='completo', status_ciclo=None,
    )
    produto_recusado = _criar_produto_com_ciclo(
        'etapa_completo_recusado', fase=Fase.VIDEO_MENSAL, etapa_atual='completo', status_ciclo=StatusPostagem.RECUSADO,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.GERAL, filtros={'etapa': ['completo']}, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_completo_normal, resultado), _aparece(produto_recusado, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_condicao_etapa_completo_exclui_recusado',
        'A: completo, status=None | B: completo, status=Recusado. Chip Etapa=[completo]',
        esperado, 'NULL-safe: status isnull=True inclui A; ~Q(status=Recusado) exclui B mesmo com a mesma etapa_atual',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_condicao_etapa_completo_inclui_status_nao_recusado(tabela_resultados):
    # Setup: etapa_atual()='completo' só é possível com status=None ou
    # status=Recusado (ver CicloVideo.etapa_atual()) — mas o próprio Q()
    # usa ~Q(status=Recusado), então qualquer status diferente de Recusado
    # (mesmo um hipotético) também entraria. Prova o outro lado do OR: quem
    # bate por não-ser-Recusado, não por ser NULL.
    produto = _criar_produto_com_ciclo(
        'etapa_completo_status_aprovado', fase=Fase.VIDEO_MENSAL, etapa_atual='completo', status_ciclo=StatusPostagem.APROVADO,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.GERAL, filtros={'etapa': ['completo']}, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_condicao_etapa_completo_inclui_status_nao_recusado',
        'etapa=completo, status=Aprovado (status preenchido, mas não Recusado)',
        esperado, 'prova o 2º ramo do OR: ~Q(status=Recusado) inclui quem tem status preenchido e diferente de Recusado',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_condicao_etapa_recusado_pega_status_recusado(tabela_resultados):
    produto = _criar_produto_com_ciclo(
        'etapa_recusado', fase=Fase.VIDEO_MENSAL, etapa_atual='completo', status_ciclo=StatusPostagem.RECUSADO,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.GERAL, filtros={'etapa': ['recusado']}, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_condicao_etapa_recusado_pega_status_recusado',
        'etapa_atual=completo, status_ciclo_atual=Recusado, chip Etapa=[recusado]',
        esperado, "chip próprio de 'recusado' filtra por status, não por etapa_atual",
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


@pytest.mark.parametrize('chave', ['roteiro', 'postar', 'aguardando_aprovacao', 'replicar', 'concluido'], ids=lambda c: c)
def test_condicao_etapa_passthrough_direto(tabela_resultados, chave):
    # Setup: as 5 etapas restantes caem no caso "_": Q(etapa_atual=chave) puro.
    produto_certo = _criar_produto_com_ciclo(f'etapa_passthrough_certo_{chave}', fase=Fase.VIDEO_MENSAL, etapa_atual=chave)
    produto_errado = _criar_produto_com_ciclo(f'etapa_passthrough_errado_{chave}', fase=Fase.VIDEO_MENSAL, etapa_atual='roteiro' if chave != 'roteiro' else 'base')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.GERAL, filtros={'etapa': [chave]}, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_certo, resultado), _aparece(produto_errado, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_condicao_etapa_passthrough_direto',
        f"etapa_atual='{chave}', chip Etapa=[{chave}]",
        esperado, 'caso genérico do match — Q(etapa_atual=chave) puro, sem regra extra',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C3 — A Fazer Hoje: Mensal/Trimestral qualquer etapa de produção x Simples
# só com Base já feito (decisão de 13/08)
# ============================================================

@pytest.mark.parametrize('etapa', ETAPAS_FABRICA, ids=lambda e: e)
def test_a_fazer_hoje_mensal_entra_em_qualquer_etapa_de_producao(tabela_resultados, etapa):
    # Setup: Mensal, sem nenhum motivo de urgência (não atrasado, sem risco,
    # sem vídeo reprovado) — mesmo assim entra, porque tem prazo real.
    status_ciclo = StatusPostagem.RECUSADO if etapa == 'recusado' else None
    etapa_real = 'completo' if etapa == 'recusado' else etapa
    produto = _criar_produto_com_ciclo(
        f'afh_mensal_{etapa}', fase=Fase.VIDEO_MENSAL, etapa_atual=etapa_real, status_ciclo=status_ciclo,
        data_devida=date(2026, 8, 30), ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_mensal_entra_em_qualquer_etapa_de_producao',
        f'Vídeo Mensal, etapa={etapa}, prazo=30/08 (longe), não atrasado',
        esperado, 'Mensal/Trimestral têm prazo real — qualquer etapa de produção entra, mesmo sem urgência aparente',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_trimestral_entra_em_base_espelhando_mensal(tabela_resultados):
    # Setup: espelho do parametrize acima, só confirma que Trimestral segue
    # a mesma regra de Mensal (não é regra exclusiva de 1 fase).
    produto = _criar_produto_com_ciclo(
        'afh_trimestral_base', fase=Fase.VIDEO_TRIMESTRAL, etapa_atual='base',
        data_devida=date(2026, 8, 30), ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_trimestral_entra_em_base_espelhando_mensal',
        'Vídeo Trimestral, etapa=base, prazo longe, não atrasado',
        esperado, 'mesma regra do Mensal, espelhada pro Trimestral',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_simples_nunca_tocado_nao_entra(tabela_resultados):
    # Setup: Simples nunca tocado (nao_agendado sintético) — decisão de
    # 13/08: virou backlog puro, não é "urgente hoje".
    produto = _criar_produto_nunca_tocado('afh_simples_nunca_tocado')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_simples_nunca_tocado_nao_entra',
        'Simples nunca tocado (etapa_atual=nao_agendado sintético)',
        esperado, 'sem nenhum progresso ainda — é backlog, não motivo de urgência hoje',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_simples_em_base_com_ciclo_real_nao_entra(tabela_resultados):
    # Setup: diferente do teste anterior — aqui já EXISTE CicloVideo, mas
    # ainda parado em Base (nunca produziu nada). Mesmo resultado do
    # "nunca tocado": ainda não fez progresso nenhum.
    produto = _criar_produto_com_ciclo('afh_simples_base_real', fase=Fase.SIMPLES, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_simples_em_base_com_ciclo_real_nao_entra',
        'Simples, CicloVideo real existe, etapa_atual=base',
        esperado, 'ainda não tem Base feito — mesma regra de quem nunca foi tocado',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


@pytest.mark.parametrize('etapa', ['roteiro', 'completo', 'recusado'], ids=lambda e: e)
def test_a_fazer_hoje_simples_com_base_feito_entra(tabela_resultados, etapa):
    # Setup: Simples já passou de Base (Roteiro/Completo/Recusado) —
    # "faltam processos a serem feitos" (motivo dado pelo usuário, 13/08).
    status_ciclo = StatusPostagem.RECUSADO if etapa == 'recusado' else None
    etapa_real = 'completo' if etapa == 'recusado' else etapa
    produto = _criar_produto_com_ciclo(
        f'afh_simples_{etapa}', fase=Fase.SIMPLES, etapa_atual=etapa_real, status_ciclo=status_ciclo,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_simples_com_base_feito_entra',
        f'Simples, etapa={etapa} (Base já feito)',
        esperado, 'processo em andamento que falta terminar — entra mesmo sem prazo',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


@pytest.mark.parametrize('fase,etapa', [
    (Fase.VIDEO_MENSAL, 'postar'), (Fase.VIDEO_MENSAL, 'aguardando_aprovacao'),
    (Fase.VIDEO_MENSAL, 'replicar'), (Fase.VIDEO_MENSAL, 'concluido'),
    (Fase.SIMPLES, 'postar'), (Fase.SIMPLES, 'aguardando_aprovacao'),
    (Fase.SIMPLES, 'replicar'), (Fase.SIMPLES, 'concluido'),
], ids=lambda v: str(v))
def test_a_fazer_hoje_nunca_pega_etapas_fora_de_producao(tabela_resultados, fase, etapa):
    # Setup: postar/aguardando_aprovacao/replicar/concluido têm tela própria
    # (Aguardando Postar-Replicar, Aguardando Aprovação, Prontos pra
    # Agendar) — não fazem mais parte do escopo de A Fazer Hoje, nem pra
    # Mensal/Trimestral nem pra Simples.
    produto = _criar_produto_com_ciclo(f'afh_fora_producao_{fase}_{etapa}', fase=fase, etapa_atual=etapa)

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_nunca_pega_etapas_fora_de_producao',
        f'fase={fase}, etapa={etapa}',
        esperado, 'etapa fora de ETAPAS_FABRICA tem tela própria — nunca aparece em A Fazer Hoje',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_exclui_pausado_e_descontinuado_incondicionalmente(tabela_resultados):
    produto_pausado = _criar_produto_com_ciclo(
        'afh_pausado', fase=Fase.VIDEO_MENSAL, etapa_atual='base', status_manual=StatusManualAgenda.PAUSADO,
    )
    produto_descontinuado = _criar_produto_com_ciclo(
        'afh_descontinuado', fase=Fase.VIDEO_MENSAL, etapa_atual='base', status_manual=StatusManualAgenda.DESCONTINUADO,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_pausado, resultado), _aparece(produto_descontinuado, resultado))
    esperado = (False, False)
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_exclui_pausado_e_descontinuado_incondicionalmente',
        'Pausado etapa=base | Descontinuado etapa=base',
        esperado, 'A Fazer Hoje é lista de ação — pausado/descontinuado nunca é "pra fazer"',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_etapa_chip_ignora_chave_fora_de_etapas_fabrica(tabela_resultados):
    # Setup: dentro de A Fazer Hoje, o chip de Etapa só aceita as 4 de
    # ETAPAS_FABRICA — pedir uma etapa fora dessa lista (ex: 'postar', que
    # é válida em Geral) é ignorada silenciosamente (linha 314: "if chave
    # in chaves_validas"). Como nenhuma chave válida sobra, condicao_combinada
    # fica um Q() vazio — que em .filter() não restringe nada, então a tela
    # continua mostrando tudo que já era do escopo dela (não vira "vazio").
    produto_base = _criar_produto_com_ciclo('afh_chip_base', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.A_FAZER_HOJE, filtros={'etapa': ['postar']}, data_referencia=DATA_REFERENCIA,
    )

    aparece = _aparece(produto_base, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_etapa_chip_ignora_chave_fora_de_etapas_fabrica',
        "Mensal em Base, chip Etapa=['postar'] (fora de ETAPAS_FABRICA)",
        esperado, "'postar' não está em ETAPAS_FABRICA — Q() vazio não filtra nada, produto continua aparecendo",
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_etapa_chip_recusado_estreita_certo(tabela_resultados):
    produto_recusado = _criar_produto_com_ciclo(
        'afh_chip_recusado', fase=Fase.VIDEO_MENSAL, etapa_atual='completo', status_ciclo=StatusPostagem.RECUSADO,
    )
    produto_base = _criar_produto_com_ciclo('afh_chip_base_2', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.A_FAZER_HOJE, filtros={'etapa': ['recusado']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_recusado, resultado), _aparece(produto_base, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_etapa_chip_recusado_estreita_certo',
        "A: recusado | B: base. Chip Etapa=['recusado']",
        esperado, "'recusado' está em ETAPAS_FABRICA — chip estreita normalmente dentro da tela",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_ordena_por_prioridade_fase_prazo_ignorando_ordenar(tabela_resultados):
    produto_prioridade_alta = _criar_produto_com_ciclo(
        'afh_ordem_alta', fase=Fase.VIDEO_TRIMESTRAL, etapa_atual='base',
        tem_video_reprovado=True, ciclo_atual_atrasado=True,
    )
    ParticipacaoAgenda.objects.create(produto=produto_prioridade_alta, urgente=True)

    produto_prioridade_baixa = _criar_produto_com_ciclo(
        'afh_ordem_baixa', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=True,
    )

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.A_FAZER_HOJE, ordenar='-titulo', data_referencia=DATA_REFERENCIA,
    )

    ids_na_ordem = list(resultado.filter(
        pk__in=[produto_prioridade_alta.pk, produto_prioridade_baixa.pk],
    ).values_list('pk', flat=True))
    esperado = [produto_prioridade_alta.pk, produto_prioridade_baixa.pk]
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_ordena_por_prioridade_fase_prazo_ignorando_ordenar',
        'A: urgente+sem vídeo (prioridade máxima) | B: só atrasado. ordenar=-titulo pedido de propósito',
        'A antes de B',
        'A Fazer Hoje sempre ordena prioridade→fase→prazo — "ordenar" do usuário não tem efeito aqui',
        ids_na_ordem, ids_na_ordem == esperado,
    )
    assert ids_na_ordem == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C4 — Aguardando Postar/Replicar: as 2 sub-abas, sem filtro de data
# ============================================================

def test_aguardando_postar_replicar_escopo_bruto_e_uniao_de_postar_e_replicar(tabela_resultados):
    # Setup: chama construir_queryset_tela() DIRETO, não listar_produtos_
    # agenda_filtrados() — essa última sempre aplica o narrowing de aba
    # (default 'postar', linha 318), então nunca mostraria o union bruto.
    # condicao_tela() em si (o escopo da tela, antes de qualquer aba) é
    # que precisa ser union — é isso que este teste prova.
    produto_postar = _criar_produto_com_ciclo('apr_postar', fase=Fase.VIDEO_MENSAL, etapa_atual='postar')
    produto_replicar = _criar_produto_com_ciclo('apr_replicar', fase=Fase.VIDEO_TRIMESTRAL, etapa_atual='replicar')
    produto_fora = _criar_produto_com_ciclo('apr_fora', fase=Fase.VIDEO_MENSAL, etapa_atual='completo')

    resultado, _ = construir_queryset_tela(Tela.AGUARDANDO_POSTAR_REPLICAR, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_postar, resultado), _aparece(produto_replicar, resultado), _aparece(produto_fora, resultado))
    esperado = (True, True, False)
    registrar_resultado(
        tabela_resultados, 'test_aguardando_postar_replicar_escopo_bruto_e_uniao_de_postar_e_replicar',
        'Postar | Replicar | Completo — direto em construir_queryset_tela, sem passar por listar_produtos_agenda_filtrados',
        esperado, 'condicao_tela() em si é a união das 2 — o narrowing pra 1 sub-aba só acontece 1 nível acima',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_aguardando_postar_replicar_sem_aba_usa_postar_como_padrao(tabela_resultados):
    produto_postar = _criar_produto_com_ciclo('apr_padrao_postar', fase=Fase.VIDEO_MENSAL, etapa_atual='postar')
    produto_replicar = _criar_produto_com_ciclo('apr_padrao_replicar', fase=Fase.VIDEO_MENSAL, etapa_atual='replicar')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.AGUARDANDO_POSTAR_REPLICAR, filtros={}, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_postar, resultado), _aparece(produto_replicar, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_aguardando_postar_replicar_sem_aba_usa_postar_como_padrao',
        "filtros={} (sem 'aba'), Postar | Replicar",
        esperado, "filtros.get('aba') or 'postar' — sem aba explícita, cai em Postar",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_aguardando_postar_replicar_aba_replicar_estreita(tabela_resultados):
    produto_postar = _criar_produto_com_ciclo('apr_aba_postar', fase=Fase.VIDEO_MENSAL, etapa_atual='postar')
    produto_replicar = _criar_produto_com_ciclo('apr_aba_replicar', fase=Fase.VIDEO_MENSAL, etapa_atual='replicar')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.AGUARDANDO_POSTAR_REPLICAR, filtros={'aba': 'replicar'}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_postar, resultado), _aparece(produto_replicar, resultado))
    esperado = (False, True)
    registrar_resultado(
        tabela_resultados, 'test_aguardando_postar_replicar_aba_replicar_estreita',
        "aba='replicar', Postar | Replicar",
        esperado, 'clicar na sub-aba Replicar mostra só quem está esperando replicar',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_aguardando_postar_replicar_nao_filtra_por_data(tabela_resultados):
    # Setup: 2 produtos em Postar, 1 com prazo bem no futuro, 1 sem data
    # nenhuma (Trimestral pode não ter, embora normalmente tenha) — decisão
    # de 12/08: "Hoje" no nome descreve rotina, não é condição de query.
    produto_prazo_futuro = _criar_produto_com_ciclo(
        'apr_sem_data_futuro', fase=Fase.VIDEO_MENSAL, etapa_atual='postar', data_devida=date(2026, 12, 31),
    )
    produto_sem_prazo = _criar_produto_com_ciclo(
        'apr_sem_data_nenhuma', fase=Fase.VIDEO_MENSAL, etapa_atual='postar', data_devida=None,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.AGUARDANDO_POSTAR_REPLICAR, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_prazo_futuro, resultado), _aparece(produto_sem_prazo, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'test_aguardando_postar_replicar_nao_filtra_por_data',
        'A: prazo=31/12 (bem no futuro) | B: sem data_devida nenhuma',
        esperado, 'mostra tudo que está pronto, independente de data_devida — nunca escondido por vencer "depois"',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_aguardando_postar_replicar_exclui_pausado(tabela_resultados):
    produto = _criar_produto_com_ciclo(
        'apr_pausado', fase=Fase.VIDEO_MENSAL, etapa_atual='postar', status_manual=StatusManualAgenda.PAUSADO,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.AGUARDANDO_POSTAR_REPLICAR, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_aguardando_postar_replicar_exclui_pausado',
        'Pausado, etapa=postar',
        esperado, 'mesma exclusão incondicional das outras telas fora de Pausados',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C6 — Prontos pra Agendar Mensal: só Simples + concluído
# ============================================================

def test_prontos_agendar_pega_simples_concluido(tabela_resultados):
    produto = _criar_produto_com_ciclo('pam_simples_concluido', fase=Fase.SIMPLES, etapa_atual='concluido')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.PRONTOS_AGENDAR, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_prontos_agendar_pega_simples_concluido',
        'Simples, etapa_atual=concluido',
        esperado, 'Simples já replicado — só falta o clique de Agendar',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_prontos_agendar_nao_pega_simples_em_andamento(tabela_resultados):
    produto = _criar_produto_com_ciclo('pam_simples_andamento', fase=Fase.SIMPLES, etapa_atual='roteiro')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.PRONTOS_AGENDAR, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_prontos_agendar_nao_pega_simples_em_andamento',
        'Simples, etapa_atual=roteiro',
        esperado, 'ainda não terminou — não é "pronto" pra agendar nada ainda',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_prontos_agendar_nao_pega_mensal_concluido(tabela_resultados):
    # Setup: Vídeo Mensal também passa por 'concluido' momentaneamente
    # (antes de criar_proximo() rodar) — a condição exige fase=Simples
    # também, não só a etapa.
    produto = _criar_produto_com_ciclo('pam_mensal_concluido', fase=Fase.VIDEO_MENSAL, etapa_atual='concluido')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.PRONTOS_AGENDAR, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_prontos_agendar_nao_pega_mensal_concluido',
        'Vídeo Mensal, etapa_atual=concluido',
        esperado, 'concluido sozinho não basta — a condição exige fase=Simples também',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C7 — Pausados na Agenda: única tela onde Pausado/Descontinuado aparece
# ============================================================

def test_pausados_pega_pausado_e_descontinuado(tabela_resultados):
    produto_pausado = _criar_produto_com_ciclo(
        'pausados_pausado', fase=Fase.VIDEO_MENSAL, etapa_atual='base', status_manual=StatusManualAgenda.PAUSADO,
    )
    produto_descontinuado = _criar_produto_com_ciclo(
        'pausados_descontinuado', fase=Fase.VIDEO_MENSAL, etapa_atual='base', status_manual=StatusManualAgenda.DESCONTINUADO,
    )
    produto_ativo = _criar_produto_com_ciclo('pausados_ativo', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.PAUSADOS, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_pausado, resultado), _aparece(produto_descontinuado, resultado), _aparece(produto_ativo, resultado))
    esperado = (True, True, False)
    registrar_resultado(
        tabela_resultados, 'test_pausados_pega_pausado_e_descontinuado',
        'Pausado | Descontinuado | Ativo, sem filtro',
        esperado, 'única tela que existe justamente pra mostrar os 2 — Ativo nunca entra aqui',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_pausados_filtro_interno_separa_so_pausado(tabela_resultados):
    # Setup: dentro da própria tela Pausados, o filtro status_manual serve
    # pra separar só Pausado de só Descontinuado (linha 241 — branch elif,
    # só existe quando tela == Pausados).
    produto_pausado = _criar_produto_com_ciclo(
        'pausados_filtro_pausado', fase=Fase.VIDEO_MENSAL, etapa_atual='base', status_manual=StatusManualAgenda.PAUSADO,
    )
    produto_descontinuado = _criar_produto_com_ciclo(
        'pausados_filtro_descontinuado', fase=Fase.VIDEO_MENSAL, etapa_atual='base', status_manual=StatusManualAgenda.DESCONTINUADO,
    )

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.PAUSADOS, filtros={'status_manual': [StatusManualAgenda.PAUSADO]}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_pausado, resultado), _aparece(produto_descontinuado, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_pausados_filtro_interno_separa_so_pausado',
        'Pausado | Descontinuado, filtro status_manual=[Pausado], tela Pausados',
        esperado, 'narrowing interno — não é exclusão nem inclusão global, é filtro dentro do próprio escopo',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C8 — Geral: Período (com o fix de fase_atual='' pro Período=Simples),
# Etapa (8 chips) e ordenação escolhida pelo usuário
# ============================================================

def test_geral_periodo_todos_nao_filtra(tabela_resultados):
    produto_simples = _criar_produto_com_ciclo('geral_periodo_todos_simples', fase=Fase.SIMPLES, etapa_atual='base')
    produto_mensal = _criar_produto_com_ciclo('geral_periodo_todos_mensal', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'periodo': Periodo.TODOS}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_simples, resultado), _aparece(produto_mensal, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'test_geral_periodo_todos_nao_filtra',
        'Simples | Vídeo Mensal, periodo=Todos',
        esperado, "'todos' é a saída explícita do filtro — nunca aplica fase_atual nenhum",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_geral_periodo_simples_inclui_nunca_tocado(tabela_resultados):
    # Setup: fix de 12/08 — produto nunca tocado tem fase_atual='' (nunca
    # 'simples' de verdade), mas já É Simples na prática (ponto de entrada).
    produto_nunca_tocado = _criar_produto_nunca_tocado('geral_periodo_simples_nunca_tocado')
    produto_simples_real = _criar_produto_com_ciclo('geral_periodo_simples_real', fase=Fase.SIMPLES, etapa_atual='roteiro')
    produto_mensal = _criar_produto_com_ciclo('geral_periodo_simples_out_mensal', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'periodo': Periodo.SIMPLES}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (
        _aparece(produto_nunca_tocado, resultado), _aparece(produto_simples_real, resultado), _aparece(produto_mensal, resultado),
    )
    esperado = (True, True, False)
    registrar_resultado(
        tabela_resultados, 'test_geral_periodo_simples_inclui_nunca_tocado',
        'nunca tocado (fase_atual="") | Simples real | Vídeo Mensal, periodo=Simples',
        esperado, "fix real (achado em teste local): fase_atual__in=[Fase.SIMPLES, ''] — sem isso, nunca tocado ficava em limbo",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_geral_periodo_video_mensal_filtra_exato(tabela_resultados):
    # Setup: ramo "else" do período (qualquer valor que não seja Simples).
    produto_mensal = _criar_produto_com_ciclo('geral_periodo_mensal_dentro', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    produto_trimestral = _criar_produto_com_ciclo('geral_periodo_mensal_fora', fase=Fase.VIDEO_TRIMESTRAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'periodo': Periodo.VIDEO_MENSAL}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_mensal, resultado), _aparece(produto_trimestral, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_geral_periodo_video_mensal_filtra_exato',
        'Vídeo Mensal | Vídeo Trimestral, periodo=Vídeo Mensal',
        esperado, 'ramo else do período — filtro exato por fase_atual, sem soma nenhuma (só Simples soma)',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_tambem_aceita_filtro_de_periodo(tabela_resultados):
    # Setup: o guard do período inclui A Fazer Hoje, não só Geral.
    produto_simples = _criar_produto_com_ciclo('afh_periodo_simples', fase=Fase.SIMPLES, etapa_atual='roteiro')
    produto_mensal = _criar_produto_com_ciclo('afh_periodo_mensal', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.A_FAZER_HOJE, filtros={'periodo': Periodo.SIMPLES}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_simples, resultado), _aparece(produto_mensal, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_tambem_aceita_filtro_de_periodo',
        'Simples (roteiro, já qualifica pra A Fazer Hoje) | Vídeo Mensal, periodo=Simples, tela A Fazer Hoje',
        esperado, 'período é filtro adicional dentro do escopo já definido pela tela — não é exclusivo de Geral',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_outras_telas_ignoram_filtro_de_periodo(tabela_resultados):
    # Setup: fora de Geral/A Fazer Hoje, 'periodo' no dict de filtros não
    # tem efeito nenhum (guard exige tela in (GERAL, A_FAZER_HOJE)).
    produto = _criar_produto_com_ciclo('pausados_periodo_ignorado', fase=Fase.VIDEO_MENSAL, etapa_atual='base', status_manual=StatusManualAgenda.PAUSADO)

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.PAUSADOS, filtros={'periodo': Periodo.SIMPLES}, data_referencia=DATA_REFERENCIA,
    )

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_outras_telas_ignoram_filtro_de_periodo',
        'Pausado, Vídeo Mensal, periodo=Simples (deveria ser ignorado), tela Pausados',
        esperado, "guard só libera período em (Geral, A Fazer Hoje) — Pausados nem olha pra essa chave",
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_geral_etapa_chip_concluido_estreita(tabela_resultados):
    # Setup: chip novo de 13/08 — faltava em Geral, agora cobre a etapa
    # 'concluido' junto com as outras 7.
    produto_concluido = _criar_produto_com_ciclo('geral_chip_concluido', fase=Fase.SIMPLES, etapa_atual='concluido')
    produto_outro = _criar_produto_com_ciclo('geral_chip_nao_concluido', fase=Fase.SIMPLES, etapa_atual='roteiro')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'etapa': ['concluido']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_concluido, resultado), _aparece(produto_outro, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_geral_etapa_chip_concluido_estreita',
        "chip Etapa=['concluido'], A concluido | B roteiro",
        esperado, "8º chip (13/08) — mesmo mecanismo dos outros 7, sem regra especial (cai no case '_' de condicao_etapa)",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_geral_etapa_aceita_todas_as_8_opcoes(tabela_resultados):
    # Setup: confirma que OPCOES_ETAPA tem exatamente as 8 chaves esperadas,
    # na ordem real do fluxo (13/08) — sanity check estrutural, não de
    # comportamento de query.
    chaves = [chave for chave, _ in OPCOES_ETAPA]
    esperado = ['base', 'roteiro', 'completo', 'postar', 'aguardando_aprovacao', 'recusado', 'replicar', 'concluido']
    registrar_resultado(
        tabela_resultados, 'test_geral_etapa_aceita_todas_as_8_opcoes',
        'OPCOES_ETAPA',
        esperado, 'ordem real do fluxo — igual ao BADGES_ETAPA já existente, com recusado deslocado pra depois de aguardando_aprovacao',
        chaves, chaves == esperado,
    )
    assert chaves == esperado

    # TearDown: nada a desmontar.


def test_geral_etapa_multiplas_selecoes_e_uniao(tabela_resultados):
    # Setup: múltiplas seleções no mesmo chip são UNIÃO (OR), não interseção.
    produto_base = _criar_produto_com_ciclo('geral_multi_base', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    produto_roteiro = _criar_produto_com_ciclo('geral_multi_roteiro', fase=Fase.VIDEO_MENSAL, etapa_atual='roteiro')
    produto_completo = _criar_produto_com_ciclo('geral_multi_completo', fase=Fase.VIDEO_MENSAL, etapa_atual='completo')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'etapa': ['base', 'roteiro']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_base, resultado), _aparece(produto_roteiro, resultado), _aparece(produto_completo, resultado))
    esperado = (True, True, False)
    registrar_resultado(
        tabela_resultados, 'test_geral_etapa_multiplas_selecoes_e_uniao',
        "chip Etapa=['base', 'roteiro'], A base | B roteiro | C completo",
        esperado, 'múltiplas seleções somam (OR) — usuário confirmou querer assim',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_geral_respeita_ordenar_escolhido_pelo_usuario(tabela_resultados):
    produto_a = _criar_produto_com_ciclo(
        'geral_ordem_a_titulo', fase=Fase.VIDEO_MENSAL, etapa_atual='base', titulo='AAA Produto',
    )
    produto_z = _criar_produto_com_ciclo(
        'geral_ordem_z_titulo', fase=Fase.VIDEO_MENSAL, etapa_atual='base', titulo='ZZZ Produto',
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.GERAL, ordenar='-titulo', data_referencia=DATA_REFERENCIA)

    ids_na_ordem = list(resultado.filter(pk__in=[produto_a.pk, produto_z.pk]).values_list('pk', flat=True))
    esperado = [produto_z.pk, produto_a.pk]
    registrar_resultado(
        tabela_resultados, 'test_geral_respeita_ordenar_escolhido_pelo_usuario',
        'A="AAA Produto" | Z="ZZZ Produto", ordenar=-titulo',
        'Z antes de A (ordem decrescente)',
        'Geral é a única tela (fora de Aguardando Aprovação) onde a coluna clicada pelo usuário manda',
        ids_na_ordem, ids_na_ordem == esperado,
    )
    assert ids_na_ordem == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C9 — filtros compartilhados (smoke test — a lógica em si não muda de
# tela pra tela, só de onde a query nasce)
# ============================================================

def test_filtro_busca_por_titulo(tabela_resultados):
    produto = _criar_produto_com_ciclo(
        'smoke_busca', fase=Fase.VIDEO_MENSAL, etapa_atual='base', titulo='Fone Bluetooth XPTO',
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.GERAL, busca='XPTO', data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_filtro_busca_por_titulo',
        'título="Fone Bluetooth XPTO", busca="XPTO"',
        esperado, 'smoke test — busca continua ligada na query nova',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_filtro_marca(tabela_resultados):
    produto_a = _criar_produto_com_ciclo('smoke_marca_a', fase=Fase.VIDEO_MENSAL, etapa_atual='base', marca='Samsung')
    produto_b = _criar_produto_com_ciclo('smoke_marca_b', fase=Fase.VIDEO_MENSAL, etapa_atual='base', marca='LG')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'marcas': ['Samsung']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_marca',
        'A marca=Samsung | B marca=LG, filtro marcas=[Samsung]',
        esperado, 'smoke test — filtro de marca continua ligado',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_urgente(tabela_resultados):
    produto_a = _criar_produto_com_ciclo('smoke_urgente_a', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    ParticipacaoAgenda.objects.create(produto=produto_a, urgente=True)
    produto_b = _criar_produto_com_ciclo('smoke_urgente_b', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    ParticipacaoAgenda.objects.create(produto=produto_b, urgente=False)

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'urgente': ['sim']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_urgente',
        'A urgente=True | B urgente=False, filtro urgente=[sim]',
        esperado, 'smoke test — filtro de urgente continua ligado',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_sem_video(tabela_resultados):
    produto_a = _criar_produto_com_ciclo('smoke_sem_video_a', fase=Fase.VIDEO_MENSAL, etapa_atual='base', tem_video_reprovado=True)
    produto_b = _criar_produto_com_ciclo('smoke_sem_video_b', fase=Fase.VIDEO_MENSAL, etapa_atual='base', tem_video_reprovado=False)

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'sem_video': ['sim']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_sem_video',
        'A tem_video_reprovado=True | B=False, filtro sem_video=[sim]',
        esperado, 'smoke test — filtro de vídeo reprovado continua ligado',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_atrasado_sim_fora_de_a_fazer_hoje(tabela_resultados):
    produto_a = _criar_produto_com_ciclo('smoke_atrasado_a', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=True)
    produto_b = _criar_produto_com_ciclo('smoke_atrasado_b', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=False)

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'atrasado': ['sim']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_atrasado_sim_fora_de_a_fazer_hoje',
        'A atrasado=True | B atrasado=False, tela Geral, filtro atrasado=[sim]',
        esperado, 'smoke test — filtro de atrasado continua ligado fora de A Fazer Hoje',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_atrasado_nao_exclui(tabela_resultados):
    # Setup: ramo "elif 'nao' in valores" — ainda não coberto pela suíte
    # anterior (só testava 'sim').
    produto_a = _criar_produto_com_ciclo('smoke_atrasado_nao_a', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=True)
    produto_b = _criar_produto_com_ciclo('smoke_atrasado_nao_b', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=False)

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'atrasado': ['nao']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (False, True)
    registrar_resultado(
        tabela_resultados, 'test_filtro_atrasado_nao_exclui',
        'A atrasado=True | B atrasado=False, filtro atrasado=[nao]',
        esperado, "ramo 'nao': qs.exclude(condicao_atrasado) — só quem NÃO está atrasado sobra",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_risco_sim_pega_quem_esta_em_risco(tabela_resultados):
    # Setup: produção em andamento, não atrasado, prazo dentro do limite de
    # 1 dia útil (12/08 + 1 dia útil = 13/08).
    produto_em_risco = _criar_produto_com_ciclo(
        'smoke_risco_sim', fase=Fase.VIDEO_MENSAL, etapa_atual='roteiro',
        data_devida=date(2026, 8, 13), ciclo_atual_atrasado=False,
    )
    produto_sem_risco = _criar_produto_com_ciclo(
        'smoke_risco_sim_fora', fase=Fase.VIDEO_MENSAL, etapa_atual='roteiro',
        data_devida=date(2026, 8, 30), ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'risco': ['sim']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_em_risco, resultado), _aparece(produto_sem_risco, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_risco_sim_pega_quem_esta_em_risco',
        'A prazo=13/08 (dentro do limite) | B prazo=30/08 (longe), filtro risco=[sim]',
        esperado, 'filtro avançado independente de tela — primeira vez coberto neste módulo',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_risco_nao_exclui_quem_esta_em_risco(tabela_resultados):
    produto_em_risco = _criar_produto_com_ciclo(
        'smoke_risco_nao', fase=Fase.VIDEO_MENSAL, etapa_atual='roteiro',
        data_devida=date(2026, 8, 13), ciclo_atual_atrasado=False,
    )
    produto_sem_risco = _criar_produto_com_ciclo(
        'smoke_risco_nao_fora', fase=Fase.VIDEO_MENSAL, etapa_atual='roteiro',
        data_devida=date(2026, 8, 30), ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'risco': ['nao']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_em_risco, resultado), _aparece(produto_sem_risco, resultado))
    esperado = (False, True)
    registrar_resultado(
        tabela_resultados, 'test_filtro_risco_nao_exclui_quem_esta_em_risco',
        'A prazo=13/08 (em risco) | B prazo=30/08 (fora), filtro risco=[nao]',
        esperado, "ramo 'nao': qs.exclude(condicao_risco) — só quem NÃO está em risco sobra",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_status_postagem(tabela_resultados):
    produto_aprovado = _criar_produto_com_ciclo(
        'smoke_status_postagem_a', fase=Fase.VIDEO_MENSAL, etapa_atual='replicar', status_ciclo=StatusPostagem.APROVADO,
    )
    produto_recusado = _criar_produto_com_ciclo(
        'smoke_status_postagem_b', fase=Fase.VIDEO_MENSAL, etapa_atual='completo', status_ciclo=StatusPostagem.RECUSADO,
    )

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'status_postagem': [StatusPostagem.APROVADO]}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_aprovado, resultado), _aparece(produto_recusado, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_status_postagem',
        'A status=Aprovado | B status=Recusado, filtro status_postagem=[Aprovado]',
        esperado, 'filtro direto por status_ciclo_atual — nunca testado antes neste módulo',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_sincronizado_drive_sim_pega_snapshot_fresco(tabela_resultados):
    produto_fresco = _criar_produto_com_ciclo('smoke_drive_fresco', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    SnapshotArquivosDrive.objects.create(produto=produto_fresco, pasta_encontrada=True)

    produto_sem_snapshot = _criar_produto_com_ciclo('smoke_drive_sem_snapshot', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'sincronizado_drive': ['sim']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_fresco, resultado), _aparece(produto_sem_snapshot, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_sincronizado_drive_sim_pega_snapshot_fresco',
        'A: snapshot recém-criado (dentro da validade) | B: sem snapshot nenhum, filtro=[sim]',
        esperado, 'primeira vez coberto neste módulo — snapshot existe e está dentro de VALIDADE_SNAPSHOT_DRIVE (8h)',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_sincronizado_drive_nao_pega_expirado_e_inexistente(tabela_resultados):
    # Setup: snapshot existe mas passou da validade (atualizado_em é
    # auto_now — precisa de .update() pra "voltar no tempo", já que .save()
    # sempre sobrescreveria pra agora).
    produto_expirado = _criar_produto_com_ciclo('smoke_drive_expirado', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    snapshot = SnapshotArquivosDrive.objects.create(produto=produto_expirado, pasta_encontrada=True)
    momento_expirado = timezone.now() - VALIDADE_SNAPSHOT_DRIVE - timedelta(hours=1)
    SnapshotArquivosDrive.objects.filter(pk=snapshot.pk).update(atualizado_em=momento_expirado)

    produto_sem_snapshot = _criar_produto_com_ciclo('smoke_drive_nunca_verificado', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'sincronizado_drive': ['nao']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_expirado, resultado), _aparece(produto_sem_snapshot, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'test_filtro_sincronizado_drive_nao_pega_expirado_e_inexistente',
        'A: snapshot com +1h além da validade de 8h | B: sem snapshot nenhum, filtro=[nao]',
        esperado, "ramo 'nao': exclude(condicao_sincronizado) — snapshot vencido conta igual a nenhum snapshot",
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_faixa_numero_ocorrencia(tabela_resultados):
    produto_a = _criar_produto_com_ciclo('smoke_faixa_a', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    CicloVideo.objects.filter(produto=produto_a).update(numero_ocorrencia=5)
    produto_b = _criar_produto_com_ciclo('smoke_faixa_b', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    CicloVideo.objects.filter(produto=produto_b).update(numero_ocorrencia=1)

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'numero_ocorrencia_ciclo_atual_min': 3}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_faixa_numero_ocorrencia',
        'A ocorrência #5 | B ocorrência #1, filtro numero_ocorrencia_ciclo_atual_min=3',
        esperado, 'smoke test (DOC de outro app) — filtro de faixa continua ligado no campo certo',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

   # TearDown: nada a desmontar.


def test_filtro_atrasado_ambiguo_nao_filtra(tabela_resultados):
    # Setup: 'sim' e 'nao' marcados ao mesmo tempo — nem o if nem o elif
    # batem, então nada é filtrado (branch nunca antes exercitado).
    produto_a = _criar_produto_com_ciclo('smoke_atrasado_ambiguo_a', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=True)
    produto_b = _criar_produto_com_ciclo('smoke_atrasado_ambiguo_b', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=False)

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'atrasado': ['sim', 'nao']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'test_filtro_atrasado_ambiguo_nao_filtra',
        'A atrasado=True | B atrasado=False, filtro atrasado=[sim, nao]',
        esperado, 'os 2 valores marcados juntos — nem if nem elif batem, comportamento é não filtrar nada',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_risco_ambiguo_nao_filtra(tabela_resultados):
    produto_em_risco = _criar_produto_com_ciclo(
        'smoke_risco_ambiguo_a', fase=Fase.VIDEO_MENSAL, etapa_atual='roteiro',
        data_devida=date(2026, 8, 13), ciclo_atual_atrasado=False,
    )
    produto_sem_risco = _criar_produto_com_ciclo(
        'smoke_risco_ambiguo_b', fase=Fase.VIDEO_MENSAL, etapa_atual='roteiro',
        data_devida=date(2026, 8, 30), ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'risco': ['sim', 'nao']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_em_risco, resultado), _aparece(produto_sem_risco, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'test_filtro_risco_ambiguo_nao_filtra',
        'A em risco | B fora, filtro risco=[sim, nao]',
        esperado, 'os 2 valores marcados juntos — nem if nem elif batem, comportamento é não filtrar nada',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_filtro_sincronizado_drive_ambiguo_nao_filtra(tabela_resultados):
    produto_fresco = _criar_produto_com_ciclo('smoke_drive_ambiguo_a', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    SnapshotArquivosDrive.objects.create(produto=produto_fresco, pasta_encontrada=True)
    produto_sem_snapshot = _criar_produto_com_ciclo('smoke_drive_ambiguo_b', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.GERAL, filtros={'sincronizado_drive': ['sim', 'nao']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_fresco, resultado), _aparece(produto_sem_snapshot, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'test_filtro_sincronizado_drive_ambiguo_nao_filtra',
        'A com snapshot fresco | B sem snapshot, filtro sincronizado_drive=[sim, nao]',
        esperado, 'os 2 valores marcados juntos — nem if nem elif batem, comportamento é não filtrar nada',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.