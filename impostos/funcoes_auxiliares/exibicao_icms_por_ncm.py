# impostos/funcoes_auxiliares/exibicao_icms_por_ncm.py

# Função Objetivo: Monta o dado pronto pra exibir a tela de ICMS por NCM
# (matriz NCM × UF + Média Ponderada) — nunca grava nada, só lê IcmsNcmUf
# e calcula a Média Ponderada em tempo real (decisão no vault: ela nunca
# é gravada, sempre calculada na hora, pra nunca ficar desatualizada).

from decimal import Decimal

from impostos.funcoes_auxiliares.importacao_icms_ncm import UFS_ORDENADAS
from impostos.models import IcmsNcmUf

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


# Função Objetivo: Monta as linhas da matriz — 1 por NCM, já com a Média Ponderada calculada.
def montar_matriz_icms_por_ncm():
    valores_por_ncm = {}
    for registro in IcmsNcmUf.objects.all():
        valores_por_ncm.setdefault(registro.ncm, {})[registro.uf] = registro.aliquota

    linhas = []
    for ncm in sorted(valores_por_ncm.keys()):
        valores_por_uf = valores_por_ncm[ncm]
        linhas.append({
            'ncm': ncm,
            'valores': [
                {'uf': uf, 'aliquota': valores_por_uf.get(uf)}
                for uf in UFS_ORDENADAS
            ],
            'media_ponderada': calcular_media_ponderada(valores_por_uf),
        })

    return linhas


# Função Objetivo: Resolve 1 consulta NCM + UF (ou Média Ponderada) pra calculadora da tela.
def consultar_icms_por_ncm(ncm, uf):
    valores_por_uf = {
        registro.uf: registro.aliquota
        for registro in IcmsNcmUf.objects.filter(ncm=ncm)
    }

    ncm_encontrado = bool(valores_por_uf)
    e_media_ponderada = (uf == 'MEDIA_PONDERADA')

    if not ncm_encontrado:
        return None, False, e_media_ponderada

    if e_media_ponderada:
        return calcular_media_ponderada(valores_por_uf), True, True

    return valores_por_uf.get(uf), True, False