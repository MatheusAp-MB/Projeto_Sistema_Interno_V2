# arquivos_referencia/funcoes_auxiliares/importacao_busca_legal.py

# Função Objetivo: Atualiza os IMPOSTOS DE SAÍDA de UMA empresa com a planilha Busca Legal que está no Drive, a partir da tela "Arquivos de
# referência". Roda, EM ORDEM, os mesmos 4 passos do terminal (Sincronizar_Impostos_de_Saida) — usando as MESMAS classes do projeto, sem
# copiar a lógica de ler a planilha nem a de gravar — e devolve, já contado, o que mudou de verdade para a janela de resultado.
#
# * [DECISÃO, 16/10/2026] → Modo EXPANDIR. Ideia do Matheus: "se a linha já existe, é atualizada; se não existe, é criada; NÃO apaga nada
#   por não estar no arquivo". É o jeito como as classes do projeto já funcionam (elas só criam e atualizam, nunca apagam), então no Expandir
#   nada é removido das tabelas de imposto. Motivo: a planilha cobre hoje 100% do estoque, mas conforme chegarem produtos novos ela vai
#   crescer — e uma planilha menor nunca pode apagar o que o sistema já sabe.
# * [DECISÃO, 16/10/2026] → Modo SUBSTITUIR (opção B do Matheus): depois da confirmação o sistema da empresa fica LITERALMENTE igual à planilha —
#   "se não está na planilha, não está no sistema". Além do que o Expandir faz, o Substituir APAGA:
#     a) o CST de saída (e, por consequência, ICMS/PIS/COFINS de saída) dos produtos cujo EAN não está na planilha, ou está nela sem CST;
#     b) os grupos de ICMS (alíquotas por UF + média) e de PIS/COFINS que a planilha não tem;
#     c) os grupos que a planilha tem mas que o sistema REJEITOU (EANs do grupo não concordam): a planilha não dá um valor válido para eles,
#        então o valor antigo também sai (no Expandir ele ficava). Quem lê a prévia vê esses grupos numa lista própria, antes de confirmar;
#     d) as alíquotas de UF que ficaram vazias na planilha, dentro de um grupo que continua existindo.
#   O PRODUTO em si nunca é apagado: só os 5 campos fiscais de saída. Fica de fora do "igual à planilha" a regra do tributo já pago
#   (PIS/COFINS 0% por CST 02/04/06 da nota de entrada, decisão de 01/10/2026): ela não vem da planilha, e a janela diz quantos produtos a têm.
#   Tudo continua na MESMA transação e com as MESMAS classes do projeto; as remoções são feitas aqui, em volta delas.
# * [IMPORTANTE] → PRÉVIA: o mesmo código roda numa transação que é DESFEITA no fim (quem chama pede `simular`), então a prévia mostra exatamente
#   o que a gravação de verdade fará, sem uma segunda conta que pudesse divergir da primeira.
# * [EXPLICAÇÃO] → Os 4 passos, na ordem que o terminal usa (cada um precisa do anterior):
#     1) CST dos produtos (preencher_CST_produtos): grava Produto.cst_saida pelo EAN da planilha;
#     2) ICMS por grupo (importar_icms_saida_por_ncm_cst_origem): agrupa os produtos por NCM + CST + Origem; o grupo só entra se TODOS os EANs
#        dele concordam nas 27 UFs (senão é REJEITADO inteiro e o valor antigo do grupo, se existir, fica como estava);
#     3) PIS/COFINS por grupo (importar_pis_cofins_saida_por_ncm_cst): igual, agrupando por NCM + CST;
#     4) Impostos nos produtos (preencher_impostos_saida): preenche os 5 campos fiscais de TODOS os produtos do catálogo a partir das tabelas
#        dos passos 2 e 3 (e zera o campo que ficou sem dado validado).
# * [IMPORTANTE] → Os 4 passos rodam dentro de UMA transação (quem chama abre): se qualquer um falhar, NADA é gravado. No terminal cada
#   comando grava por conta própria; aqui é tudo ou nada. A planilha vem do Drive (bytes na memória): nada vai para o disco.
# * [EXPLICAÇÃO] → Como se conta "novos / mudaram / iguais": tira-se uma fotografia dos valores que já estavam gravados ANTES de cada passo
#   gravar e compara-se com o que o arquivo manda. As contas "Atualizados" das classes do projeto não servem para isso, porque elas regravam
#   tudo o que casa com o arquivo, tenha mudado ou não. Para os produtos, a fotografia é da tabela inteira, antes e depois — assim também
#   se enxerga o produto que NÃO está na planilha mas mudou, porque o grupo (NCM+CST+Origem) dele mudou de valor.
# * [EXPLICAÇÃO] → Cada tabela de imposto é por GRUPO, não por produto: um EAN novo entrando num grupo que já existe pode trocar o valor do
#   grupo inteiro (e, com isso, o imposto de produtos que nem estão na planilha). Por isso a janela lista os grupos que mudaram de valor.
# * [IMPORTANTE] → Este passo ainda NÃO recalcula as grades de preço: o resultado avisa quando algum imposto de produto mudou (o recálculo
#   automático é um ciclo à parte).

import io
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import timezone

MODO_EXPANDIR = 'expandir'
MODO_SUBSTITUIR = 'substituir'
MODOS_VALIDOS = (MODO_EXPANDIR, MODO_SUBSTITUIR)

