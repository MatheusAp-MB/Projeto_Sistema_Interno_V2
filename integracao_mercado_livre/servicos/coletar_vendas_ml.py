# integracao_mercado_livre/servicos/coletar_vendas_ml.py
#
# Função Objetivo: O COLETOR do histórico de vendas: busca os pedidos do Mercado Livre (GET /orders/search), limpa e tipa cada item
# vendido e grava em VendaItemMercadoLivre, registrando cada coleta em ColetaVendasMercadoLivre. Quem chama são os BOTÕES da tela de vendas
# (gestao_vendas) — nunca nada automático, e a tela nunca consulta o ML sozinha (regra do Matheus, a mesma das telas do Full).
#
# As coletas são GRANULARES (decisão do Matheus, 11/10/2026: nem sempre a varredura completa de todos os SKUs):
#   - coletar_mlb      → 1 MLB, de (hoje − N dias) até hoje (filtro "item" do /orders/search). O botão "Atualizar produto" chama esta mesma função
#                        1 vez por MLB do SKU.
#   - coletar_dia      → 1 dia da conta toda (todos os SKUs), ~4 páginas em um dia de ~160 pedidos.
#   - iniciar_periodo  → de (hoje − N dias) até hoje da conta toda, dia por dia, numa THREAD (com andamento e botão Parar), do dia mais novo para o
#                        mais antigo: se parar no meio, o que ficou pronto é o trecho mais recente, que é o mais valioso.
#
# * [EXPLICAÇÃO] → "N dias" aqui significa N dias PARA TRÁS de hoje: o intervalo é [hoje − N, hoje], ou seja, N + 1 dias de calendário (hoje entra, parcial).
#                  O N vem dos períodos por calendário da tela (Última semana, Último mês...; ver cobertura_vendas_ml.periodos_de_hoje).
#                  O limite é o primeiro dia que o ML ainda devolve (cobertura_vendas_ml.primeiro_dia_do_ml): ~12 meses atrás.
# * [EXPLICAÇÃO] → O que se mediu do endpoint em 10/10/2026 (conta Magazine; ver api_mercado_livre/pedidos_ml.py): 0 erro 429 em 42 chamadas,
#                  ~0,27 s por chamada, páginas de 50 e teto de offset + limit <= 10000. Por isso: (1) cada consulta que anuncia mais de
#                  10000 pedidos é partida ao meio (por hora, no mínimo) antes de paginar; (2) a espera entre chamadas é curta
#                  (PAUSA_ENTRE_CHAMADAS_S) e configurável aqui em cima; (3) 429 continua tratado (o cliente compartilhado já tenta 5 vezes
#                  com espera; aqui há mais 1 tentativa depois de uma pausa maior).
# * [EXPLICAÇÃO] → A HORA DO FILTRO (medido em 12/10/2026, dia 24/11/2025): o ML ignora minutos e lê a HORA INTEIRA no "order.date_created.to". Pedir to = D+1 00:00 lê até
#                  D+1 00:59:59 (477 pedidos em vez de 465): a hora 0 do dia seguinte era lida 2 vezes (~1,3% de leituras a mais: 1.074 pedidos no ano). Por isso `_buscar_pagina`
#                  manda `fim − 1 hora` ao ML (to = D 23:00 lê o dia D inteiro: 465, igual ao banco). Toda janela daqui é [inicio, fim) em HORAS CHEIAS (há uma trava para isso).
# * [EXPLICAÇÃO] → A ORDEM da lista (medido em 12/10/2026 e escrito na doc de Orders: "Sellers por date_closed"): o sort=date_desc ordena pela data de FECHAMENTO do pedido, não pela
#                  de criação. Dois pedidos fechados no mesmo segundo não têm ordem definida entre si: se o par cair na fronteira de uma página (posição 50, 100...), o ML pode mandar
#                  um pedido 2 vezes e outro nenhuma (o "anunciou 202, vieram 201" de 08/07/2026). A causa ainda está em teste (scripts_exploracao_ML/
#                  investigar_empates_de_fechamento_nas_paginas_so_no_banco.py). A PROTEÇÃO é a RELEITURA: se o total não fecha, a janela é lida de novo com página de OUTRO
#                  tamanho (a fronteira cai em outro ponto) e os pedidos que faltavam são somados (LIMITES_DAS_RELEITURAS). Funciona qualquer que seja a causa.
# * [EXPLICAÇÃO] → A gravação é por "upsert" (order_id + posição do item): puxar o mesmo período de novo NÃO duplica, só atualiza a linha.
#                  É assim que um cancelamento feito depois chega ao banco: basta atualizar o período de novo.
# * [EXPLICAÇÃO] → O seller_id nunca é gravado (nem no banco, nem na mensagem). Nenhum dado de comprador é lido além do que o ML manda no
#                  pedido: o coletor só copia os campos do item, do pedido e do estoque listados em limpar_pedido.

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from math import ceil
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.db import connections, router
from django.db.utils import OperationalError
from django.utils import timezone

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import requisicoes_enviadas_nesta_thread
from api_mercado_livre.core.estrutura_api.excecoes import ErroAutenticacaoAPI
from core.empresa import definir_empresa_ativa
from integracao_mercado_livre.servicos.buscar_detalhes import _caminho_pasta_logs
from integracao_mercado_livre.servicos.cobertura_vendas_ml import (
    DIAS_DE_REVISAO, PERIODO_PADRAO, carregar_coletas, dias_para_tras, dias_pendentes, dica_de_borda, dividir_janela, faixas_de_dias,
    primeiro_dia_do_ml)
from mercado_livre.models import ColetaVendasMercadoLivre, ExecucaoColetaVendasMercadoLivre, VendaItemMercadoLivre

FUSO = ZoneInfo('America/Sao_Paulo')

LIMITE_POR_PAGINA = 50
TETO_OFFSET_MAIS_LIMITE = 10000         # medido em 10/10/2026: offset 9950 + limit 50 passou; offset 82100 deu 400
# * [EXPLICAÇÃO] → O limite de quão para trás se coleta NÃO é mais um número fixo de dias: é o primeiro dia que o ML guarda (cobertura_vendas_ml.
#                  primeiro_dia_do_ml). 360 dias foi lido com 200 OK (82106 pedidos) em 10/10/2026; o dia exato de 12 meses atrás (11/10/2025) foi lido em 11/10/2026, mas em 12/10/2026 se viu que ele vem PARCIAL (o ML corta o começo do dia mais antigo); por isso FOLGA_DO_LIMITE_ML_DIAS = 1 (ver cobertura_vendas_ml.py).

# * [EXPLICAÇÃO] → 0,3 s ≈ o tempo de 1 chamada medida (0,27 s): 1 chamada por vez, sem paralelismo. Para 90 dias da conta toda
#                  (~360 chamadas) dá poucos minutos. Subir/baixar aqui se o ML começar a devolver 429.
PAUSA_ENTRE_CHAMADAS_S = 0.3
SEGUNDOS_POR_CHAMADA_ESTIMADO = 0.6     # 0,27 s da chamada medida + a pausa acima: para a estimativa que a tela mostra

