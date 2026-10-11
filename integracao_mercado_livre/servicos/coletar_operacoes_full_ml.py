# integracao_mercado_livre/servicos/coletar_operacoes_full_ml.py
# ============================================================================================================================
# AVISO — ENDPOINT DE OPERAÇÕES DO FULL ABANDONADO PARA O HISTÓRICO DE VENDAS (decisão do Matheus, 10/10/2026, 20:04)
# ============================================================================================================================
# Este código usa GET /stock/fulfillment/operations/search. Ele FUNCIONA (90 dias de 1 SKU = 3 Códigos ML foram coletados),
# mas foi ABANDONADO: o endpoint é instável e a necessidade é rodar para MAIS DE MIL SKUs. NÃO APAGUE — guarda o que foi
# aprendido. Notas completas no vault: 05_Integracao_Mercado_Livre/Historico_de_Vendas/ (descoberta, decisão, dúvida, checkpoint).
#
# PROBLEMAS OBSERVADOS (10/10/2026, dado real, conta Magazine, 1 SKU = 3 Códigos ML):
#  1) 429 FREQUENTE: 8 de 25 chamadas na sondagem (18:33-18:38) e 34 de 51 tentativas nas 3 rodadas reais do coletor (19:43-19:46).
#     Corpo: {"message": "Entity operation_kvs_ds_v2__fbm_seller_stock_operations is over quota", "error": "over_quota"}
#     NÃO é o texto "requests por minuto" da doc: cita uma entidade interna; o ESCOPO da cota é DESCONHECIDO (app, vendedor, global?).
#  2) SEM PISTA DE QUANDO TENTAR DE NOVO: nenhuma resposta traz Retry-After nem cabeçalho de limite.
#  3) PESO E ESPAÇAMENTO NÃO MUDAM A TAXA: chamada leve (1 Código, limit=1) 3/8 x pesada (3 Códigos, limit=1000) 2/8 com 429;
#     esperar 15 s entre as chamadas ainda deu 5 de 16 primeiras páginas com 429. Os 429 vêm em rajadas e a taxa variou no tempo
#     (32% às 18:33 x 67% às 19:43) — a causa é desconhecida.
#  4) SCROLL FRÁGIL: repetir o MESMO scroll depois de um 429 costuma virar 404 {"message": "Operation not found"} (2 de 2 nas
#     rodadas reais; 1 de 3 passou na sondagem). O coletor recomeça a janela e descarta as linhas repetidas (2000 na rodada de 90 dias).
#  5) Chamadas SEM scroll: 13 de 15 terminaram em 200 nas rodadas reais; 1 esgotou as 5 tentativas com 429 e 1 foi interrompida.
#  6) 120 e 150 dias NÃO foram testados (Ctrl+C durante a espera de 60 s, antes da parte antiga): só 90 dias foram validados.
#  7) A profundidade do histórico NÃO é a causa: o 429 apareceu também na janela dos 7 dias mais recentes (11 de 14 tentativas).
#
# NUNCA TESTADO: máximo de Códigos ML por chamada; omitir "type" (1 chamada em vez de 4 por janela); dividir a janela por data até
# caber em 1000 operações (sem scroll); se o horário muda a taxa. Não há contato com o Mercado Livre por ora.
#
# CAMINHO NOVO: GET /orders/search (ver o checkpoint 'Checkpoint - Historico de Vendas e Calendario de Vendas' no vault).
# Textos mais abaixo que dizem que o limite é "por minuto" ou que o 429 "passa depois de esperar" foram escritos ANTES desses
# testes: valem os fatos deste aviso.
#
# ESCOPO: o coletor inteiro (janelas de 46 dias, 4 tipos, esperas de 60 s, recomeço por scroll 404, cobertura) foi desenhado em
# volta desses problemas. Fica como está, sem uso previsto. As esperas e o recomeço de scroll NÃO resolveram o 429: só o contornaram.
# ============================================================================================================================
#
# Função Objetivo: Coletor das operações de estoque do Full (GET /stock/fulfillment/operations/search): busca no Mercado Livre as
# operações de 1 ou mais Códigos ML, limpa e tipa cada uma e grava em OperacaoFullMercadoLivre — a ÚNICA origem das "vendas do Full
# por dia". Fluxo: API -> este serviço (limpa e tipa) -> banco -> a tela só LÊ o banco. Nenhum JSON no meio, e nada do JSON cru da
# API é guardado.
#
# REGRA DO MATHEUS: NUNCA requisição automática à API. Este serviço só é chamado por comando manual (coletar_operacoes_full) ou por
# botão — nunca por tela aberta, rotina agendada ou importação.
#
# * [EXPLICAÇÃO] → Como a busca funciona (doc "Envios Fulfillment" + o que a investigação de 10/10/2026 mostrou com dado real):
#   1) Janelas: a doc limita cada chamada a 60 dias e o ML só guarda 12 meses. A busca é fatiada em janelas de 46 dias (folga sobre
#      o limite; o valor que rodou bem na investigação), e o date_to de cada janela é EXCLUSIVO.
#   2) Tipos: cada janela é buscada 1 tipo por vez — os 4 do model (venda, cancelamento, não entregue, devolução). Uma busca sem
#      resultado volta como 200 com total 0 (visto com dado real em SALE_RETURN); por isso um 404 NÃO é tratado como "vazio".
#   3) Paginação: até 1000 operações por página; o "scroll" (expira em 5 minutos) pede a página seguinte. Se uma página de scroll
#      responde 404 (visto com dado real, logo depois de duas respostas 429 na mesma página), a janela recomeça do zero, sem
#      scroll, e as operações repetidas são descartadas pelo id (no máximo 3 recomeços por janela).
#   4) Pausa de 1 segundo entre as chamadas (a API responde 429 "por minuto"; o cliente já espera e tenta de novo).
#   4b) Paciência no 429: a doc diz que o limite deste endpoint é por minuto, mas não diz o número, e o ML não manda Retry-After. O
#      cliente compartilhado (chamar_api) tenta 5 vezes, com backoff de uns 33 s no total, e desiste com o erro "Número máximo de
#      tentativas (5) esgotado" — texto que só nasce de 429 esgotado. Quando ele chega, o coletor espera ESPERA_APOS_429_S (60 s, a
#      unidade do limite) e repete a MESMA página, até MAX_ESPERAS_429_POR_CHAMADA vezes (trava provisória: sem ela, uma cota
#      travada deixaria a coleta esperando para sempre). Se o scroll vencer durante a espera (ele expira em 5 minutos), o 404 que
#      volta cai no recomeço da janela (ponto 3). O resumo mostra quantas esperas aconteceram: é a medida real do limite.
#   5) Cobertura: o que foi buscado fica registrado POR Código ML (CoberturaOperacaoFullMercadoLivre) e avança JANELA POR JANELA:
#      assim que os 4 tipos de uma janela terminam bem (todas as páginas), a cobertura daquela janela é gravada. Busca incompleta
#      (página que falhou, resposta parcial, menos linhas do que a API anunciou, limite de páginas, 429 que não passou) é FALHA
#      DAQUELA janela: a cobertura não anda além da última janela concluída e o motivo fica registrado. A próxima coleta recomeça
#      de onde a cobertura parou (menos a margem de segurança). As linhas já gravadas ficam (reler não duplica: o id da operação
#      é único).
#   5b) Histórico: o padrão da 1ª busca é DIAS_PRIMEIRA_CARGA (90 dias) e o comando aceita --dias (até 360). Com um --dias maior que
#      a cobertura que o Código já tem, o coletor busca só a parte mais ANTIGA que falta (de hoje menos --dias até o início da
#      cobertura), depois da parte nova. Essa parte é fatiada de trás para frente, a partir da borda da cobertura: cada janela
#      concluída encosta na anterior, então uma falha no meio nunca deixa buraco. Se a parte nova de um Código falhou nesta rodada,
#      a parte antiga dele não é tentada (a API já está recusando; insistir só gasta mais cota).
#   6) Limpeza: cada operação vira os campos do model. Operação sem id, Código, data ou quantidade, de tipo que não coletamos ou
#      de Código que não foi pedido é DESCARTADA e CONTADA — nunca vira "0 unidade" (ausente não é zero).
#   7) Uma operação já gravada nunca é alterada: ela é um fato do passado; se a busca traz o mesmo id de novo, é ignorado.
#
# O 401 (acesso recusado) interrompe tudo: nenhuma chamada seguinte funcionaria.

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone as fuso

