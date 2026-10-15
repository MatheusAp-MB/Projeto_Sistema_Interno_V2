# arquivos_referencia/funcoes_auxiliares/catalogo_arquivos.py

# Função Objetivo: Lista FECHADA dos arquivos de referência que a tela "Arquivos de referência" conhece: o que é
# cada um, para que serve, que formato o sistema espera e qual auditor o confere. A tela monta os cartões a partir
# daqui — nada de nome de arquivo vindo do navegador entra em caminho nenhum (só os ids desta lista).
#
# * [DECISÃO, 14/10/2026] → Os 6 arquivos de referência (Grupo A da frente "Rotina Vira Botão"): 4 tabelas de frete
#   (Mercado Livre, Magalu, TikTok Shop, Amazon) e 2 planilhas Busca Legal (MAGAZINE e SAMVALE). Quase nunca mudam.
# * [DECISÃO, 15/10/2026] → 1º ciclo: só as 4 tabelas de frete têm auditoria. Busca Legal aparece na tela, marcada
#   como "auditoria na próxima etapa", para a pessoa ver o desenho completo.
# * [EXPLICAÇÃO] → `nome_no_drive` é o nome FIXO que o arquivo terá no Drive (o mesmo que os importadores do popular
#   banco procuram hoje na pasta). Nesta etapa ele só informa; o envio ao Drive vem depois.

from dataclasses import dataclass

GRUPO_FRETE = 'frete'
GRUPO_IMPOSTOS_SAIDA = 'impostos_saida'

TITULOS_DOS_GRUPOS = {
    GRUPO_FRETE: 'Tabelas de frete',
    GRUPO_IMPOSTOS_SAIDA: 'Impostos de saída — Busca Legal',
}

SUBTITULOS_DOS_GRUPOS = {
    GRUPO_FRETE: 'Valem para as duas empresas. O “popular banco” lê estes arquivos para calcular as grades.',
    GRUPO_IMPOSTOS_SAIDA: 'Um arquivo por empresa. Alimenta ICMS, PIS e COFINS de saída.',
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
        formato_esperado='1 aba · 1 linha por produto · ICMS por UF de destino (27 colunas).',
        nome_no_drive='TABELA SAIDA POR UF MAGAZINE.xlsx', auditoria_pronta=False,
    ),
    ArquivoDeReferencia(
        id='busca-legal-samvale', grupo=GRUPO_IMPOSTOS_SAIDA, nome='Busca Legal — Samvale (SV)', icone='fa-file-invoice-dollar',
        para_que_serve='ICMS, PIS, COFINS e CST de saída por produto (casado pelo EAN) da empresa Samvale.',
        formato_esperado='1 aba · 1 linha por produto · ICMS por UF de destino (27 colunas).',
        nome_no_drive='TABELA SAIDA POR UF SAMVALE.xlsx', auditoria_pronta=False,
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
