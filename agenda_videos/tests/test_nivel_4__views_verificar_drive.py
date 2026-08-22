# agenda_videos/tests/test_nivel_4__views_verificar_drive.py

# Função Objetivo: Testa view_verificar_produto_drive() e
# view_verificar_todos_drive() — Nível 4 (view HTTP real). É a versão
# síncrona/antiga de verificação manual de Drive (sem thread+polling, de
# antes do Portal do Drive existir) — ainda roteada e acessível, por isso
# ainda precisa de teste, mesmo com o comentário [PENDENTE] no código
# sugerindo que ficou "esquecida".
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse

from produtos.models import Produto
from agenda_videos.models import ConfiguracaoFase, Fase
import agenda_videos.views as views_module
from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — view_verificar_produto_drive()/view_verificar_todos_drive()'


@pytest.fixture(autouse=True)
def _empresa_ativa_magazine():
    definir_empresa_ativa(EMPRESA_MAGAZINE)


@pytest.fixture
def regua_de_fases():
    # Setup: _recarregar_e_renderizar_card() (usada pela verificação
    # individual) chama sincronizar_indicadores_agenda_produto(), que
    # precisa de ConfiguracaoFase cadastrada — mesmo fixture já usada em
    # test_nivel_4__view_alternar_urgente.py.
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


def _criar_produto(sku, ean, marca='Marca Teste'):
    return Produto.objects.create(ean=ean, sku=sku, titulo='Produto Teste', marca=marca)


def _url_verificar_produto(produto_id):
    return reverse('agenda_videos_verificar_drive', args=[produto_id])


def _url_verificar_todos():
    return reverse('agenda_videos_verificar_todos_drive')


# ---------------------------------------------------------------------
# view_verificar_produto_drive
# ---------------------------------------------------------------------

