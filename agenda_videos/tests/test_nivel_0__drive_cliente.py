# agenda_videos/tests/test_nivel_0__drive_cliente.py

# SUT: agenda_videos/funcoes_auxiliares/drive/cliente.py (obter_pasta_raiz_id_ativa)
# DOC: core.empresa (definir_empresa_ativa/obter_empresa_ativa) — só troca o
#      estado thread-local em memória, nenhuma chamada de rede nem banco.
#      Nível 0.

from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE
from agenda_videos.funcoes_auxiliares.drive.cliente import obter_pasta_raiz_id_ativa
from testes_apoio.apoio_visual import registrar_resultado


def test_nivel_0__obter_pasta_raiz_id_ativa_magazine_e_samvale_sao_diferentes(tabela_resultados):
    # Função Objetivo: prova o isolamento exigido pelo critério de pronto da
    # Etapa 1 (checkpoint "Correção de Ponta a Ponta da Agenda de Vídeos",
    # 18/08/2026) — Magazine e Samvale precisam resolver pra 2 IDs de pasta
    # DIFERENTES e nenhum dos 2 pode vir vazio, senão as 2 empresas estariam
    # sem querer olhando pra mesma pasta (ou pra pasta nenhuma).
    # Setup + Exercise:
    definir_empresa_ativa(EMPRESA_MAGAZINE)
    pasta_magazine = obter_pasta_raiz_id_ativa()

    definir_empresa_ativa(EMPRESA_SAMVALE)
    pasta_samvale = obter_pasta_raiz_id_ativa()

    # Assert:
    passou = (
        pasta_magazine is not None
        and pasta_samvale is not None
        and pasta_magazine != pasta_samvale
    )
    registrar_resultado(
        tabela_resultados, teste='obter_pasta_raiz_id_ativa — Magazine e Samvale resolvem pra pastas diferentes',
        entrada='empresa ativa = MAGAZINE, depois SAMVALE',
        esperado='2 IDs de pasta não-nulos e diferentes entre si',
        motivo='Prova formal do isolamento exigido pelo critério de pronto da Etapa 1',
        obtido=f'pasta_magazine={pasta_magazine}, pasta_samvale={pasta_samvale}',
        passou=passou,
    )
    assert passou


def test_nivel_0__obter_pasta_raiz_id_ativa_sem_empresa_ativa_levanta_erro(tabela_resultados):
    # Função Objetivo: sem nenhuma empresa ativa definida (comando de
    # terminal, migration, shell — mesmo cenário documentado em
    # core.empresa.obter_empresa_ativa), a função precisa levantar erro
    # explícito, nunca devolver um ID de pasta arbitrário/errado por engano.
    # Setup:
    definir_empresa_ativa(None)

    # Exercise:
    levantou_erro = False
    try:
        obter_pasta_raiz_id_ativa()
    except RuntimeError:
        levantou_erro = True

    # Assert:
    passou = levantou_erro
    registrar_resultado(
        tabela_resultados, teste='obter_pasta_raiz_id_ativa — sem empresa ativa levanta erro',
        entrada='empresa ativa = None',
        esperado='RuntimeError',
        motivo='Nunca devolver pasta arbitrária quando não dá pra saber de qual empresa é a chamada',
        obtido=f'levantou_erro={levantou_erro}',
        passou=passou,
    )
    assert passou