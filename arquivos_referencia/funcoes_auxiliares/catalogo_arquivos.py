# arquivos_referencia/funcoes_auxiliares/catalogo_arquivos.py

# Função Objetivo: Lista FECHADA dos arquivos de referência que a tela "Arquivos de referência" conhece: o que é
# cada um, para que serve, que formato o sistema espera e qual auditor o confere. A tela monta os cartões a partir
# daqui — nada de nome de arquivo vindo do navegador entra em caminho nenhum (só os ids desta lista).
#
# * [DECISÃO, 14/10/2026] → Os 6 arquivos de referência (Grupo A da frente "Rotina Vira Botão"): 4 tabelas de frete
#   (Mercado Livre, Magalu, TikTok Shop, Amazon) e 2 planilhas Busca Legal (MAGAZINE e SAMVALE). Quase nunca mudam.
# * [DECISÃO, 15/10/2026] → 1º ciclo: as 4 tabelas de frete. 2º ciclo (mesmo dia): as 2 planilhas Busca Legal. Com isso os
#   6 arquivos têm auditoria. (O estado "Em breve" da tela fica pronto para qualquer arquivo novo que entre sem auditoria.)
# * [EXPLICAÇÃO] → `nome_no_drive` é o nome FIXO que o arquivo tem no Drive (o mesmo que os importadores do popular
#   banco procuram hoje na pasta): quem escolhe o arquivo pode ter qualquer nome, o que vai para o Drive sempre usa este.
# * [DECISÃO, 15/10/2026] → 3º ciclo: ENVIO ao Drive. Cada grupo tem uma subpasta fixa dentro da pasta raiz do sistema
#   (GOOGLE_DRIVE_PASTA_RAIZ_SISTEMA no .env) — os nomes são os que Matheus criou no Drive em 14/10/2026.

from dataclasses import dataclass

from .leitura_planilha import LIMITE_DE_LINHAS_POR_ABA

GRUPO_FRETE = 'frete'
GRUPO_IMPOSTOS_SAIDA = 'impostos_saida'

TITULOS_DOS_GRUPOS = {
    GRUPO_FRETE: 'Tabelas de frete',
    GRUPO_IMPOSTOS_SAIDA: 'Impostos de saída — Busca Legal',
}

# A Busca Legal tem 1 linha por produto (hoje ~650 na Magazine e ~400 na Samvale): folga grande, mas ainda longe de "planilha de outra coisa".
LIMITE_DE_LINHAS_BUSCA_LEGAL = 20000

# Nome EXATO da subpasta do Drive de cada grupo (dentro da pasta raiz do sistema). Se não existir na hora do envio, é criada.
PASTAS_NO_DRIVE_POR_GRUPO = {
    GRUPO_FRETE: 'Tabelas de Frete',
    GRUPO_IMPOSTOS_SAIDA: 'Tabelas de Impostos de Saida',
}

SUBTITULOS_DOS_GRUPOS = {
    GRUPO_FRETE: 'Valem para as duas empresas. O “popular banco” lê estes arquivos para calcular as grades.',
    GRUPO_IMPOSTOS_SAIDA: 'Um arquivo por empresa. Alimenta ICMS, PIS e COFINS de saída. A conferência consulta os produtos do sistema (só leitura).',
}


@dataclass(frozen=True)
class ArquivoDeReferencia:
    id: str                 # vai na URL (só letras minúsculas e "-")
    grupo: str
    nome: str
    icone: str              # classe do Font Awesome
    para_que_serve: str
    formato_esperado: str
    nome_no_drive: str
    auditoria_pronta: bool
    classe_do_auditor: str = ''     # "módulo:Classe" dentro de funcoes_auxiliares (importado só quando precisa)
    limite_de_linhas: int = LIMITE_DE_LINHAS_POR_ABA   # tabela de frete é pequena; a Busca Legal tem 1 linha por produto

    # Subpasta do Drive onde este arquivo mora (decidida pelo grupo).
    @property
    def pasta_no_drive(self):
        return PASTAS_NO_DRIVE_POR_GRUPO[self.grupo]