def test_verificar_produto_sucesso_recarrega_o_card(client, tabela_resultados, monkeypatch, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-VD-001', '7891111100010')
    chamadas = []
    monkeypatch.setattr(views_module, 'verificar_produto_no_drive', lambda produto_id: chamadas.append(produto_id))

    # Exercise:
    resposta = client.get(_url_verificar_produto(produto.id))

    # Assert:
    passou = resposta.status_code == 200 and chamadas == [produto.id]
    registrar_resultado(
        tabela_resultados, teste='Verificação individual sem erro → recarrega o card, chamando verificar_produto_no_drive 1x',
        entrada=f'produto_id={produto.id}', esperado='status 200, verificar_produto_no_drive chamado com esse produto_id',
        motivo='Fluxo feliz: nenhum contexto de erro precisa ser injetado no card',
        obtido=f'status={resposta.status_code}, chamadas={chamadas}',
        passou=passou,
    )
    assert passou


def test_verificar_produto_com_falha_mostra_erro_no_card(client, tabela_resultados, monkeypatch, regua_de_fases):
    # Setup:
    produto = _criar_produto('SKU-VD-002', '7891111100011')

    def _verificar_com_falha(produto_id):
        raise ConnectionError('Falha simulada de rede com o Drive')
    monkeypatch.setattr(views_module, 'verificar_produto_no_drive', _verificar_com_falha)

    # Exercise:
    resposta = client.get(_url_verificar_produto(produto.id))

    # Assert:
    passou = resposta.status_code == 200 and 'Não foi possível conectar ao Google Drive' in (resposta.context.get('erro_verificacao_drive') or '')
    registrar_resultado(
        tabela_resultados, teste='Verificação individual com exceção → recarrega o card com erro_verificacao_drive preenchido',
        entrada='verificar_produto_no_drive lançando ConnectionError',
        esperado="status 200, context['erro_verificacao_drive'] cita 'Não foi possível conectar'",
        motivo='O card nunca pode quebrar (500) só porque o Drive está fora do ar no momento',
        obtido=f'status={resposta.status_code}, erro_verificacao_drive={resposta.context.get("erro_verificacao_drive")!r}',
        passou=passou,
    )
    assert passou


def test_verificar_produto_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.get(_url_verificar_produto(999999))

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='produto_id inexistente → 404',
        entrada='produto_id=999999', esperado='status_code == 404',
        motivo='get_object_or_404 precisa disparar 404 antes de chamar o Drive',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_verificar_todos_drive
# ---------------------------------------------------------------------

def test_verificar_todos_com_avanco_mostra_mensagem_de_sucesso_e_redireciona(client, tabela_resultados, monkeypatch):
    # Setup:
    resumo_por_produto = [(1, ['ponto_a']), (2, ['ponto_b', 'ponto_c'])]
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', lambda: (resumo_por_produto, []))

    # Exercise:
    resposta = client.get(_url_verificar_todos(), follow=True)

    # Assert:
    from django.contrib.messages import get_messages
    mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
    passou = (
        resposta.status_code == 200
        and any('2 produto(s) avançaram' in m and '3 ponto(s)' in m for m in mensagens)
    )
    registrar_resultado(
        tabela_resultados, teste='2 produtos avançaram → mensagem de sucesso com contagem, redireciona pra tela principal',
        entrada=f'resumo_por_produto={resumo_por_produto}',
        esperado="mensagem cita '2 produto(s) avançaram' e '3 ponto(s)'",
        motivo='Mesmo cálculo de total_pontos da versão thread+polling do Portal do Drive — soma etapas, não conta produtos',
        obtido=f'mensagens={mensagens}',
        passou=passou,
    )
    assert passou


def test_verificar_todos_sem_avanco_mostra_mensagem_de_info(client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', lambda: ([], []))

    # Exercise:
    resposta = client.get(_url_verificar_todos(), follow=True)

    # Assert:
    from django.contrib.messages import get_messages
    mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
    passou = resposta.status_code == 200 and any('nenhum produto' in m for m in mensagens)
    registrar_resultado(
        tabela_resultados, teste='Nenhum avanço → mensagem tipo info',
        entrada='resumo_por_produto=[], sem_produto_no_banco=[]', esperado="mensagem cita 'nenhum produto'",
        motivo='Rodou até o fim, só não achou nada novo — não é erro',
        obtido=f'mensagens={mensagens}',
        passou=passou,
    )
    assert passou


def test_verificar_todos_com_pasta_orfa_mostra_aviso(client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', lambda: ([], ['789111']))

    # Exercise:
    resposta = client.get(_url_verificar_todos(), follow=True)

    # Assert:
    from django.contrib.messages import get_messages
    mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
    passou = resposta.status_code == 200 and any('1 pasta(s)' in m for m in mensagens)
    registrar_resultado(
        tabela_resultados, teste='1 EAN órfão no Drive → mensagem de aviso com a contagem',
        entrada="sem_produto_no_banco=['789111']", esperado="mensagem cita '1 pasta(s)'",
        motivo='Aviso separado da mensagem principal, mesmo padrão da versão thread+polling',
        obtido=f'mensagens={mensagens}',
        passou=passou,
    )
    assert passou


def test_verificar_todos_com_falha_mostra_erro_e_redireciona(client, tabela_resultados, monkeypatch):
    # Setup:
    def _verificar_com_falha():
        raise ConnectionError('Falha simulada de rede com o Drive')
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', _verificar_com_falha)

    # Exercise:
    resposta = client.get(_url_verificar_todos(), follow=True)

    # Assert:
    from django.contrib.messages import get_messages
    mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
    passou = resposta.status_code == 200 and any('Não foi possível conectar ao Google Drive' in m for m in mensagens)
    registrar_resultado(
        tabela_resultados, teste='Exceção na varredura completa → mensagem de erro genérica, sem 500',
        entrada='verificar_todos_no_drive lançando ConnectionError', esperado="mensagem cita 'Não foi possível conectar'",
        motivo='Mesma proteção contra falha de rede da versão thread+polling',
        obtido=f'mensagens={mensagens}',
        passou=passou,
    )
    assert passou