MAXIMO_DE_ITENS_POR_LISTA = 8
MAXIMO_DE_LINHAS_NA_LISTA_DO_SUBSTITUIR = 200   # produtos/grupos por lista na janela da prévia (o total exato vem sempre à parte)
TAMANHO_DO_LOTE_DE_REMOCAO = 500                # chaves por DELETE/UPDATE (lotes pequenos são mais seguros no MySQL)
TAMANHO_MAXIMO_DO_TITULO_NA_LISTA = 70
PERCENTUAL_QUE_PEDE_ATENCAO_EXTRA = 20          # a prévia destaca em vermelho quando o Substituir tira o CST de tantos % dos produtos

# Campos fiscais do Produto que os passos 1 e 4 gravam (a ordem é a da fotografia).
CAMPOS_FISCAIS = ('cst_saida', 'icms_saida_sp', 'icms_saida_media', 'pis_percentual', 'cofins_percentual')
_POSICAO_DO_CST, _POSICAO_DO_ICMS_SP, _POSICAO_DO_ICMS_MEDIA, _POSICAO_DO_PIS, _POSICAO_DO_COFINS = 1, 2, 3, 4, 5

TOM_NORMAL = ''
TOM_AVISO = 'aviso'


class ImportacaoDeImpostosRecusada(Exception):
    """A planilha não serve para esta empresa (ex.: nenhum EAN dela existe no sistema): nada é gravado."""

    def __init__(self, motivos):
        super().__init__('; '.join(motivos[:3]))
        self.motivos = motivos


# Contagem de 1 tabela de grupos (ICMS ou PIS/COFINS): quantos grupos o arquivo trouxe em cada situação.
@dataclass
class ContagemDeGrupos:
    novos: int = 0
    mudaram: int = 0
    iguais: int = 0
    rejeitados: int = 0
    ignoradas: int = 0                                  # linhas sem NCM ou sem CST no produto (não formam grupo)
    mudaram_detalhe: list = field(default_factory=list)  # textos prontos: o que mudou em cada grupo que já existia
    rejeitados_detalhe: list = field(default_factory=list)


def _percentual(valor):
    if valor is None:
        return 'vazio'
    return f'{Decimal(valor):.2f}'.replace('.', ',') + '%'


def _origem_em_texto(origem):
    return origem if origem else 'sem origem'


# Função Objetivo: Fotografia dos 5 campos fiscais de TODOS os produtos do banco da empresa: {pk: (ean, cst, icms_sp, icms_media, pis, cofins)}.
def _fotografar_produtos(alias):
    from produtos.models import Produto

    return {linha[0]: linha[1:] for linha in Produto.objects.using(alias).values_list('pk', 'ean', *CAMPOS_FISCAIS)}


# ---------- Passo 2: ICMS ----------

def _comparar_icms(agrupador, persistidor, antes_uf, antes_media):
    """Compara o que o arquivo manda (grupos aceitos) com o que já estava gravado ANTES de o persistidor mexer. Devolve ContagemDeGrupos."""
    contagem = ContagemDeGrupos(ignoradas=agrupador.sem_ncm_na_planilha_ou_sem_cst_no_produto)
    grupos_antes = {chave[:3] for chave in antes_uf} | set(antes_media)

    for grupo, valores_por_uf in agrupador.aceitos.items():
        ufs_novas = ufs_diferentes = 0
        for uf, aliquota in valores_por_uf.items():
            chave = (*grupo, uf)
            if chave not in antes_uf:
                ufs_novas += 1
            elif antes_uf[chave] != aliquota:
                ufs_diferentes += 1
        media_nova = persistidor.existentes_media[grupo].media_ponderada if grupo in persistidor.existentes_media else None
        media_antiga = antes_media.get(grupo)
        media_mudou = grupo in antes_media and media_nova is not None and media_antiga != media_nova

        if grupo not in grupos_antes:
            if ufs_novas:
                contagem.novos += 1
            else:
                contagem.iguais += 1   # grupo aceito sem nenhuma alíquota preenchida: não há o que gravar
        elif ufs_novas or ufs_diferentes or media_mudou:
            contagem.mudaram += 1
            ncm, cst, origem = grupo
            partes = []
            if ufs_diferentes or ufs_novas:
                total = ufs_diferentes + ufs_novas
                partes.append(f'{total} {"UF" if total == 1 else "UFs"} com valor diferente')
            if media_mudou:
                partes.append(f'média {_percentual(media_antiga)} → {_percentual(media_nova)}')
            contagem.mudaram_detalhe.append(
                f'ICMS · NCM {ncm} · CST {cst} · origem {_origem_em_texto(origem)} — ' + '; '.join(partes)
            )
        else:
            contagem.iguais += 1

    for rejeitado in sorted(agrupador.rejeitados, key=lambda r: -r.total_eans_no_grupo):
        grupo = (rejeitado.ncm, rejeitado.cst, rejeitado.origem_mercadoria_cadastro)
        n_ufs = len(rejeitado.divergencias_por_uf)
        sobra = 'o valor que já estava no sistema foi mantido' if grupo in grupos_antes else 'não tinha valor no sistema, continua sem'
        contagem.rejeitados += 1
        contagem.rejeitados_detalhe.append(
            f'ICMS · NCM {rejeitado.ncm} · CST {rejeitado.cst} · origem {_origem_em_texto(rejeitado.origem_mercadoria_cadastro)} — '
            f'{rejeitado.total_eans_no_grupo} EANs não concordam em {n_ufs} {"UF" if n_ufs == 1 else "UFs"}; {sobra}'
        )
    return contagem


