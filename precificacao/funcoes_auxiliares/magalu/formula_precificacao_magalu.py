# precificacao/funcoes_auxiliares/magalu/formula_precificacao_magalu.py

# Função Objetivo: Representa 1 margem candidata do Magalu já resolvida, com auditoria.
# Explicação em detalhe: espelha FormulaPrecificacao (ML), mas SEM DimensoesEfetivas —
# Magalu não tem "declarado na plataforma" (sem pipeline de anúncio ainda), só o
# fallback do Produto ERP, resolvido direto aqui. SEM busca de faixa de preço — o frete
# do Magalu é peso × faixa de reputação, direto (resolver_preco_com_frete_fixo do
# goal_seek genérico, nunca usado até agora). SEM rebate (confirmado: não existe
# conceito parecido no Magalu hoje). Zero import de mercado_livre — app independente.
#
# Créditos fiscais de entrada (ICMS/IPI/PIS/COFINS) vêm prontos de impostos_entrada, via
# montar_creditos_fiscais_para_precificacao — já por unidade, já com o diferimento de ICMS
# ST resolvido internamente. Esta classe nunca reinterpreta esse valor, só consome.

from dataclasses import dataclass, asdict
from decimal import Decimal
from django.core.exceptions import ObjectDoesNotExist
from precificacao.funcoes_auxiliares.goal_seek import resolver_preco_com_frete_fixo
from produtos.funcoes_auxiliares.dimensoes_fisicas import (
    metro_cubico_de_dimensoes, selecionar_faixa_por_dimensao, resolver_dimensao_produto,
)
from impostos.funcoes_auxiliares.creditos_fiscais_para_precificacao import (
    montar_creditos_fiscais_para_precificacao,
)


# Função Objetivo: Foto imutável de tudo que a fórmula consumiu.
@dataclass
class DadosEntrada:
    sku: str
    ean: str
    margem_alvo_percentual: Decimal

    custo: Decimal
    custo_com_boni: Decimal
    frete_cif_fob_percentual: Decimal
    icms_saida_percentual: Decimal
    pis_saida_percentual: Decimal
    cofins_saida_percentual: Decimal
    comissao_percentual: Decimal

    armazenagem_planilha: Decimal | None
    origem_dados_fiscais: str  # 'planilha_precificacao' ou 'erp_completo'

    altura: Decimal
    largura: Decimal
    comprimento: Decimal
    peso: Decimal
    # * [EXPLICAÇÃO] → Sempre 'produto_erp' — Magalu não tem conceito de
    #                  "declarado na plataforma" (sem pipeline de anúncio
    #                  ainda). Campo mantido, mesmo nome do ML, pra manter
    #                  a mesma estrutura de auditoria — só o valor nunca varia.
    origem_dimensao: str

    fator_coleta: Decimal
    periodo_armazenagem: Decimal

    faixa_reputacao: str  # 'baixa'/'media'/'alta' — define a coluna de frete usada
    taxa_unidade_fixa: Decimal  # taxa fixa em R$ por unidade vendida — independente do preço


# Função Objetivo: Cada pedaço calculado, passo a passo, com o par número/percentual.
@dataclass
class DadosIntermediarios:
    custo_final: Decimal
    ipi_valor: Decimal
    frete_cif_fob_valor: Decimal

    metro_cubico: Decimal
    coleta: Decimal

    armazenagem_origem: str
    armazenagem: Decimal

    credito_icms_entrada: Decimal
    credito_pis: Decimal
    credito_cofins: Decimal
    pis_saida_valor: Decimal
    cofins_saida_valor: Decimal
    icms_saida_valor: Decimal
    comissao_valor: Decimal

    fixo: Decimal
    taxa_percentual: Decimal
    taxa_valor: Decimal
    denominador: Decimal
    margem_alvo_valor: Decimal

    faixa_frete_peso_min: Decimal
    faixa_frete_peso_max: Decimal | None
    preco_exato_antes_arredondar: Decimal


# Função Objetivo: O resultado final que a fórmula gerou.
@dataclass
class DadosSaida:
    preco_final: Decimal
    frete_usado: Decimal
    margem_valor: Decimal
    margem_percentual_obtida: Decimal
    margem_exata_percentual: Decimal
    margem_exata_valor: Decimal


