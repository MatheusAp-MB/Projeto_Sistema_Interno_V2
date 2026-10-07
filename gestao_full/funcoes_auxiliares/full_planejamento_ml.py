# gestao_full/funcoes_auxiliares/full_planejamento_ml.py
#
# Monta a tela FINAL "Full — Planejamento de envios" (a versão organizada, para apresentar).
# A tela de debug "Full — ficha do código" continua existindo (full_ml.py): ela guarda o detalhe de
# cada campo; esta aqui parte do PRODUTO e responde, de cima para baixo, o que quem planeja envios
# quer saber:
#   1) Qual é o produto?                     (EAN, SKU, título, cód. fabricante, marca, estoque, imagem)
#   2) Quais Códigos ML do Full ele tem?     (um mesmo SKU pode ter mais de um)
#   3) Para cada Código ML: preciso enviar?  (urgência, sugestão, recomendação)
#   4) Por quê?                              (estoque no Full, vendas dos últimos 30 dias e por semana)
#   5) Quais anúncios usam esse Código ML?   (MLB, título, status, preço...)
#
# REGRA DO MATHEUS: NUNCA chamar a API do ML sozinha. Tudo aqui LÊ do banco e do arquivo
# detalhes_mlbs.json (leitura de arquivo, sem rede). Os números do Full (REPOS e ESTOQUE) vêm da
# última consulta salva (ConsultaFullMercadoLivre); quem consulta o ML é só o botão "Consultar no
# Mercado Livre", que reaproveita a mesma view da ficha de debug.
#
# Este arquivo NÃO repete a lógica da ficha: reaproveita o catálogo de campos, os formatadores, a
# leitura do banco e o registro de situações (A validar / Hipótese / Válido / Inválido) do full_ml.py.
# Cada número mostrado carrega a sua FONTE, o caminho exato do campo e o SELO de conferência — o
# mesmo registro que a equipe preenche na ficha de debug.

import json
import re
from datetime import datetime
from types import SimpleNamespace

from mercado_livre.funcoes_auxiliares.badges import (
    BADGES_CATALOGO, BADGES_CONFERENCIA_FULL, BADGES_LOGISTICA, BADGES_STATUS, BADGES_TIPO_ANUNCIO,
    BADGES_URGENCIA_FULL, BADGE_ESTRELA_FULL, BADGE_PADRAO, badge_de, badge_flex,
)
from gestao_full.funcoes_auxiliares.full_ml import (
    CATALOGO_FULL, CAMPOS_PRODUTO_BANCO, FONTES_FULL, MOTIVO_INDISPONIVEL, RECOMENDACAO, ROTULO_PROJETO,
    SITUACAO_PADRAO, _data_curta, _fmt_preco, _inventario_do_upid, _linha_do_banco, _n_br, _ordenar_semanas,
    _rotulo_do_anuncio, _valor_api, _variacao_do_banco, buscar_ultima_consulta, chave_campo, etiqueta_projeto,
    ler_banco, pegar,
)

LIMITE_PRODUTOS_NA_TELA = 5
LIMITE_SUGESTOES = 12

# Ordem em que os Códigos ML aparecem: o mais urgente primeiro; quem ainda não foi consultado, por último.
RANK_URGENCIA = {'URGENT': 0, 'THIS_WEEK': 1, 'NEXT_WEEK': 2, 'IN_TWO_WEEKS': 3, 'NO_URGENCY': 4, 'EXCEDENT': 5}
RANK_SEM_URGENCIA = 8
RANK_SEM_CONSULTA = 9

# Ordem dos anúncios dentro de um Código ML: ativos primeiro, encerrados por último.
RANK_STATUS = {'active': 0, 'paused': 1, 'under_review': 2, 'not_yet_active': 3, 'payment_required': 4, 'closed': 9}


# ---------------------------------------------------------------------------
# O ARQUIVO detalhes_mlbs.json (LEITURA DE ARQUIVO — sem rede, sem API)
# ---------------------------------------------------------------------------
# * [EXPLICAÇÃO] → Desde 07/10/2026 o banco TAMBÉM guarda o inventory_id (variacao.inventory_id, gravado pelo
#                  importar_anuncios_ml), mas ESTA tela ainda usa o arquivo como ponte SKU -> Códigos ML: ela
#                  também lê do arquivo dezenas de campos de cada anúncio, então trocar a ponte é um passo à
#                  parte. O arquivo é grande, então é lido UMA vez e guardado na memória
#                  do servidor, e só é lido de novo quando o arquivo muda (data de modificação/tamanho).
#                  Reaproveita _ler_detalhes da consulta (a mesma leitura que o botão usa).
_CACHE_ARQUIVO = {}


def _indexar_arquivo(registros, gerado_em):
    por_sku, por_inventario, por_mlb, por_upid, sku_original = {}, {}, {}, {}, {}
    for r in registros:
        sku = str(r.get('sku') or '').strip()
        if sku:
            por_sku.setdefault(sku.upper(), []).append(r)
            sku_original.setdefault(sku.upper(), sku)
        for campo, indice in (('inventory_id', por_inventario), ('mlb', por_mlb), ('user_product_id', por_upid)):
            valor = str(r.get(campo) or '').strip().upper()
            if valor:
                indice.setdefault(valor, []).append(r)
    return {'registros': registros, 'gerado_em': gerado_em, 'por_sku': por_sku, 'por_inventario': por_inventario,
            'por_mlb': por_mlb, 'por_upid': por_upid, 'sku_original': sku_original}


