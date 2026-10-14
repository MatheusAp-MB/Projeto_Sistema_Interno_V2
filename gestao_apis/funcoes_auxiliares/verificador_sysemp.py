# gestao_apis/funcoes_auxiliares/verificador_sysemp.py

# Função Objetivo: Lê e testa a conexão com o Sysemp (ERP) — uma conexão POR EMPRESA, porque cada
# empresa tem a sua própria instância numerada da API (MB = /61, SV = /84) e o seu próprio token.
#
# * [EXPLICAÇÃO] → ler_local_sysemp() NÃO chama a internet: só confere se o token da empresa está no .env.
#   Nunca devolve "Funcionando" — ter o token no .env não prova que o Sysemp o aceita.
#
# * [DECISÃO, 14/10/2026] → O teste é a consulta de notas de entrada (listarManifestoNotaEntrada) de UM
#   dia (de ontem até hoje), só a 1ª página (offset 0), 1 chamada por clique. É o MESMO método e o MESMO
#   cliente que o sistema usa de verdade nos impostos de entrada, então o teste prova token, endereço da
#   empresa e método juntos. Não existe um método "ping" conhecido no Sysemp, e as consultas que conhecemos
#   carregam dados — com 1 dia só a resposta fica pequena (cada página traz no máximo ~100 registros,
#   vault: "Paginação do Endpoint Manifesto Nota Entrada"). Os registros devolvidos são só contados:
#   nada deles é guardado nem mostrado.
#
# * [IMPORTANTE] → "1 dia" = data inicial ONTEM e data final HOJE: o próprio ImpostosEntradaXML exige a data
#   inicial ANTERIOR à final (as duas iguais seriam recusadas antes de ir à internet).
# * [IMPORTANTE] → O Sysemp pode responder com sucesso HTTP e mesmo assim trazer {"status": false, ...} no
#   corpo — foi assim o "Método não Localizado" de 17/08/2026, quando o token de uma empresa foi usado no
#   endereço da outra (vault: "Sysemp Usa Instância Numerada Diferente por Empresa"). Por isso só vale como
#   "Funcionando" a resposta que traz "retorno" e não traz status false. "retorno" vazio é sucesso: é só
#   um dia sem nota de entrada.
# * [IMPORTANTE] → O token e o endereço são lidos do .env EXATAMENTE como o ApiSysemp do sistema faz
#   (sem limpar espaços, com o endereço padrão da empresa quando a variável de endereço não existe): se o
#   sistema não consegue usar o valor, o teste também não pode conseguir.
# * [IMPORTANTE] → Os textos de "O que aconteceu / Próximo passo" são sempre nossos (só o código de status vem
#   do Sysemp). A resposta REAL do Sysemp (ou o erro que ele devolveu) aparece num bloco à parte em "Ver detalhes",
#   depois de passar por preparar_resposta_para_exibir() — que tira tokens e CORTA em ~4000 caracteres, então uma
#   lista grande de notas nunca é mostrada nem guardada inteira (decisão de 14/10/2026). O token nunca é escrito
#   em lugar nenhum.
# * [EXPLICAÇÃO] → 1 tentativa só (maximo_tentativas=1): um clique manual não deve ficar preso em
#   retentativas automáticas. Num erro passageiro o cliente ainda espera o tempo de recuo (2 a 3 s, ou o
#   que o Sysemp mandar) antes de avisar.

import os
from datetime import date, timedelta

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, PREFIXO_ENV_POR_EMPRESA

from .estados import ATENCAO, COM_PROBLEMA, FUNCIONANDO, NAO_CONFIGURADA, NAO_VERIFICADA, Resultado
from .protecao_de_segredos import preparar_resposta_para_exibir

PREFIXO_POR_CONEXAO_SYSEMP = {
    'sysemp_mb': PREFIXO_ENV_POR_EMPRESA[EMPRESA_MAGAZINE],
    'sysemp_sv': PREFIXO_ENV_POR_EMPRESA[EMPRESA_SAMVALE],
}

DIAS_DO_PERIODO_DO_TESTE = 1


def _url_base_da_empresa(prefixo):
    # * [EXPLICAÇÃO] → Import dentro da função de propósito: se o pacote api_sysemp falhar ao carregar,
    #                  só os cartões do Sysemp mostram o erro — a tela abre igual.
    from api_sysemp import URL_BASE_PADRAO_POR_PREFIXO
    return os.environ.get(f'{prefixo}_SYSEMP_API_URL_BASE') or URL_BASE_PADRAO_POR_PREFIXO[prefixo]


def _periodo_do_teste():
    hoje = date.today()
    inicio = hoje - timedelta(days=DIAS_DO_PERIODO_DO_TESTE)
    return inicio, hoje


def _descrever_periodo(inicio, fim):
    return f'{inicio:%d/%m} a {fim:%d/%m}'


def ler_local_sysemp(conexao_id):
    prefixo = PREFIXO_POR_CONEXAO_SYSEMP[conexao_id]
    nome_da_variavel = f'{prefixo}_SYSEMP_API_TOKEN'
    if not os.environ.get(nome_da_variavel):
        return Resultado(
            NAO_CONFIGURADA,
            f'A variável {nome_da_variavel} não está no .env.',
            como_resolver=f'Adicionar a linha {nome_da_variavel}=... no .env.',
        )
    inicio, fim = _periodo_do_teste()
    return Resultado(
        NAO_VERIFICADA,
        'Token configurado. Falta testar a conexão com o Sysemp.',
        evidencia=(
            f'Endereço da API: {_url_base_da_empresa(prefixo)} · '
            f'Teste: notas de entrada de {DIAS_DO_PERIODO_DO_TESTE} dia (1ª página).'
        ),
    )


