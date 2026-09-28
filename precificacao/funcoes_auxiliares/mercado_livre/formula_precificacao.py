# precificacao/funcoes_auxiliares/mercado_livre/formula_precificacao.py

# Função Objetivo: Representa 1 margem candidata já resolvida, com auditoria completa.
# Explicação em detalhe: substitui calcular_preco_grade_ml/calcular_preco_com_frete_real —
# 1 objeto só, que "explode" a fórmula em métodos, guardando cada pedaço calculado. Usa
# DimensoesEfetivas (Variação ML ou fallback Produto ERP) em vez de ler o Produto direto,
# pra Coleta/Armazenagem/Frete sempre respeitarem a origem certa da dimensão. Reaproveita
# resolver_preco_por_margem (goal_seek.py) — nunca reimplementa a busca de faixa validada.
# 3 dataclasses (DadosEntrada/DadosIntermediarios/DadosSaida) guardam uma FOTO imutável —
# sem FK, sem objeto vivo — pronta pro modal de auditoria HTML, imune a bug de import
# futuro (o dado exibido é sempre o que a fórmula realmente usou naquele cálculo).
#
# Créditos fiscais de entrada (ICMS/IPI/PIS/COFINS) vêm prontos de impostos_entrada, via
# montar_creditos_fiscais_para_precificacao — já por unidade, já com o diferimento de ICMS
# ST resolvido internamente. Esta classe nunca reinterpreta esse valor, só consome.
#
# Mínima/Padrão/Máxima/Competição NÃO são subclasses — são a MESMA classe, instanciada 4
# vezes com margem_alvo_percentual diferente (dado diferente, não comportamento diferente).
#
# ProvaFiscalEntrada/peso_fisico+peso_cubico/armazenagem_valor_diario (10/09) — Camada 2 da
# tela de auditoria: nenhum dado NOVO no banco, só campos que a fórmula já calculava e
# descartava (o valor bruto da nota antes de dividir por unidade; os 2 pesos antes do
# max(); a taxa diária da faixa antes de multiplicar pelo período), agora fotografados
# junto pra a tela poder provar a conta em vez de só mostrar o resultado. Linhas calculadas
# ANTES dessa mudança não têm esses campos — passam None, e quem consome (Camada 3) precisa
# tratar como opcional.

from dataclasses import dataclass, asdict
from decimal import Decimal
from django.core.exceptions import ObjectDoesNotExist
from precificacao.funcoes_auxiliares.goal_seek import resolver_preco_por_margem, resolver_preco_com_frete_dinamico
from api_mercado_livre.core.estrutura_api.cliente_api import ErroAPI, ErroAutenticacaoAPI
from produtos.funcoes_auxiliares.dimensoes_fisicas import (
    metro_cubico_de_dimensoes, selecionar_faixa_por_dimensao,
)
from impostos.funcoes_auxiliares.entrada.creditos_fiscais_para_precificacao import (
    montar_creditos_fiscais_para_precificacao,
)


# Função Objetivo: 1 imposto de entrada, com o valor bruto da nota E a conta que gerou ele.
@dataclass
class ProvaImposto:
    valor: Decimal          # já como veio da nota — ainda NÃO dividido por unidade
    base_calculo: Decimal
    aliquota: Decimal


# Função Objetivo: Foto da nota fiscal de entrada, crua — prova de onde cada crédito vem.
# Explicação em detalhe: quantidade_nota é o divisor que transforma cada .valor daqui no
# "R$/unidade" que DadosIntermediarios usa (ex: ipi_valor = ipi.valor ÷ quantidade_nota).
# icms_st só vem preenchido quando tem_icms_st=True — nunca finge um ICMS ST que não existe.
@dataclass
class ProvaFiscalEntrada:
    quantidade_nota: Decimal
    tem_icms_st: bool
    ipi: ProvaImposto
    icms: ProvaImposto
    icms_st: ProvaImposto | None
    pis: ProvaImposto
    cofins: ProvaImposto


