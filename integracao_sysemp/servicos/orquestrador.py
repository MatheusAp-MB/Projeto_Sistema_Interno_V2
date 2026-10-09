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
#
# Atualizado (09/10/2026): além do retrato por produto, grava também o
# espelho da NOTA INTEIRA (todos os itens, ver NotaCompletaXml) de cada nota
# usada como base por algum produto — alimenta o botão "Ver NF" da grade de
# precificação. Falha no espelho nunca derruba o retrato do produto (mesma
# filosofia de resiliência: vira pendência + contador no relatório). Também
# ganhou o parâmetro desde (busca mais pra trás que a janela normal, pra
# preencher o espelho de notas antigas sem mexer na cobertura).

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date

from django.db import DatabaseError

from api_sysemp import ApiSysemp
from api_sysemp.core.excecoes import ErroAPISysemp
from produtos.models import Produto

from impostos.funcoes_auxiliares.entrada.sincronizacao_impostos_entrada import sincronizar_impostos_entrada_do_xml
from impostos.funcoes_auxiliares.entrada.sincronizacao_nota_fiscal_entrada import gravar_nota_fiscal_completa
from integracao_sysemp.models import SincronizacaoXmlManifestoNotaEntrada

from .arquivos_retorno_api import (
    NOME_ARQUIVO_BRUTO,
    NOME_ARQUIVO_BRUTO_PARCIAL,
    NOME_ARQUIVO_FILTRADO,
    NOME_ARQUIVO_NOTAS_MAIS_RECENTES,
    salvar_json,
)
from .dados_xml_nf import DadosXmlNF, NotaCompletaXml
from .erros_sincronizacao import registrar_erro, remover_erro
from .filtro_cfop import contar_por_cfop, filtrar_por_cfop
from .notas_completas import agrupar_manifesto_por_chave
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
    # * [EXPLICAÇÃO] → espelho da nota inteira (ver NotaCompletaXml): quantas
    #                  notas foram gravadas/atualizadas e quantas falharam
    #                  (a falha vira pendência, nunca derruba o produto).
    notas_completas_gravadas: int = 0
    notas_completas_com_erro: int = 0
    # * [EXPLICAÇÃO] → 1 tupla (cfop, descrição, contagem) por CFOP
    #                  mantido, sempre na ordem de CFOPS_PARA_MANTER —
    #                  mostra qual CFOP puxou o volume, sem abrir json.
    contagem_por_cfop: list = field(default_factory=list)


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


def _gravar_nota_completa_uma_vez(
    chave: str, linhas_por_chave: dict[str, list[dict]], chaves_ja_tratadas: set[str],
    relatorio: RelatorioDeSincronizacao,
) -> None:
    """Grava o espelho da nota inteira (todos os itens) 1 única vez por
    execução — vários produtos selecionados costumam sair da mesma nota.
    Qualquer falha vira pendência (a chave da nota é o identificador da
    pendência, em vez de um Código Barras) e nunca interrompe o lote."""
    if chave in chaves_ja_tratadas:
        return
    chaves_ja_tratadas.add(chave)
    try:
        linhas_da_nota = linhas_por_chave.get(chave)
        if not linhas_da_nota:
            raise ValueError('nota não encontrada entre as linhas do bruto')
        nota = NotaCompletaXml.a_partir_dos_registros(linhas_da_nota)
        gravar_nota_fiscal_completa(nota)
    except (KeyError, ValueError, TypeError, DatabaseError) as erro:
        registrar_erro(chave, etapa='persistencia_nota_completa', mensagem=str(erro))
        relatorio.notas_completas_com_erro += 1
        return
    remover_erro(chave)
    relatorio.notas_completas_gravadas += 1


def persistir_selecionados_no_banco(
    selecionados: list[dict], relatorio: RelatorioDeSincronizacao,
    linhas_por_chave: dict[str, list[dict]] | None = None,
) -> None:
    """Único ponto que persiste os registros já selecionados (1 nota mais
    recente por produto) no banco — usado tanto pelo pipeline completo
    (sincronizar_impostos_entrada_xml) quanto por qualquer reprocessamento
    a partir de um json já salvo em disco, sem tocar API nem watermark
    (ver management command reprocessar_impostos_entrada_de_json).

    linhas_por_chave (opcional, ver notas_completas.py): todas as linhas
    do bruto agrupadas por nota. Quando passado, grava também o espelho da
    nota inteira de cada produto sincronizado. None (reprocessamento só a
    partir do json de selecionados, que não tem os outros itens da nota)
    = grava só o retrato por produto, como sempre."""
    chaves_ja_tratadas: set[str] = set()
    for registro in selecionados:
        codigo_barras = registro[CAMPO_CODIGO_PRODUTO]
        produto = Produto.objects.filter(ean=codigo_barras).first()
        if produto is None:
            relatorio.produtos_sem_correspondencia += 1
            continue  # produto ainda não cadastrado no sistema — não é erro
        try:
            dados = DadosXmlNF.a_partir_do_registro(registro)
            sincronizar_impostos_entrada_do_xml(produto, dados)
        except (KeyError, ValueError, TypeError, DatabaseError) as erro:
            # * [EXPLICAÇÃO] → DatabaseError entra aqui (09/10/2026): dado de
            #                  nota que não cabe na coluna (ex: redução de PIS/
            #                  COFINS absurda quando o Custo Total do Sysemp está
            #                  inconsistente com a base de cálculo — achado real
            #                  na Samvale, NF 1781) levantava DataError, que não
            #                  era capturado e derrubava o lote INTEIRO no meio
            #                  de milhares de produtos. Agora vira pendência
            #                  daquele produto só (a transação dele já foi
            #                  desfeita, nada fica pela metade) e o lote segue.
            registrar_erro(codigo_barras, etapa='parse_ou_persistencia', mensagem=str(erro))
            relatorio.produtos_com_erro += 1
            continue
        remover_erro(codigo_barras)
        relatorio.produtos_sincronizados += 1
        if linhas_por_chave is not None:
            _gravar_nota_completa_uma_vez(
                dados.identificacao_nf.chave_acesso_nf, linhas_por_chave, chaves_ja_tratadas, relatorio,
            )


def sincronizar_impostos_entrada_xml(
    informar_fase=None, informar_pagina=None, forcar=False, desde: date | None = None,
) -> RelatorioDeSincronizacao:
    """Executa a sincronização de ponta a ponta. Devolve o relatório de
    tempo/contagens — só mede, não decide nem aplica nenhuma otimização
    por conta própria. informar_fase(mensagem: str) é chamado a cada fase
    relevante. informar_pagina(numero_da_pagina, registros_na_pagina,
    total_acumulado), se passado, substitui a versão em texto genérico —
    permite quem chama montar exibição mais rica (ex: linha ao vivo com
    ritmo) sem o orquestrador saber de rich, console, ou nada disso.
    forcar=True ignora a guarda de esta_desatualizada() (o "descanso" de
    MARGEM_DE_SEGURANCA_DIAS) e busca a mesma janela de sempre mesmo que
    a cobertura ainda esteja fresca — usado quando se sabe que um dado
    pode ter entrado no Sysemp fora do ritmo normal (ex: nota fiscal
    antiga cuja entrada só foi lançada agora, achado real de 19/08/2026
    com a marca HIDROLIGHT) e não dá pra esperar o prazo normal.
    desde (opcional, implica forcar): busca a partir desta data se ela for
    anterior ao início da janela normal — nunca encurta a janela normal.
    Serve pra preencher o espelho de notas antigas (ver notas_completas.py)
    sem esperar uma nota nova de cada produto. Não mexe na cobertura além
    do que uma sincronização normal já faria."""

    def _informar(mensagem: str) -> None:
        if informar_fase is not None:
            informar_fase(mensagem)

    def _informar_pagina(numero_da_pagina, registros_na_pagina, total_acumulado):
        if informar_pagina is not None:
            informar_pagina(numero_da_pagina, registros_na_pagina, total_acumulado)
        else:
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
    if not forcar and desde is None and not registro_watermark.esta_desatualizada():
        _informar('Dados já atualizados — nada a fazer.')
        return _finalizar()

    data_inicial, data_final = registro_watermark.calcular_janela_da_proxima_busca()
    if desde is not None and desde < data_inicial:
        data_inicial = desde
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
        relatorio.contagem_por_cfop = contar_por_cfop(filtrado)
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
        persistir_selecionados_no_banco(
            selecionados, relatorio, linhas_por_chave=agrupar_manifesto_por_chave(bruto['retorno']),
        )

    registro_watermark.registrar_sincronizacao_bem_sucedida(data_inicial, data_final)
    _informar('Sincronização concluída.')
    return _finalizar()