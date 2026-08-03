"""
Nível 3 — listar_produtos_agenda_filtrados()

Substitui test_nivel_3__listar_a_fazer_hoje.py — listar_a_fazer_hoje() foi
aposentada (Fase 2 do mapa de execução das 5 telas), unificada nesta única
função, com 'tela' decidindo tanto quem entra quanto como ordena. Divide em
6 blocos: C1 escopo de cada tela (o cerne do redesenho), C2 os 6 motivos de
A Fazer Hoje + as 2 exclusões estruturais (Simples nunca entra, Pausado/
Descontinuado sempre sai), C3 chip clicado estreitando a tela, C4 a
assimetria de status_manual entre A Fazer Hoje e as outras 4 telas, C5
ordenação (fixa x escolhida), C6 filtros compartilhados (smoke test — a
lógica deles não mudou, só de onde a query nasce; não reexaure cada
combinação sim/não/ambíguo já provada na suíte anterior). DOC (cache de
IndicadoresAgendaProduto/ParticipacaoAgenda) já validado nas Camadas A/B —
aqui só se preenche o cache manualmente por cenário.
"""
from datetime import date, datetime

import pytest
from django.utils import timezone

from agenda_videos.funcoes_auxiliares.filtros_agenda_videos import Tela, listar_produtos_agenda_filtrados
from agenda_videos.models.ciclo_video import CicloVideo, StatusPostagem
from agenda_videos.models.configuracao_fase import Fase
from agenda_videos.models.indicadores_agenda_produto import IndicadoresAgendaProduto
from agenda_videos.models.participacao_agenda import ParticipacaoAgenda, StatusManualAgenda
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 3 — listar_produtos_agenda_filtrados()'

# data_referencia fixa: segunda 03/08/2026. hoje=03/08, limite_risco=04/08.
DATA_REFERENCIA = date(2026, 8, 3)


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
    # preenchido — DOC (sincronização) já validado nas Camadas A/B, aqui só
    # se preenche o cache manualmente por cenário, igual ao padrão da
    # suíte anterior.
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
    # "Base" na tela Simples soma esta situação (sem NENHUM CicloVideo,
    # cache sintético 'nao_agendado') com a de quem já tem ciclo mas ainda
    # está em 'base' — decisão de arquitetura #2 do mapa de execução.
    produto = _criar_produto(rotulo, titulo=titulo, marca=marca)
    IndicadoresAgendaProduto.objects.create(
        produto=produto, fase_atual='', etapa_atual='nao_agendado',
        ciclo_atual_atrasado=False, tem_video_reprovado=False, status_manual=StatusManualAgenda.ATIVO,
    )
    return produto


def _aparece(produto, resultado):
    return resultado.filter(pk=produto.pk).exists()


# ============================================================
# C1 — escopo de cada tela (o cerne do redesenho: quem entra onde)
# ============================================================