# Função Objetivo: Foto imutável de tudo que a fórmula consumiu.
@dataclass
class DadosEntrada:
    sku: str
    ean: str
    tipo_anuncio: str
    margem_alvo_percentual: Decimal

    custo: Decimal
    custo_com_boni: Decimal
    frete_cif_fob_percentual: Decimal
    icms_saida_percentual: Decimal
    pis_saida_percentual: Decimal
    cofins_saida_percentual: Decimal
    comissao_percentual: Decimal

    armazenagem_planilha: Decimal | None
    # * [EXPLICAÇÃO] → 'planilha_precificacao' ou 'erp_completo' — usa
    #                  armazenagem_planilha is not None como indicador
    #                  (única marca real que existe hoje; a planilha
    #                  roda por último e grava esse campo junto com o
    #                  resto dos fiscais/custo). Uso temporário, será
    #                  removido quando a planilha deixar de ser usada.
    origem_dados_fiscais: str

    altura: Decimal
    largura: Decimal
    comprimento: Decimal
    peso: Decimal
    origem_dimensao: str  # 'variacao_ml' ou 'produto_erp'
    # * [EXPLICAÇÃO] → None quando a origem é 'variacao_ml' e o vendedor
    #                  não declarou os 2 separados (não deveria acontecer,
    #                  já que dimensao_completa exige peso_declarado_kg —
    #                  mas nunca finge um valor que não foi resolvido).
    peso_fisico: Decimal | None
    peso_cubico: Decimal | None

    fator_coleta: Decimal
    periodo_armazenagem: Decimal

    rebate_percentual: Decimal
    preco_original: Decimal | None

    # * [EXPLICAÇÃO] → None só quando obter_creditos_fiscais() nunca achou
    #                  impostos_entrada (produto sem NF sincronizada) —
    #                  nesse caso a fórmula nem chega a resolver, então
    #                  na prática, se DadosEntrada existe, prova_fiscal
    #                  também existe.
    prova_fiscal: ProvaFiscalEntrada | None


# Função Objetivo: Cada pedaço calculado, passo a passo, com o par número/percentual.
@dataclass
class DadosIntermediarios:
    custo_final: Decimal
    ipi_valor: Decimal
    frete_cif_fob_valor: Decimal

    metro_cubico: Decimal
    coleta: Decimal

    armazenagem_origem: str  # 'planilha' ou 'faixa_dimensao'
    armazenagem: Decimal
    # * [EXPLICAÇÃO] → só existe quando armazenagem_origem='faixa_dimensao'
    #                  — armazenagem = valor_diario × periodo_armazenagem.
    #                  Na origem 'planilha' não tem taxa diária nenhuma
    #                  por trás (é 1 valor fixo já validado), fica None.
    armazenagem_valor_diario: Decimal | None

    credito_icms_entrada: Decimal
    credito_pis: Decimal
    credito_cofins: Decimal
    icms_saida_valor: Decimal
    pis_saida_valor: Decimal
    cofins_saida_valor: Decimal
    comissao_valor: Decimal

    fixo: Decimal
    taxa_percentual: Decimal
    taxa_valor: Decimal
    denominador: Decimal
    margem_alvo_valor: Decimal
    rebate_valor: Decimal

    faixa_frete_peso_min: Decimal
    faixa_frete_peso_max: Decimal | None
    faixa_frete_preco_min: Decimal
    faixa_frete_preco_max: Decimal | None
    preco_exato_antes_arredondar: Decimal


# Função Objetivo: O resultado final que a fórmula gerou.
@dataclass
class DadosSaida:
    preco_final: Decimal
    frete_usado: Decimal
    margem_valor: Decimal
    margem_percentual_obtida: Decimal
    # * [EXPLICAÇÃO] → Margem no PREÇO EXATO, antes do RoundUp90 —
    #                  diferente de margem_percentual_obtida (que é no
    #                  preço já arredondado). Pedido explícito de
    #                  auditoria: mostrar os 2 lado a lado no modal de
    #                  detalhe, pra deixar claro quanto o arredondamento
    #                  pra ",90" mexeu na margem real.
    margem_exata_percentual: Decimal
    margem_exata_valor: Decimal
    # * [EXPLICAÇÃO] → Pendência #1 (28/09/2026) — detalhamento CRU da
    #                  chamada de API que confirmou o frete usado no
    #                  cálculo (dict com billable_weight/discount_type/
    #                  discount_rate/discount_promoted_amount, do jeito
    #                  que a API devolveu). Só existe no caminho
    #                  'api_real' (origem_frete) — None na tabela, e
    #                  None também em linhas calculadas antes dessa
    #                  mudança.
    frete_detalhamento_api: dict | None = None


# Função Objetivo: Pacote dos dados fiscais/custo que só dependem do PRODUTO (créditos de
# entrada + custo final) — nunca do MLB, nunca da margem.
# Explicação em detalhe: Otimização Frente A (28/09/2026, checkpoint seção 20/21) — validado
# com script isolado, produto real de 44 MLBs: créditos fiscais e custo final são IDÊNTICOS
# entre qualquer MLB/margem/tipo do mesmo produto. Calculado 1x por produto (ver
# FormulaPrecificacao.resolver_dados_fiscais_produto) e reaproveitado por qualquer instância
# de FormulaPrecificacao desse produto, em vez de recalculado 4x à toa (1x por margem) —
# inclusive evita repetir a consulta ao banco (produto.impostos_entrada).
@dataclass
class DadosFiscaisProduto:
    impostos_entrada: object
    creditos: object
    custo_com_boni: Decimal
    frete_cif_fob_percentual: Decimal
    frete_cif_fob_valor: Decimal
    ipi_valor: Decimal
    custo_final: Decimal