# Função Objetivo: Representa 1 margem candidata do Magalu, já resolvida — mesma
# classe, instanciada 4x (Mínima/Padrão/Máxima/Competição) com margem_alvo diferente.
class FormulaPrecificacaoMagalu:

    # Função Objetivo: Recebe tudo que precisa pra resolver essa margem.
    def __init__(self, produto, config_magalu, config_geral,
                 margem_alvo_percentual, frete_todas, faixas_armazenagem=None):
        self.produto = produto
        self.config_magalu = config_magalu
        self.config_geral = config_geral
        self.margem_alvo_percentual = Decimal(str(margem_alvo_percentual))
        self.frete_todas = frete_todas
        self.faixas_armazenagem = faixas_armazenagem

        self.entrada = None
        self.intermediarios = None
        self.saida = None
        self.resolvida = False
        self._creditos = None

    # Função Objetivo: Resolve a dimensão direto do Produto — sem DimensoesEfetivas.
    # Explicação em detalhe: peso efetivo = maior entre físico e cúbico (mesma regra do
    # ML, confirmada na planilha do Magalu via fórmula MAIOR($T4:$U4;1)).
    def resolver_dimensao(self):
        self._altura, self._largura, self._comprimento, self._peso = resolver_dimensao_produto(self.produto)

    # Função Objetivo: Busca os créditos fiscais de entrada, já resolvidos e por unidade.
    def obter_creditos_fiscais(self):
        try:
            impostos_entrada = self.produto.impostos_entrada
        except ObjectDoesNotExist:
            self._creditos = None
            return

        creditos = montar_creditos_fiscais_para_precificacao(impostos_entrada)

        # Sem quantidade_nota (ou qualquer outro dado fiscal ausente),
        # nenhum dos 4 créditos existe — produto não precifica, nunca
        # finge um crédito parcial. Decisão: sem fallback.
        if None in (creditos.icms, creditos.ipi, creditos.pis, creditos.cofins):
            self._creditos = None
            return

        self._creditos = creditos

    # Função Objetivo: Calcula o custo final (custo com boni + IPI + frete CIF/FOB).
    def calcular_custo_final(self):
        produto = self.produto
        custo_com_boni = produto.custo_com_boni or produto.custo
        frete_cif_fob_percentual = produto.frete_cif_fob or Decimal('0')

        # IPI já vem em R$ pronto (dividido por unidade em impostos_entrada) —
        # nunca recalculado aqui a partir de percentual.
        ipi_valor = self._creditos.ipi
        frete_cif_fob_valor = custo_com_boni * (frete_cif_fob_percentual / 100)

        self._custo_com_boni = custo_com_boni
        self._frete_cif_fob_percentual = frete_cif_fob_percentual
        self._frete_cif_fob_valor = frete_cif_fob_valor
        self._ipi_valor = ipi_valor
        self._custo_final = custo_com_boni + ipi_valor + frete_cif_fob_valor

    # Função Objetivo: Calcula a coleta a partir do metro cúbico da dimensão resolvida.
    def calcular_coleta(self):
        self._metro_cubico = metro_cubico_de_dimensoes(self._altura, self._largura, self._comprimento)
        self._coleta = self._metro_cubico * self.config_geral.fator_coleta

    # Função Objetivo: Calcula a armazenagem — planilha se existir, senão faixa por dimensão.
    def calcular_armazenagem(self):
        produto = self.produto

        if produto.armazenagem_planilha is not None:
            self._armazenagem_origem = 'planilha'
            self._armazenagem = produto.armazenagem_planilha
            return

        if self.faixas_armazenagem is not None:
            faixas = self.faixas_armazenagem
        else:
            from precificacao.models import FaixaArmazenagem
            faixas = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))

        faixa_usada = selecionar_faixa_por_dimensao(self._altura, self._largura, self._comprimento, faixas)
        self._armazenagem_origem = 'faixa_dimensao'
        self._armazenagem = (faixa_usada.valor_diario * self.config_geral.periodo_armazenagem) if faixa_usada else Decimal('0')

    # Função Objetivo: Soma os 3 pedaços do FIXO e desconta os créditos de ICMS/PIS/COFINS.
    def calcular_fixo(self):
        creditos = self._creditos

        # creditos.icms já vem certo pra qualquer regime (líquido do
        # ST quando o produto é ST, normal quando não é) — nunca soma os 2.
        self._credito_icms_entrada = creditos.icms
        self._credito_pis = creditos.pis
        self._credito_cofins = creditos.cofins

        self._fixo = self._coleta + self._armazenagem + self._custo_final - (
            self._credito_icms_entrada + self._credito_pis + self._credito_cofins
        )

    # Função Objetivo: Monta a taxa (comissão Magalu + ICMS saída + PIS + COFINS) e o denominador.
    def montar_taxa_e_denominador(self):
        produto = self.produto
        self._comissao_percentual = self.config_magalu.comissao_percentual
        self._icms_saida_percentual = produto.icms_saida_media or Decimal('0')
        self._pis_saida_percentual = produto.pis_percentual or Decimal('0')
        self._cofins_saida_percentual = produto.cofins_percentual or Decimal('0')

        self._taxa_percentual = (
            self._comissao_percentual + self._icms_saida_percentual
            + self._pis_saida_percentual + self._cofins_saida_percentual
        ) / 100
        self._denominador = Decimal('1') - self._taxa_percentual - (self.margem_alvo_percentual / 100)

    # Função Objetivo: Busca direto a faixa de frete certa por peso — sem busca de preço.
    def buscar_faixa_frete(self):
        peso = self._peso
        self._faixa_frete = next(
            (f for f in self.frete_todas if f.peso_min <= peso and (f.peso_max is None or f.peso_max >= peso)),
            None,
        )

    # Função Objetivo: Resolve o preço, reaproveitando resolver_preco_com_frete_fixo.
    def resolver_preco(self):
        if self._faixa_frete is None:
            self.resolvida = False
            return

        frete = self._faixa_frete.valor_para_reputacao(self.config_magalu.faixa_reputacao_atual)
        self._taxa_unidade = self.config_magalu.taxa_unidade_fixa

        resultado = resolver_preco_com_frete_fixo(
            fixo=self._fixo,
            taxa_percentual=self._taxa_percentual,
            margem_alvo_fracao=self.margem_alvo_percentual / 100,
            frete=frete,
            taxa_unidade=self._taxa_unidade,
        )

        if resultado is None:
            self.resolvida = False
            return

        self.resolvida = True
        detalhamento = resultado['detalhamento']

        self._preco_final = resultado['preco_calculado']
        self._frete_usado = resultado['frete_usado']
        self._margem_valor = detalhamento['margem_valor']
        self._margem_percentual_obtida = resultado['margem_percentual_obtida']
        self._preco_exato_antes_arredondar = detalhamento['preco_exato_antes_arredondar']

        # * [EXPLICAÇÃO] → Mesma fórmula de margem, aplicada no preço EXATO,
        #                  antes do RoundUp90 — mesma lógica do ML, agora
        #                  descontando também a taxa unidade fixa.
        self._margem_exata_valor = (
            self._preco_exato_antes_arredondar * (1 - self._taxa_percentual)
            - self._fixo - self._frete_usado - self._taxa_unidade
        )
        self._margem_exata_percentual = (self._margem_exata_valor / self._preco_exato_antes_arredondar) * 100

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

        self.resolver_dimensao()
        self.calcular_custo_final()
        self.calcular_coleta()
        self.calcular_armazenagem()
        self.calcular_fixo()
        self.montar_taxa_e_denominador()
        self.buscar_faixa_frete()
        self.resolver_preco()

        if not self.resolvida:
            return self

        self._montar_dados_entrada()
        self._montar_dados_intermediarios()
        self._montar_dados_saida()
        return self

    # Função Objetivo: Monta a foto imutável de tudo que foi consumido.
    def _montar_dados_entrada(self):
        produto = self.produto
        self.entrada = DadosEntrada(
            sku=produto.sku,
            ean=produto.ean,
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
            altura=self._altura,
            largura=self._largura,
            comprimento=self._comprimento,
            peso=self._peso,
            origem_dimensao='produto_erp',
            fator_coleta=self.config_geral.fator_coleta,
            periodo_armazenagem=self.config_geral.periodo_armazenagem,
            faixa_reputacao=self.config_magalu.faixa_reputacao_atual,
            taxa_unidade_fixa=self._taxa_unidade,
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
            credito_icms_entrada=self._credito_icms_entrada,
            credito_pis=self._credito_pis,
            credito_cofins=self._credito_cofins,
            pis_saida_valor=self._pis_saida_valor,
            cofins_saida_valor=self._cofins_saida_valor,
            icms_saida_valor=self._icms_saida_valor,
            comissao_valor=self._comissao_valor,
            fixo=self._fixo,
            taxa_percentual=self._taxa_percentual * 100,
            taxa_valor=self._taxa_valor,
            denominador=self._denominador,
            margem_alvo_valor=self._margem_alvo_valor,
            faixa_frete_peso_min=self._faixa_frete.peso_min,
            faixa_frete_peso_max=self._faixa_frete.peso_max,
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
        )

    # Função Objetivo: Devolve a fórmula em forma abstrata, sem números.
    def formula_abstrata(self):
        return 'preço = (frete + FIXO) ÷ (1 − taxa − margem-alvo)'

    # Função Objetivo: Devolve a fórmula com os números reais já preenchidos.
    def formula_preenchida(self):
        i = self.intermediarios
        s = self.saida
        return f'preço = (R$ {s.frete_usado} + R$ {i.fixo}) ÷ {i.denominador} = R$ {s.preco_final}'

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
            {'ordem': 5, 'rotulo': 'Taxa', 'formula': 'comissão Magalu + ICMS saída + PIS + COFINS', 'resultado': i.taxa_percentual},
            {'ordem': 6, 'rotulo': 'Denominador', 'formula': '1 − taxa − margem-alvo', 'resultado': i.denominador},
            {'ordem': 7, 'rotulo': 'Frete por peso e reputação', 'formula': f'peso {e.peso}kg, faixa {e.faixa_reputacao}', 'resultado': s.frete_usado},
            {'ordem': 8, 'rotulo': 'Preço exato', 'formula': '(frete + FIXO) ÷ denominador', 'resultado': i.preco_exato_antes_arredondar},
            {'ordem': 9, 'rotulo': 'Preço final (arredondado ,90)', 'formula': 'RoundUp90 — sempre pra CIMA', 'resultado': s.preco_final},
            {'ordem': 10, 'rotulo': 'Margem obtida', 'formula': 'preço×(1−taxa) − FIXO − frete', 'resultado': s.margem_percentual_obtida},
        ]

    # Função Objetivo: Devolve as 3 dataclasses já serializadas, prontas pro JSONField.
    def para_dict_auditoria(self):
        return {
            'entrada': asdict(self.entrada),
            'intermediarios': asdict(self.intermediarios),
            'saida': asdict(self.saida),
            'passos': self.passos(),
        }