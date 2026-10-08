# gestao_full/funcoes_auxiliares/full_estoque_varredura.py
#
# Os botões de ATUALIZAÇÃO da tela "Full — Estoque no Full": consultar no Mercado Livre o estoque de 1 Código ML ("Atualizar"), de todos
# os Códigos de um produto ("Atualizar produto") ou de TODOS os Códigos da empresa ("Fazer varredura completa").
#
# REGRA DO MATHEUS: a tela NUNCA chama a API do ML sozinha. Nada aqui roda ao abrir, buscar, filtrar ou paginar a tela: só roda depois de um
# CLIQUE num desses botões. Quem consulta de verdade é sempre integracao_mercado_livre/servicos/consultar_full_ml.consultar_codigo — a mesma
# consulta do botão "Consultar no Mercado Livre" do Planejamento (grava 1 linha nova em ConsultaFullMercadoLivre por Código consultado).
#
# * [EXPLICAÇÃO] → A varredura completa roda numa THREAD (como a varredura de características e o Portal do Drive): o clique responde na hora
#                  e a tela pergunta o andamento de tempos em tempos. O estado (andamento, resultado) mora no CACHE, uma chave por empresa
#                  (Magazine e Samvale podem varrer ao mesmo tempo). Não há tabela nova: o que a varredura deixa de permanente são as próprias
#                  consultas que ela grava.
# * [EXPLICAÇÃO] → A varredura consulta UM Código por vez, do que mais precisa para o que menos precisa (sem número primeiro, depois o mais
#                  antigo). Para no mesmo instante se o Mercado Livre recusar o acesso (token): nenhuma chamada seguinte funcionaria.
#                  "Parar" para DEPOIS do Código que está sendo consultado — o que já foi consultado fica salvo.
# * [EXPLICAÇÃO] → Cada Código consultado grava uma linha nova no histórico de consultas (uma varredura completa = uma linha por Código).
#                  As antigas continuam guardadas; a tela só lê a mais recente de cada Código.

import threading
import time

CHAVE_CACHE_VARREDURA = 'full_estoque_varredura_{empresa}'
CHAVE_CACHE_PARAR = 'full_estoque_varredura_parar_{empresa}'

# * [EXPLICAÇÃO] → Enquanto roda, o estado é regravado a cada Código (o prazo recomeça a cada gravação). O RESULTADO final fica mais tempo
#                  guardado: quem fechou a tela durante a varredura ainda vê o resumo quando voltar.
TIMEOUT_ANDAMENTO_SEGUNDOS = 900
TIMEOUT_RESULTADO_SEGUNDOS = 6 * 3600

# * [EXPLICAÇÃO] → Se o estado diz "rodando" mas nada foi gravado há mais que isso, a thread morreu (ex.: o servidor reiniciou): a tela deixa
#                  começar outra varredura em vez de ficar travada para sempre. (Mesmo prazo da varredura de características.)
SEGUNDOS_SEM_PROGRESSO_PARA_CONSIDERAR_PARADA = 300

# Quantas vezes por segundo o andamento é gravado no cache (o navegador só pergunta a cada ~2 s; gravar a cada Código seria barulho à toa).
INTERVALO_GRAVACAO_PROGRESSO = 1.0

# * [EXPLICAÇÃO] → Falhas inesperadas SEGUIDAS (não as do Mercado Livre, que são esperadas) indicam um problema que afeta todos os Códigos
#                  (ex.: o banco caiu). Com tantas assim, a varredura para em vez de repetir o erro 900 vezes.
MAX_FALHAS_INESPERADAS_SEGUIDAS = 5

# Quantas falhas ficam guardadas para o resumo final (o resto só entra na contagem) e o tamanho máximo do texto de cada uma.
MAX_FALHAS_GUARDADAS = 200
MAX_TEXTO_FALHA = 200

MSG_ACESSO_RECUSADO = 'O Mercado Livre recusou o acesso (token inválido ou vencido).'


class CodigoOcupado(Exception):
    """O mesmo Código ML já está sendo consultado agora (outro clique, outra aba ou a varredura)."""


def _chave(empresa):
    return CHAVE_CACHE_VARREDURA.format(empresa=empresa)


def _chave_parar(empresa):
    return CHAVE_CACHE_PARAR.format(empresa=empresa)


def _plural(n, singular, plural):
    return singular if n == 1 else plural