# Função Objetivo: Pacote dos dados que só dependem da DIMENSÃO efetiva (mais o produto, só
# pra saber se ele tem armazenagem de planilha própria) — nunca da margem.
# Explicação em detalhe: Otimização Frente A (28/09/2026, checkpoint seção 20/21/22) — coleta,
# armazenagem (quando resolvida por faixa) e faixas de frete candidatas não mudam entre as 4
# margens de uma mesma assinatura (dimensão+categoria+tipo já usada como chave de
# cache_formulas em calcular_grade_precificacao_ml.py). Calculado 1x por assinatura (ver
# FormulaPrecificacao.resolver_dados_dimensao_frete) e reaproveitado pelas 4 instâncias de
# FormulaPrecificacao que resolvem essa assinatura, em vez de recalculado 4x à toa.
# ATENÇÃO: usa a mesma tupla de dimensão (mesma ordem altura/largura/comprimento) já usada
# como assinatura — nunca funde combinações com eixos em ordem diferente (ex: 13x25x30 com
# 25x30x13), porque selecionar_faixa_por_dimensao() compara cada eixo contra um teto
# diferente (max_altura/max_largura/max_profundidade) — ordem trocada pode cair em faixa de
# armazenagem errada. Ver checkpoint, seção 22.
@dataclass
class DadosDimensaoFrete:
    metro_cubico: Decimal
    coleta: Decimal
    armazenagem_origem: str
    armazenagem: Decimal
    armazenagem_valor_diario: Decimal | None
    faixas_candidatas: list


