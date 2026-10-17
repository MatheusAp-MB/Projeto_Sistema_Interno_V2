# arquivos_referencia/funcoes_auxiliares/recalculo_das_grades.py

# Função Objetivo: PASSO 3 da tela "Arquivos de referência" — depois de "Atualizar o sistema com o Drive" gravar uma tabela de frete ou os impostos
# dos produtos, recalcular as GRADES DE PREÇO que usam o que mudou. Roda a MESMA calculadora do terminal (calcular_grade_precificacao_<marketplace>),
# para 1 grade e 1 EMPRESA por vez, e devolve os números prontos para a tela (linhas criadas, atualizadas, removidas, sem preço, erros, tempo).
#
# * [DECISÃO, 16/10/2026] → Ciclo 3 da "Rotina Vira Botão": só as grades LOCAIS (Magalu, TikTok Shop, Amazon, Raia e Shopee). A grade do Mercado
#   Livre fica de fora de propósito: ela chama a API do ML (simular frete) para cada produto, e a regra do Matheus é gastar o mínimo possível de
#   chamadas da API — por isso ela ganha um ciclo próprio, com confirmação e estimativa de chamadas antes de rodar.
# * [DECISÃO, 16/10/2026] → O que recalcula o quê (só quando o arquivo realmente mudou alguma coisa; "já estava em dia" não recalcula nada):
#   frete Magalu → grade Magalu; frete TikTok → grade TikTok; frete Amazon → grade Amazon; planilha Busca Legal com produtos de imposto
#   alterado → as 5 grades locais (todas usam o ICMS, o PIS e o COFINS do produto). Frete do Mercado Livre e impostos também afetam a grade do ML,
#   que continua com aviso até o ciclo dela.
# * [EXPLICAÇÃO] → 1 pedido por grade, uma depois da outra (o JS da tela): cada grade mostra o resultado dela, e uma que falha não derruba as outras.
#   Cada grade roda dentro de UMA transação do banco da empresa: ou fica toda nova, ou nada muda (as grades Raia e Shopee, que no terminal gravam sem
#   transação, aqui também ficam "tudo ou nada").
# * [EXPLICAÇÃO] → Só o banco da empresa pedida é lido e gravado. O ORM escolhe o banco pela empresa ativa da requisição (EmpresaRouter): por isso a
#   empresa pedida é definida como ativa durante o cálculo e a original é SEMPRE devolvida no fim (igual a atualizacao_do_sistema.py).
# * [IMPORTANTE] → As calculadoras ligam o registro de consultas do banco (`connection.force_debug_cursor`) para contar SQL no terminal. Num servidor
#   isso deixaria o registro ligado para sempre naquela conexão; aqui o estado anterior é devolvido no fim (as calculadoras em si não foram mexidas).
# * [IMPORTANTE] → Trava por (grade, empresa): dois cliques (ou duas abas) não recalculam a mesma grade da mesma empresa ao mesmo tempo. Vale dentro de
#   1 processo do servidor; o que protege o banco de verdade é a transação.
# * [EXPLICAÇÃO] → "Removidas" só existe nas grades que ESPELHAM o cálculo (Magalu, TikTok, Amazon: combinação que deixou de ter preço perde a linha antiga,
#   ver gravar_grade_precificacao.py). Raia e Shopee não apagam linha antiga (como no terminal): o resultado diz isso quando há combinação sem preço.

import importlib
import logging
import threading
import time
from dataclasses import dataclass

from django.core.management.color import no_style
from django.db import connections, transaction

from core.empresa import ALIAS_BANCO_POR_EMPRESA, EMPRESAS_VALIDAS, definir_empresa_ativa, obter_empresa_ativa

from .historico_da_atualizacao import NOMES_CURTOS_DAS_EMPRESAS

logger = logging.getLogger(__name__)

PACOTE_DAS_CALCULADORAS = 'precificacao.funcoes_auxiliares'
MAXIMO_DE_EXEMPLOS_DE_ERRO = 5
TAMANHO_MAXIMO_DO_EXEMPLO = 180

# Resultado de 1 GRADE (a tela mostra ícone + texto para cada um).
STATUS_GRADE_RECALCULADA = 'ok'
STATUS_GRADE_OCUPADA = 'ocupado'            # já tem um recálculo desta grade, nesta empresa, em andamento
STATUS_GRADE_FALHOU = 'falha_sistema'       # erro do sistema: a transação foi desfeita, a grade continua como estava


@dataclass(frozen=True)
class GradeLocal:
    id: str
    nome: str
    modulo: str     # módulo da calculadora, dentro de PACOTE_DAS_CALCULADORAS
    funcao: str     # a MESMA função que o comando de terminal chama
    espelha: bool   # True = grava com gravar_grade_espelhando_o_calculo (apaga a linha antiga de quem ficou sem preço)


# Na ordem em que a janela mostra. É a lista FECHADA do que a tela recalcula hoje (a grade do ML não está aqui de propósito).
GRADES_LOCAIS = (
    GradeLocal('magalu', 'Magalu', 'magalu.calcular_grade_precificacao_magalu', 'calcular_grade_precificacao_magalu', True),
    GradeLocal('tiktok', 'TikTok Shop', 'tiktok.calcular_grade_precificacao_tiktok', 'calcular_grade_precificacao_tiktok', True),
    GradeLocal('amazon', 'Amazon', 'amazon.calcular_grade_precificacao_amazon', 'calcular_grade_precificacao_amazon', True),
    GradeLocal('raia', 'Raia', 'raia.calcular_grade_precificacao_raia', 'calcular_grade_precificacao_raia', False),
    GradeLocal('shopee', 'Shopee', 'shopee.calcular_grade_precificacao_shopee', 'calcular_grade_precificacao_shopee', False),
)

_GRADES_POR_ID = {grade.id: grade for grade in GRADES_LOCAIS}

# id do cartão do FRETE (catalogo_arquivos.py) -> grades locais que usam essa tabela.
GRADES_DO_FRETE = {
    'frete-magalu': ('magalu',),
    'frete-tiktok-shop': ('tiktok',),
    'frete-amazon': ('amazon',),
}
FRETE_QUE_AFETA_A_GRADE_DO_ML = 'frete-mercado-livre'
NOME_DA_GRADE_DO_ML = 'Mercado Livre'

# Cada (grade, empresa) tem a sua trava (a Magazine e a Samvale podem recalcular a mesma grade ao mesmo tempo: são bancos separados).
_TRAVA_GERAL = threading.Lock()
_TRAVAS_POR_GRADE_E_EMPRESA = {}


def _trava_da_grade(id_da_grade, empresa):
    with _TRAVA_GERAL:
        return _TRAVAS_POR_GRADE_E_EMPRESA.setdefault((id_da_grade, empresa), threading.Lock())


# Função Objetivo: Onde as calculadoras escrevem "[GRADE TIKTOK] ... 200/1500 produtos": aqui ninguém lê, então se descarta (o resultado vai para a tela).
class SaidaSilenciosa:

    def write(self, *_, **__):
        return 0

    def flush(self):
        pass


def buscar_grade(id_da_grade):
    return _GRADES_POR_ID.get(id_da_grade)


# Função Objetivo: Depois de gravar UM arquivo, quais grades locais precisam ser recalculadas — e se a grade do ML também ficou desatualizada.
# `da_empresa` = o resultado dessa empresa devolvido por quem gravou (_gravar_na_empresa); só se chama com a gravação feita e com algo mudado.
# Devolve (ids das grades locais na ordem da tela, a grade do ML ficou desatualizada?).
def grades_afetadas(id_do_arquivo, e_busca_legal, da_empresa):
    if e_busca_legal:
        # Os preços usam o ICMS/PIS/COFINS que ficam no produto: só uma mudança NO PRODUTO (ou produto que perdeu o CST) muda preço.
        if da_empresa.get('produtos_mudaram') or da_empresa.get('produtos_perderam_cst'):
            return tuple(grade.id for grade in GRADES_LOCAIS), True
        return (), False
    ids = GRADES_DO_FRETE.get(id_do_arquivo, ())
    return tuple(grade.id for grade in GRADES_LOCAIS if grade.id in ids), id_do_arquivo == FRETE_QUE_AFETA_A_GRADE_DO_ML


def _carregar_calculadora(grade):
    modulo = importlib.import_module(f'{PACOTE_DAS_CALCULADORAS}.{grade.modulo}')
    return getattr(modulo, grade.funcao)


def _nome_da_empresa(empresa):
    return NOMES_CURTOS_DAS_EMPRESAS.get(empresa, empresa.title())


def _resultado_base(grade, empresa, status, mensagem='', **extras):
    return {
        'grade_id': grade.id, 'nome': grade.nome, 'espelha': grade.espelha, 'empresa': empresa, 'empresa_nome': _nome_da_empresa(empresa),
        'status': status, 'mensagem': mensagem, 'segundos': 0.0,
        'criadas': 0, 'atualizadas': 0, 'removidas': None, 'sem_calculo': 0,
        'total_de_erros': 0, 'exemplos_de_erro': [], 'exemplos_ocultos': 0, **extras,
    }


# Função Objetivo: Resultado para um erro do PRÓPRIO sistema (bug) que escapou: a view usa quando o resto quebrou.
def resultado_de_falha_da_grade(grade, empresa):
    return _resultado_base(
        grade, empresa, STATUS_GRADE_FALHOU,
        'Erro do próprio sistema ao recalcular. Nada foi gravado: a grade continua com os preços de antes. Veja o terminal do servidor.',
    )


def _cortar_erros(erros):
    exemplos = [str(erro)[:TAMANHO_MAXIMO_DO_EXEMPLO] for erro in erros[:MAXIMO_DE_EXEMPLOS_DE_ERRO]]
    return exemplos, max(0, len(erros) - len(exemplos))


# Função Objetivo: Recalcula UMA grade local de UMA empresa. `grade` é um GradeLocal e `empresa` é a empresa selecionada na tela (a view já conferiu).
# Falha PREVISTA (já tem outro recálculo igual em andamento) e erro do sistema viram resultado (para a tela); só pedido inválido sobe como exceção.
def recalcular_grade(grade, empresa):
    if empresa not in EMPRESAS_VALIDAS:
        raise ValueError(f'Empresa desconhecida: {empresa!r}')
    if grade.id not in _GRADES_POR_ID:
        raise ValueError(f'Grade desconhecida: {grade.id!r}')
    nome = _nome_da_empresa(empresa)

    trava = _trava_da_grade(grade.id, empresa)
    if not trava.acquire(blocking=False):
        return _resultado_base(
            grade, empresa, STATUS_GRADE_OCUPADA,
            f'Já tem um recálculo desta grade na {nome} em andamento (outra pessoa ou outra aba). Espere terminar e tente de novo.',
        )
    try:
        return _rodar_a_calculadora(grade, empresa)
    finally:
        trava.release()


def _rodar_a_calculadora(grade, empresa):
    alias = ALIAS_BANCO_POR_EMPRESA[empresa]
    nome = _nome_da_empresa(empresa)
    calculadora = _carregar_calculadora(grade)
    conexoes = [connections[alias_da_conexao] for alias_da_conexao in {'default', *ALIAS_BANCO_POR_EMPRESA.values()}]
    registro_ligado_antes = {conexao.alias: conexao.force_debug_cursor for conexao in conexoes}

    empresa_da_requisicao = obter_empresa_ativa()
    definir_empresa_ativa(empresa)
    inicio = time.perf_counter()
    try:
        with transaction.atomic(using=alias):
            numeros = calculadora(SaidaSilenciosa(), no_style())
    except Exception:
        logger.exception('Recálculo da grade %s na empresa %s falhou', grade.id, empresa)
        resultado = resultado_de_falha_da_grade(grade, empresa)
        resultado['segundos'] = time.perf_counter() - inicio
        return resultado
    finally:
        definir_empresa_ativa(empresa_da_requisicao)
        for conexao in conexoes:
            if not registro_ligado_antes[conexao.alias]:
                conexao.force_debug_cursor = False
                conexao.queries_log.clear()

    exemplos, ocultos = _cortar_erros(numeros['erros'])
    return _resultado_base(
        grade, empresa, STATUS_GRADE_RECALCULADA, f'Grade do {grade.nome} da {nome} recalculada.',
        segundos=time.perf_counter() - inicio, criadas=numeros['criadas'], atualizadas=numeros['atualizadas'], removidas=numeros['removidas'],
        sem_calculo=numeros['sem_calculo'], total_de_erros=len(numeros['erros']), exemplos_de_erro=exemplos, exemplos_ocultos=ocultos,
    )
