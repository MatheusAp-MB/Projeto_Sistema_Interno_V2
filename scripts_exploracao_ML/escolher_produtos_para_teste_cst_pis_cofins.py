# scripts_exploracao_ML/escolher_produtos_para_teste_cst_pis_cofins.py
#
# Função Objetivo: escolher, SEM você procurar na tela, os produtos pra testar a regra
# "CST de PIS/COFINS 02, 04 ou 06 no XML do fornecedor = 0% na entrada e na saída":
#   - 1 produto com CST 02, 1 com CST 04 e 1 com CST 06 (os 3 entram na regra);
#   - 1 produto de CONTROLE: CST fora da regra, sem selo ZERO. Ele NÃO pode mudar nada.
# Pra cada um, o script mostra o link da página de impressão da auditoria do anúncio escolhido
# (abra o link, Ctrl+P, "Salvar como PDF") e os números de hoje (o "antes").
#
# Só leitura: só faz SELECT no banco da empresa. A única coisa que o script grava é um arquivo
# .json aqui nesta pasta (o .gitignore já cobre "scripts_exploracao_ML/*.json") com os produtos
# escolhidos e os números de "antes".
#
# Os 2 modos são automáticos:
#   1ª vez (o .json NÃO existe) = modo ANTES: escolhe os produtos, mostra os links e guarda os
#                                 números de hoje.
#   2ª vez (o .json existe)     = modo DEPOIS: usa os MESMOS produtos, lê a grade de novo e
#                                 confere, produto a produto, se mudou só o que a regra manda
#                                 mudar (e se o produto de controle ficou igual).
#   Pra escolher tudo de novo: apague o .json (ou ponha REESCOLHER = True).
#
# Quem decide a regra é o módulo dono dela (impostos/funcoes_auxiliares/entrada/
# pis_cofins_tributo_ja_pago.py) — este script só chama, nunca repete a lista de CSTs.
#
# Como rodar (na raiz do projeto, com o ambiente ativado):
#   python scripts_exploracao_ML/escolher_produtos_para_teste_cst_pis_cofins.py

import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

# Permite rodar este script direto, de qualquer diretório, sem depender do CWD
# pra achar os pacotes do projeto.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from django.core.exceptions import ObjectDoesNotExist
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from core.empresa import EMPRESA_POR_ALIAS_BANCO, definir_empresa_ativa
from impostos.funcoes_auxiliares.entrada.conversao_valores_impostos import valor_por_unidade
from impostos.funcoes_auxiliares.entrada.pis_cofins_tributo_ja_pago import pis_cofins_tributo_ja_pago_pelo_fornecedor
from impostos.models import ImpostosECustosXMLEntradaProduto
from precificacao.models import GradePrecificacaoML
from precificacao.views.grade_mercado_livre import TIPO_GRADE_PARA_ML
from produtos.models import Produto

console = Console()

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EMPRESA = 'magazine'                  # 'magazine' ou 'samvale'
BASE_URL = 'http://10.0.0.193:8000'   # o endereço onde você abre o sistema (o mesmo do rodapé dos seus PDFs)
TIPO_ANUNCIO = 'classico'             # 'classico' ou 'premium'
MARGEM = 'padrao'                     # 'minima', 'padrao', 'maxima' ou 'competicao'
REESCOLHER = False                    # True = ignora o .json e escolhe tudo de novo

# Produto/anúncio que você JÁ baixou como "Antes" (SKU -> id da variação, o "?variacao=" do link
# do seu PDF). Se o SKU cair num dos grupos, o script usa ESSE anúncio em vez de sortear outro.
ESCOLHAS_FIXAS = {'F7908050719121.001': 308}
# ========================================

PASTA_SCRIPT = Path(__file__).resolve().parent
CAMINHO_JSON = PASTA_SCRIPT / f'teste_cst_pis_cofins_{EMPRESA}.json'

CSTS_DA_REGRA = ('02', '04', '06')
PAPEL_CONTROLE = 'CONTROLE'
TOLERANCIA_REAIS = Decimal('0.02')     # diferença de centavos por arredondamento do sistema


# ----------------------------------------------------------------------------------------
# Funções puras (sem banco) — pequenas de propósito, pra ler e conferir fácil
# ----------------------------------------------------------------------------------------