def _resultado_de_erro_de_status(erro, prefixo, periodo, local):
    from api_sysemp.core.excecoes import (
        ErroAutenticacaoSysemp, ErroLimiteRequisicoesSysemp, ErroNegocioSysemp, ErroRedeSysemp, ErroServidorSysemp,
    )

    status = getattr(erro, 'status_code', None)
    evidencia = f'Teste: notas de entrada ({periodo}) respondeu {status}.'

    if isinstance(erro, ErroAutenticacaoSysemp):
        return Resultado(
            COM_PROBLEMA,
            f'O Sysemp recusou o token desta empresa (status {status}): ele está errado, foi desativado ou não tem permissão.',
            como_resolver=f'Conferir o token no Sysemp, trocar {prefixo}_SYSEMP_API_TOKEN no .env e reiniciar o servidor.',
            evidencia=evidencia,
        )
    if isinstance(erro, ErroNegocioSysemp):
        return Resultado(
            ATENCAO,
            'O Sysemp recusou o pedido de teste (status 400).',
            como_resolver='Testar de novo mais tarde. Se repetir, ver o terminal do servidor.',
            evidencia=evidencia,
        )
    if isinstance(erro, ErroLimiteRequisicoesSysemp):
        return Resultado(
            ATENCAO,
            'O Sysemp limitou o uso agora (status 429): chamadas demais em pouco tempo.',
            como_resolver='Esperar alguns minutos e testar de novo.',
            evidencia=evidencia,
        )
    if isinstance(erro, ErroServidorSysemp):
        return Resultado(
            ATENCAO,
            f'O Sysemp está instável agora (status {status}).',
            como_resolver='Esperar alguns minutos e testar de novo. Não precisa mexer no token por causa disso.',
            evidencia=evidencia,
        )
    if isinstance(erro, ErroRedeSysemp):
        # * [EXPLICAÇÃO] → Inclui o tempo esgotado. Não diz nada sobre o token.
        return Resultado(
            ATENCAO,
            'A chamada de teste não chegou ao Sysemp (falha de rede ou tempo esgotado).',
            como_resolver='Conferir a internet do servidor e testar de novo.',
            evidencia=local.evidencia,
        )
    return Resultado(
        ATENCAO,
        f'O Sysemp respondeu algo inesperado ao teste (status {status}).',
        como_resolver='Testar de novo; se repetir, ver o terminal do servidor.',
        evidencia=evidencia,
    )


def _resultado_de_resposta(resposta, prefixo, url_base, periodo):
    if isinstance(resposta, dict) and resposta.get('status') is False:
        # * [EXPLICAÇÃO] → O texto desta mensagem fica de fora de propósito (ver [IMPORTANTE] acima).
        return Resultado(
            COM_PROBLEMA,
            'O Sysemp respondeu, mas recusou a consulta de teste (resposta de erro).',
            como_resolver=(
                f'Conferir se o token e o endereço são da mesma empresa ({prefixo}_SYSEMP_API_TOKEN e '
                f'{url_base}): cada empresa tem a sua instância no Sysemp (MB usa /61, SV usa /84).'
            ),
            evidencia=f'Teste: notas de entrada ({periodo}) respondeu com status false no corpo da resposta.',
        )

    formato_conhecido = (
        isinstance(resposta, dict)
        and 'retorno' in resposta
        and isinstance(resposta['retorno'], (list, type(None)))
    )
    if not formato_conhecido:
        return Resultado(
            ATENCAO,
            'O Sysemp respondeu ao teste, mas em um formato que o sistema não reconhece.',
            como_resolver='Testar de novo; se repetir, a resposta do Sysemp mudou e o sistema precisa ser ajustado.',
            evidencia=f'Teste: notas de entrada ({periodo}) respondeu sem o campo "retorno" esperado.',
        )

    quantidade = len(resposta['retorno'] or [])
    if quantidade == 0:
        detalhe = 'sem registros nesse período (normal quando não houve entrada de nota)'
    else:
        detalhe = f'{quantidade} registro(s) na 1ª página'
    return Resultado(
        FUNCIONANDO,
        'O Sysemp aceitou o token desta empresa e respondeu à consulta de notas de entrada.',
        evidencia=f'Teste: notas de entrada de {periodo} respondeu com sucesso, {detalhe}.',
    )


def testar_sysemp(conexao_id):
    local = ler_local_sysemp(conexao_id)
    if local.estado == NAO_CONFIGURADA:
        return local

    from api_sysemp.core.cliente import ClienteApiSysemp
    from api_sysemp.core.excecoes import ErroAPISysemp
    from api_sysemp.impostos_entrada_xml import ImpostosEntradaXML

    prefixo = PREFIXO_POR_CONEXAO_SYSEMP[conexao_id]
    token = os.environ.get(f'{prefixo}_SYSEMP_API_TOKEN')
    url_base = _url_base_da_empresa(prefixo)
    inicio, fim = _periodo_do_teste()
    periodo = _descrever_periodo(inicio, fim)

    cliente = ClienteApiSysemp(token, url_base=url_base, maximo_tentativas=1)
    try:
        resposta = ImpostosEntradaXML(cliente).listar_por_periodo(
            inicio.isoformat(), fim.isoformat(), offset='0', data_referencia=fim,
        )
    except ErroAPISysemp as erro:
        resultado = _resultado_de_erro_de_status(erro, prefixo, periodo, local)
        resultado.resposta = preparar_resposta_para_exibir(getattr(erro, 'corpo_resposta', ''), (token,))
        return resultado

    resultado = _resultado_de_resposta(resposta, prefixo, url_base, periodo)
    resultado.resposta = preparar_resposta_para_exibir(resposta, (token,))
    return resultado
