# arquivos_referencia/funcoes_auxiliares/auditor_base.py

# Função Objetivo: Base dos auditores de tabela de frete (Mercado Livre, Magalu, TikTok Shop, Amazon): o que
# todos fazem igual — ler célula com segurança, conferir o cabeçalho, apontar fórmula sem resultado e montar
# o "onde" de cada achado. Cada auditor espelha o importador do popular banco da mesma tabela: se o importador
# leria algo errado ou ignoraria uma linha, o auditor tem que dizer ANTES.
#
# * [DECISÃO, 15/10/2026] → As posições das colunas NÃO são copiadas para cá: cada auditor importa as constantes
#   do próprio importador (ex.: COL_PESO_MIN de importar_tabela_frete_magalu.py). Assim, se o importador mudar
#   de lugar uma coluna, a auditoria muda junto — nunca "valida" um layout que o importador já não lê.
# * [EXPLICAÇÃO] → O cabeçalho é conferido porque os importadores leem por POSIÇÃO (coluna E = peso mínimo),
#   nunca pelo nome. Planilha com as colunas trocadas de lugar "carrega" sem erro e grava lixo no banco.

import unicodedata

from .relatorio_auditoria import descrever_local, limpar_texto


# Função Objetivo: Texto sem acento e em minúsculas, para comparar cabeçalhos sem se importar com maiúscula/acento.
def sem_acentos(texto):
    decomposto = unicodedata.normalize('NFD', str(texto))
    return ''.join(c for c in decomposto if unicodedata.category(c) != 'Mn').lower()


# Função Objetivo: Valor da coluna `indice` da linha, ou None se a linha é mais curta (como se a célula estivesse vazia).
def celula(linha, indice):
    if linha is None or indice >= len(linha):
        return None
    return linha[indice]


class AuditorDeTabela:

    # Função Objetivo: Recebe a planilha já lida e o relatório onde os achados vão sendo registrados.
    def __init__(self, leitura, relatorio):
        self.leitura = leitura
        self.relatorio = relatorio
        self.titulos_das_colunas = {}

    def auditar(self):
        raise NotImplementedError

    # Função Objetivo: "Onde" de um achado numa aba, com o título da coluna quando se sabe.
    def local(self, aba, linha=None, coluna=None):
        titulo = self.titulos_das_colunas.get(coluna) if coluna is not None else None
        return descrever_local(aba, linha, coluna, titulo)

    # Função Objetivo: Guarda os títulos do cabeçalho (para os achados dizerem "coluna E (Peso mínimo)").
    def memorizar_titulos(self, cabecalho):
        self.titulos_das_colunas = {
            indice: limpar_texto(valor) for indice, valor in enumerate(cabecalho) if valor is not None and limpar_texto(valor)
        }

    # Função Objetivo: Confere se cada coluna esperada tem, no cabeçalho, as palavras que a identificam.
    # `esperadas` é uma lista de (indice_da_coluna, nome_esperado, [palavras que o cabeçalho tem que conter]).
    # Devolve True se TODAS conferem. Se não, registra ERRO (o importador leria a coluna errada em silêncio).
    def conferir_cabecalho(self, aba, cabecalho, esperadas):
        tudo_certo = True
        for indice, nome_esperado, palavras in esperadas:
            encontrado = celula(cabecalho, indice)
            texto = sem_acentos(limpar_texto(encontrado)) if encontrado is not None else ''
            if all(palavra in texto for palavra in palavras):
                continue
            tudo_certo = False
            visto = f'“{limpar_texto(encontrado)}”' if texto else 'uma célula vazia'
            self.relatorio.erro(
                descrever_local(aba, 1, indice),
                f'Era para esta coluna ser “{nome_esperado}”, mas o cabeçalho tem {visto}.',
                'O sistema lê as colunas pela POSIÇÃO, não pelo nome. Confira se é o arquivo certo e se as colunas '
                'estão na ordem original.',
            )
        return tudo_certo

    # Função Objetivo: Fórmula sem resultado salvo = célula "vazia" para o importador. Registra 1 ERRO por aba.
    def apontar_formulas_sem_resultado(self, aba):
        achadas = self.leitura.formulas_sem_resultado.get(aba)
        if not achadas:
            return
        exemplos = ', '.join(descrever_celula(linha, coluna) for linha, coluna in achadas[:5])
        mais = f' (e mais {len(achadas) - 5})' if len(achadas) > 5 else ''
        self.relatorio.erro(
            descrever_local(aba),
            f'{len(achadas)} célula(s) têm fórmula mas nenhum resultado salvo: {exemplos}{mais}. '
            f'O sistema leria essas células como vazias.',
            'Abra o arquivo no Excel e salve de novo (Ctrl+S) para o Excel gravar o resultado das fórmulas.',
        )

    # Função Objetivo: Avisa quando o arquivo tem mais de uma aba (o importador lê só a aba ATIVA, a que estava aberta ao salvar).
    def avisar_abas_extras(self):
        nomes = self.leitura.nomes_das_abas
        if len(nomes) > 1:
            self.relatorio.aviso(
                'arquivo inteiro',
                f'O arquivo tem {len(nomes)} abas ({", ".join(nomes)}). O sistema lê só a aba que estava ativa ao salvar: '
                f'“{self.leitura.nome_da_aba_ativa}”.',
                'Confira se é essa a aba certa — ou deixe o arquivo com uma aba só.',
            )


# Função Objetivo: "E5" a partir de linha (1 = primeira) e coluna (0 = A).
def descrever_celula(n_linha, indice_da_coluna):
    from openpyxl.utils import get_column_letter
    return f'{get_column_letter(indice_da_coluna + 1)}{n_linha}'
