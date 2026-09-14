# renomear_comandos_impostos_saida.py

# Função Objetivo: Etapa 8 do roteiro de Impostos de Saída — renomeia os 2
# comandos que escondiam a chave real no nome (mesmo problema já corrigido
# nas tabelas, Decisão de Nomenclatura das Tabelas de 13/09) e atualiza as
# referências internas ao nome antigo. `preencher_CST_produtos` e
# `preencher_impostos_saida` ficam sem mudança (decisão confirmada).
#
# Idempotente: rodar 2x não quebra — se já encontrar o estado renomeado,
# só avisa e pula. Assert de ocorrência única antes de qualquer troca de
# texto, pra nunca trocar em lugar que não é o esperado.
#
# Rodar com: python renomear_comandos_impostos_saida.py

import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

# (arquivo antigo, arquivo novo) — só os 2 comandos que precisam mudar.
COMANDOS_RENOMEADOS = [
    (
        RAIZ / 'impostos' / 'management' / 'commands' / 'importar_icms_por_ncm.py',
        RAIZ / 'impostos' / 'management' / 'commands' / 'importar_icms_saida_por_ncm_cst_origem.py',
    ),
    (
        RAIZ / 'impostos' / 'management' / 'commands' / 'importar_pis_cofins_por_ncm_cst.py',
        RAIZ / 'impostos' / 'management' / 'commands' / 'importar_pis_cofins_saida_por_ncm_cst.py',
    ),
]

# (arquivo, texto antigo, texto novo) — referências por nome de comando que
# precisam ser atualizadas depois do rename, pra não quebrar nada.
REFERENCIAS_PARA_ATUALIZAR = [
    (
        RAIZ / 'impostos' / 'management' / 'commands' / 'Sincronizar_Impostos_de_Saida.py',
        "'importar_icms_por_ncm'",
        "'importar_icms_saida_por_ncm_cst_origem'",
    ),
    (
        RAIZ / 'impostos' / 'management' / 'commands' / 'Sincronizar_Impostos_de_Saida.py',
        "'importar_pis_cofins_por_ncm_cst'",
        "'importar_pis_cofins_saida_por_ncm_cst'",
    ),
    (
        RAIZ / 'impostos' / 'management' / 'commands' / 'preencher_CST_produtos.py',
        'importar_icms_por_ncm, importar_pis_cofins_por_ncm_cst',
        'importar_icms_saida_por_ncm_cst_origem, importar_pis_cofins_saida_por_ncm_cst',
    ),
    (
        RAIZ / 'diagnosticar_produto.py',
        'importar_icms_por_ncm',
        'importar_icms_saida_por_ncm_cst_origem',
    ),
]


def renomear_arquivo(antigo: Path, novo: Path):
    if novo.exists() and not antigo.exists():
        print(f'  [já renomeado] {antigo.name} -> {novo.name} (pulando)')
        return
    if not antigo.exists():
        raise SystemExit(f'  [ERRO] Arquivo esperado não encontrado: {antigo}')
    if novo.exists():
        raise SystemExit(f'  [ERRO] Destino já existe, não vou sobrescrever: {novo}')

    resultado = subprocess.run(
        ['git', 'mv', str(antigo), str(novo)],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        raise SystemExit(f'  [ERRO] git mv falhou pra {antigo.name}:\n{resultado.stderr}')
    print(f'  [ok] {antigo.name} -> {novo.name}')


def atualizar_referencia(arquivo: Path, texto_antigo: str, texto_novo: str):
    conteudo = arquivo.read_text(encoding='utf-8')
    ocorrencias = conteudo.count(texto_antigo)

    if ocorrencias == 0:
        if texto_novo in conteudo:
            print(f'  [já atualizado] {arquivo.name}: "{texto_antigo}" (pulando)')
            return
        raise SystemExit(
            f'  [ERRO] "{texto_antigo}" não encontrado em {arquivo} — arquivo mudou desde o esperado, conferir na mão.'
        )
    if ocorrencias > 1:
        raise SystemExit(
            f'  [ERRO] "{texto_antigo}" aparece {ocorrencias}x em {arquivo} — esperava exatamente 1, '
            'conferir na mão antes de trocar (pra não trocar no lugar errado).'
        )

    arquivo.write_text(conteudo.replace(texto_antigo, texto_novo), encoding='utf-8')
    print(f'  [ok] {arquivo.name}: "{texto_antigo}" -> "{texto_novo}"')


def main():
    print('=== Etapa 8 — Renomeando os 2 comandos ===')
    for antigo, novo in COMANDOS_RENOMEADOS:
        renomear_arquivo(antigo, novo)

    print('\n=== Atualizando referências ao nome antigo ===')
    for arquivo, texto_antigo, texto_novo in REFERENCIAS_PARA_ATUALIZAR:
        if not arquivo.exists():
            raise SystemExit(f'  [ERRO] Arquivo esperado não encontrado: {arquivo}')
        atualizar_referencia(arquivo, texto_antigo, texto_novo)

    print('\n=== Concluído ===')
    print('Rode "python manage.py check" e "python manage.py makemigrations --check --dry-run" pra conferir.')
    print('Depois teste os 2 comandos com o nome novo (--empresa=MAGAZINE) e o Sincronizar_Impostos_de_Saida inteiro.')
    print('Esse script pode ser apagado depois de conferir.')


if __name__ == '__main__':
    main()