from django.core.cache import cache
from django.utils import timezone

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.excecoes import ErroAutenticacaoAPI
from core.empresa import definir_empresa_ativa
from integracao_mercado_livre.servicos.buscar_detalhes import _caminho_pasta_logs
from mercado_livre.models import CoberturaOperacaoFullMercadoLivre, OperacaoFullMercadoLivre

# Os tipos vêm do próprio model (um dono só para "quais tipos de operação guardamos").
TIPOS_COLETADOS = [tipo.value for tipo in OperacaoFullMercadoLivre.Tipo]

DIAS_POR_JANELA_API = 46          # a doc limita a 60 dias por chamada
LIMITE_POR_PAGINA = 1000          # máximo da doc
MAX_PAGINAS_POR_JANELA = 30       # trava de segurança (30 x 1000 operações numa janela de 1 tipo)
MAX_REINICIOS_POR_JANELA = 3
PAUSA_ENTRE_CHAMADAS_S = 1.0
ESPERA_APOS_429_S = 60            # a doc diz "por minuto"; o ML não manda Retry-After neste endpoint
MAX_ESPERAS_429_POR_CHAMADA = 3   # trava provisória (valor a ajustar com o que o resumo mostrar)
TEXTO_429_ESGOTADO = 'Número máximo de tentativas'   # início do erro do chamar_api quando as tentativas por 429 acabam
TAMANHO_LOTE_CONSULTA_IDS = 1000
TAMANHO_LOTE_GRAVACAO = 500

