# impostos/funcoes_auxiliares/exibicao_icms_por_ncm.py

# Função Objetivo: Monta o dado pronto pra exibir a tela de ICMS por NCM
# (matriz NCM × UF + Média Ponderada) — nunca grava nada, só lê IcmsSaidaPorNcmCstOrigemUf
# e calcula a Média Ponderada em tempo real (decisão no vault: ela nunca
# é gravada, sempre calculada na hora, pra nunca ficar desatualizada).

from decimal import Decimal

from impostos.funcoes_auxiliares.saida.importacao_icms_ncm import UFS_ORDENADAS
from impostos.models import IcmsSaidaPorNcmCstOrigemUf

DUAS_CASAS_DECIMAIS = Decimal('0.01')
PESO_SP = Decimal('0.5')
PESO_OUTRAS = Decimal('0.5')


# Função Objetivo: Calcula a Média Ponderada de 1 NCM (SP × 50% + média das outras 26 × 50%).
# Explicação em detalhe: nunca força um valor — se SP está ausente, ou se
# nenhuma das outras 26 UFs tem valor, devolve None (exibido como "—" na
# tela), igual à regra já usada no mockup e na decisão do vault.
def calcular_media_ponderada(valores_por_uf):
    sp = valores_por_uf.get('SP')
    outras = [valores_por_uf[uf] for uf in UFS_ORDENADAS if uf != 'SP' and uf in valores_por_uf]

    if sp is None or not outras:
        return None

    media_outras = sum(outras) / len(outras)
    ponderada = (sp * PESO_SP) + (media_outras * PESO_OUTRAS)
    return ponderada.quantize(DUAS_CASAS_DECIMAIS)


# Função Objetivo: Monta as linhas da matriz — 1 por grupo NCM+Origem+CST,
# já com mostrar_ncm/rowspan_ncm e mostrar_origem/rowspan_origem prontos
# pra tela renderizar as 2 colunas mescladas (rowspan real), e a Média
# Ponderada calculada.
def montar_matriz_icms_por_ncm():
    # 13/09/2026 — chave expandida pra (NCM, CST, Origem): agrupar só por
    # NCM aqui misturava, na mesma linha, alíquotas de combinações CST/
    # Origem diferentes (ex: NCM 84248229 com CST 20 e CST 00) — a última
    # lida por UF sobrescrevia silenciosamente a anterior, o mesmo bug que
    # motivou a correção da chave em IcmsSaidaPorNcmCstOrigemUf (ver Decisão no vault).
    valores_por_grupo = {}
    for registro in IcmsSaidaPorNcmCstOrigemUf.objects.all():
        chave = (registro.ncm, registro.cst, registro.origem_mercadoria_cadastro)
        valores_por_grupo.setdefault(chave, {})[registro.uf] = registro.aliquota

    # 14/09/2026 — ordenação passa de (ncm, cst, origem) pra
    # (ncm, origem, cst): a tela (Mockup 1 aprovado) agrupa visualmente
    # NCM → Origem → CST, com célula mesclada (rowspan) em NCM e em
    # Origem — os grupos da mesma Origem precisam ficar fisicamente
    # juntos na lista, senão o rowspan cobre linhas erradas.
    # key= evita comparar None com string: origem pode ser None (produto
    # sem impostos_entrada sincronizado) convivendo com outro grupo do
    # mesmo NCM+CST com origem preenchida — sorted() puro quebra nesse
    # caso (TypeError, comparação None vs str), então trata None como ''
    # só pra fins de ordenação, sem mudar o valor real armazenado.
    grupos_ordenados = sorted(
        valores_por_grupo.keys(),
        key=lambda chave: (chave[0], chave[2] or '', chave[1]),
    )

    # Conta quantos grupos cada NCM tem, e quantos grupos cada par
    # (NCM, Origem) tem — é o tamanho do rowspan de cada célula mesclada.
    total_grupos_por_ncm = {}
    total_grupos_por_ncm_origem = {}
    for (ncm, cst, origem) in grupos_ordenados:
        total_grupos_por_ncm[ncm] = total_grupos_por_ncm.get(ncm, 0) + 1
        chave_ncm_origem = (ncm, origem)
        total_grupos_por_ncm_origem[chave_ncm_origem] = total_grupos_por_ncm_origem.get(chave_ncm_origem, 0) + 1

    linhas = []
    ncm_anterior = None
    ncm_origem_anterior = None
    for (ncm, cst, origem) in grupos_ordenados:
        valores_por_uf = valores_por_grupo[(ncm, cst, origem)]
        chave_ncm_origem = (ncm, origem)
        linhas.append({
            'ncm': ncm,
            'cst': cst,
            'origem_mercadoria_cadastro': origem,
            'mostrar_ncm': ncm != ncm_anterior,
            'rowspan_ncm': total_grupos_por_ncm[ncm],
            'mostrar_origem': chave_ncm_origem != ncm_origem_anterior,
            'rowspan_origem': total_grupos_por_ncm_origem[chave_ncm_origem],
            'valores': [
                {'uf': uf, 'aliquota': valores_por_uf.get(uf)}
                for uf in UFS_ORDENADAS
            ],
            'media_ponderada': calcular_media_ponderada(valores_por_uf),
        })
        ncm_anterior = ncm
        ncm_origem_anterior = chave_ncm_origem

    return linhas


