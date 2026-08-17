# diagnostico_sysemp_periodo.py
#
# Testa a causa raiz do "Metodo não Localizado" no período real da 1ª
# carga da Samvale (SV): 2020-05-01 -> hoje. ATUALIZADO (17/08/2026):
# antes de qualquer chamada à API, verifica e imprime DE ONDE o token vai
# vir (variável de ambiente já presente no processo vs fallback pro .env
# da raiz do repo) — sem nunca imprimir o valor real, só um fingerprint
# mascarado, porque os testes anteriores não confirmavam isso e a
# conclusão ficava inválida se o token usado fosse o da MB por engano.
#
# Como rodar:
#     poetry run python diagnostico_sysemp_periodo.py
#
# Só lê o token de MB_SYSEMP_API_TOKEN (nunca aparece no script nem é
# impresso — só um fingerprint mascarado).

import os
from datetime import date

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from api_sysemp import ApiSysemp
from api_sysemp.core.excecoes import ErroAPISysemp
from integracao_sysemp.models import SincronizacaoXmlManifestoNotaEntrada

NOME_VARIAVEL_TOKEN = 'MB_SYSEMP_API_TOKEN'


def imprimir_cabecalho(titulo):
    print("\n" + "=" * 70)
    print(titulo)
    print("=" * 70)


def verificar_origem_do_token():
    """Descobre e imprime DE ONDE o token vai vir (variável de ambiente já
    presente no processo, vs fallback pro .env da raiz do repo) — SEM
    nunca imprimir o valor real. Mostra só um fingerprint mascarado
    (4 primeiros/últimos caracteres + tamanho) pra você confirmar
    visualmente que é o token esperado, sem expor o segredo. Devolve True
    só se a variável já estava definida no ambiente do processo ANTES de
    qualquer load_dotenv — ou seja, se foi você quem definiu, não o
    fallback do .env."""
    veio_do_ambiente_do_processo = NOME_VARIAVEL_TOKEN in os.environ
    valor_bruto = os.environ.get(NOME_VARIAVEL_TOKEN)

    imprimir_cabecalho("VERIFICAÇÃO DE ORIGEM DO TOKEN (antes de qualquer chamada à API)")

    if veio_do_ambiente_do_processo:
        print(f"Origem: variável de ambiente do processo — {NOME_VARIAVEL_TOKEN} já estava definida antes de rodar este script.")
    else:
        print(f"Origem: NENHUMA variável de ambiente {NOME_VARIAVEL_TOKEN} estava definida neste processo.")
        print("ApiSysemp() vai cair no fallback do .env da raiz do repo — provavelmente o token padrão (MB), não o da SV.")

    if valor_bruto:
        tamanho = len(valor_bruto)
        fingerprint = f"{valor_bruto[:4]}...{valor_bruto[-4:]} ({tamanho} caracteres)"
        print(f"Fingerprint mascarado: {fingerprint}")
        print("Confira à mão se esse fingerprint bate com o token da SV — nunca com o da MB.")
    else:
        print("Nenhum valor presente pra mostrar fingerprint.")

    return veio_do_ambiente_do_processo


def inspecionar_pagina(rotulo, resposta):
    """Classifica o formato de 1 página de resposta e imprime o veredito.
    Devolve (ok, registros) — ok=False marca anomalia (soft error)."""
    if isinstance(resposta, dict) and resposta.get("status") is False:
        print(f"{rotulo}: ANOMALIA — status=False, message={resposta.get('message')!r}")
        return False, []
    if isinstance(resposta, dict) and "retorno" in resposta:
        registros = resposta.get("retorno") or []
        print(f"{rotulo}: ok — {len(registros)} registro(s)")
        return True, registros
    print(f"{rotulo}: FORMATO INESPERADO — corpo bruto: {resposta}")
    return False, []


