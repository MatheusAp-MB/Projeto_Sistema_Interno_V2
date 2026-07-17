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
# Mínima/Padrão/Máxima/Competição NÃO são subclasses — são a MESMA classe, instanciada 4
# vezes com margem_alvo_percentual diferente (dado diferente, não comportamento diferente).

from dataclasses import dataclass, asdict
from decimal import Decimal
from precificacao.funcoes_auxiliares.goal_seek import resolver_preco_por_margem
from mercado_livre.funcoes_auxiliares.calculo_margem import (
    metro_cubico_de_dimensoes, selecionar_faixa_por_dimensao,
)


# Função Objetivo: Foto imutável de tudo que a fórmula consumiu.
@dataclass
class DadosEntrada:
    sku: str
    ean: str
    tipo_anuncio: str
    margem_alvo_percentual: Decimal

    custo: Decimal
    custo_com_boni: Decimal
    ipi_percentual: Decimal
    frete_cif_fob_percentual: Decimal
    st_valor: Decimal
    icms_entrada_percentual: Decimal
    pis_cofins_percentual: Decimal
    icms_saida_percentual: Decimal
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

    fator_coleta: Decimal
    periodo_armazenagem: Decimal

    rebate_percentual: Decimal
    preco_original: Decimal | None


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

    credito_icms_entrada: Decimal
    credito_pis: Decimal
    pis_cofins_valor: Decimal
    icms_saida_valor: Decimal
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


