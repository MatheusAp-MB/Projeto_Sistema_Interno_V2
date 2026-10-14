# gestao_apis/funcoes_auxiliares/verificador_demais_conexoes.py

# Função Objetivo: Leitura e teste das conexões que não têm um arquivo próprio: hoje, só o Agente de
# automação (o programa que roda no computador de quem faz as postagens no Mercado Livre).
#
# * [EXPLICAÇÃO] → ler_local_agente() NÃO chama nada: só confere se o AGENTE_TOKEN existe no .env do
#   sistema. Nunca devolve "Funcionando" — ter a chave no .env não prova que o agente está aberto.
#
# * [DECISÃO, 14/10/2026] → O servidor do sistema NÃO consegue chamar o agente: ele só escuta no próprio
#   computador (127.0.0.1:5678), e o servidor pode estar na nuvem. Por isso o teste é feito em 2 tempos:
#     1) o NAVEGADOR de quem clicou chama GET http://127.0.0.1:5678/ping (mesmo jeito que o sistema já usa para
#        mandar o agente executar postagens, replicações e verificações);
#     2) o agente, por sua vez, chama o sistema com a chave dele (GET /api/agente/ping/) e conta o que
#        aconteceu na resposta;
#     3) o navegador manda essa resposta para cá (campo "ping") e AQUI sai o resultado.
#   Assim um "Funcionando" prova as duas pontas: o agente está aberto neste computador E o sistema aceita
#   a chave dele (a mesma que ele usa nas postagens de verdade).
#
# * [IMPORTANTE] → O campo "ping" vem do NAVEGADOR: nada dele é confiado. Só entram valores de uma lista fechada,
#   com tipo e tamanho conferidos; o resto é descartado. Os textos de "O que aconteceu / Próximo passo" são sempre
#   nossos; a resposta real do agente aparece no bloco "Resposta real da API" (já sem tokens).
# * [IMPORTANTE] → O resultado vale para o COMPUTADOR de quem clicou: o agente só existe onde foi instalado.
#   Quem testa num computador sem o agente vê "Atenção" — o histórico guarda "quem" testou.

import json
import re

from django.conf import settings

from .estados import ATENCAO, COM_PROBLEMA, FUNCIONANDO, NAO_CONFIGURADA, NAO_VERIFICADA, Resultado
from .protecao_de_segredos import preparar_resposta_para_exibir

TAMANHO_MAXIMO_DO_PING = 2000
ESPERA_DO_NAVEGADOR_EM_SEGUNDOS = 12  # tem que bater com ESPERA_MAXIMA_DO_PING_MS do script_gestao_apis.js

EVIDENCIA_DO_TESTE = (
    'Teste: o navegador de quem clicou chama o agente (127.0.0.1:5678) e o agente chama o sistema com a chave dele.'
)

_PADRAO_ENDERECO_DO_SERVIDOR = re.compile(r'^https?://[A-Za-z0-9.\-:\[\]]{1,120}(/[A-Za-z0-9._~\-/]{0,60})?$')
_PADRAO_NOME_DE_ERRO_DE_REDE = re.compile(r'^[A-Za-z]{1,60}$')
_MOTIVOS_DE_FALHA_DO_NAVEGADOR = ('tempo_esgotado', 'sem_resposta')


def ler_local_agente():
    if not settings.AGENTE_TOKEN:
        return Resultado(
            NAO_CONFIGURADA,
            'A variável AGENTE_TOKEN não está no .env.',
            como_resolver='Definir AGENTE_TOKEN no .env do sistema e o mesmo valor no agente.',
        )
    return Resultado(
        NAO_VERIFICADA,
        'Chave configurada no sistema. Falta testar o agente deste computador.',
        evidencia=EVIDENCIA_DO_TESTE,
    )


def _inteiro(valor):
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _limpar_corpo_do_agente(corpo):
    """Só os campos conhecidos, com tipo e tamanho conferidos. Devolve None se não é a resposta de um agente."""
    if corpo.get('status') != 'ok':
        return None
    limpo = {'status': 'ok'}
    if isinstance(corpo.get('ocupado'), bool):
        limpo['ocupado'] = corpo['ocupado']
    servidor = corpo.get('servidor')
    chave = settings.AGENTE_TOKEN
    if isinstance(servidor, str) and _PADRAO_ENDERECO_DO_SERVIDOR.match(servidor) and not (chave and chave in servidor):
        limpo['servidor'] = servidor
    if isinstance(corpo.get('servidor_respondeu'), bool):
        limpo['servidor_respondeu'] = corpo['servidor_respondeu']
    status_do_servidor = _inteiro(corpo.get('status_http_servidor'))
    if status_do_servidor is not None and 100 <= status_do_servidor <= 599:
        limpo['status_http_servidor'] = status_do_servidor
    erro = corpo.get('erro_de_rede')
    if isinstance(erro, str) and _PADRAO_NOME_DE_ERRO_DE_REDE.match(erro):
        limpo['erro_de_rede'] = erro
    return limpo


def _ler_ping_do_navegador(texto):
    """Devolve o ping já limpo, ou None se o texto não tem o formato esperado."""
    if not isinstance(texto, str) or not texto or len(texto) > TAMANHO_MAXIMO_DO_PING:
        return None
    try:
        bruto = json.loads(texto)
    except ValueError:
        return None
    if not isinstance(bruto, dict):
        return None

    if bruto.get('alcancou') is not True:
        motivo = bruto.get('motivo')
        return {'alcancou': False, 'motivo': motivo if motivo in _MOTIVOS_DE_FALHA_DO_NAVEGADOR else 'sem_resposta'}

    status = _inteiro(bruto.get('status'))
    if status is None or not 100 <= status <= 599:
        return None
    corpo = bruto.get('corpo')
    return {'alcancou': True, 'status': status, 'corpo': _limpar_corpo_do_agente(corpo) if isinstance(corpo, dict) else None}


