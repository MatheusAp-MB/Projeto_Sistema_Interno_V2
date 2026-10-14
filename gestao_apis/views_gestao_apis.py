# gestao_apis/views_gestao_apis.py

# Função Objetivo: Views da tela "Gestão de APIs" — painel de saúde das conexões externas
# (Google Drive, Mercado Livre, Sysemp, agente).
#
# * [DECISÃO, 14/10/2026] → Sem trava por usuário/permissão por enquanto (frente separada, a fazer
#   depois). Por isso a tela NÃO depende do LOGIN_REQUIRED: o que a protege hoje é (1) nenhum
#   segredo chega ao navegador, (2) o teste é POST com CSRF, (3) limite de 1 teste a cada poucos
#   segundos por conexão, (4) cada teste fica registrado com "quem" clicou.
# * [DECISÃO, 14/10/2026] → "Renovar autorização" do Google Drive (regra de Matheus: o máximo de ações possíveis em
#   tela, nada depende de terminal): 2 rotas — uma leva o navegador ao Google (POST com CSRF), a outra recebe a
#   volta (GET, protegida pelo "state" da sessão). O resultado chega à tela por um aviso de uso único na sessão.
# * [DECISÃO, 14/10/2026] → O login do Google abre numa JANELA PEQUENA (como a do "escolher conta"), não na página
#   inteira. O Google proíbe o login dentro de modal/iframe, então janela própria é o jeito certo. A janela não
#   consegue "falar" com a tela principal (o Django manda Cross-Origin-Opener-Policy: same-origin, que corta a ligação
#   entre a tela e a janela quando ela vai ao Google), por isso a tela principal PERGUNTA ao servidor (rota
#   "situacao") se a janela já terminou. Testado no Chromium: com esse cabeçalho padrão a janela ainda se fecha sozinha. Se o navegador bloquear a janela, vale o
#   caminho antigo (a própria página vai ao Google e volta).

import time
import traceback

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .funcoes_auxiliares.catalogo_conexoes import buscar_conexao, conexoes_da_empresa, unidades_de_teste
from .funcoes_auxiliares.estados import NAO_VERIFICADA, Resultado
from .funcoes_auxiliares.eventos import (
    SEGUNDOS_ENTRE_TESTES_DA_MESMA_CONEXAO,
    evento_em_memoria,
    identificar_quem,
    registrar_evento,
    testado_ha_pouco,
)
from .funcoes_auxiliares.montagem_do_painel import executar_teste, montar_painel


CHAVE_DO_AVISO_NA_SESSAO = 'gestao_apis_aviso'

# * [EXPLICAÇÃO] → Marcador de "o login do Google está aberto numa janela pequena": nasce quando a janela é aberta e vira
#                  "concluído" quando o Google devolve o navegador a ela. A tela principal consulta isto (rota "situacao").
CHAVE_DA_JANELA_NA_SESSAO = 'gestao_apis_janela'
VALIDADE_DA_JANELA_EM_SEGUNDOS = 660   # um pouco mais que os 10 minutos de validade do pedido ao Google


def _guardar_aviso(request, tipo, texto):
    # * [EXPLICAÇÃO] → Aviso de uso único: aparece na próxima abertura da tela e some (não vai na URL, então
    #                  ninguém consegue "montar" um aviso falso por link).
    request.session[CHAVE_DO_AVISO_NA_SESSAO] = {'tipo': tipo, 'texto': texto}


def _marcador_da_janela_aguardando(request):
    """True se uma janela pequena do Google foi aberta há pouco e ainda não terminou."""
    marcador = request.session.get(CHAVE_DA_JANELA_NA_SESSAO)
    if not isinstance(marcador, dict) or marcador.get('concluido'):
        return False
    try:
        return time.time() - float(marcador.get('criado_em', 0)) <= VALIDADE_DA_JANELA_EM_SEGUNDOS
    except (TypeError, ValueError):
        return False


def _responder_na_janela(request, tipo, texto, encerra=True):
    # * [EXPLICAÇÃO] → Fim do caminho da janela pequena: o resultado fica (1) no aviso de uso único, que a tela principal
    #                  mostra quando se recarregar, e (2) numa página mínima que a própria janela exibe e fecha sozinha.
    #                  encerra=False = retorno de uma janela ANTIGA que não confere com o pedido atual: só esta janela
    #                  mostra o erro; a tela principal continua esperando a janela nova (não é avisada nem recarregada).
    if encerra:
        _guardar_aviso(request, tipo, texto)
        request.session[CHAVE_DA_JANELA_NA_SESSAO] = {'concluido': True, 'criado_em': time.time()}
    resposta = render(request, 'gestao_apis/estrutura_janela_autorizacao.html', {
        'tipo': tipo,
        'texto': texto,
        'fechar_em_ms': 8000 if tipo == 'erro' else 2500,
    })
    resposta['Cache-Control'] = 'no-store'
    return resposta


