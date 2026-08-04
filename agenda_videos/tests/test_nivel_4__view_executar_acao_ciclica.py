# agenda_videos/tests/test_nivel_4__view_executar_acao_ciclica.py

# Função Objetivo: Testa view_executar_acao_ciclica() — Nível 4 (view HTTP
# real). A view mais ramificada do fluxo manual: 6 sub-ações (postar/
# aprovado/recusado/nova_tentativa/seguir/replicar), cada uma com guard de
# estado próprio, mais os 2 guards compartilhados (produto sem ciclo, ação
# desconhecida). aprovado/recusado compartilham a MESMA função de guard
# (_acao_marcar_aprovado_ou_recusado) — testo a falha 1 vez só, não duplico.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.models import CicloVideo, ConfiguracaoFase, Fase, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 4 — view_executar_acao_ciclica(): postar/aprovar/recusar/replicar via HTTP'


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste')


def _url(produto_id, acao):
    return reverse('agenda_videos_roadmap_acao_ciclica', args=[produto_id, acao])


@pytest.fixture
def regua_de_fases():
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


def _ciclo_pronto_pra_postar(produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1):
    agora = timezone.now()
    return CicloVideo.objects.create(
        produto=produto, fase=fase, numero_ocorrencia=numero_ocorrencia, data_devida=agora.date(),
        base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
    )


def _ciclo_aguardando_aprovacao(produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1):
    ciclo = _ciclo_pronto_pra_postar(produto, fase, numero_ocorrencia)
    ciclo.marcar_aguardando_aprovacao()
    return ciclo


def _ciclo_aprovado(produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1):
    ciclo = _ciclo_aguardando_aprovacao(produto, fase, numero_ocorrencia)
    ciclo.status = StatusPostagem.APROVADO
    ciclo.aprovado_ou_recusado_em = timezone.now()
    ciclo.save(update_fields=['status', 'aprovado_ou_recusado_em'])
    return ciclo


def _ciclo_recusado(produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1):
    ciclo = _ciclo_aguardando_aprovacao(produto, fase, numero_ocorrencia)
    ciclo.status = StatusPostagem.RECUSADO
    ciclo.aprovado_ou_recusado_em = timezone.now()
    ciclo.save(update_fields=['status', 'aprovado_ou_recusado_em'])
    return ciclo


# ===================================================================
# postar
# ===================================================================

