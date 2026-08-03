# * [RESUMO] → Seed da régua de fases da Agenda de Vídeos (Simples → Vídeo
#              Mensal → Vídeo Trimestral) — dado editável no admin, nunca
#              dict fixo no código (decisão do usuário, 30/07), mas precisa
#              existir em qualquer banco novo pra Agenda de Vídeos funcionar.
#              Usa get_or_create — seguro rodar mais de uma vez, nunca duplica.
#              Mesma régua usada na fixture de teste regua_de_fases
#              (agenda_videos/tests/test_nivel_3__criar_proximo.py).

from agenda_videos.models import ConfiguracaoFase, Fase


def popular_regua_fases_agenda_videos(stdout, style):
    stdout.write('  [REGUA DE FASES] Vídeo Trimestral...')
    trimestral, criado = ConfiguracaoFase.objects.get_or_create(
        fase=Fase.VIDEO_TRIMESTRAL,
        defaults={
            'periodo_continuo': True,
            'distancia_dias_corridos': 90,
            'distancia_dias_ao_entrar_na_fase': 90,
        }
    )
    stdout.write(f'       {"criada" if criado else "já existe"}')

    stdout.write('  [REGUA DE FASES] Vídeo Mensal...')
    mensal, criado = ConfiguracaoFase.objects.get_or_create(
        fase=Fase.VIDEO_MENSAL,
        defaults={
            'periodo_continuo': False,
            'periodo': 4,
            'distancia_dias_corridos': 30,
            'distancia_dias_ao_entrar_na_fase': 0,
            'proxima_fase': trimestral,
        }
    )
    stdout.write(f'       {"criada" if criado else "já existe"}')

    stdout.write('  [REGUA DE FASES] Simples...')
    _, criado = ConfiguracaoFase.objects.get_or_create(
        fase=Fase.SIMPLES,
        defaults={
            'periodo_continuo': False,
            'periodo': 1,
            'proxima_fase': mensal,
        }
    )
    stdout.write(f'       {"criada" if criado else "já existe"}')