# * [EXPLICAÇÃO] → Trava por Código ML, para o mesmo Código não ser coletado por dois cliques ao mesmo tempo. Se o servidor cair no
#                  meio, a trava some sozinha depois deste prazo.
CHAVE_CACHE_TRAVA = 'full_operacoes_coleta_{empresa}_{codigo}'
TIMEOUT_TRAVA_SEGUNDOS = 3600

MSG_ACESSO_RECUSADO = 'O Mercado Livre recusou o acesso (token inválido ou vencido).'

MAX_ID_CODIGO = OperacaoFullMercadoLivre._meta.get_field('inventory_id').max_length
MAX_ID_ENVIO = OperacaoFullMercadoLivre._meta.get_field('shipment_id').max_length


class ErroColetaOperacoes(Exception):
    """Problema da busca de UM grupo de Códigos (resposta incompleta, 404 fora do scroll, limite de páginas...) ou pedido
    inválido (nenhum Código). A cobertura NÃO avança além da última janela que já tinha terminado bem. A mensagem já vem
    pronta para a tela ou o comando."""


@dataclass
class RelatorioColetaOperacoes:
    """Resumo de 1 coleta — objeto de processo (nunca salvo no banco)."""
    codigos: list[str]
    dias_de_historico: int = 0                         # profundidade pedida nesta coleta (já validada)
    hoje_utc: date | None = None                       # o "hoje" (dia UTC) usado para calcular as janelas
    chamadas: int = 0                                  # páginas pedidas à API (as repetições internas de 429 não entram)
    segundos: float = 0.0                              # tempo dentro das chamadas à API (inclui as esperas internas do cliente)
    linhas_recebidas: int = 0                          # linhas de operação que a API entregou (já sem as repetidas)
    repetidas_descartadas: int = 0                     # mesma operação vinda 2x na mesma janela (só depois de recomeço por 404)
    descartadas: Counter = field(default_factory=Counter)   # {motivo: quantas} (limpeza)
    gravadas_novas: int = 0
    ja_existiam: int = 0
    reinicios_por_scroll_404: int = 0
    esperas_por_429: int = 0                           # vezes que o coletor esperou ESPERA_APOS_429_S depois de o cliente desistir
    segundos_de_espera_429: float = 0.0
    segundos_total: float = 0.0                        # relógio da coleta inteira
    janelas_concluidas: int = 0                        # janelas (de 1 grupo de Códigos) que terminaram bem nesta coleta
    codigos_com_falha: set = field(default_factory=set)
    falhas: list[str] = field(default_factory=list)    # 1 texto por grupo de Códigos que falhou
    puladas: list[str] = field(default_factory=list)   # Códigos que já estavam sendo coletados em outro lugar
    coberturas: dict = field(default_factory=dict)     # {Código ML: (data_inicial, data_final_exclusiva)} dos que avançaram nesta coleta (mesmo em parte)


