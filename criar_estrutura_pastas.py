import re
import openpyxl
from pathlib import Path

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CAMINHO_PLANILHA = Path(r"C:/Users/Win10/Desktop/Videos ML/Magazine.xlsx")
PASTA_RAIZ = Path(r"C:/Users/Win10/Desktop/Videos ML")
NOME_EMPRESA_FIXO = "Magazine"
QTD_ROTEIROS_TESTE = 3
# ========================================


# Função Objetivo: Remove caracteres inválidos pra nome de pasta/arquivo no Windows.
def sanitizar_nome(texto):
    texto = re.sub(r'[\\/:*?"<>|]', '', texto)
    texto = texto.strip(" .")  # Windows não aceita pasta terminando em espaço/ponto
    return texto


wb = openpyxl.load_workbook(CAMINHO_PLANILHA, data_only=True)
ws = wb["Agenda"]

criadas = 0
puladas = 0

for linha in ws.iter_rows(min_row=2, values_only=True):
    ean, mlb, produto, marca, status = linha[2], linha[3], linha[4], linha[5], linha[8]

    if not produto or not ean:
        continue  # linha vazia (fim real dos dados)

    marca_limpa = sanitizar_nome(str(marca or "SEM_MARCA"))
    produto_limpo = sanitizar_nome(str(produto))
    nome_pasta_produto = f"{produto_limpo} # {ean}"

    pasta_produto = PASTA_RAIZ / NOME_EMPRESA_FIXO / marca_limpa / nome_pasta_produto

    if pasta_produto.exists():
        puladas += 1
        print(f"[JÁ EXISTE] {pasta_produto}")
        continue

    pasta_produto.mkdir(parents=True, exist_ok=True)

    for numero in range(1, QTD_ROTEIROS_TESTE + 1):
        arquivo_roteiro = pasta_produto / f"Roteiro {numero:02d}.mp4"
        arquivo_roteiro.touch()

    criadas += 1
    print(f"[CRIADA] {pasta_produto}  (MLB: {mlb})")

print()
print(f"Total: {criadas} pasta(s) criada(s), {puladas} já existiam.")