# Função Objetivo: O arquivo já indexado por SKU, Código ML, MLB e user_product_id, ou (None, "texto do problema")
# se ele não existe / está ilegível. Só lê o arquivo de novo quando ele mudou desde a última leitura.
def ler_arquivo_detalhes(empresa):
    from integracao_mercado_livre.servicos.buscar_detalhes import _caminho_saida_json
    from integracao_mercado_livre.servicos.consultar_full_ml import ErroConsultaFull, _ler_detalhes

    caminho = _caminho_saida_json(empresa)
    try:
        estado = caminho.stat()
    except OSError:
        return None, ('O arquivo detalhes_mlbs.json desta empresa não existe. '
                      'Rode o comando buscar_detalhes para esta empresa.')
    chave = (estado.st_mtime_ns, estado.st_size)
    guardado = _CACHE_ARQUIVO.get(str(caminho))
    if guardado and guardado['chave'] == chave:
        return guardado['arquivo'], ''
    try:
        registros, gerado_em = _ler_detalhes(empresa)
    except ErroConsultaFull as erro:
        return None, str(erro)
    arquivo = _indexar_arquivo(registros, gerado_em)
    _CACHE_ARQUIVO[str(caminho)] = {'chave': chave, 'arquivo': arquivo}
    return arquivo, ''


def _data_hora_do_texto(texto):
    """'2026-10-05 10:11:12' -> '05/10/2026 10:11'. Se não for uma data, devolve o texto como está."""
    texto = str(texto or '').strip()
    if not texto:
        return ''
    try:
        momento = datetime.fromisoformat(texto.replace('Z', '+00:00'))
    except ValueError:
        return texto
    return momento.strftime('%d/%m/%Y %H:%M')


# ---------------------------------------------------------------------------
# A BUSCA — SKU, EAN, Código ML ou MLB
# ---------------------------------------------------------------------------
def _mlb_do_texto(alvo):
    """'MLB5838465508', '#5838465508' ou só os números (9+ dígitos) -> 'MLB5838465508'. Outra coisa -> None."""
    if alvo.startswith('MLBU'):
        return None
    digitos = ''.join(c for c in alvo if c.isdigit())
    if alvo.startswith('MLB') and digitos == alvo[3:] and digitos:
        return f'MLB{digitos}'
    if alvo.startswith('#') and digitos == alvo[1:] and digitos:
        return f'MLB{digitos}'
    if alvo.isdigit() and len(alvo) >= 9:
        return f'MLB{alvo}'
    return None


def _produto_para_tela(produto):
    dados = _linha_do_banco(produto, CAMPOS_PRODUTO_BANCO)
    return {
        'sku': dados['sku'] or '', 'ean': dados['ean'] or '', 'titulo': dados['titulo'] or '', 'marca': dados['marca'] or '',
        'cod_fabricante': dados['cod_fabricante'] or '', 'estoque': dados['estoque'], 'imagem_url': dados['imagem_url'] or '',
    }


# Função Objetivo: Descobre QUAIS SKUs o texto digitado pede. Tenta, nesta ordem (todas só LEEM): SKU/EAN no
# cadastro, SKU no arquivo, Código ML, MLB, user_product_id e, por último, uma consulta de Código ML já salva
# (para um código que o arquivo ainda não conhece). Se nada bater exatamente, devolve sugestões pelo cadastro
# (cada palavra digitada precisa aparecer no SKU, título, EAN, cód. fabricante ou marca).
# Devolve {"texto", "achados": {SKU_MAIUSCULO: {"sku", "motivo"}}, "consultas_extra": [consulta...],
#          "sugestoes": [...], "mais_sugestoes": bool, "sem_sku": [...]}.
def resolver_busca(texto, arquivo):
    from django.db.models import Q
    from produtos.models import Produto

    q = ' '.join(str(texto or '').split())
    resultado = {'texto': q, 'achados': {}, 'consultas_extra': [], 'sugestoes': [], 'mais_sugestoes': False, 'sem_sku': []}
    if not q:
        return resultado
    alvo = q.upper()
    achados = resultado['achados']

    def somar(sku, motivo):
        sku = str(sku or '').strip()
        if sku and sku.upper() not in achados:
            achados[sku.upper()] = {'sku': sku, 'motivo': motivo}

    for produto in Produto.objects.filter(Q(sku__iexact=q) | Q(ean=q)).only('sku', 'ean', 'titulo'):
        if produto.sku:
            somar(produto.sku, 'SKU' if produto.sku.upper() == alvo else 'EAN')
        else:
            resultado['sem_sku'].append({'ean': produto.ean, 'titulo': produto.titulo})

    if arquivo:
        if alvo in arquivo['sku_original']:
            somar(arquivo['sku_original'][alvo], 'SKU')
        for r in arquivo['por_inventario'].get(alvo, []):
            somar(r.get('sku'), f'Código ML {alvo}')
        mlb = _mlb_do_texto(alvo)
        if mlb:
            for r in arquivo['por_mlb'].get(mlb, []):
                somar(r.get('sku'), f'anúncio {mlb}')
        for r in arquivo['por_upid'].get(alvo, []):
            somar(r.get('sku'), f'produto do vendedor {alvo}')

    if not achados:
        consulta = buscar_ultima_consulta(alvo)
        if consulta:
            resultado['consultas_extra'].append(consulta)
            for r in consulta.registros_arquivo or []:
                somar(r.get('sku'), f'consulta salva do Código ML {alvo}')
            for pacote in consulta.reposicao.values():
                somar(pegar(pacote.get('dados'), 'identifiers.seller_sku'), f'consulta salva do Código ML {alvo}')

    if not achados and not resultado['sem_sku']:
        filtro = Q()
        for palavra in q.split():
            filtro &= (Q(sku__icontains=palavra) | Q(titulo__icontains=palavra) | Q(ean__icontains=palavra)
                       | Q(cod_fabricante__icontains=palavra) | Q(marca__icontains=palavra))
        encontrados = list(Produto.objects.filter(filtro).order_by('titulo')[:LIMITE_SUGESTOES + 1])
        resultado['mais_sugestoes'] = len(encontrados) > LIMITE_SUGESTOES
        resultado['sugestoes'] = [_produto_para_tela(p) for p in encontrados[:LIMITE_SUGESTOES]]
    return resultado


