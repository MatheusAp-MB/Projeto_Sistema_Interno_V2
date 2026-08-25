# agenda_videos/tests/test_nivel_4__views_postagem_automatica.py

# Função Objetivo: Testa as 5 views do ciclo de Postagem Automática —
# Nível 4 (view HTTP real): confirmar (abre modal), iniciar (cria a
# execução), progresso (completo e parcial/HTMX) e cancelar execução
# travada. listar_produtos_elegiveis é substituída por uma fake — já tem
# cobertura própria em outro lugar; aqui o que importa é o COMPORTAMENTO
# da view em cima do resultado dela.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse

from produtos.models import Produto
from agenda_videos.models import (
    ExecucaoPostagemAutomatica, ItemExecucaoPostagem, StatusItemExecucao,
    ExecucaoReplicacaoAutomatica, StatusExecucao,
)
import agenda_videos.views as views_module
from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — Postagem Automática: confirmar/iniciar/progresso/cancelar'


@pytest.fixture(autouse=True)
def _empresa_ativa_magazine():
    definir_empresa_ativa(EMPRESA_MAGAZINE)


def _criar_produto(sku, ean, marca='Marca Teste'):
    return Produto.objects.create(ean=ean, sku=sku, titulo='Produto Teste', marca=marca)


def _url_confirmar():
    return reverse('agenda_videos_confirmar_postagem_automatica')


def _url_iniciar():
    return reverse('agenda_videos_iniciar_postagem_automatica')


def _url_progresso(execucao_id):
    return reverse('agenda_videos_progresso_postagem_automatica', args=[execucao_id])


def _url_progresso_parcial(execucao_id):
    return reverse('agenda_videos_progresso_postagem_automatica_parcial', args=[execucao_id])


def _url_cancelar(execucao_id):
    return reverse('agenda_videos_cancelar_execucao_travada', args=[execucao_id])


# ---------------------------------------------------------------------
# view_confirmar_postagem_automatica
# ---------------------------------------------------------------------

def test_confirmar_sem_execucao_em_andamento_mostra_modal_com_elegiveis(client, tabela_resultados, monkeypatch):
    # Setup:
    produtos_elegiveis = [_criar_produto('SKU-PA-001', '7891111100020'), _criar_produto('SKU-PA-002', '7891111100021')]
    monkeypatch.setattr(views_module, 'listar_produtos_elegiveis', lambda: produtos_elegiveis)

    # Exercise:
    resposta = client.get(_url_confirmar())

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['quantidade_elegiveis'] == 2
    registrar_resultado(
        tabela_resultados, teste='Sem execução em andamento → modal de confirmação com a contagem certa de elegíveis',
        entrada='listar_produtos_elegiveis() → 2 produtos', esperado='status 200, quantidade_elegiveis == 2',
        motivo='É essa contagem que aparece no texto de confirmação pro usuário',
        obtido=f'status={resposta.status_code}, quantidade_elegiveis={resposta.context.get("quantidade_elegiveis")}',
        passou=passou,
    )
    assert passou


def test_confirmar_com_postagem_ja_rodando_mostra_modal_de_ja_em_andamento(client, tabela_resultados):
    # Setup:
    execucao = ExecucaoPostagemAutomatica.objects.create(status=StatusExecucao.RODANDO)

    # Exercise:
    resposta = client.get(_url_confirmar())

    # Assert:
    passou = (
        resposta.status_code == 200
        and resposta.context['execucao'].id == execucao.id
        and resposta.context['url_nome_progresso'] == 'agenda_videos_progresso_postagem_automatica'
    )
    registrar_resultado(
        tabela_resultados, teste='Postagem já rodando → mostra modal "já em andamento" apontando pro progresso de POSTAGEM',
        entrada='ExecucaoPostagemAutomatica com status=RODANDO',
        esperado="url_nome_progresso == 'agenda_videos_progresso_postagem_automatica'",
        motivo="_obter_execucao_em_andamento() marca tipo_execucao='postagem' nesse caso",
        obtido=f'status={resposta.status_code}, url_nome_progresso={resposta.context.get("url_nome_progresso")}',
        passou=passou,
    )
    assert passou


