# agenda_videos/tests/test_nivel_4__views_replicacao_automatica.py

# Função Objetivo: Testa as 5 views do ciclo de Replicação Automática —
# Nível 4 (view HTTP real), espelhando a suíte de Postagem Automática
# (mesma máquina de estados StatusExecucao, mesmo mecanismo de "só 1
# execução por vez"). listar_produtos_agenda_filtrados é substituída por
# uma fake — já tem cobertura própria em outro arquivo.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse

from produtos.models import Produto
from agenda_videos.models import (
    ExecucaoReplicacaoAutomatica, ItemExecucaoReplicacao, StatusItemExecucaoReplicacao,
    ExecucaoPostagemAutomatica, StatusExecucao,
)
import agenda_videos.views as views_module
from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — Replicação Automática: confirmar/iniciar/progresso/cancelar'


@pytest.fixture(autouse=True)
def _empresa_ativa_magazine():
    definir_empresa_ativa(EMPRESA_MAGAZINE)


def _criar_produto(sku, ean, marca='Marca Teste'):
    return Produto.objects.create(ean=ean, sku=sku, titulo='Produto Teste', marca=marca)


def _url_confirmar():
    return reverse('agenda_videos_confirmar_replicacao_automatica')


def _url_iniciar():
    return reverse('agenda_videos_iniciar_replicacao_automatica')


def _url_progresso(execucao_id):
    return reverse('agenda_videos_progresso_replicacao_automatica', args=[execucao_id])


def _url_progresso_parcial(execucao_id):
    return reverse('agenda_videos_progresso_replicacao_automatica_parcial', args=[execucao_id])


def _url_cancelar(execucao_id):
    return reverse('agenda_videos_cancelar_execucao_replicacao_travada', args=[execucao_id])


# ---------------------------------------------------------------------
# view_confirmar_replicacao_automatica
# ---------------------------------------------------------------------

def test_confirmar_sem_execucao_em_andamento_mostra_modal_com_elegiveis(client, tabela_resultados, monkeypatch):
    # Setup:
    produtos_elegiveis = [_criar_produto('SKU-RA-001', '7891111100060'), _criar_produto('SKU-RA-002', '7891111100061')]
    monkeypatch.setattr(views_module, 'listar_produtos_agenda_filtrados', lambda *args, **kwargs: produtos_elegiveis)

    # Exercise:
    resposta = client.get(_url_confirmar())

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['quantidade_elegiveis'] == 2
    registrar_resultado(
        tabela_resultados, teste='Sem execução em andamento → modal de confirmação com a contagem certa de elegíveis',
        entrada='listar_produtos_agenda_filtrados(...) → 2 produtos', esperado='status 200, quantidade_elegiveis == 2',
        motivo='Mesmo texto de confirmação da postagem, só que pro fluxo de replicar',
        obtido=f'status={resposta.status_code}, quantidade_elegiveis={resposta.context.get("quantidade_elegiveis")}',
        passou=passou,
    )
    assert passou


def test_confirmar_com_replicacao_ja_rodando_mostra_modal_de_ja_em_andamento(client, tabela_resultados):
    # Setup:
    execucao = ExecucaoReplicacaoAutomatica.objects.create(status=StatusExecucao.RODANDO)

    # Exercise:
    resposta = client.get(_url_confirmar())

    # Assert:
    passou = (
        resposta.status_code == 200
        and resposta.context['execucao'].id == execucao.id
        and resposta.context['url_nome_progresso'] == 'agenda_videos_progresso_replicacao_automatica'
    )
    registrar_resultado(
        tabela_resultados, teste='Replicação já rodando → modal "já em andamento" apontando pro progresso de REPLICAÇÃO',
        entrada='ExecucaoReplicacaoAutomatica com status=RODANDO',
        esperado="url_nome_progresso == 'agenda_videos_progresso_replicacao_automatica'",
        motivo="_obter_execucao_em_andamento() marca tipo_execucao='replicacao' nesse caso",
        obtido=f'status={resposta.status_code}, url_nome_progresso={resposta.context.get("url_nome_progresso")}',
        passou=passou,
    )
    assert passou