# ---------- Passo 3: PIS/COFINS ----------

def _comparar_pis_cofins(agrupador, antes):
    contagem = ContagemDeGrupos(ignoradas=agrupador.sem_ncm_na_planilha_ou_sem_cst_no_produto)
    for grupo, valores in agrupador.aceitos.items():
        novo = (valores['pis'], valores['cofins'])
        if grupo not in antes:
            contagem.novos += 1
        elif antes[grupo] != novo:
            contagem.mudaram += 1
            ncm, cst = grupo
            partes = []
            if antes[grupo][0] != novo[0]:
                partes.append(f'PIS {_percentual(antes[grupo][0])} → {_percentual(novo[0])}')
            if antes[grupo][1] != novo[1]:
                partes.append(f'COFINS {_percentual(antes[grupo][1])} → {_percentual(novo[1])}')
            contagem.mudaram_detalhe.append(f'PIS/COFINS · NCM {ncm} · CST {cst} — ' + '; '.join(partes))
        else:
            contagem.iguais += 1

    for rejeitado in sorted(agrupador.rejeitados, key=lambda r: -r.total_eans_no_grupo):
        grupo = (rejeitado.ncm, rejeitado.cst)
        campos = ' e '.join(sorted(rejeitado.divergencias_por_campo))
        sobra = 'o valor que já estava no sistema foi mantido' if grupo in antes else 'não tinha valor no sistema, continua sem'
        contagem.rejeitados += 1
        contagem.rejeitados_detalhe.append(
            f'PIS/COFINS · NCM {rejeitado.ncm} · CST {rejeitado.cst} — {rejeitado.total_eans_no_grupo} EANs não concordam em {campos}; {sobra}'
        )
    return contagem


# ---------- Passo 4: produtos ----------

def _comparar_produtos(antes, depois, eans_da_planilha):
    """Compara a fotografia dos produtos antes e depois dos 4 passos. Além dos números, devolve QUEM perdeu o CST (`pks_perderam_cst`) e QUEM
    continuou com CST mas perdeu algum dos 4 impostos (`pks_perderam_imposto`) — a prévia do Substituir lista esses produtos."""
    mudaram = mudou_cst = mudou_icms = mudou_pis_cofins = perderam_valor = fora_da_planilha = 0
    pks_perderam_cst = []
    pks_perderam_imposto = []
    for pk, valores_depois in depois.items():
        valores_antes = antes.get(pk)
        if valores_antes is None:
            continue   # produto criado no meio do caminho: não acontece aqui (os passos não criam produto), mas nunca quebra a conta
        if valores_antes == valores_depois:
            continue
        mudaram += 1
        if valores_antes[_POSICAO_DO_CST] != valores_depois[_POSICAO_DO_CST]:
            mudou_cst += 1
        if (valores_antes[_POSICAO_DO_ICMS_SP], valores_antes[_POSICAO_DO_ICMS_MEDIA]) != (
            valores_depois[_POSICAO_DO_ICMS_SP], valores_depois[_POSICAO_DO_ICMS_MEDIA]
        ):
            mudou_icms += 1
        if (valores_antes[_POSICAO_DO_PIS], valores_antes[_POSICAO_DO_COFINS]) != (
            valores_depois[_POSICAO_DO_PIS], valores_depois[_POSICAO_DO_COFINS]
        ):
            mudou_pis_cofins += 1
        if any(antes_ is not None and depois_ is None for antes_, depois_ in zip(valores_antes[1:], valores_depois[1:])):
            perderam_valor += 1
        if valores_antes[_POSICAO_DO_CST] is not None and valores_depois[_POSICAO_DO_CST] is None:
            pks_perderam_cst.append(pk)
        elif any(antes_ is not None and depois_ is None for antes_, depois_ in zip(valores_antes[2:], valores_depois[2:])):
            pks_perderam_imposto.append(pk)
        if valores_depois[0] not in eans_da_planilha:   # posição 0 da fotografia é o EAN
            fora_da_planilha += 1
    return {
        'mudaram': mudaram, 'mudou_cst': mudou_cst, 'mudou_icms': mudou_icms, 'mudou_pis_cofins': mudou_pis_cofins,
        'perderam_valor': perderam_valor, 'fora_da_planilha': fora_da_planilha,
        'pks_perderam_cst': pks_perderam_cst, 'pks_perderam_imposto': pks_perderam_imposto,
    }


def _lista_curta(textos):
    return list(textos[:MAXIMO_DE_ITENS_POR_LISTA]), max(0, len(textos) - MAXIMO_DE_ITENS_POR_LISTA)


# ---------- Modo Substituir: o que é apagado e como é contado ----------

def _em_lotes(itens):
    itens = list(itens)
    for inicio in range(0, len(itens), TAMANHO_DO_LOTE_DE_REMOCAO):
        yield itens[inicio:inicio + TAMANHO_DO_LOTE_DE_REMOCAO]


# Função Objetivo: Apaga do banco da empresa as linhas de UMA tabela de imposto pelas chaves (pk) dadas, em lotes. Só roda dentro da transação.
def _apagar_linhas(modelo, alias, pks):
    for lote in _em_lotes(sorted(pks)):
        modelo.objects.using(alias).filter(pk__in=lote).delete()


