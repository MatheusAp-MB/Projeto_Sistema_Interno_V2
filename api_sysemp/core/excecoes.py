# api_sysemp/core/excecoes.py

# Função Objetivo: Hierarquia de exceção própria da API Sysemp — nunca erro
# genérico. Cada subclasse corresponde a 1 categoria de falha, porque cada
# categoria pede uma ação diferente de quem chama: erro de rede, de limite
# de requisição (429) e de servidor (5xx) são passageiros e permitem
# retentativa; erro de autenticação e de negócio (400) não são passageiros —
# repetir a mesma chamada não resolve, então falham na hora. Ver "Padrão de
# Robustez para Clientes de API Externa" no vault.


class ErroAPISysemp(Exception):
    # Função Objetivo: Base de toda falha de comunicação com a API Sysemp.
    # Guarda o status HTTP e um trecho do corpo da resposta — a única pista
    # real de o que deu errado, já que a API não tem doc completa.

    def __init__(self, mensagem, status_code=None, corpo_resposta=None):
        super().__init__(mensagem)
        self.status_code = status_code
        self.corpo_resposta = corpo_resposta


class ErroRedeSysemp(ErroAPISysemp):
    # Função Objetivo: Falha de rede/timeout — nunca deixamos a exceção crua
    # do `requests` escapar sem reembrulhar nesta. Passageira: permite
    # retentativa.
    pass


class ErroLimiteRequisicoesSysemp(ErroAPISysemp):
    # Função Objetivo: Resposta 429 — passageira, permite retentativa com
    # espera. Carrega o tempo de espera sugerido pela própria API, quando
    # ela informar algum (ver protecao.py).

    def __init__(self, mensagem, status_code=None, corpo_resposta=None, tempo_espera_sugerido=None):
        super().__init__(mensagem, status_code, corpo_resposta)
        self.tempo_espera_sugerido = tempo_espera_sugerido


class ErroServidorSysemp(ErroAPISysemp):
    # Função Objetivo: Resposta 5xx — passageira, mesma lógica de
    # retentativa do limite de requisições.
    pass


class ErroAutenticacaoSysemp(ErroAPISysemp):
    # Função Objetivo: Resposta 401/403 — não é passageira. Repetir a mesma
    # chamada com o mesmo token não resolve, então falha na hora, sem
    # retentativa automática.
    pass


class ErroNegocioSysemp(ErroAPISysemp):
    # Função Objetivo: Resposta 400 com payload de erro de negócio
    # (parâmetro inválido, por exemplo) — não é passageira. Corrigir o
    # parâmetro é responsabilidade de quem chama, não do cliente. Falha na
    # hora.
    pass