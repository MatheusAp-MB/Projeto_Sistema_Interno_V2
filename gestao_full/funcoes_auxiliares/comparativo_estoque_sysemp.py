# gestao_full/funcoes_auxiliares/comparativo_estoque_sysemp.py

# Função Objetivo: A COLETA do estoque na API Sysemp para o Comparativo de estoque (debug): o botão "Coletar do Sysemp" da tela. Busca todas as
# páginas do método listarAnaliseEstoqueFull (via ApiSysemp.analise_estoque_full) e guarda o resultado CRU, para a tela comparar sem chamar a
# API de novo a cada clique.
#
# REGRA: nada aqui roda ao abrir, buscar, filtrar ou paginar a tela. Só roda depois de um CLIQUE em "Coletar do Sysemp". A Sysemp só permite
# LEITURA (ver "Sysemp So Permite Acesso de Leitura..." no vault): este método só lê.
#
# * [EXPLICAÇÃO] → Mesmo desenho da varredura do Estoque no Full (full_estoque_varredura.py): a coleta roda numa THREAD, o clique responde na
#                  hora e a tela pergunta o andamento de tempos em tempos. Três itens no CACHE do servidor, todos por empresa (Magazine e Samvale
#                  não se misturam): o ESTADO (andamento / resultado), o pedido de PARAR e a COLETA em si (as linhas cruas). Não há tabela
#                  nova: dado cru de API não é gravado no banco (decisão do Matheus). O cache é a memória do servidor: reiniciar o servidor
#                  apaga a coleta, e basta clicar de novo.
# * [EXPLICAÇÃO] → A coleta anterior só é SUBSTITUÍDA quando a nova termina (completa ou parada por um motivo anormal, como a API repetir
#                  páginas — isso fica registrado na própria coleta). Erro ou "Parar" no meio mantêm a coleta anterior intacta.
# * [EXPLICAÇÃO] → A thread não herda a empresa ativa (ela vive num threading.local do middleware). Aqui isso não importa: a empresa é
#                  passada EXPLÍCITA ao ApiSysemp e a thread não lê o banco.

import threading
import time

from django.utils import timezone

from api_sysemp.analise_estoque_full import (
    MAXIMO_PAGINAS,
    MOTIVO_INTERROMPIDA,
    MOTIVO_LIMITE_DE_PAGINAS,
    MOTIVO_PAGINA_REPETIDA,
    MOTIVO_RESPOSTA_INESPERADA,
)

CHAVE_CACHE_ESTADO = 'comparativo_estoque_sysemp_estado_{empresa}'
CHAVE_CACHE_PARAR = 'comparativo_estoque_sysemp_parar_{empresa}'
CHAVE_CACHE_COLETA = 'comparativo_estoque_sysemp_coleta_{empresa}'

# * [EXPLICAÇÃO] → O estado é regravado a cada página (o prazo recomeça a cada gravação). O RESULTADO final fica mais tempo guardado: quem
#                  fechou a tela durante a coleta ainda vê o resumo quando voltar. A COLETA em si fica 24 h (é o que a tela compara).
TIMEOUT_ANDAMENTO_SEGUNDOS = 1800
TIMEOUT_RESULTADO_SEGUNDOS = 6 * 3600
TIMEOUT_COLETA_SEGUNDOS = 24 * 3600

# * [EXPLICAÇÃO] → Uma página pode levar bem mais que 30 s (a API é pesada: o prazo de cada chamada é de 120 s, com até 4 tentativas e espera
#                  entre elas). Só depois de 10 minutos sem nenhuma página nova o estado "rodando" é considerado de uma thread morta (ex.:
#                  o servidor reiniciou) e a tela deixa começar outra coleta.
SEGUNDOS_SEM_PROGRESSO_PARA_CONSIDERAR_PARADA = 600

MAX_TEXTO_ERRO = 400

TEXTO_DO_FIM_ANORMAL = {
    MOTIVO_PAGINA_REPETIDA: 'a API devolveu de novo linhas que já tinham vindo (ela parece ignorar o offset da paginação)',
    MOTIVO_LIMITE_DE_PAGINAS: f'chegou ao limite de segurança de {MAXIMO_PAGINAS} páginas',
    MOTIVO_RESPOSTA_INESPERADA: 'a API respondeu fora do formato esperado',
}


def _chave_estado(empresa):
    return CHAVE_CACHE_ESTADO.format(empresa=empresa)