# ---------------------------------------------------------------------------
# SELOS E FONTES — o que acompanha cada número
# ---------------------------------------------------------------------------
_ENTRADAS = {(c['fonte'], c['caminho']): c for c in CATALOGO_FULL}


# Função Objetivo: O selo de conferência de 1 campo (fonte + caminho) — lido do registro que a equipe preenche na
# ficha de debug. Campo sem registro = "Não conferido". A dica traz o nome interno e a observação, se houver.
def _selo(fonte, caminho, validacoes, rotulos_situacao):
    registro = validacoes.get(chave_campo(fonte, caminho)) or {}
    situacao = registro.get('situacao') or SITUACAO_PADRAO
    badge = BADGES_CONFERENCIA_FULL.get(situacao, BADGES_CONFERENCIA_FULL[SITUACAO_PADRAO])
    partes = [f'Na ficha de debug: {rotulos_situacao.get(situacao, situacao)}']
    if registro.get('nome_interno'):
        partes.append(f"nome interno: {registro['nome_interno']}")
    if registro.get('observacao'):
        partes.append(f"observação: {registro['observacao']}")
    return {'situacao': situacao, 'badge': badge, 'dica': ' · '.join(partes)}


# * [EXPLICAÇÃO] → O caminho de um campo (ex.: "recommendation.suggested_quantity") é comprido e não tem espaços, então
#                  o navegador o cortaria no meio de uma palavra. Em vez de inserir caracteres invisíveis (que iriam
#                  junto se alguém copiasse o texto), o caminho vai em PEDAÇOS e a tela põe um <wbr> (ponto de quebra
#                  opcional) entre eles: quebra só depois de "." e "_", e o texto copiado continua exato.
def _caminho_em_pedacos(caminho):
    return [pedaco for pedaco in re.split(r'(?<=[._])', caminho) if pedaco]


def _meta_do_campo(fonte, caminho, validacoes, rotulos_situacao):
    info = FONTES_FULL[fonte]
    return {
        'fonte': fonte, 'caminho': caminho, 'caminho_pedacos': _caminho_em_pedacos(caminho),
        'projeto': info['projeto'], 'projeto_rotulo': ROTULO_PROJETO[info['projeto']],
        'etiqueta': etiqueta_projeto(fonte), 'endpoint': info['endpoint_modelo'],
        'selo': _selo(fonte, caminho, validacoes, rotulos_situacao),
    }


def _bruto_texto(pacote, caminho):
    """O trecho que a API mandou para este campo, como texto (para a dica 'Como veio da API')."""
    if not pacote or not pacote.get('dados'):
        return ''
    valor = pegar(pacote['dados'], caminho)
    return '' if valor is None else json.dumps(valor, ensure_ascii=False)


# Função Objetivo: A frase que a tela escreve no lugar do número quando não há número para mostrar.
def _explicacao_do_estado(estado, nota):
    if estado == 'vazio':
        return 'A API respondeu, mas não mandou este campo para este código.'
    if estado == 'erro':
        return f'A consulta falhou: {nota}' if nota else 'A consulta falhou.'
    if estado == 'sem_chamada':
        return 'Este código ainda não foi consultado.'
    return ''