# ---------------------------------------------------------------------------
# JANELAS E BUSCA NA API
# ---------------------------------------------------------------------------
# Função Objetivo: Divide [data_de, data_ate) em janelas de até DIAS_POR_JANELA_API dias, da mais antiga para a mais nova.
def fatiar_em_janelas(data_de: date, data_ate: date) -> list[tuple[date, date]]:
    janelas = []
    atual = data_de
    while atual < data_ate:
        proxima = min(atual + timedelta(days=DIAS_POR_JANELA_API), data_ate)
        janelas.append((atual, proxima))
        atual = proxima
    return janelas


# Função Objetivo: Divide [data_de, data_ate) em janelas de até DIAS_POR_JANELA_API dias, mas de TRÁS PARA FRENTE a partir de
# data_ate (a janela mais nova primeiro). É a ordem de quem estende o histórico para trás: cada janela encosta no início da cobertura
# que a anterior acabou de recuar, e a cobertura nunca fica com buraco.
def fatiar_para_tras(data_de: date, data_ate: date) -> list[tuple[date, date]]:
    janelas = []
    atual = data_ate
    while atual > data_de:
        anterior = max(atual - timedelta(days=DIAS_POR_JANELA_API), data_de)
        janelas.append((anterior, atual))
        atual = anterior
    return janelas


_ultima_chamada = {'t': None}


# Função Objetivo: 1 página da API, com a pausa entre chamadas. Conta a chamada mesmo se a API recusou (gasta cota do mesmo jeito).
def _buscar_pagina(api_ml, relatorio, codigos, tipo, data_de, data_ate, scroll):
    if _ultima_chamada['t'] is not None:
        espera = PAUSA_ENTRE_CHAMADAS_S - (time.monotonic() - _ultima_chamada['t'])
        if espera > 0:
            time.sleep(espera)
    inicio = time.monotonic()
    try:
        return api_ml.buscar_full_operacoes(codigos, tipo, data_de, data_ate, scroll=scroll, limite=LIMITE_POR_PAGINA)
    finally:
        _ultima_chamada['t'] = time.monotonic()
        relatorio.chamadas += 1
        relatorio.segundos += _ultima_chamada['t'] - inicio


def _e_404(texto_do_erro):
    return str(texto_do_erro).startswith('Erro 404')


# Função Objetivo: O cliente compartilhado desistiu por 429? (esse texto só nasce quando as 5 tentativas por 429 acabam: ver chamar_api)
def _e_429_esgotado(texto_do_erro):
    return str(texto_do_erro).startswith(TEXTO_429_ESGOTADO)


# Função Objetivo: Espera ESPERA_APOS_429_S e conta a espera. Avisa quem chamou, para o comando/tela não parecer travado.
def _esperar_apos_429(relatorio, avisar, onde, numero_da_espera):
    if avisar:
        avisar(f'Limite de chamadas do ML (429): esperando {ESPERA_APOS_429_S:.0f}s e repetindo ({numero_da_espera}/{MAX_ESPERAS_429_POR_CHAMADA}) — {onde}')
    inicio = time.monotonic()
    time.sleep(ESPERA_APOS_429_S)
    relatorio.esperas_por_429 += 1
    relatorio.segundos_de_espera_429 += time.monotonic() - inicio