# Função Objetivo: Consulta 1 Código ML no Mercado Livre com a trava de "este Código já está sendo consultado" (a MESMA trava do botão do
# Planejamento, para as duas telas não consultarem o mesmo Código ao mesmo tempo). Levanta CodigoOcupado se a trava já estava de pé; os erros
# da consulta (ErroConsultaFull, ErroAutenticacaoAPI...) sobem como vieram.
def consultar_com_trava(empresa, codigo, usuario, detalhes=None):
    from django.core.cache import cache

    from gestao_full.views_full import CHAVE_CACHE_TRAVA_CONSULTA, TIMEOUT_TRAVA_SEGUNDOS
    from integracao_mercado_livre.servicos.consultar_full_ml import consultar_codigo

    chave_trava = CHAVE_CACHE_TRAVA_CONSULTA.format(empresa=empresa, codigo=codigo)
    if not cache.add(chave_trava, True, timeout=TIMEOUT_TRAVA_SEGUNDOS):
        raise CodigoOcupado(codigo)
    try:
        return consultar_codigo(empresa, codigo, usuario, detalhes=detalhes)
    finally:
        cache.delete(chave_trava)


# Função Objetivo: O estado da varredura desta empresa SE ela está rodando de verdade (andamento gravado há pouco), senão None.
def varredura_em_andamento(empresa):
    from django.core.cache import cache

    estado = cache.get(_chave(empresa))
    if not estado or estado.get('status') != 'rodando':
        return None
    if time.time() - estado.get('atualizado_em', 0) > SEGUNDOS_SEM_PROGRESSO_PARA_CONSIDERAR_PARADA:
        return None
    return estado


# Função Objetivo: Começa a varredura completa (já depois da confirmação na janela): grava o estado inicial e dispara a thread, sem esperar.
# Se já há uma varredura rodando devolve o estado dela em vez de começar outra. Devolve (estado, comecou_agora).
def iniciar_varredura(empresa, usuario):
    from django.core.cache import cache

    em_andamento = varredura_em_andamento(empresa)
    if em_andamento is not None:
        return em_andamento, False

    agora = time.time()
    estado = {
        'status': 'rodando', 'rotulo': 'Preparando a varredura', 'atual': 0, 'total': None, 'codigo': '', 'parando': False,
        'consultados': 0, 'com_erro_ml': 0, 'com_erro_estoque': 0, 'com_erro_repos': 0, 'com_erro_flex': 0, 'n_falhas': 0, 'puladas': 0, 'falhas': [],
        'iniciado_em': agora, 'atualizado_em': agora, 'decorrido': 0,
    }
    cache.delete(_chave_parar(empresa))
    # Tira um resultado antigo que ninguém viu e grava o novo estado só se a chave ainda estiver livre (se outro clique chegou junto, vale o dele).
    cache.delete(_chave(empresa))
    if not cache.add(_chave(empresa), estado, timeout=TIMEOUT_ANDAMENTO_SEGUNDOS):
        return cache.get(_chave(empresa)) or estado, False

    # * [EXPLICAÇÃO] → A empresa e o usuário são capturados AQUI (na thread da requisição, onde o middleware já resolveu a empresa) e repassados:
    #                  a empresa ativa vive num threading.local() que a thread nova não herda.
    threading.Thread(target=_rodar_em_thread, args=(empresa, usuario), daemon=True).start()
    return estado, True


# Função Objetivo: Pede para a varredura parar DEPOIS do Código que está sendo consultado. Devolve o estado marcado como "parando", ou None
# se não há varredura rodando.
def pedir_parada(empresa):
    from django.core.cache import cache

    estado = varredura_em_andamento(empresa)
    if estado is None:
        return None
    cache.set(_chave_parar(empresa), True, timeout=TIMEOUT_ANDAMENTO_SEGUNDOS)
    estado = {**estado, 'parando': True, 'rotulo': 'Parando depois do Código atual'}
    cache.set(_chave(empresa), estado, timeout=TIMEOUT_ANDAMENTO_SEGUNDOS)
    return estado


# Função Objetivo: O estado para o "polling" da tela. Rodando: devolve o andamento. Terminou (ou deu erro): entrega o resultado UMA vez e o tira
# do cache, para ele não reaparecer a cada recarga. Nada no cache: {"status": "ocioso"}.
def ler_estado_varredura(empresa):
    from django.core.cache import cache

    chave = _chave(empresa)
    estado = cache.get(chave)
    if not estado:
        return {'status': 'ocioso'}
    if estado.get('status') == 'rodando':
        if varredura_em_andamento(empresa) is None:
            cache.delete(chave)
            return {'status': 'erro', 'mensagem': 'A varredura anterior parou sem terminar (provavelmente o servidor foi reiniciado). Os Códigos já '
                                                  'consultados ficaram salvos. Você pode começar outra.'}
        return estado
    cache.delete(chave)
    return estado