# Função Objetivo: 1 número da tela já com tudo que o acompanha: o valor (do jeito que o full_ml.py formata), o estado
# ("ok", "vazio", "erro", "sem_chamada" ou "so_tela"), a fonte + caminho do campo, se o endpoint é NOVO ou JÁ USADO e o
# selo de conferência. "tipo" diz como o valor é desenhado: "numero" (grande), "texto" (frase) ou "pilula".
# "formatador" troca só o jeito de ESCREVER o valor: recebe o valor cru e devolve (texto, nota).
def _tile(fonte, caminho, pacote, validacoes, rotulos_situacao, rotulo=None, tipo='numero', formatador=None):
    entrada = _ENTRADAS[(fonte, caminho)]
    if fonte == 'TELA':
        estado, texto, nota = 'so_tela', entrada['nota'], ''
    else:
        estado, texto, nota = _valor_api(entrada, pacote)
        if estado == 'ok' and formatador:
            texto, nota = formatador(pegar(pacote['dados'], caminho), pacote['dados'])
    return {
        'rotulo': rotulo or entrada['nome'], 'nome_no_catalogo': entrada['nome'], 'tipo': tipo, 'estado': estado,
        'valor': texto, 'nota': nota, 'explicacao': _explicacao_do_estado(estado, nota),
        'bruto': _bruto_texto(pacote, caminho) if fonte != 'TELA' else '',
        'meta': _meta_do_campo(fonte, caminho, validacoes, rotulos_situacao), 'sub': [], 'pilula': None,
    }


def _motivos_legivel(valor, dados):
    """[{"status": "transfer", "quantity": 2}] -> '2 em transferência · 1 perdida'."""
    if not isinstance(valor, list) or not valor:
        return 'nenhuma unidade indisponível', ''
    partes = [f"{_n_br(item.get('quantity'))} {MOTIVO_INDISPONIVEL.get(item.get('status'), item.get('status'))}"
              for item in valor if isinstance(item, dict)]
    return (' · '.join(partes) or 'nenhuma unidade indisponível'), ''


def _recomendacao_legivel(valor, dados):
    traducao = RECOMENDACAO.get(valor)
    return (traducao[:1].upper() + traducao[1:] if traducao else str(valor)), f'(valor da API: {valor})'


def _beneficios_legivel(valor, dados):
    if isinstance(valor, list) and not valor:
        return 'Nenhum benefício', '(lista vazia)'
    if isinstance(valor, list):
        return ', '.join(str(v) for v in valor), '(AGING = estoque antigo)' if 'AGING' in valor else ''
    return str(valor), ''


def _estrela_legivel(valor, dados):
    if not isinstance(valor, list):
        return str(valor), ''
    return ('Sim' if 'star_product' in valor else 'Não'), f'(tags: {", ".join(str(t) for t in valor) or "nenhuma"})'


def _prazo_legivel(valor, dados):
    return _data_curta(valor) if len(str(valor)) == 10 else str(valor), f'(valor da API: {valor})'


# ---------------------------------------------------------------------------
# O GRÁFICO DE VENDAS POR SEMANA (SVG desenhado aqui, sem JavaScript)
# ---------------------------------------------------------------------------
# * [EXPLICAÇÃO] → Todos os números do SVG saem como TEXTO já formatado ("12.5"): o Django, em português, escreve
#                  decimais com vírgula, e uma vírgula dentro de um atributo de SVG o quebra.
LARGURA_BARRA, PASSO_BARRA, MARGEM_ESQ, MARGEM_DIR, TOPO_GRAFICO, ALTURA_AREA, RODAPE_GRAFICO = 34, 56, 44, 12, 26, 130, 44


def _teto_do_eixo(maximo):
    """O menor valor 'redondo' (1, 1,2, 1,5, 2, 2,5, 3, 4, 5, 6, 8 ou 10 vezes uma potência de 10) que cobre o maior
    valor. Os fatores intermediários evitam o exagero de, por exemplo, 106 unidades ganharem um eixo até 200."""
    if maximo <= 0:
        return 10
    potencia = 1
    while potencia * 10 < maximo:
        potencia *= 10
    for fator in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if potencia * fator >= maximo:
            return potencia * fator
    return potencia * 10


