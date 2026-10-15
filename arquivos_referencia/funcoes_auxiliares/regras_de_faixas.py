# arquivos_referencia/funcoes_auxiliares/regras_de_faixas.py

# Função Objetivo: Regras de auditoria que TODAS as tabelas de frete compartilham (faixas de peso e de preço):
# faixa repetida, buraco entre faixas, sobreposição, teto no lugar errado e valor que "cai" quando devia subir.
# Cada auditor (ML, Magalu, TikTok, Amazon) lê a sua planilha e chama estas funções com as faixas já lidas.
#
# * [DECISÃO, 15/10/2026] → Quem bloqueia e quem só avisa (combinado com Matheus):
#   - ERRO (bloqueia): faixa repetida; faixa sem teto no MEIO da tabela; máximo menor que o mínimo.
#   - AVISO (só avisa): buraco ou sobreposição entre faixas; primeira faixa que não começa em 0; última faixa
#     com teto; frete que diminui quando o peso/preço aumenta.
# * [EXPLICAÇÃO] → Por que a "folga" entre faixas não é zero: as tabelas reais trocam de faixa assim — "0 a 0,499"
#   e depois "0,5 a 0,999" (diferença de 0,001 kg); "R$ 0 a 29,99" e depois "R$ 30" (diferença de R$ 0,01). Isso é
#   normal e não é buraco. O ML é diferente: a faixa seguinte começa EXATAMENTE onde a anterior termina.

from dataclasses import dataclass

TOLERANCIA = 1e-6

FOLGA_DO_PESO_EM_KG = 0.0011        # Magalu, TikTok e Amazon (0,499 → 0,5 = 0,001)
FOLGA_DO_PESO_DO_ML = 0.0           # ML: o mínimo da próxima é o máximo da anterior
FOLGA_DO_PRECO_EM_REAIS = 0.0125    # R$ 29,99 → R$ 30 = R$ 0,01


@dataclass
class Faixa:
    linha: int
    minimo: float
    maximo: object = None      # None = sem teto


@dataclass
class Ponto:
    linha: int
    coluna: int
    valor: float