# Função Objetivo: Tira o CST de saída dos produtos (o produto em si NÃO é apagado). Só roda dentro da transação.
def _apagar_cst_dos_produtos(alias, pks):
    from produtos.models import Produto

    for lote in _em_lotes(sorted(pks)):
        Produto.objects.using(alias).filter(pk__in=lote).update(cst_saida=None)


def _ordem_do_grupo(grupo):
    return tuple('' if parte is None else str(parte) for parte in grupo)


def _texto_do_grupo_icms(grupo):
    ncm, cst, origem = grupo
    return f'NCM {ncm} · CST {cst} · origem {_origem_em_texto(origem)}'


def _texto_da_uf_esvaziada(chave):
    ncm, cst, origem, uf = chave
    return f'NCM {ncm} · CST {cst} · origem {_origem_em_texto(origem)} · UF {uf}'


def _texto_do_grupo_pis(grupo):
    ncm, cst = grupo
    return f'NCM {ncm} · CST {cst}'


def _remocao_vazia():
    return {'sem_na_planilha': [], 'rejeitados': [], 'sem_valor': [], 'ufs_esvaziadas': [], 'grupos_removidos': 0}


# Função Objetivo: Substituir, passo 2 — apaga do ICMS (alíquotas por UF e média) o que a planilha NÃO manda de volta. Roda DEPOIS de o persistidor
# do projeto gravar o que a planilha manda. `pk_uf` / `pk_media` = as linhas que JÁ existiam antes do passo (chave do grupo -> pk).
# Devolve o que foi apagado, separado pelo MOTIVO (a prévia mostra cada motivo à parte):
#   sem_na_planilha = grupo que a planilha nem menciona · rejeitados = a planilha tem o grupo, mas os EANs dele não concordam (nenhum valor válido)
#   · sem_valor = a planilha tem o grupo, aceito, mas sem nenhuma alíquota preenchida · ufs_esvaziadas = (NCM, CST, origem, UF) em branco dentro de grupo que continua.
def _remover_icms_que_a_planilha_nao_tem(alias, agrupador, persistidor, pk_uf, pk_media):
    from impostos.models import IcmsSaidaMediaPorNcmCstOrigem, IcmsSaidaPorNcmCstOrigemUf

    grupos_na_planilha = set(agrupador.linhas_por_grupo)
    grupos_rejeitados = {(r.ncm, r.cst, r.origem_mercadoria_cadastro) for r in agrupador.rejeitados}
    uf_mantidas = {(*grupo, uf) for grupo, valores in agrupador.aceitos.items() for uf in valores}
    media_mantida = {(m.ncm, m.cst, m.origem_mercadoria_cadastro) for m in persistidor.media_para_criar + persistidor.media_para_atualizar}

    grupos_antes = {chave[:3] for chave in pk_uf} | set(pk_media)
    grupos_depois = {chave[:3] for chave in uf_mantidas} | media_mantida
    grupos_que_somem = grupos_antes - grupos_depois

    _apagar_linhas(IcmsSaidaPorNcmCstOrigemUf, alias, [pk for chave, pk in pk_uf.items() if chave not in uf_mantidas])
    _apagar_linhas(IcmsSaidaMediaPorNcmCstOrigem, alias, [pk for chave, pk in pk_media.items() if chave not in media_mantida])

    return {
        'sem_na_planilha': sorted((g for g in grupos_que_somem if g not in grupos_na_planilha), key=_ordem_do_grupo),
        'rejeitados': sorted((g for g in grupos_que_somem if g in grupos_rejeitados), key=_ordem_do_grupo),
        'sem_valor': sorted((g for g in grupos_que_somem if g in grupos_na_planilha and g not in grupos_rejeitados), key=_ordem_do_grupo),
        'ufs_esvaziadas': sorted((chave for chave in pk_uf if chave not in uf_mantidas and chave[:3] not in grupos_que_somem), key=_ordem_do_grupo),
        'grupos_removidos': len(grupos_que_somem),
    }


# Função Objetivo: Substituir, passo 3 — igual ao ICMS, para PIS/COFINS (grupo = NCM + CST). `pk_pis` = grupos que já existiam antes do passo.
def _remover_pis_cofins_que_a_planilha_nao_tem(alias, agrupador, pk_pis):
    from impostos.models import PisCofinsSaidaPorNcmCst

    grupos_na_planilha = set(agrupador.linhas_por_grupo)
    grupos_rejeitados = {(r.ncm, r.cst) for r in agrupador.rejeitados}
    grupos_que_somem = {chave for chave in pk_pis if chave not in agrupador.aceitos}

    _apagar_linhas(PisCofinsSaidaPorNcmCst, alias, [pk_pis[chave] for chave in grupos_que_somem])

    return {
        'sem_na_planilha': sorted((g for g in grupos_que_somem if g not in grupos_na_planilha), key=_ordem_do_grupo),
        'rejeitados': sorted((g for g in grupos_que_somem if g in grupos_rejeitados), key=_ordem_do_grupo),
        'sem_valor': [],   # grupo aceito é SEMPRE gravado (mesmo sem PIS/COFINS preenchidos): nunca some por isso
        'ufs_esvaziadas': [],
        'grupos_removidos': len(grupos_que_somem),
    }


# Função Objetivo: Quem perdeu o CST, separado pelo motivo: (EAN fora da planilha, EAN na planilha mas sem CST).
def _separar_quem_perdeu_o_cst(pks, produtos_antes, eans_da_planilha):
    fora = [pk for pk in pks if produtos_antes[pk][0] not in eans_da_planilha]
    sem_cst = [pk for pk in pks if produtos_antes[pk][0] in eans_da_planilha]
    return fora, sem_cst