# * [EXPLICAÇÃO] → O "Atualizar" de um MLB vira PEDIDOS CURTOS: cada requisição da tela lê no máximo MAX_PEDIDOS_POR_REQUISICAO pedidos
#                  (1000 = 20 páginas = uns 12 s). Se a janela tem mais que isso, o servidor NÃO grava nada e devolve a janela já partida
#                  em pedaços (FOLGA_DA_DIVISAO: pedaços de ~80% do limite, para sobrar margem quando os dias não são iguais). Assim
#                  nenhuma requisição fica minutos pendurada (o que estoura timeout de servidor) e a tela mostra andamento.
MAX_PEDIDOS_POR_REQUISICAO = 1000
FOLGA_DA_DIVISAO = 0.8
TENTATIVAS_DE_GRAVACAO = 3
CODIGOS_MYSQL_PARA_REPETIR = (1213, 1205)   # 1213 = deadlock detectado, 1205 = tempo de espera por trava: o MySQL manda repetir a transação
ESPERA_ANTES_DE_REPETIR_S = 20
MAX_TENTATIVAS_POR_PAGINA = 2
LIMITES_DAS_RELEITURAS = (45, 40)           # tamanho da página em cada RELEITURA de uma janela que não fechou (no máx. 2 releituras; ver _ler_intervalo). Menor que 50 de propósito
TEXTO_429_ESGOTADO = 'Número máximo de tentativas'   # o erro do chamar_api quando as tentativas por 429 acabam

CHAVE_CACHE_PERIODO = 'vendas_periodo_{empresa}'
CHAVE_CACHE_PARAR = 'vendas_periodo_parar_{empresa}'
CHAVE_CACHE_TRAVA = 'vendas_coleta_trava_{empresa}_{alvo}'
TIMEOUT_ANDAMENTO_SEGUNDOS = 900
TIMEOUT_RESULTADO_SEGUNDOS = 6 * 3600
TIMEOUT_TRAVA_SEGUNDOS = 900
SEGUNDOS_SEM_PROGRESSO_PARA_CONSIDERAR_PARADA = 300
INTERVALO_GRAVACAO_PROGRESSO = 1.0
MAX_AVISOS = 20
MAX_MENSAGEM_REGISTRADA = 8000   # teto do texto gravado no banco (mensagem + até MAX_AVISOS avisos de até 300 caracteres cada)

CAMPOS_ATUALIZADOS_NO_UPSERT = [
    'mlb', 'seller_sku', 'variation_id', 'quantidade', 'preco_unitario', 'taxa_venda', 'tipo_anuncio', 'status', 'criado_em_ml',
    'fechado_em_ml', 'dia_venda', 'hora_venda', 'node_id', 'store_id', 'pack_id', 'shipping_id', 'catalogo', 'com_desconto', 'atualizado_em',
]


class ErroColetaVendas(Exception):
    """Uma coleta que não pôde ser feita (pedido de período inválido, MLB sem anúncio, o ML devolveu erro...). A mensagem é para a tela."""


class JanelaGrande(Exception):
    """A janela pedida tem mais pedidos que o limite desta requisição: NADA foi gravado. `total` = pedidos que o ML anunciou; `partes` = a
    janela partida em pedaços [(inicio, fim), ...] que cabem no limite. `chamadas` = as requisições que esta tentativa já gastou (a 1ª página, que só
    serviu para descobrir o total): a tela soma para o total EXATO do clique."""

    def __init__(self, total, partes, chamadas=0):
        super().__init__(total)
        self.total, self.partes, self.chamadas = total, partes, chamadas


class ColetaOcupada(Exception):
    """Já há uma coleta do mesmo alvo rodando (outro clique, outra aba) ou uma varredura de período em andamento."""


@dataclass
class RelatorioColetaVendas:
    escopo: str
    alvo: str = ''
    data_de: date | None = None
    data_ate: date | None = None
    status: str = ColetaVendasMercadoLivre.Status.CONCLUIDA
    chamadas: int = 0
    erros_429: int = 0
    pedidos_lidos: int = 0
    itens_gravados: int = 0
    itens_ignorados: int = 0
    dias_pulados: int = 0
    avisos: list = field(default_factory=list)
    avisos_a_mais: int = 0   # avisos que passaram do limite MAX_AVISOS: só contados, sem texto
    mensagem: str = ''
    iniciado_em: datetime | None = None

    def avisar(self, texto):
        if len(self.avisos) < MAX_AVISOS:
            self.avisos.append(str(texto)[:300])
        else:
            self.avisos_a_mais += 1


# ==================================================== datas e limpeza (funções puras) ====================================================

def _inicio_do_dia(dia: date) -> datetime:
    return datetime(dia.year, dia.month, dia.day, tzinfo=FUSO)


def _hoje() -> date:
    return datetime.now(FUSO).date()


# Função Objetivo: A data do ML (ex.: 2026-10-09T08:50:35.000-04:00) como instante COM fuso. Sem fuso ou fora do padrão devolve None: aqui
# ninguém adivinha o fuso. O ML manda -04:00 em todas as datas; Brasília é -03:00, então o dia da venda SEMPRE sai desta conversão,
# nunca de cortar o texto.
def ler_instante(texto):
    if not texto:
        return None
    try:
        instante = datetime.fromisoformat(str(texto))
    except ValueError:
        return None
    return instante if instante.tzinfo is not None else None


