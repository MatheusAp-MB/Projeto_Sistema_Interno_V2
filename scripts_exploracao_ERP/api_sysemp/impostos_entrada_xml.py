# scripts_exploracao_ERP/api_sysemp/impostos_entrada_xml.py

# Função Objetivo: Contexto "Obter impostos de entrada vindos do XML" —
# sabe tudo que o ClienteApiSysemp (transporte puro) não deve saber: qual
# endpoint chamar, quais nomes de campo a API espera, e o que é um período
# válido pra essa consulta específica. Compõe um ClienteApiSysemp (nunca
# herda dele) e devolve o resultado cru — sem parsing, ainda estamos
# descobrindo o formato real do dado. Ver "Padrao de Robustez para
# Clientes de API Externa" no vault.

from datetime import date, timedelta


class ImpostosEntradaXML:
    def __init__(self, cliente):
        self._cliente = cliente

    # * [EXPLICAÇÃO] → Recusa período claramente inválido ANTES de gastar
    #                  uma chamada de rede — nunca formato errado, nunca
    #                  invertido, nunca no futuro. Margem de 1 dia no
    #                  limite futuro é de propósito: o ERP tem bugs de
    #                  data conhecidos, e 1 dia evita falso positivo.
    def _validar_periodo(self, data_inicial, data_final, data_referencia):
        try:
            inicial = date.fromisoformat(data_inicial)
        except ValueError:
            raise ValueError(f'data_inicial inválida (esperado AAAA-MM-DD): {data_inicial!r}')

        try:
            final = date.fromisoformat(data_final)
        except ValueError:
            raise ValueError(f'data_final inválida (esperado AAAA-MM-DD): {data_final!r}')

        if inicial >= final:
            raise ValueError(f'data_inicial ({inicial}) precisa ser anterior a data_final ({final}).')

        limite_maximo = data_referencia + timedelta(days=1)
        if final > limite_maximo:
            raise ValueError(f'data_final ({final}) está no futuro além do limite permitido ({limite_maximo}).')

    # Função Objetivo: offset vazio já quebrou a API antes (achado real, na
    # fase de exploração manual) — exige string representando inteiro
    # não-negativo, nunca vazia.
    def _validar_offset(self, offset):
        if not offset or not offset.isdigit():
            raise ValueError(f'offset inválido (esperado inteiro não-negativo como string): {offset!r}')

    # Função Objetivo: Único endpoint documentado até agora — lista as
    # notas fiscais de entrada (compras) manifestadas, por período. Valida
    # antes de gastar uma chamada de rede. data_referencia existe só pra
    # permitir teste determinístico (nunca date.today() cru dentro do
    # SUT) — em uso real, sempre None, resolvido pra hoje.
    def listar_por_periodo(self, data_inicial, data_final, offset='0', data_referencia=None):
        if data_referencia is None:
            data_referencia = date.today()
        self._validar_periodo(data_inicial, data_final, data_referencia)
        self._validar_offset(offset)

        corpo = {'datainicial': data_inicial, 'datafinal': data_final, 'offset': offset}
        return self._cliente.chamar('listarManifestoNotaEntrada', corpo)

    def listar_periodo_completo(self, data_inicial, data_final, data_referencia=None, ao_avancar_pagina=None):
        if data_referencia is None:
            data_referencia = date.today()

        todos_os_registros = []
        offset = 0
        numero_da_pagina = 0
        while True:
            pagina = self.listar_por_periodo(
                data_inicial, data_final, offset=str(offset), data_referencia=data_referencia
            )
            registros_da_pagina = pagina['retorno']
            if not registros_da_pagina:
                break
            todos_os_registros.extend(registros_da_pagina)
            offset += len(registros_da_pagina)
            numero_da_pagina += 1

            # * [EXPLICAÇÃO] → callback opcional só pra progresso — essa
            #                   classe continua sem saber o que é console
            #                   ou print, quem chama decide como mostrar.
            if ao_avancar_pagina is not None:
                ao_avancar_pagina(numero_da_pagina, len(registros_da_pagina), len(todos_os_registros))

        return {'retorno': todos_os_registros}