def _grafico_semanas(dados_rep):
    semanas = _ordenar_semanas(pegar(dados_rep, 'sales.sales_history') if dados_rep else None)
    if not semanas:
        return None
    vendidas = [int(s.get('units_sold') or 0) for s in semanas]
    teto = _teto_do_eixo(max(vendidas))
    base_y = TOPO_GRAFICO + ALTURA_AREA
    barras = []
    for i, (semana, unidades) in enumerate(zip(semanas, vendidas)):
        altura = ALTURA_AREA * unidades / teto
        x = MARGEM_ESQ + i * PASSO_BARRA + (PASSO_BARRA - LARGURA_BARRA) / 2
        dias = int(semana.get('days_out_of_stock') or 0)
        campanha = bool(semana.get('campaigns'))
        periodo = f"{_data_curta(semana.get('start_date'))} a {_data_curta(semana.get('end_date'))}"
        dica = f'{periodo}: {_n_br(unidades)} un.'
        if dias:
            dica += f' · {dias} dia(s) sem estoque'
        if campanha:
            dica += ' · semana com campanha'
        barras.append({
            'x': f'{x:.1f}', 'y': f'{base_y - altura:.1f}', 'largura': f'{LARGURA_BARRA}', 'altura': f'{altura:.1f}',
            'centro': f'{x + LARGURA_BARRA / 2:.1f}', 'y_valor': f'{base_y - altura - 5:.1f}',
            'y_data': f'{base_y + 15}', 'y_dias': f'{base_y + 30}', 'y_campanha': f'{base_y - altura - 17:.1f}',
            'unidades': _n_br(unidades), 'data': _data_curta(semana.get('start_date')), 'dias': dias, 'campanha': campanha,
            'dica': dica,
        })
    # * [EXPLICAÇÃO] → Unidades são números inteiros: a linha do meio só aparece quando a metade do teto também é inteira
    #                  (teto 120 → 60; teto 5 → sem linha do meio, em vez de "2,5 unidades").
    linhas_guia = []
    for fracao in (0, 0.5, 1):
        valor = teto * fracao
        if not float(valor).is_integer():
            continue
        linhas_guia.append({'y': f'{base_y - ALTURA_AREA * fracao:.1f}', 'x_texto': f'{MARGEM_ESQ - 6}',
                            'texto': _n_br(int(valor))})
    largura = MARGEM_ESQ + len(semanas) * PASSO_BARRA + MARGEM_DIR
    return {
        'largura': largura, 'altura': base_y + RODAPE_GRAFICO, 'x_inicio': f'{MARGEM_ESQ}', 'x_fim': f'{largura - MARGEM_DIR}',
        'barras': barras, 'guias': linhas_guia, 'total': _n_br(sum(vendidas)), 'n_semanas': len(semanas),
        'com_dias_sem_estoque': any(b['dias'] for b in barras), 'com_campanha': any(b['campanha'] for b in barras),
    }


# ---------------------------------------------------------------------------
# OS ANÚNCIOS de um Código ML (1 linha por MLB, ou por variação)
# ---------------------------------------------------------------------------
def _linha_de_anuncio(r, banco, sku_da_tela):
    mlb = str(r.get('mlb') or '')
    anuncio_banco = banco['anuncios'].get(mlb) if banco else None
    tipo_banco = (anuncio_banco or {}).get('tipo_de_anuncio') or {}
    sku = str(r.get('sku') or '').strip()
    return {
        'mlb': mlb, 'variacao_id': r.get('variacao_id') or '', 'rotulo': _rotulo_do_anuncio(r),
        'variacao_atributos': r.get('variacao_atributos') or '', 'titulo': r.get('title') or '',
        'permalink': r.get('permalink') or '', 'imagem': r.get('imagem_principal') or r.get('thumbnail') or '',
        'status': r.get('status'), 'badge_status': badge_de(BADGES_STATUS, r.get('status')),
        'badge_tipo': badge_de(BADGES_TIPO_ANUNCIO, r.get('listing_type_id')),
        'badge_logistica': badge_de(BADGES_LOGISTICA, r.get('logistic_type')),
        'badge_flex': badge_flex(bool(r.get('flex'))),
        'badge_catalogo': badge_de(BADGES_CATALOGO, tipo_banco.get('classificacao_catalogo')) if tipo_banco else None,
        'estoque': _n_br(r.get('available_quantity')) if r.get('available_quantity') is not None else '—',
        'vendidos': _n_br(r.get('sold_quantity')) if r.get('sold_quantity') is not None else '—',
        'preco': _fmt_preco(r['price'], None)[0] if r.get('price') is not None else '—',
        'preco_original': _fmt_preco(r['original_price'], None)[0] if r.get('original_price') else '',
        'sku': sku, 'de_outro_sku': bool(sku) and sku.upper() != sku_da_tela.upper(),
        'banco_lido': banco is not None, 'anuncio_no_banco': anuncio_banco is not None,
        'variacao_no_banco': _variacao_do_banco(banco, r) is not None if banco else None,
        'rank': RANK_STATUS.get(r.get('status'), 5),
    }


def _anuncios_ordenados(registros, banco, sku_da_tela):
    linhas = [_linha_de_anuncio(r, banco, sku_da_tela) for r in registros]
    return sorted(linhas, key=lambda a: (a['rank'], a['mlb'], str(a['variacao_id'])))


# ---------------------------------------------------------------------------
# O CARTÃO DE 1 CÓDIGO ML
# ---------------------------------------------------------------------------
def _upid_do_codigo(registros, consulta):
    """O user_product_id (MLBU) que a consulta usou para este Código ML, e a lista de todos que o código tem."""
    todos = []
    for r in registros:
        if r.get('user_product_id') and r['user_product_id'] not in todos:
            todos.append(r['user_product_id'])
    if consulta:
        for upid in consulta.reposicao:
            if upid not in todos:
                todos.append(upid)
    escolhido = next((u for u in todos if consulta and u in consulta.reposicao), todos[0] if todos else None)
    return escolhido, todos


