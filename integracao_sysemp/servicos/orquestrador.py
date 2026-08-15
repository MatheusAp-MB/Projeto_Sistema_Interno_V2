# integracao_sysemp/servicos/orquestrador.py

# Função Objetivo: Ponto de entrada único da sincronização de impostos de
# entrada — decide o período (watermark), busca a API, filtra, seleciona,
# grava os jsons de apoio, e persiste no banco produto a produto. Erro
# individual não trava o lote inteiro; erro total (rede/API) marca falha
# no watermark sem tocar a cobertura. Cronometra cada fase (granular) —
# só mede, não decide nem aplica otimização nenhuma por conta própria.
# Devolve RelatorioDeSincronizacao, não dict cru — cada fase é um campo
# nomeado (None quando a fase nem chegou a rodar), mesma filosofia de
# objeto estruturado já usada em todo o resto do projeto (ver
# "Modelagem de Objeto e Encapsulamento" no vault). Aceita um callback
# opcional informar_fase(mensagem: str) — quem chama decide como exibir
# (ou nem exibe, se não passar nada); o orquestrador nunca imprime nada
# ele mesmo. Repassa progresso página a página durante a busca na API
# (mesmo hook ao_avancar_pagina já usado em scripts_exploracao_ERP).
#
# Atualizado (15/08/2026): filtrar_por_cfop() e
# selecionar_nota_mais_recente_por_produto() agora devolvem (resultado,
# erros) em vez de só o resultado — 1 registro malformado (nota com
# itens_nf nulo, data ou NF inválida, linha sem Código Barras) não
# derruba mais a fase inteira, só vira 1 entrada na lista de erros. Essas
# 2 funções continuam sem saber de disco (ver arquivos_retorno_api.py:
# "nenhuma função de negócio sabe de disco por conta própria") — é o
# orquestrador quem chama registrar_erro() pra cada erro devolvido, mesma
# filosofia de resiliência já usada em persistir_selecionados_no_banco.
# Novos campos no relatório (notas_com_erro_no_filtro,
# linhas_com_erro_na_selecao) tornam essas pendências visíveis sem
# precisar abrir o json de erros.

import time
from contextlib import contextmanager
from dataclasses import dataclass

from api_sysemp import ApiSysemp
from api_sysemp.core.excecoes import ErroAPISysemp
from produtos.models import Produto

from impostos.models import ImpostosECustosXMLEntradaProduto
from integracao_sysemp.models import SincronizacaoXmlManifestoNotaEntrada

from .arquivos_retorno_api import (
    NOME_ARQUIVO_BRUTO,
    NOME_ARQUIVO_BRUTO_PARCIAL,
    NOME_ARQUIVO_FILTRADO,
    NOME_ARQUIVO_NOTAS_MAIS_RECENTES,
    salvar_json,
)
from .dados_xml_nf import DadosXmlNF
from .erros_sincronizacao import registrar_erro, remover_erro
from .filtro_cfop import filtrar_por_cfop
from .selecao_nota_recente import selecionar_nota_mais_recente_por_produto

CAMPO_CODIGO_PRODUTO = 'Código Barras'


@dataclass
class RelatorioDeSincronizacao:
    """Tempo de cada fase (segundos) e contagens de produtos de 1
    execução do orquestrador. Campo de tempo = None significa que
    aquela fase nem chegou a rodar (ex: watermark não estava
    desatualizado, ou a busca na API falhou antes das fases seguintes).
    total é o único tempo sempre preenchido."""

    total: float = 0.0
    busca_api: float | None = None
    salvar_bruto: float | None = None
    filtro_cfop: float | None = None
    salvar_filtrado: float | None = None
    selecao_nota_recente: float | None = None
    salvar_selecionados: float | None = None
    persistencia_no_banco: float | None = None
    produtos_selecionados: int = 0
    produtos_sincronizados: int = 0
    produtos_sem_correspondencia: int = 0
    produtos_com_erro: int = 0
    notas_com_erro_no_filtro: int = 0
    linhas_com_erro_na_selecao: int = 0


