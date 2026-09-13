# Função Objetivo: Monta o dado pronto pra exibir a tela de Auditoria
# Fiscal (Camada D da auditoria fiscal — ver Descoberta "Auditoria Fiscal
# de Impostos de Saida" no vault, 13/09/2026) — 2 abas (ICMS por NCM e
# PIS/COFINS por NCM+CST), cada 1 listando TODAS as rejeições da última
# importação, sem truncar, já ordenadas por impacto (qtd_eans_no_grupo,
# maior primeiro — Meta.ordering dos próprios models). Só lê
# IcmsNcmRejeitado/PisCofinsNcmCstRejeitado — nunca a planilha Excel ao
# vivo (mesma garantia de motivo_impostos_saida.py: a tela nunca desalinha
# do banco).

from impostos.models import IcmsNcmRejeitado, PisCofinsNcmCstRejeitado


# Função Objetivo: Extrai todos os EANs de 1 estrutura de divergências
# (seja por UF, seja por campo PIS/COFINS) — usado só pra montar o texto
# de busca da tela, nunca reexibido em si (o detalhe completo já vem de
# divergencias_por_uf/campos_divergentes direto no template).
def _todos_eans(estrutura_divergencias):
    eans = []
    for grupos in estrutura_divergencias.values():
        for grupo in grupos:
            eans.extend(grupo.get('eans', []))
    return eans


def _linha_icms(rejeitado):
    return {
        'ncm': rejeitado.ncm,
        'qtd_eans_no_grupo': rejeitado.qtd_eans_no_grupo,
        'qtd_ufs_divergentes': rejeitado.qtd_ufs_divergentes,
        'divergencias_por_uf': rejeitado.divergencias_por_uf,
        'constatado_em': rejeitado.constatado_em,
        'busca': (' '.join([rejeitado.ncm] + _todos_eans(rejeitado.divergencias_por_uf))).lower(),
    }


def _linha_pis_cofins(rejeitado):
    return {
        'ncm': rejeitado.ncm,
        'cst': rejeitado.cst,
        'qtd_eans_no_grupo': rejeitado.qtd_eans_no_grupo,
        'campos_divergentes': rejeitado.campos_divergentes,
        'constatado_em': rejeitado.constatado_em,
        'busca': (
            ' '.join([rejeitado.ncm, rejeitado.cst] + _todos_eans(rejeitado.campos_divergentes))
        ).lower(),
    }


# Função Objetivo: Ponto de entrada da view — 1 única consulta por tabela
# (sem paginação: a auditoria existe justamente pra nunca truncar nada —
# decisão do vault, 13/09/2026; volume esperado é de dezenas de NCMs
# rejeitados, não milhares).
def montar_contexto_auditoria_fiscal():
    rejeitados_icms = list(IcmsNcmRejeitado.objects.all())
    rejeitados_pis_cofins = list(PisCofinsNcmCstRejeitado.objects.all())

    return {
        'linhas_icms': [_linha_icms(r) for r in rejeitados_icms],
        # Todo IcmsNcmRejeitado desta rodada compartilha o MESMO
        # constatado_em (garantia do vault) — o 1º da lista já representa
        # a rodada inteira. None quando a tabela está vazia (comando nunca
        # rodou, ou rodou e não achou rejeição nenhuma — os 2 casos são
        # indistinguíveis aqui de propósito: o que importa pro usuário é
        # que não há nada pendente agora).
        'constatado_em_icms': rejeitados_icms[0].constatado_em if rejeitados_icms else None,
        'linhas_pis_cofins': [_linha_pis_cofins(r) for r in rejeitados_pis_cofins],
        'constatado_em_pis_cofins': rejeitados_pis_cofins[0].constatado_em if rejeitados_pis_cofins else None,
    }