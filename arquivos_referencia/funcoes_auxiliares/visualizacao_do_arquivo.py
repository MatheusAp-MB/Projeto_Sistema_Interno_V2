# arquivos_referencia/funcoes_auxiliares/visualizacao_do_arquivo.py

# Função Objetivo: Prepara o "Ver arquivo" da tela "Arquivos de referência": abre um .xlsx (só na memória — nada em disco, nada em banco)
# e devolve tudo que a janela precisa para mostrar o arquivo "literalmente como se a pessoa o abrisse no Excel": nome, tamanho, de onde
# veio, uma tabela HTML por aba (tabela_do_visualizador.py) e os avisos (aba cortada, aba oculta, fórmula sem resultado salvo).
#
# * [DECISÃO, 16/10/2026] → Visualizador do arquivo bruto (pedido do Matheus). Dois arquivos podem ser vistos: o que JÁ ESTÁ no Drive
#   (lido do Drive na hora, igual ao botão de atualizar) e o que a pessoa acabou de ESCOLHER no computador (o navegador manda o arquivo de
#   novo; nada é guardado). Só leitura: ver o arquivo nunca grava no sistema nem no Drive.
# * [EXPLICAÇÃO] → O openpyxl é aberto 2 vezes só quando o arquivo tem fórmula: uma com os RESULTADOS (o que o Excel mostra) e outra com as
#   FÓRMULAS (para a barra de fórmulas e para a visão "Valor bruto"). Arquivo sem fórmula abre 1 vez só.
# * [IMPORTANTE] → As mesmas proteções da auditoria valem aqui (tamanho, zip seguro, só .xlsx — conferir_o_arquivo), mais um limite próprio:
#   o XML das abas aberto de uma vez (modo normal, necessário para mesclagens e cores) não pode passar de LIMITE_DE_XML_DAS_ABAS.
#   Qualquer problema vira ErroDeLeitura com texto pronto para a tela: o visualizador mostra o motivo no lugar da tabela, nunca quebra.

import io
import zipfile

import openpyxl

from .leitura_planilha import ErroDeLeitura, conferir_o_arquivo
from .relatorio_auditoria import formatar_tamanho
from .tabela_do_visualizador import (
    LIMITE_DE_CELULAS_NO_ARQUIVO, LIMITE_DE_COLUNAS_MOSTRADAS, LIMITE_DE_LINHAS_MOSTRADAS, Estilos, ler_cores_do_tema, montar_aba,
)

LIMITE_DE_XML_DAS_ABAS = 25 * 1024 * 1024
LIMITE_DE_ABAS_MOSTRADAS = 30

ORIGEM_DRIVE = 'drive'
ORIGEM_ESCOLHIDO = 'escolhido'


# Função Objetivo: O arquivo tem alguma fórmula? (procura "<f>" ou "<f " nas abas, sem interpretar o XML)
def _tem_formula(conteudo):
    with zipfile.ZipFile(io.BytesIO(conteudo)) as zip_:
        for parte in zip_.infolist():
            if parte.filename.startswith('xl/worksheets/') and parte.filename.endswith('.xml'):
                with zip_.open(parte) as arquivo:
                    resto = b''
                    while True:
                        pedaco = arquivo.read(1024 * 1024)
                        if not pedaco:
                            break
                        trecho = resto + pedaco
                        if b'<f>' in trecho or b'<f ' in trecho:
                            return True
                        resto = trecho[-3:]
    return False


def _conferir_o_xml_das_abas(conteudo):
    with zipfile.ZipFile(io.BytesIO(conteudo)) as zip_:
        total = sum(
            parte.file_size for parte in zip_.infolist()
            if parte.filename.startswith('xl/worksheets/') and parte.filename.endswith('.xml')
        )
    if total > LIMITE_DE_XML_DAS_ABAS:
        raise ErroDeLeitura(
            'As abas deste arquivo são grandes demais para serem mostradas na tela.',
            'Abra o arquivo no Excel. Se for o arquivo certo, avise o desenvolvedor.',
        )


def _abrir(conteudo, com_resultados):
    try:
        return openpyxl.load_workbook(io.BytesIO(conteudo), data_only=com_resultados, keep_links=False)
    except Exception:
        raise ErroDeLeitura(
            'Não consegui abrir este arquivo como planilha do Excel.',
            'Abra no Excel, salve de novo como .xlsx e tente outra vez.',
        )