# Função Objetivo: Texto de cada produto da lista da prévia: EAN, SKU, título e o CST que ele TINHA (o que vai ser apagado). Lista curta: o total vem à parte.
def _lista_de_produtos(alias, produtos_antes, pks):
    from produtos.models import Produto

    primeiros = sorted(pks, key=lambda pk: produtos_antes[pk][0] or '')[:MAXIMO_DE_LINHAS_NA_LISTA_DO_SUBSTITUIR]
    detalhes = {pk: (sku, titulo) for pk, sku, titulo in Produto.objects.using(alias).filter(pk__in=primeiros).values_list('pk', 'sku', 'titulo')}
    itens = []
    for pk in primeiros:
        sku, titulo = detalhes.get(pk, (None, ''))
        titulo = (titulo or '')[:TAMANHO_MAXIMO_DO_TITULO_NA_LISTA]
        cst = produtos_antes[pk][_POSICAO_DO_CST]
        itens.append(f'EAN {produtos_antes[pk][0]} · SKU {sku or "—"} · {titulo}' + (f' · tinha CST {cst}' if cst is not None else ''))
    return itens, max(0, len(pks) - len(primeiros))


def _lista_de_grupos(grupos, texto_do_grupo):
    textos = [texto_do_grupo(g) for g in grupos]
    return textos[:MAXIMO_DE_LINHAS_NA_LISTA_DO_SUBSTITUIR], max(0, len(textos) - MAXIMO_DE_LINHAS_NA_LISTA_DO_SUBSTITUIR)


# `plural` é o texto de sempre; `singular` é o que aparece quando o total é exatamente 1.
def _bloco(chave, plural, singular, total, itens=None, mais=0):
    return {'chave': chave, 'texto': singular if total == 1 else plural, 'total': total, 'itens': itens or [], 'mais': mais}


# Função Objetivo: Monta o que a janela mostra do Substituir: cada coisa que será APAGADA (ou que foi apagada), com o total exato, o motivo e a lista.
# Os textos dos blocos valem nos dois tempos (a prévia diz "vai ser apagado", o resultado diz "foi apagado": quem escreve o tempo é o título da janela).
# Só entram blocos com total maior que zero. `nada_a_apagar` = o sistema já só tinha o que a planilha tem.
def _montar_substituicao(alias, produtos_antes, produtos, fora_pks, sem_cst_pks, remocao_icms, remocao_pis, tributo_ja_pago_zero):
    blocos = []

    def de_produtos(chave, plural, singular, pks):
        if pks:
            itens, mais = _lista_de_produtos(alias, produtos_antes, pks)
            blocos.append(_bloco(chave, plural, singular, len(pks), itens, mais))

    de_produtos(
        'produtos_fora_da_planilha',
        'produtos ficam sem o CST e sem os impostos de saída: o EAN deles NÃO está na planilha',
        'produto fica sem o CST e sem os impostos de saída: o EAN dele NÃO está na planilha', fora_pks,
    )
    de_produtos(
        'produtos_sem_cst',
        'produtos ficam sem o CST e sem os impostos de saída: o EAN deles está na planilha, mas SEM CST',
        'produto fica sem o CST e sem os impostos de saída: o EAN dele está na planilha, mas SEM CST', sem_cst_pks,
    )
    de_produtos(
        'produtos_sem_imposto',
        'produtos mantêm o CST, mas ficam sem ICMS/PIS/COFINS de saída: o grupo deles (NCM + CST + origem) é apagado ou não tem valor válido na planilha',
        'produto mantém o CST, mas fica sem ICMS/PIS/COFINS de saída: o grupo dele (NCM + CST + origem) é apagado ou não tem valor válido na planilha',
        produtos['pks_perderam_imposto'],
    )

    def de_grupos(chave, plural, singular, grupos, texto_do_grupo):
        if grupos:
            itens, mais = _lista_de_grupos(grupos, texto_do_grupo)
            blocos.append(_bloco(chave, plural, singular, len(grupos), itens, mais))

    de_grupos('icms_fora_da_planilha', 'grupos de ICMS apagados: a planilha não tem esses grupos',
              'grupo de ICMS apagado: a planilha não tem esse grupo', remocao_icms['sem_na_planilha'], _texto_do_grupo_icms)
    de_grupos('icms_rejeitados', 'grupos de ICMS apagados: estão REJEITADOS na planilha (os EANs do grupo não concordam), então ela não dá um valor válido para eles',
              'grupo de ICMS apagado: está REJEITADO na planilha (os EANs do grupo não concordam), então ela não dá um valor válido para ele',
              remocao_icms['rejeitados'], _texto_do_grupo_icms)
    de_grupos('icms_sem_valor', 'grupos de ICMS apagados: estão na planilha, mas sem nenhuma alíquota preenchida',
              'grupo de ICMS apagado: está na planilha, mas sem nenhuma alíquota preenchida', remocao_icms['sem_valor'], _texto_do_grupo_icms)
    de_grupos(
        'icms_ufs_vazias', 'alíquotas de ICMS por UF apagadas: a planilha deixou essas UFs em branco, em grupos que continuam existindo',
        'alíquota de ICMS por UF apagada: a planilha deixou essa UF em branco, em um grupo que continua existindo',
        remocao_icms['ufs_esvaziadas'], _texto_da_uf_esvaziada,
    )
    de_grupos('pis_fora_da_planilha', 'grupos de PIS/COFINS apagados: a planilha não tem esses grupos',
              'grupo de PIS/COFINS apagado: a planilha não tem esse grupo', remocao_pis['sem_na_planilha'], _texto_do_grupo_pis)
    de_grupos('pis_rejeitados', 'grupos de PIS/COFINS apagados: estão REJEITADOS na planilha (os EANs do grupo não concordam), então ela não dá um valor válido para eles',
              'grupo de PIS/COFINS apagado: está REJEITADO na planilha (os EANs do grupo não concordam), então ela não dá um valor válido para ele',
              remocao_pis['rejeitados'], _texto_do_grupo_pis)

    produtos_com_cst = sum(1 for valores in produtos_antes.values() if valores[_POSICAO_DO_CST] is not None)
    perdem_o_cst = len(fora_pks) + len(sem_cst_pks)
    percentual = int((100 * perdem_o_cst) / produtos_com_cst + 0.5) if produtos_com_cst else 0  # arredonda 62,5 para 63 (round() do Python arredondaria para 62)
    return {
        'blocos': blocos, 'nada_a_apagar': not blocos,
        'produtos_com_cst_antes': produtos_com_cst, 'produtos_perdem_o_cst': perdem_o_cst, 'percentual': percentual,
        'percentual_alto': percentual >= PERCENTUAL_QUE_PEDE_ATENCAO_EXTRA,
        'produtos_com_regra_do_tributo_ja_pago': tributo_ja_pago_zero,
        'grupos_apagados': remocao_icms['grupos_removidos'] + remocao_pis['grupos_removidos'],
    }