# Função Objetivo: Traz TODAS as operações de 1 tipo numa janela (paginando por scroll) e devolve a lista de linhas CRUAS, sem repetidas.
# Levanta ErroColetaOperacoes se a busca não puder ser dada como completa. ErroAutenticacaoAPI (401) sobe como veio.
# "avisar" (opcional) recebe 1 texto curto sempre que o coletor vai esperar por causa do 429.
def buscar_janela(api_ml, relatorio, codigos, tipo, data_de, data_ate, avisar=None):
    onde = f'{tipo}, de {data_de:%d/%m/%Y} até {data_ate:%d/%m/%Y} (exclusivo)'
    linhas, ids_vistos, invalidas = [], set(), 0
    scroll, paginas, reinicios, esperas_429, total_api = None, 0, 0, 0, None
    while True:
        pacote = _buscar_pagina(api_ml, relatorio, codigos, tipo, data_de, data_ate, scroll)
        if pacote.erro:
            if _e_429_esgotado(pacote.erro):
                if esperas_429 >= MAX_ESPERAS_429_POR_CHAMADA:
                    raise ErroColetaOperacoes(
                        f'{onde}: o Mercado Livre continuou recusando por excesso de chamadas (429, limite por minuto) mesmo depois de '
                        f'{MAX_ESPERAS_429_POR_CHAMADA} esperas de {ESPERA_APOS_429_S:.0f}s.'
                    )
                esperas_429 += 1
                _esperar_apos_429(relatorio, avisar, onde, esperas_429)
                continue   # repete a MESMA página (mesmo scroll)
            if _e_404(pacote.erro) and scroll and reinicios < MAX_REINICIOS_POR_JANELA:
                reinicios += 1
                relatorio.reinicios_por_scroll_404 += 1
                scroll = None
                # A janela é lida de novo do zero: as linhas sem id (que não dá para deduplicar) e as inválidas vêm outra vez.
                linhas = [linha for linha in linhas if linha.get('id') is not None]
                invalidas = 0
                esperas_429 = 0
                continue
            raise ErroColetaOperacoes(f'{onde}: {pacote.erro}')
        if pacote.http != 200 or not isinstance(pacote.dados, dict):
            raise ErroColetaOperacoes(
                f'{onde}: resposta incompleta ou inesperada (HTTP {pacote.http}; faltou: {pacote.x_content_missing or "nada informado"}).'
            )
        esperas_429 = 0
        paginas += 1
        resultados = pacote.dados.get('results') or []
        paging = pacote.dados.get('paging') or {}
        if total_api is None:
            total_api = paging.get('total')
        for linha in resultados:
            if not isinstance(linha, dict):
                invalidas += 1
                continue
            id_da_linha = linha.get('id')
            if id_da_linha is not None:
                if id_da_linha in ids_vistos:
                    relatorio.repetidas_descartadas += 1
                    continue
                ids_vistos.add(id_da_linha)
            linhas.append(linha)
        scroll = paging.get('scroll')
        # Fim: a API devolve scroll vazio/nulo, ou não veio linha nenhuma, ou já recebemos o total anunciado.
        # A linha inválida também conta no total que a API anunciou (ela veio; só não serve) — por isso entra na conta de "recebidas".
        if not scroll or not resultados or (isinstance(total_api, int) and len(linhas) + invalidas >= total_api):
            break
        if paginas >= MAX_PAGINAS_POR_JANELA:
            raise ErroColetaOperacoes(
                f'{onde}: passou de {MAX_PAGINAS_POR_JANELA} páginas de {LIMITE_POR_PAGINA} operações; a busca foi interrompida '
                f'por segurança e NÃO é dada como completa.'
            )
    recebidas = len(linhas) + invalidas
    if isinstance(total_api, int) and recebidas < total_api:
        raise ErroColetaOperacoes(f'{onde}: a API anunciou {total_api} operações, mas vieram só {recebidas}.')
    if invalidas:
        relatorio.descartadas['linha_invalida'] += invalidas
    return linhas