def _avisos_dos_pacotes(pacote_rep, pacote_est):
    avisos = []
    for nome, pacote in (('REPOS', pacote_rep), ('ESTOQUE', pacote_est)):
        if pacote is None:
            continue
        if pacote.get('erro'):
            avisos.append(f"{nome}: o Mercado Livre devolveu um erro — {pacote['erro']}")
        elif pacote.get('x_content_missing'):
            avisos.append(f"{nome}: a resposta veio incompleta (X-Content-Missing: {pacote['x_content_missing']}).")
    return avisos


# Função Objetivo: O cartão de 1 Código ML. "registros" são os anúncios do código no arquivo; "consulta" é a última
# consulta salva dele (ou None). Sem consulta, o cartão só mostra os anúncios e o convite para consultar: não há
# número do Full para exibir. Com consulta, monta os blocos na ordem em que o planejador lê: Resumo (o que fazer),
# Estoque, Vendas, Detalhes da reposição e o que ainda não tem fonte.
def _montar_codigo(codigo, registros, consulta, banco, sku_da_tela, validacoes, rotulos_situacao, ancora, formatar_data_hora):
    upid, upids = _upid_do_codigo(registros, consulta)
    pacote_rep = consulta.reposicao.get(upid) if consulta and upid else None
    dados_rep = (pacote_rep or {}).get('dados')
    registros_upid = [r for r in registros if r.get('user_product_id') == upid] if upid else registros
    inventario = _inventario_do_upid(dados_rep, registros_upid, consulta.estoque) if consulta else None
    pacote_est = consulta.estoque.get(inventario) if consulta and inventario else None

    anuncios = _anuncios_ordenados(registros, banco, sku_da_tela)
    card = {
        'ancora': ancora, 'codigo': codigo, 'user_product_id': upid, 'consultado': consulta is not None,
        'badge_estrela': BADGE_ESTRELA_FULL,
        'consulta_quando': formatar_data_hora(consulta.consultado_em) if consulta else '',
        'consulta_usuario': consulta.usuario if consulta else '',
        'aviso_varios_produtos': (f'Este Código ML tem {len(upids)} produtos do vendedor ({", ".join(upids)}); '
                                  f'a tela mostra o {upid}. Veja a ficha de debug para os outros.') if len(upids) > 1 else '',
        'avisos': _avisos_dos_pacotes(pacote_rep, pacote_est) if consulta else [],
        'anuncios': anuncios, 'n_anuncios': len(anuncios),
        'n_outro_sku': sum(1 for a in anuncios if a['de_outro_sku']),
        'n_fora_do_banco': sum(1 for a in anuncios if a['banco_lido'] and not a['anuncio_no_banco']),
        'rank': RANK_SEM_CONSULTA, 'urgencia_badge': None, 'estrela': False, 'resumo': [], 'estoque': [], 'vendas': [],
        'grafico': None, 'grafico_meta': None, 'reposicao': [], 'sem_fonte': [],
    }
    if consulta is None:
        return card

    def tile(fonte, caminho, pacote, **kw):
        return _tile(fonte, caminho, pacote, validacoes, rotulos_situacao, **kw)

    urgencia = tile('REPOS', 'stock.shipping_urgency', pacote_rep, rotulo='Urgência de envio', tipo='pilula')
    bruto_urgencia = pegar(dados_rep, 'stock.shipping_urgency') if dados_rep else None
    if urgencia['estado'] == 'ok':
        urgencia['pilula'] = BADGES_URGENCIA_FULL.get(bruto_urgencia, {**BADGE_PADRAO, 'label': str(bruto_urgencia)})
        urgencia['valor'], urgencia['nota'] = urgencia['pilula']['label'], f'(valor da API: {bruto_urgencia})'
        card['urgencia_badge'] = urgencia['pilula']
        card['rank'] = RANK_URGENCIA.get(bruto_urgencia, RANK_SEM_URGENCIA)
    else:
        card['rank'] = RANK_SEM_URGENCIA

    estrela = tile('REPOS', 'product.tags', pacote_rep, rotulo='Produto Estrela', tipo='texto', formatador=_estrela_legivel)
    card['estrela'] = estrela['estado'] == 'ok' and estrela['valor'] == 'Sim'
    sugestao = tile('REPOS', 'recommendation.suggested_quantity', pacote_rep, rotulo='Sugestão de envio')
    # * [EXPLICAÇÃO] → Uma quantidade exata ("40 un.") cabe no tamanho grande; uma faixa ("de 300 a 450 un.") quebraria
    #                  em 2 linhas, então ela é escrita no tamanho de frase.
    if sugestao['estado'] == 'ok' and len(sugestao['valor']) > 12:
        sugestao['tipo'] = 'texto'
    card['resumo'] = [
        urgencia,
        sugestao,
        tile('REPOS', 'recommendation.recommendation_type', pacote_rep, rotulo='Recomendação', tipo='texto',
             formatador=_recomendacao_legivel),
        estrela,
    ]

    indisponivel = tile('ESTOQUE', 'not_available_quantity', pacote_est, rotulo='Indisponível')
    indisponivel['sub'].append(tile('ESTOQUE', 'not_available_detail', pacote_est, rotulo='Motivo', tipo='texto',
                                    formatador=_motivos_legivel))
    card['estoque'] = [
        tile('REPOS', 'stock.total_stock', pacote_rep, rotulo='Aptas e a caminho'),
        tile('ESTOQUE', 'total', pacote_est, rotulo='Total no estoque do Full'),
        tile('ESTOQUE', 'available_quantity', pacote_est, rotulo='Disponível para venda'),
        indisponivel,
        tile('REPOS', 'stock.minimum_distributable_stock', pacote_rep, rotulo='Mínimo para envios rápidos'),
    ]

    vendas = tile('REPOS', 'sales.sales_totals.units_sold[0].full', pacote_rep, rotulo='Vendas no Full — últimos 30 dias')
    vendas['sub'].append(tile('REPOS', 'sales.sales_totals.gmv[0].full', pacote_rep, rotulo='Valor vendido', tipo='texto'))
    card['vendas'] = [vendas]
    card['grafico'] = _grafico_semanas(dados_rep)
    card['grafico_meta'] = _meta_do_campo('REPOS', 'sales.sales_history', validacoes, rotulos_situacao)
    card['grafico_estado'] = _valor_api(_ENTRADAS[('REPOS', 'sales.sales_history')], pacote_rep)[0]

    card['reposicao'] = [
        tile('REPOS', 'recommendation.replenishment_deadline', pacote_rep, rotulo='Prazo para repor', tipo='texto',
             formatador=_prazo_legivel),
        tile('REPOS', 'recommendation.replenishment_frequency', pacote_rep, rotulo='Frequência de reposição (semanas)'),
        tile('REPOS', 'eligibility_benefits', pacote_rep, rotulo='Benefícios de elegibilidade', tipo='texto',
             formatador=_beneficios_legivel),
    ]

    # O que existe na página do ML e nenhuma API usada aqui entrega (e vale para o Código ML, não para a conta).
    card['sem_fonte'] = [tile('TELA', e['caminho'], None, tipo='texto') for e in CATALOGO_FULL
                         if e['fonte'] == 'TELA' and e['bloco'] in ('estoque', 'vendas', 'so_tela')]
    return card


