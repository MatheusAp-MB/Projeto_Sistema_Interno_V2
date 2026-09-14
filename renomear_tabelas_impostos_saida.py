# renomear_tabelas_impostos_saida.py

# Função Objetivo: Etapa 9 do roteiro de Impostos de Saída — renomeia as 4
# classes de model (e os arquivos que as guardam) pro nome final já fechado
# na Decisão de Nomenclatura das Tabelas (13/09/2026), e atualiza todo o
# código ativo que usa essas classes. NÃO mexe em nenhuma migration —
# migrations são histórico do Django, e a nova (delete+create, "recriar do
# zero", decisão do vault) é gerada por você via `makemigrations`
# interativo, não por este script. NÃO roda `migrate` nem apaga tabela
# nenhuma sozinho.
#
# Idempotente: rodar 2x não quebra — pula o que já está no estado novo.
#
# Rodar com: python renomear_tabelas_impostos_saida.py

import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

# --- 1) Arquivos de model: renomeados junto com a classe que guardam -------
MODELS_RENOMEADOS = [
    (
        RAIZ / 'impostos' / 'models' / 'saida' / 'icms_ncm_uf.py',
        RAIZ / 'impostos' / 'models' / 'saida' / 'icms_saida_por_ncm_cst_origem_uf.py',
    ),
    (
        RAIZ / 'impostos' / 'models' / 'saida' / 'pis_cofins_ncm_cst.py',
        RAIZ / 'impostos' / 'models' / 'saida' / 'pis_cofins_saida_por_ncm_cst.py',
    ),
    (
        RAIZ / 'impostos' / 'models' / 'saida' / 'icms_ncm_rejeitado.py',
        RAIZ / 'impostos' / 'models' / 'saida' / 'icms_saida_por_ncm_cst_origem_rejeitado.py',
    ),
    (
        RAIZ / 'impostos' / 'models' / 'saida' / 'pis_cofins_ncm_cst_rejeitado.py',
        RAIZ / 'impostos' / 'models' / 'saida' / 'pis_cofins_saida_por_ncm_cst_rejeitado.py',
    ),
]

# --- 2) Scripts avulsos já usados (Passo 1, exploração PIS/COFINS, truncar
#        de uma migração anterior) — nenhum é rotina, todos referenciam os
#        nomes antigos e vão quebrar se rodados de novo. Removidos
#        (recuperáveis pelo histórico do git se precisar de volta).
ARQUIVOS_MORTOS_PARA_REMOVER = [
    RAIZ / 'dividir_models_impostos.py',
    RAIZ / 'teste04.py',
    RAIZ / 'truncar_icms_ncm.py',
]

# --- 3) impostos/models/saida/__init__.py: caso especial — path do módulo
#        MUDOU (por causa do rename acima) junto com o nome da classe, não
#        dá pra tratar genérico igual o resto.
INIT_SAIDA = RAIZ / 'impostos' / 'models' / 'saida' / '__init__.py'
LINHAS_INIT_SAIDA = [
    (
        'from .icms_ncm_uf import IcmsNcmUf',
        'from .icms_saida_por_ncm_cst_origem_uf import IcmsSaidaPorNcmCstOrigemUf',
    ),
    (
        'from .pis_cofins_ncm_cst import PisCofinsNcmCst',
        'from .pis_cofins_saida_por_ncm_cst import PisCofinsSaidaPorNcmCst',
    ),
    (
        'from .icms_ncm_rejeitado import IcmsNcmRejeitado',
        'from .icms_saida_por_ncm_cst_origem_rejeitado import IcmsSaidaPorNcmCstOrigemRejeitado',
    ),
    (
        'from .pis_cofins_ncm_cst_rejeitado import PisCofinsNcmCstRejeitado',
        'from .pis_cofins_saida_por_ncm_cst_rejeitado import PisCofinsSaidaPorNcmCstRejeitado',
    ),
]