def test_confirmar_com_postagem_ja_rodando_mostra_modal_apontando_pra_postagem(client, tabela_resultados):
    # Setup: espelha o teste cruzado da suíte de postagem — aqui é a tela
    # de confirmar REPLICAÇÃO que precisa detectar uma execução de
    # POSTAGEM já rodando.
    ExecucaoPostagemAutomatica.objects.create(status=StatusExecucao.RODANDO)

    # Exercise:
    resposta = client.get(_url_confirmar())

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['url_nome_progresso'] == 'agenda_videos_progresso_postagem_automatica'
    registrar_resultado(
        tabela_resultados, teste='Postagem já rodando → modal de confirmar REPLICAÇÃO aponta pro progresso de POSTAGEM',
        entrada='ExecucaoPostagemAutomatica com status=RODANDO (nenhuma de replicação)',
        esperado="url_nome_progresso == 'agenda_videos_progresso_postagem_automatica'",
        motivo='Só 1 execução por vez, de qualquer tipo',
        obtido=f'status={resposta.status_code}, url_nome_progresso={resposta.context.get("url_nome_progresso")}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_iniciar_replicacao_automatica
# ---------------------------------------------------------------------

def test_iniciar_sem_execucao_em_andamento_cria_execucao_e_itens_na_ordem(client, tabela_resultados, monkeypatch):
    # Setup:
    produtos_elegiveis = [
        _criar_produto('SKU-RA-010', '7891111100070'),
        _criar_produto('SKU-RA-011', '7891111100071'),
        _criar_produto('SKU-RA-012', '7891111100072'),
    ]
    monkeypatch.setattr(views_module, 'listar_produtos_agenda_filtrados', lambda *args, **kwargs: produtos_elegiveis)

    # Exercise:
    resposta = client.get(_url_iniciar())

    # Assert:
    execucao = ExecucaoReplicacaoAutomatica.objects.get()
    itens = list(execucao.itens.order_by('ordem'))
    passou = (
        resposta.status_code == 302
        and resposta.url == _url_progresso(execucao.id)
        and [i.produto_id for i in itens] == [p.id for p in produtos_elegiveis]
        and [i.ordem for i in itens] == [1, 2, 3]
    )
    registrar_resultado(
        tabela_resultados, teste='3 produtos elegíveis → cria 1 execução + 3 itens, na mesma ordem, redireciona pro progresso',
        entrada=f'listar_produtos_agenda_filtrados(...) → {[p.sku for p in produtos_elegiveis]}',
        esperado='1 ExecucaoReplicacaoAutomatica, 3 ItemExecucaoReplicacao com ordem 1/2/3',
        motivo='Mesma regra de ordem da suíte de postagem',
        obtido=f'status={resposta.status_code}, redirect_url={resposta.url}, produtos_dos_itens={[i.produto_id for i in itens]}, ordens={[i.ordem for i in itens]}',
        passou=passou,
    )
    assert passou


def test_iniciar_com_execucao_ja_em_andamento_nao_cria_outra_e_redireciona_pra_existente(client, tabela_resultados, monkeypatch):
    # Setup:
    execucao_existente = ExecucaoReplicacaoAutomatica.objects.create(status=StatusExecucao.RODANDO)

    def _nao_deveria_ser_chamada(*args, **kwargs):
        raise AssertionError('listar_produtos_agenda_filtrados não deveria ser chamado quando já existe execução em andamento')
    monkeypatch.setattr(views_module, 'listar_produtos_agenda_filtrados', _nao_deveria_ser_chamada)

    # Exercise:
    resposta = client.get(_url_iniciar())

    # Assert:
    total_execucoes = ExecucaoReplicacaoAutomatica.objects.count()
    passou = resposta.status_code == 302 and resposta.url == _url_progresso(execucao_existente.id) and total_execucoes == 1
    registrar_resultado(
        tabela_resultados, teste='Execução já em andamento → não cria outra, redireciona pra existente',
        entrada=f'ExecucaoReplicacaoAutomatica #{execucao_existente.id} já RODANDO',
        esperado=f'redireciona pra {_url_progresso(execucao_existente.id)}, total de execuções continua 1',
        motivo='Só 1 execução por vez',
        obtido=f'status={resposta.status_code}, redirect_url={resposta.url}, total_execucoes={total_execucoes}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_progresso_replicacao_automatica / _parcial
# ---------------------------------------------------------------------

def _criar_execucao_com_itens():
    execucao = ExecucaoReplicacaoAutomatica.objects.create(status=StatusExecucao.RODANDO)
    produtos = [_criar_produto(f'SKU-PROGR-{n}', f'789111110008{n}') for n in range(4)]
    status_por_ordem = [
        StatusItemExecucaoReplicacao.CONCLUIDO, StatusItemExecucaoReplicacao.FALHOU,
        StatusItemExecucaoReplicacao.CANCELADO, StatusItemExecucaoReplicacao.AGUARDANDO,
    ]
    for ordem, (produto, status) in enumerate(zip(produtos, status_por_ordem), start=1):
        ItemExecucaoReplicacao.objects.create(execucao=execucao, produto=produto, ordem=ordem, status=status)
    return execucao


def test_progresso_completo_mostra_contadores_certos_por_status(client, tabela_resultados):
    # Setup:
    execucao = _criar_execucao_com_itens()

    # Exercise:
    resposta = client.get(_url_progresso(execucao.id))

    # Assert:
    contexto = resposta.context
    passou = (
        resposta.status_code == 200
        and contexto['total'] == 4 and contexto['concluidos'] == 1
        and contexto['falharam'] == 1 and contexto['cancelados'] == 1
    )
    registrar_resultado(
        tabela_resultados, teste='4 itens (1 concluído, 1 falhou, 1 cancelado, 1 aguardando) → contadores certos',
        entrada='1 execução, 4 itens com status diferentes', esperado='total=4, concluidos=1, falharam=1, cancelados=1',
        motivo='_montar_contexto_progresso_replicacao soma por status',
        obtido=f'total={contexto.get("total")}, concluidos={contexto.get("concluidos")}, falharam={contexto.get("falharam")}, cancelados={contexto.get("cancelados")}',
        passou=passou,
    )
    assert passou


def test_progresso_parcial_usa_o_mesmo_contexto_do_completo(client, tabela_resultados):
    # Setup:
    execucao = _criar_execucao_com_itens()

    # Exercise:
    resposta = client.get(_url_progresso_parcial(execucao.id))

    # Assert:
    contexto = resposta.context
    passou = resposta.status_code == 200 and contexto['total'] == 4 and contexto['concluidos'] == 1
    registrar_resultado(
        tabela_resultados, teste='Fragmento HTMX (parcial) devolve o mesmo cálculo de contexto que a página completa',
        entrada='mesma execução do teste anterior', esperado='total=4, concluidos=1',
        motivo='Polling HTMX precisa do mesmo cálculo, só muda o template',
        obtido=f'status={resposta.status_code}, total={contexto.get("total")}, concluidos={contexto.get("concluidos")}',
        passou=passou,
    )
    assert passou


def test_progresso_execucao_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.get(_url_progresso(999999))

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='execucao_id inexistente → 404',
        entrada='execucao_id=999999', esperado='status_code == 404',
        motivo='get_object_or_404 protege a tela de progresso',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_cancelar_execucao_replicacao_travada
# ---------------------------------------------------------------------

def test_cancelar_execucao_travada_cancela_so_os_itens_aguardando(client, tabela_resultados):
    # Setup:
    execucao = ExecucaoReplicacaoAutomatica.objects.create(status=StatusExecucao.RODANDO)
    produto_concluido = _criar_produto('SKU-CANCR-001', '7891111100090')
    produto_aguardando_1 = _criar_produto('SKU-CANCR-002', '7891111100091')
    produto_aguardando_2 = _criar_produto('SKU-CANCR-003', '7891111100092')
    item_concluido = ItemExecucaoReplicacao.objects.create(
        execucao=execucao, produto=produto_concluido, ordem=1, status=StatusItemExecucaoReplicacao.CONCLUIDO)
    ItemExecucaoReplicacao.objects.create(
        execucao=execucao, produto=produto_aguardando_1, ordem=2, status=StatusItemExecucaoReplicacao.AGUARDANDO)
    ItemExecucaoReplicacao.objects.create(
        execucao=execucao, produto=produto_aguardando_2, ordem=3, status=StatusItemExecucaoReplicacao.AGUARDANDO)

    # Exercise:
    resposta = client.post(_url_cancelar(execucao.id))

    # Assert:
    execucao.refresh_from_db()
    status_dos_itens = list(execucao.itens.order_by('ordem').values_list('status', flat=True))
    passou = (
        resposta.status_code == 302
        and resposta.url == _url_progresso(execucao.id)
        and execucao.status == StatusExecucao.CANCELADO
        and execucao.finalizado_em is not None
        and status_dos_itens == [
            StatusItemExecucaoReplicacao.CONCLUIDO, StatusItemExecucaoReplicacao.CANCELADO, StatusItemExecucaoReplicacao.CANCELADO,
        ]
    )
    registrar_resultado(
        tabela_resultados, teste='Cancelar execução travada → só itens AGUARDANDO viram CANCELADO',
        entrada='1 item concluído + 2 aguardando',
        esperado='execução vira CANCELADO com finalizado_em preenchido; status = [concluido, cancelado, cancelado]',
        motivo='Mesma regra da suíte de postagem — nunca desfaz trabalho já feito',
        obtido=f'status={resposta.status_code}, execucao_status={execucao.status}, finalizado_em={execucao.finalizado_em}, itens={status_dos_itens}',
        passou=passou,
    )
    assert passou


def test_cancelar_execucao_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url_cancelar(999999))

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='execucao_id inexistente → 404',
        entrada='execucao_id=999999', esperado='status_code == 404',
        motivo='get_object_or_404 também protege o cancelamento de replicação',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou