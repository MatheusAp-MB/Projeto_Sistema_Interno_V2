# integracao_sysemp/servicos/tests/test_nivel_3__orquestrador.py

# Função Objetivo: Nível 3 (banco real) do orquestrador
# sincronizar_impostos_entrada_xml() — cobre a costura entre watermark,
# ApiSysemp (mockada como caixa-preta, já testada em api_sysemp/tests/),
# filtro/seleção, persistência em impostos e pendências de erro. Não
# repete a exaustão de retry/backoff da API, nem os cenários já cobertos
# em impostos/tests/ (sincronizar_a_partir_de) — só a orquestração.

from datetime import date

import pytest

from api_sysemp.core.excecoes import ErroAPISysemp
from impostos.models import ImpostosECustosXMLEntradaProduto
from integracao_sysemp.models import SincronizacaoXmlManifestoNotaEntrada
from integracao_sysemp.servicos import arquivos_retorno_api, erros_sincronizacao, orquestrador
from integracao_sysemp.servicos.orquestrador import sincronizar_impostos_entrada_xml
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 3 — orquestrador (sincronizar_impostos_entrada_xml)'

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])


@pytest.fixture(autouse=True)
def _redirecionar_pasta_retorno_api(tmp_path, monkeypatch):
    monkeypatch.setattr(arquivos_retorno_api, 'PASTA_RETORNO_API', tmp_path)


def _criar_produto(ean: str) -> Produto:
    return Produto.objects.create(ean=ean, titulo=f'Produto Teste {ean}')


def _item_padrao(**overrides) -> dict:
    valores = {
        'ID Produto': 1, 'Produto': 'Produto Teste', 'Código Barras': '7900000000001',
        'Código Auxiliar': '', 'Código Fabricante': '', 'Qtde': 1,
        'NR NF': '1001', 'Entrada NF': '2026-08-01', 'Emissão': '2026-07-30',
        'Fornecedor': 'Fornecedor Teste', 'Empresa Fantasia': 'Empresa Fantasia Teste',
        'CFOP XML': '1.102', 'CFOP Cadastro': '1.102',
        'Natureza da Operacao Cadastro': 'Compra',
        'Chave': 'chave-teste',
        'TES Saida Cadastro': 1, 'NCM XML': '00000000', 'NCM Cadastro': '00000000',
        'Origem XML': '0', 'Origem Cadastro': '0',
        'Origem Descricão XML': 'Nacional', 'Origem Descricão Cadastro': 'Nacional',
        'Base Calculo ICMS ST': 0, 'Aliquota ICMS ST': 0, 'Redução ICMS ST': 0, 'Valor ICMS ST': 0,
        '% FCP ST': 0, 'Valor FCP ST': 0,
        'CST ICMS': 0, 'CST ICMS Cadastro': 0, 'Base Calculo ICMS': 100, 'Aliquota ICMS': 18,
        'Redução ICMS': 0, 'Valor ICMS': 18,
        'Base ICMS Ret': 0, 'Valor ICMS Ret': 0,
        'CST IPI': 0, 'CST IPI Cadastro': 0, 'Base Calculo IPI': 100, 'Aliquota IPI': 5, 'Valor IPI': 5,
        'CST PIS': 0, 'CST PIS Cadastro': 0, 'Base Calculo PIS': 100, 'Aliquota PIS': 1.65, 'Valor PIS': 1.65,
        'CST COFINS': 0, 'CST COFINS Cadastro': 0, 'Base Calculo COFINS': 100, 'Aliquota COFINS': 7.6,
        'Valor COFINS': 7.6,
        'Custo Total': 100, 'Custo Unitário': 100,
    }
    valores.update(overrides)
    return valores


def _nota_com_item(**overrides_item) -> dict:
    return {'itens_nf': [_item_padrao(**overrides_item)]}


class _ImpostosEntradaFalso:
    def __init__(self, retorno=None, excecao=None, paginas_simuladas=None, registros_parciais_na_falha=None):
        self._retorno = retorno
        self._excecao = excecao
        self._paginas_simuladas = paginas_simuladas or []
        self._registros_parciais_na_falha = registros_parciais_na_falha

    def listar_periodo_completo(self, data_inicial, data_final, ao_avancar_pagina=None, ao_falhar_com_parcial=None):
        # * [EXPLICAÇÃO] → assert de tipo aqui não é excesso de zelo: um
        #                  mock permissivo demais (aceitando date OU str)
        #                  foi exatamente o que deixou passar um bug real
        #                  (orquestrador passando date, API exigindo str
        #                  ISO) sem nenhum teste pegar. Trava aqui pra
        #                  nunca mais passar batido.
        assert isinstance(data_inicial, str) and isinstance(data_final, str), (
            f'orquestrador precisa converter date pra string ISO antes de chamar a API '
            f'(recebido: {type(data_inicial)}, {type(data_final)})'
        )
        if ao_avancar_pagina is not None:
            for pagina in self._paginas_simuladas:
                ao_avancar_pagina(*pagina)
        if self._excecao is not None:
            # * [EXPLICAÇÃO] → simula o comportamento real de
            #                  listar_periodo_completo: acumula o que
            #                  conseguiu (páginas simuladas acima) antes
            #                  de chamar o callback de parcial e relançar.
            if self._registros_parciais_na_falha and ao_falhar_com_parcial is not None:
                ao_falhar_com_parcial(self._registros_parciais_na_falha)
            raise self._excecao
        return self._retorno


class _ApiSysempFalsa:
    def __init__(self, retorno=None, excecao=None, paginas_simuladas=None, registros_parciais_na_falha=None):
        self.impostos_entrada = _ImpostosEntradaFalso(
            retorno=retorno, excecao=excecao, paginas_simuladas=paginas_simuladas,
            registros_parciais_na_falha=registros_parciais_na_falha,
        )


def _mockar_api(monkeypatch, retorno=None, excecao=None, paginas_simuladas=None, registros_parciais_na_falha=None):
    monkeypatch.setattr(
        orquestrador, 'ApiSysemp',
        lambda: _ApiSysempFalsa(
            retorno=retorno, excecao=excecao, paginas_simuladas=paginas_simuladas,
            registros_parciais_na_falha=registros_parciais_na_falha,
        ),
    )


def _api_proibida(*args, **kwargs):
    raise AssertionError('ApiSysemp não deveria ser chamada quando não está desatualizado')


def test_sincroniza_com_sucesso_grava_jsons_persiste_e_avanca_watermark(monkeypatch, tabela_resultados):
    # Setup: nunca sincronizado, 1 produto real, API devolve 1 nota válida
    # pro EAN desse produto.
    hoje = date.today()
    produto = _criar_produto('7900000000001')
    bruto = {'retorno': [_nota_com_item(**{'Código Barras': '7900000000001'})]}
    _mockar_api(monkeypatch, retorno=bruto)

    # Exercise
    sincronizar_impostos_entrada_xml()

    # Assert: os 3 jsons de apoio existem, o produto foi sincronizado e o
    # watermark avançou até hoje.
    filtrado = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_FILTRADO)
    selecionados = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_NOTAS_MAIS_RECENTES)
    persistiu = ImpostosECustosXMLEntradaProduto.objects.filter(produto=produto).exists()
    watermark = SincronizacaoXmlManifestoNotaEntrada.obter()
    bateu = (
        len(filtrado) == 1 and len(selecionados) == 1 and persistiu
        and watermark.status == SincronizacaoXmlManifestoNotaEntrada.Status.SINCRONIZADO
        and watermark.data_final_cobertura == hoje
    )
    registrar_resultado(
        tabela_resultados, 'sincroniza_com_sucesso',
        '1 produto real, API devolve 1 nota válida', 'jsons gravados, impostos persistido, watermark sincronizado',
        'Fluxo feliz de ponta a ponta precisa costurar todas as peças já testadas isoladamente',
        f'filtrado={len(filtrado)}, selecionados={len(selecionados)}, persistiu={persistiu}, status={watermark.status!r}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_nao_desatualizado_nao_chama_api_nem_grava_nada(monkeypatch, tabela_resultados):
    # Setup: watermark sincronizado recentemente (dentro da margem) —
    # esta_desatualizada() é False. API proibida: qualquer chamada quebra
    # o teste na hora.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()
    registro.registrar_sincronizacao_bem_sucedida(date(2026, 1, 1), date.today())
    monkeypatch.setattr(orquestrador, 'ApiSysemp', _api_proibida)

    # Exercise
    sincronizar_impostos_entrada_xml()

    # Assert: nenhum json foi criado — prova que a função voltou antes de
    # tentar buscar qualquer coisa.
    bruto_existe = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_BRUTO) is not None
    registrar_resultado(
        tabela_resultados, 'nao_desatualizado_nao_chama_api',
        'watermark sincronizado dentro da margem', 'nenhuma chamada à API, nenhum json gravado',
        'Guarda de esta_desatualizada() evita chamada de rede sem necessidade',
        f'bruto_existe={bruto_existe}', bruto_existe is False,
    )
    assert bruto_existe is False

    # TearDown: nada a desmontar.


def test_erro_na_api_registra_falha_e_nao_avanca_watermark(monkeypatch, tabela_resultados):
    # Setup: nunca sincronizado, API falha de verdade (erro de rede).
    _mockar_api(monkeypatch, excecao=ErroAPISysemp('erro de rede simulado'))

    # Exercise
    sincronizar_impostos_entrada_xml()

    # Assert: watermark marca falha, cobertura continua vazia, nenhum
    # json foi gravado (a falha acontece antes de qualquer gravação).
    watermark = SincronizacaoXmlManifestoNotaEntrada.obter()
    bruto_existe = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_BRUTO) is not None
    bateu = (
        watermark.status == SincronizacaoXmlManifestoNotaEntrada.Status.FALHA
        and watermark.data_final_cobertura is None
        and bruto_existe is False
    )
    registrar_resultado(
        tabela_resultados, 'erro_na_api_registra_falha',
        'ErroAPISysemp na busca', 'status=Falha, cobertura intocada, nenhum json gravado',
        'Falha total (rede/API) nunca pode avançar o watermark nem deixar rastro de dado incompleto',
        f'status={watermark.status!r}, final={watermark.data_final_cobertura}, bruto_existe={bruto_existe}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_erro_antes_da_1a_pagina_limpa_parcial_de_tentativa_anterior(monkeypatch, tabela_resultados):
    # Setup: existe um parcial de uma tentativa ANTERIOR e sem relação
    # nenhuma com esta (achado real, 15/08/2026), e a API falha de cara,
    # antes de qualquer página — ao_falhar_com_parcial nem chega a ser
    # chamado nesse caso.
    arquivos_retorno_api.salvar_json(
        {'retorno': [{'sobra': 'de uma tentativa antiga sem relação com esta falha'}]},
        arquivos_retorno_api.NOME_ARQUIVO_BRUTO_PARCIAL,
    )
    _mockar_api(monkeypatch, excecao=ErroAPISysemp('erro de rede simulado antes da 1ª página'))

    # Exercise
    sincronizar_impostos_entrada_xml()

    # Assert: o parcial antigo não pode sobreviver — precisa estar limpo,
    # mesmo essa tentativa não tendo acumulado nenhuma página nova.
    parcial = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_BRUTO_PARCIAL, padrao=None)
    bateu = parcial == {'retorno': []}
    registrar_resultado(
        tabela_resultados, 'erro_antes_1a_pagina_limpa_parcial_antigo',
        'parcial de tentativa antiga presente, nova tentativa falha antes da 1ª página',
        "parcial limpo ({'retorno': []}), não o dado antigo",
        'Bug real corrigido (15/08/2026): sem limpar no início, o parcial de uma falha antiga e sem relação ficava parecendo ser desta tentativa',
        f'parcial={parcial}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_erro_no_meio_da_paginacao_salva_parcial_em_disco(monkeypatch, tabela_resultados):
    # Setup: nunca sincronizado, API consegue 1 página (2 registros) e
    # falha na seguinte — simula queda no meio de uma busca longa.
    registros_parciais = [_nota_com_item(**{'Código Barras': '7900000000001'})]
    _mockar_api(
        monkeypatch, excecao=ErroAPISysemp('erro de rede simulado no meio da paginação'),
        registros_parciais_na_falha=registros_parciais,
    )

    # Exercise
    sincronizar_impostos_entrada_xml()

    # Assert: watermark ainda marca falha (comportamento intocado), mas
    # o que já tinha sido buscado com sucesso está salvo no parcial —
    # nunca no Bruto oficial (que ficaria incompleto).
    watermark = SincronizacaoXmlManifestoNotaEntrada.obter()
    parcial = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_BRUTO_PARCIAL, padrao=None)
    bruto_existe = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_BRUTO) is not None
    bateu = (
        watermark.status == SincronizacaoXmlManifestoNotaEntrada.Status.FALHA
        and bruto_existe is False
        and parcial == {'retorno': registros_parciais}
    )
    registrar_resultado(
        tabela_resultados, 'erro_no_meio_da_paginacao_salva_parcial',
        'ErroAPISysemp após 1 página já obtida', 'watermark em falha, parcial salvo, Bruto oficial intocado',
        'Achado real (14/08/2026): dado de API é caro — falha no meio de uma paginação longa não pode jogar fora o que já foi buscado.',
        f'status={watermark.status!r}, bruto_existe={bruto_existe}, parcial={parcial}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_sincroniza_com_sucesso_limpa_parcial_de_tentativa_anterior(monkeypatch, tabela_resultados):
    # Setup: existe um parcial deixado por uma falha anterior, e agora
    # a API responde com sucesso completo.
    arquivos_retorno_api.salvar_json(
        {'retorno': [{'sobra': 'de uma tentativa anterior que falhou'}]},
        arquivos_retorno_api.NOME_ARQUIVO_BRUTO_PARCIAL,
    )
    produto = _criar_produto('7900000000001')
    bruto = {'retorno': [_nota_com_item(**{'Código Barras': '7900000000001'})]}
    _mockar_api(monkeypatch, retorno=bruto)

    # Exercise
    sincronizar_impostos_entrada_xml()

    # Assert: sucesso completo deixa o parcial obsoleto limpo — nunca
    # confunde uma tentativa velha com a atual (já completa e oficial
    # no Bruto.json).
    parcial = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_BRUTO_PARCIAL, padrao=None)
    persistiu = ImpostosECustosXMLEntradaProduto.objects.filter(produto=produto).exists()
    bateu = parcial == {'retorno': []} and persistiu
    registrar_resultado(
        tabela_resultados, 'sucesso_limpa_parcial_anterior',
        'parcial de tentativa anterior presente, sincronização atual com sucesso total',
        "parcial limpo ({'retorno': []})",
        'Parcial de tentativa velha não pode sobreviver a uma sincronização completa e bem-sucedida.',
        f'parcial={parcial}, persistiu={persistiu}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_codigo_barras_sem_produto_e_pulado_sem_erro(monkeypatch, tabela_resultados):
    # Setup: nunca sincronizado, API devolve 1 item cujo EAN não tem
    # Produto correspondente no banco.
    bruto = {'retorno': [_nota_com_item(**{'Código Barras': '0000000000000'})]}
    _mockar_api(monkeypatch, retorno=bruto)

    # Exercise
    sincronizar_impostos_entrada_xml()

    # Assert: nada foi persistido, nenhuma pendência de erro foi criada,
    # e o watermark AINDA avança (não encontrar produto não é falha).
    persistiu = ImpostosECustosXMLEntradaProduto.objects.exists()
    erros = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_ERROS, padrao={})
    watermark = SincronizacaoXmlManifestoNotaEntrada.obter()
    bateu = (
        persistiu is False and '0000000000000' not in erros
        and watermark.status == SincronizacaoXmlManifestoNotaEntrada.Status.SINCRONIZADO
    )
    registrar_resultado(
        tabela_resultados, 'codigo_barras_sem_produto_e_pulado',
        'EAN 0000000000000 sem Produto cadastrado', 'pulado, sem erro registrado, watermark avança',
        'Produto ainda não cadastrado no sistema é esperado — não é anomalia',
        f'persistiu={persistiu}, tem_erro={"0000000000000" in erros}, status={watermark.status!r}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_registro_malformado_vai_pros_erros_e_resto_do_lote_segue(monkeypatch, tabela_resultados):
    # Setup: 2 produtos reais — 1 com item válido, 1 com item malformado
    # (falta CST ICMS, quebra o parse do DadosXmlNF).
    _criar_produto('7900000000001')
    _criar_produto('7900000000002')
    item_valido = _item_padrao(**{'Código Barras': '7900000000001'})
    item_malformado = _item_padrao(**{'Código Barras': '7900000000002'})
    del item_malformado['CST ICMS']
    bruto = {'retorno': [{'itens_nf': [item_valido, item_malformado]}]}
    _mockar_api(monkeypatch, retorno=bruto)

    # Exercise
    sincronizar_impostos_entrada_xml()

    # Assert: o válido persiste, o malformado vai pros erros, e o
    # watermark AVANÇA mesmo assim (erro individual ≠ falha total).
    persistiu_valido = ImpostosECustosXMLEntradaProduto.objects.filter(
        produto__ean='7900000000001',
    ).exists()
    persistiu_malformado = ImpostosECustosXMLEntradaProduto.objects.filter(
        produto__ean='7900000000002',
    ).exists()
    erros = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_ERROS, padrao={})
    watermark = SincronizacaoXmlManifestoNotaEntrada.obter()
    bateu = (
        persistiu_valido and not persistiu_malformado
        and '7900000000002' in erros
        and watermark.status == SincronizacaoXmlManifestoNotaEntrada.Status.SINCRONIZADO
    )
    registrar_resultado(
        tabela_resultados, 'registro_malformado_vai_pros_erros',
        '1 item válido + 1 sem CST ICMS', 'válido persiste, malformado vira pendência, watermark avança',
        'Erro em 1 produto não pode travar os outros 999 do mesmo lote',
        f'valido={persistiu_valido}, malformado_persistiu={persistiu_malformado}, '
        f'tem_pendencia={"7900000000002" in erros}, status={watermark.status!r}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_nota_bruta_malformada_no_filtro_nao_derruba_a_sincronizacao(monkeypatch, tabela_resultados):
    # Setup: 1 produto real com nota válida + 1 nota bruta malformada
    # (itens_nf=None) no mesmo lote — bug corrigido em 15/08/2026 (antes,
    # isso derrubava filtrar_por_cfop inteiro).
    _criar_produto('7900000000001')
    nota_valida = _nota_com_item(**{'Código Barras': '7900000000001'})
    nota_malformada = {'NR NF': '9999', 'itens_nf': None}
    bruto = {'retorno': [nota_valida, nota_malformada]}
    _mockar_api(monkeypatch, retorno=bruto)

    # Exercise
    relatorio = sincronizar_impostos_entrada_xml()

    # Assert: o produto válido sincronizou normalmente, a nota malformada
    # virou pendência (não travou nada), e o watermark avançou.
    persistiu = ImpostosECustosXMLEntradaProduto.objects.filter(produto__ean='7900000000001').exists()
    erros = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_ERROS, padrao={})
    watermark = SincronizacaoXmlManifestoNotaEntrada.obter()
    bateu = (
        persistiu and '9999' in erros
        and relatorio.notas_com_erro_no_filtro == 1
        and watermark.status == SincronizacaoXmlManifestoNotaEntrada.Status.SINCRONIZADO
    )
    registrar_resultado(
        tabela_resultados, 'nota_bruta_malformada_no_filtro_nao_derruba',
        '1 nota válida + 1 nota com itens_nf=None no mesmo lote', 'válida sincroniza, malformada vira pendência, watermark avança',
        'Bug real corrigido (15/08/2026): 1 nota malformada não pode mais derrubar filtrar_por_cfop inteiro',
        f'persistiu={persistiu}, tem_pendencia_nf_9999={"9999" in erros}, '
        f'notas_com_erro_no_filtro={relatorio.notas_com_erro_no_filtro}, status={watermark.status!r}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_linha_malformada_na_selecao_nao_derruba_a_sincronizacao(monkeypatch, tabela_resultados):
    # Setup: 1 produto real com nota válida + 1 item que passa no filtro de
    # CFOP mas tem NR NF não numérico — quebra a etapa de seleção da nota
    # mais recente, não a de filtro. Bug real corrigido em 15/08/2026.
    _criar_produto('7900000000001')
    item_valido = _item_padrao(**{'Código Barras': '7900000000001'})
    item_com_nf_invalida = _item_padrao(**{'Código Barras': '7900000000002', 'NR NF': 'nao-numerico'})
    bruto = {'retorno': [{'itens_nf': [item_valido, item_com_nf_invalida]}]}
    _mockar_api(monkeypatch, retorno=bruto)

    # Exercise
    relatorio = sincronizar_impostos_entrada_xml()

    # Assert: o produto válido sincronizou normalmente, a linha com NF
    # inválida virou pendência (não travou nada), e o watermark avançou.
    persistiu = ImpostosECustosXMLEntradaProduto.objects.filter(produto__ean='7900000000001').exists()
    erros = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_ERROS, padrao={})
    watermark = SincronizacaoXmlManifestoNotaEntrada.obter()
    bateu = (
        persistiu and '7900000000002' in erros
        and relatorio.linhas_com_erro_na_selecao == 1
        and watermark.status == SincronizacaoXmlManifestoNotaEntrada.Status.SINCRONIZADO
    )
    registrar_resultado(
        tabela_resultados, 'linha_malformada_na_selecao_nao_derruba',
        '1 item válido + 1 item com NR NF="nao-numerico" no mesmo lote', 'válido sincroniza, inválido vira pendência, watermark avança',
        'Bug real corrigido (15/08/2026): linha com NF não numérica não pode mais derrubar a seleção nem passar batida',
        f'persistiu={persistiu}, tem_pendencia_produto_2={"7900000000002" in erros}, '
        f'linhas_com_erro_na_selecao={relatorio.linhas_com_erro_na_selecao}, status={watermark.status!r}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_produto_com_pendencia_antiga_remove_ao_sincronizar_bem(monkeypatch, tabela_resultados):
    # Setup: pendência de erro já registrada antes pra esse EAN, produto
    # real existe, e agora a API devolve um item bem formado pra ele.
    _criar_produto('7900000000009')
    erros_sincronizacao.registrar_erro('7900000000009', etapa='parse_ou_persistencia', mensagem='erro anterior simulado')
    bruto = {'retorno': [_nota_com_item(**{'Código Barras': '7900000000009'})]}
    _mockar_api(monkeypatch, retorno=bruto)

    # Exercise
    sincronizar_impostos_entrada_xml()

    # Assert: a pendência antiga não existe mais.
    erros = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_ERROS, padrao={})
    registrar_resultado(
        tabela_resultados, 'pendencia_antiga_removida_ao_sincronizar_bem',
        'pendência prévia + sincronização bem-sucedida do mesmo EAN', 'pendência removida',
        'Produto que voltou a sincronizar bem não pode continuar marcado como erro',
        f'{erros}', '7900000000009' not in erros,
    )
    assert '7900000000009' not in erros

    # TearDown: nada a desmontar.