@require_GET
def view_gestao_apis(request):
    # * [EXPLICAÇÃO] → Abrir a página NÃO chama nenhuma API externa: o estado vem da configuração
    #                  local + do último teste gravado. Só o botão Testar vai à internet.
    contexto = montar_painel()
    # * [EXPLICAÇÃO] → Se a pessoa recarregar a tela com a janela do Google ainda aberta, a página volta a esperar por ela
    #                  (data-gapi-janela-aguardando). Marcador já "concluído" é limpo aqui: o aviso é mostrado agora mesmo.
    contexto['janela_do_google_aguardando'] = _marcador_da_janela_aguardando(request)
    marcador = request.session.get(CHAVE_DA_JANELA_NA_SESSAO)
    if isinstance(marcador, dict) and marcador.get('concluido'):
        request.session.pop(CHAVE_DA_JANELA_NA_SESSAO, None)
    aviso = request.session.pop(CHAVE_DO_AVISO_NA_SESSAO, None)
    if isinstance(aviso, dict) and aviso.get('tipo') in ('ok', 'info', 'erro') and aviso.get('texto'):
        contexto['aviso_da_acao'] = aviso
    return render(request, 'gestao_apis/estrutura_gestao_apis.html', contexto)


@require_POST
def view_iniciar_autorizacao_google(request):
    # * [EXPLICAÇÃO] → O JS manda modo=janela quando abriu a janela pequena; sem isso, é o caminho comum (página inteira).
    em_janela = request.POST.get('modo') == 'janela'
    if em_janela:
        request.session[CHAVE_DA_JANELA_NA_SESSAO] = {'concluido': False, 'criado_em': time.time()}
    else:
        request.session.pop(CHAVE_DA_JANELA_NA_SESSAO, None)

    # * [EXPLICAÇÃO] → Import aqui dentro: se a biblioteca do Google falhar ao carregar, só este botão avisa.
    try:
        from .funcoes_auxiliares.autorizacao_google_drive import iniciar_autorizacao
        endereco_do_google, recusa = iniciar_autorizacao(request)
    except Exception:
        traceback.print_exc()
        endereco_do_google = None
        recusa = (
            'O início da autorização quebrou por um erro do próprio sistema (não é problema do Google). '
            'Veja o terminal do servidor.'
        )
    if endereco_do_google is None:
        if em_janela:
            return _responder_na_janela(request, 'erro', recusa)
        _guardar_aviso(request, 'erro', recusa)
        return redirect('gestao_apis_painel')
    return redirect(endereco_do_google)


@require_GET
def view_retorno_autorizacao_google(request):
    # * [EXPLICAÇÃO] → Lido ANTES de tratar a volta: é o marcador deixado pelo início quando abriu a janela pequena.
    em_janela = isinstance(request.session.get(CHAVE_DA_JANELA_NA_SESSAO), dict)
    try:
        from .funcoes_auxiliares.autorizacao_google_drive import concluir_autorizacao
        tipo, texto = concluir_autorizacao(request)
    except Exception:
        traceback.print_exc()
        tipo = 'erro'
        texto = (
            'A renovação quebrou por um erro do próprio sistema (não é problema do Google). Veja o terminal do '
            'servidor e use o botão Testar para ver a situação atual do login.'
        )
    if em_janela:
        # Pedido ainda na sessão = este retorno NÃO era o do pedido atual (janela antiga, endereço forjado): a janela
        # nova continua valendo e a tela principal não deve se encerrar por causa disto.
        from .funcoes_auxiliares.autorizacao_google_drive import CHAVE_DA_SESSAO
        return _responder_na_janela(request, tipo, texto, encerra=CHAVE_DA_SESSAO not in request.session)
    _guardar_aviso(request, tipo, texto)
    return redirect('gestao_apis_painel')