# `plural` é o texto de sempre (e a chave estável de cada número); `singular` é o que aparece quando o valor é exatamente 1 ("1 grupo", não "1 grupos").
def _numero(valor, plural, singular, tom=TOM_NORMAL):
    return {'valor': valor, 'texto': singular if valor == 1 else plural, 'plural': plural, 'tom': tom if valor else TOM_NORMAL}


def _etapa_de_grupos(numero, titulo, grupos_no_arquivo, contagem, ignoradas_plural, ignoradas_singular, removidos=0):
    numeros = [
        _numero(grupos_no_arquivo, 'grupos no arquivo', 'grupo no arquivo'),
        _numero(contagem.novos, 'novos', 'novo'),
        _numero(contagem.mudaram, 'já existiam e mudaram de valor', 'já existia e mudou de valor', TOM_AVISO),
        _numero(contagem.iguais, 'já estavam iguais', 'já estava igual'),
        _numero(contagem.rejeitados, 'rejeitados (EANs do grupo não concordam)', 'rejeitado (EANs do grupo não concordam)', TOM_AVISO),
        _numero(contagem.ignoradas, ignoradas_plural, ignoradas_singular, TOM_AVISO),
        _numero(removidos, 'grupos APAGADOS do sistema (a planilha não os tem, ou não tem valor válido para eles)',
                'grupo APAGADO do sistema (a planilha não o tem, ou não tem valor válido para ele)', TOM_AVISO),
    ]
    return {'numero': numero, 'titulo': titulo, 'numeros': [n for n in numeros if n['valor'] or n['plural'] == 'grupos no arquivo']}