def test_relatorio_de_sucesso_tem_todas_as_fases_e_contagens_certas(monkeypatch, tabela_resultados):
    # Setup: 1 produto real, API devolve 1 nota válida.
    _criar_produto('7900000000001')
    bruto = {'retorno': [_nota_com_item(**{'Código Barras': '7900000000001'})]}
    _mockar_api(monkeypatch, retorno=bruto)

    # Exercise
    relatorio = sincronizar_impostos_entrada_xml()

    # Assert: todas as 8 fases de tempo preenchidas, contagens certas.
    campos_de_tempo = (
        relatorio.busca_api, relatorio.salvar_bruto, relatorio.filtro_cfop,
        relatorio.salvar_filtrado, relatorio.selecao_nota_recente,
        relatorio.salvar_selecionados, relatorio.persistencia_no_banco, relatorio.total,
    )
    bateu = (
        all(tempo is not None and tempo >= 0 for tempo in campos_de_tempo)
        and relatorio.produtos_selecionados == 1
        and relatorio.produtos_sincronizados == 1
        and relatorio.produtos_sem_correspondencia == 0
        and relatorio.produtos_com_erro == 0
    )
    registrar_resultado(
        tabela_resultados, 'relatorio_de_sucesso_tem_todas_as_fases',
        '1 produto real, sincronização completa', '8 fases preenchidas, 1 selecionado, 1 sincronizado, 0/0 nas outras',
        'Relatório precisa refletir de verdade todas as fases que rodaram, não só devolver algo genérico',
        f'tempos={campos_de_tempo}, selecionados={relatorio.produtos_selecionados}, '
        f'sincronizados={relatorio.produtos_sincronizados}, sem_correspondencia={relatorio.produtos_sem_correspondencia}, '
        f'com_erro={relatorio.produtos_com_erro}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_relatorio_quando_nao_desatualizado_so_tem_total(monkeypatch, tabela_resultados):
    # Setup: watermark sincronizado recentemente (dentro da margem). API
    # proibida: qualquer chamada quebra o teste na hora.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()
    registro.registrar_sincronizacao_bem_sucedida(date(2026, 1, 1), date.today())
    monkeypatch.setattr(orquestrador, 'ApiSysemp', _api_proibida)

    # Exercise
    relatorio = sincronizar_impostos_entrada_xml()

    # Assert: nenhuma fase de busca/persistência rodou — só total.
    bateu = relatorio.busca_api is None and relatorio.persistencia_no_banco is None and relatorio.total is not None
    registrar_resultado(
        tabela_resultados, 'relatorio_nao_desatualizado_so_tem_total',
        'watermark dentro da margem, early return', 'busca_api=None, persistencia_no_banco=None, total preenchido',
        'Fase que nunca rodou não pode aparecer como se tivesse rodado (0.0 seria mentira, não é "instantâneo")',
        f'busca_api={relatorio.busca_api}, persistencia_no_banco={relatorio.persistencia_no_banco}, total={relatorio.total}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_relatorio_quando_erro_na_api_tem_busca_api_mas_nao_as_fases_seguintes(monkeypatch, tabela_resultados):
    # Setup: nunca sincronizado, API falha de verdade (erro de rede).
    _mockar_api(monkeypatch, excecao=ErroAPISysemp('erro de rede simulado'))

    # Exercise
    relatorio = sincronizar_impostos_entrada_xml()

    # Assert: a fase que rodou (busca_api) ficou registrada mesmo com o
    # retorno antecipado; as fases seguintes nunca chegaram a rodar.
    bateu = relatorio.busca_api is not None and relatorio.filtro_cfop is None and relatorio.total is not None
    registrar_resultado(
        tabela_resultados, 'relatorio_erro_na_api_tem_busca_api_mas_nao_seguintes',
        'ErroAPISysemp na busca', 'busca_api preenchido, filtro_cfop=None, total preenchido',
        'O tempo da fase que rodou não pode se perder no retorno antecipado — prova o cuidado com a ordem cronômetro/return',
        f'busca_api={relatorio.busca_api}, filtro_cfop={relatorio.filtro_cfop}, total={relatorio.total}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_informar_fase_e_chamado_em_ordem_pelas_fases_principais(monkeypatch, tabela_resultados):
    # Setup: 1 produto real, API devolve 1 nota válida. Captura as
    # mensagens de informar_fase numa lista, em ordem.
    _criar_produto('7900000000001')
    bruto = {'retorno': [_nota_com_item(**{'Código Barras': '7900000000001'})]}
    _mockar_api(monkeypatch, retorno=bruto)
    mensagens = []

    # Exercise
    sincronizar_impostos_entrada_xml(informar_fase=mensagens.append)

    # Assert: as 5 fases principais aparecem, em ordem, em alguma mensagem.
    termos_esperados = (
        'Buscando manifesto', 'Filtrando por CFOP', 'Selecionando a nota mais recente',
        'Persistindo no banco', 'concluída',
    )
    indices = [
        next((i for i, m in enumerate(mensagens) if termo in m), None) for termo in termos_esperados
    ]
    bateu = all(i is not None for i in indices) and indices == sorted(indices)
    registrar_resultado(
        tabela_resultados, 'informar_fase_chamado_em_ordem',
        '1 produto real, sincronização completa', f'{termos_esperados} aparecem em ordem',
        'Usuário rodando às cegas precisa ver em que fase está — sem isso, silêncio parece travamento',
        f'{mensagens}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_informar_fase_quando_nao_desatualizado_avisa_e_para(monkeypatch, tabela_resultados):
    # Setup: watermark sincronizado recentemente. API proibida.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()
    registro.registrar_sincronizacao_bem_sucedida(date(2026, 1, 1), date.today())
    monkeypatch.setattr(orquestrador, 'ApiSysemp', _api_proibida)
    mensagens = []

    # Exercise
    sincronizar_impostos_entrada_xml(informar_fase=mensagens.append)

    # Assert: só 1 mensagem, avisando que não há nada a fazer.
    bateu = len(mensagens) == 1 and 'nada a fazer' in mensagens[0]
    registrar_resultado(
        tabela_resultados, 'informar_fase_nao_desatualizado',
        'watermark dentro da margem, early return', '1 mensagem só, "nada a fazer"',
        'Não avisar nada aqui também deixaria o usuário sem saber se rodou ou não',
        f'{mensagens}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_informar_fase_quando_erro_na_api_avisa_o_motivo(monkeypatch, tabela_resultados):
    # Setup: nunca sincronizado, API falha de verdade.
    _mockar_api(monkeypatch, excecao=ErroAPISysemp('erro de rede simulado'))
    mensagens = []

    # Exercise
    sincronizar_impostos_entrada_xml(informar_fase=mensagens.append)

    # Assert: alguma mensagem menciona a falha e o motivo real.
    bateu = any('Falha na busca' in m and 'erro de rede simulado' in m for m in mensagens)
    registrar_resultado(
        tabela_resultados, 'informar_fase_erro_na_api',
        'ErroAPISysemp na busca', 'mensagem de falha com o motivo real',
        'Usuário precisa saber POR QUE falhou, não só que parou',
        f'{mensagens}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_progresso_de_pagina_e_repassado_para_informar_fase(monkeypatch, tabela_resultados):
    # Setup: 1 produto real, API simula 2 páginas antes de devolver o
    # resultado final.
    _criar_produto('7900000000001')
    bruto = {'retorno': [_nota_com_item(**{'Código Barras': '7900000000001'})]}
    _mockar_api(monkeypatch, retorno=bruto, paginas_simuladas=[(1, 100, 100), (2, 42, 142)])
    mensagens = []

    # Exercise
    sincronizar_impostos_entrada_xml(informar_fase=mensagens.append)

    # Assert: as 2 páginas simuladas aparecem como mensagem, com os
    # números certos.
    bateu = (
        any('página 1' in m and '142' not in m and '100' in m for m in mensagens)
        and any('página 2' in m and '142' in m for m in mensagens)
    )
    registrar_resultado(
        tabela_resultados, 'progresso_de_pagina_repassado',
        '2 páginas simuladas via ao_avancar_pagina', 'mensagens de página 1 e página 2, com os totais certos',
        'Sem isso, a fase mais lenta (busca paginada) fica muda de novo — mesmo bug que motivou essa rodada',
        f'{mensagens}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(monkeypatch, tabela_resultados):
    # Setup: valor esperado ERRADO de propósito.
    produto = _criar_produto('7900000000001')
    bruto = {'retorno': [_nota_com_item(**{'Código Barras': '7900000000001'})]}
    _mockar_api(monkeypatch, retorno=bruto)

    # Exercise
    sincronizar_impostos_entrada_xml()

    # Assert: compara contra o valor errado de propósito — tem que falhar.
    persistiu = ImpostosECustosXMLEntradaProduto.objects.filter(produto=produto).exists()
    registrar_resultado(
        tabela_resultados, 'caso_de_falha_proposital',
        f'persistiu={persistiu}', 'persistiu=False (errado de propósito)',
        'Propositalmente errado — prova que a tabela mostra FALHOU corretamente.',
        f'persistiu={persistiu}', persistiu is False,
    )
    assert persistiu is False

    # TearDown: nada a desmontar.

def test_forcar_ignora_guarda_e_busca_mesmo_com_watermark_fresco(monkeypatch, tabela_resultados):
    # Setup: mesmo cenário do teste acima (watermark sincronizado dentro
    # da margem, esta_desatualizada() é False) — mas chamando com
    # forcar=True. Desta vez a API é permitida (ao contrário do teste
    # acima), pra provar que ela FOI chamada mesmo assim.
    registro = SincronizacaoXmlManifestoNotaEntrada.obter()
    registro.registrar_sincronizacao_bem_sucedida(date(2026, 1, 1), date.today())
    bruto = {'retorno': []}
    _mockar_api(monkeypatch, retorno=bruto)

    # Exercise
    sincronizar_impostos_entrada_xml(forcar=True)

    # Assert: o bruto foi gravado — só acontece se a busca na API rodou
    # de verdade, provando que forcar=True atravessou a guarda de
    # esta_desatualizada() que bloqueou o teste anterior.
    bruto_existe = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_BRUTO) is not None
    registrar_resultado(
        tabela_resultados, 'forcar_ignora_guarda',
        'watermark sincronizado dentro da margem, forcar=True', 'busca na API acontece mesmo assim, bruto gravado',
        'forcar=True existe pra reconsultar sem esperar o prazo normal (achado real HIDROLIGHT, 19/08/2026)',
        f'bruto_existe={bruto_existe}', bruto_existe is True,
    )
    assert bruto_existe is True

    # TearDown: nada a desmontar.