# Função Objetivo: Representa 1 margem candidata, já resolvida — mesma classe,
# instanciada 4x (Mínima/Padrão/Máxima/Competição) com margem_alvo_percentual diferente.
class FormulaPrecificacao:

    # Função Objetivo: Recebe tudo que precisa pra resolver essa margem.
    def __init__(self, produto, dimensoes_efetivas, config_tipo, config_geral,
                 margem_alvo_percentual, frete_todas, faixas_armazenagem=None,
                 rebate_percentual=None, preco_original=None, regime=None,
                 variacao=None, api_ml=None, dados_fiscais_produto=None,
                 dados_dimensao_frete=None):
        from mercado_livre.models import FreteML

        self.produto = produto
        self.dimensoes_efetivas = dimensoes_efetivas
        self.config_tipo = config_tipo
        self.config_geral = config_geral
        self.margem_alvo_percentual = Decimal(str(margem_alvo_percentual))
        self.frete_todas = frete_todas
        # * [EXPLICAÇÃO] → Qual das 2 tabelas reais de frete usar — ver
        #                  nota em calculo_margem.buscar_frete. Sem esse
        #                  parâmetro, usa SEM_FRETE_GRATIS_RAPIDO
        #                  (comportamento de sempre).
        self.regime = regime if regime is not None else FreteML.Regime.SEM_FRETE_GRATIS_RAPIDO
        self.faixas_armazenagem = faixas_armazenagem
        self.rebate_percentual = Decimal(str(rebate_percentual)) if rebate_percentual is not None else Decimal('0')
        self.preco_original = Decimal(str(preco_original)) if preco_original is not None else None

        # * [EXPLICAÇÃO] → Frente A (28/09/2026) — variacao/api_ml são o que permite
        #                  tentar o goal-seek via simulação de API antes da tabela. Os 2
        #                  são opcionais e None por padrão: quem chama sem eles (Hub de
        #                  Promoções, qualquer uso fora da Grade) continua 100% no
        #                  caminho da tabela, sem nenhuma mudança de comportamento.
        #                  variacao=None (linha fallback do produto) NUNCA tenta API —
        #                  decisão fechada no checkpoint, seção 19.
        self.variacao = variacao
        self.api_ml = api_ml
        self.origem_frete = None

        self.entrada = None
        self.intermediarios = None
        self.saida = None
        self.resolvida = False
        self._creditos = None
        self._impostos_entrada = None
        self._armazenagem_valor_diario = None
        # * [EXPLICAÇÃO] → Otimização Frente A (28/09/2026) — quando fornecido (ver
        #                  DadosFiscaisProduto/resolver_dados_fiscais_produto), pula a
        #                  consulta ao banco e o cálculo de custo final em
        #                  obter_creditos_fiscais()/calcular_custo_final(), reaproveitando
        #                  o que já foi calculado 1x pra esse produto. None (padrão) =
        #                  comportamento de sempre, sem nenhuma mudança.
        self._dados_fiscais_produto = dados_fiscais_produto
        # * [EXPLICAÇÃO] → Mesma lógica acima, pro pacote de dimensão (ver
        #                  DadosDimensaoFrete/resolver_dados_dimensao_frete) — pula
        #                  calcular_coleta()/calcular_armazenagem()/filtrar_faixas_frete()
        #                  quando já foi resolvido 1x pra essa assinatura.
        self._dados_dimensao_frete = dados_dimensao_frete

    # Função Objetivo: Busca os créditos fiscais de entrada, já resolvidos e por unidade.
    def obter_creditos_fiscais(self):
        if self._dados_fiscais_produto is not None:
            self._impostos_entrada = self._dados_fiscais_produto.impostos_entrada
            self._creditos = self._dados_fiscais_produto.creditos
            return

        try:
            impostos_entrada = self.produto.impostos_entrada
        except ObjectDoesNotExist:
            self._creditos = None
            return

        # * [EXPLICAÇÃO] → Guarda o objeto CRU (10/09) — não só o crédito
        #                  já dividido por unidade. É a prova que a tela
        #                  de auditoria usa pra mostrar "valor da nota ÷
        #                  quantidade", não só o resultado já pronto.
        self._impostos_entrada = impostos_entrada

        creditos = montar_creditos_fiscais_para_precificacao(impostos_entrada)

        # * [EXPLICAÇÃO] → Sem quantidade_nota (ou qualquer outro dado
        #                  fiscal ausente), nenhum dos 4 créditos existe
        #                  — produto não precifica, nunca finge um
        #                  crédito parcial. Decisão: sem fallback.
        if None in (creditos.icms, creditos.ipi, creditos.pis, creditos.cofins):
            self._creditos = None
            return

        self._creditos = creditos

    # Função Objetivo: Calcula o custo final (IPI + frete CIF/FOB, sobre o custo).
    def calcular_custo_final(self):
        if self._dados_fiscais_produto is not None:
            d = self._dados_fiscais_produto
            self._custo_com_boni = d.custo_com_boni
            self._frete_cif_fob_percentual = d.frete_cif_fob_percentual
            self._frete_cif_fob_valor = d.frete_cif_fob_valor
            self._ipi_valor = d.ipi_valor
            self._custo_final = d.custo_final
            return

        produto = self.produto
        frete_cif_fob_percentual = produto.frete_cif_fob or Decimal('0')

        # IPI já vem em R$ pronto (dividido por unidade em impostos_entrada) —
        # nunca recalculado aqui a partir de percentual.
        ipi_valor = self._creditos.ipi
        frete_cif_fob_valor = produto.custo * (frete_cif_fob_percentual / 100)

        # Decisão do Matheus (14/09/2026): custo_com_boni nunca é preenchido na
        # prática (nenhum importador/script grava valor ali) — parou de ser lido.
        # self._custo_com_boni continua existindo só pelo nome (usado pela
        # auditoria/modal), mas agora É produto.custo, sem fallback nenhum.
        self._custo_com_boni = produto.custo
        self._frete_cif_fob_percentual = frete_cif_fob_percentual
        self._frete_cif_fob_valor = frete_cif_fob_valor
        self._ipi_valor = ipi_valor
        self._custo_final = produto.custo + ipi_valor + frete_cif_fob_valor

    # Função Objetivo: Calcula 1x os dados fiscais/custo que só dependem do PRODUTO —
    # créditos de entrada + custo final — reaproveitáveis por QUALQUER MLB/margem/tipo
    # desse produto (ver DadosFiscaisProduto). Devolve None nos mesmos casos em que
    # obter_creditos_fiscais() zeraria os créditos (produto sem nota fiscal sincronizada,
    # ou créditos incompletos) — quem chama trata None como "sem precomputado", e cada
    # FormulaPrecificacao cai no caminho de sempre (consulta o banco ela mesma).
    @classmethod
    def resolver_dados_fiscais_produto(cls, produto):
        instancia = cls(
            produto=produto, dimensoes_efetivas=None, config_tipo=None, config_geral=None,
            margem_alvo_percentual=Decimal('0'), frete_todas=None,
        )
        instancia.obter_creditos_fiscais()
        if instancia._creditos is None:
            return None
        instancia.calcular_custo_final()
        return DadosFiscaisProduto(
            impostos_entrada=instancia._impostos_entrada,
            creditos=instancia._creditos,
            custo_com_boni=instancia._custo_com_boni,
            frete_cif_fob_percentual=instancia._frete_cif_fob_percentual,
            frete_cif_fob_valor=instancia._frete_cif_fob_valor,
            ipi_valor=instancia._ipi_valor,
            custo_final=instancia._custo_final,
        )

    # Função Objetivo: Calcula a coleta a partir do metro cúbico do DimensoesEfetivas.
    def calcular_coleta(self):
        if self._dados_dimensao_frete is not None:
            self._metro_cubico = self._dados_dimensao_frete.metro_cubico
            self._coleta = self._dados_dimensao_frete.coleta
            return

        dim = self.dimensoes_efetivas
        self._metro_cubico = metro_cubico_de_dimensoes(dim.altura, dim.largura, dim.comprimento)
        self._coleta = self._metro_cubico * self.config_geral.fator_coleta

    # Função Objetivo: Calcula a armazenagem — planilha se existir, senão faixa por dimensão.
    def calcular_armazenagem(self):
        if self._dados_dimensao_frete is not None:
            d = self._dados_dimensao_frete
            self._armazenagem_origem = d.armazenagem_origem
            self._armazenagem = d.armazenagem
            self._armazenagem_valor_diario = d.armazenagem_valor_diario
            return

        produto = self.produto
        dim = self.dimensoes_efetivas

        if produto.armazenagem_planilha is not None:
            self._armazenagem_origem = 'planilha'
            self._armazenagem = produto.armazenagem_planilha
            self._armazenagem_valor_diario = None
            return

        if self.faixas_armazenagem is not None:
            faixas = self.faixas_armazenagem
        else:
            from precificacao.models import FaixaArmazenagem
            faixas = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))

        faixa_usada = selecionar_faixa_por_dimensao(dim.altura, dim.largura, dim.comprimento, faixas)
        self._armazenagem_origem = 'faixa_dimensao'
        self._armazenagem_valor_diario = faixa_usada.valor_diario if faixa_usada else None
        self._armazenagem = (faixa_usada.valor_diario * self.config_geral.periodo_armazenagem) if faixa_usada else Decimal('0')

    # Função Objetivo: Soma os 3 pedaços do FIXO e desconta os créditos de ICMS/PIS/COFINS.
    def calcular_fixo(self):
        creditos = self._creditos

        # * [EXPLICAÇÃO] → creditos.icms já vem certo pra qualquer
        #                  regime (líquido do ST quando o produto é
        #                  ST, normal quando não é) — nunca soma os 2.
        self._credito_icms_entrada = creditos.icms
        self._credito_pis = creditos.pis
        self._credito_cofins = creditos.cofins

        self._fixo = self._coleta + self._armazenagem + self._custo_final - (
            self._credito_icms_entrada + self._credito_pis + self._credito_cofins
        )

    # Função Objetivo: Monta a taxa (comissão + ICMS saída + PIS + COFINS) e o denominador da meta.
    def montar_taxa_e_denominador(self):
        produto = self.produto
        self._comissao_percentual = self.config_tipo.comissao
        self._icms_saida_percentual = produto.icms_saida_media or Decimal('0')
        self._pis_saida_percentual = produto.pis_percentual or Decimal('0')
        self._cofins_saida_percentual = produto.cofins_percentual or Decimal('0')

        self._taxa_percentual = (
            self._comissao_percentual + self._icms_saida_percentual
            + self._pis_saida_percentual + self._cofins_saida_percentual
        ) / 100
        self._denominador = Decimal('1') - self._taxa_percentual - (self.margem_alvo_percentual / 100)

        if self.rebate_percentual and self.preco_original:
            self._rebate_valor = self.preco_original * (self.rebate_percentual / 100)
        else:
            self._rebate_valor = Decimal('0')

    # Função Objetivo: Filtra as faixas de frete candidatas pelo peso do DimensoesEfetivas
    # e pelo regime desta instância (Sem/Com Frete Grátis Rápido).
    def filtrar_faixas_frete(self):
        if self._dados_dimensao_frete is not None:
            self._faixas_candidatas = self._dados_dimensao_frete.faixas_candidatas
            return

        peso = self.dimensoes_efetivas.peso
        self._faixas_candidatas = sorted(
            (
                f for f in self.frete_todas
                if f.regime == self.regime and f.peso_min <= peso and (f.peso_max is None or f.peso_max >= peso)
            ),
            key=lambda f: f.preco_min,
        )

    # Função Objetivo: Calcula 1x os dados que só dependem da DIMENSÃO efetiva (coleta,
    # armazenagem, faixas de frete candidatas) — reaproveitáveis pelas 4 margens de uma
    # mesma assinatura (dimensão+categoria+tipo). Nunca funde assinaturas diferentes — quem
    # chama já garante que dimensoes_efetivas é exatamente a mesma tupla usada como chave
    # de cache em calcular_grade_precificacao_ml.py.
    @classmethod
    def resolver_dados_dimensao_frete(cls, produto, dimensoes_efetivas, config_geral,
                                       frete_todas, faixas_armazenagem=None, regime=None):
        instancia = cls(
            produto=produto, dimensoes_efetivas=dimensoes_efetivas, config_tipo=None,
            config_geral=config_geral, margem_alvo_percentual=Decimal('0'),
            frete_todas=frete_todas, faixas_armazenagem=faixas_armazenagem, regime=regime,
        )
        instancia.calcular_coleta()
        instancia.calcular_armazenagem()
        instancia.filtrar_faixas_frete()
        return DadosDimensaoFrete(
            metro_cubico=instancia._metro_cubico,
            coleta=instancia._coleta,
            armazenagem_origem=instancia._armazenagem_origem,
            armazenagem=instancia._armazenagem,
            armazenagem_valor_diario=instancia._armazenagem_valor_diario,
            faixas_candidatas=instancia._faixas_candidatas,
        )

    # Função Objetivo: Monta a string de dimensão no formato que a API espera ("AxLxCcm,pesoEmGramas").
    # Explicação em detalhe: mesma receita validada em scripts_exploracao_ML/
    # buscar_e_testar_candidatos_diversos_frete_via_api.py (_formatar_dimensao) — usa
    # peso_fisico (não o faturável), a própria API calcula o peso cúbico a partir da
    # dimensão crua.
    @staticmethod
    def _formatar_numero_dimensao(valor):
        inteiro = valor.to_integral_value()
        if valor == inteiro:
            return str(int(inteiro))
        return str(valor.normalize())

    def _montar_dimensions_str(self):
        dim = self.dimensoes_efetivas
        f = self._formatar_numero_dimensao
        peso_gramas = int((dim.peso_fisico * 1000).to_integral_value())
        return f'{f(dim.altura)}x{f(dim.largura)}x{f(dim.comprimento)},{peso_gramas}'

    # Função Objetivo: Tenta o goal-seek via simulação de API — só quando a linha tem MLB
    # publicado com categoria conhecida (autocontido daquele MLB, ver checkpoint seção 19).
    # Explicação em detalhe: devolve None (nunca lança) em qualquer falha — sem MLB, sem
    # categoria, ou erro/timeout da API — pra resolver_preco() sempre poder cair no
    # fallback da tabela sem se importar com o motivo.
    def _tentar_resolver_preco_via_api(self, custo_produto):
        if self.variacao is None or self.api_ml is None:
            return None

        categoria = getattr(self.variacao, 'categoria', None)
        if categoria is None:
            return None

        dimensions_str = self._montar_dimensions_str()
        category_id = categoria.category_id
        listing_type_id = self.config_tipo.tipo_anuncio
        api_ml = self.api_ml

        def consultar_frete(item_price):
            try:
                valor, detalhamento = api_ml.simular_frete(
                    dimensions_str, item_price, category_id, listing_type_id, free_shipping=False,
                )
            except (ErroAPI, ErroAutenticacaoAPI):
                return None
            return valor, detalhamento

        return resolver_preco_com_frete_dinamico(
            fixo=self._fixo,
            taxa_percentual=self._taxa_percentual,
            margem_alvo_fracao=self.margem_alvo_percentual / 100,
            custo_produto=custo_produto,
            faixas_preco_candidatas=self._faixas_candidatas,
            consultar_frete=consultar_frete,
            rebate_valor=self._rebate_valor,
        )

    # Função Objetivo: Resolve o preço — tenta a API primeiro (Frente A), tabela como fallback.
    def resolver_preco(self):
        # Decisão do Matheus (14/09/2026): custo_com_boni nunca é preenchido na
        # prática — parou de ser lido em qualquer parte da fórmula.
        custo_produto = self.produto.custo

        # * [EXPLICAÇÃO] → Frente A (28/09/2026, checkpoint seção 19): só 1 frete por
        #                  linha, nunca 2 campos. Tenta o goal-seek completo via API; se
        #                  falhar em qualquer chamada (ou a linha não for elegível), cai
        #                  pro goal-seek completo via tabela — o mesmo de sempre, sem
        #                  nenhuma mudança. origem_frete registra qual dos 2 resolveu.
        resultado = self._tentar_resolver_preco_via_api(custo_produto)
        if resultado is not None:
            self.origem_frete = 'api_real'
        else:
            resultado = resolver_preco_por_margem(
                fixo=self._fixo,
                taxa_percentual=self._taxa_percentual,
                margem_alvo_fracao=self.margem_alvo_percentual / 100,
                custo_produto=custo_produto,
                faixas_frete_candidatas=self._faixas_candidatas,
                rebate_valor=self._rebate_valor,
            )
            self.origem_frete = 'tabela_calculada'

        if resultado is None:
            self.resolvida = False
            return

        self.resolvida = True
        detalhamento = resultado['detalhamento']
        faixa_frete_obj = resultado['faixa_frete']

        self._preco_final = resultado['preco_calculado']
        self._frete_usado = resultado['frete_usado']
        self._margem_valor = detalhamento['margem_valor']
        self._margem_percentual_obtida = resultado['margem_percentual_obtida']
        self._preco_exato_antes_arredondar = detalhamento['preco_exato_antes_arredondar']
        # * [EXPLICAÇÃO] → Pendência #1 (28/09/2026) — só existe quando
        #                  origem_frete='api_real' (resolver_preco_por_margem,
        #                  caminho tabela, nunca coloca essa chave no dict).
        #                  .get() devolve None no caminho tabela, sem exceção.
        self._frete_detalhamento_api = detalhamento.get('frete_detalhamento_api')

        # * [EXPLICAÇÃO] → Mesma fórmula de margem, só que aplicada no
        #                  preço EXATO (antes do RoundUp90) — nunca
        #                  recalculada depois, sempre persistida junto
        #                  com o resto (nunca ao vivo no modal).
        self._margem_exata_valor = (
            self._preco_exato_antes_arredondar * (1 - self._taxa_percentual)
            - self._fixo - self._frete_usado + self._rebate_valor
        )
        self._margem_exata_percentual = (self._margem_exata_valor / self._preco_exato_antes_arredondar) * 100

        # * [EXPLICAÇÃO] → Snapshot dos limites da faixa escolhida — NUNCA
        #                  guarda o objeto FreteML em si (isso seria FK
        #                  disfarçada). Só os 4 números que ele tinha
        #                  naquele instante.
        self._faixa_frete_peso_min = faixa_frete_obj.peso_min
        self._faixa_frete_peso_max = faixa_frete_obj.peso_max
        self._faixa_frete_preco_min = faixa_frete_obj.preco_min
        self._faixa_frete_preco_max = faixa_frete_obj.preco_max

        self._comissao_valor = self._preco_final * self._comissao_percentual / 100
        self._icms_saida_valor = self._preco_final * self._icms_saida_percentual / 100
        self._pis_saida_valor = self._preco_final * self._pis_saida_percentual / 100
        self._cofins_saida_valor = self._preco_final * self._cofins_saida_percentual / 100
        self._taxa_valor = self._preco_final * self._taxa_percentual
        self._margem_alvo_valor = self._preco_final * (self.margem_alvo_percentual / 100)

    # Função Objetivo: Roda todos os passos acima, na ordem certa, e monta as 3 dataclasses.
    def calcular(self):
        self.obter_creditos_fiscais()
        if self._creditos is None:
            self.resolvida = False
            return self

        self.calcular_custo_final()
        self.calcular_coleta()
        self.calcular_armazenagem()
        self.calcular_fixo()
        self.montar_taxa_e_denominador()
        self.filtrar_faixas_frete()
        self.resolver_preco()

        if not self.resolvida:
            return self

        self._montar_dados_entrada()
        self._montar_dados_intermediarios()
        self._montar_dados_saida()
        return self

    # Função Objetivo: Monta a foto crua da nota fiscal — a prova por trás dos créditos.
    # Explicação em detalhe: mesma checagem de tem_icms_st que _produto_tem_icms_st (em
    # impostos/funcoes_auxiliares/creditos_fiscais_para_precificacao.py) — reimplementada
    # aqui de propósito (é uma função privada daquele módulo, não pensada pra ser
    # importada) em vez de reaproveitada; se a regra mudar lá, precisa mudar aqui junto.
    def _montar_prova_fiscal(self):
        ie = self._impostos_entrada
        if ie is None:
            return None

        tem_st = ie.icms_st.valor > 0 or ie.icms_st.base_calculo > 0

        return ProvaFiscalEntrada(
            quantidade_nota=ie.quantidade_nota,
            tem_icms_st=tem_st,
            ipi=ProvaImposto(valor=ie.ipi.valor, base_calculo=ie.ipi.base_calculo, aliquota=ie.ipi.aliquota),
            icms=ProvaImposto(valor=ie.icms.valor, base_calculo=ie.icms.base_calculo, aliquota=ie.icms.aliquota),
            icms_st=ProvaImposto(
                valor=ie.icms_st.valor, base_calculo=ie.icms_st.base_calculo, aliquota=ie.icms_st.aliquota,
            ) if tem_st else None,
            pis=ProvaImposto(valor=ie.pis.valor, base_calculo=ie.pis.base_calculo, aliquota=ie.pis.aliquota),
            cofins=ProvaImposto(valor=ie.cofins.valor, base_calculo=ie.cofins.base_calculo, aliquota=ie.cofins.aliquota),
        )

    # Função Objetivo: Monta a foto imutável de tudo que foi consumido.
    def _montar_dados_entrada(self):
        produto = self.produto
        dim = self.dimensoes_efetivas
        self.entrada = DadosEntrada(
            sku=produto.sku,
            ean=produto.ean,
            tipo_anuncio=self.config_tipo.get_tipo_anuncio_display(),
            margem_alvo_percentual=self.margem_alvo_percentual,
            custo=produto.custo,
            custo_com_boni=self._custo_com_boni,
            frete_cif_fob_percentual=self._frete_cif_fob_percentual,
            icms_saida_percentual=self._icms_saida_percentual,
            pis_saida_percentual=self._pis_saida_percentual,
            cofins_saida_percentual=self._cofins_saida_percentual,
            comissao_percentual=self._comissao_percentual,
            armazenagem_planilha=produto.armazenagem_planilha,
            origem_dados_fiscais=(
                'planilha_precificacao' if produto.armazenagem_planilha is not None else 'erp_completo'
            ),
            altura=dim.altura,
            largura=dim.largura,
            comprimento=dim.comprimento,
            peso=dim.peso,
            origem_dimensao=dim.origem.value,
            peso_fisico=dim.peso_fisico,
            peso_cubico=dim.peso_cubico,
            fator_coleta=self.config_geral.fator_coleta,
            periodo_armazenagem=self.config_geral.periodo_armazenagem,
            rebate_percentual=self.rebate_percentual,
            preco_original=self.preco_original,
            prova_fiscal=self._montar_prova_fiscal(),
        )

    # Função Objetivo: Monta cada pedaço calculado, passo a passo.
    def _montar_dados_intermediarios(self):
        self.intermediarios = DadosIntermediarios(
            custo_final=self._custo_final,
            ipi_valor=self._ipi_valor,
            frete_cif_fob_valor=self._frete_cif_fob_valor,
            metro_cubico=self._metro_cubico,
            coleta=self._coleta,
            armazenagem_origem=self._armazenagem_origem,
            armazenagem=self._armazenagem,
            armazenagem_valor_diario=self._armazenagem_valor_diario,
            credito_icms_entrada=self._credito_icms_entrada,
            credito_pis=self._credito_pis,
            credito_cofins=self._credito_cofins,
            icms_saida_valor=self._icms_saida_valor,
            pis_saida_valor=self._pis_saida_valor,
            cofins_saida_valor=self._cofins_saida_valor,
            comissao_valor=self._comissao_valor,
            fixo=self._fixo,
            taxa_percentual=self._taxa_percentual * 100,
            taxa_valor=self._taxa_valor,
            denominador=self._denominador,
            margem_alvo_valor=self._margem_alvo_valor,
            rebate_valor=self._rebate_valor,
            faixa_frete_peso_min=self._faixa_frete_peso_min,
            faixa_frete_peso_max=self._faixa_frete_peso_max,
            faixa_frete_preco_min=self._faixa_frete_preco_min,
            faixa_frete_preco_max=self._faixa_frete_preco_max,
            preco_exato_antes_arredondar=self._preco_exato_antes_arredondar,
        )

    # Função Objetivo: Monta o resultado final que a fórmula gerou.
    def _montar_dados_saida(self):
        self.saida = DadosSaida(
            preco_final=self._preco_final,
            frete_usado=self._frete_usado,
            margem_valor=self._margem_valor,
            margem_percentual_obtida=self._margem_percentual_obtida,
            margem_exata_percentual=self._margem_exata_percentual,
            margem_exata_valor=self._margem_exata_valor,
            frete_detalhamento_api=self._frete_detalhamento_api,
        )

    # Função Objetivo: Devolve a fórmula em forma abstrata, sem números.
    def formula_abstrata(self):
        return 'preço = (frete + FIXO − rebate) ÷ (1 − taxa − margem-alvo)'

    # Função Objetivo: Devolve a fórmula com os números reais já preenchidos.
    def formula_preenchida(self):
        i = self.intermediarios
        s = self.saida
        return (
            f'preço = (R$ {s.frete_usado} + R$ {i.fixo} − R$ {i.rebate_valor}) '
            f'÷ {i.denominador} = R$ {s.preco_final}'
        )

    # Função Objetivo: Devolve o passo a passo ordenado, pronto pro modal de auditoria.
    def passos(self):
        e = self.entrada
        i = self.intermediarios
        s = self.saida
        return [
            {'ordem': 1, 'rotulo': 'Custo final', 'formula': 'custo_com_boni + IPI + frete CIF/FOB', 'resultado': i.custo_final},
            {'ordem': 2, 'rotulo': 'Coleta', 'formula': 'metro_cúbico × fator_coleta', 'resultado': i.coleta},
            {'ordem': 3, 'rotulo': 'Armazenagem', 'formula': f'origem: {i.armazenagem_origem}', 'resultado': i.armazenagem},
            {'ordem': 4, 'rotulo': 'FIXO', 'formula': 'coleta + armazenagem + custo_final − créditos', 'resultado': i.fixo},
            {'ordem': 5, 'rotulo': 'Taxa', 'formula': 'comissão + ICMS saída + PIS + COFINS', 'resultado': i.taxa_percentual},
            {'ordem': 6, 'rotulo': 'Denominador', 'formula': '1 − taxa − margem-alvo', 'resultado': i.denominador},
            {'ordem': 7, 'rotulo': 'Faixa de frete escolhida', 'formula': f'peso {e.peso}kg, faixa R$ {i.faixa_frete_preco_min}–{i.faixa_frete_preco_max}', 'resultado': s.frete_usado},
            {'ordem': 8, 'rotulo': 'Preço exato', 'formula': '(frete + FIXO − rebate) ÷ denominador', 'resultado': i.preco_exato_antes_arredondar},
            {'ordem': 9, 'rotulo': 'Preço final (arredondado ,90)', 'formula': 'RoundUp90 — sempre pra CIMA', 'resultado': s.preco_final},
            {'ordem': 10, 'rotulo': 'Margem obtida', 'formula': 'preço×(1−taxa) − FIXO − frete + rebate', 'resultado': s.margem_percentual_obtida},
        ]

    # Função Objetivo: Devolve as 3 dataclasses já serializadas, prontas pro JSONField.
    def para_dict_auditoria(self):
        return {
            'entrada': asdict(self.entrada),
            'intermediarios': asdict(self.intermediarios),
            'saida': asdict(self.saida),
            'passos': self.passos(),
        }