# ---------------------------------------------------------------------------
# LIMPEZA E TIPAGEM (1 operação crua -> 1 linha do model)
# ---------------------------------------------------------------------------
# Função Objetivo: date_created da API (UTC, termina com Z) em datetime com fuso. None se faltar ou não vier com fuso.
def _ler_instante_utc(texto):
    if not texto:
        return None
    try:
        instante = datetime.fromisoformat(str(texto).replace('Z', '+00:00'))
    except ValueError:
        return None
    return instante if instante.tzinfo is not None else None


# Função Objetivo: Transforma 1 operação CRUA da API em 1 OperacaoFullMercadoLivre (sem salvar). Devolve (operacao, None) ou
# (None, motivo_do_descarte). "codigos_maiusculos" = os Códigos ML que foram pedidos, em maiúsculo.
def limpar_operacao(linha: dict, codigos_maiusculos: set):
    try:
        id_operacao = int(linha.get('id'))
    except (TypeError, ValueError):
        return None, 'sem_id'

    inventory_id = str(linha.get('inventory_id') or '').strip()
    if not inventory_id:
        return None, 'sem_codigo_ml'
    if inventory_id.upper() not in codigos_maiusculos:
        return None, 'codigo_nao_pedido'
    if len(inventory_id) > MAX_ID_CODIGO:
        return None, 'codigo_ml_longo_demais'

    tipo = str(linha.get('type') or '').strip().upper()
    if tipo not in TIPOS_COLETADOS:
        return None, 'tipo_nao_coletado'

    data_operacao = _ler_instante_utc(linha.get('date_created'))
    if data_operacao is None:
        return None, 'sem_data'

    # Na venda a quantidade vem NEGATIVA em detail.available_quantity (a unidade sai do estoque): guardamos sem o sinal.
    detalhe = linha.get('detail') or {}
    try:
        unidades = abs(int(detalhe.get('available_quantity')))
    except (TypeError, ValueError, AttributeError):
        return None, 'sem_quantidade'
    if unidades == 0:
        return None, 'sem_quantidade'

    shipment_id = ''
    for referencia in (linha.get('external_references') or []):
        if isinstance(referencia, dict) and referencia.get('type') == 'shipment_id' and referencia.get('value') is not None:
            shipment_id = str(referencia['value']).strip()
            break
    if len(shipment_id) > MAX_ID_ENVIO:
        return None, 'envio_longo_demais'

    return OperacaoFullMercadoLivre(
        id_operacao=id_operacao, inventory_id=inventory_id, tipo=tipo,
        data_operacao=data_operacao, unidades=unidades, shipment_id=shipment_id,
    ), None


# Função Objetivo: Grava só as operações que ainda não estão no banco (o id da operação é único). As que já existem são contadas e ignoradas.
def _gravar(operacoes, relatorio):
    if not operacoes:
        return
    ids = [operacao.id_operacao for operacao in operacoes]
    existentes = set()
    for inicio in range(0, len(ids), TAMANHO_LOTE_CONSULTA_IDS):
        lote = ids[inicio:inicio + TAMANHO_LOTE_CONSULTA_IDS]
        existentes.update(OperacaoFullMercadoLivre.objects.filter(id_operacao__in=lote).values_list('id_operacao', flat=True))
    novas = [operacao for operacao in operacoes if operacao.id_operacao not in existentes]
    relatorio.ja_existiam += len(operacoes) - len(novas)
    if novas:
        # ignore_conflicts: se outra coleta gravou o mesmo id um instante antes, não dá erro nem duplica.
        OperacaoFullMercadoLivre.objects.bulk_create(novas, batch_size=TAMANHO_LOTE_GRAVACAO, ignore_conflicts=True)
    relatorio.gravadas_novas += len(novas)