# Função Objetivo: Confere uma sequência de faixas (todas do mesmo "grupo": mesmo regime, mesmo peso...).
# `faixas` pode vir em qualquer ordem — a função ordena pelo mínimo.
# `descrever_local(linha)` devolve o "onde" da linha (cada auditor sabe a sua aba/coluna);
# `formatar` escreve um valor (peso em kg, preço em R$); `nome` é "peso" ou "preço"; `consequencia` explica o
# efeito de um buraco ("produtos nesse intervalo ficariam sem frete").
def verificar_sequencia_de_faixas(relatorio, faixas, *, descrever_local, formatar, nome, consequencia,
                                  folga_entre_faixas, ultima_deve_ser_aberta, minimo_esperado_da_primeira=0.0,
                                  grupo='', posicao=None, conferir_continuidade=True):
    # * [EXPLICAÇÃO] → `conferir_continuidade=False` (usado quando alguma linha da tabela tem ERRO de célula e ficou de
    #   fora da conta): sem essa linha, "buraco", "primeira faixa" e "última faixa" seriam alarmes falsos causados pelo
    #   erro, não pela tabela. Repetida, máximo menor que mínimo e teto no meio continuam sendo conferidos.
    sufixo = f' ({grupo})' if grupo else ''
    # * [EXPLICAÇÃO] → `posicao` diz como escrever "onde" a faixa está: normalmente "linha 7"; no cabeçalho de preço do ML
    #   (onde as 8 faixas estão lado a lado na linha 1) é "coluna G". Em `Faixa.linha` vai então o número da posição.
    posicao = posicao or (lambda p: f'linha {p}')
    ordenadas = sorted(faixas, key=lambda f: (f.minimo, f.linha))
    anterior = None

    for faixa in ordenadas:
        if faixa.maximo is not None and faixa.maximo < faixa.minimo - TOLERANCIA:
            relatorio.erro(
                descrever_local(faixa.linha),
                f'O {nome} máximo ({formatar(faixa.maximo)}) é menor que o mínimo ({formatar(faixa.minimo)}){sufixo}.',
                'Troque os dois valores ou corrija o que foi digitado errado.',
            )

        if anterior is not None:
            if abs(faixa.minimo - anterior.minimo) <= TOLERANCIA:
                relatorio.erro(
                    descrever_local(faixa.linha),
                    f'Faixa repetida{sufixo}: o {nome} mínimo {formatar(faixa.minimo)} já aparece na '
                    f'{posicao(anterior.linha)}. O sistema guardaria só uma das duas.',
                    'Apague a linha repetida (ou corrija o valor se uma delas é de outra faixa).',
                )
                continue

            if anterior.maximo is None:
                relatorio.erro(
                    descrever_local(anterior.linha),
                    f'A faixa da {posicao(anterior.linha)} não tem {nome} máximo, mas existem faixas acima dela{sufixo}.',
                    f'Preencha o {nome} máximo dessa faixa. Só a ÚLTIMA faixa pode ficar sem teto.',
                )
            elif conferir_continuidade:
                diferenca = faixa.minimo - anterior.maximo
                if diferenca < -TOLERANCIA:
                    relatorio.aviso(
                        descrever_local(faixa.linha),
                        f'Sobreposição{sufixo}: a faixa da {posicao(anterior.linha)} vai até {formatar(anterior.maximo)}, '
                        f'mas esta começa em {formatar(faixa.minimo)}.',
                        'Confira os limites das duas faixas.',
                    )
                elif diferenca > folga_entre_faixas + TOLERANCIA:
                    relatorio.aviso(
                        descrever_local(faixa.linha),
                        f'Buraco{sufixo}: a faixa da {posicao(anterior.linha)} termina em {formatar(anterior.maximo)} e esta '
                        f'começa em {formatar(faixa.minimo)} — {consequencia}',
                        'Confira se falta uma faixa ou se algum limite foi digitado errado.',
                    )
        anterior = faixa

    if not ordenadas or not conferir_continuidade:
        return

    primeira, ultima = ordenadas[0], ordenadas[-1]
    if minimo_esperado_da_primeira is not None and abs(primeira.minimo - minimo_esperado_da_primeira) > TOLERANCIA:
        relatorio.aviso(
            descrever_local(primeira.linha),
            f'A primeira faixa{sufixo} começa em {formatar(primeira.minimo)}, não em {formatar(minimo_esperado_da_primeira)} '
            f'— {consequencia}',
            'Confira se falta a faixa inicial.',
        )
    if ultima_deve_ser_aberta and ultima.maximo is not None:
        relatorio.aviso(
            descrever_local(ultima.linha),
            f'A última faixa{sufixo} tem {nome} máximo ({formatar(ultima.maximo)}): acima disso o sistema não acha valor.',
            f'Se a tabela não tem teto, deixe o {nome} máximo da última faixa vazio (ou “sem limite”, no Mercado Livre).',
        )


# Função Objetivo: Avisa quando o valor CAI numa sequência em que só devia subir (ou ficar igual).
# `pontos` já vem na ordem certa (do menor peso/preço para o maior).
def verificar_valores_nao_decrescentes(relatorio, pontos, *, descrever_local, formatar_valor, quando):
    for anterior, atual in zip(pontos, pontos[1:]):
        if atual.valor < anterior.valor - TOLERANCIA:
            relatorio.aviso(
                descrever_local(atual.linha, atual.coluna),
                f'O valor cai de {formatar_valor(anterior.valor)} (linha {anterior.linha}) para '
                f'{formatar_valor(atual.valor)} {quando}.',
                'Pode estar certo, mas confira se não é erro de digitação.',
            )
