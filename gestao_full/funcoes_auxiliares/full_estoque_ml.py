# gestao_full/funcoes_auxiliares/full_estoque_ml.py
#
# Monta a tela "Full — Estoque no Full" (Mercado Livre → Full → Estoque no Full): para cada PRODUTO, quanto
# estoque ele tem hoje no Full, somando os Códigos ML dele. É a tela de CONSULTA ("quanto temos?"); a tela de
# Planejamento de envios responde "quanto enviar?".
#
# REGRA DO MATHEUS: esta tela NUNCA chama a API do ML SOZINHA. Abrir, buscar, filtrar, ordenar e paginar só LEEM do banco:
#   * produto -> Códigos ML: variacao.inventory_id (gravado pelo importar_anuncios_ml desde 07/10/2026);
#   * os números: a consulta mais recente de cada Código ML (ConsultaFullMercadoLivre). Sem consulta não há número — a
#     tela diz isso e não inventa.
# A API só é chamada por CLIQUE, nos botões "Atualizar" (um Código ML), "Atualizar produto" e "Fazer varredura completa".
# Quem chama é gestao_full/funcoes_auxiliares/full_estoque_varredura.py e a view; ESTE arquivo continua só lendo o banco
# (e remontando um produto depois que o número dele mudou: montar_um_produto).
#
# * [EXPLICAÇÃO] → O estoque pertence ao CÓDIGO ML, não ao anúncio: dois anúncios do mesmo Código ML mostram o
#                  mesmo valor. Por isso o total de um produto é a soma dos seus CÓDIGOS (nunca dos anúncios, que
#                  contaria em dobro). Um Código só entra na soma depois de consultado; enquanto algum Código do
#                  produto não foi consultado, o total aparece como PARCIAL.
# * [EXPLICAÇÃO] → O número em destaque é o "Total no estoque do Full" (ESTOQUE total): tudo que está fisicamente
#                  lá. Ele se divide em "Disponível para venda" + "Indisponível" (com o motivo). A "Soma geral"
#                  (REPOS stock.total_stock, que o Mercado Livre chama de "aptas e a caminho") é outro número, de outra consulta, e é
#                  Total no Full + A caminho; a parte "A CAMINHO" tem coluna própria e é HIPÓTESE (REPOS menos ESTOQUE) até a equipe
#                  conferir com a tela do Mercado Livre. As colunas, da esquerda para a direita: Total no Full | Disponível para venda |
#                  Indisponível | A caminho | Soma geral | Consulta (barra de colunas, linha do produto e cartão do Código usam as mesmas).
# * [EXPLICAÇÃO] → O cartão de cada Código ML mostra, além disso, 3 blocos que respondem "onde está o estoque?" (08/10/2026):
#                    1) PRONTO PRA VENDA NO FULL  = ESTOQUE available_quantity (exato, vem do ML);
#                    2) NO FLEX (seu depósito)    = FLEX locations[type != "meli_facility"].quantity, a soma do que o vendedor guarda fora do
#                       Full (exato, vem do ML; o selo diz que ainda não foi conferido com o estoque real);
#                    3) A CAMINHO DO FULL         = (a) EM TRANSFERÊNCIA: ESTOQUE not_available_detail "transfer" — já está dentro do Total no
#                       Full, só não pode ser vendida ainda (exato); (b) ENVIADAS E AINDA NÃO RECEBIDAS: "Soma geral" menos "Total no
#                       Full" (estimativa/hipótese — o ML não manda esse número pronto).
#                  O depósito é do SKU, não do Código ML nem do produto do vendedor (user_product_id): fisicamente existem X unidades do SKU e o
#                  ERP manda esse MESMO X para todos os anúncios do SKU, então o ML devolve o mesmo número em cada produto do vendedor (confirmado
#                  em 08/10/2026: o pulverizador tem 13 produtos do vendedor e todos mostram 27). Por isso a soma conta cada LOJA uma vez só
#                  (deposito_por_loja), dentro do Código e entre os Códigos do produto. Se a mesma loja trouxer quantidades diferentes (o ERP
#                  sincroniza os anúncios em horários diferentes), vale a maior e a tela avisa (deposito_aviso).

import unicodedata
from datetime import datetime, timezone as fuso

from django.core.paginator import Paginator
from django.urls import reverse
from django.http import QueryDict
from django.utils import timezone
from django.utils.http import urlencode

from gestao_full.funcoes_auxiliares.full_ml import MOTIVO_INDISPONIVEL, _fmt_preco, _n_br, pegar
from gestao_full.funcoes_auxiliares.full_planejamento_ml import RANK_STATUS, _meta_do_campo
from mercado_livre.funcoes_auxiliares.badges import (
    BADGES_CATALOGO, BADGES_CONFERENCIA_FULL, BADGES_ESTOQUE_FULL, BADGES_LOGISTICA, BADGES_STATUS, BADGES_TIPO_ANUNCIO,
    badge_de, badge_flex,
)

# * [EXPLICAÇÃO] → Depois de quantas horas uma consulta salva é considerada "desatualizada". O estoque do Full muda
#                  o dia todo; 24 h é um ponto de partida — ajuste aqui se a equipe quiser outro prazo.
HORAS_PARA_DESATUALIZADO = 24
# * [EXPLICAÇÃO] → Quantos produtos aparecem por página: a pessoa escolhe entre as opções; sem escolha vale o padrão.
POR_PAGINA_PADRAO = 25
OPCOES_POR_PAGINA = (25, 50, 100, 200)
# Com poucos produtos na lista (ex.: depois de buscar um SKU) os Códigos ML já vêm abertos.
LIMITE_PARA_ABRIR_SOZINHO = 3
# Valor que a URL leva para "só os produtos sem marca cadastrada".
SEM_MARCA = '(sem marca)'

# * [EXPLICAÇÃO] → Filtros: (chave, rótulo, grupo). O grupo só organiza os botões na tela; só um filtro vale por vez.
FILTROS = (
    ('todos', 'Todos', ''),
    ('com_indisponivel', 'Com indisponível', 'Estoque'),
    ('sem_disponivel', 'Sem disponível para venda', 'Estoque'),
    ('zerados', 'Zerados no Full', 'Estoque'),
    ('desatualizados', 'Consulta desatualizada', 'Consulta'),
    ('faltam_consultas', 'Faltam consultas', 'Consulta'),
    ('com_erro', 'Consulta com erro', 'Consulta'),
    ('repos_erro', 'Reposição com erro', 'Consulta'),
    ('nao_bate', 'Total não bate', 'Conferir'),
    ('compartilhados', 'Código ML compartilhado', 'Conferir'),
    ('varios_codigos', 'Mais de um Código ML', 'Conferir'),
)

# * [EXPLICAÇÃO] → Ordenações: (chave, rótulo, grupo). O grupo vira um bloco no seletor "Ordenar por". Quem não tem número
#                  para a ordem escolhida (nunca consultado, por exemplo) vai SEMPRE para o fim; empates saem por título A–Z.
#                  As do grupo "Reposição" precisam ler a reposição de TODOS os Códigos da lista (e não só dos que cabem na
#                  página), por isso podem demorar um pouco mais — só pesam quando a pessoa as escolhe.
GRUPO_REPOSICAO = 'Reposição (lê mais dados: pode demorar um pouco mais)'
ORDENS = (
    ('total_desc', 'Total no Full — maior primeiro', 'Estoque'),
    ('total_asc', 'Total no Full — menor primeiro', 'Estoque'),
    ('disponivel_desc', 'Disponível para venda — maior primeiro', 'Estoque'),
    ('disponivel_asc', 'Disponível para venda — menor primeiro', 'Estoque'),
    ('indisponivel_desc', 'Indisponível — maior primeiro', 'Estoque'),
    ('indisponivel_asc', 'Indisponível — menor primeiro', 'Estoque'),
    ('pct_indisponivel_desc', 'Maior % indisponível do total', 'Estoque'),
    ('soma_desc', 'Soma geral — maior primeiro', GRUPO_REPOSICAO),
    ('soma_asc', 'Soma geral — menor primeiro', GRUPO_REPOSICAO),
    ('a_caminho_desc', 'A caminho — maior primeiro (hipótese)', GRUPO_REPOSICAO),
    ('a_caminho_asc', 'A caminho — menor primeiro (hipótese)', GRUPO_REPOSICAO),
    ('titulo', 'Título (A–Z)', 'Produto'),
    ('titulo_desc', 'Título (Z–A)', 'Produto'),
    ('sku', 'SKU (A–Z)', 'Produto'),
    ('marca', 'Marca (A–Z)', 'Produto'),
    ('codigos_desc', 'Mais Códigos ML primeiro', 'Produto'),
    ('consulta_antiga', 'Consulta mais antiga primeiro', 'Consulta'),
    ('consulta_recente', 'Consulta mais recente primeiro', 'Consulta'),
)
ORDENS_QUE_LEEM_REPOSICAO = {'soma_desc', 'soma_asc', 'a_caminho_desc', 'a_caminho_asc'}
# * [EXPLICAÇÃO] → A coluna "Aptas e a caminho" virou "Soma geral" (e ganhou a coluna "A caminho" ao lado). Quem salvou um link com a ordem antiga
#                  continua caindo na ordem certa, em vez de voltar para a padrão sem avisar.
ORDENS_RENOMEADAS = {'aptas_desc': 'soma_desc', 'aptas_asc': 'soma_asc'}
FILTRO_PADRAO = 'todos'
ORDEM_PADRAO = 'total_desc'

# * [EXPLICAÇÃO] → Clicar no título de uma coluna ordena por ela: o 1º clique usa a primeira ordem, o 2º inverte, o 3º volta.
ORDEM_DAS_COLUNAS = {
    'produto': ('titulo', 'titulo_desc'),
    'total': ('total_desc', 'total_asc'),
    'disponivel': ('disponivel_desc', 'disponivel_asc'),
    'indisponivel': ('indisponivel_desc', 'indisponivel_asc'),
    'a_caminho': ('a_caminho_desc', 'a_caminho_asc'),
    'soma': ('soma_desc', 'soma_asc'),
    'consulta': ('consulta_antiga', 'consulta_recente'),
}