# ---------------------------------------------------------------------------
# O CARTÃO DE 1 PRODUTO
# ---------------------------------------------------------------------------
def _consultas_dos_codigos(codigos, consultas_extra):
    """{CÓDIGO_MAIÚSCULO: a consulta mais recente} — 1 SELECT para todos os códigos da tela."""
    from mercado_livre.models import ConsultaFullMercadoLivre
    ultimas = {c.codigo.upper(): c for c in reversed(consultas_extra)}
    if codigos:
        for consulta in ConsultaFullMercadoLivre.objects.filter(codigo__in=sorted({c.upper() for c in codigos})):
            ultimas.setdefault(consulta.codigo.upper(), consulta)
    return ultimas


def _ler_produtos(skus):
    from produtos.models import Produto
    return {p.sku: _produto_para_tela(p) for p in Produto.objects.filter(sku__in=skus)}


def _registros_do_sku(sku, arquivo, consultas_extra):
    if arquivo and arquivo['por_sku'].get(sku.upper()):
        return list(arquivo['por_sku'][sku.upper()])
    return [r for c in consultas_extra for r in (c.registros_arquivo or []) if str(r.get('sku') or '').upper() == sku.upper()]


def _registros_do_codigo(codigo, arquivo, consultas_extra):
    if arquivo and arquivo['por_inventario'].get(codigo.upper()):
        return list(arquivo['por_inventario'][codigo.upper()])
    return [r for c in consultas_extra for r in (c.registros_arquivo or [])
            if str(r.get('inventory_id') or '').upper() == codigo.upper()]


# Função Objetivo: Quantas chamadas GET o botão "Consultar" vai fazer para 1 Código ML: 1 de estoque (o próprio Código ML)
# + 1 de reposição por user_product_id diferente nos anúncios dele. É a mesma conta que consultar_codigo
# (integracao_mercado_livre/servicos/consultar_full_ml.py) faz; aqui ela só serve para avisar a pessoa ANTES de clicar
# em "Sincronizar" — por isso a tela diz "cerca de" e nada é chamado.
def _chamadas_previstas(registros):
    user_products = {str(r.get('user_product_id')) for r in registros if r.get('user_product_id')}
    return 1 + len(user_products)


