"""
Nível 2 — CicloVideo.__str__()

Representação textual do ciclo, usada em admin/logs. Não escreve no banco
(produto entra como objeto em memória, sem query — ver Disciplina de Testes
Automatizados, seção "Esperado é sempre o valor exato..."), por isso fica
no Nível 2, não no 3.
"""
from agenda_videos.models.ciclo_video import CicloVideo
from agenda_videos.models.configuracao_fase import Fase
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 2 — CicloVideo.__str__()'


def test_str_monta_texto_legivel(tabela_resultados):
    # Setup: produto em memória (sem .save()) + ciclo em memória, sem
    # nenhum campo de produção preenchido — etapa_atual() cai em 'base'.
    produto = Produto(sku='ABC123', titulo='Produto Teste')
    ciclo = CicloVideo(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

    # Exercise: chama o SUT de verdade.
    resultado = str(ciclo)

    # Assert: texto exato — sem branch, 1 caso já cobre a linha inteira.
    esperado = 'ABC123 — Simples #1 (base)'
    registrar_resultado(
        tabela_resultados, 'str_monta_texto_legivel',
        'sku=ABC123, fase=Simples, numero_ocorrencia=1, sem campos de produção',
        esperado,
        '__str__ junta sku + fase + numero + etapa_atual() num texto só, sempre no mesmo formato',
        resultado,
        resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar (nada foi salvo no banco).