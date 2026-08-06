# agenda_videos/tests/test_nivel_3__orquestrador_postagem_automatica.py

# Função Objetivo: Testa listar_produtos_elegiveis() e obter_mlb_do_produto()
# — Nível 3 (banco real, sem HTTP). Primeira rodada de testes do orquestrador
# da Postagem Automática. Setup sempre via sincronizar_indicadores_agenda_produto()
# de verdade (nunca cache fabricado à mão) — mesma disciplina já usada no
# resto do projeto: o cache é sempre DERIVADO do CicloVideo real, nunca a
# fonte.
#
# Atenção especial: listar_produtos_elegiveis() usa date.today() direto (sem
# parâmetro de data injetável) — por isso "hoje" é calculado aqui do MESMO
# jeito que o código de produção calcula, nunca hardcoded, pra o teste valer
# em qualquer dia real que rodar.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

from datetime import date, timedelta

import pytest
from django.utils import timezone

from produtos.models import Produto
from mercado_livre.models import AnuncioMercadoLivre, VariacaoAnuncioMercadoLivre
from agenda_videos.models import (
    CicloVideo, Fase, ParticipacaoAgenda, HistoricoStatusManualAgenda, StatusManualAgenda,
)
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import ultimo_dia_util_ou_hoje
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_indicadores_agenda_produto
from agenda_videos.funcoes_auxiliares.postagem_automatica.orquestrador import (
    listar_produtos_elegiveis, obter_mlb_do_produto,
)
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 3 — orquestrador da Postagem Automática: listar_produtos_elegiveis() e obter_mlb_do_produto()'

HOJE = ultimo_dia_util_ou_hoje(date.today())
ATRASADO = HOJE - timedelta(days=3)
FUTURO = HOJE + timedelta(days=3)


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste', marca='Marca Teste')


def _produto_pronto_pra_postar(sku, data_devida, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1):
    produto = _criar_produto(sku)
    agora = timezone.now()
    CicloVideo.objects.create(
        produto=produto, fase=fase, numero_ocorrencia=numero_ocorrencia, data_devida=data_devida,
        base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
    )
    sincronizar_indicadores_agenda_produto(produto)
    return produto


def _ids(queryset):
    return set(p.id for p in queryset)


# ===================================================================
# listar_produtos_elegiveis()
# ===================================================================

def test_produto_pronto_com_vencimento_hoje_aparece(tabela_resultados):
    # Setup:
    produto = _produto_pronto_pra_postar('SKU-001', data_devida=HOJE)

    # Exercise:
    resultado = listar_produtos_elegiveis()

    # Assert:
    passou = produto.id in _ids(resultado)
    registrar_resultado(
        tabela_resultados, teste='produto pronto pra postar, vencimento hoje',
        entrada=f'etapa=postar, data_devida={HOJE}', esperado='produto aparece na lista',
        motivo='Caso básico — vencimento exatamente hoje precisa entrar',
        obtido=f'apareceu={produto.id in _ids(resultado)}',
        passou=passou,
    )
    assert passou


def test_produto_pronto_atrasado_aparece(tabela_resultados):
    # Setup: o bot processa o pool inteiro do dia, atrasado incluso.
    produto = _produto_pronto_pra_postar('SKU-002', data_devida=ATRASADO)

    # Exercise:
    resultado = listar_produtos_elegiveis()

    # Assert:
    passou = produto.id in _ids(resultado)
    registrar_resultado(
        tabela_resultados, teste='produto pronto pra postar, vencimento atrasado',
        entrada=f'etapa=postar, data_devida={ATRASADO} (passado)', esperado='produto aparece (atrasado também é elegível)',
        motivo='Fila cobre hoje-ou-atrasado, nunca só hoje',
        obtido=f'apareceu={produto.id in _ids(resultado)}',
        passou=passou,
    )
    assert passou


def test_produto_pronto_com_vencimento_futuro_nao_aparece(tabela_resultados):
    # Setup:
    produto = _produto_pronto_pra_postar('SKU-003', data_devida=FUTURO)

    # Exercise:
    resultado = listar_produtos_elegiveis()

    # Assert:
    passou = produto.id not in _ids(resultado)
    registrar_resultado(
        tabela_resultados, teste='produto pronto pra postar, vencimento no futuro',
        entrada=f'etapa=postar, data_devida={FUTURO}', esperado='produto NÃO aparece ainda',
        motivo='Fila não deve antecipar postagem antes do vencimento',
        obtido=f'apareceu={produto.id in _ids(resultado)}',
        passou=passou,
    )
    assert passou