def test_postar_sucesso_marca_aguardando_aprovacao(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-001')
    ciclo = _ciclo_pronto_pra_postar(produto)

    # Exercise:
    resposta = client.get(_url(produto.id, 'postar'))

    # Assert:
    ciclo.refresh_from_db()
    passou = resposta.status_code == 200 and ciclo.status == StatusPostagem.AGUARDANDO_APROVACAO
    registrar_resultado(
        tabela_resultados, teste='postar: sucesso marca aguardando aprovação',
        entrada='etapa_atual()=postar, nunca postou hoje', esperado='200, status=AGUARDANDO_APROVACAO',
        motivo='Caminho normal de postar',
        obtido=f'status={resposta.status_code}, ciclo_status={ciclo.status}',
        passou=passou,
    )
    assert passou


def test_postar_falha_etapa_errada(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-002')
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise:
    resposta = client.get(_url(produto.id, 'postar'))

    # Assert:
    ciclo.refresh_from_db()
    passou = resposta.status_code == 400 and ciclo.status is None
    registrar_resultado(
        tabela_resultados, teste='postar: etapa errada (ainda em Base) → 400',
        entrada='etapa_atual()=base', esperado='400, status continua None',
        motivo='Só pode postar quem está na etapa "postar"',
        obtido=f'status={resposta.status_code}, ciclo_status={ciclo.status}',
        passou=passou,
    )
    assert passou


def test_postar_falha_ja_postou_hoje(client, tabela_resultados, regua_de_fases):
    # Função Objetivo: trava "1 vídeo por dia por produto" — usa o mesmo
    # ciclo com aguardando_aprovacao_em já preenchido hoje mas status=None
    # (situação real de cache desatualizado, já documentada na tela A
    # Fazer Hoje) pra provar que ja_postou_hoje() olha o campo real, não
    # o status.
    # Setup:
    produto = _criar_produto('SKU-003')
    ciclo = _ciclo_pronto_pra_postar(produto)
    ciclo.aguardando_aprovacao_em = timezone.now()
    ciclo.save(update_fields=['aguardando_aprovacao_em'])

    # Exercise:
    resposta = client.get(_url(produto.id, 'postar'))

    # Assert:
    ciclo.refresh_from_db()
    passou = resposta.status_code == 400 and ciclo.status is None
    registrar_resultado(
        tabela_resultados, teste='postar: já postou hoje → 400',
        entrada='etapa_atual()=postar, mas aguardando_aprovacao_em já é de hoje', esperado='400, status continua None',
        motivo='1 vídeo por dia por produto — trava de segurança contra duplo-clique',
        obtido=f'status={resposta.status_code}, ciclo_status={ciclo.status}',
        passou=passou,
    )
    assert passou


# ===================================================================
# aprovado / recusado (mesmo guard compartilhado)
# ===================================================================

def test_aprovado_sucesso(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-004')
    ciclo = _ciclo_aguardando_aprovacao(produto)

    # Exercise:
    resposta = client.get(_url(produto.id, 'aprovado'))

    # Assert:
    ciclo.refresh_from_db()
    passou = (
        resposta.status_code == 200 and ciclo.status == StatusPostagem.APROVADO
        and ciclo.aprovado_ou_recusado_em is not None
    )
    registrar_resultado(
        tabela_resultados, teste='aprovado: sucesso',
        entrada='status=AGUARDANDO_APROVACAO', esperado='200, status=APROVADO, timestamp preenchido',
        motivo='Caminho normal de aprovação',
        obtido=f'status={resposta.status_code}, ciclo_status={ciclo.status}',
        passou=passou,
    )
    assert passou


def test_recusado_sucesso(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-005')
    ciclo = _ciclo_aguardando_aprovacao(produto)

    # Exercise:
    resposta = client.get(_url(produto.id, 'recusado'))

    # Assert:
    ciclo.refresh_from_db()
    passou = resposta.status_code == 200 and ciclo.status == StatusPostagem.RECUSADO
    registrar_resultado(
        tabela_resultados, teste='recusado: sucesso',
        entrada='status=AGUARDANDO_APROVACAO', esperado='200, status=RECUSADO',
        motivo='Caminho normal de recusa — mesma função de guard de aprovado, ação diferente',
        obtido=f'status={resposta.status_code}, ciclo_status={ciclo.status}',
        passou=passou,
    )
    assert passou


def test_aprovado_falha_estado_invalido(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-006')
    ciclo = _ciclo_pronto_pra_postar(produto)  # status=None, nunca postado

    # Exercise:
    resposta = client.get(_url(produto.id, 'aprovado'))

    # Assert:
    ciclo.refresh_from_db()
    passou = resposta.status_code == 400 and ciclo.status is None
    registrar_resultado(
        tabela_resultados, teste='aprovado: sem aguardar aprovação → 400',
        entrada='status=None (nem foi postado ainda)', esperado='400, status continua None',
        motivo='Guard compartilhado com recusado — só testo 1 vez, é a mesma função',
        obtido=f'status={resposta.status_code}, ciclo_status={ciclo.status}',
        passou=passou,
    )
    assert passou


# ===================================================================
# nova_tentativa
# ===================================================================

def test_nova_tentativa_sucesso_reabre_completo(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-007')
    ciclo = _ciclo_recusado(produto)

    # Exercise:
    resposta = client.get(_url(produto.id, 'nova_tentativa'))

    # Assert:
    ciclo.refresh_from_db()
    passou = resposta.status_code == 200 and ciclo.status is None and ciclo.completo_concluido_em is None
    registrar_resultado(
        tabela_resultados, teste='nova_tentativa: sucesso reabre Completo',
        entrada='status=RECUSADO', esperado='200, status=None, completo_concluido_em=None',
        motivo='Recusado precisa refazer o Completo antes de postar de novo',
        obtido=f'status={resposta.status_code}, ciclo_status={ciclo.status}, completo_concluido_em={ciclo.completo_concluido_em}',
        passou=passou,
    )
    assert passou


def test_nova_tentativa_falha_estado_invalido(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-008')
    ciclo = _ciclo_aprovado(produto)  # aprovado, não recusado

    # Exercise:
    resposta = client.get(_url(produto.id, 'nova_tentativa'))

    # Assert:
    ciclo.refresh_from_db()
    passou = resposta.status_code == 400 and ciclo.status == StatusPostagem.APROVADO
    registrar_resultado(
        tabela_resultados, teste='nova_tentativa: status != RECUSADO → 400',
        entrada='status=APROVADO', esperado='400, status continua APROVADO',
        motivo='Nova tentativa só existe pra recusada',
        obtido=f'status={resposta.status_code}, ciclo_status={ciclo.status}',
        passou=passou,
    )
    assert passou


# ===================================================================
# seguir (sem repor)
# ===================================================================

def test_seguir_sucesso_cota_cumprida_cria_proxima_fase(client, tabela_resultados, regua_de_fases):
    # Setup: Mensal #4 é a última ocorrência do período (4) — cota já
    # cumprida mesmo com esta rodada recusada, avança pra Trimestral.
    produto = _criar_produto('SKU-009')
    _ciclo_recusado(produto, numero_ocorrencia=4)

    # Exercise:
    resposta = client.get(_url(produto.id, 'seguir'))

    # Assert:
    proxima = CicloVideo.objects.filter(produto=produto, fase=Fase.VIDEO_TRIMESTRAL, numero_ocorrencia=1).first()
    passou = resposta.status_code == 200 and proxima is not None
    registrar_resultado(
        tabela_resultados, teste='seguir: cota cumprida → cria a próxima fase',
        entrada='Mensal #4 recusado, período=4 (cumprido)', esperado='200, cria Vídeo Trimestral #1',
        motivo='Cota já cumprida — segue pra próxima fase sem repor a rodada recusada',
        obtido=f'status={resposta.status_code}, trimestral_1_existe={proxima is not None}',
        passou=passou,
    )
    assert passou


def test_seguir_falha_cota_ainda_nao_cumprida(client, tabela_resultados, regua_de_fases):
    # Setup: Mensal #2 recusado — período é 4, ainda restam rodadas.
    produto = _criar_produto('SKU-010')
    _ciclo_recusado(produto, numero_ocorrencia=2)

    # Exercise:
    resposta = client.get(_url(produto.id, 'seguir'))

    # Assert:
    proxima_existe = CicloVideo.objects.filter(produto=produto).exclude(numero_ocorrencia=2).exists()
    passou = resposta.status_code == 400 and not proxima_existe
    registrar_resultado(
        tabela_resultados, teste='seguir: cota ainda não cumprida → 400',
        entrada='Mensal #2 recusado, período=4 (ainda restam 2 rodadas)', esperado='400, nenhum ciclo novo criado',
        motivo='Não pode pular pra próxima fase enquanto a cota atual não foi cumprida',
        obtido=f'status={resposta.status_code}, ciclo_novo_criado={proxima_existe}',
        passou=passou,
    )
    assert passou


def test_seguir_falha_sem_proxima_fase_configurada(client, tabela_resultados):
    # Função Objetivo: régua isolada de propósito (SEM a fixture normal) —
    # Simples com período=1 e proxima_fase=None, simulando régua incompleta.
    # Setup:
    ConfiguracaoFase.objects.create(fase=Fase.SIMPLES, periodo_continuo=False, periodo=1, proxima_fase=None)
    produto = _criar_produto('SKU-011')
    _ciclo_recusado(produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise:
    resposta = client.get(_url(produto.id, 'seguir'))

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='seguir: cota cumprida mas sem próxima fase configurada → 400',
        entrada='Simples#1 recusado, período=1 (cumprido), proxima_fase=None', esperado='status_code == 400',
        motivo='Régua incompleta — não trava com erro cru, devolve 400 tratado',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


# ===================================================================
# replicar
# ===================================================================

def test_replicar_sucesso_dispara_proximo_ciclo(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-012')
    ciclo = _ciclo_aprovado(produto, numero_ocorrencia=1)

    # Exercise:
    resposta = client.get(_url(produto.id, 'replicar'))

    # Assert:
    ciclo.refresh_from_db()
    proximo = CicloVideo.objects.filter(produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=2).first()
    passou = (
        resposta.status_code == 200 and ciclo.status == StatusPostagem.REPLICADO
        and ciclo.replicado_em is not None and proximo is not None
    )
    registrar_resultado(
        tabela_resultados, teste='replicar: sucesso dispara o próximo ciclo',
        entrada='status=APROVADO, fase=Vídeo Mensal #1', esperado='200, status=REPLICADO, cria Mensal #2',
        motivo='Qualquer fase que não seja Simples dispara criar_proximo() automaticamente',
        obtido=f'status={resposta.status_code}, ciclo_status={ciclo.status}, proximo_existe={proximo is not None}',
        passou=passou,
    )
    assert passou


def test_replicar_falha_estado_invalido(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-013')
    ciclo = _ciclo_aguardando_aprovacao(produto)  # aguardando, não aprovado ainda

    # Exercise:
    resposta = client.get(_url(produto.id, 'replicar'))

    # Assert:
    ciclo.refresh_from_db()
    passou = resposta.status_code == 400 and ciclo.status == StatusPostagem.AGUARDANDO_APROVACAO
    registrar_resultado(
        tabela_resultados, teste='replicar: status != APROVADO → 400',
        entrada='status=AGUARDANDO_APROVACAO', esperado='400, status continua AGUARDANDO_APROVACAO',
        motivo='Só pode replicar quem já foi aprovado',
        obtido=f'status={resposta.status_code}, ciclo_status={ciclo.status}',
        passou=passou,
    )
    assert passou


# ===================================================================
# Guards compartilhados (produto sem ciclo, ação desconhecida, 404)
# ===================================================================

def test_produto_sem_ciclo_nenhum_e_400(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-014')

    # Exercise:
    resposta = client.get(_url(produto.id, 'postar'))

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='produto sem nenhum ciclo → 400',
        entrada='produto nunca tocado, acao=postar', esperado='status_code == 400',
        motivo='Guard mais externo — roda antes de olhar qual ação foi pedida',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_acao_desconhecida_e_400(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-015')
    _ciclo_pronto_pra_postar(produto)

    # Exercise:
    resposta = client.get(_url(produto.id, 'essa_acao_nao_existe'))

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='ação desconhecida → 400',
        entrada='acao=essa_acao_nao_existe (fora do dict ACOES_CICLICAS)', esperado='status_code == 400',
        motivo='ACOES_CICLICAS.get(acao) devolve None — tratado, não KeyError',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_produto_inexistente_devolve_404(client, tabela_resultados, regua_de_fases):
    # Exercise:
    resposta = client.get(_url(999999, 'postar'))

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='produto_id inexistente → 404',
        entrada='produto_id=999999 (não existe)', esperado='status_code == 404',
        motivo='get_object_or_404 precisa disparar 404 de verdade',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou