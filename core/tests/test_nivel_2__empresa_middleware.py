# core/tests/test_nivel_2__empresa_middleware.py

# Função Objetivo: Testa EmpresaMiddleware isoladamente (RequestFactory +
# get_response falso) — Nível 2, não toca banco nenhum. Cobre o "Achado
# central" da correção de 24-25/08: rota /api/ passa a EXIGIR o cabeçalho
# X-Empresa (nunca cai num padrão silencioso), enquanto rota fora de /api/
# mantém o comportamento antigo, baseado em sessão de navegador.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import json

from django.http import HttpResponse
from django.test import RequestFactory

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_PADRAO, EMPRESA_SAMVALE, obter_empresa_ativa
from core.middleware import EmpresaMiddleware
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 2 — core.middleware.EmpresaMiddleware (isolado, sem banco)'

fabrica = RequestFactory()


def _get_response_capturando(estado):
    # Função Objetivo: substitui a "próxima camada" (view real) só pra
    # registrar QUAL empresa estava ativa no momento em que o middleware
    # deixou passar — é isso que prova que definir_empresa_ativa() foi
    # chamado com o valor certo, sem precisar de uma view/banco de verdade.
    def _dummy(request):
        estado['chamado'] = True
        estado['empresa_capturada'] = obter_empresa_ativa()
        return HttpResponse('ok', status=200)
    return _dummy


def _montar_middleware(estado):
    return EmpresaMiddleware(_get_response_capturando(estado))


# ===================================================================
# Rotas /api/ — exige X-Empresa explícito, nunca cai em padrão silencioso
# ===================================================================

def test_rota_api_sem_x_empresa_devolve_400_e_nao_chama_a_proxima_camada(tabela_resultados):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado)
    request = fabrica.post('/api/postagem-automatica/execucao/1/heartbeat/')

    # Exercise:
    resposta = middleware(request)

    # Assert:
    corpo = json.loads(resposta.content)
    passou = resposta.status_code == 400 and 'erro' in corpo and estado['chamado'] is False
    registrar_resultado(
        tabela_resultados, teste='Rota /api/ sem cabeçalho X-Empresa',
        entrada='POST /api/.../heartbeat/, sem X-Empresa', esperado='400, corpo com "erro", view real NUNCA chamada',
        motivo='"Achado central" — sem o header, nunca pode cair num padrão silencioso (Magazine)',
        obtido=f'status={resposta.status_code}, corpo={corpo}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou


def test_rota_api_com_x_empresa_invalido_devolve_400_e_nao_chama_a_proxima_camada(tabela_resultados):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado)
    request = fabrica.post('/api/postagem-automatica/execucao/1/heartbeat/', HTTP_X_EMPRESA='OUTRACOISA')

    # Exercise:
    resposta = middleware(request)

    # Assert:
    corpo = json.loads(resposta.content)
    passou = resposta.status_code == 400 and 'OUTRACOISA' in corpo['erro'] and estado['chamado'] is False
    registrar_resultado(
        tabela_resultados, teste='Rota /api/ com X-Empresa inválido',
        entrada="X-Empresa: 'OUTRACOISA'", esperado='400, mensagem cita o valor recebido, view real NUNCA chamada',
        motivo='Valor fora de EMPRESAS_VALIDAS precisa ser recusado, igual a ausente',
        obtido=f'status={resposta.status_code}, corpo={corpo}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou


def test_rota_api_com_x_empresa_magazine_ativa_magazine_e_segue_adiante(tabela_resultados):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado)
    request = fabrica.post('/api/postagem-automatica/execucao/1/heartbeat/', HTTP_X_EMPRESA=EMPRESA_MAGAZINE)

    # Exercise:
    resposta = middleware(request)

    # Assert:
    passou = resposta.status_code == 200 and estado['chamado'] is True and estado['empresa_capturada'] == EMPRESA_MAGAZINE
    registrar_resultado(
        tabela_resultados, teste='Rota /api/ com X-Empresa=MAGAZINE',
        entrada='X-Empresa: MAGAZINE', esperado='200, view real chamada com Magazine já ativa',
        motivo='Caminho feliz do agente local postando/replicando pela Magazine',
        obtido=f'status={resposta.status_code}, chamado={estado["chamado"]}, empresa_capturada={estado.get("empresa_capturada")}',
        passou=passou,
    )
    assert passou