# Função Objetivo: A página inteira. Devolve {"texto", "estado", "produtos", "sugestoes", ...}; "estado" diz o que a tela
# desenha: "vazio" (nada digitado), "nao_achou", "escolher" (vários produtos parecidos: a pessoa escolhe) ou
# "produtos" (1 ou mais produtos, cada um com os seus Códigos ML). LÊ SÓ do arquivo e do banco.
def montar_planejamento(empresa, texto, validacoes, rotulos_situacao):
    from mercado_livre.funcoes_auxiliares.caracteristicas_ml import formatar_data_hora

    arquivo, erro_arquivo = ler_arquivo_detalhes(empresa)
    pagina = {
        'texto': ' '.join(str(texto or '').split()), 'estado': 'vazio', 'produtos': [], 'sugestoes': [], 'mais_sugestoes': False,
        'sem_sku': [], 'total_achados': 0,
        'arquivo': {'existe': arquivo is not None, 'erro': erro_arquivo, 'gerado_em': _data_hora_do_texto(arquivo['gerado_em']) if arquivo else '',
                    'n_registros': len(arquivo['registros']) if arquivo else 0},
    }
    if not pagina['texto']:
        return pagina

    resolucao = resolver_busca(texto, arquivo)
    pagina['sem_sku'] = resolucao['sem_sku']
    achados = list(resolucao['achados'].values())
    pagina['total_achados'] = len(achados)
    if not achados:
        pagina['estado'] = 'escolher' if resolucao['sugestoes'] else 'nao_achou'
        pagina['sugestoes'], pagina['mais_sugestoes'] = resolucao['sugestoes'], resolucao['mais_sugestoes']
        return pagina

    achados = achados[:LIMITE_PRODUTOS_NA_TELA]
    extras = resolucao['consultas_extra']
    skus = [a['sku'] for a in achados]
    produtos_db = _ler_produtos(skus)

    registros_do_sku = {sku: _registros_do_sku(sku, arquivo, extras) for sku in skus}
    codigos_do_sku = {}
    for sku, registros in registros_do_sku.items():
        codigos = []
        for r in registros:
            codigo = str(r.get('inventory_id') or '').strip()
            if codigo and codigo.upper() not in {c.upper() for c in codigos}:
                codigos.append(codigo)
        codigos_do_sku[sku] = codigos
    todos_codigos = [c for codigos in codigos_do_sku.values() for c in codigos]
    registros_do_codigo = {c: _registros_do_codigo(c, arquivo, extras) for c in todos_codigos}
    consultas = _consultas_dos_codigos(todos_codigos, extras)

    # * [EXPLICAÇÃO] → O banco é lido UMA vez para todos os anúncios que a tela vai mostrar (ler_banco: no máximo 4
    #                  consultas, só leitura). Ele recebe os registros no formato de "consulta" que a ficha de debug usa.
    vistos, todos_registros = set(), []
    for registros in list(registros_do_sku.values()) + list(registros_do_codigo.values()):
        for r in registros:
            if id(r) not in vistos:
                vistos.add(id(r))
                todos_registros.append(r)
    banco = ler_banco(SimpleNamespace(registros_arquivo=todos_registros, reposicao={})) if todos_registros else None

    for numero, achado in enumerate(achados, start=1):
        sku = achado['sku']
        cadastro = produtos_db.get(sku)
        cartoes = []
        for posicao, codigo in enumerate(codigos_do_sku[sku], start=1):
            cartoes.append(_montar_codigo(
                codigo, registros_do_codigo[codigo], consultas.get(codigo.upper()), banco, sku, validacoes, rotulos_situacao,
                f'plan-codigo-{numero}-{posicao}', formatar_data_hora))
        cartoes.sort(key=lambda c: (c['rank'], c['codigo']))
        for posicao, cartao in enumerate(cartoes, start=1):
            cartao['ancora'] = f'plan-codigo-{numero}-{posicao}'   # na ordem em que aparecem na tela (o link da faixa segue a mesma ordem)
        fora_do_full = [r for r in registros_do_sku[sku] if not str(r.get('inventory_id') or '').strip()]
        pagina['produtos'].append({
            'ancora': f'plan-produto-{numero}', 'sku': sku, 'motivo': achado['motivo'], 'cadastro': cadastro,
            'codigos': cartoes, 'fora_do_full': _anuncios_ordenados(fora_do_full, banco, sku),
            'n_chamadas_sync': sum(_chamadas_previstas(registros_do_codigo[c['codigo']]) for c in cartoes),
            'n_anuncios_no_arquivo': len(registros_do_sku[sku]), 'arquivo_existe': arquivo is not None,
            'titulo_do_anuncio': next((r.get('title') for r in registros_do_sku[sku] if r.get('title')), ''),
        })
    pagina['estado'] = 'produtos'
    return pagina


# Função Objetivo: A legenda da tela ("Como ler esta tela"): o que cada selo significa e de onde vem cada fonte.
def montar_legenda(rotulos_situacao):
    significado = {
        'valido': 'Alguém comparou com a tela do Mercado Livre e bateu (situação "Válido" na ficha de debug).',
        'hipotese': 'Achamos que é isso, mas ainda falta prova (situação "Hipótese").',
        'a_validar': 'Ainda ninguém comparou este dado com a tela do Mercado Livre (situação "A validar").',
        'invalido': 'Foi comparado com a tela e não bate (situação "Inválido"; a explicação fica na observação).',
    }
    selos = [{'badge': BADGES_CONFERENCIA_FULL[chave], 'texto': significado[chave]} for chave in BADGES_CONFERENCIA_FULL]
    fontes = [{'chave': chave, 'nome': info['nome'], 'endpoint': info['endpoint_modelo'], 'projeto': info['projeto'],
               'projeto_rotulo': ROTULO_PROJETO[info['projeto']], 'projeto_texto': info['projeto_texto']}
              for chave, info in FONTES_FULL.items()]
    return {'selos': selos, 'fontes': fontes}