# Função Objetivo: Converte qualquer valor (número, texto do JSON, None) em Decimal, sem inventar zero.
def _dec(valor):
    if valor is None or valor == '':
        return None
    return Decimal(str(valor))


# Função Objetivo: Formata como o sistema mostra (vírgula decimal). None vira "—".
def _fmt(valor, casas=2, prefixo='', sufixo=''):
    numero = _dec(valor)
    if numero is None:
        return '—'
    texto = f'{numero:,.{casas}f}'.replace(',', '#').replace('.', ',').replace('#', '.')
    return f'{prefixo}{texto}{sufixo}'


def _texto_cst(cst):
    return str(cst).strip().zfill(2)


# Função Objetivo: Diz em qual grupo o produto cai, olhando o CST do PIS e o do COFINS de cada um.
# Devolve '02'/'04'/'06' (PIS e COFINS na regra, com o mesmo CST), 'MISTO' (só um dos dois na regra,
# ou CSTs diferentes entre si) ou 'FORA' (nenhum dos dois na regra = produto de controle).
def classificar_grupo(cst_pis, cst_cofins):
    pis_na_regra = pis_cofins_tributo_ja_pago_pelo_fornecedor(cst_pis)
    cofins_na_regra = pis_cofins_tributo_ja_pago_pelo_fornecedor(cst_cofins)

    if not pis_na_regra and not cofins_na_regra:
        return 'FORA'
    if pis_na_regra and cofins_na_regra and _texto_cst(cst_pis) == _texto_cst(cst_cofins):
        return _texto_cst(cst_pis)
    return 'MISTO'


