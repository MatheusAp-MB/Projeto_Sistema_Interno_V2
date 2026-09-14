# impostos/funcoes_auxiliares/exibicao_pis_cofins_por_ncm_cst.py

# Função Objetivo: Monta o dado pronto pra exibir a tela de PIS/COFINS por
# NCM + CST (tabela sempre visível + consulta por NCM+CST) — nunca grava
# nada, só lê PisCofinsSaidaPorNcmCst. Espelha exibicao_icms_por_ncm.py, trocando
# a chave NCM por NCM+CST (decisão: PIS/COFINS só bate por NCM+CST, não
# por NCM sozinho — ver Descoberta no vault).

from impostos.models import PisCofinsSaidaPorNcmCst


# Função Objetivo: Monta as linhas da tabela completa — 1 por combinação
# NCM+CST, com marcação de quando é a 1ª linha do NCM (pra não repetir o
# código na tela) e quantos CSTs aquele NCM tem (pro selo informativo).
def montar_tabela_pis_cofins_por_ncm_cst():
    registros = list(PisCofinsSaidaPorNcmCst.objects.order_by('ncm', 'cst'))

    total_csts_por_ncm = {}
    for registro in registros:
        total_csts_por_ncm[registro.ncm] = total_csts_por_ncm.get(registro.ncm, 0) + 1

    linhas = []
    ncm_anterior = None
    for registro in registros:
        linhas.append({
            'ncm': registro.ncm,
            'cst': registro.cst,
            'pis': registro.pis,
            'cofins': registro.cofins,
            'mostrar_ncm': registro.ncm != ncm_anterior,
            'total_csts_do_ncm': total_csts_por_ncm[registro.ncm],
        })
        ncm_anterior = registro.ncm

    return linhas


# Função Objetivo: Lista os CSTs que existem de verdade pro NCM digitado —
# usado pra popular o <select> de CST dependente, via HTMX, sem deixar o
# usuário cruzar um par NCM+CST que não existe.
def listar_csts_disponiveis_para_ncm(ncm):
    return list(
        PisCofinsSaidaPorNcmCst.objects.filter(ncm=ncm).order_by('cst').values_list('cst', flat=True)
    )


# Função Objetivo: Resolve 1 consulta NCM + CST pra calculadora da tela.
def consultar_pis_cofins_por_ncm_cst(ncm, cst):
    registro = PisCofinsSaidaPorNcmCst.objects.filter(ncm=ncm, cst=cst).first()
    if registro is None:
        return None, None, False
    return registro.pis, registro.cofins, True