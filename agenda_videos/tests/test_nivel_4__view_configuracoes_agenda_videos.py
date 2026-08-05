# agenda_videos/tests/test_nivel_4__view_configuracoes_agenda_videos.py

# Função Objetivo: Testa view_configuracoes_agenda_videos() — Nível 4 (view
# HTTP real). Bloco D da rodada de testes de views (ver Checkpoint no
# Obsidian). Trava especificamente contra regressão o bug corrigido em
# "Validacao de Configuracoes Nao Abre Excecao Para Simples" — Simples não
# usa distância entre ocorrências e não pode exigir esse campo.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.urls import reverse

from agenda_videos.models import ConfiguracaoFase, Fase
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 4 — view_configuracoes_agenda_videos(): GET/POST via HTTP'


def _url():
    return reverse('agenda_videos_configuracoes')


def _payload_valido(**overrides):
    # Espelha uma submissão real do form único (as 3 fases sempre juntas).
    dados = {
        'simples_periodo': '1',
        'simples_distancia_dias_corridos': '',  # Simples não usa esse campo
        'simples_distancia_dias_ao_entrar_na_fase': '0',
        'video_mensal_periodo': '4',
        'video_mensal_distancia_dias_corridos': '30',
        'video_mensal_distancia_dias_ao_entrar_na_fase': '0',
        'video_trimestral_periodo_continuo': 'on',
        'video_trimestral_distancia_dias_corridos': '90',
        'video_trimestral_distancia_dias_ao_entrar_na_fase': '90',
    }
    dados.update(overrides)
    return dados


def test_get_sem_nenhuma_configuracao_devolve_padrao_em_branco(client, tabela_resultados):
    # Exercise:
    resposta = client.get(_url())

    # Assert:
    fases = resposta.context['fases']
    passou = (
        resposta.status_code == 200 and len(fases) == 3
        and all(not f['configurado'] and f['periodo'] == '' and f['distancia_dias_corridos'] == '' for f in fases)
    )
    registrar_resultado(
        tabela_resultados, teste='GET sem nenhuma ConfiguracaoFase',
        entrada='banco vazio', esperado='3 fases no contexto, todas configurado=False e em branco',
        motivo='Sem registro salvo, a view precisa devolver valores padrão sem quebrar',
        obtido=f'status={resposta.status_code}, configuradas={[f["configurado"] for f in fases]}',
        passou=passou,
    )
    assert passou


def test_get_com_config_existente_reflete_valores_reais(client, tabela_resultados):
    # Setup:
    ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_MENSAL, periodo=4, distancia_dias_corridos=30, distancia_dias_ao_entrar_na_fase=0,
    )

    # Exercise:
    resposta = client.get(_url())

    # Assert:
    fases = {f['valor']: f for f in resposta.context['fases']}
    mensal = fases[Fase.VIDEO_MENSAL]
    passou = (
        mensal['configurado'] is True and mensal['periodo'] == 4 and mensal['distancia_dias_corridos'] == 30
        and fases[Fase.SIMPLES]['configurado'] is False
    )
    registrar_resultado(
        tabela_resultados, teste='GET com Vídeo Mensal já configurado',
        entrada='ConfiguracaoFase(Vídeo Mensal, periodo=4, distancia=30)', esperado='contexto reflete os valores reais só pra essa fase',
        motivo='As outras fases sem registro continuam com o padrão em branco',
        obtido=f'mensal={mensal}',
        passou=passou,
    )
    assert passou


def test_post_simples_salva_com_distancia_em_branco(client, tabela_resultados):
    # Função Objetivo: regressão direta do bug corrigido em "Validacao de
    # Configuracoes Nao Abre Excecao Para Simples" — Simples só tem 1
    # ocorrência, não pode exigir "distância entre ocorrências".
    # Exercise:
    resposta = client.post(_url(), _payload_valido())

    # Assert:
    config = ConfiguracaoFase.objects.filter(fase=Fase.SIMPLES).first()
    passou = resposta.status_code == 302 and config is not None and config.distancia_dias_corridos is None and config.periodo == 1
    registrar_resultado(
        tabela_resultados, teste='POST Simples com distância em branco',
        entrada='simples_distancia_dias_corridos=""', esperado='ConfiguracaoFase(Simples) criada, distancia_dias_corridos=None',
        motivo='Simples é a única fase que não exige esse campo — travar contra o bug já corrigido',
        obtido=f'status={resposta.status_code}, config={config}',
        passou=passou,
    )
    assert passou


def test_post_video_mensal_sem_distancia_nao_salva(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url(), _payload_valido(video_mensal_distancia_dias_corridos=''))

    # Assert:
    config = ConfiguracaoFase.objects.filter(fase=Fase.VIDEO_MENSAL).first()
    passou = resposta.status_code == 302 and config is None
    registrar_resultado(
        tabela_resultados, teste='POST Vídeo Mensal sem distância (obrigatória pra ela)',
        entrada='video_mensal_distancia_dias_corridos=""', esperado='nada criado pra Vídeo Mensal',
        motivo='Diferente de Simples, Mensal exige distância entre ocorrências',
        obtido=f'status={resposta.status_code}, config={config}',
        passou=passou,
    )
    assert passou