# Função Objetivo: Busca e grava tudo de 1 grupo de Códigos (todos com a mesma lista de janelas), janela por janela. É um GERADOR:
# devolve (janela_de, janela_ate) cada vez que os 4 tipos de uma janela terminam bem e já estão gravados — quem chama registra a
# cobertura na hora. Se uma janela falha, o erro sobe e as janelas anteriores continuam valendo.
def _coletar_grupo(api_ml, relatorio, codigos, janelas, avisar=None):
    codigos_maiusculos = {codigo.upper() for codigo in codigos}
    for janela_de, janela_ate in janelas:
        for tipo in TIPOS_COLETADOS:
            linhas = buscar_janela(api_ml, relatorio, codigos, tipo, janela_de, janela_ate, avisar)
            relatorio.linhas_recebidas += len(linhas)
            operacoes = []
            for linha in linhas:
                operacao, motivo = limpar_operacao(linha, codigos_maiusculos)
                if motivo:
                    relatorio.descartadas[motivo] += 1
                else:
                    operacoes.append(operacao)
            _gravar(operacoes, relatorio)
        yield janela_de, janela_ate


# Função Objetivo: Executa 1 grupo de Códigos que têm a mesma lista de janelas: busca janela por janela e registra a cobertura de cada
# Código assim que a janela termina bem. Falha de busca (ErroColetaOperacoes) NÃO sobe: marca a falha nos Códigos do grupo e deixa o
# chamador seguir para o próximo grupo. 401 (ErroAutenticacaoAPI) marca a falha e sobe, porque nenhuma chamada seguinte funcionaria.
def _executar_grupo(api_ml, relatorio, coberturas, por_maiusculo, do_grupo, janelas, avisar=None):
    nomes = [por_maiusculo[maiusculo] for maiusculo in do_grupo]
    try:
        for janela_de, janela_ate in _coletar_grupo(api_ml, relatorio, nomes, janelas, avisar):
            agora = timezone.now()
            for maiusculo in do_grupo:
                cobertura = coberturas[maiusculo]
                cobertura.registrar_busca_bem_sucedida(janela_de, janela_ate, agora)
                relatorio.coberturas[por_maiusculo[maiusculo]] = (
                    cobertura.data_inicial_cobertura, cobertura.data_final_cobertura_exclusiva,
                )
            relatorio.janelas_concluidas += 1
            if avisar:
                avisar(f'Janela de {janela_de:%d/%m/%Y} até {janela_ate:%d/%m/%Y} (exclusivo) concluída — {", ".join(nomes)}')
    except ErroColetaOperacoes as erro:
        for maiusculo in do_grupo:
            coberturas[maiusculo].registrar_falha(str(erro))
            relatorio.codigos_com_falha.add(por_maiusculo[maiusculo])
        relatorio.falhas.append(f'{", ".join(nomes)} — {erro}')
    except ErroAutenticacaoAPI:
        for maiusculo in do_grupo:
            coberturas[maiusculo].registrar_falha(MSG_ACESSO_RECUSADO)
        raise