# Função Objetivo: Escolhe o candidato do MEIO da fila (mediana do crédito), pra pegar um produto
# "típico" e não o mais caro nem o mais barato — com a fila ordenada pelo crédito de PIS+COFINS da nota.
def escolher_pela_mediana(candidatos):
    ordenados = sorted(candidatos, key=lambda c: (c['credito_total'] or Decimal('0'), c.get('saida_total') or Decimal('0')))
    return ordenados[len(ordenados) // 2]


# Função Objetivo: Diz se o produto tem ALGO que a regra possa mexer (senão o teste só prova que nada muda).
# Produto da regra: crédito na nota > 0, OU PIS/COFINS de saída > 0 na grade, OU cadastro de saída que não é
# 0 (vazio ou positivo — a regra grava 0,00). CST 04/06 não destacam PIS/COFINS na nota, então neles o que
# muda costuma ser só o cadastro. Controle: precisa de crédito E saída > 0, pra mostrar que continuam iguais.
def tem_o_que_mudar(grupo, credito_total, saida_total, situacao_cadastro):
    tem_credito = credito_total is not None and credito_total > 0
    tem_saida = saida_total is not None and saida_total > 0
    if grupo == 'FORA':
        return tem_credito and tem_saida
    return tem_credito or tem_saida or situacao_cadastro != 'zero'


# Função Objetivo: Tira da linha da grade os números que importam pra comparar antes x depois.
# Tudo vem do próprio detalhamento que o modal "como chegamos nesse preço" usa.
def montar_snapshot(linha):
    detalhamento = linha.detalhamento or {}
    intermediarios = detalhamento.get('intermediarios') or {}
    entrada = detalhamento.get('entrada') or {}

    def texto(valor):
        numero = _dec(valor)
        return None if numero is None else str(numero)

    return {
        'preco': texto(linha.preco),
        'margem_obtida_pct': texto(linha.margem_percentual_obtida),
        'margem_alvo_pct': texto(entrada.get('margem_alvo_percentual')),
        'fixo': texto(intermediarios.get('fixo')),
        'taxa_pct': texto(intermediarios.get('taxa_percentual')),
        'denominador': texto(intermediarios.get('denominador')),
        'credito_pis': texto(intermediarios.get('credito_pis')),
        'credito_cofins': texto(intermediarios.get('credito_cofins')),
        'pis_saida_pct': texto(entrada.get('pis_saida_percentual')),
        'cofins_saida_pct': texto(entrada.get('cofins_saida_percentual')),
    }


def montar_url_pdf(produto_id, variacao_id):
    tipo_ml = TIPO_GRADE_PARA_ML[TIPO_ANUNCIO]
    return (
        f'{BASE_URL}/precificacao/grade-mercado-livre/detalhe/'
        f'{produto_id}/{tipo_ml}/{MARGEM}/imprimir/?variacao={variacao_id}'
    )


def _perto(a, b, tolerancia=TOLERANCIA_REAIS):
    a, b = _dec(a), _dec(b)
    return a is not None and b is not None and abs(a - b) <= tolerancia


def _soma(*valores):
    numeros = [_dec(v) for v in valores]
    return None if any(n is None for n in numeros) else sum(numeros)


def _menos(a, b):
    a, b = _dec(a), _dec(b)
    return None if a is None or b is None else a - b


# Função Objetivo: Texto (ou None) pra guardar no JSON, sem inventar zero.
def _txt(valor):
    numero = _dec(valor)
    return None if numero is None else str(numero)


# Função Objetivo: "Igual ao antes?" — os 2 vazios contam como iguais; senão, diferença dentro da tolerância.
def _igual(a, b, tolerancia):
    if _dec(a) is None and _dec(b) is None:
        return True
    return _perto(a, b, tolerancia)


# Função Objetivo: Resume o que o CADASTRO do produto (Produto.pis_percentual/cofins_percentual) guarda de
# PIS/COFINS de saída: 'vazia' (os 2 em branco = sem linha na tabela por NCM+CST), 'positiva' (algum > 0)
# ou 'zero'. A grade lê vazio como 0%, por isso grade e cadastro podem parecer iguais e não ser.
def situacao_saida_cadastro(pis, cofins):
    pis, cofins = _dec(pis), _dec(cofins)
    if pis is None and cofins is None:
        return 'vazia'
    if (pis or 0) > 0 or (cofins or 0) > 0:
        return 'positiva'
    return 'zero'


# Função Objetivo: Monta a lista de conferências (item, antes, depois, esperado, passou) de 1 produto.
# Produto da regra: crédito e saída zerados, FIXO sobe o crédito perdido, taxa cai a saída antiga, cadastro de
# saída = 0,00; o preço só precisa mudar se havia crédito ou saída a tirar (senão tem que ficar IGUAL).
# Produto de controle: TUDO igual ao antes.
def montar_conferencias(papel, antes, depois):
    itens = []

    if papel == PAPEL_CONTROLE:
        for rotulo, chave, sufixo in (
            ('Crédito PIS (R$)', 'credito_pis', ''), ('Crédito COFINS (R$)', 'credito_cofins', ''),
            ('PIS saída (%)', 'pis_saida_pct', '%'), ('COFINS saída (%)', 'cofins_saida_pct', '%'),
            ('PIS saída no cadastro (%)', 'cadastro_pis', '%'), ('COFINS saída no cadastro (%)', 'cadastro_cofins', '%'),
            ('FIXO (R$)', 'fixo', ''), ('Taxa total (%)', 'taxa_pct', '%'),
            ('Preço final (R$)', 'preco', ''),
        ):
            itens.append((rotulo, _fmt(antes.get(chave), sufixo=sufixo), _fmt(depois.get(chave), sufixo=sufixo),
                          'igual ao antes', _igual(antes.get(chave), depois.get(chave), Decimal('0.005'))))
        return itens, False

    credito_perdido = _soma(antes.get('credito_pis'), antes.get('credito_cofins'))
    fixo_esperado = _soma(antes.get('fixo'), credito_perdido)
    saida_antiga = _soma(antes.get('pis_saida_pct'), antes.get('cofins_saida_pct'))
    taxa_esperada = _menos(antes.get('taxa_pct'), saida_antiga)
    margem_depois, meta = _dec(depois.get('margem_obtida_pct')), _dec(depois.get('margem_alvo_pct'))
    grade_deve_mudar = (credito_perdido or 0) > 0 or (saida_antiga or 0) > 0

    # * [EXPLICAÇÃO] → NÃO dá pra provar "a grade foi recalculada" pela data: GradePrecificacaoML.calculado_em é
    #                  auto_now, mas a gravação usa bulk_update com lista de campos que não inclui calculado_em —
    #                  então ele guarda só o dia em que a linha foi CRIADA. O sinal confiável é o próprio número:
    #                  se a grade deveria mudar (havia crédito ou saída a tirar) e nenhum número mudou, ela não
    #                  foi recalculada (ou foi recalculada antes do passo 3).
    grade_nao_mudou = all(
        _igual(antes.get(chave), depois.get(chave), Decimal('0.005'))
        for chave in ('preco', 'fixo', 'taxa_pct', 'credito_pis', 'credito_cofins', 'pis_saida_pct', 'cofins_saida_pct')
    )
    nao_recalculada = grade_deve_mudar and grade_nao_mudou

    if grade_deve_mudar:
        linha_preco = ('Preço final (R$)', _fmt(antes.get('preco')), _fmt(depois.get('preco')),
                       'muda (sobe ou desce)', _dec(antes.get('preco')) != _dec(depois.get('preco')))
    else:
        linha_preco = ('Preço final (R$)', _fmt(antes.get('preco')), _fmt(depois.get('preco')),
                       'igual ao antes (crédito e saída já eram 0)', _perto(antes.get('preco'), depois.get('preco'), Decimal('0.005')))

    itens += [
        ('Crédito PIS (R$)', _fmt(antes.get('credito_pis')), _fmt(depois.get('credito_pis')), 'R$ 0,00',
         _perto(depois.get('credito_pis'), 0, Decimal('0.005'))),
        ('Crédito COFINS (R$)', _fmt(antes.get('credito_cofins')), _fmt(depois.get('credito_cofins')), 'R$ 0,00',
         _perto(depois.get('credito_cofins'), 0, Decimal('0.005'))),
        ('PIS saída (%)', _fmt(antes.get('pis_saida_pct'), sufixo='%'), _fmt(depois.get('pis_saida_pct'), sufixo='%'),
         '0,00%', _perto(depois.get('pis_saida_pct'), 0, Decimal('0.005'))),
        ('COFINS saída (%)', _fmt(antes.get('cofins_saida_pct'), sufixo='%'), _fmt(depois.get('cofins_saida_pct'), sufixo='%'),
         '0,00%', _perto(depois.get('cofins_saida_pct'), 0, Decimal('0.005'))),
        ('PIS saída no cadastro (%)', _fmt(antes.get('cadastro_pis'), sufixo='%'), _fmt(depois.get('cadastro_pis'), sufixo='%'),
         '0,00%', _perto(depois.get('cadastro_pis'), 0, Decimal('0.005'))),
        ('COFINS saída no cadastro (%)', _fmt(antes.get('cadastro_cofins'), sufixo='%'), _fmt(depois.get('cadastro_cofins'), sufixo='%'),
         '0,00%', _perto(depois.get('cadastro_cofins'), 0, Decimal('0.005'))),
        ('FIXO (R$)', _fmt(antes.get('fixo')), _fmt(depois.get('fixo')),
         f'{_fmt(fixo_esperado)} (antes + créditos perdidos)', _perto(depois.get('fixo'), fixo_esperado)),
        ('Taxa total (%)', _fmt(antes.get('taxa_pct'), sufixo='%'), _fmt(depois.get('taxa_pct'), sufixo='%'),
         f'{_fmt(taxa_esperada, sufixo="%")} (antes − PIS e COFINS de saída)', _perto(depois.get('taxa_pct'), taxa_esperada)),
        linha_preco,
        ('Margem obtida (%)', _fmt(antes.get('margem_obtida_pct'), sufixo='%'), _fmt(depois.get('margem_obtida_pct'), sufixo='%'),
         f'≥ meta de {_fmt(meta, sufixo="%")}', margem_depois is not None and meta is not None and margem_depois >= meta),
    ]
    return itens, nao_recalculada


# Função Objetivo: Frase do que se espera de 1 produto, pra aparecer junto do "antes" no painel.
def descrever_expectativa(papel, antes):
    if papel == PAPEL_CONTROLE:
        return 'Esperado: TUDO igual depois (é o produto de controle — fora da regra).'
    credito_perdido = _soma(antes.get('credito_pis'), antes.get('credito_cofins'))
    saida_antiga = _soma(antes.get('pis_saida_pct'), antes.get('cofins_saida_pct'))
    if (credito_perdido or 0) > 0 or (saida_antiga or 0) > 0:
        return 'Esperado: crédito vai a R$ 0,00, saída vai a 0,00%, FIXO e taxa mudam e o preço muda.'
    return ('Esperado: a GRADE fica igual (crédito e saída já são 0 hoje); o que muda é o CADASTRO, que passa a '
            'ter 0,00% de PIS/COFINS de saída.')


# ----------------------------------------------------------------------------------------
# Leitura do banco (só SELECT)
# ----------------------------------------------------------------------------------------

# Função Objetivo: Lê o retrato de entrada de todos os produtos e separa em grupos pelo CST.
def carregar_candidatos():
    grupos = {'02': [], '04': [], '06': [], 'MISTO': [], 'FORA': []}
    retratos_incompletos = 0
    sem_quantidade = 0
    total = 0

    consulta = ImpostosECustosXMLEntradaProduto.objects.select_related('produto', 'pis', 'cofins').order_by('produto_id')
    for retrato in consulta.iterator():
        total += 1
        try:
            pis, cofins = retrato.pis, retrato.cofins
        except ObjectDoesNotExist:
            retratos_incompletos += 1
            continue

        grupo = classificar_grupo(pis.cst_xml, cofins.cst_xml)
        credito_pis = valor_por_unidade(pis.valor, retrato.quantidade_nota)
        credito_cofins = valor_por_unidade(cofins.valor, retrato.quantidade_nota)
        if credito_pis is None or credito_cofins is None:
            sem_quantidade += 1

        grupos[grupo].append({
            'produto_id': retrato.produto_id,
            'sku': retrato.produto.sku,
            'ean': retrato.produto.ean,
            'titulo': retrato.produto.titulo,
            'pis_saida_cadastro': _txt(retrato.produto.pis_percentual),
            'cofins_saida_cadastro': _txt(retrato.produto.cofins_percentual),
            'nf': retrato.nr_nf,
            'cst_pis': _texto_cst(pis.cst_xml),
            'cst_cofins': _texto_cst(cofins.cst_xml),
            'credito_pis_nota': None if credito_pis is None else str(credito_pis),
            'credito_cofins_nota': None if credito_cofins is None else str(credito_cofins),
            'credito_total': None if credito_pis is None or credito_cofins is None else credito_pis + credito_cofins,
        })

    return grupos, {'total': total, 'retratos_incompletos': retratos_incompletos, 'sem_quantidade': sem_quantidade}


# Função Objetivo: Pra cada produto, as linhas RESOLVIDAS da grade (do anúncio com MLB, no tipo e margem
# escolhidos) — é nelas que existe a página de auditoria. {produto_id: [linhas em ordem de variação]}.
def carregar_linhas_da_grade(produto_ids):
    linhas = (
        GradePrecificacaoML.objects
        .filter(
            produto_id__in=produto_ids, variacao__isnull=False, tipo_anuncio=TIPO_ANUNCIO,
            margem=MARGEM, resolvida=True, detalhamento__isnull=False,
        )
        .select_related('variacao__anuncio')
        .order_by('produto_id', 'variacao_id')
    )
    por_produto = {}
    for linha in linhas:
        por_produto.setdefault(linha.produto_id, []).append(linha)
    return por_produto


# Função Objetivo: Escolhe a linha da grade de 1 produto: a fixa (se o SKU está em ESCOLHAS_FIXAS e a
# variação existe) ou a primeira. None se o produto não tem linha.
def escolher_linha(candidato, linhas_do_produto):
    if not linhas_do_produto:
        return None
    variacao_fixa = ESCOLHAS_FIXAS.get(candidato['sku'])
    if variacao_fixa is not None:
        for linha in linhas_do_produto:
            if linha.variacao_id == variacao_fixa:
                return linha
    return linhas_do_produto[0]


# Função Objetivo: Pra cada candidato que tem linha na grade, guarda a linha escolhida ('_linha') e o
# PIS+COFINS de saída que a grade usa hoje ('saida_total'). Sem linha, nada é guardado.
def anexar_linha_e_saida(grupos, linhas_por_produto):
    for lista in grupos.values():
        for c in lista:
            linhas_do_produto = linhas_por_produto.get(c['produto_id'])
            if not linhas_do_produto:
                continue
            linha = escolher_linha(c, linhas_do_produto)
            snapshot = montar_snapshot(linha)
            c['_linha'] = linha
            c['saida_total'] = _soma(snapshot['pis_saida_pct'], snapshot['cofins_saida_pct']) or Decimal('0')


# ----------------------------------------------------------------------------------------
# Modo ANTES
# ----------------------------------------------------------------------------------------

def rodar_modo_antes():
    grupos, resumo = carregar_candidatos()
    todos_ids = [c['produto_id'] for lista in grupos.values() for c in lista]
    linhas_por_produto = carregar_linhas_da_grade(todos_ids)
    anexar_linha_e_saida(grupos, linhas_por_produto)

    # Resumo do universo — responde "quantos produtos entram na regra?" e "quantos têm o que mudar?".
    tabela = Table(title=f'Quantos produtos caem em cada grupo — {EMPRESA}', show_lines=True)
    for coluna in ('Grupo', 'Produtos', 'Com linha na grade (anúncio com MLB)',
                   'Com crédito de PIS/COFINS na nota (> 0)', 'Com PIS/COFINS de saída na grade (> 0)',
                   'PIS/COFINS de saída no CADASTRO do produto'):
        tabela.add_column(coluna)
    descricao = {
        '02': 'CST 02 (PIS e COFINS) — regra', '04': 'CST 04 (PIS e COFINS) — regra', '06': 'CST 06 (PIS e COFINS) — regra',
        'MISTO': 'MISTO (só um dos dois na regra, ou CSTs diferentes)', 'FORA': 'FORA da regra (controle)',
    }
    for grupo, lista in grupos.items():
        com_grade = [c for c in lista if '_linha' in c]
        com_credito = sum(1 for c in com_grade if c['credito_total'] is not None and c['credito_total'] > 0)
        com_saida = sum(1 for c in com_grade if c['saida_total'] > 0)
        situacoes = [situacao_saida_cadastro(c['pis_saida_cadastro'], c['cofins_saida_cadastro']) for c in lista]
        cadastro = f'{situacoes.count("vazia")} vazio · {situacoes.count("zero")} zero · {situacoes.count("positiva")} maior que zero'
        tabela.add_row(descricao[grupo], str(len(lista)), str(len(com_grade)), str(com_credito), str(com_saida), cadastro)
    console.print(tabela)
    console.print(
        f'Retratos de entrada lidos: {resumo["total"]} · incompletos (ignorados): {resumo["retratos_incompletos"]} · '
        f'sem quantidade na NF (sem crédito por unidade): {resumo["sem_quantidade"]}'
    )
    if grupos['MISTO']:
        console.print('[yellow]Atenção: produtos MISTOS (PIS e COFINS com CSTs que não combinam) — confira alguns:[/yellow]')
        for c in grupos['MISTO'][:5]:
            console.print(f'  SKU {escape(str(c["sku"]))} · CST PIS {c["cst_pis"]} / COFINS {c["cst_cofins"]}')

    # Se um SKU de ESCOLHAS_FIXAS caiu em MISTO (PIS e COFINS com CSTs que não combinam), ele não serve
    # de CST 02/04/06 — avisa, senão o script sortearia outro produto sem você saber por quê.
    for sku_fixo in ESCOLHAS_FIXAS:
        if any(c['sku'] == sku_fixo for c in grupos['MISTO']):
            console.print(
                f'[yellow]O SKU fixo {escape(sku_fixo)} caiu no grupo MISTO — não entra como produto de '
                f'CST 02/04/06; o script vai sortear outro produto pra esse papel.[/yellow]'
            )

    escolhidos = []
    for papel, grupo in (('CST 02', '02'), ('CST 04', '04'), ('CST 06', '06'), (PAPEL_CONTROLE, 'FORA')):
        com_linha = [c for c in grupos[grupo] if '_linha' in c]
        elegiveis = [
            c for c in com_linha
            if tem_o_que_mudar(grupo, c['credito_total'], c['saida_total'],
                               situacao_saida_cadastro(c['pis_saida_cadastro'], c['cofins_saida_cadastro']))
        ]
        if not elegiveis and grupo != 'FORA' and com_linha:
            console.print(
                f'[yellow]"{papel}": nenhum produto do grupo tem algo pra mudar (crédito, saída e cadastro já estão em 0). '
                f'Vou escolher 1 mesmo assim, só pra confirmar que continua igual depois.[/yellow]'
            )
            elegiveis = com_linha
        if not elegiveis:
            console.print(f'[yellow]Sem candidato para "{papel}": {len(grupos[grupo])} produtos no grupo, nenhum com linha na grade que sirva.[/yellow]')
            continue

        fixo = next((c for c in elegiveis if c['sku'] in ESCOLHAS_FIXAS), None)
        candidato = fixo or escolher_pela_mediana(elegiveis)
        linha = candidato['_linha']

        escolhidos.append({
            'papel': papel,
            'produto_id': candidato['produto_id'],
            'variacao_id': linha.variacao_id,
            'sku': candidato['sku'],
            'ean': candidato['ean'],
            'titulo': candidato['titulo'],
            'mlb': linha.variacao.anuncio.mlb,
            'nf': candidato['nf'],
            'cst_pis': candidato['cst_pis'],
            'cst_cofins': candidato['cst_cofins'],
            'credito_pis_nota': candidato['credito_pis_nota'],
            'credito_cofins_nota': candidato['credito_cofins_nota'],
            'url': montar_url_pdf(candidato['produto_id'], linha.variacao_id),
            'antes': {
                **montar_snapshot(linha),
                'cadastro_pis': candidato['pis_saida_cadastro'],
                'cadastro_cofins': candidato['cofins_saida_cadastro'],
            },
        })

    if not escolhidos:
        console.print('[red]Nenhum produto escolhido — nada foi salvo.[/red]')
        return

    console.print()
    for e in escolhidos:
        a = e['antes']
        corpo = (
            f'[bold]{escape(str(e["titulo"]))}[/bold]\n'
            f'SKU {escape(str(e["sku"]))} · EAN {escape(str(e["ean"]))} · NF {escape(str(e["nf"]))} · {e["mlb"]}\n'
            f'CST XML — PIS {e["cst_pis"]} / COFINS {e["cst_cofins"]} · crédito na nota por unidade: '
            f'PIS {_fmt(e["credito_pis_nota"], prefixo="R$ ")} · COFINS {_fmt(e["credito_cofins_nota"], prefixo="R$ ")}\n'
            f'ANTES na grade ({TIPO_ANUNCIO} · {MARGEM}): preço {_fmt(a["preco"], prefixo="R$ ")} · '
            f'margem {_fmt(a["margem_obtida_pct"], sufixo="%")} · FIXO {_fmt(a["fixo"], prefixo="R$ ")} · '
            f'taxa {_fmt(a["taxa_pct"], sufixo="%")} · saída PIS {_fmt(a["pis_saida_pct"], sufixo="%")} / '
            f'COFINS {_fmt(a["cofins_saida_pct"], sufixo="%")}\n'
            f'CADASTRO do produto (saída): PIS {_fmt(a["cadastro_pis"], sufixo="%")} / COFINS {_fmt(a["cadastro_cofins"], sufixo="%")}'
            f' ("—" = vazio)\n'
            f'[dim]{descrever_expectativa(e["papel"], a)}[/dim]'
        )
        console.print(Panel(corpo, title=e['papel'], title_align='left'))

    console.print('\n[bold]LINKS dos PDFs "Antes"[/bold] (abra, Ctrl+P, "Salvar como PDF"; nome sugerido ao lado):')
    for e in escolhidos:
        console.print(f'\nAntes_{e["papel"].replace(" ", "_")}.pdf', markup=False, highlight=False)
        console.print(e['url'], soft_wrap=True, markup=False, highlight=False)

    conteudo = {
        'empresa': EMPRESA, 'tipo_anuncio': TIPO_ANUNCIO, 'margem': MARGEM,
        'criado_em': datetime.now().isoformat(timespec='seconds'), 'escolhidos': escolhidos,
    }
    CAMINHO_JSON.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding='utf-8')
    console.print(
        f'\n[green]Produtos e números de "antes" salvos em {CAMINHO_JSON.name}.[/green] '
        'Depois de rodar os comandos, rode este mesmo script de novo: ele confere o "depois".'
    )


