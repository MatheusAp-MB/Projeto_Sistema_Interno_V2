# mercado_livre/funcoes_auxiliares/dimensoes_efetivas.py

# Função Objetivo: Resolve a dimensão efetiva de 1 MLB — Variação ML ou fallback do Produto ERP.
# Explicação em detalhe: implementa a decisão da reforma — Frete, Coleta e Armazenagem sempre
# usam a EMBALAGEM, e sempre preferem o dado declarado pelo vendedor no Mercado Livre
# (SELLER_PACKAGE_*) quando ele existe completo (as 4: altura, largura, comprimento, peso). Só
# cai no fallback do Produto (ERP) quando falta qualquer um dos 4. Peso efetivo é sempre o
# maior entre físico e cúbico — regra oficial do Mercado Livre, replicada aqui. Dimensões (nos
# 2 branches) usam sempre os campos "_ordenada_cm" (21/07) — nunca os brutos direto — pra
# bater certo nas faixas de armazenagem/frete sem depender de rótulo de eixo original.
#
# peso_fisico/peso_cubico (10/09) — os 2 já eram calculados nos 2 branches só pra tirar o
# max() e descartados em seguida. Passaram a ser guardados também, pra tela de auditoria
# poder provar QUAL dos 2 venceu, não só mostrar o resultado já resolvido. Default None
# (não os 2 campos com nome errado — None de verdade) pra não quebrar quem já constrói
# DimensoesEfetivas direto (ex: _dim_padrao() nos testes) sem passar esses 2.
#
# * [CORREÇÃO 11/09/2026] → resolver_dimensoes_efetivas devolvia, no branch do Produto
#   ERP, "produto.altura_ordenada_cm or Decimal('0')" pros 3 eixos + peso — quando a
#   embalagem não está cadastrada no ERP (altura/largura/comprimento_ordenada_cm = None),
#   isso montava uma DimensoesEfetivas com TUDO zerado, um objeto VÁLIDO, não "sem dado".
#   filtrar_faixas_frete() (formula_precificacao.py) filtra a faixa de frete só por peso
#   (peso_min <= peso) — e a tabela FreteML sempre tem faixa peso_min=0.000 (a mais leve),
#   então o cálculo "resolvia" com sucesso, só que usando frete de produto até 300g sem
#   saber o peso/dimensão real. Silencioso — não aparecia em SEM CÁLCULO nem em erros de
#   assert. Confirmado em produção: 3084 linhas MAGAZINE / 4804 linhas SAMVALE
#   (369 / 533 produtos distintos) resolvidas=True vindo exatamente desse fallback quebrado
#   (frete_usado entre R$5,65 e R$20,95 — sempre a faixa mais barata). Não existe fallback
#   legítimo pra usar em vez disso: Produto.altura_produto_sem_embalar (dimensão sem caixa)
#   não serve pra frete, que depende da embalagem. Agora devolve None quando nem a
#   variação nem o Produto ERP têm dado suficiente — quem chama decide o que fazer
#   (calcular_grade_precificacao_ml grava resolvida=False com motivo claro, sem tentar
#   calcular nada com peso fabricado).

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
    peso_fisico: Decimal = None
    peso_cubico: Decimal = None


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
# Explicação em detalhe: devolve None (em vez de fabricar zero) quando nem a variação nem o
# Produto ERP têm dado suficiente. Quem chama tem que tratar o None explicitamente, nunca
# repassar direto pra FormulaPrecificacao.
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
            peso_fisico=peso_fisico,
            peso_cubico=peso_cubico,
        )

    altura = produto.altura_ordenada_cm
    largura = produto.largura_ordenada_cm
    comprimento = produto.comprimento_ordenada_cm
    peso_fisico = produto.peso_produto_apos_embalado or Decimal('0')
    peso_cubico = produto.peso_cubado or Decimal('0')
    peso = max(peso_fisico, peso_cubico)

    if altura is None or largura is None or comprimento is None or peso == 0:
        return None

    return DimensoesEfetivas(
        altura=altura,
        largura=largura,
        comprimento=comprimento,
        peso=peso,
        origem=OrigemDimensao.PRODUTO_ERP,
        peso_fisico=peso_fisico,
        peso_cubico=peso_cubico,
    )