# Função Objetivo: Do conteúdo do arquivo (bytes) para os dados da janela "Ver arquivo". Levanta ErroDeLeitura (texto pronto) se não der.
# `nome` é o nome do arquivo para mostrar; `origem` = ORIGEM_DRIVE | ORIGEM_ESCOLHIDO; `modificado_em` (datetime) só quando veio do Drive.
def montar_visualizacao(conteudo, nome, origem, modificado_em=None):
    conferir_o_arquivo(conteudo)
    _conferir_o_xml_das_abas(conteudo)

    com_formulas = _tem_formula(conteudo)
    valores = _abrir(conteudo, com_resultados=True)
    formulas = None
    try:
        formulas = _abrir(conteudo, com_resultados=False) if com_formulas else None
        return _montar(valores, formulas, conteudo, nome, origem, modificado_em)
    finally:
        valores.close()
        if formulas is not None:
            formulas.close()


def _montar(valores, formulas, conteudo, nome, origem, modificado_em):
    cores_do_tema = ler_cores_do_tema(getattr(valores, 'loaded_theme', None))
    estilos = Estilos()
    celulas_disponiveis = LIMITE_DE_CELULAS_NO_ARQUIVO

    visiveis = [aba for aba in valores.worksheets if aba.sheet_state == 'visible']
    ocultas = len(valores.worksheets) - len(visiveis)
    if not visiveis:
        raise ErroDeLeitura('O arquivo só tem abas ocultas.', 'Abra no Excel e exiba a aba que quer conferir.')
    aba_ativa = valores.active.title if valores.active is not None and valores.active.sheet_state == 'visible' else visiveis[0].title

    abas, avisos = [], []
    total_sem_resultado = 0
    for indice, aba in enumerate(visiveis[:LIMITE_DE_ABAS_MOSTRADAS]):
        pronta = montar_aba(aba, formulas[aba.title] if formulas is not None else None, estilos, cores_do_tema, celulas_disponiveis)
        celulas_disponiveis -= pronta['celulas']
        total_sem_resultado += pronta['formulas_sem_resultado']
        resumo = None
        if pronta['vazia']:
            resumo = 'Esta aba está vazia.'
        elif pronta['cortada']:
            resumo = _texto_do_corte(aba.title, pronta)
            avisos.append(resumo)
        abas.append({
            'indice': indice, 'nome': aba.title, 'ativa': aba.title == aba_ativa, 'html': pronta['html'],
            'linhas': pronta['linhas'], 'colunas': pronta['colunas'], 'resumo': resumo,
            'formulas_sem_resultado': pronta['formulas_sem_resultado'],
        })
    if not any(a['ativa'] for a in abas):
        abas[0]['ativa'] = True
    if len(visiveis) > LIMITE_DE_ABAS_MOSTRADAS:
        avisos.append(f'O arquivo tem {len(visiveis)} abas; só as primeiras {LIMITE_DE_ABAS_MOSTRADAS} são mostradas.')
    if ocultas:
        avisos.append(f'{ocultas} {"aba oculta não é mostrada" if ocultas == 1 else "abas ocultas não são mostradas"} (igual ao Excel).')
    if total_sem_resultado:
        avisos.append(
            f'{total_sem_resultado} {"célula tem fórmula" if total_sem_resultado == 1 else "células têm fórmula"} sem resultado salvo no arquivo '
            '(marcadas com um canto vermelho): o Excel recalcula ao abrir, mas o sistema lê essas células como vazias.'
        )

    css = estilos.css()
    if '<' in css or '>' in css:   # nunca acontece (só entram valores validados); se acontecer, melhor sem cor do que CSS suspeito
        css = ''
    return {
        'nome': nome, 'tamanho_texto': formatar_tamanho(len(conteudo)), 'origem': origem, 'modificado_em': modificado_em,
        'abas': abas, 'avisos': avisos, 'css': css, 'tem_formula': formulas is not None,
    }


def _texto_do_corte(nome_da_aba, pronta):
    limite_de_celulas = f'{LIMITE_DE_CELULAS_NO_ARQUIVO:,}'.replace(',', '.')
    if pronta['linhas'] == 0:
        return f'A aba “{nome_da_aba}” não coube na tela (limite de {limite_de_celulas} células por arquivo). O arquivo inteiro continua intacto.'
    if pronta['linhas'] < pronta['linhas_no_arquivo']:
        # Parou antes das LIMITE_DE_LINHAS_MOSTRADAS linhas: quem acabou foi o limite de células do arquivo todo.
        motivo = (
            f'limite de {limite_de_celulas} células por arquivo' if pronta['linhas'] < LIMITE_DE_LINHAS_MOSTRADAS
            else f'limite de {LIMITE_DE_LINHAS_MOSTRADAS} por aba'
        )
        return (
            f'A aba “{nome_da_aba}” tem {pronta["linhas_no_arquivo"]} linhas; a tela mostra as primeiras {pronta["linhas"]} '
            f'({motivo}). O arquivo inteiro continua intacto.'
        )
    return (
        f'A aba “{nome_da_aba}” tem mais colunas do que a tela mostra (limite de {LIMITE_DE_COLUNAS_MOSTRADAS}). '
        'O arquivo inteiro continua intacto.'
    )
