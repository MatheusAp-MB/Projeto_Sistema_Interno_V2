"""
Calcula, para cada combinação de NCM + EAN/GTIN, a média ponderada:
    resultado = (valor_SP + média_dos_demais_estados) / 2

Ou seja: SP vale 50% do resultado, e os demais estados dividem
igualmente entre si os outros 50% (via média simples).

Ajuste as constantes na seção CONFIG antes de rodar.
"""

import pandas as pd

# ============== CONFIG ==============
INPUT_PATH = "processado_MAGAZINE - BuscaLegal de todos os produtos.xlsx somente icms.xlsx"       # caminho do arquivo de entrada (.xlsx ou .csv)
OUTPUT_PATH = "resumo_media_ean_ncm.xlsx"
SHEET_NAME = 0                          # índice ou nome da aba, se .xlsx

COL_NCM = "NCM"
COL_EAN = "EAN/GTIN"
COL_UF_DESTINO = "UF Destino"
COL_VALOR = "Dado a ser calculado"
UF_REFERENCIA = "SP"                    # estado que vale 50%
# =====================================


def carregar_planilha(caminho: str, sheet_name=0) -> pd.DataFrame:
    if caminho.lower().endswith(".csv"):
        df = pd.read_csv(caminho)
    else:
        df = pd.read_excel(caminho, sheet_name=sheet_name)

    # normaliza nomes de coluna (remove quebras de linha e espaços extras,
    # útil porque algumas colunas do cabeçalho vêm com anotações em 2 linhas)
    df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]
    return df


def calcular_grupo(grupo: pd.DataFrame) -> pd.Series:
    sp = grupo.loc[grupo[COL_UF_DESTINO] == UF_REFERENCIA, COL_VALOR]
    demais = grupo.loc[grupo[COL_UF_DESTINO] != UF_REFERENCIA, COL_VALOR]

    aviso = None

    if len(sp) == 0:
        valor_sp = None
        aviso = "SEM_SP"
    elif len(sp) > 1:
        valor_sp = sp.mean()
        aviso = f"SP_DUPLICADO_{len(sp)}x"
    else:
        valor_sp = sp.iloc[0]

    media_demais = demais.mean() if len(demais) > 0 else None
    if media_demais is None and aviso is None:
        aviso = "SEM_DEMAIS_ESTADOS"

    if valor_sp is not None and media_demais is not None:
        resultado = (valor_sp + media_demais) / 2
    else:
        resultado = None

    return pd.Series({
        "valor_SP": valor_sp,
        "media_demais_estados": media_demais,
        "resultado_da_media": resultado,
        "qtd_linhas_no_grupo": len(grupo),
        "aviso": aviso,
    })


def main():
    df = carregar_planilha(INPUT_PATH, SHEET_NAME)

    faltantes = [c for c in (COL_NCM, COL_EAN, COL_UF_DESTINO, COL_VALOR) if c not in df.columns]
    if faltantes:
        raise ValueError(
            f"Colunas não encontradas: {faltantes}\n"
            f"Colunas disponíveis no arquivo: {list(df.columns)}"
        )

    resumo = (
        df.groupby([COL_NCM, COL_EAN], dropna=False)
          .apply(calcular_grupo)
          .reset_index()
    )

    resumo.to_excel(OUTPUT_PATH, index=False)

    total_avisos = resumo["aviso"].notna().sum()
    print(f"Grupos processados (NCM+EAN únicos): {len(resumo)}")
    print(f"Grupos com aviso (revisar manualmente): {total_avisos}")
    if total_avisos:
        print(resumo.loc[resumo["aviso"].notna(), [COL_NCM, COL_EAN, "aviso"]].to_string(index=False))
    print(f"\nArquivo salvo em: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()