# ---------------------------------------------------------------------------
# ENTRADA PÚBLICA
# ---------------------------------------------------------------------------
# Função Objetivo: Coleta as operações do Full dos Códigos ML pedidos e grava no banco da empresa, em 2 fases. 1ª: a parte NOVA, do ponto
# onde a cobertura de cada Código parou (menos a margem de segurança) até amanhã; Códigos com o mesmo intervalo são buscados juntos
# (1 chamada leva todos). 2ª: a parte ANTIGA que falta, se "dias_de_historico" pede mais fundo do que a cobertura já tem (ver ponto 5b
# do cabeçalho); só para Códigos cuja 1ª fase não falhou. A cobertura avança janela por janela (ver ponto 5). "dias_de_historico" vazio usa
# o padrão do model (DIAS_PRIMEIRA_CARGA); fora de 1 a 360 levanta ErroColetaOperacoes. "avisar" (opcional) recebe textos curtos de
# progresso. "hoje_utc" e "api_ml" existem só para teste; sem eles usa o dia UTC de agora e a API de verdade.
# Levanta ErroColetaOperacoes (pedido inválido) ou ErroAutenticacaoAPI (401); falha de busca de um grupo NÃO levanta: fica em
# relatorio.falhas e na própria cobertura do Código.
def coletar_operacoes(
    empresa: str, codigos, hoje_utc: date | None = None, api_ml=None, avisar=None, dias_de_historico: int | None = None,
) -> RelatorioColetaOperacoes:
    inicio_total = time.monotonic()
    definir_empresa_ativa(empresa)

    por_maiusculo = {}
    for codigo in codigos:
        texto = str(codigo or '').strip()
        if texto:
            por_maiusculo.setdefault(texto.upper(), texto)
    if not por_maiusculo:
        raise ErroColetaOperacoes('Nenhum Código ML para coletar.')

    try:
        dias = CoberturaOperacaoFullMercadoLivre.resolver_dias_de_historico(dias_de_historico)
    except ValueError as erro:
        raise ErroColetaOperacoes(str(erro))

    relatorio = RelatorioColetaOperacoes(codigos=list(por_maiusculo.values()), dias_de_historico=dias)
    if hoje_utc is None:
        hoje_utc = datetime.now(fuso.utc).date()
    relatorio.hoje_utc = hoje_utc
    if api_ml is None:
        api_ml = ApiMercadoLivre(pasta_logs=_caminho_pasta_logs(empresa), empresa=empresa)

    travados = []
    try:
        for maiusculo, codigo in por_maiusculo.items():
            if cache.add(CHAVE_CACHE_TRAVA.format(empresa=empresa, codigo=maiusculo), True, timeout=TIMEOUT_TRAVA_SEGUNDOS):
                travados.append(maiusculo)
            else:
                relatorio.puladas.append(codigo)

        coberturas = {maiusculo: CoberturaOperacaoFullMercadoLivre.obter(por_maiusculo[maiusculo]) for maiusculo in travados}

        # 1ª fase: a parte nova (a mais recente, a que mais importa vem primeiro).
        grupos_da_parte_nova = defaultdict(list)
        for maiusculo, cobertura in coberturas.items():
            parte_nova, _ = cobertura.calcular_buscas(hoje_utc, dias)
            grupos_da_parte_nova[parte_nova].append(maiusculo)
        for (data_de, data_ate), do_grupo in sorted(grupos_da_parte_nova.items()):
            _executar_grupo(api_ml, relatorio, coberturas, por_maiusculo, do_grupo, fatiar_em_janelas(data_de, data_ate), avisar)

        # 2ª fase: a parte antiga que falta, calculada AGORA (a cobertura já reflete o que a 1ª fase conseguiu). Quem falhou na 1ª
        # fase não tenta: a API está recusando e insistir só gasta mais cota.
        grupos_da_parte_antiga = defaultdict(list)
        for maiusculo, cobertura in coberturas.items():
            if por_maiusculo[maiusculo] in relatorio.codigos_com_falha:
                continue
            _, parte_antiga = cobertura.calcular_buscas(hoje_utc, dias)
            if parte_antiga:
                grupos_da_parte_antiga[parte_antiga].append(maiusculo)
        for (data_de, data_ate), do_grupo in sorted(grupos_da_parte_antiga.items()):
            if avisar:
                avisar(
                    f'Estendendo o histórico para trás: de {data_de:%d/%m/%Y} até {data_ate:%d/%m/%Y} (exclusivo) — '
                    f'{", ".join(por_maiusculo[maiusculo] for maiusculo in do_grupo)}'
                )
            _executar_grupo(api_ml, relatorio, coberturas, por_maiusculo, do_grupo, fatiar_para_tras(data_de, data_ate), avisar)
    finally:
        relatorio.segundos_total = time.monotonic() - inicio_total
        for maiusculo in travados:
            cache.delete(CHAVE_CACHE_TRAVA.format(empresa=empresa, codigo=maiusculo))
    return relatorio
