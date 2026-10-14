# gestao_apis/views_gestao_apis.py

# Função Objetivo: Views da tela "Gestão de APIs" — painel de saúde das conexões externas
# (Google Drive, Mercado Livre, Sysemp, agente).
#
# * [DECISÃO, 14/10/2026] → Sem trava por usuário/permissão por enquanto (frente separada, a fazer
#   depois). Por isso a tela NÃO depende do LOGIN_REQUIRED: o que a protege hoje é (1) nenhum
#   segredo chega ao navegador, (2) o teste é POST com CSRF, (3) limite de 1 teste a cada poucos
#   segundos por conexão, (4) cada teste fica registrado com "quem" clicou.

import traceback

from django.http import JsonResponse
from django.shortcuts import render
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


@require_GET
def view_gestao_apis(request):
    # * [EXPLICAÇÃO] → Abrir a página NÃO chama nenhuma API externa: o estado vem da configuração
    #                  local + do último teste gravado. Só o botão Testar vai à internet.
    return render(request, 'gestao_apis/estrutura_gestao_apis.html', montar_painel())


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
                resultado = executar_teste(unidade_id)
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