@contextmanager
def _cronometrar(relatorio: RelatorioDeSincronizacao, campo: str):
    """Guarda o tempo gasto no bloco no campo indicado (segundos) — usa
    try/finally pra registrar mesmo se o bloco terminar em exceção
    tratada dentro dele."""
    inicio = time.perf_counter()
    try:
        yield
    finally:
        setattr(relatorio, campo, time.perf_counter() - inicio)


def _registrar_erros(erros: list[dict], etapa: str) -> None:
    """Recebe a lista de erros devolvida por uma etapa pura (filtro ou
    seleção) e grava cada 1 como pendência de verdade — só o orquestrador
    sabe de disco (ver arquivos_retorno_api.py)."""
    for erro in erros:
        registrar_erro(erro['identificador'], etapa=etapa, mensagem=erro['mensagem'])


def persistir_selecionados_no_banco(selecionados: list[dict], relatorio: RelatorioDeSincronizacao) -> None:
    """Único ponto que persiste os registros já selecionados (1 nota mais
    recente por produto) no banco — usado tanto pelo pipeline completo
    (sincronizar_impostos_entrada_xml) quanto por qualquer reprocessamento
    a partir de um json já salvo em disco, sem tocar API nem watermark
    (ver management command reprocessar_impostos_entrada_de_json)."""
    for registro in selecionados:
        codigo_barras = registro[CAMPO_CODIGO_PRODUTO]
        produto = Produto.objects.filter(ean=codigo_barras).first()
        if produto is None:
            relatorio.produtos_sem_correspondencia += 1
            continue  # produto ainda não cadastrado no sistema — não é erro
        try:
            dados = DadosXmlNF.a_partir_do_registro(registro)
            ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)
        except (KeyError, ValueError, TypeError) as erro:
            registrar_erro(codigo_barras, etapa='parse_ou_persistencia', mensagem=str(erro))
            relatorio.produtos_com_erro += 1
            continue
        remover_erro(codigo_barras)
        relatorio.produtos_sincronizados += 1