ARQUIVOS = (
    ArquivoDeReferencia(
        id='frete-mercado-livre', grupo=GRUPO_FRETE, nome='Frete — Mercado Livre', icone='fa-truck',
        para_que_serve='Frete do Mercado Livre por faixa de peso × faixa de preço × regime (com e sem Frete Grátis Rápido).',
        formato_esperado='1 aba · colunas A a M · 2 linhas por faixa de peso (1 por regime) · 8 faixas de preço no cabeçalho.',
        nome_no_drive='Tabela_Frete_Mercado_Livre.xlsx', auditoria_pronta=True,
        classe_do_auditor='auditoria_frete_ml:AuditorFreteML',
    ),
    ArquivoDeReferencia(
        id='frete-magalu', grupo=GRUPO_FRETE, nome='Frete — Magalu', icone='fa-truck',
        para_que_serve='Frete do Magalu por faixa de peso e reputação do vendedor (<92%, 92–97%, >97%).',
        formato_esperado='1 aba · colunas A a F · 1 linha por faixa de peso · 3 colunas de valor (uma por reputação).',
        nome_no_drive='Tabela_Frete_Magalu.xlsx', auditoria_pronta=True,
        classe_do_auditor='auditoria_frete_magalu:AuditorFreteMagalu',
    ),
    ArquivoDeReferencia(
        id='frete-tiktok-shop', grupo=GRUPO_FRETE, nome='Frete — TikTok Shop', icone='fa-truck',
        para_que_serve='Frete do TikTok Shop por faixa de peso (valor médio).',
        formato_esperado='1 aba · colunas A a D · 1 linha por faixa de peso.',
        nome_no_drive='Tabela_Frete_Tiktok_Shop.xlsx', auditoria_pronta=True,
        classe_do_auditor='auditoria_frete_tiktok:AuditorFreteTiktok',
    ),
    ArquivoDeReferencia(
        id='frete-amazon', grupo=GRUPO_FRETE, nome='Frete — Amazon', icone='fa-truck',
        para_que_serve='Frete da Amazon (DBA e FBA) por faixa de peso × faixa de preço.',
        formato_esperado='2 abas com nome exato: “Frete Amazon_DBA” e “Frete Amazon_FBA” · colunas A a E · 1 linha por combinação.',
        nome_no_drive='Tabela_Frete_Amazon.xlsx', auditoria_pronta=True,
        classe_do_auditor='auditoria_frete_amazon:AuditorFreteAmazon',
    ),
    ArquivoDeReferencia(
        id='busca-legal-magazine', grupo=GRUPO_IMPOSTOS_SAIDA, nome='Busca Legal — Magazine (MB)', icone='fa-file-invoice-dollar',
        para_que_serve='ICMS, PIS, COFINS e CST de saída por produto (casado pelo EAN) da empresa Magazine.',
        formato_esperado='Aba ativa · cabeçalho na linha 2 · colunas Cód Barras, NCM, CST, PIS, COFINS e as 27 UFs (AC a TO).',
        nome_no_drive='TABELA SAIDA POR UF MAGAZINE.xlsx', auditoria_pronta=True,
        classe_do_auditor='auditoria_busca_legal:AuditorBuscaLegalMagazine', limite_de_linhas=LIMITE_DE_LINHAS_BUSCA_LEGAL,
    ),
    ArquivoDeReferencia(
        id='busca-legal-samvale', grupo=GRUPO_IMPOSTOS_SAIDA, nome='Busca Legal — Samvale (SV)', icone='fa-file-invoice-dollar',
        para_que_serve='ICMS, PIS, COFINS e CST de saída por produto (casado pelo EAN) da empresa Samvale.',
        formato_esperado='Aba ativa · cabeçalho na linha 2 · colunas Cód Barras, NCM, CST, PIS, COFINS e as 27 UFs (AC a TO).',
        nome_no_drive='TABELA SAIDA POR UF SAMVALE.xlsx', auditoria_pronta=True,
        classe_do_auditor='auditoria_busca_legal:AuditorBuscaLegalSamvale', limite_de_linhas=LIMITE_DE_LINHAS_BUSCA_LEGAL,
    ),
)

_POR_ID = {arquivo.id: arquivo for arquivo in ARQUIVOS}


def buscar_arquivo(id_do_arquivo):
    return _POR_ID.get(id_do_arquivo)


# Função Objetivo: Os arquivos agrupados na ordem da tela: [(id_do_grupo, titulo, subtitulo, [arquivos])].
def arquivos_por_grupo():
    grupos = []
    for id_do_grupo in (GRUPO_FRETE, GRUPO_IMPOSTOS_SAIDA):
        grupos.append((
            id_do_grupo, TITULOS_DOS_GRUPOS[id_do_grupo], SUBTITULOS_DOS_GRUPOS[id_do_grupo],
            [a for a in ARQUIVOS if a.grupo == id_do_grupo],
        ))
    return grupos
