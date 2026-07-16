"""
CONFIRMAÇÃO — Qual atributo de dimensão veio preenchido de verdade?
"""

import json
from pathlib import Path

ARQUIVO = Path("Arquivos_API/detalhes_mlbs.json")


def main():
    with open(ARQUIVO, encoding="utf-8") as f:
        dados = json.load(f)

    registros = dados["registros"]
    total = len(registros)

    campos = [
        "attr_seller_package_height", "attr_seller_package_width",
        "attr_seller_package_length", "attr_seller_package_weight",
        "attr_dimensions", "attr_weight",
    ]

    print(f"Total de registros: {total}\n")
    for c in campos:
        preenchidos = sum(1 for r in registros if r.get(c) is not None)
        print(f"  {c}: {preenchidos} preenchidos ({preenchidos/total*100:.1f}%)")

    # Mostra 1 exemplo real de cada campo que teve algum valor
    print("\nExemplo do primeiro registro:")
    for c in campos:
        print(f"  {c}: {registros[0].get(c)}")


if __name__ == "__main__":
    main()