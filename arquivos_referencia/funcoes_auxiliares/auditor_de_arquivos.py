# arquivos_referencia/funcoes_auxiliares/auditor_de_arquivos.py

# Função Objetivo: Ponto de entrada ÚNICO da auditoria: recebe o arquivo de referência escolhido (do catálogo) e os
# bytes que a pessoa enviou, e devolve o RelatorioDeAuditoria pronto para a tela. Não grava nada (nem em disco,
# nem no Drive, nem no banco): o arquivo só existe na memória durante a conferência.
#
# * [EXPLICAÇÃO] → Dois tipos de "problema" são tratados de jeitos diferentes:
#   - problema NO ARQUIVO (não é planilha, está protegido por senha, colunas fora do lugar...): vira conteúdo do
#     relatório — a pessoa vê na tela o que corrigir. Nunca é exceção.
#   - problema NO SISTEMA (bug de um auditor, módulo faltando): a exceção sobe até a view, que registra o erro no
#     log e avisa por toast. Não se esconde um bug dentro de um relatório "bonito".

import importlib

from .leitura_planilha import ErroDeLeitura, ler_planilha
from .relatorio_auditoria import RelatorioDeAuditoria


# Função Objetivo: Carrega a classe do auditor a partir do texto "modulo:Classe" do catálogo (só importa quando precisa).
def _carregar_auditor(arquivo):
    nome_do_modulo, nome_da_classe = arquivo.classe_do_auditor.split(':')
    modulo = importlib.import_module(f'{__package__}.{nome_do_modulo}')
    return getattr(modulo, nome_da_classe)


# Função Objetivo: Audita 1 arquivo. `arquivo` é um ArquivoDeReferencia do catálogo; `conteudo` são os bytes enviados.
# `tamanho_em_bytes` é o tamanho REAL do arquivo (a tela lê só o começo de um arquivo enorme, então o tamanho exibido não pode sair de `conteudo`).
def auditar_arquivo(arquivo, conteudo, nome_do_arquivo_enviado, tamanho_em_bytes=None):
    if not arquivo.auditoria_pronta or not arquivo.classe_do_auditor:
        raise ValueError(f'O arquivo “{arquivo.id}” ainda não tem auditoria.')

    relatorio = RelatorioDeAuditoria(nome_do_arquivo_enviado, len(conteudo) if tamanho_em_bytes is None else tamanho_em_bytes)
    try:
        leitura = ler_planilha(conteudo, arquivo.limite_de_linhas)
    except ErroDeLeitura as problema:
        relatorio.nao_conseguiu_ler(problema.o_que, problema.como_corrigir)
        return relatorio

    auditor = _carregar_auditor(arquivo)(leitura, relatorio)
    auditor.auditar()
    return relatorio