def test_post_periodo_continuo_marcado_salva_periodo_none(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url(), _payload_valido())

    # Assert:
    config = ConfiguracaoFase.objects.filter(fase=Fase.VIDEO_TRIMESTRAL).first()
    passou = config is not None and config.periodo_continuo is True and config.periodo is None
    registrar_resultado(
        tabela_resultados, teste='POST Vídeo Trimestral com periodo_continuo=on',
        entrada='video_trimestral_periodo_continuo="on", sem período', esperado='periodo_continuo=True, periodo=None',
        motivo='Quando contínuo, período nunca é lido nem exigido',
        obtido=f'config={config}',
        passou=passou,
    )
    assert passou


def test_post_sem_periodo_continuo_e_sem_periodo_nao_salva(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url(), _payload_valido(video_mensal_periodo=''))

    # Assert:
    config = ConfiguracaoFase.objects.filter(fase=Fase.VIDEO_MENSAL).first()
    passou = resposta.status_code == 302 and config is None
    registrar_resultado(
        tabela_resultados, teste='POST sem periodo_continuo e sem período preenchido',
        entrada='video_mensal_periodo=""', esperado='nada criado pra Vídeo Mensal',
        motivo='Sem periodo_continuo, período é obrigatório',
        obtido=f'status={resposta.status_code}, config={config}',
        passou=passou,
    )
    assert passou


def test_post_distancia_de_entrada_em_branco_vira_zero(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url(), _payload_valido(video_mensal_distancia_dias_ao_entrar_na_fase=''))

    # Assert:
    config = ConfiguracaoFase.objects.filter(fase=Fase.VIDEO_MENSAL).first()
    passou = config is not None and config.distancia_dias_ao_entrar_na_fase == 0
    registrar_resultado(
        tabela_resultados, teste='POST distância-de-entrada em branco',
        entrada='video_mensal_distancia_dias_ao_entrar_na_fase=""', esperado='distancia_dias_ao_entrar_na_fase == 0',
        motivo='Esse campo nunca é obrigatório — em branco cai no padrão 0',
        obtido=f'config={config}',
        passou=passou,
    )
    assert passou


def test_post_atualiza_config_existente_sem_duplicar(client, tabela_resultados):
    # Setup:
    ConfiguracaoFase.objects.create(
        fase=Fase.VIDEO_MENSAL, periodo=4, distancia_dias_corridos=30, distancia_dias_ao_entrar_na_fase=0,
    )

    # Exercise:
    resposta = client.post(_url(), _payload_valido(
        video_mensal_periodo='6', video_mensal_distancia_dias_corridos='45',
    ))

    # Assert:
    total = ConfiguracaoFase.objects.filter(fase=Fase.VIDEO_MENSAL).count()
    config = ConfiguracaoFase.objects.get(fase=Fase.VIDEO_MENSAL)
    passou = total == 1 and config.periodo == 6 and config.distancia_dias_corridos == 45
    registrar_resultado(
        tabela_resultados, teste='POST atualiza Vídeo Mensal já configurado',
        entrada='config existente (periodo=4) + POST com periodo=6', esperado='1 registro só, com os valores novos',
        motivo='update_or_create nunca deve duplicar o registro por fase (fase é unique)',
        obtido=f'total={total}, config={config}',
        passou=passou,
    )
    assert passou


def test_post_uma_fase_invalida_nao_trava_as_outras(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url(), _payload_valido(video_mensal_distancia_dias_corridos=''))

    # Assert:
    simples_ok = ConfiguracaoFase.objects.filter(fase=Fase.SIMPLES).exists()
    mensal_ok = ConfiguracaoFase.objects.filter(fase=Fase.VIDEO_MENSAL).exists()
    trimestral_ok = ConfiguracaoFase.objects.filter(fase=Fase.VIDEO_TRIMESTRAL).exists()
    passou = simples_ok and not mensal_ok and trimestral_ok
    registrar_resultado(
        tabela_resultados, teste='1 fase inválida (Mensal) entre 2 válidas na mesma submissão',
        entrada='só video_mensal_distancia_dias_corridos em branco', esperado='Simples e Trimestral salvam, só Mensal fica sem',
        motivo='O loop processa cada fase de forma independente — 1 falha não deve travar as outras',
        obtido=f'simples={simples_ok}, mensal={mensal_ok}, trimestral={trimestral_ok}',
        passou=passou,
    )
    assert passou


def test_post_nenhuma_fase_valida_nao_salva_nada(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url(), _payload_valido(
        simples_periodo='',
        video_mensal_distancia_dias_corridos='',
        video_trimestral_distancia_dias_corridos='',
    ))

    # Assert:
    total = ConfiguracaoFase.objects.count()
    passou = resposta.status_code == 302 and total == 0
    registrar_resultado(
        tabela_resultados, teste='Nenhuma fase válida na submissão',
        entrada='as 3 fases com dado obrigatório faltando', esperado='nenhum registro criado, ainda assim redireciona (302)',
        motivo='View sempre redireciona no final, com ou sem sucesso — nunca 400',
        obtido=f'status={resposta.status_code}, total_no_banco={total}',
        passou=passou,
    )
    assert passou