# Função Objetivo: Representa 1 margem candidata, já resolvida — mesma classe,
# instanciada 4x (Mínima/Padrão/Máxima/Competição) com margem_alvo_percentual diferente.
class FormulaPrecificacao:

    # Função Objetivo: Recebe tudo que precisa pra resolver essa margem.
    def __init__(self, produto, dimensoes_efetivas, config_tipo, config_geral,
                 margem_alvo_percentual, frete_todas, faixas_armazenagem=None,
                 rebate_percentual=None, preco_original=None):
        self.produto = produto
        self.dimensoes_efetivas = dimensoes_efetivas
        self.config_tipo = config_tipo
        self.config_geral = config_geral
        self.margem_alvo_percentual = Decimal(str(margem_alvo_percentual))
        self.frete_todas = frete_todas
        self.faixas_armazenagem = faixas_armazenagem
        self.rebate_percentual = Decimal(str(rebate_percentual)) if rebate_percentual is not None else Decimal('0')
        self.preco_original = Decimal(str(preco_original)) if preco_original is not None else None

        self.entrada = None
        self.intermediarios = None
        self.saida = None
        self.resolvida = False

    # Função Objetivo: Calcula o custo final (custo com boni + IPI + frete CIF/FOB + ST).
    def calcular_custo_final(self):
        produto = self.produto
        custo_com_boni = produto.custo_com_boni or produto.custo
        ipi_percentual = produto.ipi or Decimal('0')
        frete_cif_fob_percentual = produto.frete_cif_fob or Decimal('0')
        st_valor = produto.st_valor or Decimal('0')

        ipi_valor = custo_com_boni * (ipi_percentual / 100)
        frete_cif_fob_valor = custo_com_boni * (frete_cif_fob_percentual / 100)

        self._custo_com_boni = custo_com_boni
        self._ipi_percentual = ipi_percentual
        self._ipi_valor = ipi_valor
        self._frete_cif_fob_percentual = frete_cif_fob_percentual
        self._frete_cif_fob_valor = frete_cif_fob_valor
        self._st_valor = st_valor
        self._custo_final = custo_com_boni + ipi_valor + frete_cif_fob_valor + st_valor

    # Função Objetivo: Calcula a coleta a partir do metro cúbico do DimensoesEfetivas.
    def calcular_coleta(self):
        dim = self.dimensoes_efetivas
        self._metro_cubico = metro_cubico_de_dimensoes(dim.altura, dim.largura, dim.comprimento)
        self._coleta = self._metro_cubico * self.config_geral.fator_coleta

    # Função Objetivo: Calcula a armazenagem — planilha se existir, senão faixa por dimensão.
    def calcular_armazenagem(self):
        produto = self.produto
        dim = self.dimensoes_efetivas

        if produto.armazenagem_planilha is not None:
            self._armazenagem_origem = 'planilha'
            self._armazenagem = produto.armazenagem_planilha
            return

        if self.faixas_armazenagem is not None:
            faixas = self.faixas_armazenagem
        else:
            from mercado_livre.models import FaixaArmazenagemMercadoLivre
            faixas = list(FaixaArmazenagemMercadoLivre.objects.filter(ativo=True).order_by('ordem'))

        faixa_usada = selecionar_faixa_por_dimensao(dim.altura, dim.largura, dim.comprimento, faixas)
        self._armazenagem_origem = 'faixa_dimensao'
        self._armazenagem = (faixa_usada.valor_diario * self.config_geral.periodo_armazenagem) if faixa_usada else Decimal('0')

    # Função Objetivo: Soma os 3 pedaços do FIXO e desconta os créditos de ICMS/PIS.
    def calcular_fixo(self):
        produto = self.produto
        self._icms_entrada_percentual = produto.icms_entrada or Decimal('0')
        self._pis_percentual = produto.pis_cofins or Decimal('0')

        self._credito_icms_entrada = produto.custo * (self._icms_entrada_percentual / 100)
        self._credito_pis = produto.custo * (self._pis_percentual / 100)

        self._fixo = self._coleta + self._armazenagem + self._custo_final - (
            self._credito_icms_entrada + self._credito_pis
        )

    # Função Objetivo: Monta a taxa (comissão + ICMS saída + PIS) e o denominador da meta.
    def montar_taxa_e_denominador(self):
        produto = self.produto
        self._comissao_percentual = self.config_tipo.comissao
        self._icms_saida_percentual = produto.icms_saida_media or Decimal('0')
        self._pis_cofins_percentual = produto.pis_cofins or Decimal('0')

        self._taxa_percentual = (
            self._comissao_percentual + self._icms_saida_percentual + self._pis_cofins_percentual
        ) / 100
        self._denominador = Decimal('1') - self._taxa_percentual - (self.margem_alvo_percentual / 100)

        if self.rebate_percentual and self.preco_original:
            self._rebate_valor = self.preco_original * (self.rebate_percentual / 100)
        else:
            self._rebate_valor = Decimal('0')

    # Função Objetivo: Filtra as faixas de frete candidatas pelo peso do DimensoesEfetivas.
    def filtrar_faixas_frete(self):
        peso = self.dimensoes_efetivas.peso
        self._faixas_candidatas = sorted(
            (f for f in self.frete_todas if f.peso_min <= peso and (f.peso_max is None or f.peso_max >= peso)),
            key=lambda f: f.preco_min,
        )

    # Função Objetivo: Resolve o preço, reaproveitando resolver_preco_por_margem do goal_seek.
    def resolver_preco(self):
        custo_produto = self.produto.custo_com_boni or self.produto.custo

        resultado = resolver_preco_por_margem(
            fixo=self._fixo,
            taxa_percentual=self._taxa_percentual,
            margem_alvo_fracao=self.margem_alvo_percentual / 100,
            custo_produto=custo_produto,
            faixas_frete_candidatas=self._faixas_candidatas,
            rebate_valor=self._rebate_valor,
        )

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
        self._pis_cofins_valor = self._preco_final * self._pis_cofins_percentual / 100
        self._taxa_valor = self._preco_final * self._taxa_percentual
        self._margem_alvo_valor = self._preco_final * (self.margem_alvo_percentual / 100)

    # Função Objetivo: Roda todos os passos acima, na ordem certa, e monta as 3 dataclasses.
    def calcular(self):
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
            ipi_percentual=self._ipi_percentual,
            frete_cif_fob_percentual=self._frete_cif_fob_percentual,
            st_valor=self._st_valor,
            icms_entrada_percentual=self._icms_entrada_percentual,
            pis_cofins_percentual=self._pis_cofins_percentual,
            icms_saida_percentual=self._icms_saida_percentual,
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
            fator_coleta=self.config_geral.fator_coleta,
            periodo_armazenagem=self.config_geral.periodo_armazenagem,
            rebate_percentual=self.rebate_percentual,
            preco_original=self.preco_original,
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
            pis_cofins_valor=self._pis_cofins_valor,
            icms_saida_valor=self._icms_saida_valor,
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
            {'ordem': 1, 'rotulo': 'Custo final', 'formula': 'custo_com_boni + IPI + frete CIF/FOB + ST', 'resultado': i.custo_final},
            {'ordem': 2, 'rotulo': 'Coleta', 'formula': 'metro_cúbico × fator_coleta', 'resultado': i.coleta},
            {'ordem': 3, 'rotulo': 'Armazenagem', 'formula': f'origem: {i.armazenagem_origem}', 'resultado': i.armazenagem},
            {'ordem': 4, 'rotulo': 'FIXO', 'formula': 'coleta + armazenagem + custo_final − créditos', 'resultado': i.fixo},
            {'ordem': 5, 'rotulo': 'Taxa', 'formula': 'comissão + ICMS saída + PIS', 'resultado': i.taxa_percentual},
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