def testar_paginacao_controlada(impostos_entrada, data_inicial, data_final):
    imprimir_cabecalho(
        f"CENÁRIO 1 — paginação controlada (período real: {data_inicial} -> {data_final})"
    )
    offset = 0
    numero_pagina = 0
    LIMITE_DE_PAGINAS = 50  # limite de segurança deste diagnóstico, não do pipeline real
    while numero_pagina < LIMITE_DE_PAGINAS:
        numero_pagina += 1
        rotulo = f"página {numero_pagina} (offset={offset})"
        try:
            resposta = impostos_entrada.listar_por_periodo(
                data_inicial, data_final, offset=str(offset)
            )
        except ErroAPISysemp as erro:
            print(f"{rotulo}: EXCEÇÃO {type(erro).__name__} — status_code={erro.status_code}, corpo={erro.corpo_resposta}")
            return
        ok, registros = inspecionar_pagina(rotulo, resposta)
        if not ok:
            print(f"\n>>> Anomalia encontrada na página {numero_pagina}, offset={offset}.")
            return
        if not registros:
            print(f"\n>>> Página vazia (fim natural da paginação) na página {numero_pagina}, offset={offset}.")
            return
        offset += len(registros)
    print(f"\n>>> Parando em {LIMITE_DE_PAGINAS} páginas de propósito (limite de segurança deste diagnóstico) — não é o fim real da paginação.")


def testar_varredura_por_ano(impostos_entrada, data_inicial_total, data_final_total):
    imprimir_cabecalho("CENÁRIO 2 — varredura por ano (offset=0 em cada janela, sem deriva)")
    ano = data_inicial_total.year
    while ano <= data_final_total.year:
        inicio_da_janela = date(ano, 1, 1) if ano > data_inicial_total.year else data_inicial_total
        fim_da_janela = date(ano, 12, 31) if ano < data_final_total.year else data_final_total
        rotulo = f"{inicio_da_janela.isoformat()} -> {fim_da_janela.isoformat()}"
        try:
            resposta = impostos_entrada.listar_por_periodo(
                inicio_da_janela.isoformat(), fim_da_janela.isoformat(), offset="0"
            )
        except ErroAPISysemp as erro:
            print(f"{rotulo}: EXCEÇÃO {type(erro).__name__} — status_code={erro.status_code}, corpo={erro.corpo_resposta}")
        else:
            inspecionar_pagina(rotulo, resposta)
        ano += 1


def diagnosticar():
    imprimir_cabecalho("DIAGNÓSTICO SYSEMP — período real da 1ª carga (SV)")

    origem_confirmada = verificar_origem_do_token()
    if not origem_confirmada:
        print("\n>>> PARANDO AQUI DE PROPÓSITO.")
        print(">>> Sem confirmação de que veio do ambiente (não do fallback do .env), continuar")
        print(">>> não prova nada sobre a conta da SV. Exporte MB_SYSEMP_API_TOKEN com o valor")
        print(">>> da SV neste MESMO terminal, na mesma sessão, e rode de novo.")
        return

    try:
        api = ApiSysemp()
    except RuntimeError as erro:
        imprimir_cabecalho("VEREDITO: TOKEN AUSENTE")
        print(str(erro))
        return

    data_inicial_total = SincronizacaoXmlManifestoNotaEntrada.DATA_INICIAL_PRIMEIRA_CARGA
    data_final_total = date.today()
    print(f"\nPeríodo total testado: {data_inicial_total.isoformat()} -> {data_final_total.isoformat()}")
    print("(o mesmo período que a sincronização real usa na 1ª carga)")
    print(f"\nEndpoint completo: {api.impostos_entrada._cliente.URL_BASE}/listarManifestoNotaEntrada")

    testar_paginacao_controlada(
        api.impostos_entrada, data_inicial_total.isoformat(), data_final_total.isoformat()
    )
    testar_varredura_por_ano(api.impostos_entrada, data_inicial_total, data_final_total)

    imprimir_cabecalho("FIM DO DIAGNÓSTICO")
    print("Cole a saída completa (os dois cenários) de volta.")


if __name__ == "__main__":
    diagnosticar()