def test_nao_agendado_pega_simples_concluido(tabela_resultados):
    # Setup: Simples já com tudo feito (replicado) — só falta clicar Agendar.
    produto = _criar_produto_com_ciclo('na_simples_concluido', fase=Fase.SIMPLES, etapa_atual='concluido')

    # Exercise: chama o SUT de verdade.
    resultado = listar_produtos_agenda_filtrados(tela=Tela.NAO_AGENDADO, data_referencia=DATA_REFERENCIA)

    # Assert: exatamente o critério de Não Agendado.
    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_nao_agendado_pega_simples_concluido',
        'Simples, etapa_atual=concluido',
        esperado, 'fila estreita de Não Agendado: Simples pronto, só falta Agendar',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_nao_agendado_nao_pega_simples_em_andamento(tabela_resultados):
    # Setup: Simples ainda em produção (não concluído).
    produto = _criar_produto_com_ciclo('na_simples_andamento', fase=Fase.SIMPLES, etapa_atual='roteiro')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.NAO_AGENDADO, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_nao_agendado_nao_pega_simples_em_andamento',
        'Simples, etapa_atual=roteiro',
        esperado, 'Simples em produção pertence à tela Simples, não Não Agendado — bug antigo que motivou o redesenho',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_nao_agendado_nao_pega_mensal(tabela_resultados):
    # Setup: já agendado, em Vídeo Mensal.
    produto = _criar_produto_com_ciclo('na_mensal', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.NAO_AGENDADO, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_nao_agendado_nao_pega_mensal',
        'Vídeo Mensal, etapa_atual=base',
        esperado, 'já agendado — não é mais candidato a Não Agendado',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_simples_pega_qualquer_etapa_exceto_concluido(tabela_resultados):
    # Setup: 2 produtos Simples em etapas bem distantes — não precisa
    # testar as 7 etapas, o mecanismo é o mesmo booleano (fase=Simples E
    # etapa != concluido) pra qualquer uma delas.
    produto_inicio = _criar_produto_com_ciclo('simples_base', fase=Fase.SIMPLES, etapa_atual='base')
    produto_fim = _criar_produto_com_ciclo('simples_aguardando', fase=Fase.SIMPLES, etapa_atual='aguardando_aprovacao')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.SIMPLES, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_inicio, resultado), _aparece(produto_fim, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'test_simples_pega_qualquer_etapa_exceto_concluido',
        'Simples etapa=base | Simples etapa=aguardando_aprovacao',
        esperado, 'qualquer etapa não-concluído entra — mesmo mecanismo booleano pras 2 pontas',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_simples_nao_pega_concluido(tabela_resultados):
    # Setup: Simples concluído — pertence a Não Agendado, não aqui.
    produto = _criar_produto_com_ciclo('simples_concluido', fase=Fase.SIMPLES, etapa_atual='concluido')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.SIMPLES, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_simples_nao_pega_concluido',
        'Simples, etapa_atual=concluido',
        esperado, 'concluído pertence a Não Agendado, nunca aos 2 ao mesmo tempo',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_simples_pega_nunca_tocado(tabela_resultados):
    # Setup: produto sem NENHUM CicloVideo — decisão de arquitetura #2 do
    # mapa: "Base" soma esta situação com a de quem já tem ciclo em 'base'.
    produto = _criar_produto_nunca_tocado('simples_nunca_tocado')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.SIMPLES, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_simples_pega_nunca_tocado',
        'sem nenhum CicloVideo, cache etapa_atual=nao_agendado (sintético)',
        esperado, 'decisão de arquitetura #2 do mapa — "nunca tocado" e "base em andamento" são a mesma ação pendente',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_simples_nao_pega_outras_fases(tabela_resultados):
    # Setup: 1 produto em cada uma das outras 2 fases.
    produto_mensal = _criar_produto_com_ciclo('simples_out_mensal', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    produto_trimestral = _criar_produto_com_ciclo('simples_out_trimestral', fase=Fase.VIDEO_TRIMESTRAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.SIMPLES, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_mensal, resultado), _aparece(produto_trimestral, resultado))
    esperado = (False, False)
    registrar_resultado(
        tabela_resultados, 'test_simples_nao_pega_outras_fases',
        'Vídeo Mensal etapa=base | Vídeo Trimestral etapa=base',
        esperado, 'tela Simples é só fase Simples',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_mensal_filtra_so_pela_fase(tabela_resultados):
    # Setup: 1 produto em cada fase, todos etapa=base.
    produto_mensal = _criar_produto_com_ciclo('mensal_ok', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    produto_simples = _criar_produto_com_ciclo('mensal_out_simples', fase=Fase.SIMPLES, etapa_atual='base')
    produto_trimestral = _criar_produto_com_ciclo('mensal_out_trimestral', fase=Fase.VIDEO_TRIMESTRAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.VIDEO_MENSAL, data_referencia=DATA_REFERENCIA)

    obtido = (
        _aparece(produto_mensal, resultado), _aparece(produto_simples, resultado), _aparece(produto_trimestral, resultado),
    )
    esperado = (True, False, False)
    registrar_resultado(
        tabela_resultados, 'test_mensal_filtra_so_pela_fase',
        'Mensal | Simples | Trimestral, todos etapa=base',
        esperado, 'tela de fase é filtro puro por fase_atual, qualquer etapa entra',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_trimestral_filtra_so_pela_fase(tabela_resultados):
    # Setup: espelho do teste anterior, agora Trimestral.
    produto_trimestral = _criar_produto_com_ciclo('trimestral_ok', fase=Fase.VIDEO_TRIMESTRAL, etapa_atual='postar')
    produto_mensal = _criar_produto_com_ciclo('trimestral_out_mensal', fase=Fase.VIDEO_MENSAL, etapa_atual='postar')

    resultado = listar_produtos_agenda_filtrados(tela=Tela.VIDEO_TRIMESTRAL, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_trimestral, resultado), _aparece(produto_mensal, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_trimestral_filtra_so_pela_fase',
        'Trimestral | Mensal, ambos etapa=postar',
        esperado, 'mesmo mecanismo do Mensal, espelhado pro Trimestral',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_produto_sem_indicadores_nenhum_nao_aparece_em_nenhuma_tela(tabela_resultados):
    # Setup: produto "cru" — nem CicloVideo, nem IndicadoresAgendaProduto.
    # Sanity check estrutural: toda condicao_tela() filtra via
    # indicadores_agenda__X, que faz INNER JOIN — sem a linha de cache,
    # nunca aparece em tela nenhuma.
    produto = _criar_produto('cru_sem_cache')

    aparece_em = {
        tela: _aparece(produto, listar_produtos_agenda_filtrados(tela=tela, data_referencia=DATA_REFERENCIA))
        for tela in Tela.values
    }

    esperado = {tela: False for tela in Tela.values}
    registrar_resultado(
        tabela_resultados, 'test_produto_sem_indicadores_nenhum_nao_aparece_em_nenhuma_tela',
        'produto sem CicloVideo e sem IndicadoresAgendaProduto, nas 5 telas',
        esperado, 'sem sincronização nenhuma ainda, o produto não é candidato a tela alguma',
        aparece_em, aparece_em == esperado,
    )
    assert aparece_em == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C2 — A Fazer Hoje: os 6 motivos de urgência + as 2 exclusões estruturais
# ============================================================

def test_a_fazer_hoje_pega_atrasado(tabela_resultados):
    # Setup: Mensal, atrasado=True, etapa em produção (nem risco nem prazo
    # importam aqui).
    produto = _criar_produto_com_ciclo(
        'afh_atrasado', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=True,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_pega_atrasado',
        'Mensal, ciclo_atual_atrasado=True, etapa=base',
        esperado, 'atrasado é urgência real, independente da etapa',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_pega_risco(tabela_resultados):
    # Setup: Mensal, etapa em produção, não atrasado, prazo dentro do
    # limite (04/08).
    produto = _criar_produto_com_ciclo(
        'afh_risco', fase=Fase.VIDEO_MENSAL, etapa_atual='roteiro',
        data_devida=date(2026, 8, 4), ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_pega_risco',
        'Mensal, etapa=roteiro, não atrasado, prazo=04/08 (limite de 1 dia útil)',
        esperado, 'produção não terminou + prazo a ≤1 dia útil de distância = risco',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_nao_pega_producao_sem_risco_nem_atraso(tabela_resultados):
    # Setup: Mensal, etapa em produção, prazo bem longe, não atrasado —
    # nenhum dos 6 motivos bate.
    produto = _criar_produto_com_ciclo(
        'afh_sem_urgencia', fase=Fase.VIDEO_MENSAL, etapa_atual='base',
        data_devida=date(2026, 8, 20), ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_nao_pega_producao_sem_risco_nem_atraso',
        'Mensal, etapa=base, prazo=20/08 (longe), não atrasado',
        esperado, 'produção em dia, sem risco — o bug antigo mostrava isso aqui; agora não aparece mais',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_pega_postar_hoje(tabela_resultados):
    # Setup: Mensal, etapa=postar, prazo=hoje, ainda não postou.
    produto = _criar_produto_com_ciclo(
        'afh_postar_hoje', fase=Fase.VIDEO_MENSAL, etapa_atual='postar',
        data_devida=DATA_REFERENCIA, ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_pega_postar_hoje',
        'Mensal, etapa=postar, data_devida=hoje, não postou',
        esperado, 'prazo de postar chegou e ainda não postou',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_nao_pega_postar_ja_postado_hoje(tabela_resultados):
    # Setup: mesmo cenário do teste anterior, mas já postou hoje — o
    # achado do cache defasado (postou_hoje), corrigido nesta fase.
    momento_hoje = timezone.make_aware(datetime(2026, 8, 3, 15, 0))
    produto = _criar_produto_com_ciclo(
        'afh_postar_ja_postou', fase=Fase.VIDEO_MENSAL, etapa_atual='postar',
        data_devida=DATA_REFERENCIA, aguardando_aprovacao_em=momento_hoje, ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_nao_pega_postar_ja_postado_hoje',
        'Mensal, etapa=postar (cache), prazo=hoje, mas já postou hoje às 15h',
        esperado, 'postou_hoje protege contra o cache de etapa_atual ficar desatualizado',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_nao_pega_postar_prazo_futuro(tabela_resultados):
    # Setup: Mensal, etapa=postar, prazo no futuro, não atrasado.
    produto = _criar_produto_com_ciclo(
        'afh_postar_futuro', fase=Fase.VIDEO_MENSAL, etapa_atual='postar',
        data_devida=date(2026, 8, 10), ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_nao_pega_postar_prazo_futuro',
        'Mensal, etapa=postar, prazo=10/08 (futuro), não atrasado',
        esperado, 'só aparece pra postar quando o prazo é hoje (ou já está atrasado)',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_pega_aguardando_aprovacao_e_replicar_sem_checar_prazo(tabela_resultados):
    # Setup: 2 produtos, ambos com prazo bem longe — essas 2 etapas contam
    # sempre, independente da distância do prazo do ciclo.
    produto_aguardando = _criar_produto_com_ciclo(
        'afh_aguardando', fase=Fase.VIDEO_MENSAL, etapa_atual='aguardando_aprovacao',
        data_devida=date(2026, 8, 20), ciclo_atual_atrasado=False,
    )
    produto_replicar = _criar_produto_com_ciclo(
        'afh_replicar', fase=Fase.VIDEO_TRIMESTRAL, etapa_atual='replicar',
        data_devida=date(2026, 8, 20), ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_aguardando, resultado), _aparece(produto_replicar, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_pega_aguardando_aprovacao_e_replicar_sem_checar_prazo',
        'aguardando_aprovacao e replicar, ambos prazo=20/08 (longe)',
        esperado, '"se não foi replicado ainda é porque tem ação pendente a ser feita" — contam sempre',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_pega_recusado_sem_checar_prazo(tabela_resultados):
    # Setup: status da postagem mais recente = Recusado, prazo bem longe.
    produto = _criar_produto_com_ciclo(
        'afh_recusado', fase=Fase.VIDEO_MENSAL, etapa_atual='completo',
        data_devida=date(2026, 8, 20), status_ciclo=StatusPostagem.RECUSADO, ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_pega_recusado_sem_checar_prazo',
        'Mensal, etapa=completo, status_ciclo=Recusado, prazo=20/08 (longe)',
        esperado, 'recusado também é ação pendente em aberto, conta sempre',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_nunca_pega_simples(tabela_resultados):
    # Setup: Simples com atrasado=True — bateria em qualquer outra tela de
    # urgência, mas Simples não tem prazo, então nunca participa de A
    # Fazer Hoje. A mudança de escopo mais importante desta fase.
    produto = _criar_produto_com_ciclo(
        'afh_simples_atrasado', fase=Fase.SIMPLES, etapa_atual='base', ciclo_atual_atrasado=True,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_nunca_pega_simples',
        'Simples, ciclo_atual_atrasado=True',
        esperado, 'A Fazer Hoje é só Mensal/Trimestral — Simples não tem prazo, nunca entra aqui',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_exclui_pausado_e_descontinuado_incondicionalmente(tabela_resultados):
    # Setup: 2 produtos claramente urgentes (atrasados), só o status
    # manual muda.
    produto_pausado = _criar_produto_com_ciclo(
        'afh_pausado', fase=Fase.VIDEO_MENSAL, etapa_atual='base',
        ciclo_atual_atrasado=True, status_manual=StatusManualAgenda.PAUSADO,
    )
    produto_descontinuado = _criar_produto_com_ciclo(
        'afh_descontinuado', fase=Fase.VIDEO_MENSAL, etapa_atual='base',
        ciclo_atual_atrasado=True, status_manual=StatusManualAgenda.DESCONTINUADO,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_pausado, resultado), _aparece(produto_descontinuado, resultado))
    esperado = (False, False)
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_exclui_pausado_e_descontinuado_incondicionalmente',
        'Pausado atrasado=True | Descontinuado atrasado=True',
        esperado, 'A Fazer Hoje é lista de ação — pausado/descontinuado nunca é "pra fazer", mesmo urgente',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_a_fazer_hoje_nao_pega_concluido(tabela_resultados):
    # Setup: Mensal já concluído (Vídeo Mensal também pode passar por
    # 'concluido' momentaneamente antes de criar o próximo ciclo) — nenhum
    # motivo de urgência bate.
    produto = _criar_produto_com_ciclo(
        'afh_concluido', fase=Fase.VIDEO_MENSAL, etapa_atual='concluido',
        data_devida=date(2026, 8, 20), ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE, data_referencia=DATA_REFERENCIA)

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_nao_pega_concluido',
        'Mensal, etapa_atual=concluido, prazo longe, não atrasado',
        esperado, 'nada pendente numa ocorrência concluída',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C3 — chip clicado estreita a tela (filtro de etapa/motivo)
# ============================================================

def test_motivo_a_fazer_hoje_estreita_para_1_motivo(tabela_resultados):
    # Setup: 2 produtos, ambos dentro de A Fazer Hoje por motivos diferentes.
    produto_atrasado = _criar_produto_com_ciclo(
        'chip_afh_atrasado', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=True,
    )
    produto_risco = _criar_produto_com_ciclo(
        'chip_afh_risco', fase=Fase.VIDEO_MENSAL, etapa_atual='roteiro',
        data_devida=date(2026, 8, 4), ciclo_atual_atrasado=False,
    )

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.A_FAZER_HOJE, filtros={'motivo_a_fazer_hoje': ['atrasado']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_atrasado, resultado), _aparece(produto_risco, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_motivo_a_fazer_hoje_estreita_para_1_motivo',
        'A: atrasado=True | B: em risco. Filtro motivo_a_fazer_hoje=[atrasado]',
        esperado, 'clicar no chip "Atrasado" mostra só quem está atrasado, mesmo os 2 estando na tela',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


def test_pendente_agora_estreita_tela_de_fase(tabela_resultados):
    # Setup: 2 produtos na mesma fase, etapas diferentes.
    produto_completo = _criar_produto_com_ciclo('chip_mensal_completo', fase=Fase.VIDEO_MENSAL, etapa_atual='completo')
    produto_base = _criar_produto_com_ciclo('chip_mensal_base', fase=Fase.VIDEO_MENSAL, etapa_atual='base')

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.VIDEO_MENSAL, filtros={'pendente_agora': ['completo']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_completo, resultado), _aparece(produto_base, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_pendente_agora_estreita_tela_de_fase',
        'Mensal: A etapa=completo | B etapa=base. Filtro pendente_agora=[completo]',
        esperado, 'clicar no chip "Completo" mostra só quem está em completo, dentro da tela Mensal',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C4 — status_manual: assimetria A Fazer Hoje x as outras 4 telas
# ============================================================

def test_a_fazer_hoje_pedir_pausado_nunca_traz_nada(tabela_resultados):
    # Setup: produto pausado, urgente (atrasado) — mesmo pedindo
    # status_manual=[Pausado] explicitamente, a exclusão incondicional já
    # rodou antes do filtro do dict, então nunca aparece aqui.
    produto = _criar_produto_com_ciclo(
        'afh_filtro_pausado', fase=Fase.VIDEO_MENSAL, etapa_atual='base',
        ciclo_atual_atrasado=True, status_manual=StatusManualAgenda.PAUSADO,
    )

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.A_FAZER_HOJE, filtros={'status_manual': [StatusManualAgenda.PAUSADO]}, data_referencia=DATA_REFERENCIA,
    )

    aparece = _aparece(produto, resultado)
    esperado = False
    registrar_resultado(
        tabela_resultados, 'test_a_fazer_hoje_pedir_pausado_nunca_traz_nada',
        'Pausado, atrasado=True, filtro status_manual=[Pausado]',
        esperado, 'exclusão incondicional de A Fazer Hoje roda ANTES do filtro do dict — pedir pausado sempre dá vazio aqui',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_mensal_pedir_pausado_traz_o_produto_de_volta(tabela_resultados):
    # Setup: mesmo produto pausado, agora na tela Mensal — sem exclusão
    # incondicional aqui, o filtro status_manual funciona de verdade.
    produto = _criar_produto_com_ciclo(
        'mensal_filtro_pausado', fase=Fase.VIDEO_MENSAL, etapa_atual='base',
        status_manual=StatusManualAgenda.PAUSADO,
    )

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.VIDEO_MENSAL, filtros={'status_manual': [StatusManualAgenda.PAUSADO]}, data_referencia=DATA_REFERENCIA,
    )

    aparece = _aparece(produto, resultado)
    esperado = True
    registrar_resultado(
        tabela_resultados, 'test_mensal_pedir_pausado_traz_o_produto_de_volta',
        'Pausado, tela Mensal, filtro status_manual=[Pausado]',
        esperado, 'decisão de 03/08: fora de A Fazer Hoje, pausado só some se o usuário filtrar de propósito',
        aparece, aparece == esperado,
    )
    assert aparece == esperado

    # TearDown: nada a desmontar.


def test_mensal_sem_filtro_mostra_pausado_junto_com_o_resto(tabela_resultados):
    # Setup: 1 ativo, 1 pausado, sem filtro nenhum de status_manual.
    produto_ativo = _criar_produto_com_ciclo('mensal_sem_filtro_ativo', fase=Fase.VIDEO_MENSAL, etapa_atual='base')
    produto_pausado = _criar_produto_com_ciclo(
        'mensal_sem_filtro_pausado', fase=Fase.VIDEO_MENSAL, etapa_atual='base',
        status_manual=StatusManualAgenda.PAUSADO,
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.VIDEO_MENSAL, data_referencia=DATA_REFERENCIA)

    obtido = (_aparece(produto_ativo, resultado), _aparece(produto_pausado, resultado))
    esperado = (True, True)
    registrar_resultado(
        tabela_resultados, 'test_mensal_sem_filtro_mostra_pausado_junto_com_o_resto',
        'Ativo | Pausado, sem filtro de status_manual',
        esperado, 'as 4 telas de listagem mostram tudo por padrão, pausado incluso — só A Fazer Hoje esconde sempre',
        obtido, obtido == esperado,
    )
    assert obtido == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C5 — ordenação: fixa em A Fazer Hoje, escolhida nas outras 4 telas
# ============================================================

def test_a_fazer_hoje_ordena_por_prioridade_fase_prazo_ignorando_ordenar(tabela_resultados):
    # Setup: 2 produtos só em Mensal/Trimestral (Simples não participa
    # mais de A Fazer Hoje) — prioridade decide antes de tudo.
    produto_prioridade_alta = _criar_produto_com_ciclo(
        'afh_ordem_alta', fase=Fase.VIDEO_TRIMESTRAL, etapa_atual='base',
        tem_video_reprovado=True, ciclo_atual_atrasado=True,
    )
    ParticipacaoAgenda.objects.create(produto=produto_prioridade_alta, urgente=True)

    produto_prioridade_baixa = _criar_produto_com_ciclo(
        'afh_ordem_baixa', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=True,
    )

    # Exercise: pede ordenar='-titulo' de propósito — deve ser ignorado.
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


def test_mensal_respeita_ordenar_escolhido_pelo_usuario(tabela_resultados):
    # Setup: 2 produtos, mesma prioridade/fase, só o título muda.
    produto_a = _criar_produto_com_ciclo(
        'mensal_ordem_a_titulo', fase=Fase.VIDEO_MENSAL, etapa_atual='base', titulo='AAA Produto',
    )
    produto_z = _criar_produto_com_ciclo(
        'mensal_ordem_z_titulo', fase=Fase.VIDEO_MENSAL, etapa_atual='base', titulo='ZZZ Produto',
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.VIDEO_MENSAL, ordenar='-titulo', data_referencia=DATA_REFERENCIA)

    ids_na_ordem = list(resultado.filter(pk__in=[produto_a.pk, produto_z.pk]).values_list('pk', flat=True))
    esperado = [produto_z.pk, produto_a.pk]
    registrar_resultado(
        tabela_resultados, 'test_mensal_respeita_ordenar_escolhido_pelo_usuario',
        'A="AAA Produto" | Z="ZZZ Produto", ordenar=-titulo',
        'Z antes de A (ordem decrescente)',
        'nas 4 telas de listagem, a coluna escolhida pelo usuário manda, igual antes do redesenho',
        ids_na_ordem, ids_na_ordem == esperado,
    )
    assert ids_na_ordem == esperado

    # TearDown: nada a desmontar.


# ============================================================
# C6 — filtros compartilhados (lógica já provada antes da Fase 2; aqui só
# confirma que a query nova, nascida em construir_queryset_tela, ainda
# liga certo — não reexaure cada combinação sim/não/ambíguo de novo)
# ============================================================

def test_filtro_busca_por_titulo(tabela_resultados):
    produto = _criar_produto_com_ciclo(
        'smoke_busca', fase=Fase.VIDEO_MENSAL, etapa_atual='base', titulo='Fone Bluetooth XPTO',
    )

    resultado = listar_produtos_agenda_filtrados(tela=Tela.VIDEO_MENSAL, busca='XPTO', data_referencia=DATA_REFERENCIA)

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
        tela=Tela.VIDEO_MENSAL, filtros={'marcas': ['Samsung']}, data_referencia=DATA_REFERENCIA,
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
        tela=Tela.VIDEO_MENSAL, filtros={'urgente': ['sim']}, data_referencia=DATA_REFERENCIA,
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
        tela=Tela.VIDEO_MENSAL, filtros={'sem_video': ['sim']}, data_referencia=DATA_REFERENCIA,
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
    # Setup: na tela Mensal, atrasado ainda é um filtro OPCIONAL (não é
    # critério de escopo, como é em A Fazer Hoje).
    produto_a = _criar_produto_com_ciclo('smoke_atrasado_a', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=True)
    produto_b = _criar_produto_com_ciclo('smoke_atrasado_b', fase=Fase.VIDEO_MENSAL, etapa_atual='base', ciclo_atual_atrasado=False)

    resultado = listar_produtos_agenda_filtrados(
        tela=Tela.VIDEO_MENSAL, filtros={'atrasado': ['sim']}, data_referencia=DATA_REFERENCIA,
    )

    obtido = (_aparece(produto_a, resultado), _aparece(produto_b, resultado))
    esperado = (True, False)
    registrar_resultado(
        tabela_resultados, 'test_filtro_atrasado_sim_fora_de_a_fazer_hoje',
        'A atrasado=True | B atrasado=False, tela Mensal, filtro atrasado=[sim]',
        esperado, 'smoke test — filtro de atrasado continua ligado fora de A Fazer Hoje',
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
        tela=Tela.VIDEO_MENSAL, filtros={'numero_ocorrencia_ciclo_atual_min': 3}, data_referencia=DATA_REFERENCIA,
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