# ----------------------------------------------------------------------------------------
# Modo DEPOIS
# ----------------------------------------------------------------------------------------

def rodar_modo_depois():
    conteudo = json.loads(CAMINHO_JSON.read_text(encoding='utf-8'))
    console.print(f'Modo DEPOIS: usando os produtos de {CAMINHO_JSON.name} (criado em {conteudo["criado_em"]}).')

    total_ok = total_conferencias = 0
    avisos = set()

    for e in conteudo['escolhidos']:
        linha = (
            GradePrecificacaoML.objects
            .filter(produto_id=e['produto_id'], variacao_id=e['variacao_id'], tipo_anuncio=conteudo['tipo_anuncio'], margem=conteudo['margem'])
            .select_related('variacao__anuncio').first()
        )
        console.print(f'\n[bold]{e["papel"]}[/bold] — SKU {escape(str(e["sku"]))} · {e["mlb"]}')
        if linha is None or not linha.resolvida or not linha.detalhamento:
            motivo = linha.motivo_nao_resolvida if linha is not None else 'linha não existe mais'
            console.print(f'[red]Sem linha resolvida na grade agora ({escape(str(motivo))}). Não dá pra conferir.[/red]')
            avisos.add('Algum produto saiu da grade ou ficou sem preço — vale abrir o modal dele.')
            continue

        cadastro_agora = Produto.objects.filter(pk=e['produto_id']).values('pis_percentual', 'cofins_percentual').first() or {}
        dados_depois = {
            **montar_snapshot(linha),
            'cadastro_pis': _txt(cadastro_agora.get('pis_percentual')),
            'cadastro_cofins': _txt(cadastro_agora.get('cofins_percentual')),
        }
        itens, nao_recalculada = montar_conferencias(e['papel'], e['antes'], dados_depois)
        if nao_recalculada:
            avisos.add('A grade de algum produto da regra NÃO mudou nada — ela ainda não foi recalculada (rode o passo 4: '
                       'calcular_grade_precificacao_ml ou calcular_todas_as_grades_precificacao).')

        tabela = Table(show_lines=True)
        for coluna in ('Item', 'Antes', 'Depois', 'Esperado', ''):
            tabela.add_column(coluna)
        for rotulo, antes, depois, esperado, passou in itens:
            tabela.add_row(rotulo, str(antes), str(depois), esperado, '[green]✓[/green]' if passou else '[red]✗[/red]')
            total_conferencias += 1
            total_ok += 1 if passou else 0
        console.print(tabela)

        if e['papel'] != PAPEL_CONTROLE:
            if not _perto(dados_depois['cadastro_pis'], 0, Decimal('0.005')) or not _perto(dados_depois['cadastro_cofins'], 0, Decimal('0.005')):
                avisos.add('O CADASTRO de PIS/COFINS de saída de algum produto da regra ainda não está em 0,00 — rode o passo 3 (preencher_impostos_saida).')
            credito_zerou = _perto(dados_depois['credito_pis'], 0, Decimal('0.005')) and _perto(dados_depois['credito_cofins'], 0, Decimal('0.005'))
            saida_igual = _dec(dados_depois['pis_saida_pct']) == _dec(e['antes']['pis_saida_pct']) and _dec(dados_depois['cofins_saida_pct']) == _dec(e['antes']['cofins_saida_pct'])
            if credito_zerou and saida_igual and _dec(e['antes']['pis_saida_pct']):
                avisos.add(
                    'Crédito zerou, mas a saída (PIS/COFINS %) continua igual: a grade foi recalculada ANTES do '
                    'preencher_impostos_saida (ou ele não pegou o produto). Rode o passo 3 e recalcule de novo.'
                )

    console.print(f'\n[bold]Resultado: {total_ok} de {total_conferencias} conferências ✓[/bold]')
    for aviso in sorted(avisos):
        console.print(f'[yellow]• {aviso}[/yellow]')


def main():
    definir_empresa_ativa(EMPRESA_POR_ALIAS_BANCO[EMPRESA])

    if CAMINHO_JSON.exists() and not REESCOLHER:
        rodar_modo_depois()
    else:
        rodar_modo_antes()


if __name__ == '__main__':
    main()