def _decimal(valor):
    if valor is None or valor == '':
        return None
    try:
        return Decimal(str(valor)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def _texto(valor):
    return '' if valor is None else str(valor).strip()


# Função Objetivo: Transforma 1 pedido cru do ML em linhas prontas para VendaItemMercadoLivre (1 por item). Devolve (linhas, ignorados): os
# ignorados são os motivos (texto) de pedido/item sem o mínimo (id, data, MLB, quantidade >= 1) — nunca vira linha "com zero".
def limpar_pedido(pedido: dict):
    order_id = pedido.get('id')
    criado = ler_instante(pedido.get('date_created'))
    if not isinstance(order_id, int) or criado is None:
        return [], [f'pedido {order_id}: sem id numérico ou sem date_created com fuso']
    fechado = ler_instante(pedido.get('date_closed'))
    criado_em_brasilia = criado.astimezone(FUSO)
    tags = pedido.get('tags') or []
    envio = pedido.get('shipping') or {}
    linhas, ignorados = [], []
    for posicao, item_do_pedido in enumerate(pedido.get('order_items') or []):
        anuncio = item_do_pedido.get('item') or {}
        mlb = _texto(anuncio.get('id'))
        quantidade = item_do_pedido.get('quantity')
        if not mlb or not isinstance(quantidade, int) or quantidade < 1:
            ignorados.append(f'pedido {order_id} item {posicao}: sem MLB ou sem quantidade válida')
            continue
        estoque = item_do_pedido.get('stock') or {}
        linhas.append({
            'order_id': order_id, 'posicao': posicao, 'mlb': mlb,
            'seller_sku': _texto(anuncio.get('seller_sku')), 'variation_id': _texto(anuncio.get('variation_id')),
            'quantidade': quantidade,
            'preco_unitario': _decimal(item_do_pedido.get('unit_price')), 'taxa_venda': _decimal(item_do_pedido.get('sale_fee')),
            'tipo_anuncio': _texto(item_do_pedido.get('listing_type_id')),
            'status': _texto(pedido.get('status')),
            'criado_em_ml': criado, 'fechado_em_ml': fechado,
            'dia_venda': criado_em_brasilia.date(), 'hora_venda': criado_em_brasilia.hour,
            'node_id': _texto(estoque.get('node_id')), 'store_id': _texto(estoque.get('store_id')),
            'pack_id': pedido.get('pack_id') if isinstance(pedido.get('pack_id'), int) else None,
            'shipping_id': envio.get('id') if isinstance(envio.get('id'), int) else None,
            'catalogo': 'catalog' in tags, 'com_desconto': 'order_has_discount' in tags,
        })
    return linhas, ignorados


# Função Objetivo: Grava as linhas por "upsert" (order_id + posição): o que já existe é atualizado (status novo, por exemplo), o que não existe é
# criado. Devolve quantas linhas foram gravadas.
def gravar_itens(linhas):
    unicas = {(l['order_id'], l['posicao']): l for l in linhas}
    if not unicas:
        return 0
    # * [EXPLICAÇÃO] → Com várias requisições gravando ao mesmo tempo (o "Atualizar produto" lê 3 trechos juntos), o MySQL pode detectar
    #                  deadlock quando duas transações travam as mesmas linhas em ordem diferente. Por isso (1) as linhas vão SEMPRE em ordem
    #                  (order_id, posicao) e (2) se mesmo assim o MySQL mandar repetir (1213/1205), repete a gravação — é o tratamento
    #                  recomendado por ele. O upsert é idempotente: repetir não duplica nada.
    opcoes = {'update_conflicts': True, 'update_fields': CAMPOS_ATUALIZADOS_NO_UPSERT}
    # O Django exige 'unique_fields' nos bancos que dizem em qual constraint o conflito acontece (SQLite, PostgreSQL) e PROÍBE
    # nos que não dizem (MySQL/MariaDB: usam ON DUPLICATE KEY UPDATE e se apoiam na UniqueConstraint order_id+posicao da tabela).
    banco = router.db_for_write(VendaItemMercadoLivre)
    if connections[banco].features.supports_update_conflicts_with_target:
        opcoes['unique_fields'] = ['order_id', 'posicao']
    objetos = [VendaItemMercadoLivre(**unicas[chave]) for chave in sorted(unicas)]
    for tentativa in range(1, TENTATIVAS_DE_GRAVACAO + 1):
        try:
            VendaItemMercadoLivre.objects.bulk_create(objetos, batch_size=500, **opcoes)
            break
        except OperationalError as erro:
            codigo = erro.args[0] if erro.args else None
            if codigo not in CODIGOS_MYSQL_PARA_REPETIR or tentativa == TENTATIVAS_DE_GRAVACAO:
                raise
            time.sleep(0.2 * tentativa)
    return len(unicas)


def _gravar_pedidos(relatorio, pedidos):
    linhas = []
    for pedido in pedidos:
        do_pedido, ignorados = limpar_pedido(pedido)
        linhas.extend(do_pedido)
        relatorio.itens_ignorados += len(ignorados)
        for motivo in ignorados:
            relatorio.avisar(motivo)
    relatorio.pedidos_lidos += len(pedidos)
    relatorio.itens_gravados += gravar_itens(linhas)


# ==================================================== chamadas ao Mercado Livre ====================================================

def _vale_repetir(texto):
    return TEXTO_429_ESGOTADO in texto or 'Timeout' in texto or 'Erro 5' in texto


# Função Objetivo: A janela [inicio, fim) tem de ser em HORAS CHEIAS e de pelo menos 1 hora: o ML lê a hora inteira em from/to (ver o cabeçalho), então um minuto "quebrado" seria lido
# errado em silêncio. Quem chama monta janelas em horas cheias (dias inteiros ou o meio arredondado por hora de _ler_intervalo); isto só garante que ninguém quebre essa regra depois.
def _exigir_janela_em_horas_cheias(inicio, fim):
    if any(instante.minute or instante.second or instante.microsecond for instante in (inicio, fim)):
        raise ErroColetaVendas(f'Janela fora de hora cheia ({inicio:%d/%m %H:%M:%S} a {fim:%d/%m %H:%M:%S}): o filtro do ML lê a hora inteira. Nada foi lido.')
    if fim - inicio < timedelta(hours=1):
        raise ErroColetaVendas(f'Janela com menos de 1 hora ({inicio:%d/%m %H:%M} a {fim:%d/%m %H:%M}). Nada foi lido.')


# Função Objetivo: 1 página, com 1 nova tentativa depois de uma pausa maior se o ML recusou por excesso de chamadas (429), deu timeout ou 5xx.
# Levanta ErroColetaVendas se a página não veio; ErroAutenticacaoAPI sobe como veio.
# * [EXPLICAÇÃO] → O `to` mandado ao ML é `fim − 1 hora`, não `fim`: o ML lê até o FIM da hora do `to` (12/10/2026), então `fim` exclusivo vira `fim − 1 hora` inclusivo (ver o cabeçalho).
#                  O `from` vai como está (from = 00:00 já inclui a hora 0). `limite` é o tamanho da página: 50 na leitura normal, menor nas releituras.
# * [EXPLICAÇÃO] → `relatorio.chamadas` = REQUISIÇÕES HTTP reais (12/10/2026): é a diferença do contador do cliente da API (cliente_api.
#                  requisicoes_enviadas_nesta_thread) antes e depois de pedir a página, então a retentativa interna por 429, timeout ou 206 também
#                  entra. O `max(1, ...)` mantém "pelo menos 1 por página" se o cliente for trocado por um falso (teste) que não conta.
def _buscar_pagina(api_ml, relatorio, inicio, fim, offset, mlb, limite=LIMITE_POR_PAGINA):
    _exigir_janela_em_horas_cheias(inicio, fim)
    fim_do_filtro = fim - timedelta(hours=1)
    for tentativa in range(1, MAX_TENTATIVAS_POR_PAGINA + 1):
        if relatorio.chamadas:
            time.sleep(PAUSA_ENTRE_CHAMADAS_S)
        antes = requisicoes_enviadas_nesta_thread()
        try:
            pacote = api_ml.buscar_pedidos(inicio, fim_do_filtro, offset=offset, limite=limite, mlb=mlb)
        finally:
            relatorio.chamadas += max(1, requisicoes_enviadas_nesta_thread() - antes)
        if pacote.erro is None and pacote.http == 200 and isinstance(pacote.dados, dict):
            return pacote.dados
        texto = pacote.erro or f'HTTP {pacote.http}'
        if TEXTO_429_ESGOTADO in texto:
            relatorio.erros_429 += 1
        if tentativa < MAX_TENTATIVAS_POR_PAGINA and _vale_repetir(texto):
            time.sleep(ESPERA_ANTES_DE_REPETIR_S)
            continue
        raise ErroColetaVendas(f'O Mercado Livre não devolveu a página de pedidos: {texto[:250]}')


def _pedido_tem_o_mlb(pedido, mlb):
    return any((i.get('item') or {}).get('id') == mlb for i in (pedido.get('order_items') or []))


class _Interrompida(Exception):
    """A pessoa apertou Parar no meio de um dia: o dia incompleto não conta como coberto."""


class _JanelaGrande(Exception):
    """Interno: o ML anunciou mais pedidos que `max_pedidos`; ainda nada foi paginado nem gravado. args[0] = o total anunciado."""


# Função Objetivo: Pagina [inicio, fim) a partir de `offset`, até `total`, com páginas de `limite` pedidos, e soma o que veio em `por_id` (por número do pedido: o repetido não duplica).
# `parar` (opcional) é chamado antes de cada página. A última página é encurtada para offset + tamanho nunca passar de 10000 (teto do ML), mesmo com `limite` fora de 50.
def _paginar(api_ml, relatorio, inicio, fim, mlb, parar, total, por_id, limite, offset=0):
    while offset < total:
        if parar and parar():
            raise _Interrompida()
        tamanho = min(limite, TETO_OFFSET_MAIS_LIMITE - offset)
        if tamanho <= 0:
            break
        pagina = _buscar_pagina(api_ml, relatorio, inicio, fim, offset, mlb, tamanho).get('results') or []
        if not pagina:
            break
        por_id.update({p['id']: p for p in pagina})
        offset += tamanho


# Função Objetivo: Todos os pedidos de [inicio, fim) — da conta toda ou, com `mlb`, só dos que têm esse item. Se o ML anuncia mais de 10000
# pedidos para o intervalo, parte ao meio (por hora, no mínimo) ANTES de paginar, porque offset + limit não passa de 10000. Devolve a lista
# de pedidos crus, sem repetição. `parar` (opcional) é chamado entre as páginas: se devolver True, levanta _Interrompida. `max_pedidos`
# (opcional): se o ML anunciar mais que isso, levanta _JanelaGrande logo depois da 1ª página, antes de paginar.
# RELEITURA: se, depois de paginar, vieram MENOS pedidos que o ML anunciou, a janela é lida de novo (até 2 vezes, com páginas de OUTRO tamanho, ver LIMITES_DAS_RELEITURAS) e os pedidos
# que faltavam são somados; para assim que fecha. Custa umas 5 chamadas por janela que não fechou (2 janelas em 366 dias na coleta do ano de 11/10/2026). Se ainda não fechar, vira aviso.
def _ler_intervalo(api_ml, relatorio, inicio, fim, mlb=None, parar=None, max_pedidos=None):
    dados = _buscar_pagina(api_ml, relatorio, inicio, fim, 0, mlb)
    total = (dados.get('paging') or {}).get('total') or 0
    primeira = dados.get('results') or []
    if mlb and primeira and not all(_pedido_tem_o_mlb(p, mlb) for p in primeira):
        raise ErroColetaVendas(
            'O filtro por MLB não foi respeitado pelo Mercado Livre (vieram pedidos de outros anúncios). Nada foi gravado, para não marcar '
            'como coberto o que não foi lido.')
    if max_pedidos and total > max_pedidos:
        raise _JanelaGrande(total)
    if total > TETO_OFFSET_MAIS_LIMITE:
        meio = (inicio + (fim - inicio) / 2).replace(minute=0, second=0, microsecond=0)
        if meio <= inicio or meio >= fim:
            raise ErroColetaVendas(f'O Mercado Livre anunciou {total} pedidos para menos de 1 hora; não dá para dividir mais.')
        por_id = {p['id']: p for p in _ler_intervalo(api_ml, relatorio, inicio, meio, mlb, parar)}
        por_id.update({p['id']: p for p in _ler_intervalo(api_ml, relatorio, meio, fim, mlb, parar)})
        return list(por_id.values())

    por_id = {p['id']: p for p in primeira}
    _paginar(api_ml, relatorio, inicio, fim, mlb, parar, total, por_id, LIMITE_POR_PAGINA, offset=LIMITE_POR_PAGINA)
    releituras = 0
    for limite in LIMITES_DAS_RELEITURAS:
        if len(por_id) >= total:
            break
        _paginar(api_ml, relatorio, inicio, fim, mlb, parar, total, por_id, limite)
        releituras += 1
    if len(por_id) < total:
        depois = f', mesmo depois de {releituras} {"releitura" if releituras == 1 else "releituras"}' if releituras else ''
        relatorio.avisar(
            f'De {inicio:%d/%m %H:%M} a {fim:%d/%m %H:%M} o ML anunciou {total} pedidos e vieram {len(por_id)}{depois} (a ordem da lista pode mudar '
            f'enquanto se pagina; atualizar de novo completa).')
    elif len(por_id) > total:
        relatorio.avisar(
            f'De {inicio:%d/%m %H:%M} a {fim:%d/%m %H:%M} o ML anunciou {total} pedidos e vieram {len(por_id)} (mais que o anunciado: a janela mudou durante a leitura).')
    return list(por_id.values())


# ==================================================== trava e registro ====================================================

@contextmanager
def _travar(empresa, alvo):
    chave = CHAVE_CACHE_TRAVA.format(empresa=empresa, alvo=alvo)
    if not cache.add(chave, True, timeout=TIMEOUT_TRAVA_SEGUNDOS):
        raise ColetaOcupada(alvo)
    try:
        yield
    finally:
        cache.delete(chave)


def _garantir_sem_periodo(empresa):
    if periodo_em_andamento(empresa) is not None:
        raise ColetaOcupada('periodo')


# Função Objetivo: O texto que vai para o BANCO (coluna `mensagem` de ColetaVendasMercadoLivre e de ExecucaoColetaVendasMercadoLivre): a mensagem que a tela
#                  mostrou + TODOS os avisos da coleta, um por linha. A tela mostra só o 1º aviso e a contagem (cabe no aviso flutuante); o resto ficava só na
#                  memória do servidor e se perdia (aconteceu em 12/10/2026: a coleta do ano deu "2 avisos" e só um tinha texto).
# * [EXPLICAÇÃO] → MAX_AVISOS (20) limita quantos textos a coleta guarda; o que passar disso é só contado (avisos_a_mais) e o texto diz quantos ficaram de fora.
# * [EXPLICAÇÃO] → O título "Avisos desta coleta" é o marcador que o script conferir_coleta_da_conta_toda_contra_coleta_por_produto.py procura: se mudar aqui, mude lá.
def _mensagem_para_registro(relatorio):
    texto = relatorio.mensagem or ''
    if relatorio.avisos:
        texto += f'\n\nAvisos desta coleta ({len(relatorio.avisos) + relatorio.avisos_a_mais}):\n' + '\n'.join(f'- {aviso}' for aviso in relatorio.avisos)
        if relatorio.avisos_a_mais:
            texto += f'\n- (e mais {relatorio.avisos_a_mais} sem texto guardado: o limite é {MAX_AVISOS} por coleta)'
    return texto[:MAX_MENSAGEM_REGISTRADA]


def _registrar(relatorio, usuario, sku=''):
    ColetaVendasMercadoLivre.objects.create(
        escopo=relatorio.escopo,
        mlb=relatorio.alvo if relatorio.escopo == ColetaVendasMercadoLivre.Escopo.MLB else '',
        sku=sku, data_de=relatorio.data_de, data_ate=relatorio.data_ate, status=relatorio.status,
        pedidos_lidos=relatorio.pedidos_lidos, itens_gravados=relatorio.itens_gravados, chamadas=relatorio.chamadas,
        erros_429=relatorio.erros_429, mensagem=_mensagem_para_registro(relatorio), usuario=usuario[:150],
        iniciado_em=relatorio.iniciado_em, concluido_em=timezone.now(),
    )


# ==================================================== execuções: 1 linha por CLIQUE, com o custo em chamadas ====================================================

LIMITE_DE_CONTAGEM = 10_000_000   # teto de qualquer número vindo da tela (só evita estourar o campo; ninguém chega perto)


def _natural(valor):
    try:
        return max(0, min(int(valor), LIMITE_DE_CONTAGEM))
    except (TypeError, ValueError):
        return 0


# Função Objetivo: Guarda no banco a execução de UM clique (1 linha em ExecucaoColetaVendasMercadoLivre) com o total EXATO de chamadas ao Mercado Livre que ele
#                  custou. É o que o servidor faz sozinho nos botões que ele executa inteiros: "Atualizar dia" e "Coletar período da conta".
# * [EXPLICAÇÃO] → NUNCA derruba a coleta: se não conseguir gravar, só escreve o erro no terminal do servidor (a coleta em si já está salva).
def _registrar_execucao(relatorio, tipo, usuario, data_de, data_ate, trechos, trechos_com_falha, dias_total=0, dias_a_coletar=0, segundos=None):
    import traceback

    try:
        agora = timezone.now()
        if segundos is None:
            segundos = (agora - relatorio.iniciado_em).total_seconds()
        ExecucaoColetaVendasMercadoLivre.objects.create(
            tipo=tipo, data_de=data_de, data_ate=data_ate, status=relatorio.status,
            dias_total=dias_total, dias_a_coletar=dias_a_coletar, trechos=trechos, trechos_com_falha=trechos_com_falha,
            chamadas=relatorio.chamadas, erros_429=relatorio.erros_429, pedidos_lidos=relatorio.pedidos_lidos, segundos=_natural(segundos),
            mensagem=_mensagem_para_registro(relatorio), usuario=(usuario or '')[:150], iniciado_em=relatorio.iniciado_em, concluido_em=agora,
        )
    except Exception:
        traceback.print_exc()


# Função Objetivo: Guarda no banco a execução de UM clique em "Atualizar" de um MLB ou do produto (com ou sem "Reler tudo"). Estes botões a TELA monta em
#                  vários trechos e, quando o último termina, manda para cá o total que somou. Não chama o Mercado Livre. Devolve a linha criada.
# * [EXPLICAÇÃO] → O status sai dos trechos: nenhum trecho lido = falha; algum falhou ou a fila parou (acesso recusado, rede caída) = parcial; senão concluída.
# * [EXPLICAÇÃO] → Os números vêm do navegador: são limitados ao teto (nunca negativos). Quem pode abrir a tela já pode disparar a coleta, então não
#                  há o que proteger além de dado absurdo.
def registrar_execucao_do_clique(tipo, usuario, sku='', mlb='', dias=0, reler_tudo=False, mlbs=0, dias_total=0, dias_a_coletar=0, trechos=0,
                                 trechos_com_falha=0, trechos_sem_contagem=0, parou=False, pedidos=0, chamadas=0, erros_429=0, segundos=0, mensagem=''):
    Tipo, Status = ExecucaoColetaVendasMercadoLivre.Tipo, ExecucaoColetaVendasMercadoLivre.Status
    if tipo not in (Tipo.PRODUTO, Tipo.MLB):
        raise ErroColetaVendas('Tipo de execução inválido.')
    if tipo == Tipo.MLB and not mlb.startswith('MLB'):
        raise ErroColetaVendas('MLB inválido para registrar a execução.')
    trechos, trechos_com_falha = _natural(trechos), _natural(trechos_com_falha)
    if trechos == 0:
        status = Status.FALHA
    elif trechos_com_falha or parou:
        status = Status.PARCIAL
    else:
        status = Status.CONCLUIDA
    agora, hoje, segundos = timezone.now(), _hoje(), _natural(segundos)
    return ExecucaoColetaVendasMercadoLivre.objects.create(
        tipo=tipo, sku=sku[:40], mlb=mlb[:20] if tipo == Tipo.MLB else '', reler_tudo=bool(reler_tudo),
        data_de=hoje - timedelta(days=min(_natural(dias), 3650)), data_ate=hoje, status=status,
        mlbs=_natural(mlbs), dias_total=_natural(dias_total), dias_a_coletar=_natural(dias_a_coletar),
        trechos=trechos, trechos_com_falha=trechos_com_falha, trechos_sem_contagem=_natural(trechos_sem_contagem),
        chamadas=_natural(chamadas), erros_429=_natural(erros_429), pedidos_lidos=_natural(pedidos), segundos=segundos,
        mensagem=str(mensagem or '')[:5000], usuario=(usuario or '')[:150],
        iniciado_em=agora - timedelta(seconds=segundos), concluido_em=agora,
    )


def _plural(n, singular, plural):
    return singular if n == 1 else plural


def _resumo(relatorio, o_que):
    partes = [
        f"{o_que}: {relatorio.pedidos_lidos} {_plural(relatorio.pedidos_lidos, 'pedido', 'pedidos')} "
        f"({relatorio.itens_gravados} {_plural(relatorio.itens_gravados, 'item gravado', 'itens gravados')}) "
        f"de {relatorio.data_de:%d/%m/%Y} a {relatorio.data_ate:%d/%m/%Y}, em {relatorio.chamadas} {_plural(relatorio.chamadas, 'chamada', 'chamadas')} ao Mercado Livre",
    ]
    if relatorio.dias_pulados:
        partes.append(f'{relatorio.dias_pulados} {_plural(relatorio.dias_pulados, "dia já coletado foi pulado", "dias já coletados foram pulados")}')
    if relatorio.erros_429:
        partes.append(f'{relatorio.erros_429} com recusa por excesso de chamadas (429)')
    if relatorio.itens_ignorados:
        partes.append(f'{relatorio.itens_ignorados} {_plural(relatorio.itens_ignorados, "item ignorado", "itens ignorados")} por falta de dado')
    if relatorio.avisos and not relatorio.itens_ignorados:
        total_de_avisos = len(relatorio.avisos) + relatorio.avisos_a_mais
        guardados = ' (a lista completa fica guardada na coleta, no banco)' if total_de_avisos > 1 else ''
        partes.append(f'{total_de_avisos} {_plural(total_de_avisos, "aviso", "avisos")}{guardados}: {relatorio.avisos[0]}')
    return '; '.join(partes) + '.'


# ==================================================== coletas síncronas (1 MLB e 1 dia; "Atualizar produto" é a tela chamando 1 MLB por vez) ====================================================

def _api(empresa):
    return ApiMercadoLivre(pasta_logs=_caminho_pasta_logs(empresa), empresa=empresa)


# Função Objetivo: O N (dias para trás de hoje) do período padrão da tela (hoje: Últimos 3 meses). Substitui o antigo número fixo de dias.
def dias_padrao():
    return dias_para_tras(PERIODO_PADRAO, _hoje())


# Função Objetivo: Garante que `dias` (para trás de hoje) cabe no histórico que o Mercado Livre guarda; senão levanta ErroColetaVendas.
def _validar_dias(dias, hoje):
    primeiro = primeiro_dia_do_ml(hoje)
    maximo = (hoje - primeiro).days
    if not 1 <= dias <= maximo:
        raise ErroColetaVendas(f'O período precisa voltar de 1 a {maximo} dias a partir de hoje (o Mercado Livre guarda a partir de {primeiro:%d/%m/%Y}).')


# Função Objetivo: Coleta os pedidos de 1 MLB: de (hoje − `dias`) até hoje (dias para trás + hoje) ou, se vierem `de` e `ate`, só nesse trecho. Botão
# "Atualizar" da tela. Sempre devolve o relatório (status concluida ou falha); só ErroAutenticacaoAPI (token recusado), ColetaOcupada e
# JanelaGrande sobem. `max_pedidos` (a tela manda): se o ML anunciar mais pedidos que isso para a janela, NADA é gravado e sobe JanelaGrande
# com a janela já partida; janela de 1 dia não se parte, então lá o limite não vale.
def coletar_mlb(empresa, mlb, dias=None, usuario='', sku='', api_ml=None, de=None, ate=None, max_pedidos=None):
    mlb = _texto(mlb).upper()
    if not mlb.startswith('MLB'):
        raise ErroColetaVendas(f'"{mlb}" não parece um MLB.')
    hoje = _hoje()
    if de is None and ate is None:
        dias = dias_padrao() if dias is None else dias
        _validar_dias(dias, hoje)
        de, ate = hoje - timedelta(days=dias), hoje
    elif de is None or ate is None or de > ate or ate > hoje or de < primeiro_dia_do_ml(hoje):
        raise ErroColetaVendas(f'O trecho pedido é inválido (precisa estar entre {primeiro_dia_do_ml(hoje):%d/%m/%Y} e hoje, com início antes do fim).')
    _garantir_sem_periodo(empresa)
    relatorio = RelatorioColetaVendas(
        escopo=ColetaVendasMercadoLivre.Escopo.MLB, alvo=mlb, data_de=de, data_ate=ate, iniciado_em=timezone.now(),
    )
    limite = max_pedidos if (max_pedidos and ate > de) else None
    # * [EXPLICAÇÃO] → A trava é por MLB + trecho: o mesmo trecho não roda 2 vezes ao mesmo tempo (clique duplo, outra aba), mas trechos
    #                  diferentes do mesmo MLB podem rodar juntos (o "Atualizar produto" lê vários trechos ao mesmo tempo).
    with _travar(empresa, f'{mlb}:{de:%Y%m%d}-{ate:%Y%m%d}'):
        try:
            api_ml = api_ml or _api(empresa)
            pedidos = _ler_intervalo(api_ml, relatorio, _inicio_do_dia(de), _inicio_do_dia(ate + timedelta(days=1)), mlb=mlb, max_pedidos=limite)
            _gravar_pedidos(relatorio, pedidos)
            relatorio.mensagem = _resumo(relatorio, f'{mlb} atualizado')
        except _JanelaGrande as grande:
            total = grande.args[0]
            raise JanelaGrande(total, dividir_janela(de, ate, max(2, ceil(total / (limite * FOLGA_DA_DIVISAO)))), relatorio.chamadas) from None
        except ErroAutenticacaoAPI as erro:
            relatorio.status = ColetaVendasMercadoLivre.Status.FALHA
            relatorio.mensagem = 'O Mercado Livre recusou o acesso (token inválido ou vencido). Nada foi gravado.'
            _registrar(relatorio, usuario, sku)
            erro.chamadas_feitas = relatorio.chamadas   # a view devolve para a tela somar no total do clique
            raise
        except ErroColetaVendas as erro:
            relatorio.status = ColetaVendasMercadoLivre.Status.FALHA
            relatorio.mensagem = f'{mlb}: {erro}{dica_de_borda(de, hoje)}'
        _registrar(relatorio, usuario, sku)
    return relatorio


# Função Objetivo: O PLANO do "Atualizar" (1 MLB ou o produto todo): para cada MLB, as faixas de dias que faltam buscar (ver dias_pendentes em
# cobertura_vendas_ml: dia nunca coletado, só parcial, ou dentro dos últimos 30 dias; "reler_tudo" = todos). Não chama o Mercado Livre.
# Devolve {'trechos': [{'mlb', 'de', 'ate', 'dias'}...], 'dias_total': (dias + 1) x MLBs, 'dias_a_coletar': o que vai ser lido, 'dias_de_revisao': 30}.
def planejar_trechos(mlbs, dias, reler_tudo=False, hoje=None):
    hoje = hoje or _hoje()
    _validar_dias(dias, hoje)
    de = hoje - timedelta(days=dias)
    coletas = carregar_coletas(de, hoje)
    trechos, a_coletar = [], 0
    for mlb in mlbs:
        pendentes = dias_pendentes(coletas, mlb, de, hoje, hoje, reler_tudo)
        a_coletar += len(pendentes)
        for inicio, fim in faixas_de_dias(pendentes):
            trechos.append({'mlb': mlb, 'de': inicio.isoformat(), 'ate': fim.isoformat(), 'dias': (fim - inicio).days + 1})
    return {'trechos': trechos, 'dias_total': (dias + 1) * len(mlbs), 'dias_a_coletar': a_coletar, 'dias_de_revisao': DIAS_DE_REVISAO}


# Função Objetivo: Coleta 1 dia INTEIRO da conta toda (todos os SKUs). Botão "Atualizar dia" da tela. Mesma regra de retorno de coletar_mlb.
def coletar_dia(empresa, dia: date, usuario='', api_ml=None):
    hoje = _hoje()
    if dia > hoje:
        raise ErroColetaVendas('Esse dia ainda não chegou.')
    if dia < primeiro_dia_do_ml(hoje):
        raise ErroColetaVendas(f'O Mercado Livre só guarda pedidos a partir de {primeiro_dia_do_ml(hoje):%d/%m/%Y}; esse dia ficou para trás.')
    _garantir_sem_periodo(empresa)
    relatorio = RelatorioColetaVendas(
        escopo=ColetaVendasMercadoLivre.Escopo.DIA, alvo=f'{dia:%Y-%m-%d}', data_de=dia, data_ate=dia, iniciado_em=timezone.now())
    with _travar(empresa, f'dia-{dia:%Y%m%d}'):
        try:
            api_ml = api_ml or _api(empresa)
            pedidos = _ler_intervalo(api_ml, relatorio, _inicio_do_dia(dia), _inicio_do_dia(dia + timedelta(days=1)))
            _gravar_pedidos(relatorio, pedidos)
            relatorio.mensagem = _resumo(relatorio, f'Dia {dia:%d/%m/%Y} atualizado')
        except ErroAutenticacaoAPI as erro:
            relatorio.status = ColetaVendasMercadoLivre.Status.FALHA
            relatorio.mensagem = 'O Mercado Livre recusou o acesso (token inválido ou vencido). Nada foi gravado.'
            _registrar(relatorio, usuario)
            _registrar_execucao(relatorio, ExecucaoColetaVendasMercadoLivre.Tipo.DIA, usuario, dia, dia, trechos=0, trechos_com_falha=1,
                                dias_total=1, dias_a_coletar=1)
            erro.chamadas_feitas = relatorio.chamadas   # a view devolve para a tela somar no total do clique
            raise
        except ErroColetaVendas as erro:
            relatorio.status = ColetaVendasMercadoLivre.Status.FALHA
            relatorio.mensagem = f'Dia {dia:%d/%m/%Y}: {erro}{dica_de_borda(dia, hoje)}'
        _registrar(relatorio, usuario)
        _registrar_execucao(relatorio, ExecucaoColetaVendasMercadoLivre.Tipo.DIA, usuario, dia, dia, dias_total=1, dias_a_coletar=1,
                            trechos=int(relatorio.status != ColetaVendasMercadoLivre.Status.FALHA),
                            trechos_com_falha=int(relatorio.status == ColetaVendasMercadoLivre.Status.FALHA))
    return relatorio


# ==================================================== varredura de período (conta toda, em segundo plano) ====================================================

def _chave(empresa):
    return CHAVE_CACHE_PERIODO.format(empresa=empresa)


def _chave_parar(empresa):
    return CHAVE_CACHE_PARAR.format(empresa=empresa)


# Função Objetivo: Quantas chamadas se espera para [hoje − `dias`, hoje] da conta toda: 1 + pedidos do dia / 50 por dia. Usa a média por dia
# do que já está no banco (últimos 30 dias gravados); sem dado, 4 páginas por dia (160 pedidos/dia medidos em 09/10/2026). É estimativa.
def _paginas_por_dia():
    from django.db.models import Count

    desde = _hoje() - timedelta(days=30)
    contagem = VendaItemMercadoLivre.objects.filter(dia_venda__gte=desde).aggregate(n=Count('order_id', distinct=True))['n'] or 0
    dias_com_dado = VendaItemMercadoLivre.objects.filter(dia_venda__gte=desde).values('dia_venda').distinct().count()
    paginas_por_dia = 1 + (contagem / dias_com_dado) / LIMITE_POR_PAGINA if dias_com_dado else 4
    return max(paginas_por_dia, 1)


def estimar_chamadas_do_periodo(dias, reler_tudo=False):
    a_ler = dias + 1 if reler_tudo else len(_dias_pendentes_da_conta(dias))
    return int(round(a_ler * _paginas_por_dia()))


# Função Objetivo: As opções da janela "Coletar período da conta" de uma vez só (poucas consultas ao banco): recebe os períodos de hoje
# (cobertura_vendas_ml.periodos_de_hoje) e devolve cada um com os dias que faltam, as chamadas e os minutos estimados — só o que falta e
# "reler tudo". `dias` = N para trás de hoje (o que a coleta recebe); `total_dias` = N + 1. É estimativa: usa o ritmo de pedidos por dia já gravado.
def estimar_opcoes_do_periodo(periodos):
    paginas = _paginas_por_dia()
    hoje = _hoje()
    coletas = carregar_coletas(hoje - timedelta(days=max(p['dias_para_tras'] for p in periodos)), hoje)

    def minutos(chamadas):
        return max(1, ceil(chamadas * SEGUNDOS_POR_CHAMADA_ESTIMADO / 60))

    opcoes = []
    for periodo in periodos:
        dias = periodo['dias_para_tras']
        pendentes = len(dias_pendentes(coletas, None, hoje - timedelta(days=dias), hoje, hoje))
        faltam, tudo = int(round(pendentes * paginas)), int(round((dias + 1) * paginas))
        opcoes.append({**periodo, 'dias': dias, 'dias_a_coletar': pendentes, 'chamadas': faltam, 'minutos': minutos(faltam),
                       'chamadas_tudo': tudo, 'minutos_tudo': minutos(tudo)})
    return opcoes


# Função Objetivo: Os dias de [hoje − `dias`, hoje] que a coleta da CONTA TODA ainda precisa buscar (do mais antigo ao mais novo): só coleta de dia/período
# cobre a conta toda, e a regra de "só o que falta" é a mesma do Atualizar por MLB (ver cobertura_vendas_ml.dias_pendentes).
def _dias_pendentes_da_conta(dias, reler_tudo=False):
    hoje = _hoje()
    de = hoje - timedelta(days=dias)
    return dias_pendentes(carregar_coletas(de, hoje), None, de, hoje, hoje, reler_tudo)


def periodo_em_andamento(empresa):
    estado = cache.get(_chave(empresa))
    if not estado or estado.get('status') != 'rodando':
        return None
    if time.time() - estado.get('atualizado_em', 0) > SEGUNDOS_SEM_PROGRESSO_PARA_CONSIDERAR_PARADA:
        return None
    return estado


# Função Objetivo: Começa a varredura do período [hoje − dias, hoje] (depois da confirmação na janela): grava o estado inicial e dispara a thread sem esperar.
# Só busca os dias que faltam (ver _dias_pendentes_da_conta); `reler_tudo` busca todos. Se já há uma rodando, devolve o estado dela.
# Devolve (estado, comecou_agora).
def iniciar_periodo(empresa, dias, usuario='', reler_tudo=False):
    _validar_dias(dias, _hoje())
    em_andamento = periodo_em_andamento(empresa)
    if em_andamento is not None:
        return em_andamento, False
    pendentes = _dias_pendentes_da_conta(dias, reler_tudo)
    agora = time.time()
    estado = {
        'status': 'rodando', 'rotulo': 'Preparando a coleta', 'atual': 0, 'total': len(pendentes), 'dia': '', 'parando': False,
        'pedidos': 0, 'itens': 0, 'chamadas': 0, 'erros_429': 0, 'iniciado_em': agora, 'atualizado_em': agora, 'decorrido': 0,
    }
    cache.delete(_chave_parar(empresa))
    cache.delete(_chave(empresa))
    if not cache.add(_chave(empresa), estado, timeout=TIMEOUT_ANDAMENTO_SEGUNDOS):
        return cache.get(_chave(empresa)) or estado, False
    # * [EXPLICAÇÃO] → A empresa é repassada: a empresa ativa vive num threading.local() que a thread nova não herda.
    threading.Thread(target=_rodar_periodo_em_thread, args=(empresa, dias, usuario, set(pendentes)), daemon=True).start()
    return estado, True


def pedir_parada(empresa):
    estado = periodo_em_andamento(empresa)
    if estado is None:
        return None
    cache.set(_chave_parar(empresa), True, timeout=TIMEOUT_ANDAMENTO_SEGUNDOS)
    estado = {**estado, 'parando': True, 'rotulo': 'Parando depois do dia atual'}
    cache.set(_chave(empresa), estado, timeout=TIMEOUT_ANDAMENTO_SEGUNDOS)
    return estado


# Função Objetivo: O estado para o "polling" da tela. Rodando: o andamento. Terminou ou deu erro: entrega o resultado UMA vez e o tira do cache.
def ler_estado_periodo(empresa):
    chave = _chave(empresa)
    estado = cache.get(chave)
    if not estado:
        return {'status': 'ocioso'}
    if estado.get('status') == 'rodando':
        if periodo_em_andamento(empresa) is None:
            cache.delete(chave)
            return {'status': 'erro', 'mensagem': 'A coleta anterior parou sem terminar (provavelmente o servidor foi reiniciado). Os dias já '
                                                  'coletados ficaram salvos. Você pode começar outra.'}
        return estado
    cache.delete(chave)
    return estado


def _rodar_periodo_em_thread(empresa, dias, usuario, pendentes):
    import traceback

    from django.db import connections

    definir_empresa_ativa(empresa)
    chave, chave_parar = _chave(empresa), _chave_parar(empresa)
    inicio = time.time()
    hoje = _hoje()
    relatorio = RelatorioColetaVendas(
        escopo=ColetaVendasMercadoLivre.Escopo.PERIODO, alvo=f'{dias + 1} dias', data_de=hoje - timedelta(days=dias), data_ate=hoje,
        iniciado_em=timezone.now())
    estado = {
        'status': 'rodando', 'rotulo': 'Consultando o Mercado Livre', 'atual': 0, 'total': len(pendentes), 'dia': '', 'parando': False,
        'pedidos': 0, 'itens': 0, 'chamadas': 0, 'erros_429': 0, 'iniciado_em': inicio, 'atualizado_em': inicio, 'decorrido': 0,
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
        estado['parando'] = bool(cache.get(chave_parar))
        estado['rotulo'] = 'Parando depois do dia atual' if estado['parando'] else 'Consultando o Mercado Livre'
        estado['pedidos'], estado['itens'] = relatorio.pedidos_lidos, relatorio.itens_gravados
        estado['chamadas'], estado['erros_429'] = relatorio.chamadas, relatorio.erros_429
        estado['decorrido'] = int(agora - inicio)
        gravar(dict(estado))

    def parar():
        return bool(cache.get(chave_parar))

    ultimo_dia_completo = None
    trechos_lidos = 0   # dias que terminaram por completo (vira `trechos` na execução registrada ao final)
    try:
        api_ml = _api(empresa)
        gravar_andamento(forcar=True)
        interrompida, erro_texto = False, ''
        n_lidos = 0
        for posicao in range(dias + 1):
            if parar():
                interrompida = True
                break
            dia = hoje - timedelta(days=posicao)
            if dia not in pendentes:
                # Já coletado COMPLETO antes e fora dos últimos DIAS_DE_REVISAO dias: não volta do Mercado Livre. Conta como coberto.
                ultimo_dia_completo = dia
                relatorio.dias_pulados += 1
                continue
            n_lidos += 1
            estado['atual'], estado['dia'] = n_lidos, f'{dia:%d/%m/%Y}'
            try:
                pedidos = _ler_intervalo(api_ml, relatorio, _inicio_do_dia(dia), _inicio_do_dia(dia + timedelta(days=1)), parar=parar)
            except _Interrompida:
                interrompida = True
                break
            except ErroColetaVendas as erro:
                erro_texto = f'Parou no dia {dia:%d/%m/%Y}: {erro}{dica_de_borda(dia, hoje)}'
                break
            _gravar_pedidos(relatorio, pedidos)
            ultimo_dia_completo = dia
            trechos_lidos += 1
            gravar_andamento()
        gravar_andamento(forcar=True)
    except ErroAutenticacaoAPI:
        traceback.print_exc()
        erro_texto, interrompida = 'O Mercado Livre recusou o acesso (token inválido ou vencido).', False
    except Exception as erro:
        # * [EXPLICAÇÃO] → Mantido de propósito: falha em segundo plano que passa em silêncio é impossível de investigar depois.
        traceback.print_exc()
        erro_texto, interrompida = f'Falha inesperada: {erro}. O detalhe está no terminal do servidor.', False

    try:
        completa = ultimo_dia_completo is not None and ultimo_dia_completo == relatorio.data_de and not interrompida and not erro_texto
        if ultimo_dia_completo is None:
            relatorio.status = ColetaVendasMercadoLivre.Status.FALHA
        else:
            relatorio.data_de = ultimo_dia_completo
            relatorio.status = ColetaVendasMercadoLivre.Status.CONCLUIDA if completa else ColetaVendasMercadoLivre.Status.PARCIAL
        duracao = int(time.time() - inicio)
        tempo = f'{duracao // 60} min {duracao % 60:02d} s' if duracao >= 60 else f'{duracao} s'
        if ultimo_dia_completo is None:
            relatorio.data_de = hoje - timedelta(days=dias)
            relatorio.mensagem = erro_texto or 'Coleta interrompida antes de concluir o primeiro dia; nada ficou coberto.'
        else:
            abertura = 'Coleta concluída' if completa else ('Coleta interrompida a pedido' if interrompida else 'Coleta parou')
            relatorio.mensagem = f'{abertura} em {tempo}. ' + _resumo(relatorio, 'Conta toda') + (f' {erro_texto}' if erro_texto else '')
        _registrar(relatorio, usuario)
        _registrar_execucao(relatorio, ExecucaoColetaVendasMercadoLivre.Tipo.PERIODO, usuario, hoje - timedelta(days=dias), hoje, trechos=trechos_lidos,
                            trechos_com_falha=1 if erro_texto else 0, dias_total=dias + 1, dias_a_coletar=len(pendentes), segundos=duracao)
        gravar({
            'status': 'erro' if (erro_texto and ultimo_dia_completo is None) else 'concluido', 'mensagem': relatorio.mensagem,
            'interrompida': interrompida, 'completa': completa, 'com_aviso': bool(erro_texto or relatorio.avisos),
            'pedidos': relatorio.pedidos_lidos, 'itens': relatorio.itens_gravados, 'chamadas': relatorio.chamadas,
            'erros_429': relatorio.erros_429, 'duracao_segundos': duracao,
        }, TIMEOUT_RESULTADO_SEGUNDOS)
    except Exception:
        traceback.print_exc()
        gravar({'status': 'erro', 'mensagem': 'A coleta parou por um erro inesperado ao registrar o resultado. O detalhe está no terminal.'},
               TIMEOUT_RESULTADO_SEGUNDOS)
    finally:
        cache.delete(chave_parar)
        connections.close_all()