def _resultado_do_ping(ping):
    if not ping['alcancou']:
        if ping['motivo'] == 'tempo_esgotado':
            return Resultado(
                ATENCAO,
                f'O agente não respondeu ao teste a tempo (mais de {ESPERA_DO_NAVEGADOR_EM_SEGUNDOS} segundos).',
                como_resolver='Esperar um pouco e testar de novo. Se repetir, fechar o agente e abrir de novo.',
                evidencia=EVIDENCIA_DO_TESTE,
            )
        return Resultado(
            ATENCAO,
            'O navegador não conseguiu falar com o agente neste computador (ele está fechado, é uma versão '
            'antiga sem o teste, ou o navegador bloqueou a conversa).',
            como_resolver=(
                'Abrir o agente (ícone na bandeja do Windows). Se ele já estava aberto, gerar o .exe de novo com '
                'a versão atual e abrir. O agente só existe nos computadores onde foi instalado.'
            ),
            evidencia=EVIDENCIA_DO_TESTE,
        )

    status = ping['status']
    corpo = ping['corpo']
    if status == 404:
        return Resultado(
            ATENCAO,
            'Algo respondeu na porta do agente, mas não conhece o teste: é uma versão antiga do agente.',
            como_resolver='Gerar o .exe do agente de novo com a versão atual e abrir.',
            evidencia=f'{EVIDENCIA_DO_TESTE} Resposta: status 404.',
        )
    if status != 200:
        return Resultado(
            ATENCAO,
            f'O agente respondeu ao teste com erro (status {status}).',
            como_resolver='Testar de novo. Se repetir, ver o arquivo de log do agente (agente_log_...txt, na pasta dele).',
            evidencia=f'{EVIDENCIA_DO_TESTE} Resposta: status {status}.',
        )
    if corpo is None:
        return Resultado(
            ATENCAO,
            'O agente respondeu ao teste, mas em um formato que o sistema não reconhece.',
            como_resolver='Gerar o .exe do agente de novo com a versão atual e testar.',
            evidencia=EVIDENCIA_DO_TESTE,
        )

    servidor = corpo.get('servidor')
    endereco = f' Endereço do sistema que o agente usa: {servidor}.' if servidor else ''
    status_do_servidor = corpo.get('status_http_servidor')

    if corpo.get('servidor_respondeu') is not True:
        erro = corpo.get('erro_de_rede')
        detalhe = f' Erro de rede: {erro}.' if erro else ''
        return Resultado(
            ATENCAO,
            'O agente está aberto, mas não conseguiu falar com o sistema (sem internet ou endereço errado).',
            como_resolver=(
                'Conferir a internet deste computador e a linha SERVIDOR= do agente_config.env '
                '(ela precisa ser o endereço do sistema).'
            ),
            evidencia=f'{EVIDENCIA_DO_TESTE}{endereco}{detalhe}',
        )
    if status_do_servidor in (401, 403):
        return Resultado(
            COM_PROBLEMA,
            f'O sistema recusou a chave do agente (status {status_do_servidor}): o TOKEN do agente_config.env '
            'não é o mesmo AGENTE_TOKEN do .env do sistema.',
            como_resolver=(
                'Copiar o valor de AGENTE_TOKEN do .env do sistema para a linha TOKEN= do agente_config.env, '
                'abrir o agente de novo e testar.'
            ),
            evidencia=f'{EVIDENCIA_DO_TESTE}{endereco}',
        )
    if status_do_servidor == 200:
        tarefa = ' O agente está executando uma tarefa agora.' if corpo.get('ocupado') else ''
        return Resultado(
            FUNCIONANDO,
            'O agente deste computador respondeu e o sistema aceitou a chave dele.',
            evidencia=f'{EVIDENCIA_DO_TESTE}{endereco}{tarefa}',
        )
    if status_do_servidor == 400:
        return Resultado(
            ATENCAO,
            'O sistema recusou o pedido de teste do agente (status 400).',
            como_resolver='Testar de novo. Se repetir, ver o terminal do servidor.',
            evidencia=f'{EVIDENCIA_DO_TESTE}{endereco}',
        )
    return Resultado(
        ATENCAO,
        f'O sistema respondeu ao agente com erro (status {status_do_servidor}).',
        como_resolver='Esperar alguns minutos e testar de novo.',
        evidencia=f'{EVIDENCIA_DO_TESTE}{endereco}',
    )


def testar_agente(dados_do_navegador):
    local = ler_local_agente()
    if local.estado == NAO_CONFIGURADA:
        return local

    ping = _ler_ping_do_navegador(dados_do_navegador.get('ping'))
    if ping is None:
        return Resultado(
            ATENCAO,
            'O navegador mandou o resultado do teste do agente em um formato que o sistema não reconhece.',
            como_resolver='Recarregar a página e testar de novo.',
            evidencia=EVIDENCIA_DO_TESTE,
        )

    resultado = _resultado_do_ping(ping)
    if ping['alcancou'] and ping['corpo']:
        resultado.resposta = preparar_resposta_para_exibir(ping['corpo'], (settings.AGENTE_TOKEN,))
    return resultado