# Função Objetivo: Lista as Origens da Mercadoria que existem de verdade
# pro NCM digitado — 1º nível do <select> dependente da calculadora
# (Etapa 6c), mesmo padrão de listar_csts_disponiveis_para_ncm em
# exibicao_pis_cofins_por_ncm_cst.py.
# Explicação em detalhe: Origem pode ser None (produto sem
# impostos_entrada sincronizado) — devolvida como None mesmo, nunca como
# string vazia; quem monta o <select> (view/template, na Etapa 6c) decide
# como representar esse caso, não é responsabilidade desta função, que só
# trabalha com valor de domínio real.
def listar_origens_disponiveis_para_ncm(ncm):
    # .order_by() (vazio) limpa a ordenação padrão do Meta do model
    # (['ncm', 'cst', 'origem_mercadoria_cadastro', 'uf']) antes do
    # .distinct() — sem isso o Django inclui 'uf' (e os outros campos da
    # ordenação) na consulta por trás dos panos mesmo não pedido no
    # values_list, e o DISTINCT deixa de funcionar de verdade (bug real
    # encontrado em 13/09/2026: devolvia 1 linha por UF, 27 repetições de
    # cada Origem, em vez de 1 só).
    origens = IcmsSaidaPorNcmCstOrigemUf.objects.filter(ncm=ncm).order_by().values_list(
        'origem_mercadoria_cadastro', flat=True,
    ).distinct()
    # key= mesma lógica já usada em montar_matriz_icms_por_ncm: None não
    # compara com string, trata como '' só pra fins de ordenação.
    return sorted(origens, key=lambda origem: origem or '')


# Função Objetivo: Lista os CSTs que existem de verdade pro NCM + Origem
# digitados — 2º nível do <select> dependente da calculadora (Etapa 6c).
# Explicação em detalhe: um mesmo NCM+Origem ainda pode ter mais de 1 CST
# (é exatamente essa combinação — NCM+CST+Origem — que forma 1 grupo real,
# ver Decisão no vault sobre a chave de consolidação) — por isso este
# nível também pode devolver mais de 1 opção, igual o de Origem acima.
def listar_csts_disponiveis_para_ncm_origem(ncm, origem):
    return list(
        IcmsSaidaPorNcmCstOrigemUf.objects.filter(ncm=ncm, origem_mercadoria_cadastro=origem)
        .order_by('cst').values_list('cst', flat=True).distinct()
    )


# Função Objetivo: Resolve 1 consulta NCM + Origem + CST + UF (ou Média
# Ponderada) pra calculadora da tela. Exige os 4 campos porque, sem
# Origem e CST, não tem como saber qual dos possíveis grupos daquele NCM
# o usuário quer consultar — a versão antiga, que filtrava só por NCM,
# sofria de sobrescrita silenciosa quando o NCM tinha mais de 1 grupo
# (ver Descoberta no vault: "Tela de ICMS por NCM Redesenhada..."),
# removida nesta etapa (Etapa 6c), agora que a calculadora tem os 3
# selects dependentes (NCM → Origem → CST → UF) capazes de fornecer os
# 4 valores.
def consultar_icms_por_ncm(ncm, origem, cst, uf):
    valores_por_uf = {
        registro.uf: registro.aliquota
        for registro in IcmsSaidaPorNcmCstOrigemUf.objects.filter(ncm=ncm, origem_mercadoria_cadastro=origem, cst=cst)
    }

    grupo_encontrado = bool(valores_por_uf)
    e_media_ponderada = (uf == 'MEDIA_PONDERADA')

    if not grupo_encontrado:
        return None, False, e_media_ponderada

    if e_media_ponderada:
        return calcular_media_ponderada(valores_por_uf), True, True

    return valores_por_uf.get(uf), True, False