# Função Objetivo: Roda a varredura de verdade (na thread). Consulta os Códigos um a um, grava o andamento no cache e, no fim, o resultado.
def _rodar_em_thread(empresa, usuario):
    import traceback

    from django.core.cache import cache
    from django.db import connections

    from api_mercado_livre.core.estrutura_api.excecoes import ErroAutenticacaoAPI
    from core.empresa import definir_empresa_ativa
    from gestao_full.funcoes_auxiliares.full_estoque_ml import codigos_para_varredura
    from integracao_mercado_livre.servicos.consultar_full_ml import ErroConsultaFull, ler_detalhes_para_varredura

    # * [EXPLICAÇÃO] → Thread nova = empresa ativa vazia: define de novo (senão as consultas ao banco não sabem de qual empresa ler).
    definir_empresa_ativa(empresa)
    chave, chave_parar = _chave(empresa), _chave_parar(empresa)
    inicio = time.time()
    estado = {
        'status': 'rodando', 'rotulo': 'Consultando o Mercado Livre', 'atual': 0, 'total': 0, 'codigo': '', 'parando': False,
        'consultados': 0, 'com_erro_ml': 0, 'com_erro_estoque': 0, 'com_erro_repos': 0, 'com_erro_flex': 0, 'n_falhas': 0, 'puladas': 0, 'falhas': [],
        'iniciado_em': inicio, 'atualizado_em': inicio, 'decorrido': 0,
    }
    ultimo = {'gravado_em': 0.0}

    def gravar(novo, timeout=TIMEOUT_ANDAMENTO_SEGUNDOS):
        novo['atualizado_em'] = time.time()
        cache.set(chave, novo, timeout=timeout)

    def gravar_andamento(forcar=False):
        agora = time.time()
        if not forcar and agora - ultimo['gravado_em'] < INTERVALO_GRAVACAO_PROGRESSO:
            return
        ultimo['gravado_em'] = agora
        # Quem aperta "Parar" grava o pedido no cache; o andamento passa a dizer isso (senão a tela voltaria a "Consultando" até o próximo Código).
        estado['parando'] = bool(cache.get(chave_parar))
        estado['rotulo'] = 'Parando depois do Código atual' if estado['parando'] else 'Consultando o Mercado Livre'
        estado['decorrido'] = int(agora - inicio)   # a tela estima o "faltam cerca de X min" com isto (sem depender do relógio do navegador)
        gravar({**estado, 'falhas': list(estado['falhas'])})

    def resumo_final(interrompida):
        feitos = estado['consultados']
        total = estado['total']
        partes = [f"{feitos} de {total} {_plural(total, 'Código ML consultado', 'Códigos ML consultados')}"]
        # * [EXPLICAÇÃO] → O ML responde o estoque e a reposição (soma geral e a caminho) em chamadas separadas; cada uma pode falhar sozinha. O Código
        #                  entra nas duas contas se as duas falharam. Na tela, cada tipo tem o seu filtro.
        if estado['com_erro_repos']:
            partes.append(f"{estado['com_erro_repos']} com erro na reposição (Soma geral e A caminho; ache pelo filtro \"Reposição com erro\")")
        if estado['com_erro_estoque']:
            partes.append(f"{estado['com_erro_estoque']} com erro no estoque (ache pelo filtro \"Consulta com erro\")")
        # O estoque do depósito (Flex) vem de uma terceira chamada; se ela falha, o cartão do Código mostra o motivo no bloco "No Flex".
        if estado['com_erro_flex']:
            partes.append(f"{estado['com_erro_flex']} com erro no estoque do depósito (Flex; o motivo aparece no cartão do Código ML)")
        if estado['com_erro_ml'] and not (estado['com_erro_repos'] or estado['com_erro_estoque'] or estado['com_erro_flex']):
            partes.append(f"{estado['com_erro_ml']} com resposta de erro do Mercado Livre")
        if estado['n_falhas']:
            partes.append(f"{estado['n_falhas']} {_plural(estado['n_falhas'], 'não pôde ser consultado', 'não puderam ser consultados')}")
        if estado['puladas']:
            partes.append(f"{estado['puladas']} {_plural(estado['puladas'], 'pulado (já estava sendo consultado em outro lugar)', 'pulados (já estavam sendo consultados em outro lugar)')}")
        duracao = int(time.time() - inicio)
        tempo = f'{duracao // 60} min {duracao % 60:02d} s' if duracao >= 60 else f'{duracao} s'
        abertura = f'Varredura interrompida a pedido, após {tempo}' if interrompida else f'Varredura concluída em {tempo}'
        return f"{abertura}: {'; '.join(partes)}."

    def guardar_falha(codigo, texto):
        estado['n_falhas'] += 1
        if len(estado['falhas']) < MAX_FALHAS_GUARDADAS:
            estado['falhas'].append({'codigo': codigo, 'mensagem': str(texto)[:MAX_TEXTO_FALHA]})

    try:
        try:
            detalhes = ler_detalhes_para_varredura(empresa)
            codigos = codigos_para_varredura()
        except ErroConsultaFull as erro:
            gravar({'status': 'erro', 'mensagem': str(erro)}, TIMEOUT_RESULTADO_SEGUNDOS)
            return
        estado['total'] = len(codigos)
        gravar_andamento(forcar=True)

        seguidas, interrompida = 0, False
        for posicao, codigo in enumerate(codigos, start=1):
            if cache.get(chave_parar):
                interrompida = True
                break
            estado['atual'], estado['codigo'] = posicao, codigo
            try:
                relatorio = consultar_com_trava(empresa, codigo, usuario, detalhes=detalhes)
                estado['consultados'] += 1
                if relatorio.falhas:
                    estado['com_erro_ml'] += 1
                    # Cada falha vem escrita "ESTOQUE <código>: <erro>", "REPOS <produto do vendedor>: <erro>" ou "FLEX <produto do vendedor>: <erro>"
                    # (consultar_full_ml.consultar_codigo).
                    if any(falha.startswith('ESTOQUE') for falha in relatorio.falhas):
                        estado['com_erro_estoque'] += 1
                    if any(falha.startswith('REPOS') for falha in relatorio.falhas):
                        estado['com_erro_repos'] += 1
                    if any(falha.startswith('FLEX') for falha in relatorio.falhas):
                        estado['com_erro_flex'] += 1
                seguidas = 0
            except CodigoOcupado:
                estado['puladas'] += 1
            except ErroConsultaFull as erro:
                guardar_falha(codigo, erro)
                seguidas = 0
            except ErroAutenticacaoAPI:
                traceback.print_exc()
                gravar({'status': 'erro',
                        'mensagem': f"{MSG_ACESSO_RECUSADO} A varredura foi interrompida no Código {codigo} ({estado['consultados']} de {len(codigos)} "
                                    f"já consultados; o que foi consultado ficou salvo)."}, TIMEOUT_RESULTADO_SEGUNDOS)
                return
            except Exception as erro:
                # * [EXPLICAÇÃO] → Mantido de propósito: falha em segundo plano que passa em silêncio é impossível de investigar depois.
                traceback.print_exc()
                guardar_falha(codigo, f'Falha inesperada: {erro}')
                seguidas += 1
                if seguidas >= MAX_FALHAS_INESPERADAS_SEGUIDAS:
                    gravar({'status': 'erro',
                            'mensagem': f"A varredura parou depois de {seguidas} falhas inesperadas seguidas ({estado['consultados']} de {len(codigos)} "
                                        f"já consultados). O detalhe está no terminal do servidor."}, TIMEOUT_RESULTADO_SEGUNDOS)
                    return
            gravar_andamento(forcar=posicao == len(codigos))

        gravar({
            'status': 'concluido', 'mensagem': resumo_final(interrompida), 'interrompida': interrompida,
            'com_falhas': bool(estado['n_falhas'] or estado['com_erro_ml']), 'total': estado['total'], 'consultados': estado['consultados'],
            'com_erro_ml': estado['com_erro_ml'], 'com_erro_estoque': estado['com_erro_estoque'], 'com_erro_repos': estado['com_erro_repos'],
            'com_erro_flex': estado['com_erro_flex'], 'n_falhas': estado['n_falhas'], 'puladas': estado['puladas'], 'falhas': estado['falhas'],
            'duracao_segundos': int(time.time() - inicio),
        }, TIMEOUT_RESULTADO_SEGUNDOS)
    except Exception:
        traceback.print_exc()
        gravar({'status': 'erro', 'mensagem': 'A varredura parou por um erro inesperado. O detalhe está no terminal do servidor.'}, TIMEOUT_RESULTADO_SEGUNDOS)
    finally:
        cache.delete(chave_parar)
        connections.close_all()
