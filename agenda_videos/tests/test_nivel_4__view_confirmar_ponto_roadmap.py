# agenda_videos/tests/test_nivel_4__view_confirmar_ponto_roadmap.py

# Função Objetivo: Testa view_confirmar_ponto_roadmap() — Nível 4 (view HTTP
# real). Essa view é o "modal de confirmação antes de agir" — sua função
# real é revalidar que a etapa pedida (chave) ainda é a etapa REAL do ciclo,
# evitando agir sobre estado desatualizado (ex: 2 abas abertas). Cobre as
# 2 formas de erro (400) e os caminhos de sucesso (200) mapeados no código.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.models import CicloVideo, Fase, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — view_confirmar_ponto_roadmap(): modal de confirmação via HTTP'


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste')


def _url(produto_id, chave):
    return reverse('agenda_videos_roadmap_confirmar', args=[produto_id, chave])


def test_sem_ciclo_nenhum_e_chave_base_confirma_sem_salvar_nada(client, tabela_resultados):
    # Função Objetivo: 1º clique real de um produto nunca tocado — a view
    # monta um ciclo só pra EXIBIR o modal, nunca escreve no banco (a
    # criação real é view_marcar_ponto_roadmap, não esta).
    # Setup:
    produto = _criar_produto('SKU-001')

    # Exercise:
    resposta = client.get(_url(produto.id, 'base'))

    # Assert:
    nada_foi_salvo = not CicloVideo.objects.filter(produto=produto).exists()
    passou = resposta.status_code == 200 and resposta.context['tipo_acao'] == 'confirmar_simples' and nada_foi_salvo
    registrar_resultado(
        tabela_resultados, teste='sem ciclo + chave=base → confirma, sem salvar nada',
        entrada='produto sem nenhum CicloVideo, chave=base', esperado='200, tipo_acao=confirmar_simples, 0 CicloVideo no banco',
        motivo='Só visualizar o modal nunca pode escrever no banco',
        obtido=f'status={resposta.status_code}, tipo_acao={resposta.context.get("tipo_acao")}, existe_no_banco={not nada_foi_salvo}',
        passou=passou,
    )
    assert passou


def test_sem_ciclo_nenhum_e_chave_diferente_de_base_e_400(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-002')

    # Exercise:
    resposta = client.get(_url(produto.id, 'roteiro'))

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='sem ciclo + chave=roteiro → 400',
        entrada='produto sem nenhum CicloVideo, chave=roteiro', esperado='status_code == 400',
        motivo='O único ponto alcançável sem CicloVideo é "base" — qualquer outra chave é estado impossível',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_ciclo_em_base_e_chave_base_confirma(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-003')
    CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise:
    resposta = client.get(_url(produto.id, 'base'))

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['tipo_acao'] == 'confirmar_simples'
    registrar_resultado(
        tabela_resultados, teste='ciclo real em Base + chave=base → confirma',
        entrada='CicloVideo salvo, etapa_atual()=base, chave=base', esperado='200, tipo_acao=confirmar_simples',
        motivo='Etapa pedida bate com a etapa real do ciclo',
        obtido=f'status={resposta.status_code}, tipo_acao={resposta.context.get("tipo_acao")}',
        passou=passou,
    )
    assert passou


def test_ciclo_pronto_pra_postar_e_chave_postar_confirma(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-004')
    agora = timezone.now()
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1, data_devida=date(2026, 8, 10),
        base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
    )

    # Exercise:
    resposta = client.get(_url(produto.id, 'postar'))

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['tipo_acao'] == 'postar'
    registrar_resultado(
        tabela_resultados, teste='ciclo em etapa postar + chave=postar → confirma',
        entrada='Base/Roteiro/Completo concluídos, status=None, chave=postar', esperado='200, tipo_acao=postar',
        motivo='Etapa pedida bate com a etapa real do ciclo',
        obtido=f'status={resposta.status_code}, tipo_acao={resposta.context.get("tipo_acao")}',
        passou=passou,
    )
    assert passou


def test_ciclo_aguardando_aprovacao_e_chave_aguardando_aprovacao_confirma(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-005')
    agora = timezone.now()
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1, data_devida=date(2026, 8, 10),
        base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
        status=StatusPostagem.AGUARDANDO_APROVACAO, aguardando_aprovacao_em=agora,
    )

    # Exercise:
    resposta = client.get(_url(produto.id, 'aguardando_aprovacao'))

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['tipo_acao'] == 'resolver_aprovacao'
    registrar_resultado(
        tabela_resultados, teste='ciclo aguardando aprovação + chave certa → confirma',
        entrada='status=AGUARDANDO_APROVACAO, chave=aguardando_aprovacao', esperado='200, tipo_acao=resolver_aprovacao',
        motivo='Etapa pedida bate com a etapa real do ciclo',
        obtido=f'status={resposta.status_code}, tipo_acao={resposta.context.get("tipo_acao")}',
        passou=passou,
    )
    assert passou


def test_ciclo_recusado_e_chave_completo_e_nova_tentativa(client, tabela_resultados):
    # Função Objetivo: Recusado é o ÚNICO caso onde a chave pedida ("completo")
    # não é igual ao valor puro de etapa_atual() no sentido literal do fluxo
    # normal — é um caminho dedicado, checado ANTES do match genérico.
    # Setup:
    produto = _criar_produto('SKU-006')
    agora = timezone.now()
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1, data_devida=date(2026, 8, 10),
        base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
        status=StatusPostagem.RECUSADO, aguardando_aprovacao_em=agora, aprovado_ou_recusado_em=agora,
    )

    # Exercise:
    resposta = client.get(_url(produto.id, 'completo'))

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['tipo_acao'] == 'nova_tentativa'
    registrar_resultado(
        tabela_resultados, teste='ciclo recusado + chave=completo → nova_tentativa',
        entrada='status=RECUSADO, chave=completo', esperado='200, tipo_acao=nova_tentativa',
        motivo='Recusado precisa refazer o Completo — caminho dedicado, checado antes do match genérico',
        obtido=f'status={resposta.status_code}, tipo_acao={resposta.context.get("tipo_acao")}',
        passou=passou,
    )
    assert passou


def test_estado_divergente_ciclo_em_base_mas_chave_pede_postar_e_400(client, tabela_resultados):
    # Função Objetivo: simula 2 abas abertas — 1ª aba ainda mostra "Base"
    # (desatualizada), usuário clica; entre o carregamento e o clique, o
    # estado real avançou/diverge. A view precisa recusar, não confiar
    # na chave que veio da URL sem revalidar contra o ciclo real.
    # Setup:
    produto = _criar_produto('SKU-007')
    CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise:
    resposta = client.get(_url(produto.id, 'postar'))

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='ciclo em Base + chave=postar (estado divergente) → 400',
        entrada='etapa_atual()=base, chave pedida=postar', esperado='status_code == 400',
        motivo='Revalidação contra estado desatualizado — a razão de a view existir',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_ciclo_concluido_nao_tem_acao_de_confirmacao_e_400(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-008')
    agora = timezone.now()
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
        status=StatusPostagem.REPLICADO, aguardando_aprovacao_em=agora,
        aprovado_ou_recusado_em=agora, replicado_em=agora,
    )

    # Exercise:
    resposta = client.get(_url(produto.id, 'concluido'))

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='ciclo concluído + chave=concluido → 400',
        entrada='etapa_atual()=concluido, chave=concluido', esperado='status_code == 400',
        motivo='"Concluído" é um estado resultante, não uma ação com modal de confirmação própria',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_produto_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.get(_url(999999, 'base'))

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