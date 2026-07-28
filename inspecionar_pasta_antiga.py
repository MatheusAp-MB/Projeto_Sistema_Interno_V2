import os

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CAMINHO_PASTA = r'CLIPES_MAGAZINE'
CAMINHO_ARQUIVO_SAIDA = 'arvore_clipes_magazine.txt'
# ========================================


def montar_arvore(caminho, prefixo=''):
    linhas = []
    itens = sorted(os.listdir(caminho))
    pastas = [i for i in itens if os.path.isdir(os.path.join(caminho, i))]
    arquivos = [i for i in itens if not os.path.isdir(os.path.join(caminho, i))]
    todos_ordenados = pastas + arquivos  # pastas primeiro, depois arquivos, cada grupo alfabético

    for indice, nome in enumerate(todos_ordenados):
        eh_ultimo = indice == len(todos_ordenados) - 1
        caminho_item = os.path.join(caminho, nome)
        conector = '└── ' if eh_ultimo else '├── '

        if os.path.isdir(caminho_item):
            linhas.append(f'{prefixo}{conector}{nome}/')
            prefixo_filho = prefixo + ('    ' if eh_ultimo else '│   ')
            linhas.extend(montar_arvore(caminho_item, prefixo_filho))
        else:
            tamanho_mb = os.path.getsize(caminho_item) / (1024 * 1024)
            linhas.append(f'{prefixo}{conector}{nome}  ({tamanho_mb:.1f} MB)')

    return linhas


linhas_saida = [f'Estrutura de: {CAMINHO_PASTA}', '']
linhas_saida.extend(montar_arvore(CAMINHO_PASTA))

total_pastas = sum(len(dirs) for _, dirs, _ in os.walk(CAMINHO_PASTA))
total_arquivos = sum(len(files) for _, _, files in os.walk(CAMINHO_PASTA))
linhas_saida.append('')
linhas_saida.append('--- Resumo ---')
linhas_saida.append(f'Total de pastas (incluindo subpastas): {total_pastas}')
linhas_saida.append(f'Total de arquivos: {total_arquivos}')

texto_completo = '\n'.join(linhas_saida)

with open(CAMINHO_ARQUIVO_SAIDA, 'w', encoding='utf-8') as arquivo:
    arquivo.write(texto_completo)

print(texto_completo)
print(f'\n(Também salvo em: {CAMINHO_ARQUIVO_SAIDA} — pode subir esse arquivo em vez de colar, se ficar longo demais)')