# --- 4) Troca genérica de nome de classe no resto do código ativo. Ordem
#        importa: PisCofinsNcmCst é prefixo de PisCofinsNcmCstRejeitado —
#        as versões "Rejeitado" vêm SEMPRE primeiro, senão a troca da base
#        corrompe o nome da versão rejeitada antes dela ser tratada.
ORDEM_DE_TROCA = [
    ('IcmsNcmRejeitado', 'IcmsSaidaPorNcmCstOrigemRejeitado'),
    ('PisCofinsNcmCstRejeitado', 'PisCofinsSaidaPorNcmCstRejeitado'),
    ('IcmsNcmUf', 'IcmsSaidaPorNcmCstOrigemUf'),
    ('PisCofinsNcmCst', 'PisCofinsSaidaPorNcmCst'),
]

# Caminhos JÁ NOVOS dos 4 arquivos de model (pós-rename) + todo o resto do
# código ativo que usa essas classes. Os 2 comandos de import usam o nome
# de arquivo JÁ RENOMEADO na Etapa 8 (importar_icms_saida_por_ncm_cst_origem.py
# e importar_pis_cofins_saida_por_ncm_cst.py) — não o nome antigo.
ARQUIVOS_PARA_TROCAR_CONTEUDO = [
    RAIZ / 'impostos' / 'models' / 'saida' / 'icms_saida_por_ncm_cst_origem_uf.py',
    RAIZ / 'impostos' / 'models' / 'saida' / 'pis_cofins_saida_por_ncm_cst.py',
    RAIZ / 'impostos' / 'models' / 'saida' / 'icms_saida_por_ncm_cst_origem_rejeitado.py',
    RAIZ / 'impostos' / 'models' / 'saida' / 'pis_cofins_saida_por_ncm_cst_rejeitado.py',
    RAIZ / 'impostos' / 'models' / '__init__.py',
    RAIZ / 'impostos' / 'funcoes_auxiliares' / 'saida' / 'exibicao_auditoria_fiscal.py',
    RAIZ / 'impostos' / 'funcoes_auxiliares' / 'saida' / 'exibicao_icms_por_ncm.py',
    RAIZ / 'impostos' / 'funcoes_auxiliares' / 'saida' / 'exibicao_pis_cofins_por_ncm_cst.py',
    RAIZ / 'impostos' / 'funcoes_auxiliares' / 'saida' / 'importacao_icms_ncm.py',
    RAIZ / 'impostos' / 'funcoes_auxiliares' / 'saida' / 'importacao_pis_cofins_ncm_cst.py',
    RAIZ / 'impostos' / 'funcoes_auxiliares' / 'saida' / 'motivo_impostos_saida.py',
    RAIZ / 'impostos' / 'funcoes_auxiliares' / 'saida' / 'preenchimento_impostos_saida.py',
    RAIZ / 'impostos' / 'management' / 'commands' / 'importar_icms_saida_por_ncm_cst_origem.py',
    RAIZ / 'impostos' / 'management' / 'commands' / 'importar_pis_cofins_saida_por_ncm_cst.py',
    RAIZ / 'impostos' / 'management' / 'commands' / 'preencher_impostos_saida.py',
    RAIZ / 'diagnosticar_produto.py',
    RAIZ / 'validar_impostos_saida.py',
]


