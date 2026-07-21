# core/funcoes_auxiliares/dimensoes_envio.py

# Função Objetivo: Representa as dimensões de envio de um produto/variação, já ordenadas.
# Explicação em detalhe: 'dimensao_menor/media/maior' são só posição no ranking de tamanho
# (menor -> maior), não eixo físico real (altura/largura/comprimento) — isso elimina a
# ambiguidade de rótulo de eixo entre ERP e ML na hora de comparar. 'peso' é o valor bruto,
# sem ordenação (não tem ambiguidade, é 1 valor só). 'completo' indica se os 4 valores
# (3 dimensões + peso) vieram preenchidos — usado depois pelo comparador de divergência.
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class DimensoesEnvio:
    dimensao_menor: Decimal
    dimensao_media: Decimal
    dimensao_maior: Decimal
    peso: Decimal
    completo: bool


# Função Objetivo: Monta um DimensoesEnvio a partir de 4 valores brutos (altura, largura, comprimento, peso).
# Explicação em detalhe: função pura, sem acesso a banco — usada igualmente por Produto e por
# VariacaoAnuncioMercadoLivre (2 casos reais desde já), por isso mora aqui em core, não em um
# app específico de marketplace. 'completo' só é True quando os 4 valores existem (nenhum None).
# Quando incompleto, devolve as 3 dimensões como None (não há o que ordenar) e preserva o peso
# bruto, se houver — quem decide o que fazer com incompleto é o comparador, não esta função.
def montar_dimensoes_envio(altura, largura, comprimento, peso):
    valores_dimensao = [altura, largura, comprimento]
    completo = all(valor is not None for valor in valores_dimensao) and peso is not None

    if not completo:
        return DimensoesEnvio(
            dimensao_menor=None,
            dimensao_media=None,
            dimensao_maior=None,
            peso=peso,
            completo=False,
        )

    dimensoes_ordenadas = sorted(valores_dimensao)

    return DimensoesEnvio(
        dimensao_menor=dimensoes_ordenadas[0],
        dimensao_media=dimensoes_ordenadas[1],
        dimensao_maior=dimensoes_ordenadas[2],
        peso=peso,
        completo=True,
    )