def test_produto_em_etapa_diferente_de_postar_nao_aparece(tabela_resultados):
    # Setup: só Base concluído — etapa_atual() = 'roteiro', não 'postar'.
    produto = _criar_produto('SKU-004')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1, data_devida=HOJE,
        base_concluido_em=timezone.now(),
    )
    sincronizar_indicadores_agenda_produto(produto)

    # Exercise:
    resultado = listar_produtos_elegiveis()

    # Assert:
    passou = produto.id not in _ids(resultado)
    registrar_resultado(
        tabela_resultados, teste='produto ainda em Roteiro (não chegou em Postar)',
        entrada='etapa_atual()=roteiro', esperado='produto NÃO aparece',
        motivo='Fila é só pra quem já tem vídeo pronto, esperando o clique de postar',
        obtido=f'apareceu={produto.id in _ids(resultado)}',
        passou=passou,
    )
    assert passou


def test_produto_pausado_nao_aparece_mesmo_pronto(tabela_resultados):
    # Setup:
    produto = _produto_pronto_pra_postar('SKU-005', data_devida=HOJE)
    HistoricoStatusManualAgenda.objects.create(produto=produto, status=StatusManualAgenda.PAUSADO)
    sincronizar_indicadores_agenda_produto(produto)  # recalcula com o histórico novo

    # Exercise:
    resultado = listar_produtos_elegiveis()

    # Assert:
    passou = produto.id not in _ids(resultado)
    registrar_resultado(
        tabela_resultados, teste='produto Pausado, mesmo com vídeo pronto pra postar',
        entrada='status_manual=PAUSADO', esperado='produto NÃO aparece',
        motivo='Bot nunca posta produto que o time pausou manualmente',
        obtido=f'apareceu={produto.id in _ids(resultado)}',
        passou=passou,
    )
    assert passou


def test_produto_descontinuado_nao_aparece(tabela_resultados):
    # Setup:
    produto = _produto_pronto_pra_postar('SKU-006', data_devida=HOJE)
    HistoricoStatusManualAgenda.objects.create(produto=produto, status=StatusManualAgenda.DESCONTINUADO)
    sincronizar_indicadores_agenda_produto(produto)

    # Exercise:
    resultado = listar_produtos_elegiveis()

    # Assert:
    passou = produto.id not in _ids(resultado)
    registrar_resultado(
        tabela_resultados, teste='produto Descontinuado',
        entrada='status_manual=DESCONTINUADO', esperado='produto NÃO aparece',
        motivo='Mesma trava de Pausado, pro outro status manual que também exclui',
        obtido=f'apareceu={produto.id in _ids(resultado)}',
        passou=passou,
    )
    assert passou


def test_produto_que_ja_postou_hoje_nao_aparece_de_novo(tabela_resultados):
    # Setup: ciclo #1 já foi postado hoje (aguardando_aprovacao_em=agora);
    # ciclo #2, mais novo, já está pronto pra postar de novo — simula
    # aprovar+replicar rápido demais no mesmo dia (cenário real já documentado).
    produto = _criar_produto('SKU-007')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1, data_devida=HOJE,
        base_concluido_em=timezone.now(), roteiro_concluido_em=timezone.now(), completo_concluido_em=timezone.now(),
        status='aguardando_aprovacao', aguardando_aprovacao_em=timezone.now(),
    )
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=2, data_devida=HOJE,
        base_concluido_em=timezone.now(), roteiro_concluido_em=timezone.now(), completo_concluido_em=timezone.now(),
    )
    sincronizar_indicadores_agenda_produto(produto)

    # Exercise:
    resultado = listar_produtos_elegiveis()

    # Assert:
    passou = produto.id not in _ids(resultado)
    registrar_resultado(
        tabela_resultados, teste='produto já postou hoje, mesmo com outra ocorrência pronta',
        entrada='ciclo antigo com aguardando_aprovacao_em=hoje + ciclo novo pronto pra postar', esperado='produto NÃO aparece (trava de 1x/dia)',
        motivo='Protege contra rodar a Postagem Automática 2x no mesmo dia',
        obtido=f'apareceu={produto.id in _ids(resultado)}',
        passou=passou,
    )
    assert passou