def git(*args):
    resultado = subprocess.run(['git', *args], cwd=RAIZ, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise SystemExit(f'  [ERRO] git {" ".join(args)} falhou:\n{resultado.stderr}')


def renomear_model(antigo: Path, novo: Path):
    if novo.exists() and not antigo.exists():
        print(f'  [já renomeado] {antigo.name} -> {novo.name} (pulando)')
        return
    if not antigo.exists():
        raise SystemExit(f'  [ERRO] Arquivo esperado não encontrado: {antigo}')
    if novo.exists():
        raise SystemExit(f'  [ERRO] Destino já existe, não vou sobrescrever: {novo}')
    git('mv', str(antigo), str(novo))
    print(f'  [ok] {antigo.name} -> {novo.name}')


def remover_arquivo_morto(arquivo: Path):
    if not arquivo.exists():
        print(f'  [já removido] {arquivo.name} (pulando)')
        return
    git('rm', str(arquivo))
    print(f'  [ok] removido {arquivo.name}')


def atualizar_linha_exata(arquivo: Path, texto_antigo: str, texto_novo: str):
    conteudo = arquivo.read_text(encoding='utf-8')
    ocorrencias = conteudo.count(texto_antigo)

    if ocorrencias == 0:
        if texto_novo in conteudo:
            print(f'    [já atualizado] "{texto_antigo}" (pulando)')
            return
        raise SystemExit(f'    [ERRO] "{texto_antigo}" não encontrado em {arquivo}.')
    if ocorrencias > 1:
        raise SystemExit(f'    [ERRO] "{texto_antigo}" aparece {ocorrencias}x em {arquivo} — esperava 1.')

    arquivo.write_text(conteudo.replace(texto_antigo, texto_novo), encoding='utf-8')
    print(f'    [ok] "{texto_antigo}" -> "{texto_novo}"')


def trocar_classes_no_arquivo(arquivo: Path):
    if not arquivo.exists():
        raise SystemExit(f'  [ERRO] Arquivo esperado não encontrado: {arquivo}')

    conteudo = arquivo.read_text(encoding='utf-8')
    total_trocado = 0

    for nome_antigo, nome_novo in ORDEM_DE_TROCA:
        qtd = conteudo.count(nome_antigo)
        if qtd:
            conteudo = conteudo.replace(nome_antigo, nome_novo)
            total_trocado += qtd

    if total_trocado == 0:
        print(f'  [sem ocorrência] {arquivo.relative_to(RAIZ)} (pulando — já atualizado?)')
        return

    arquivo.write_text(conteudo, encoding='utf-8')
    print(f'  [ok] {arquivo.relative_to(RAIZ)} — {total_trocado} ocorrência(s) trocada(s)')


def main():
    print('=== Etapa 9 — Renomeando os 4 arquivos de model ===')
    for antigo, novo in MODELS_RENOMEADOS:
        renomear_model(antigo, novo)

    print('\n=== Removendo os 3 scripts avulsos já usados (mortos) ===')
    for arquivo in ARQUIVOS_MORTOS_PARA_REMOVER:
        remover_arquivo_morto(arquivo)

    print('\n=== Atualizando impostos/models/saida/__init__.py (path + classe) ===')
    if not INIT_SAIDA.exists():
        raise SystemExit(f'  [ERRO] Arquivo esperado não encontrado: {INIT_SAIDA}')
    for texto_antigo, texto_novo in LINHAS_INIT_SAIDA:
        atualizar_linha_exata(INIT_SAIDA, texto_antigo, texto_novo)

    print('\n=== Trocando as classes no resto do código ativo ===')
    for arquivo in ARQUIVOS_PARA_TROCAR_CONTEUDO:
        trocar_classes_no_arquivo(arquivo)

    print('\n=== Concluído ===')
    print('Migrations NÃO foram tocadas — próximos passos manuais:')
    print('  1) python manage.py makemigrations')
    print('     Django deve perguntar, pra cada 1 das 4 classes: "Did you rename')
    print('     model impostos.X to impostos.Y? [y/N]" — responda N nas 4 (decisão')
    print('     do vault: recriar do zero, não RenameModel cirúrgico).')
    print('  2) python manage.py migrate --database=magazine')
    print('     python manage.py migrate --database=samvale')
    print('     -> ATENÇÃO: isso APAGA as 4 tabelas antigas (com o dado que tiverem)')
    print('     e cria as 4 novas vazias, nas 2 empresas.')
    print('  3) python manage.py Sincronizar_Impostos_de_Saida --empresa=MAGAZINE')
    print('     python manage.py Sincronizar_Impostos_de_Saida --empresa=SAMVALE')
    print('     -> repopula as 4 tabelas + os 5 campos fiscais do Produto, do zero.')
    print('  4) python manage.py check')
    print('Esse script pode ser apagado depois de conferir.')


if __name__ == '__main__':
    main()