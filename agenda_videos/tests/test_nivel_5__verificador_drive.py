# agenda_videos\tests\test_nivel_5__verificador_drive.py

# Função Objetivo: Confirma verificar_produto_no_drive()/verificar_todos_no_drive()
# contra o Google Drive DE VERDADE — rede real + credencial real, usando o
# EAN de referência já validado (QUIMIVIDA, 0789888395162 — 18 arquivos,
# Simples + Mensal 01-04 + Trimestral 01, todos completos e coerentes, ver
# nota "Convencao de Nomenclatura de Arquivos no Drive" no Obsidian).
# SÓ LEITURA no Drive; a escrita é sempre no banco de TESTE (CicloVideo),
# isolado e descartável. Par desta suíte: as versões SIMULADAS (mock só na
# borda de rede) estão em test_nivel_3__verificador.py — se aqui falhar e lá
# passar, o problema é do lado do Drive (dado/permissão), não do código.
#
# Auto-skip: se GOOGLE_DRIVE_CREDENCIAIS_JSON não estiver configurado nesta
# máquina, pula de forma limpa em vez de quebrar.

import pytest
from django.conf import settings

from produtos.models import Produto
from agenda_videos.models import CicloVideo, Fase
from agenda_videos.funcoes_auxiliares.drive.verificador import verificar_produto_no_drive, verificar_todos_no_drive
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Integração real — verificador.py contra o Google Drive (EAN de referência QUIMIVIDA)'

MARCA_REFERENCIA = 'QUIMIVIDA'
EAN_REFERENCIA = '0789888395162'

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        not settings.GOOGLE_DRIVE_CREDENCIAIS_JSON,
        reason='GOOGLE_DRIVE_CREDENCIAIS_JSON não configurado nesta máquina — sem credencial, sem teste real de Drive.',
    ),
]


def _criar_produto_quimivida():
    return Produto.objects.create(
        ean=EAN_REFERENCIA, sku=f'SKU-{EAN_REFERENCIA}', titulo='Produto Teste QUIMIVIDA', marca=MARCA_REFERENCIA,
    )


def test_verificar_produto_no_drive_avanca_base_roteiro_completo_de_verdade(tabela_resultados):
    # Função Objetivo: Simples#1 recém criado (etapa=base) contra a pasta
    # real do QUIMIVIDA — como o trio Base/Roteiro/Completo do Simples está
    # confirmado completo e coerente (18/18, validado nesta sessão), a
    # função precisa avançar as 3 etapas de uma vez e parar em "postar"
    # (que não depende de arquivo).
    # Setup:
    produto = _criar_produto_quimivida()
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise:
    etapas_marcadas, estrutura_drive, diagnostico = verificar_produto_no_drive(produto.id)

    # Assert:
    ciclo.refresh_from_db()
    passou = (
        etapas_marcadas == ['base', 'roteiro', 'completo']
        and diagnostico is None
        and estrutura_drive.pasta_encontrada is True
        and ciclo.base_concluido_em is not None
        and ciclo.roteiro_concluido_em is not None
        and ciclo.completo_concluido_em is not None
    )
    registrar_resultado(
        tabela_resultados, teste='verificar_produto_no_drive (Drive real) — avança Base/Roteiro/Completo',
        entrada=f'marca={MARCA_REFERENCIA!r}, ean={EAN_REFERENCIA!r}, ciclo Simples#1 recém criado',
        esperado="(['base','roteiro','completo'], None) — pasta de referência 100% coerente",
        motivo='Prova a cadeia inteira contra o Drive de verdade — se falhar aqui mas passar no simulado, o problema é dado/permissão do Drive',
        obtido=f'etapas_marcadas={etapas_marcadas}, diagnostico={diagnostico}, pasta_encontrada={estrutura_drive.pasta_encontrada}',
        passou=passou,
    )
    assert passou


def test_verificar_todos_no_drive_encontra_e_avanca_o_produto_quimivida(tabela_resultados):
    # Função Objetivo: mesma prova, mas pelo caminho em massa (sincroniza
    # snapshot de TODOS os produtos do banco de teste contra o Drive real,
    # depois avança) — só o produto QUIMIVIDA existe no banco de teste,
    # então ele é o único que pode aparecer no resumo.
    # Setup:
    produto = _criar_produto_quimivida()
    ciclo = CicloVideo.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise:
    resumo_por_produto, sem_produto_no_banco = verificar_todos_no_drive()

    # Assert:
    ciclo.refresh_from_db()
    passou = (
        resumo_por_produto == [(produto.id, ['base', 'roteiro', 'completo'])]
        and isinstance(sem_produto_no_banco, list)
        and ciclo.base_concluido_em is not None
    )
    registrar_resultado(
        tabela_resultados, teste='verificar_todos_no_drive (Drive real) — encontra e avança o QUIMIVIDA',
        entrada='único Produto no banco de teste é o QUIMIVIDA — Drive real tem centenas de outros EANs',
        esperado="resumo=[(produto_id, ['base','roteiro','completo'])] — resto do catálogo real vira sem_produto_no_banco",
        motivo='sem_produto_no_banco depende do estado vivo do Drive (não controlamos) — só checamos o tipo; o produto nosso é exato',
        obtido=f'resumo={resumo_por_produto}, total_sem_produto_no_banco={len(sem_produto_no_banco)}',
        passou=passou,
    )
    assert passou