# Os números que vêm direto do Mercado Livre: (chave, fonte, caminho do campo, rótulo). O selo de conferência de cada um vem do registro
# que a equipe preenche na ficha de debug (o mesmo das telas de Planejamento). A "Soma geral" é o número que o Mercado Livre chama de "aptas e a
# caminho" (REPOS stock.total_stock): a tela a mostra inteira e separa a parte "A caminho" na coluna ao lado (veja COLUNA_A_CAMINHO).
COLUNAS_FONTE = (
    ('total', 'ESTOQUE', 'total', 'Total no Full'),
    ('disponivel', 'ESTOQUE', 'available_quantity', 'Disponível para venda'),
    ('indisponivel', 'ESTOQUE', 'not_available_quantity', 'Indisponível'),
    ('soma', 'REPOS', 'stock.total_stock', 'Soma geral'),
)

BADGE_A_CAMINHO = BADGES_CONFERENCIA_FULL['hipotese']

# * [EXPLICAÇÃO] → "A caminho" NÃO vem do Mercado Livre: é a conta da tela (Soma geral menos Total no Full). Por isso a coluna não tem campo de
#                  API nem registro de conferência: o selo dela é sempre "Hipótese", até a equipe conferir com os envios abertos do Mercado Livre.
COLUNA_A_CAMINHO = {
    'rotulo': 'A caminho',
    'meta': {
        'fonte': 'conta da tela', 'caminho': 'Soma geral − Total no Full',
        'selo': {'badge': BADGE_A_CAMINHO,
                 'dica': 'Hipótese: o Mercado Livre não informa este número; a tela calcula Soma geral menos Total no Full. Ainda não foi conferido com os envios abertos.'},
    },
}

# * [EXPLICAÇÃO] → Selos dos números NOVOS do cartão do Código ML. Eles não vêm do registro da ficha (lá ainda não existem campos do Flex),
#                  então ficam aqui, num só lugar. Quando a equipe conferir o número com a realidade, troque 'a_validar' por 'valido' e o
#                  selo passa a dizer "Conferido" (ou 'invalido', se não bater).
SELO_DEPOSITO_FLEX = BADGES_CONFERENCIA_FULL['a_validar']
SELO_EM_TRANSFERENCIA = BADGES_CONFERENCIA_FULL['a_validar']

# * [EXPLICAÇÃO] → Estoque por local (FLEX user-products/{id}/stock): "meli_facility" é o estoque que está no Full; qualquer outro tipo é
#                  estoque do VENDEDOR fora do Full (a conta da Magazine devolve "seller_warehouse"). Tipo desconhecido aparece como veio.
LOCAL_DO_FULL = 'meli_facility'
ROTULO_DO_LOCAL = {'seller_warehouse': 'Depósito do vendedor', 'selling_address': 'Endereço de venda do vendedor', LOCAL_DO_FULL: 'Full'}
STATUS_EM_TRANSFERENCIA = 'transfer'
STATUS_PERDIDA = ('lost',)
STATUS_NAO_SUPORTADA = ('not_supported', 'notSupported')


# ---------------------------------------------------------------------------
# PEQUENAS AJUDAS
# ---------------------------------------------------------------------------
def _normalizar(texto):
    """'Água Limpa' -> 'agua limpa' (para a busca ignorar acento e maiúscula)."""
    return unicodedata.normalize('NFD', str(texto or '')).encode('ascii', 'ignore').decode('ascii').lower()


def _inteiro(valor):
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _n(valor):
    return '—' if valor is None else _n_br(valor)