@require_GET
@never_cache
def view_situacao_autorizacao_google(request):
    """
    A tela principal pergunta, de tempos em tempos, se a janela pequena do Google já terminou.
    Devolve {"aguardando": bool, "concluido": bool}. Só LÊ a sessão (e limpa o marcador quando entrega o "concluído").
    """
    marcador = request.session.get(CHAVE_DA_JANELA_NA_SESSAO)
    if not isinstance(marcador, dict):
        return JsonResponse({'aguardando': False, 'concluido': False})
    if marcador.get('concluido'):
        request.session.pop(CHAVE_DA_JANELA_NA_SESSAO, None)
        return JsonResponse({'aguardando': False, 'concluido': True})
    try:
        idade = time.time() - float(marcador.get('criado_em', 0))
    except (TypeError, ValueError):
        idade = VALIDADE_DA_JANELA_EM_SEGUNDOS + 1
    if idade > VALIDADE_DA_JANELA_EM_SEGUNDOS:
        request.session.pop(CHAVE_DA_JANELA_NA_SESSAO, None)
        return JsonResponse({'aguardando': False, 'concluido': False})
    return JsonResponse({'aguardando': True, 'concluido': False})


@require_POST
def view_testar_conexao(request, conexao_id):
    conexao = buscar_conexao(conexao_id)
    if conexao is None:
        return JsonResponse({'ok': False, 'mensagem': 'Conexão desconhecida.'}, status=404)

    # * [EXPLICAÇÃO] → A tela só mostra as conexões da empresa ativa (+ compartilhadas). Se a empresa foi
    #                  trocada em outra aba e esta página ficou velha, o teste de uma conexão da outra
    #                  empresa é recusado em vez de rodar "escondido".
    if conexao.id not in {c.id for c in conexoes_da_empresa()}:
        return JsonResponse({
            'ok': False,
            'mensagem': 'Esta conexão é da outra empresa e não aparece mais nesta tela. '
                        'Recarregue a página para ver as conexões da empresa atual.',
        }, status=400)

    if not conexao.testavel:
        return JsonResponse({'ok': False, 'mensagem': conexao.motivo_sem_teste}, status=400)

    # * [EXPLICAÇÃO] → O teste do agente é feito em 2 tempos: o NAVEGADOR chama o agente do computador e manda o
    #                  resultado aqui (campo "ping"). Sem esse campo não há o que avaliar — quem chamou não foi o
    #                  botão da tela — e nada é gravado.
    if conexao.teste_no_navegador and 'ping' not in request.POST:
        return JsonResponse({
            'ok': False,
            'mensagem': 'Este teste precisa ser feito pelo botão Testar da tela, porque usa o navegador '
                        'para chamar o agente do computador. Recarregue a página e tente de novo.',
        }, status=400)

    # * [EXPLICAÇÃO] → Uma conexão com partes (Google Drive) roda TODAS as partes num clique só, cada
    #                  uma isolada das outras: se uma quebra, a outra ainda é testada e gravada.
    unidades = unidades_de_teste(conexao)

    avisos = {}
    eventos_em_memoria = {}
    if any(testado_ha_pouco(unidade_id) for unidade_id in unidades):
        avisos[conexao.id] = (
            f'Esta conexão acabou de ser testada. Aguarde {SEGUNDOS_ENTRE_TESTES_DA_MESMA_CONEXAO} '
            'segundos para testar de novo.'
        )
    else:
        quem = identificar_quem(request)
        for unidade_id in unidades:
            try:
                resultado = executar_teste(unidade_id, dados_do_navegador=request.POST)
                acao = 'teste'
            except Exception:
                # * [EXPLICAÇÃO] → Falha do NOSSO código (não da API externa). Fica separada: aparece
                #                  como "erro interno", nunca como "Com problema" da conexão.
                traceback.print_exc()
                resultado = Resultado(
                    NAO_VERIFICADA,
                    'O teste quebrou por um erro do próprio sistema (não é problema da conexão). '
                    'Veja o terminal do servidor.',
                )
                acao = 'erro_interno'
            gravou = registrar_evento(unidade_id, acao, resultado, quem)
            if not gravou:
                # * [EXPLICAÇÃO] → Banco recusou o histórico (migração não rodada?). O cartão ainda
                #                  mostra o resultado deste teste; a tabela de eventos avisa do problema.
                eventos_em_memoria[unidade_id] = evento_em_memoria(acao, resultado)

    painel = montar_painel(avisos_por_conexao=avisos, eventos_em_memoria=eventos_em_memoria)
    cartao = next(c for c in painel['cartoes'] if c['id'] == conexao.id)
    return render(request, 'gestao_apis/parciais/estrutura_parcial_resposta_teste.html', {
        'cartao': cartao,
        'faixa': painel['faixa'],
        'eventos': painel['eventos'],
        'eventos_disponiveis': painel['eventos_disponiveis'],
    })
