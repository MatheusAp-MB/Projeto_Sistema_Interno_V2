# integracao_sysemp/servicos/orquestrador.py

# Função Objetivo: Ponto de entrada único da sincronização de impostos de
# entrada — decide o período (watermark), busca a API, filtra, seleciona,
# grava os jsons de apoio, e persiste no banco produto a produto. Erro
# individual não trava o lote inteiro; erro total (rede/API) marca falha
# no watermark sem tocar a cobertura. Ver desenho completo no vault.

from api_sysemp import ApiSysemp
from api_sysemp.core.excecoes import ErroAPISysemp
from produtos.models import Produto
from scripts_exploracao_ERP.dados_xml_nf import DadosXmlNF

from impostos.models import ImpostosECustosXMLEntradaProduto
from integracao_sysemp.models import SincronizacaoXmlManifestoNotaEntrada

from .arquivos_retorno_api import (
    NOME_ARQUIVO_BRUTO,
    NOME_ARQUIVO_FILTRADO,
    NOME_ARQUIVO_NOTAS_MAIS_RECENTES,
    salvar_json,
)
from .erros_sincronizacao import registrar_erro, remover_erro
from .filtro_cfop import filtrar_por_cfop
from .selecao_nota_recente import selecionar_nota_mais_recente_por_produto

CAMPO_CODIGO_PRODUTO = 'Código Barras'


def sincronizar_impostos_entrada_xml() -> None:
    registro_watermark = SincronizacaoXmlManifestoNotaEntrada.obter()
    if not registro_watermark.esta_desatualizada():
        return

    data_inicial, data_final = registro_watermark.calcular_janela_da_proxima_busca()

    try:
        bruto = ApiSysemp().impostos_entrada.listar_periodo_completo(data_inicial, data_final)
    except ErroAPISysemp as erro:
        registro_watermark.registrar_falha(str(erro))
        return

    salvar_json(bruto, NOME_ARQUIVO_BRUTO)

    filtrado = filtrar_por_cfop(bruto['retorno'])
    salvar_json(filtrado, NOME_ARQUIVO_FILTRADO)

    selecionados = selecionar_nota_mais_recente_por_produto(filtrado)
    salvar_json(selecionados, NOME_ARQUIVO_NOTAS_MAIS_RECENTES)

    for registro in selecionados:
        codigo_barras = registro[CAMPO_CODIGO_PRODUTO]
        produto = Produto.objects.filter(ean=codigo_barras).first()
        if produto is None:
            continue  # produto ainda não cadastrado no sistema — não é erro
        try:
            dados = DadosXmlNF.a_partir_do_registro(registro)
            ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)
        except (KeyError, ValueError, TypeError) as erro:
            registrar_erro(codigo_barras, etapa='parse_ou_persistencia', mensagem=str(erro))
            continue
        remover_erro(codigo_barras)

    registro_watermark.registrar_sincronizacao_bem_sucedida(data_inicial, data_final)