def test_rota_api_com_x_empresa_samvale_ativa_samvale_e_segue_adiante(tabela_resultados):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado)
    request = fabrica.post('/api/replicacao-automatica/execucao/1/heartbeat/', HTTP_X_EMPRESA=EMPRESA_SAMVALE)

    # Exercise:
    resposta = middleware(request)

    # Assert:
    passou = resposta.status_code == 200 and estado['chamado'] is True and estado['empresa_capturada'] == EMPRESA_SAMVALE
    registrar_resultado(
        tabela_resultados, teste='Rota /api/ com X-Empresa=SAMVALE',
        entrada='X-Empresa: SAMVALE', esperado='200, view real chamada com Samvale já ativa',
        motivo='Prova que o middleware não fica "preso" na Magazine — é isso que o bug original quebrava',
        obtido=f'status={resposta.status_code}, chamado={estado["chamado"]}, empresa_capturada={estado.get("empresa_capturada")}',
        passou=passou,
    )
    assert passou


# ===================================================================
# Rotas fora de /api/ — comportamento antigo intacto (sessão de navegador)
# ===================================================================

def test_rota_fora_da_api_sem_sessao_cai_no_padrao_magazine(tabela_resultados):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado)
    request = fabrica.get('/agenda-videos/')
    request.session = {}

    # Exercise:
    resposta = middleware(request)

    # Assert:
    passou = resposta.status_code == 200 and estado['empresa_capturada'] == EMPRESA_PADRAO
    registrar_resultado(
        tabela_resultados, teste='Rota fora de /api/, sessão sem empresa_ativa',
        entrada='sessão vazia (dict {})', esperado=f'cai no padrão ({EMPRESA_PADRAO})',
        motivo='Comportamento antigo, nunca deve mudar pro navegador — só a rota /api/ ganhou a trava nova',
        obtido=f'empresa_capturada={estado.get("empresa_capturada")}',
        passou=passou,
    )
    assert passou


def test_rota_fora_da_api_com_sessao_samvale_respeita_a_sessao(tabela_resultados):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado)
    request = fabrica.get('/agenda-videos/')
    request.session = {'empresa_ativa': EMPRESA_SAMVALE}

    # Exercise:
    resposta = middleware(request)

    # Assert:
    passou = resposta.status_code == 200 and estado['empresa_capturada'] == EMPRESA_SAMVALE
    registrar_resultado(
        tabela_resultados, teste='Rota fora de /api/, sessão com empresa_ativa=SAMVALE',
        entrada="sessão {'empresa_ativa': 'SAMVALE'}", esperado='respeita a sessão, ativa Samvale',
        motivo='É assim que o usuário troca de empresa pelo navegador — não pode regredir',
        obtido=f'empresa_capturada={estado.get("empresa_capturada")}',
        passou=passou,
    )
    assert passou


def test_rota_fora_da_api_com_sessao_invalida_cai_no_padrao_magazine(tabela_resultados):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado)
    request = fabrica.get('/agenda-videos/')
    request.session = {'empresa_ativa': 'VALOR_CORROMPIDO'}

    # Exercise:
    resposta = middleware(request)

    # Assert:
    passou = resposta.status_code == 200 and estado['empresa_capturada'] == EMPRESA_PADRAO
    registrar_resultado(
        tabela_resultados, teste='Rota fora de /api/, sessão com valor corrompido/inválido',
        entrada="sessão {'empresa_ativa': 'VALOR_CORROMPIDO'}", esperado=f'cai no padrão ({EMPRESA_PADRAO}), nunca quebra',
        motivo='Sessão adulterada ou de uma versão antiga não pode virar erro pro usuário — mesma trava de sempre',
        obtido=f'empresa_capturada={estado.get("empresa_capturada")}',
        passou=passou,
    )
    assert passou