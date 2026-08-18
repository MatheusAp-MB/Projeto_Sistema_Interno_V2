# agenda_videos/tests/test_nivel_4__view_marcar_ponto_roadmap.py

# Função Objetivo: Testa view_marcar_ponto_roadmap() — Nível 4 (view HTTP
# real). Primeira view de ESCRITA testada nesta rodada — precisa da fixture
# regua_de_fases porque o card renderizado no final (_recarregar_e_
# renderizar_card -> estrutura_parcial_card_produto.html) usa o mesmo
# widget de roadmap de view_agenda_videos. Cobre criação do 1º ciclo,
# marcação normal, os 2 tipos de estado inválido (chave errada / etapa
# fora de base-roteiro-completo) e a sincronização do cache no final.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse
from django.utils import timezone

from produtos.models import Produto
from agenda_videos.models import CicloVideo, ConfiguracaoFase, Fase, IndicadoresAgendaProduto, StatusPostagem
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — view_marcar_ponto_roadmap(): marcar Base/Roteiro/Completo via HTTP'


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste')


def _url(produto_id, chave):
    return reverse('agenda_videos_roadmap_marcar', args=[produto_id, chave])


@pytest.fixture
def regua_de_fases():
    # Setup: o card final (_recarregar_e_renderizar_card) sempre renderiza
    # o widget de roadmap, que exige a régua de ConfiguracaoFase existir —
    # mesma dependência real já vista em view_agenda_videos.
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


def test_sem_ciclo_e_chave_base_cria_o_simples_e_marca(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-001')

    # Exercise:
    resposta = client.get(_url(produto.id, 'base'))

    # Assert:
    ciclo = CicloVideo.objects.filter(produto=produto).first()
    passou = (
        resposta.status_code == 200 and ciclo is not None
        and ciclo.fase == Fase.SIMPLES and ciclo.base_concluido_em is not None
    )
    registrar_resultado(
        tabela_resultados, teste='sem ciclo + chave=base → cria Simples e marca',
        entrada='produto sem nenhum CicloVideo, chave=base', esperado='CicloVideo criado (Simples), base_concluido_em preenchido',
        motivo='1º clique real de um produto nunca tocado — cria o Simples sozinho',
        obtido=f'status={resposta.status_code}, ciclo_existe={ciclo is not None}, base_concluido_em={ciclo.base_concluido_em if ciclo else None}',
        passou=passou,
    )
    assert passou


def test_sem_ciclo_e_chave_diferente_de_base_e_400_sem_criar_nada(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-002')

    # Exercise:
    resposta = client.get(_url(produto.id, 'roteiro'))

    # Assert:
    nada_criado = not CicloVideo.objects.filter(produto=produto).exists()
    passou = resposta.status_code == 400 and nada_criado
    registrar_resultado(
        tabela_resultados, teste='sem ciclo + chave=roteiro → 400, nada criado',
        entrada='produto sem nenhum CicloVideo, chave=roteiro', esperado='400, 0 CicloVideo no banco',
        motivo='O único ponto alcançável sem CicloVideo é base',
        obtido=f'status={resposta.status_code}, nada_criado={nada_criado}',
        passou=passou,
    )
    assert passou


def test_ciclo_em_roteiro_e_chave_roteiro_marca(client, tabela_resultados, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-003')
    ciclo = CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1, base_concluido_em=timezone.now(),
    )

    # Exercise:
    resposta = client.get(_url(produto.id, 'roteiro'))

    # Assert:
    ciclo.refresh_from_db()
    passou = resposta.status_code == 200 and ciclo.roteiro_concluido_em is not None
    registrar_resultado(
        tabela_resultados, teste='ciclo em Roteiro + chave=roteiro → marca',
        entrada='base já concluída, etapa_atual()=roteiro, chave=roteiro', esperado='200, roteiro_concluido_em preenchido',
        motivo='Etapa pedida bate com a etapa real do ciclo',
        obtido=f'status={resposta.status_code}, roteiro_concluido_em={ciclo.roteiro_concluido_em}',
        passou=passou,
    )
    assert passou


def test_estado_divergente_ciclo_em_base_mas_chave_pede_completo_e_400(client, tabela_resultados, regua_de_fases):
    # Função Objetivo: mesma revalidação de estado já vista em
    # view_confirmar_ponto_roadmap — aqui é a view que efetivamente ESCREVE,
    # então é ainda mais importante que não aceite uma chave desatualizada.
    # Setup:
    produto = _criar_produto('SKU-004')
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise:
    resposta = client.get(_url(produto.id, 'completo'))

    # Assert:
    ciclo.refresh_from_db()
    passou = resposta.status_code == 400 and ciclo.completo_concluido_em is None
    registrar_resultado(
        tabela_resultados, teste='ciclo em Base + chave=completo (divergente) → 400, nada marcado',
        entrada='etapa_atual()=base, chave pedida=completo', esperado='400, completo_concluido_em continua None',
        motivo='Revalidação contra estado desatualizado — não pode marcar campo fora de ordem',
        obtido=f'status={resposta.status_code}, completo_concluido_em={ciclo.completo_concluido_em}',
        passou=passou,
    )
    assert passou


def test_etapa_fora_de_base_roteiro_completo_e_400(client, tabela_resultados, regua_de_fases):
    # Função Objetivo: "Postar" em diante é responsabilidade de
    # view_executar_acao_ciclica, nunca desta view — mesmo que a chave
    # peça exatamente a etapa real do ciclo.
    # Setup:
    produto = _criar_produto('SKU-005')
    agora = timezone.now()
    ciclo = CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        base_concluido_em=agora, roteiro_concluido_em=agora, completo_concluido_em=agora,
    )

    # Exercise:
    resposta = client.get(_url(produto.id, 'postar'))

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='etapa_atual()=postar + chave=postar → 400 (fora do escopo desta view)',
        entrada='produção completa, etapa_atual()=postar, chave=postar', esperado='status_code == 400',
        motivo='view_marcar_ponto_roadmap só marca base/roteiro/completo — postar é outra view',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_produto_inexistente_devolve_404(client, tabela_resultados, regua_de_fases):
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


def test_marcar_sincroniza_o_cache_de_indicadores(client, tabela_resultados, regua_de_fases):
    # Função Objetivo: _recarregar_e_renderizar_card sempre chama
    # sincronizar_indicadores_agenda_produto() depois de qualquer escrita —
    # confirma que o cache reflete a etapa nova, não a antiga.
    # Setup:
    produto = _criar_produto('SKU-006')

    # Exercise:
    resposta = client.get(_url(produto.id, 'base'))

    # Assert:
    indicadores = IndicadoresAgendaProduto.objects.filter(produto=produto).first()
    passou = resposta.status_code == 200 and indicadores is not None and indicadores.etapa_atual == 'roteiro'
    registrar_resultado(
        tabela_resultados, teste='marcar Base sincroniza o cache pra etapa Roteiro',
        entrada='produto sem cache prévio, marca base', esperado='IndicadoresAgendaProduto.etapa_atual == "roteiro"',
        motivo='Base acabou de ser concluída — a próxima etapa real já é Roteiro, e o cache precisa refletir isso na hora',
        obtido=f'status={resposta.status_code}, etapa_atual_no_cache={indicadores.etapa_atual if indicadores else None}',
        passou=passou,
    )
    assert passou