def sincronizar_impostos_entrada_xml(informar_fase=None) -> RelatorioDeSincronizacao:
    """Executa a sincronização de ponta a ponta. Devolve o relatório de
    tempo/contagens — só mede, não decide nem aplica nenhuma otimização
    por conta própria. informar_fase(mensagem: str), se passado, é
    chamado a cada fase relevante (inclusive página a página durante a
    busca na API) — o orquestrador nunca imprime nada sozinho."""

    def _informar(mensagem: str) -> None:
        if informar_fase is not None:
            informar_fase(mensagem)

    def _informar_pagina(numero_da_pagina, registros_na_pagina, total_acumulado):
        _informar(
            f'Buscando na API — página {numero_da_pagina} '
            f'(+{registros_na_pagina}, total {total_acumulado})',
        )

    def _salvar_parcial_em_falha(registros_acumulados):
        # * [EXPLICAÇÃO] → dado de API é caro — se a busca falhar no meio
        #                  de uma paginação longa, o que já foi obtido com
        #                  sucesso fica salvo aqui, nunca só na memória.
        #                  Não é o Bruto oficial (pode estar incompleto) —
        #                  fica num arquivo à parte, recuperável à mão se
        #                  algum dia for preciso (reprocessar_impostos_
        #                  entrada_do_bruto pode apontar pra este arquivo
        #                  em vez do oficial).
        salvar_json({'retorno': registros_acumulados}, NOME_ARQUIVO_BRUTO_PARCIAL)

    relatorio = RelatorioDeSincronizacao()
    inicio_total = time.perf_counter()

    def _finalizar() -> RelatorioDeSincronizacao:
        relatorio.total = time.perf_counter() - inicio_total
        return relatorio

    registro_watermark = SincronizacaoXmlManifestoNotaEntrada.obter()
    if not registro_watermark.esta_desatualizada():
        _informar('Dados já atualizados — nada a fazer.')
        return _finalizar()

    data_inicial, data_final = registro_watermark.calcular_janela_da_proxima_busca()
    _informar(f'Buscando manifesto na API ({data_inicial.isoformat()} → {data_final.isoformat()})...')

    # * [EXPLICAÇÃO] → limpa o parcial ANTES de tentar, não só depois de um
    #                  sucesso total — achado real (15/08/2026): se esta
    #                  tentativa falhar antes mesmo da 1ª página (nenhum
    #                  registro acumulado ainda), ao_falhar_com_parcial nem
    #                  chega a ser chamado — sem esta limpeza aqui, o
    #                  parcial de uma tentativa ANTERIOR e sem relação
    #                  nenhuma ficaria parado no disco, parecendo
    #                  (erradamente) pertencer à tentativa atual.
    salvar_json({'retorno': []}, NOME_ARQUIVO_BRUTO_PARCIAL)

    houve_erro_na_api = False
    mensagem_erro_api = ''
    with _cronometrar(relatorio, 'busca_api'):
        try:
            bruto = ApiSysemp().impostos_entrada.listar_periodo_completo(
                data_inicial.isoformat(), data_final.isoformat(),
                ao_avancar_pagina=_informar_pagina, ao_falhar_com_parcial=_salvar_parcial_em_falha,
            )
        except ErroAPISysemp as erro:
            mensagem_erro_api = str(erro)
            registro_watermark.registrar_falha(mensagem_erro_api)
            houve_erro_na_api = True

    if houve_erro_na_api:
        _informar(f'Falha na busca da API: {mensagem_erro_api}')
        return _finalizar()

    with _cronometrar(relatorio, 'salvar_bruto'):
        salvar_json(bruto, NOME_ARQUIVO_BRUTO)
        # * [EXPLICAÇÃO] → busca terminou com sucesso total — o parcial já
        #                  foi limpo no início desta tentativa (acima) e
        #                  segue vazio, já que nenhuma falha aconteceu no
        #                  meio do caminho pra sobrescrevê-lo.

    _informar(f'Filtrando por CFOP ({len(bruto["retorno"])} notas brutas)...')
    with _cronometrar(relatorio, 'filtro_cfop'):
        filtrado, erros_filtro = filtrar_por_cfop(bruto['retorno'])
    _registrar_erros(erros_filtro, etapa='filtro_cfop')
    relatorio.notas_com_erro_no_filtro = len(erros_filtro)
    if erros_filtro:
        _informar(f'{len(erros_filtro)} nota(s) puladas por erro no filtro CFOP — ver pendências.')

    with _cronometrar(relatorio, 'salvar_filtrado'):
        salvar_json(filtrado, NOME_ARQUIVO_FILTRADO)

    _informar(f'Selecionando a nota mais recente por produto ({len(filtrado)} registros filtrados)...')
    with _cronometrar(relatorio, 'selecao_nota_recente'):
        selecionados, erros_selecao = selecionar_nota_mais_recente_por_produto(filtrado)
    _registrar_erros(erros_selecao, etapa='selecao_nota_recente')
    relatorio.linhas_com_erro_na_selecao = len(erros_selecao)
    if erros_selecao:
        _informar(f'{len(erros_selecao)} linha(s) puladas por erro na seleção da nota mais recente — ver pendências.')
    relatorio.produtos_selecionados = len(selecionados)

    with _cronometrar(relatorio, 'salvar_selecionados'):
        salvar_json(selecionados, NOME_ARQUIVO_NOTAS_MAIS_RECENTES)

    _informar(f'Persistindo no banco ({len(selecionados)} produtos selecionados)...')
    with _cronometrar(relatorio, 'persistencia_no_banco'):
        persistir_selecionados_no_banco(selecionados, relatorio)

    registro_watermark.registrar_sincronizacao_bem_sucedida(data_inicial, data_final)
    _informar('Sincronização concluída.')
    return _finalizar()