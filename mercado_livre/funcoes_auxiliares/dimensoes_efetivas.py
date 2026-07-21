# mercado_livre/funcoes_auxiliares/dimensoes_efetivas.py

# Função Objetivo: Resolve a dimensão efetiva de 1 MLB — Variação ML ou fallback do Produto ERP.
# Explicação em detalhe: implementa a decisão da reforma — Frete, Coleta e Armazenagem sempre
# usam a EMBALAGEM, e sempre preferem o dado declarado pelo vendedor no Mercado Livre
# (SELLER_PACKAGE_*) quando ele existe completo (as 4: altura, largura, comprimento, peso). Só
# cai no fallback do Produto (ERP) quando falta qualquer um dos 4. Peso efetivo é sempre o
# maior entre físico e cúbico — regra oficial do Mercado Livre, replicada aqui. Dimensões (nos
# 2 branches) usam sempre os campos "_ordenada_cm" (21/07) — nunca os brutos direto — pra
# bater certo nas faixas de armazenagem/frete sem depender de rótulo de eixo original.

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


# Função Objetivo: Marca de qual fonte a dimensão efetiva veio.
class OrigemDimensao(Enum):
    VARIACAO_ML = 'variacao_ml'
    PRODUTO_ERP = 'produto_erp'


# Função Objetivo: Representa a dimensão/peso efetivos já resolvidos, prontos pro cálculo.
@dataclass
class DimensoesEfetivas:
    altura: Decimal
    largura: Decimal
    comprimento: Decimal
    peso: Decimal
    origem: OrigemDimensao


# Função Objetivo: Diz se a variação tem as 4 dimensões (já ordenadas) declaradas pelo vendedor no ML.
# Explicação em detalhe: checa "_ordenada_cm" (não mais "_declarada_cm" bruto, 21/07) — são os
# campos que organizar_e_verificar_divergencias_dimensoes_envio calcula e persiste. Peso continua
# vindo do bruto (peso_declarado_kg), que não tem ambiguidade de eixo.
def _variacao_tem_dimensao_completa(variacao):
    return (
        variacao is not None
        and variacao.altura_ordenada_cm is not None
        and variacao.largura_ordenada_cm is not None
        and variacao.comprimento_ordenada_cm is not None
        and variacao.peso_declarado_kg is not None
    )


# Função Objetivo: Calcula o peso cúbico a partir de 3 dimensões, padrão internacional (÷6000).
def _calcular_peso_cubico(altura, largura, comprimento):
    return (altura * largura * comprimento) / Decimal('6000')


# Função Objetivo: Resolve a dimensão efetiva de 1 MLB — Variação ML ou fallback do Produto ERP.
def resolver_dimensoes_efetivas(produto, variacao=None):
    if _variacao_tem_dimensao_completa(variacao):
        altura = variacao.altura_ordenada_cm
        largura = variacao.largura_ordenada_cm
        comprimento = variacao.comprimento_ordenada_cm
        peso_fisico = variacao.peso_declarado_kg
        peso_cubico = _calcular_peso_cubico(altura, largura, comprimento)

        return DimensoesEfetivas(
            altura=altura,
            largura=largura,
            comprimento=comprimento,
            peso=max(peso_fisico, peso_cubico),
            origem=OrigemDimensao.VARIACAO_ML,
        )

    altura = produto.altura_ordenada_cm or Decimal('0')
    largura = produto.largura_ordenada_cm or Decimal('0')
    comprimento = produto.comprimento_ordenada_cm or Decimal('0')
    peso_fisico = produto.peso_produto_apos_embalado or Decimal('0')
    peso_cubico = produto.peso_cubado or Decimal('0')

    return DimensoesEfetivas(
        altura=altura,
        largura=largura,
        comprimento=comprimento,
        peso=max(peso_fisico, peso_cubico),
        origem=OrigemDimensao.PRODUTO_ERP,
    )