# Função Objetivo: Roda os 4 passos para a empresa ATIVA (quem chama já definiu a empresa e abriu a transação). `conteudo` = bytes do .xlsx do
# Drive. `modo` = Expandir (só cria e atualiza) ou Substituir (também APAGA o que a planilha não tem; ver o topo do arquivo). Devolve os números para
# a tela e para o histórico:
#   {'criados', 'mudaram', 'iguais', 'removidas' (= GRUPOS apagados, ICMS + PIS/COFINS; sempre 0 no Expandir) = GRUPOS (ICMS + PIS/COFINS),
#    'produtos_mudaram', 'produtos_perderam_cst', 'rejeitados', 'nada_mudou', 'etapas': [...], 'atencoes': [...], 'modo',
#    'substituicao': (só no Substituir) o que foi/será apagado, com totais, motivos e listas}
# Levanta ImportacaoDeImpostosRecusada quando a planilha não serve para esta empresa (nada foi gravado ainda ou a transação desfaz).
def executar_busca_legal(conteudo, alias, modo=MODO_EXPANDIR):
    if modo not in MODOS_VALIDOS:
        raise ValueError(f'Modo de importação desconhecido: {modo!r}')
    substituir = modo == MODO_SUBSTITUIR

    # Importados aqui (e não no topo) para o módulo carregar leve e sem ciclo; são as classes do próprio projeto, usadas como estão.
    from impostos.funcoes_auxiliares.saida.importacao_icms_ncm import (
        PersistidorIcmsNcm, PersistidorIcmsSaidaPorNcmCstOrigemRejeitado, agrupar_icms_por_ncm,
    )
    from impostos.funcoes_auxiliares.saida.importacao_pis_cofins_ncm_cst import (
        PersistidorPisCofinsSaidaPorNcmCst, PersistidorPisCofinsSaidaPorNcmCstRejeitado, agrupar_pis_cofins_por_ncm_cst,
    )
    from impostos.funcoes_auxiliares.saida.preenchimento_cst_produtos import PreenchedorCstProdutos
    from impostos.funcoes_auxiliares.saida.preenchimento_impostos_saida import (
        COLUNA_CST, COLUNA_EAN, ImportadorImpostosSaida, _normalizar_codigo_celula, ler_linhas_planilha_impostos_saida,
    )

    def planilha():   # as classes do projeto leem o arquivo do começo a cada vez: cada passo ganha a sua cópia na memória
        return io.BytesIO(conteudo)

    # EAN -> CST da PRIMEIRA linha em que o EAN aparece (None = a linha não traz CST). É a mesma regra do passo 1 (EAN repetido: vale o primeiro).
    cst_por_ean = {}
    for linha in ler_linhas_planilha_impostos_saida(planilha()):
        ean = _normalizar_codigo_celula(linha.get(COLUNA_EAN))
        if ean and ean not in cst_por_ean:
            cst_por_ean[ean] = _normalizar_codigo_celula(linha.get(COLUNA_CST))
    eans_da_planilha = set(cst_por_ean)
    produtos_antes = _fotografar_produtos(alias)

    # Passo 1 — CST dos produtos.
    cst = PreenchedorCstProdutos(planilha())
    cst.carregar_produtos_existentes()
    cst.processar_planilha()
    eans_casados = len(eans_da_planilha) - cst.sem_produto_correspondente
    if eans_da_planilha and eans_casados <= 0:
        raise ImportacaoDeImpostosRecusada([
            'Nenhum EAN desta planilha existe no sistema desta empresa. Confira se a planilha é da empresa certa. Nada foi gravado.',
        ])
    if substituir:
        # Só depois da recusa acima (planilha da empresa errada nunca chega a apagar nada): quem tem CST no sistema e não tem CST na planilha
        # (EAN ausente, ou presente sem CST) perde o CST. Os outros EANs recebem o CST da planilha logo abaixo, como no Expandir.
        _apagar_cst_dos_produtos(alias, [
            pk for pk, valores in produtos_antes.items() if valores[_POSICAO_DO_CST] is not None and cst_por_ean.get(valores[0]) is None
        ])
    cst.salvar()

    constatado_em = timezone.now()   # o mesmo instante em todas as rejeições desta rodada (como no terminal)

    # Passo 2 — ICMS por grupo (NCM + CST + Origem).
    agrupador_icms = agrupar_icms_por_ncm(planilha())
    persistidor_icms = PersistidorIcmsNcm()
    persistidor_icms.carregar_existentes()
    antes_uf = {chave: registro.aliquota for chave, registro in persistidor_icms.existentes.items()}
    antes_media = {chave: registro.media_ponderada for chave, registro in persistidor_icms.existentes_media.items()}
    pk_uf = {chave: registro.pk for chave, registro in persistidor_icms.existentes.items()}          # as linhas que JÁ existiam (as novas não entram)
    pk_media = {chave: registro.pk for chave, registro in persistidor_icms.existentes_media.items()}
    persistidor_icms.processar(agrupador_icms.aceitos)
    contagem_icms = _comparar_icms(agrupador_icms, persistidor_icms, antes_uf, antes_media)
    persistidor_icms.salvar()
    remocao_icms = _remover_icms_que_a_planilha_nao_tem(alias, agrupador_icms, persistidor_icms, pk_uf, pk_media) if substituir else _remocao_vazia()
    PersistidorIcmsSaidaPorNcmCstOrigemRejeitado(constatado_em).salvar(agrupador_icms.rejeitados)

    # Passo 3 — PIS/COFINS por grupo (NCM + CST).
    agrupador_pis = agrupar_pis_cofins_por_ncm_cst(planilha())
    persistidor_pis = PersistidorPisCofinsSaidaPorNcmCst()
    persistidor_pis.carregar_existentes()
    antes_pis = {chave: (registro.pis, registro.cofins) for chave, registro in persistidor_pis.existentes.items()}
    pk_pis = {chave: registro.pk for chave, registro in persistidor_pis.existentes.items()}
    persistidor_pis.processar(agrupador_pis.aceitos)
    contagem_pis = _comparar_pis_cofins(agrupador_pis, antes_pis)
    persistidor_pis.salvar()
    remocao_pis = _remover_pis_cofins_que_a_planilha_nao_tem(alias, agrupador_pis, pk_pis) if substituir else _remocao_vazia()
    PersistidorPisCofinsSaidaPorNcmCstRejeitado(constatado_em).salvar(agrupador_pis.rejeitados)

    # Passo 4 — os 5 campos fiscais de todos os produtos (lê as tabelas que os passos 2 e 3 acabaram de gravar, já sem o que foi apagado).
    importador = ImportadorImpostosSaida(planilha())
    importador.rodar_preenchimento_completo()
    produtos = _comparar_produtos(produtos_antes, _fotografar_produtos(alias), eans_da_planilha)
    perderam_cst_fora, perderam_cst_sem_cst = _separar_quem_perdeu_o_cst(produtos['pks_perderam_cst'], produtos_antes, eans_da_planilha)

    # ---- Monta o resultado para a tela ----
    grupos_icms = len(agrupador_icms.linhas_por_grupo)
    grupos_pis = len(agrupador_pis.linhas_por_grupo)
    sem_ncm_ou_cst = ('linhas sem NCM ou sem CST no produto (ignoradas)', 'linha sem NCM ou sem CST no produto (ignorada)')
    numeros_da_etapa_1 = [
        _numero(len(eans_da_planilha), 'EANs na planilha', 'EAN na planilha'),
        _numero(produtos['mudou_cst'], 'produtos com CST diferente do que estava', 'produto com CST diferente do que estava'),
        _numero(len(perderam_cst_fora), 'produtos PERDERAM o CST (o EAN não está na planilha)', 'produto PERDEU o CST (o EAN não está na planilha)', TOM_AVISO),
        _numero(len(perderam_cst_sem_cst), 'produtos PERDERAM o CST (estão na planilha, sem CST)', 'produto PERDEU o CST (está na planilha, sem CST)', TOM_AVISO),
        _numero(cst.sem_produto_correspondente, 'EANs da planilha sem produto no sistema', 'EAN da planilha sem produto no sistema', TOM_AVISO),
        _numero(cst.eans_duplicados_na_planilha, 'EANs repetidos na planilha (vale o primeiro)', 'EAN repetido na planilha (vale o primeiro)', TOM_AVISO),
        _numero(cst.sem_ean_na_planilha, 'linhas sem EAN (ignoradas)', 'linha sem EAN (ignorada)', TOM_AVISO),
    ]
    numeros_da_etapa_4 = [
        _numero(produtos['mudaram'], 'produtos com algum imposto diferente do que estava', 'produto com algum imposto diferente do que estava'),
        _numero(produtos['mudou_icms'], 'com ICMS novo', 'com ICMS novo'),
        _numero(produtos['mudou_pis_cofins'], 'com PIS/COFINS novo', 'com PIS/COFINS novo'),
        # No Substituir quem não está na planilha perde o CST (contado no passo 1); "o grupo deles mudou" só vale para o Expandir.
        _numero(0 if substituir else produtos['fora_da_planilha'], 'dos que mudaram nem estão na planilha (o grupo deles mudou)',
                'dos que mudaram não está na planilha (o grupo dele mudou)', TOM_AVISO),
        _numero(produtos['perderam_valor'], 'ficaram sem valor em algum imposto (sem dado validado)',
                'ficou sem valor em algum imposto (sem dado validado)', TOM_AVISO),
        _numero(importador.pis_cofins_tributo_ja_pago_zero, 'com PIS/COFINS em 0% pela regra do tributo já pago',
                'com PIS/COFINS em 0% pela regra do tributo já pago'),
    ]
    etapas = [
        {'numero': 1, 'titulo': 'CST dos produtos',
         'numeros': [n for n in numeros_da_etapa_1 if n['valor'] or n['plural'] == 'EANs na planilha']},
        _etapa_de_grupos(2, 'ICMS por grupo (NCM + CST + origem)', grupos_icms, contagem_icms, *sem_ncm_ou_cst, remocao_icms['grupos_removidos']),
        _etapa_de_grupos(3, 'PIS e COFINS por grupo (NCM + CST)', grupos_pis, contagem_pis, *sem_ncm_ou_cst, remocao_pis['grupos_removidos']),
        {'numero': 4, 'titulo': 'Impostos nos produtos',
         'numeros': [n for n in numeros_da_etapa_4 if n['valor'] or n['plural'] == 'produtos com algum imposto diferente do que estava']},
    ]

    atencoes = []
    mudaram = contagem_icms.mudaram_detalhe + contagem_pis.mudaram_detalhe
    if mudaram:
        itens, mais = _lista_curta(mudaram)
        atencoes.append({
            'titulo': 'Grupos que já existiam e mudaram de valor (valem para todos os produtos do grupo, estejam ou não na planilha)',
            'itens': itens, 'mais': mais,
        })
    rejeitados = contagem_icms.rejeitados_detalhe + contagem_pis.rejeitados_detalhe
    if rejeitados:
        itens, mais = _lista_curta(rejeitados)
        titulo = ('Grupos rejeitados (a planilha não dá valor válido para eles: os valores antigos foram apagados — veja a lista do que foi apagado)'
                  if substituir else 'Grupos rejeitados (nada novo foi gravado deles; a tela de Auditoria Fiscal mostra o detalhe)')
        atencoes.append({'titulo': titulo, 'itens': itens, 'mais': mais})
    if cst.eans_sem_produto:
        itens, mais = _lista_curta(cst.eans_sem_produto)
        atencoes.append({'titulo': 'EANs da planilha que não existem como produto neste sistema', 'itens': itens, 'mais': mais})

    criados = contagem_icms.novos + contagem_pis.novos
    mudaram_n = contagem_icms.mudaram + contagem_pis.mudaram
    rejeitados_n = contagem_icms.rejeitados + contagem_pis.rejeitados
    removidas = remocao_icms['grupos_removidos'] + remocao_pis['grupos_removidos']
    substituicao = None
    if substituir:
        substituicao = _montar_substituicao(
            alias, produtos_antes, produtos, perderam_cst_fora, perderam_cst_sem_cst, remocao_icms, remocao_pis,
            importador.pis_cofins_tributo_ja_pago_zero,
        )
    # Grupo rejeitado = a planilha tem um grupo que o sistema não aceitou: nunca pode aparecer como "Já estava em dia".
    return {
        'criados': criados, 'mudaram': mudaram_n, 'iguais': contagem_icms.iguais + contagem_pis.iguais, 'removidas': removidas,
        'produtos_mudaram': produtos['mudaram'], 'produtos_perderam_cst': len(perderam_cst_fora) + len(perderam_cst_sem_cst),
        'rejeitados': rejeitados_n,
        'nada_mudou': not (criados or mudaram_n or produtos['mudaram'] or rejeitados_n or removidas or (substituicao and not substituicao['nada_a_apagar'])),
        'etapas': etapas, 'atencoes': atencoes, 'modo': modo, 'substituicao': substituicao,
    }