def _idade(consultado_em, agora):
    """'há 3 h', 'há 12 min', 'há 2 dias'."""
    minutos = max(int((agora - consultado_em).total_seconds() // 60), 0)
    if minutos < 1:
        return 'agora há pouco'
    if minutos < 60:
        return f'há {minutos} min'
    horas = minutos // 60
    if horas < 48:
        return f'há {horas} h'
    return f'há {horas // 24} dias'


def _data_hora_completa(valor):
    return '' if valor is None else timezone.localtime(valor).strftime('%d/%m/%Y %H:%M')


# * [EXPLICAÇÃO] → MOTIVO_INDISPONIVEL escreve os motivos no singular ("danificada"). Com 1 unidade fica certo; com 5 não
#                  ("5 danificada"). Estes são os que mudam no plural; os outros ("em transferência") não mudam.
PLURAL_DO_MOTIVO = {'danificada': 'danificadas', 'perdida': 'perdidas', 'não suportada': 'não suportadas'}


def _texto_do_motivo(status, quantidade):
    """'danificada' com 5 unidades -> '5 danificadas'."""
    rotulo = MOTIVO_INDISPONIVEL.get(status, status)
    if quantidade != 1:
        rotulo = PLURAL_DO_MOTIVO.get(rotulo, rotulo)
    return f'{_n(quantidade)} {rotulo}'


def _motivos(detalhe):
    """[{"status": "transfer", "quantity": 2}] -> [{"status", "quantidade", "texto": "2 em transferência"}]. Motivo novo aparece como veio."""
    motivos = []
    if isinstance(detalhe, list):
        for item in detalhe:
            if isinstance(item, dict):
                quantidade = _inteiro(item.get('quantity'))
                status = item.get('status')
                motivos.append({'status': status, 'quantidade': quantidade,
                                'texto': _texto_do_motivo(status, quantidade)})
    return motivos


# Função Objetivo: Os motivos de indisponível de um PRODUTO: soma, por motivo, o que cada Código ML dele informou
# (3 em transferência no Código A + 2 no Código B = "5 em transferência"). Maior quantidade primeiro.
def _somar_motivos(cartoes):
    somas = {}
    for cartao in cartoes:
        for motivo in cartao['motivos']:
            if motivo['quantidade'] is not None:
                somas[motivo['status']] = somas.get(motivo['status'], 0) + motivo['quantidade']
    return [{'texto': _texto_do_motivo(status, quantidade)}
            for status, quantidade in sorted(somas.items(), key=lambda par: (-par[1], str(par[0])))]


# Função Objetivo: "6,5%" — quanto do total no Full está indisponível. Só aparece quando há indisponível; sem total não há conta.
def _pct_indisponivel(total, indisponivel):
    if not total or not indisponivel:
        return None
    return round(indisponivel / total * 100, 1)


def _pct_txt(pct):
    return '' if pct is None else f"{pct:.1f}".replace('.', ',') + '%'


def _soma(cartoes, campo):
    valores = [c[campo] for c in cartoes if c['estado'] == 'ok' and c[campo] is not None]
    return sum(valores) if valores else None


# Função Objetivo: Quantas unidades estão "em transferência" entre os motivos do indisponível (ESTOQUE not_available_detail, status "transfer").
# Sem esse motivo na lista, o ML está dizendo que são 0.
def _em_transferencia(motivos):
    return sum(m['quantidade'] for m in motivos if m['status'] == STATUS_EM_TRANSFERENCIA and m['quantidade'] is not None)


# Função Objetivo: Quantas unidades de um (ou mais) motivo do indisponível o Código tem ("lost", "notSupported"...). Sem esse motivo, são 0.
def _quantidade_do_motivo(motivos, status):
    return sum(m['quantidade'] for m in motivos if m['status'] in status and m['quantidade'] is not None)


def _data_do_ml(texto):
    """'2026-10-08T00:05:09Z' -> datetime com fuso (None se o texto não for uma data)."""
    try:
        return datetime.fromisoformat(str(texto).replace('Z', '+00:00'))
    except ValueError:
        return None


# Função Objetivo: O texto do aviso quando a MESMA loja do depósito vem com quantidades diferentes ("diverge" = {chave: [valores]}, "rotulos" = {chave: rótulo},
# "quem" = "Os produtos deste Código" ou "Os Códigos deste produto"). Vazio quando nada diverge.
def _aviso_divergencia(diverge, rotulos, quem):
    if not diverge:
        return ''
    partes = [f"{rotulos.get(chave, 'Depósito')}: {' e '.join(_n(v) for v in sorted(valores))}" for chave, valores in sorted(diverge.items())]
    return (f"{quem} trazem quantidades diferentes para a mesma loja ({'; '.join(partes)}). O ERP atualiza os anúncios em horários diferentes: a conta usa "
            f"a maior. Use o Atualizar para conferir.")


# Função Objetivo: O estoque do DEPÓSITO do vendedor (o "Flex") de 1 Código ML, lido da consulta FLEX salva ({user_product_id: pacote}). A lista
# "locations" do ML traz um item por local; "meli_facility" é o Full e todo o resto é estoque do vendedor fora do Full. Local com status diferente de
# "active" aparece na lista mas NÃO entra na soma. O depósito é do SKU: o ERP manda o MESMO estoque para todos os anúncios, então vários produtos do
# vendedor (user_product_id) devolvem a MESMA loja com a MESMA quantidade. Por isso cada LOJA (tipo + store_id) entra UMA vez só; se as respostas trouxerem
# quantidades diferentes para a mesma loja, vale a maior e o aviso (deposito_aviso) diz isso. "deposito_por_loja" ({chave: quantidade}, só as ativas) é
# o que a soma do produto usa para não contar a mesma loja duas vezes entre Códigos. "disponivel_full" (o disponível do ESTOQUE, ou None) serve só para
# conferir com o que o próprio Flex diz que está no Full. "flex_estado": "ok" | "parcial" (algum produto do vendedor falhou) | "erro" (todos falharam) |
# "sem_consulta" (a consulta salva não tem o Flex — é anterior ao campo, ou o Código não tem produto do vendedor).
def _flex_do_codigo(flex, disponivel_full):
    resultado = {
        'flex_estado': 'sem_consulta', 'flex_erro': '', 'flex_aviso': '', 'flex_atualizado_ml': '',
        'deposito': None, 'deposito_txt': '—', 'deposito_por_loja': {}, 'deposito_rotulos': {}, 'deposito_diverge': {}, 'deposito_aviso': '',
        'deposito_repetido': False, 'deposito_locais': [],
        'flex_no_full': None, 'flex_confere': None,
    }
    if not flex:
        return resultado
    erros, lidos, modos = [], 0, set()
    lojas, no_full, atualizacoes = {}, None, []
    for user_product_id, pacote in sorted(flex.items()):
        pacote = pacote or {}
        dados = pacote.get('dados')
        lista = dados.get('locations') if isinstance(dados, dict) else None
        if pacote.get('erro') or not isinstance(lista, list):
            texto = ' '.join(str(pacote.get('erro') or 'a resposta não trouxe a lista de locais ("locations")').split())[:MAX_TEXTO_ERRO_REPOSICAO]
            erros.append(f'{user_product_id}: {texto}')
            continue
        lidos += 1
        sem_identificacao = {}
        for local in lista:
            quantidade = _inteiro(local.get('quantity')) if isinstance(local, dict) else None
            if quantidade is None:
                continue
            tipo = str(local.get('type') or '')
            if tipo == LOCAL_DO_FULL:
                no_full = (no_full or 0) + quantidade
                continue
            ativo = str(local.get('status') or 'active') == 'active'
            rotulo = ROTULO_DO_LOCAL.get(tipo, tipo or 'Local sem tipo')
            if local.get('store_id'):
                rotulo += f" · loja {local['store_id']}"
            identificacao = str(local.get('store_id') or local.get('network_node_id') or '')
            if not identificacao:
                # Sem loja nem nó, o local só se distingue pela posição na lista (o 1º sem identificação, o 2º...) dentro do mesmo tipo.
                sem_identificacao[tipo] = sem_identificacao.get(tipo, 0) + 1
                identificacao = f'#{sem_identificacao[tipo]}'
            loja = lojas.setdefault(f'{tipo}|{identificacao}', {'rotulo': rotulo, 'ativos': [], 'inativos': []})
            loja['ativos' if ativo else 'inativos'].append(quantidade)
        if dados.get('stock_mode') not in (None, 'countable'):
            modos.add(str(dados.get('stock_mode')))
        atualizado = _data_do_ml(dados.get('last_updated'))
        if atualizado is not None:
            atualizacoes.append(atualizado)

    resultado['flex_erro'] = ' | '.join(erros)
    if not lidos:
        resultado['flex_estado'] = 'erro'
        return resultado
    resultado['flex_estado'] = 'parcial' if erros else 'ok'
    por_loja, rotulos, diverge, locais = {}, {}, {}, []
    for chave, loja in sorted(lojas.items()):
        ativa = bool(loja['ativos'])
        quantidade = max(loja['ativos'] if ativa else loja['inativos'])
        if ativa:
            por_loja[chave] = quantidade
            rotulos[chave] = loja['rotulo']
            if len(set(loja['ativos'])) > 1:
                diverge[chave] = sorted(set(loja['ativos']))
        locais.append({'rotulo': loja['rotulo'], 'quantidade': quantidade, 'quantidade_txt': _n(quantidade), 'ativo': ativa})
    resultado['deposito_por_loja'] = por_loja
    resultado['deposito_rotulos'] = rotulos
    resultado['deposito_diverge'] = diverge
    resultado['deposito_aviso'] = _aviso_divergencia(diverge, rotulos, 'Os produtos deste Código')
    resultado['deposito'] = sum(por_loja.values())
    resultado['deposito_txt'] = _n(resultado['deposito'])
    resultado['deposito_locais'] = locais
    if modos:
        resultado['flex_aviso'] = (f'O Mercado Livre informa este estoque no modo "{", ".join(sorted(modos))}" (e não "countable"): '
                                   f'o número pode não representar unidades contadas.')
    resultado['flex_atualizado_ml'] = _data_hora_completa(max(atualizacoes)) if atualizacoes else ''
    resultado['flex_no_full'] = no_full
    if no_full is not None and disponivel_full is not None:
        bate = no_full == disponivel_full
        resultado['flex_confere'] = {
            'bate': bate,
            'texto': (f'O Flex também mostra {_n(no_full)} no Full: confere com o disponível para venda.' if bate else
                      f'O Flex mostra {_n(no_full)} no Full, mas o estoque do Full diz {_n(disponivel_full)} disponíveis. '
                      f'As duas respostas podem ser de horários um pouco diferentes: use o Atualizar deste Código.'),
        }
    return resultado


# ---------------------------------------------------------------------------
# BANCO (as únicas funções deste arquivo que tocam o banco — só leitura)
# ---------------------------------------------------------------------------
# Função Objetivo: Quais Códigos ML cada SKU tem, segundo o banco: {sku: {CÓDIGO_MAIÚSCULO: {"codigo", "mlbs"}}}.
# O SKU é o do Produto ligado à variação; se a variação não achou Produto, o sku_ml dela; se nem isso, "".
def _ler_codigos_por_sku():
    from mercado_livre.models import VariacaoAnuncioMercadoLivre

    linhas = (VariacaoAnuncioMercadoLivre.objects
              .exclude(inventory_id__isnull=True).exclude(inventory_id='')
              .values_list('inventory_id', 'produto_id', 'sku_ml', 'anuncio__mlb'))
    por_sku = {}
    for inventory_id, produto_id, sku_ml, mlb in linhas:
        codigo = str(inventory_id).strip()
        if not codigo:
            continue
        sku = str(produto_id or sku_ml or '').strip()
        item = por_sku.setdefault(sku, {}).setdefault(codigo.upper(), {'codigo': codigo, 'mlbs': set()})
        item['mlbs'].add(mlb)
    return por_sku


def _ler_cadastro(skus):
    from produtos.models import Produto

    skus = sorted({s for s in skus if s})
    produtos = Produto.objects.filter(sku__in=skus).only('sku', 'ean', 'titulo', 'marca', 'cod_fabricante', 'estoque', 'imagem_url')
    return {p.sku: {'sku': p.sku, 'ean': p.ean or '', 'titulo': p.titulo or '', 'marca': p.marca or '',
                    'cod_fabricante': p.cod_fabricante or '', 'estoque': p.estoque, 'imagem_url': p.imagem_url or ''}
            for p in produtos}


# Função Objetivo: A consulta MAIS RECENTE de cada Código ML ({CÓDIGO_MAIÚSCULO: consulta}). Só traz o estoque (pequeno);
# a reposição, que é maior, só é lida para os produtos da página (_preencher_aptas).
# * [EXPLICAÇÃO] → Cada consulta grava uma linha NOVA (o histórico é guardado), e uma varredura completa grava uma por Código. Com o tempo
#                  cada Código tem dezenas de linhas. Por isso são 2 buscas: a 1ª descobre só o id da última linha de cada Código; a 2ª lê
#                  exatamente essas linhas. Ler o histórico inteiro para ficar só com a última deixaria a tela mais lenta a cada varredura.
def _ler_ultimas_consultas(codigos_maiusculos):
    from django.db.models import Max
    from mercado_livre.models import ConsultaFullMercadoLivre

    ultimos_ids = list(ConsultaFullMercadoLivre.objects.filter(codigo__in=sorted(codigos_maiusculos))
                       .order_by().values('codigo').annotate(ultimo=Max('id')).values_list('ultimo', flat=True))
    ultimas = {}
    for consulta in ConsultaFullMercadoLivre.objects.filter(pk__in=ultimos_ids).only('id', 'codigo', 'consultado_em', 'estoque'):
        ultimas.setdefault(consulta.codigo.upper(), consulta)
    return ultimas


# * [EXPLICAÇÃO] → "Reposição com erro" = o ESTOQUE do Código ML veio, mas a consulta de REPOSIÇÃO (a que traz a "Soma geral" e o "A caminho") falhou na última
#                  consulta. O Mercado Livre responde as duas separadamente, então uma pode falhar sem a outra (e o Código fica com número de estoque
#                  e "—" na Soma geral e no A caminho). Para o botão de filtro e a contagem valerem para a lista INTEIRA, é preciso olhar a coluna "reposicao" da última consulta
#                  de TODOS os Códigos — a parte grande. Como uma consulta já gravada nunca é alterada, o resultado de cada uma (texto do erro, ou vazio
#                  quando está tudo certo) é guardado no cache pelo id dela: só a consulta NOVA precisa ser lida. Um único item de cache por empresa guarda
#                  só as últimas consultas atuais (some o que ficou velho), então ele nunca cresce.
CHAVE_CACHE_ERROS_REPOSICAO = 'full_estoque_erros_reposicao_{empresa}'
TIMEOUT_CACHE_ERROS_REPOSICAO = 7 * 24 * 3600
MAX_TEXTO_ERRO_REPOSICAO = 200


# Função Objetivo: O texto do erro da reposição de UMA consulta salva ("" quando não houve erro). A consulta guarda 1 pacote por produto do
# vendedor (user_product_id) do Código; o pacote que falhou tem "erro" (ou veio sem dados). Código sem nenhum produto do vendedor não tem pacote:
# não há o que consultar, então também não é erro.
def _texto_do_erro_de_reposicao(reposicao):
    partes = []
    for user_product_id, pacote in sorted((reposicao or {}).items()):
        pacote = pacote or {}
        if pacote.get('erro') or pacote.get('dados') is None:
            erro = ' '.join(str(pacote.get('erro') or 'sem resposta').split())[:MAX_TEXTO_ERRO_REPOSICAO]
            partes.append(f'{user_product_id}: {erro}')
    return ' | '.join(partes)


# Função Objetivo: {CÓDIGO_MAIÚSCULO: texto do erro} só dos Códigos cuja última consulta teve erro na reposição. "ultimas" é o que
# _ler_ultimas_consultas devolveu. Com guardar_no_cache=False (poucos Códigos, ex.: 1 produto redesenhado) lê direto e não mexe no cache.
def _ler_erros_de_reposicao(ultimas, guardar_no_cache=True):
    from django.core.cache import cache
    from core.empresa import obter_empresa_ativa
    from mercado_livre.models import ConsultaFullMercadoLivre

    codigo_da_consulta = {consulta.pk: codigo for codigo, consulta in ultimas.items()}
    if not codigo_da_consulta:
        return {}
    chave = CHAVE_CACHE_ERROS_REPOSICAO.format(empresa=obter_empresa_ativa())
    guardados = {}
    if guardar_no_cache:
        try:
            guardados = cache.get(chave) or {}
        except Exception:
            guardados = {}
    texto_da_consulta = {pk: guardados[pk] for pk in codigo_da_consulta if pk in guardados}
    faltam = [pk for pk in codigo_da_consulta if pk not in texto_da_consulta]
    if faltam:
        for consulta in ConsultaFullMercadoLivre.objects.filter(pk__in=faltam).only('id', 'reposicao'):
            texto_da_consulta[consulta.pk] = _texto_do_erro_de_reposicao(consulta.reposicao)
        if guardar_no_cache:
            try:
                cache.set(chave, texto_da_consulta, timeout=TIMEOUT_CACHE_ERROS_REPOSICAO)
            except Exception:
                pass
    return {codigo_da_consulta[pk]: texto for pk, texto in texto_da_consulta.items() if texto}


# ---------------------------------------------------------------------------
# OS NÚMEROS DE 1 CÓDIGO ML
# ---------------------------------------------------------------------------
# Função Objetivo: O que a consulta salva diz do estoque de 1 Código ML. "estado": "ok" (tem número), "sem_consulta"
# (ninguém consultou) ou "erro" (consultou, mas o ML não devolveu o estoque). "repos_erro" é o texto do erro da consulta de REPOSIÇÃO
# (vem de _ler_erros_de_reposicao); só vale quando o estoque veio (estado "ok") — se o estoque também falhou, o aviso que importa é o dele.
def _numeros_do_codigo(codigo, consulta, agora, repos_erro=''):
    cartao = {
        'codigo': codigo, 'estado': 'sem_consulta', 'erro': '', 'repos_erro': '', 'consultado_em': None, 'idade': '', 'consultado_completo': '',
        'desatualizado': False, 'total': None, 'disponivel': None, 'indisponivel': None, 'motivos': [], 'conferencia': None,
        'aptas': None, 'aptas_txt': '—', 'a_caminho': None, 'a_caminho_txt': '', 'a_caminho_qtd_txt': '—', 'aptas_nota': '', 'pct_indisponivel_txt': '',
        'soma_geral': None, 'soma_geral_txt': '—', 'soma_conta_txt': '',
        'em_transferencia': None, 'em_transferencia_txt': '—',
        'selo_deposito': SELO_DEPOSITO_FLEX, 'selo_em_transferencia': SELO_EM_TRANSFERENCIA, 'selo_a_caminho': BADGE_A_CAMINHO,
        'tem_locais': False,
        **_flex_do_codigo(None, None),
    }
    if consulta is not None:
        cartao['consultado_em'] = consulta.consultado_em
        cartao['idade'] = _idade(consulta.consultado_em, agora)
        cartao['consultado_completo'] = _data_hora_completa(consulta.consultado_em)
        cartao['desatualizado'] = (agora - consulta.consultado_em).total_seconds() > HORAS_PARA_DESATUALIZADO * 3600

        pacotes = {str(chave).upper(): pacote for chave, pacote in (consulta.estoque or {}).items()}
        pacote = pacotes.get(codigo.upper())
        if not pacote:
            cartao['estado'], cartao['erro'] = 'erro', 'A consulta salva não trouxe o estoque deste Código ML.'
        elif pacote.get('erro') or pacote.get('dados') is None:
            cartao['estado'], cartao['erro'] = 'erro', str(pacote.get('erro') or 'sem resposta')
        else:
            dados = pacote['dados']
            cartao['estado'] = 'ok'
            cartao['total'] = _inteiro(pegar(dados, 'total'))
            cartao['disponivel'] = _inteiro(pegar(dados, 'available_quantity'))
            cartao['indisponivel'] = _inteiro(pegar(dados, 'not_available_quantity'))
            cartao['motivos'] = _motivos(pegar(dados, 'not_available_detail'))
            cartao['em_transferencia'] = _em_transferencia(cartao['motivos'])
            cartao['em_transferencia_txt'] = _n(cartao['em_transferencia'])
            total, disponivel, indisponivel = cartao['total'], cartao['disponivel'], cartao['indisponivel']
            if None not in (total, disponivel, indisponivel):
                soma = disponivel + indisponivel
                bate = total == soma
                cartao['conferencia'] = {
                    'bate': bate,
                    'texto': (f'Total {_n(total)} = disponível {_n(disponivel)} + indisponível {_n(indisponivel)}' if bate else
                              f'Total ({_n(total)}) não bate com disponível ({_n(disponivel)}) + indisponível ({_n(indisponivel)}) = {_n(soma)}'),
                }
    if cartao['estado'] == 'ok':
        cartao['repos_erro'] = repos_erro or ''
    for campo in ('total', 'disponivel', 'indisponivel'):
        cartao[f'{campo}_txt'] = _n(cartao[campo]) if cartao['estado'] == 'ok' else '—'
    cartao['pct_indisponivel_txt'] = _pct_txt(_pct_indisponivel(cartao['total'], cartao['indisponivel']))
    cartao['status'] = ('desatualizado' if cartao['desatualizado'] else 'atualizado') if cartao['estado'] == 'ok' else cartao['estado']
    cartao['badge'] = BADGES_ESTOQUE_FULL[cartao['status']]
    return cartao


# Função Objetivo: "Soma geral" e "A caminho" de 1 Código ML, a partir da consulta de REPOSIÇÃO salva (REPOS stock.total_stock, que o Mercado Livre
# chama de "aptas e a caminho"). A SOMA GERAL é esse número inteiro; o A CAMINHO é só a parte dele que passa do Total no Full (Soma geral menos Total
# no Full) e é só HIPÓTESE. Quando os dois fecham (Total no Full + A caminho = Soma geral) a tela mostra a conta. Se o Mercado Livre manda MENOS que o
# Total no Full, não existe "a caminho negativo": A caminho e Soma geral ficam sem número e o aviso explica, com os números e a causa provável (unidade
# perdida ou não suportada, que o ML não conta nas aptas). Se o Código tem mais de um produto do vendedor com valores diferentes, não escolho um:
# aviso e deixo para o Planejamento. "perdidas" e "nao_suportadas" são as quantidades desses 2 motivos do indisponível do próprio Código.
def _aptas_do_codigo(reposicao, total, perdidas=0, nao_suportadas=0):
    sem_numero = {'aptas': None, 'aptas_txt': '—', 'a_caminho': None, 'a_caminho_txt': '', 'a_caminho_qtd_txt': '—',
                  'soma_geral': None, 'soma_geral_txt': '—', 'soma_conta_txt': '', 'aptas_nota': ''}
    valores = []
    for pacote in (reposicao or {}).values():
        dados = (pacote or {}).get('dados')
        valor = _inteiro(pegar(dados, 'stock.total_stock')) if dados else None
        if valor is not None:
            valores.append(valor)
    if not valores:
        return {**sem_numero, 'aptas_nota': 'Sem consulta de reposição salva para este Código ML.'}
    if len(set(valores)) > 1:
        return {**sem_numero, 'aptas_nota': 'Há mais de um produto do vendedor neste Código ML, com valores diferentes — veja o Planejamento.'}
    aptas = valores[0]
    resultado = {**sem_numero, 'aptas': aptas, 'aptas_txt': _n(aptas)}
    if total is not None:
        if aptas >= total:
            a_caminho = aptas - total
            resultado.update({'a_caminho': a_caminho, 'a_caminho_txt': f'+{_n(a_caminho)}' if a_caminho else '', 'a_caminho_qtd_txt': _n(a_caminho),
                              'soma_geral': aptas, 'soma_geral_txt': _n(aptas), 'soma_conta_txt': f'{_n(total)} + {_n(a_caminho)}'})
        else:
            resultado['aptas_nota'] = _nota_aptas_menor_que_total(aptas, total, perdidas, nao_suportadas)
    return resultado


# Função Objetivo: O aviso de quando a reposição (Soma geral) veio MENOR que o Total no Full: diz os dois números, a diferença e se ela é explicada
# pelas unidades perdidas/não suportadas do próprio Código (o ML não as conta nas aptas: em OPXW24140, 95 no total e 94 nas aptas, com 1 perdida).
def _nota_aptas_menor_que_total(aptas, total, perdidas, nao_suportadas):
    diferenca = total - aptas
    texto = f'O Mercado Livre contou {_n(aptas)} aptas, {_n(diferenca)} a menos que o Total no Full ({_n(total)}). '
    fora = perdidas + nao_suportadas
    if fora == diferenca:
        partes = []
        if perdidas:
            partes.append(f"{_n(perdidas)} {'perdida' if perdidas == 1 else 'perdidas'}")
        if nao_suportadas:
            partes.append(f"{_n(nao_suportadas)} {'não suportada' if nao_suportadas == 1 else 'não suportadas'}")
        return texto + (f"Costuma ser unidade perdida ou não suportada, que o Mercado Livre não conta nas aptas: aqui há {' e '.join(partes)}, e a conta fecha. "
                        f"Por isso não dá para estimar o que está a caminho.")
    if fora:
        explicacao = f"O Código tem {_n(fora)} perdida(s) ou não suportada(s), o que não explica a diferença toda."
    else:
        explicacao = 'O Código não tem nenhuma unidade perdida ou não suportada que explique a diferença.'
    return texto + f'{explicacao} Vale conferir com a tela do Mercado Livre, ou usar o Atualizar para ler os dois números de novo.'


# Função Objetivo: Preenche, só dos Códigos dos produtos que aparecem na página (a reposição e o Flex são a parte pesada da consulta; para os
# milhares de Códigos da lista inteira eles não são lidos): "Aptas e a caminho" (REPOS) e o estoque no depósito do vendedor (FLEX). A reposição só
# entra para Código com estoque (estado "ok"); o Flex entra também para Código cujo estoque falhou — o depósito pode ter número mesmo assim.
def _preencher_aptas(produtos, ultimas):
    from mercado_livre.models import ConsultaFullMercadoLivre

    pks = {ultimas[c['codigo'].upper()].pk for p in produtos for c in p['codigos'] if c['estado'] in ('ok', 'erro')}
    if not pks:
        return
    consultas = {c.pk: c for c in ConsultaFullMercadoLivre.objects.filter(pk__in=pks).only('id', 'reposicao', 'flex')}
    for produto in produtos:
        for cartao in produto['codigos']:
            if cartao['estado'] not in ('ok', 'erro'):
                continue
            consulta = consultas.get(ultimas[cartao['codigo'].upper()].pk)
            if cartao['estado'] == 'ok':
                aptas = _aptas_do_codigo(consulta.reposicao if consulta else None, cartao['total'],
                                         _quantidade_do_motivo(cartao['motivos'], STATUS_PERDIDA), _quantidade_do_motivo(cartao['motivos'], STATUS_NAO_SUPORTADA))
                # Com erro de reposição o cartão já mostra o erro: o aviso "sem consulta de reposição salva" seria o mesmo problema dito de outro jeito.
                if cartao['repos_erro'] and aptas['aptas'] is None:
                    aptas['aptas_nota'] = ''
                cartao.update(aptas)
            cartao.update(_flex_do_codigo(consulta.flex if consulta else None, cartao['disponivel']))
            # Os 3 blocos "onde está o estoque" só existem se há o que mostrar: o estoque do Full veio, ou o Flex respondeu (mesmo com o estoque falhando).
            cartao['tem_locais'] = cartao['estado'] == 'ok' or cartao['flex_estado'] in ('ok', 'parcial')
        # Soma do produto: só dos Códigos que têm "Soma geral" e "A caminho" (os dois existem juntos ou nenhum dos dois); se algum Código ficou de fora, é
        # parcial. O Total que entra na conta "total + a caminho" é só o desses mesmos Códigos, senão a conta mostrada não fecharia com a Soma geral.
        com_soma = [c for c in produto['codigos'] if c['soma_geral'] is not None]
        if com_soma:
            total_deles = sum(c['total'] for c in com_soma)
            a_caminho = sum(c['a_caminho'] for c in com_soma)
            produto.update({'soma_geral': sum(c['soma_geral'] for c in com_soma), 'a_caminho': a_caminho,
                            'a_caminho_txt': f'+{_n(a_caminho)}' if a_caminho else '', 'a_caminho_qtd_txt': _n(a_caminho),
                            'soma_conta_txt': f'{_n(total_deles)} + {_n(a_caminho)}'})
            produto['soma_geral_txt'] = _n(produto['soma_geral'])
        produto['aptas_parcial'] = bool(com_soma) and len(com_soma) < produto['n_codigos']
        # Soma do depósito do produto: o depósito é do SKU (o ERP manda o mesmo estoque para todos os anúncios), então cada LOJA entra UMA vez só, mesmo que
        # apareça nos 3 Códigos ML do produto. Se a mesma loja trouxer quantidades diferentes, vale a maior e o aviso diz isso.
        valores_da_loja, rotulos_da_loja, em_quantos_codigos = {}, {}, {}
        for cartao in produto['codigos']:
            for chave, quantidade in cartao['deposito_por_loja'].items():
                valores_da_loja.setdefault(chave, set()).add(quantidade)
                rotulos_da_loja.setdefault(chave, cartao['deposito_rotulos'].get(chave, 'Depósito'))
                em_quantos_codigos[chave] = em_quantos_codigos.get(chave, 0) + 1
            for chave, valores in cartao['deposito_diverge'].items():
                valores_da_loja.setdefault(chave, set()).update(valores)
        for cartao in produto['codigos']:
            cartao['deposito_repetido'] = any(em_quantos_codigos.get(chave, 0) > 1 for chave in cartao['deposito_por_loja'])
        com_flex = [c for c in produto['codigos'] if c['flex_estado'] in ('ok', 'parcial')]
        if com_flex:
            produto['deposito'] = sum(max(valores) for valores in valores_da_loja.values())
            produto['deposito_txt'] = _n(produto['deposito'])
            produto['deposito_repetido'] = any(n > 1 for n in em_quantos_codigos.values())
            produto['deposito_aviso'] = _aviso_divergencia({k: sorted(v) for k, v in valores_da_loja.items() if len(v) > 1}, rotulos_da_loja,
                                                           'Os Códigos deste produto')
        produto['deposito_parcial'] = bool(com_flex) and any(c['flex_estado'] != 'ok' for c in produto['codigos'])


# ---------------------------------------------------------------------------
# OS ANÚNCIOS DE CADA CÓDIGO ML
# ---------------------------------------------------------------------------
# * [EXPLICAÇÃO] → O número de estoque é do CÓDIGO ML, mas quem usa a tela precisa saber QUAIS anúncios usam aquele Código.
#                  Esta parte só LÊ o banco (nunca chama o Mercado Livre) e só dos Códigos dos produtos que aparecem na página.
#                  Os selos (status, tipo, logística, Flex, catálogo) vêm do tipo do anúncio e são os mesmos do Hub e do Planejamento.
#                  Estoque, vendidos e preço do cartão são os da ÚLTIMA IMPORTAÇÃO dos anúncios — NÃO são o estoque do Full.
#                  Aparecem os anúncios do SKU do produto (os mesmos que a linha do Código conta em "N anúncios").

# Função Objetivo: 1 cartão de anúncio (1 MLB, ou 1 variação dele) com o que o desenho do Planejamento mostra.
def _cartao_do_anuncio(variacao):
    anuncio = variacao.anuncio
    tipo = anuncio.tipo_de_anuncio
    status = tipo.status if tipo else ''
    mlb = anuncio.mlb or ''
    variacao_id = str(variacao.variacao_id or '')
    return {
        'mlb': mlb,
        # Anúncio sem variações guarda o próprio MLB como variacao_id: "variação" só aparece quando ela existe de verdade.
        'variacao_id': '' if variacao_id == mlb else variacao_id,
        'variacao_atributos': variacao.atributos or '',
        'titulo': anuncio.titulo_anuncio or mlb,
        'permalink': anuncio.permalink or '',
        'imagem': variacao.imagem_principal_url or variacao.thumbnail_url or '',
        'sku': str(variacao.sku_ml or variacao.produto_id or '').strip(),
        'status': status,
        'badge_status': badge_de(BADGES_STATUS, status) if tipo else None,
        'badge_tipo': badge_de(BADGES_TIPO_ANUNCIO, tipo.tipo_anuncio) if tipo else None,
        'badge_logistica': badge_de(BADGES_LOGISTICA, tipo.tipo_logistico) if tipo else None,
        'badge_flex': badge_flex(bool(tipo.flex)) if tipo else None,
        'badge_catalogo': badge_de(BADGES_CATALOGO, tipo.classificacao_catalogo) if tipo else None,
        'estoque': _n_br(variacao.estoque) if variacao.estoque is not None else '—',
        'vendidos': _n_br(variacao.qtd_vendas) if variacao.qtd_vendas is not None else '—',
        'preco': _fmt_preco(variacao.preco_atual, None)[0] if variacao.preco_atual is not None else '—',
        'preco_original': _fmt_preco(variacao.preco_original, None)[0] if variacao.preco_original else '',
        'rank': RANK_STATUS.get(status, 5),
    }


# Função Objetivo: Põe em cada Código ML dos produtos da página a lista "anuncios" (ativos primeiro, encerrados por último).
# Uma única consulta ao banco para a página inteira.
def _preencher_anuncios(produtos):
    from mercado_livre.models import VariacaoAnuncioMercadoLivre

    # Os Códigos do ML são em maiúsculas; a versão maiúscula entra junto só por garantia (o MySQL já ignora a caixa).
    codigos = {texto for p in produtos for c in p['codigos'] for texto in (c['codigo'], c['codigo'].upper())}
    if not codigos:
        return
    variacoes = (VariacaoAnuncioMercadoLivre.objects
                 .filter(inventory_id__in=codigos)
                 .select_related('anuncio', 'anuncio__tipo_de_anuncio')
                 .only('inventory_id', 'variacao_id', 'sku_ml', 'produto', 'atributos', 'estoque', 'qtd_vendas',
                       'preco_atual', 'preco_original', 'thumbnail_url', 'imagem_principal_url',
                       'anuncio__mlb', 'anuncio__titulo_anuncio', 'anuncio__permalink',
                       'anuncio__tipo_de_anuncio__status', 'anuncio__tipo_de_anuncio__tipo_anuncio',
                       'anuncio__tipo_de_anuncio__tipo_logistico', 'anuncio__tipo_de_anuncio__classificacao_catalogo',
                       'anuncio__tipo_de_anuncio__flex'))
    por_codigo_e_sku = {}
    for variacao in variacoes:
        sku = str(variacao.produto_id or variacao.sku_ml or '').strip()   # a mesma regra de _ler_codigos_por_sku
        chave = (str(variacao.inventory_id).strip().upper(), sku)
        por_codigo_e_sku.setdefault(chave, []).append(_cartao_do_anuncio(variacao))
    for produto in produtos:
        for cartao in produto['codigos']:
            anuncios = por_codigo_e_sku.get((cartao['codigo'].upper(), produto['sku']), [])
            cartao['anuncios'] = sorted(anuncios, key=lambda a: (a['rank'], a['mlb'], a['variacao_id']))


# ---------------------------------------------------------------------------
# O PRODUTO
# ---------------------------------------------------------------------------
def _montar_produto(sku, codigos_do_sku, cadastro, ultimas, produtos_do_codigo, agora, erros_reposicao=None):
    cartoes = []
    for codigo_maiusculo, info in codigos_do_sku.items():
        cartao = _numeros_do_codigo(info['codigo'], ultimas.get(codigo_maiusculo), agora, (erros_reposicao or {}).get(codigo_maiusculo, ''))
        cartao['n_anuncios'] = len(info['mlbs'])
        cartao['compartilhado_com'] = sorted(s for s in produtos_do_codigo[codigo_maiusculo] if s != sku)
        cartoes.append(cartao)
    # Maior total primeiro; quem ainda não tem número vai para o fim.
    cartoes.sort(key=lambda c: (c['total'] is None, -(c['total'] or 0), c['codigo']))

    ok = [c for c in cartoes if c['estado'] == 'ok']
    n_erro = sum(1 for c in cartoes if c['estado'] == 'erro')
    n_sem = sum(1 for c in cartoes if c['estado'] == 'sem_consulta')
    n_repos_erro = sum(1 for c in cartoes if c['repos_erro'])
    n_desatualizados = sum(1 for c in ok if c['desatualizado'])
    # Códigos em que o total que o ML mandou não é igual a disponível + indisponível (a tela avisa, não corrige).
    n_diverge = sum(1 for c in ok if c['conferencia'] and not c['conferencia']['bate'])
    if not ok and not n_erro:
        status = 'sem_consulta'
    elif not ok:
        status = 'erro'
    elif len(ok) < len(cartoes):
        status = 'parcial'
    elif n_desatualizados:
        status = 'desatualizado'
    else:
        status = 'atualizado'

    consultas = [c['consultado_em'] for c in cartoes if c['consultado_em'] is not None]
    mais_antiga = min(consultas) if consultas else None
    mais_recente = max(consultas) if consultas else None
    total, disponivel, indisponivel = _soma(cartoes, 'total'), _soma(cartoes, 'disponivel'), _soma(cartoes, 'indisponivel')
    em_transferencia = _soma(cartoes, 'em_transferencia')
    titulo = (cadastro or {}).get('titulo') or sku or 'Sem SKU'
    marca = (cadastro or {}).get('marca') or ''
    pct_indisponivel = _pct_indisponivel(total, indisponivel)
    return {
        'sku': sku, 'titulo': titulo, 'cadastro': cadastro, 'codigos': cartoes,
        'n_codigos': len(cartoes), 'n_ok': len(ok), 'n_erro': n_erro, 'n_repos_erro': n_repos_erro, 'n_sem_consulta': n_sem, 'n_desatualizados': n_desatualizados, 'n_diverge': n_diverge,
        'total': total, 'disponivel': disponivel, 'indisponivel': indisponivel,
        'total_txt': _n(total), 'disponivel_txt': _n(disponivel), 'indisponivel_txt': _n(indisponivel),
        'parcial': bool(ok) and len(ok) < len(cartoes), 'motivos': _somar_motivos(cartoes),
        'soma_geral': None, 'soma_geral_txt': '—', 'soma_conta_txt': '', 'a_caminho': None, 'a_caminho_txt': '', 'a_caminho_qtd_txt': '—', 'aptas_parcial': False,
        'em_transferencia': em_transferencia, 'em_transferencia_txt': _n(em_transferencia),
        'deposito': None, 'deposito_txt': '—', 'deposito_parcial': False, 'deposito_repetido': False, 'deposito_aviso': '',
        'selo_deposito': SELO_DEPOSITO_FLEX, 'selo_em_transferencia': SELO_EM_TRANSFERENCIA, 'selo_a_caminho': BADGE_A_CAMINHO,
        'pct_indisponivel': pct_indisponivel, 'pct_indisponivel_txt': _pct_txt(pct_indisponivel),
        'marca': marca, 'marca_chave': _normalizar(marca),
        'n_compartilhados': sum(1 for c in cartoes if c['compartilhado_com']),
        'status': status, 'badge': BADGES_ESTOQUE_FULL[status],
        'mais_antiga': mais_antiga, 'mais_recente': mais_recente, 'idade_mais_antiga': _idade(mais_antiga, agora) if mais_antiga else '',
        'mais_antiga_completa': _data_hora_completa(mais_antiga),
        'url_planejamento': (reverse('gestao_full_planejamento') + '?' + urlencode({'q': sku})) if sku else '',
        'busca': _normalizar(' '.join([sku, titulo, (cadastro or {}).get('ean', ''), (cadastro or {}).get('marca', ''),
                                       (cadastro or {}).get('cod_fabricante', '')] + [c['codigo'] for c in cartoes])),
    }


def _passa_no_filtro(produto, filtro):
    if filtro == 'com_indisponivel':
        return (produto['indisponivel'] or 0) > 0
    if filtro == 'sem_disponivel':
        return produto['n_ok'] > 0 and produto['disponivel'] == 0
    if filtro == 'zerados':
        return produto['n_ok'] > 0 and produto['total'] == 0
    if filtro == 'desatualizados':
        return produto['n_desatualizados'] > 0
    if filtro == 'faltam_consultas':
        return produto['n_sem_consulta'] > 0
    if filtro == 'com_erro':
        return produto['n_erro'] > 0
    if filtro == 'repos_erro':
        return produto['n_repos_erro'] > 0
    if filtro == 'nao_bate':
        return produto['n_diverge'] > 0
    if filtro == 'compartilhados':
        return produto['n_compartilhados'] > 0
    if filtro == 'varios_codigos':
        return produto['n_codigos'] > 1
    return True


# * [EXPLICAÇÃO] → Ordens que comparam um NÚMERO do produto: ordem -> (campo, decrescente?).
ORDENS_NUMERICAS = {
    'total_desc': ('total', True), 'total_asc': ('total', False),
    'disponivel_desc': ('disponivel', True), 'disponivel_asc': ('disponivel', False),
    'indisponivel_desc': ('indisponivel', True), 'indisponivel_asc': ('indisponivel', False),
    'pct_indisponivel_desc': ('pct_indisponivel', True),
    'soma_desc': ('soma_geral', True), 'soma_asc': ('soma_geral', False),
    'a_caminho_desc': ('a_caminho', True), 'a_caminho_asc': ('a_caminho', False),
    'codigos_desc': ('n_codigos', True),
}


# Função Objetivo: Põe a lista na ordem escolhida. Sempre parte do título A–Z, então todo empate sai em ordem alfabética
# (o sort do Python é estável, inclusive com reverse=True). Quem não tem valor para a ordem vai para o fim.
def _ordenar(lista, ordem):
    por_titulo = sorted(lista, key=lambda p: _normalizar(p['titulo']))
    if ordem in ORDENS_NUMERICAS:
        campo, decrescente = ORDENS_NUMERICAS[ordem]
        com_valor = [p for p in por_titulo if p[campo] is not None]
        sem_valor = [p for p in por_titulo if p[campo] is None]
        com_valor.sort(key=lambda p: p[campo], reverse=decrescente)
        return com_valor + sem_valor
    if ordem == 'titulo_desc':
        return sorted(lista, key=lambda p: _normalizar(p['titulo']), reverse=True)
    if ordem in ('sku', 'marca'):
        campo = 'sku' if ordem == 'sku' else 'marca_chave'
        com_valor = sorted((p for p in por_titulo if p[campo]), key=lambda p: _normalizar(p[campo]))
        return com_valor + [p for p in por_titulo if not p[campo]]
    if ordem == 'consulta_antiga':
        # Quem nunca foi consultado vem primeiro (é o mais "antigo" de todos); depois, da consulta mais velha à mais nova.
        nunca = [p for p in por_titulo if p['mais_antiga'] is None]
        return nunca + sorted((p for p in por_titulo if p['mais_antiga'] is not None), key=lambda p: p['mais_antiga'])
    if ordem == 'consulta_recente':
        recentes = sorted((p for p in por_titulo if p['mais_recente'] is not None), key=lambda p: p['mais_recente'], reverse=True)
        return recentes + [p for p in por_titulo if p['mais_recente'] is None]
    return por_titulo


# Função Objetivo: Lê o banco e monta TODOS os produtos da empresa (sem filtro, sem os números de reposição e sem os anúncios — essas duas partes são
# pesadas e só vão para os produtos que a tela vai mostrar). Da reposição entra só o AVISO DE ERRO de cada Código (_ler_erros_de_reposicao, que
# usa o cache), para o filtro "Reposição com erro" e a contagem valerem para a lista inteira. Devolve (por_sku, ultimas, produtos).
def _carregar_produtos(agora):
    por_sku = _ler_codigos_por_sku()
    produtos_do_codigo = {}
    for sku, codigos in por_sku.items():
        for codigo_maiusculo in codigos:
            produtos_do_codigo.setdefault(codigo_maiusculo, set()).add(sku)
    cadastro = _ler_cadastro(por_sku.keys())
    ultimas = _ler_ultimas_consultas(set(produtos_do_codigo))
    erros_reposicao = _ler_erros_de_reposicao(ultimas)
    produtos = [_montar_produto(sku, codigos, cadastro.get(sku), ultimas, produtos_do_codigo, agora, erros_reposicao)
                for sku, codigos in por_sku.items()]
    return por_sku, ultimas, produtos


# * [EXPLICAÇÃO] → O "estado" da tela é o conjunto de escolhas da pessoa. Ele vira o endereço (?q=...&filtro=...), então
#                  recarregar, voltar e copiar o link mantêm tudo. Só o que foge do padrão vai para o endereço.
PADROES_DA_URL = {'q': '', 'filtro': FILTRO_PADRAO, 'marca': '', 'ordem': ORDEM_PADRAO, 'por_pagina': POR_PAGINA_PADRAO, 'p': 1}


# Função Objetivo: O endereço da própria tela com o estado atual mais as mudanças pedidas. Mudou busca, filtro, marca, ordem
# ou itens por página (e não disse a página)? Volta para a página 1, para a pessoa não cair numa página que não existe mais.
def _url(estado, **mudancas):
    novo = {**estado, **mudancas}
    if 'p' not in mudancas and any(chave in mudancas for chave in ('q', 'filtro', 'marca', 'ordem', 'por_pagina')):
        novo['p'] = 1
    parametros = {chave: novo[chave] for chave in PADROES_DA_URL if novo[chave] != PADROES_DA_URL[chave]}
    base = reverse('gestao_full_estoque')
    return f'{base}?{urlencode(parametros)}' if parametros else base


def _direcao(ordem):
    return 'desc' if ordem.endswith('_desc') or ordem == 'consulta_recente' else 'asc'


# Função Objetivo: Para cada coluna clicável, o que o título dela precisa: o endereço do próximo clique, a seta e o texto de
# apoio (aria-sort para leitor de tela; dica ao passar o mouse).
def _ordenacao_das_colunas(estado, ordem):
    rotulos = {chave: rotulo for chave, rotulo, _ in ORDENS}
    colunas = {}
    for coluna, (primeira, segunda) in ORDEM_DAS_COLUNAS.items():
        ativa = ordem in (primeira, segunda)
        proxima = segunda if ordem == primeira else primeira
        direcao = _direcao(ordem) if ativa else ''
        colunas[coluna] = {
            'ativa': ativa, 'direcao': direcao, 'url': _url(estado, ordem=proxima),
            'icone': {'asc': 'fa-sort-up', 'desc': 'fa-sort-down'}.get(direcao, 'fa-sort'),
            'aria': {'asc': 'ascending', 'desc': 'descending'}.get(direcao, 'none'),
            'dica': f'Ordenar: {rotulos[proxima]}',
        }
    return colunas


# Função Objetivo: O resumo (faixa de totais) da lista que a pessoa está vendo. Soma por CÓDIGO ÚNICO: um Código ML
# que aparece em 2 produtos conta uma vez só.
def _resumo(produtos):
    codigos = {}
    for produto in produtos:
        for cartao in produto['codigos']:
            codigos.setdefault(cartao['codigo'].upper(), cartao)
    unicos = list(codigos.values())
    n_ok = sum(1 for c in unicos if c['estado'] == 'ok')
    total, disponivel, indisponivel = (_soma(unicos, campo) for campo in ('total', 'disponivel', 'indisponivel'))
    return {
        'n_produtos': len(produtos), 'n_codigos': len(unicos), 'n_ok': n_ok, 'n_sem_numero': len(unicos) - n_ok,
        'total_txt': _n(total), 'disponivel_txt': _n(disponivel), 'indisponivel_txt': _n(indisponivel),
        # A tela só pinta de verde/laranja o número que é maior que zero.
        'tem_disponivel': bool(disponivel), 'tem_indisponivel': bool(indisponivel),
    }


# ---------------------------------------------------------------------------
# PEÇAS DOS BOTÕES DE ATUALIZAÇÃO
# ---------------------------------------------------------------------------
# * [EXPLICAÇÃO] → Estas funções só LEEM o banco. Quem consulta o Mercado Livre é full_estoque_varredura.py; depois que um número
#                  mudou, a tela pede aqui o produto (ou a faixa de totais) já com o número novo, para redesenhar no lugar.

# "Nunca consultado" vira esta data bem antiga só para a ordenação (ele tem que ficar antes de todos os outros).
_NUNCA_CONSULTADO = datetime(1970, 1, 1, tzinfo=fuso.utc)


# Função Objetivo: O que a faixa de totais mostra ao lado do botão "Fazer varredura completa". É sempre da empresa INTEIRA (a varredura
# consulta todos os Códigos ML, não só os da lista filtrada). "Consulta mais antiga" = a data da consulta mais velha entre os Códigos que já
# têm alguma; depois de uma varredura completa ela vira "há poucos minutos".
def _info_varredura(produtos, agora):
    resumo = _resumo(produtos)
    consultas = [c['consultado_em'] for p in produtos for c in p['codigos'] if c['consultado_em'] is not None]
    mais_antiga = min(consultas) if consultas else None
    return {
        'n_codigos': resumo['n_codigos'], 'n_sem_numero': resumo['n_sem_numero'],
        # Quase sempre são 3 chamadas por Código (1 de estoque + 1 de reposição + 1 do depósito/Flex); é uma estimativa, não uma promessa.
        'n_chamadas': resumo['n_codigos'] * 3,
        'mais_antiga_idade': _idade(mais_antiga, agora) if mais_antiga else '',
        'mais_antiga_completa': _data_hora_completa(mais_antiga),
    }


# Função Objetivo: Os Códigos ML que a varredura completa vai consultar: TODOS os da empresa, sem repetir, na ordem em que vale a pena
# consultar — primeiro os que ainda não têm número (nunca consultados ou com erro), depois os demais do mais antigo para o mais novo.
# Assim, se a pessoa apertar "Parar" no meio, o que já foi feito foi o que mais precisava.
def codigos_para_varredura():
    agora = timezone.now()
    unicos = {}
    for codigos in _ler_codigos_por_sku().values():
        for maiusculo, info in codigos.items():
            unicos.setdefault(maiusculo, info['codigo'])
    ultimas = _ler_ultimas_consultas(set(unicos))
    consultado_em = lambda maiusculo: ultimas[maiusculo].consultado_em if maiusculo in ultimas else _NUNCA_CONSULTADO
    sem_numero, com_numero = [], []
    for maiusculo, codigo in unicos.items():
        tem_numero = _numeros_do_codigo(codigo, ultimas.get(maiusculo), agora)['estado'] == 'ok'
        (com_numero if tem_numero else sem_numero).append(maiusculo)
    ordem = sorted(sem_numero, key=lambda m: (consultado_em(m), m)) + sorted(com_numero, key=lambda m: (consultado_em(m), m))
    return [unicos[m] for m in ordem]


# Função Objetivo: Refaz UM produto (pelo SKU) com o que o banco tem agora — é o que a tela redesenha no lugar depois de "Atualizar".
# "indice" é o número do produto na lista (o mesmo do id "est-p-N"), para o produto redesenhado continuar com o mesmo endereço.
# Devolve None se o SKU já não tem Código ML no banco.
def montar_um_produto(sku, indice):
    agora = timezone.now()
    por_sku = _ler_codigos_por_sku()
    codigos = por_sku.get(sku)
    if not codigos:
        return None
    # Só importa quem mais usa os Códigos DESTE produto (o aviso "também aparece no SKU ...").
    produtos_do_codigo = {}
    for outro_sku, codigos_do_outro in por_sku.items():
        for codigo_maiusculo in codigos_do_outro:
            if codigo_maiusculo in codigos:
                produtos_do_codigo.setdefault(codigo_maiusculo, set()).add(outro_sku)
    cadastro = _ler_cadastro([sku])
    ultimas = _ler_ultimas_consultas(set(codigos))
    produto = _montar_produto(sku, codigos, cadastro.get(sku), ultimas, produtos_do_codigo, agora,
                              _ler_erros_de_reposicao(ultimas, guardar_no_cache=False))
    _preencher_aptas([produto], ultimas)
    _preencher_anuncios([produto])
    produto['indice'] = indice
    return produto


# Função Objetivo: A faixa de totais (e o texto da varredura) da lista que a pessoa está vendo, sem montar a página inteira. "parametros" é a
# query string da tela (q, filtro, marca...), a mesma que a view da tela recebe; o que for inválido volta ao padrão.
def montar_faixa_de_totais(parametros):
    estado = _ler_estado(QueryDict(parametros) if isinstance(parametros, str) else parametros)
    agora = timezone.now()
    _, _, produtos = _carregar_produtos(agora)
    lista = _aplicar_busca_e_filtros(produtos, estado)['lista']
    return {
        'filtrada': bool(estado['q'] or estado['marca'] or estado['filtro'] != FILTRO_PADRAO),
        'resumo': _resumo(lista), 'varredura': _info_varredura(produtos, agora),
    }


# ---------------------------------------------------------------------------
# A PÁGINA
# ---------------------------------------------------------------------------
# Função Objetivo: Lê da URL o que a pessoa escolheu (busca, filtro, marca, ordem, itens por página) e descarta o que for
# inválido (volta ao padrão). Devolve o "estado" da tela, no mesmo formato que _url usa.
def _ler_estado(parametros):
    texto = ' '.join(str(parametros.get('q') or '').split())
    filtro = parametros.get('filtro')
    ordem = parametros.get('ordem')
    try:
        por_pagina = int(parametros.get('por_pagina') or POR_PAGINA_PADRAO)
    except (TypeError, ValueError):
        por_pagina = POR_PAGINA_PADRAO
    return {
        'q': texto,
        'filtro': filtro if filtro in {chave for chave, _, _ in FILTROS} else FILTRO_PADRAO,
        'marca': ' '.join(str(parametros.get('marca') or '').split()),
        'ordem': ordem if ordem in {chave for chave, _, _ in ORDENS} else ORDENS_RENOMEADAS.get(ordem, ORDEM_PADRAO),
        'por_pagina': por_pagina if por_pagina in OPCOES_POR_PAGINA else POR_PAGINA_PADRAO,
        'p': 1,
    }


# Função Objetivo: Aplica na lista de produtos a busca, a marca e o filtro do "estado" (nessa ordem). Devolve as listas de cada etapa, porque
# a tela usa todas: "achados" (só a busca), "achados_da_marca" (busca + marca: contagem dos botões de filtro), "por_filtro" (busca + filtro:
# contagem das marcas) e "lista" (as três: é o que a pessoa vê, e o que a faixa de totais soma).
def _aplicar_busca_e_filtros(produtos, estado):
    palavras = _normalizar(estado['q']).split()
    achados = [p for p in produtos if all(palavra in p['busca'] for palavra in palavras)]
    marca = estado['marca']
    marca_alvo = '' if marca == SEM_MARCA else _normalizar(marca)
    da_marca = lambda p: not marca or p['marca_chave'] == marca_alvo
    por_filtro = [p for p in achados if _passa_no_filtro(p, estado['filtro'])]
    return {'achados': achados, 'marca_alvo': marca_alvo, 'da_marca': da_marca,
            'achados_da_marca': [p for p in achados if da_marca(p)],
            'por_filtro': por_filtro, 'lista': [p for p in por_filtro if da_marca(p)]}


# Função Objetivo: Agrupa itens (chave, rótulo, grupo) por grupo, na ordem em que aparecem, para a tela desenhar os blocos.
def _agrupar(itens, grupo_de):
    grupos = []
    for item in itens:
        grupo = grupo_de(item)
        if not grupos or grupos[-1]['rotulo'] != grupo:
            grupos.append({'rotulo': grupo, 'itens': []})
        grupos[-1]['itens'].append(item)
    return grupos


# Função Objetivo: A tela inteira. "parametros" são os textos de request.GET (q, filtro, marca, ordem, por_pagina, p).
# LÊ SÓ DO BANCO. Devolve o que a tela desenha: colunas (com selos e setas de ordenação), filtros e marcas (com contagem),
# resumo, produtos da página e paginação.
def montar_estoque(parametros, validacoes, rotulos_situacao):
    estado = _ler_estado(parametros)
    texto, filtro, ordem, marca, por_pagina = estado['q'], estado['filtro'], estado['ordem'], estado['marca'], estado['por_pagina']
    agora = timezone.now()

    por_sku, ultimas, produtos = _carregar_produtos(agora)

    # 1) busca de texto; 2) marca; 3) filtro; 4) ordem; 5) página. As contagens dos botões de filtro respeitam a busca e a marca;
    # as contagens da lista de marcas respeitam a busca e o filtro — assim nenhuma escolha leva a uma lista vazia sem aviso.
    etapas = _aplicar_busca_e_filtros(produtos, estado)
    marca_alvo = etapas['marca_alvo']
    achados_da_marca, por_filtro = etapas['achados_da_marca'], etapas['por_filtro']

    filtros = [{'chave': chave, 'rotulo': rotulo, 'grupo': grupo, 'contagem': sum(1 for p in achados_da_marca if _passa_no_filtro(p, chave)),
                'ativo': chave == filtro, 'url': _url(estado, filtro=chave)} for chave, rotulo, grupo in FILTROS]

    # Marcas escritas com caixa diferente ("Bosch", "bosch") contam como a mesma; o nome mostrado é a grafia mais usada.
    contagem_marcas, grafias = {}, {}
    for produto in por_filtro:
        contagem_marcas[produto['marca_chave']] = contagem_marcas.get(produto['marca_chave'], 0) + 1
        das_grafias = grafias.setdefault(produto['marca_chave'], {})
        das_grafias[produto['marca']] = das_grafias.get(produto['marca'], 0) + 1
    rotulo_da_marca = {chave: max(sorted(das_grafias), key=das_grafias.get) for chave, das_grafias in grafias.items()}
    if marca and marca_alvo not in contagem_marcas:
        contagem_marcas[marca_alvo], rotulo_da_marca[marca_alvo] = 0, ('' if marca == SEM_MARCA else marca)
    marcas = [{'rotulo': 'Todas as marcas', 'contagem': len(por_filtro), 'ativo': not marca, 'url': _url(estado, marca='')}]
    marcas += [{'rotulo': rotulo_da_marca[chave], 'contagem': contagem_marcas[chave], 'ativo': bool(marca) and chave == marca_alvo,
                'url': _url(estado, marca=rotulo_da_marca[chave])} for chave in sorted(contagem_marcas) if chave]
    if '' in contagem_marcas:
        marcas.append({'rotulo': 'Sem marca cadastrada', 'contagem': contagem_marcas[''], 'ativo': bool(marca) and marca_alvo == '',
                       'url': _url(estado, marca=SEM_MARCA)})

    lista = etapas['lista']
    # Ordenar por soma geral / a caminho exige a reposição de TODOS os Códigos da lista; nas outras ordens só se lê a da página.
    precisa_reposicao = ordem in ORDENS_QUE_LEEM_REPOSICAO
    if precisa_reposicao:
        _preencher_aptas(lista, ultimas)
    lista = _ordenar(lista, ordem)

    paginador = Paginator(lista, por_pagina)
    pagina = paginador.get_page(parametros.get('p') or 1)
    produtos_da_pagina = list(pagina.object_list)
    if not precisa_reposicao:
        _preencher_aptas(produtos_da_pagina, ultimas)
    _preencher_anuncios(produtos_da_pagina)
    for posicao, produto in enumerate(produtos_da_pagina, start=1):
        produto['indice'] = (pagina.number - 1) * por_pagina + posicao

    colunas = {chave: {'rotulo': rotulo, 'meta': _meta_do_campo(fonte, caminho, validacoes, rotulos_situacao)}
               for chave, fonte, caminho, rotulo in COLUNAS_FONTE}
    colunas['a_caminho'] = COLUNA_A_CAMINHO
    grupos_ordens = [{'rotulo': grupo['rotulo'], 'ordens': [{'chave': chave, 'rotulo': rotulo, 'ativo': chave == ordem, 'url': _url(estado, ordem=chave)}
                                                            for chave, rotulo, _ in grupo['itens']]}
                     for grupo in _agrupar(ORDENS, lambda item: item[2])]
    # * [EXPLICAÇÃO] → Filtro que hoje não acha nada (contagem 0) NÃO aparece: clicar nele só levaria a uma lista vazia, e a tela fica mais curta.
    #                  Ele volta sozinho quando passar a ter ocorrência (ex.: surgir uma consulta com erro). O filtro que está valendo
    #                  sempre aparece (o "Todos" também), e um grupo que ficou sem nenhum filtro some junto com o rótulo dele.
    grupos_filtros = []
    for grupo in _agrupar(FILTROS, lambda item: item[2]):
        chaves = {item[0] for item in grupo['itens']}
        visiveis = [f for f in filtros if f['chave'] in chaves and (f['contagem'] or f['ativo'] or f['chave'] == 'todos')]
        if visiveis:
            grupos_filtros.append({'rotulo': grupo['rotulo'], 'filtros': visiveis})
    return {
        'texto': texto, 'filtro': filtro, 'ordem': ordem, 'marca': marca, 'por_pagina': por_pagina,
        'filtro_padrao': FILTRO_PADRAO, 'ordem_padrao': ORDEM_PADRAO, 'por_pagina_padrao': POR_PAGINA_PADRAO,
        'filtrada': bool(texto or marca or filtro != FILTRO_PADRAO),
        'tem_ajustes': bool(texto or marca or filtro != FILTRO_PADRAO or ordem != ORDEM_PADRAO or por_pagina != POR_PAGINA_PADRAO),
        'grupos_ordens': grupos_ordens, 'grupos_filtros': grupos_filtros, 'marcas': marcas,
        'opcoes_por_pagina': [{'valor': n, 'rotulo': f'{n} por página', 'ativo': n == por_pagina, 'url': _url(estado, por_pagina=n)}
                              for n in OPCOES_POR_PAGINA],
        'ordenacao': _ordenacao_das_colunas(estado, ordem),
        'colunas': colunas, 'badge_a_caminho': BADGE_A_CAMINHO,
        'resumo': _resumo(lista), 'varredura': _info_varredura(produtos, agora), 'produtos': produtos_da_pagina,
        'abrir_sozinho': bool(texto) and len(lista) <= LIMITE_PARA_ABRIR_SOZINHO,
        'sem_codigos_no_banco': not por_sku,
        'horas_desatualizado': HORAS_PARA_DESATUALIZADO,
        'situacoes': [
            {'badge': BADGES_ESTOQUE_FULL['atualizado'],
             'texto': f'Todos os Códigos ML do produto foram consultados há menos de {HORAS_PARA_DESATUALIZADO} horas.'},
            {'badge': BADGES_ESTOQUE_FULL['desatualizado'],
             'texto': f'Algum Código ML foi consultado há mais de {HORAS_PARA_DESATUALIZADO} horas: o número pode ter mudado desde então.'},
            {'badge': BADGES_ESTOQUE_FULL['parcial'],
             'texto': 'Só parte dos Códigos ML do produto tem número. O total do produto soma apenas esses.'},
            {'badge': BADGES_ESTOQUE_FULL['sem_consulta'],
             'texto': 'Nenhum Código ML do produto foi consultado ainda: não existe número para mostrar.'},
            {'badge': BADGES_ESTOQUE_FULL['erro'],
             'texto': 'O Mercado Livre não devolveu o estoque na última consulta.'},
        ],
        'paginacao': {
            'numero': pagina.number, 'total_paginas': paginador.num_pages, 'total': paginador.count,
            'primeiro': pagina.start_index() if paginador.count else 0, 'ultimo': pagina.end_index() if paginador.count else 0,
            'url_anterior': _url(estado, p=pagina.number - 1) if pagina.has_previous() else '',
            'url_proxima': _url(estado, p=pagina.number + 1) if pagina.has_next() else '',
        },
        'url_limpar': _url({**estado, 'q': '', 'filtro': FILTRO_PADRAO, 'marca': '', 'ordem': ORDEM_PADRAO, 'por_pagina': POR_PAGINA_PADRAO}),
    }
