# api_sysemp/analise_estoque_full.py

# Função Objetivo: Contexto "Análise de estoque do Full" — sabe o que o ClienteApiSysemp (transporte puro) não deve saber: qual endpoint
# chamar (listarAnaliseEstoqueFull), que ele pagina por "offset" e como juntar todas as páginas numa lista só. Compõe um ClienteApiSysemp
# (nunca herda dele) e devolve as linhas CRUAS, exatamente como a Sysemp mandou (campos em texto, SKU com espaço, linha sem SKU...): quem
# limpa e organiza o dado é a primeira função que o recebe, do lado de quem usa (ver "Integridade e Fonte Unica de Dado" no vault).
# Ver também "Padrao de Robustez para Clientes de API Externa" (nunca assumir que 1 chamada traz tudo).
#
# * [EXPLICAÇÃO] → Só a PRIMEIRA página (100 linhas) foi testada de verdade até hoje (10/10/2026). Como a API devolve só as linhas com estoque
#                  maior que zero, ninguém sabe ainda quantas páginas existem, nem como ela avisa que o offset passou do fim. Por isso o laço
#                  abaixo NÃO confia em nada disso: avança o offset pelo tamanho REAL de cada página recebida e para em 1 de 4 situações —
#                  (1) página vazia (o fim normal); (2) a API devolveu só linhas que já tinham vindo (ela estaria ignorando o offset: sem esta
#                  guarda o laço nunca terminaria); (3) o limite de segurança de páginas; (4) resposta fora do formato esperado DEPOIS da
#                  1ª página (a coleta é entregue marcada como INCOMPLETA, com o trecho da resposta, em vez de jogar fora as páginas boas).
#                  Resposta fora do formato já na 1ª página é erro de verdade (ex.: "Metodo não Localizado", que a Magazine devolve).

import json
from dataclasses import dataclass, field

from .core.excecoes import ErroNegocioSysemp

METODO = 'listarAnaliseEstoqueFull'

# * [EXPLICAÇÃO] → A doc de exemplo da Sysemp chama este método "sem limite de tempo" (e o exemplo dela só mostra o pedido, não a resposta).
#                  O cliente padrão espera 30 s; aqui são 120 s, o mesmo prazo do script de exploração (scripts_exploracao_ERP).
TIMEOUT_SEGUNDOS = 120

# Teto de segurança (100 linhas por página => 50.000 linhas): só existe para o laço nunca rodar para sempre.
MAXIMO_PAGINAS = 500

# Tamanho máximo do trecho da resposta guardado quando ela vem fora do formato (nunca o token: a resposta não o contém).
MAX_TEXTO_RESPOSTA = 300

MOTIVO_PAGINA_VAZIA = 'pagina_vazia'
MOTIVO_PAGINA_REPETIDA = 'pagina_repetida'
MOTIVO_LIMITE_DE_PAGINAS = 'limite_de_paginas'
MOTIVO_RESPOSTA_INESPERADA = 'resposta_inesperada'
MOTIVO_INTERROMPIDA = 'interrompida'


# Função Objetivo: O que uma coleta devolveu: as linhas cruas, o tamanho de cada página, por que a coleta parou e, se ela parou por um motivo
# fora do normal, o trecho da resposta que explica. "completa" só é verdade quando a API mesma disse que acabou (página vazia).
@dataclass
class ColetaAnaliseEstoqueFull:
    linhas: list
    tamanhos_das_paginas: list
    motivo_do_fim: str
    detalhe_do_fim: str = ''

    @property
    def paginas(self):
        return len(self.tamanhos_das_paginas)

    @property
    def completa(self):
        return self.motivo_do_fim == MOTIVO_PAGINA_VAZIA


class AnaliseEstoqueFull:
    def __init__(self, cliente):
        self._cliente = cliente

    # Função Objetivo: offset vazio já quebrou a API antes (achado real na exploração) — exige texto de inteiro não-negativo, nunca vazio.
    def _validar_offset(self, offset):
        if not offset or not offset.isdigit():
            raise ValueError(f'offset inválido (esperado inteiro não-negativo como string): {offset!r}')

    # Função Objetivo: Chama o método UMA vez (1 página) e devolve a resposta como a Sysemp mandou. Só leitura.
    def listar_pagina(self, offset='0'):
        self._validar_offset(offset)
        return self._cliente.chamar(METODO, {'offset': offset}, timeout=TIMEOUT_SEGUNDOS)

    # Função Objetivo: A lista de linhas de uma resposta, ou None se a resposta não tem o formato esperado ({"retorno": [ ... ]}).
    @staticmethod
    def _extrair_linhas(resposta):
        if isinstance(resposta, dict) and isinstance(resposta.get('retorno'), list):
            return resposta['retorno']
        return None

    @staticmethod
    def _resumir_resposta(resposta):
        try:
            texto = json.dumps(resposta, ensure_ascii=False)
        except (TypeError, ValueError):
            texto = repr(resposta)
        return texto[:MAX_TEXTO_RESPOSTA]

    # Função Objetivo: A identidade de uma linha dentro da API (local de estoque + produto), usada só para perceber página repetida.
    @staticmethod
    def _chave_da_linha(linha):
        if isinstance(linha, dict):
            return (str(linha.get('id_empresa')), str(linha.get('id_produto')))
        return ('?', repr(linha))

    # Função Objetivo: Busca página após página até a API acabar (ou até uma das guardas do cabeçalho). "ao_avancar_pagina(numero, tamanho,
    # total_de_linhas)" e "deve_parar()" são opcionais: esta classe continua sem saber de tela, cache ou thread — quem chama decide como
    # mostrar o andamento e quando interromper. Erros do cliente (rede, autenticação, negócio...) sobem como vieram.
    def listar_tudo(self, ao_avancar_pagina=None, deve_parar=None):
        linhas, tamanhos, ja_vistas = [], [], set()
        offset = 0
        motivo, detalhe = None, ''

        while motivo is None:
            if deve_parar is not None and deve_parar():
                motivo = MOTIVO_INTERROMPIDA
                break
            if len(tamanhos) >= MAXIMO_PAGINAS:
                motivo = MOTIVO_LIMITE_DE_PAGINAS
                break

            resposta = self.listar_pagina(offset=str(offset))
            pagina = self._extrair_linhas(resposta)
            if pagina is None:
                resumo = self._resumir_resposta(resposta)
                if not tamanhos:
                    raise ErroNegocioSysemp(f'{METODO} respondeu fora do formato esperado na 1ª página: {resumo}')
                motivo, detalhe = MOTIVO_RESPOSTA_INESPERADA, f'página {len(tamanhos) + 1}: {resumo}'
                break
            if not pagina:
                motivo = MOTIVO_PAGINA_VAZIA
                break

            chaves = {self._chave_da_linha(linha) for linha in pagina}
            if chaves <= ja_vistas:
                motivo = MOTIVO_PAGINA_REPETIDA
                break
            ja_vistas |= chaves

            linhas.extend(pagina)
            tamanhos.append(len(pagina))
            offset += len(pagina)
            if ao_avancar_pagina is not None:
                ao_avancar_pagina(len(tamanhos), len(pagina), len(linhas))

        return ColetaAnaliseEstoqueFull(linhas, tamanhos, motivo, detalhe)