def _chave_parar(empresa):
    return CHAVE_CACHE_PARAR.format(empresa=empresa)


def _chave_coleta(empresa):
    return CHAVE_CACHE_COLETA.format(empresa=empresa)


def _plural(n, singular, plural):
    return singular if n == 1 else plural


# Função Objetivo: A coleta guardada desta empresa (dict com as linhas cruas e como foi a coleta), ou None se nunca coletou (ou o servidor reiniciou).
# Chaves: linhas, coletado_em, paginas, tamanhos_das_paginas, completa, motivo_do_fim, detalhe_do_fim, duracao_segundos.
def ler_coleta(empresa):
    from django.core.cache import cache

    return cache.get(_chave_coleta(empresa))


# Função Objetivo: O estado da coleta desta empresa SE ela está rodando de verdade (andamento gravado há pouco), senão None.
def coleta_em_andamento(empresa):
    from django.core.cache import cache

    estado = cache.get(_chave_estado(empresa))
    if not estado or estado.get('status') != 'rodando':
        return None
    if time.time() - estado.get('atualizado_em', 0) > SEGUNDOS_SEM_PROGRESSO_PARA_CONSIDERAR_PARADA:
        return None
    return estado


# Função Objetivo: Começa a coleta (depois do clique): grava o estado inicial e dispara a thread, sem esperar. Se já há uma coleta rodando,
# devolve o estado dela em vez de começar outra. Devolve (estado, comecou_agora).
def iniciar_coleta(empresa):
    from django.core.cache import cache

    em_andamento = coleta_em_andamento(empresa)
    if em_andamento is not None:
        return em_andamento, False

    agora = time.time()
    estado = {'status': 'rodando', 'rotulo': 'Chamando a API Sysemp', 'paginas': 0, 'linhas': 0, 'parando': False,
              'iniciado_em': agora, 'atualizado_em': agora, 'decorrido': 0}
    cache.delete(_chave_parar(empresa))
    # Tira um resultado antigo que ninguém viu e grava o novo estado só se a chave ainda estiver livre (se outro clique chegou junto, vale o dele).
    cache.delete(_chave_estado(empresa))
    if not cache.add(_chave_estado(empresa), estado, timeout=TIMEOUT_ANDAMENTO_SEGUNDOS):
        return cache.get(_chave_estado(empresa)) or estado, False

    threading.Thread(target=_rodar_em_thread, args=(empresa,), daemon=True).start()
    return estado, True


# Função Objetivo: Pede para a coleta parar ANTES da próxima página. Devolve o estado marcado como "parando", ou None se não há coleta rodando.
def pedir_parada(empresa):
    from django.core.cache import cache

    estado = coleta_em_andamento(empresa)
    if estado is None:
        return None
    cache.set(_chave_parar(empresa), True, timeout=TIMEOUT_ANDAMENTO_SEGUNDOS)
    estado = {**estado, 'parando': True, 'rotulo': 'Parando depois da página atual'}
    cache.set(_chave_estado(empresa), estado, timeout=TIMEOUT_ANDAMENTO_SEGUNDOS)
    return estado


# Função Objetivo: O estado para o "polling" da tela. Rodando: devolve o andamento. Terminou (ou deu erro): entrega o resultado UMA vez e o tira
# do cache, para ele não reaparecer a cada recarga. Nada no cache: {"status": "ocioso"}.
def ler_estado(empresa):
    from django.core.cache import cache

    chave = _chave_estado(empresa)
    estado = cache.get(chave)
    if not estado:
        return {'status': 'ocioso'}
    if estado.get('status') == 'rodando':
        if coleta_em_andamento(empresa) is None:
            cache.delete(chave)
            return {'status': 'erro', 'mensagem': 'A coleta anterior parou sem terminar (provavelmente o servidor foi reiniciado). Você pode começar outra.'}
        return estado
    cache.delete(chave)
    return estado


# Função Objetivo: A frase de "quanto tempo levou" ("42 s", "1 min 05 s").
def _texto_do_tempo(segundos):
    return f'{segundos // 60} min {segundos % 60:02d} s' if segundos >= 60 else f'{segundos} s'


