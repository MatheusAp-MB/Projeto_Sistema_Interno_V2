import pandas as pd

# ==============================
# Configurações (ajuste os caminhos abaix   o)
# ==============================
CAMINHO_PLANILHA_COMPLETA = "Produtos_ORTHO_MB.xlsx"   # planilha com todos os SKUs da marca
CAMINHO_PLANILHA_SKUS = "ID_87003.xlsx"        # planilha com os SKUs específicos a filtrar
CAMINHO_SAIDA = "skus_filtrados.xlsx"                  # nome do arquivo de saída

COLUNA_SKU = "SKU"

# ==============================
# Leitura das planilhas
# ==============================
df_completa = pd.read_excel(CAMINHO_PLANILHA_COMPLETA)
df_skus = pd.read_excel(CAMINHO_PLANILHA_SKUS)

# ==============================
# Filtro
# ==============================
lista_skus = df_skus[COLUNA_SKU].tolist()

df_filtrado = df_completa[df_completa[COLUNA_SKU].isin(lista_skus)]

# ==============================
# Geração da planilha de saída
# ==============================
df_filtrado.to_excel(CAMINHO_SAIDA, index=False)

print(f"Concluído! {len(df_filtrado)} de {len(lista_skus)} SKUs encontrados.")
print(f"Arquivo gerado: {CAMINHO_SAIDA}")