def test_produto_fase_simples_pronto_pra_postar_aparece(tabela_resultados):
    # Setup: Simples nunca tem data_devida (fica None, por design) — este
    # teste confirma a promessa do próprio comentário do orquestrador ("fila
    # cobre qualquer fase com 'postar' pronto, Simples incluso").
    produto = _produto_pronto_pra_postar('SKU-008', data_devida=None, fase=Fase.SIMPLES)

    # Exercise:
    resultado = listar_produtos_elegiveis()

    # Assert:
    passou = produto.id in _ids(resultado)
    registrar_resultado(
        tabela_resultados, teste='produto Simples pronto pra postar (data_devida=None)',
        entrada='fase=Simples, etapa=postar, data_devida=None', esperado='produto aparece (comentário do código promete isso)',
        motivo='Simples não tem vencimento — filtro de data não pode excluir ela por causa disso',
        obtido=f'apareceu={produto.id in _ids(resultado)}',
        passou=passou,
    )
    assert passou


def test_produto_urgente_aparece_antes_de_produto_comum(tabela_resultados):
    # Setup:
    produto_comum = _produto_pronto_pra_postar('SKU-009', data_devida=HOJE)
    produto_urgente = _produto_pronto_pra_postar('SKU-010', data_devida=HOJE)
    ParticipacaoAgenda.objects.create(produto=produto_urgente, urgente=True)

    # Exercise:
    resultado = list(listar_produtos_elegiveis())
    posicoes = {p.id: indice for indice, p in enumerate(resultado)}

    # Assert:
    passou = posicoes[produto_urgente.id] < posicoes[produto_comum.id]
    registrar_resultado(
        tabela_resultados, teste='ordenação real aplicada — urgente antes de comum',
        entrada='2 produtos elegíveis, 1 urgente', esperado='urgente aparece primeiro',
        motivo='Confirma que a annotation de prioridade é de fato usada no order_by (a regra dos 6 níveis já é testada à parte)',
        obtido=f'posição urgente={posicoes[produto_urgente.id]}, posição comum={posicoes[produto_comum.id]}',
        passou=passou,
    )
    assert passou


def test_produto_sem_indicadores_sincronizados_nao_aparece(tabela_resultados):
    # Setup: CicloVideo pronto, mas NUNCA sincronizado — sem IndicadoresAgendaProduto.
    produto = _criar_produto('SKU-011')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1, data_devida=HOJE,
        base_concluido_em=timezone.now(), roteiro_concluido_em=timezone.now(), completo_concluido_em=timezone.now(),
    )
    # (sem chamar sincronizar_indicadores_agenda_produto de propósito)

    # Exercise:
    resultado = listar_produtos_elegiveis()

    # Assert:
    passou = produto.id not in _ids(resultado)
    registrar_resultado(
        tabela_resultados, teste='produto com ciclo pronto mas cache nunca sincronizado',
        entrada='sem IndicadoresAgendaProduto', esperado='produto NÃO aparece (filtro é INNER JOIN no cache)',
        motivo='Mesmo padrão já visto nas 6 telas — sem cache sincronizado, invisível',
        obtido=f'apareceu={produto.id in _ids(resultado)}',
        passou=passou,
    )
    assert passou


# ===================================================================
# obter_mlb_do_produto()
# ===================================================================

def test_obter_mlb_do_produto_com_variacao_devolve_mlb_certo(tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-012')
    anuncio = AnuncioMercadoLivre.objects.create(mlb='MLB0012')
    VariacaoAnuncioMercadoLivre.objects.create(anuncio=anuncio, variacao_id='1', produto=produto)

    # Exercise:
    mlb = obter_mlb_do_produto(produto)

    # Assert:
    passou = mlb == 'MLB0012'
    registrar_resultado(
        tabela_resultados, teste='obter_mlb_do_produto com 1 variação vinculada',
        entrada='VariacaoAnuncioMercadoLivre(produto, anuncio.mlb=MLB0012)', esperado='mlb=MLB0012',
        motivo='Caminho feliz — precisa devolver o MLB real, não None',
        obtido=f'mlb={mlb}',
        passou=passou,
    )
    assert passou


def test_obter_mlb_do_produto_sem_variacao_devolve_none(tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-013')

    # Exercise:
    mlb = obter_mlb_do_produto(produto)

    # Assert:
    passou = mlb is None
    registrar_resultado(
        tabela_resultados, teste='obter_mlb_do_produto sem nenhuma variação',
        entrada='produto sem VariacaoAnuncioMercadoLivre', esperado='mlb=None',
        motivo='Nunca deve estourar exceção — produto pode não ter anúncio vinculado ainda',
        obtido=f'mlb={mlb}',
        passou=passou,
    )
    assert passou