# Função Objetivo: Roda a coleta de verdade (na thread): busca as páginas, grava o andamento e, no fim, o resultado e a coleta.
def _rodar_em_thread(empresa):
    import traceback

    from django.core.cache import cache

    from api_sysemp import ApiSysemp
    from api_sysemp.core.excecoes import ErroAPISysemp, ErroAutenticacaoSysemp

    chave, chave_parar = _chave_estado(empresa), _chave_parar(empresa)
    inicio = time.time()
    estado = {'status': 'rodando', 'rotulo': 'Chamando a API Sysemp', 'paginas': 0, 'linhas': 0, 'parando': False,
              'iniciado_em': inicio, 'atualizado_em': inicio, 'decorrido': 0}

    def gravar(novo, timeout=TIMEOUT_ANDAMENTO_SEGUNDOS):
        novo['atualizado_em'] = time.time()
        cache.set(chave, novo, timeout=timeout)

    def deve_parar():
        return bool(cache.get(chave_parar))

    def ao_avancar_pagina(numero, tamanho, total_de_linhas):
        estado['paginas'], estado['linhas'] = numero, total_de_linhas
        estado['decorrido'] = int(time.time() - inicio)
        estado['parando'] = deve_parar()
        estado['rotulo'] = 'Parando depois da página atual' if estado['parando'] else 'Coletando as páginas da API Sysemp'
        gravar({**estado})

    try:
        # Ponto de entrada único da API: resolve token e URL da empresa sozinho (RuntimeError se o token não está no .env).
        coleta = ApiSysemp(empresa=empresa).analise_estoque_full.listar_tudo(ao_avancar_pagina, deve_parar)
        duracao = int(time.time() - inicio)

        if coleta.motivo_do_fim == MOTIVO_INTERROMPIDA:
            gravar({'status': 'concluido', 'interrompida': True, 'completa': False, 'duracao_segundos': duracao,
                    'mensagem': f'Coleta interrompida a pedido, após {_texto_do_tempo(duracao)} ({coleta.paginas} '
                                f'{_plural(coleta.paginas, "página", "páginas")}). A coleta anterior foi mantida.'}, TIMEOUT_RESULTADO_SEGUNDOS)
            return

        cache.set(_chave_coleta(empresa), {
            'linhas': coleta.linhas, 'coletado_em': timezone.now(), 'paginas': coleta.paginas,
            'tamanhos_das_paginas': coleta.tamanhos_das_paginas, 'completa': coleta.completa,
            'motivo_do_fim': coleta.motivo_do_fim, 'detalhe_do_fim': coleta.detalhe_do_fim, 'duracao_segundos': duracao,
        }, timeout=TIMEOUT_COLETA_SEGUNDOS)

        mensagem = (f'Coleta concluída em {_texto_do_tempo(duracao)}: {len(coleta.linhas)} {_plural(len(coleta.linhas), "linha", "linhas")} '
                    f'em {coleta.paginas} {_plural(coleta.paginas, "página", "páginas")}.')
        if not coleta.completa:
            mensagem += f' ATENÇÃO: a coleta parou antes do fim — {TEXTO_DO_FIM_ANORMAL.get(coleta.motivo_do_fim, coleta.motivo_do_fim)}.'
            if coleta.detalhe_do_fim:
                mensagem += f' ({coleta.detalhe_do_fim})'
        gravar({'status': 'concluido', 'interrompida': False, 'completa': coleta.completa, 'duracao_segundos': duracao,
                'mensagem': mensagem}, TIMEOUT_RESULTADO_SEGUNDOS)
    except ErroAutenticacaoSysemp as erro:
        traceback.print_exc()
        gravar({'status': 'erro', 'mensagem': f'A Sysemp recusou o acesso (token inválido ou sem permissão): {str(erro)[:MAX_TEXTO_ERRO]}'},
               TIMEOUT_RESULTADO_SEGUNDOS)
    except (ErroAPISysemp, RuntimeError, ValueError) as erro:
        # Falha esperada de comunicação (rede, limite, servidor, método não liberado) ou de configuração (token ausente no .env).
        traceback.print_exc()
        gravar({'status': 'erro', 'mensagem': f'Não consegui coletar o estoque da Sysemp: {str(erro)[:MAX_TEXTO_ERRO]}'}, TIMEOUT_RESULTADO_SEGUNDOS)
    except Exception:
        # * [EXPLICAÇÃO] → Mantido de propósito: falha em segundo plano que passa em silêncio é impossível de investigar depois.
        traceback.print_exc()
        gravar({'status': 'erro', 'mensagem': 'A coleta parou por um erro inesperado. O detalhe está no terminal do servidor.'},
               TIMEOUT_RESULTADO_SEGUNDOS)
    finally:
        cache.delete(chave_parar)