def test_confirmar_com_replicacao_ja_rodando_mostra_modal_apontando_pra_replicacao(client, tabela_resultados):
    # Setup: mesmo cenário do teste acima, mas com uma execução de
    # REPLICAÇÃO rodando — prova que a tela de confirmar POSTAGEM também
    # detecta corretamente uma execução do outro tipo.
    ExecucaoReplicacaoAutomatica.objects.create(status=StatusExecucao.RODANDO)

    # Exercise:
    resposta = client.get(_url_confirmar())

    # Assert:
    passou = resposta.status_code == 200 and resposta.context['url_nome_progresso'] == 'agenda_videos_progresso_replicacao_automatica'
    registrar_resultado(
        tabela_resultados, teste='Replicação já rodando → modal de confirmar POSTAGEM aponta pro progresso de REPLICAÇÃO',
        entrada='ExecucaoReplicacaoAutomatica com status=RODANDO (nenhuma de postagem)',
        esperado="url_nome_progresso == 'agenda_videos_progresso_replicacao_automatica'",
        motivo='Só 1 execução por vez, de qualquer tipo — _obter_execucao_em_andamento() precisa achar a de replicação também',
        obtido=f'status={resposta.status_code}, url_nome_progresso={resposta.context.get("url_nome_progresso")}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_iniciar_postagem_automatica
# ---------------------------------------------------------------------

def test_iniciar_sem_execucao_em_andamento_cria_execucao_e_itens_na_ordem(client, tabela_resultados, monkeypatch):
    # Setup:
    produtos_elegiveis = [
        _criar_produto('SKU-PA-010', '7891111100030'),
        _criar_produto('SKU-PA-011', '7891111100031'),
        _criar_produto('SKU-PA-012', '7891111100032'),
    ]
    monkeypatch.setattr(views_module, 'listar_produtos_elegiveis', lambda: produtos_elegiveis)

    # Exercise:
    resposta = client.get(_url_iniciar())

    # Assert:
    execucao = ExecucaoPostagemAutomatica.objects.get()
    itens = list(execucao.itens.order_by('ordem'))
    passou = (
        resposta.status_code == 302
        and resposta.url == _url_progresso(execucao.id)
        and [i.produto_id for i in itens] == [p.id for p in produtos_elegiveis]
        and [i.ordem for i in itens] == [1, 2, 3]
    )
    registrar_resultado(
        tabela_resultados, teste='3 produtos elegíveis → cria 1 execução + 3 itens, na mesma ordem, redireciona pro progresso',
        entrada=f'listar_produtos_elegiveis() → {[p.sku for p in produtos_elegiveis]}',
        esperado='1 ExecucaoPostagemAutomatica, 3 ItemExecucaoPostagem com ordem 1/2/3 na mesma ordem dos produtos',
        motivo='ordem precisa refletir a prioridade já calculada por listar_produtos_elegiveis, não pode embaralhar',
        obtido=f'status={resposta.status_code}, redirect_url={resposta.url}, produtos_dos_itens={[i.produto_id for i in itens]}, ordens={[i.ordem for i in itens]}',
        passou=passou,
    )
    assert passou


def test_iniciar_com_execucao_ja_em_andamento_nao_cria_outra_e_redireciona_pra_existente(client, tabela_resultados, monkeypatch):
    # Setup:
    execucao_existente = ExecucaoPostagemAutomatica.objects.create(status=StatusExecucao.RODANDO)

    def _nao_deveria_ser_chamada():
        raise AssertionError('listar_produtos_elegiveis não deveria ser chamado quando já existe execução em andamento')
    monkeypatch.setattr(views_module, 'listar_produtos_elegiveis', _nao_deveria_ser_chamada)

    # Exercise:
    resposta = client.get(_url_iniciar())

    # Assert:
    total_execucoes = ExecucaoPostagemAutomatica.objects.count()
    passou = resposta.status_code == 302 and resposta.url == _url_progresso(execucao_existente.id) and total_execucoes == 1
    registrar_resultado(
        tabela_resultados, teste='Execução já em andamento → não cria outra, redireciona pra existente',
        entrada=f'ExecucaoPostagemAutomatica #{execucao_existente.id} já RODANDO',
        esperado=f'redireciona pra {_url_progresso(execucao_existente.id)}, total de execuções continua 1',
        motivo='Só 1 execução por vez — 2º clique não pode duplicar a rodada',
        obtido=f'status={resposta.status_code}, redirect_url={resposta.url}, total_execucoes={total_execucoes}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_progresso_postagem_automatica / _parcial
# ---------------------------------------------------------------------

def _criar_execucao_com_itens():
    execucao = ExecucaoPostagemAutomatica.objects.create(status=StatusExecucao.RODANDO)
    produtos = [_criar_produto(f'SKU-PROG-{n}', f'789111110004{n}') for n in range(4)]
    status_por_ordem = [
        StatusItemExecucao.CONCLUIDO, StatusItemExecucao.FALHOU,
        StatusItemExecucao.CANCELADO, StatusItemExecucao.AGUARDANDO,
    ]
    for ordem, (produto, status) in enumerate(zip(produtos, status_por_ordem), start=1):
        ItemExecucaoPostagem.objects.create(execucao=execucao, produto=produto, ordem=ordem, status=status)
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
        motivo='_montar_contexto_progresso soma por status — aguardando não entra em nenhum desses 3 contadores',
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
        entrada='mesma execução do teste anterior', esperado='total=4, concluidos=1 (mesmo contexto)',
        motivo='O polling HTMX consulta esse endpoint a cada poucos segundos — precisa ser o mesmo cálculo, só com template diferente',
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
        motivo='get_object_or_404 protege a tela de progresso de um id inválido/já apagado',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_cancelar_execucao_travada
# ---------------------------------------------------------------------

def test_cancelar_execucao_travada_cancela_so_os_itens_aguardando(client, tabela_resultados):
    # Setup: 1 item já concluído (não pode virar cancelado) + 2 aguardando
    # (precisam virar cancelado).
    execucao = ExecucaoPostagemAutomatica.objects.create(status=StatusExecucao.RODANDO)
    produto_concluido = _criar_produto('SKU-CANC-001', '7891111100050')
    produto_aguardando_1 = _criar_produto('SKU-CANC-002', '7891111100051')
    produto_aguardando_2 = _criar_produto('SKU-CANC-003', '7891111100052')
    item_concluido = ItemExecucaoPostagem.objects.create(
        execucao=execucao, produto=produto_concluido, ordem=1, status=StatusItemExecucao.CONCLUIDO)
    ItemExecucaoPostagem.objects.create(
        execucao=execucao, produto=produto_aguardando_1, ordem=2, status=StatusItemExecucao.AGUARDANDO)
    ItemExecucaoPostagem.objects.create(
        execucao=execucao, produto=produto_aguardando_2, ordem=3, status=StatusItemExecucao.AGUARDANDO)

    # Exercise:
    resposta = client.post(_url_cancelar(execucao.id))

    # Assert:
    execucao.refresh_from_db()
    item_concluido.refresh_from_db()
    status_dos_itens = list(execucao.itens.order_by('ordem').values_list('status', flat=True))
    passou = (
        resposta.status_code == 302
        and resposta.url == _url_progresso(execucao.id)
        and execucao.status == StatusExecucao.CANCELADO
        and execucao.finalizado_em is not None
        and status_dos_itens == [StatusItemExecucao.CONCLUIDO, StatusItemExecucao.CANCELADO, StatusItemExecucao.CANCELADO]
    )
    registrar_resultado(
        tabela_resultados, teste='Cancelar execução travada → só itens AGUARDANDO viram CANCELADO, item já CONCLUIDO fica intocado',
        entrada='1 item concluído + 2 aguardando',
        esperado='execução vira CANCELADO com finalizado_em preenchido; status dos itens = [concluido, cancelado, cancelado]',
        motivo='Cancelar não pode desfazer trabalho já feito — só interrompe o que ainda nem começou',
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
        motivo='get_object_or_404 protege contra id inválido também no cancelamento',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_progresso_postagem_automatica — regressão do "Achado central" (25/08)
# ---------------------------------------------------------------------

def test_progresso_aguardando_inicio_manda_a_empresa_ativa_pro_agente_local(client, tabela_resultados):
    # Setup: status padrão (AGUARDANDO_INICIO) é o único que renderiza o
    # <script> que avisa o agente local — é ele que carrega ?empresa=...
    # na URL do fetch. O agente NUNCA tem sessão de navegador, então sem
    # isso ele não tem como saber qual empresa usar (era exatamente o
    # "Achado central" corrigido nesta sessão).
    execucao = ExecucaoPostagemAutomatica.objects.create()

    # Exercise:
    resposta = client.get(_url_progresso(execucao.id))

    # Assert:
    passou = resposta.status_code == 200 and f'?empresa={EMPRESA_MAGAZINE}' in resposta.content.decode()
    registrar_resultado(
        tabela_resultados, teste='Tela de progresso (aguardando início) manda ?empresa= pro agente local',
        entrada='execução recém-criada (status padrão AGUARDANDO_INICIO), empresa ativa=MAGAZINE',
        esperado=f"HTML renderizado contém '?empresa={EMPRESA_MAGAZINE}' na URL do fetch",
        motivo='Sem isso, o agente local não tem como saber qual empresa usar',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou