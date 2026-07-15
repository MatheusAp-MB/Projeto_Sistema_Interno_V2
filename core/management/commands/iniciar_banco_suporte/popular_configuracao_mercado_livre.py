# * [RESUMO] → Seed inicial da configuração de precificação do Mercado
#              Livre — 1 configuração geral (singleton), 8 tipos de
#              anúncio (Clássico/Premium × FULL/Coleta × Catálogo/Não),
#              e 4 faixas de armazenagem por dimensão. Usa get_or_create
#              — seguro rodar mais de uma vez, nunca duplica.

from decimal import Decimal
from mercado_livre.models import (
    ConfiguracaoMercadoLivre, ConfiguracaoTipoAnuncioMercadoLivre,
    FaixaArmazenagemMercadoLivre, TipoDeAnuncioMercadoLivre,
)

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio


def popular_configuracao_mercado_livre(stdout, style):
    stdout.write('  [CONFIG ML] Configuração geral...')
    _, criado = ConfiguracaoMercadoLivre.objects.get_or_create(
        pk=1,
        defaults={
            'fator_coleta': Decimal('72'),
            'periodo_armazenagem': 30,
        }
    )
    stdout.write(f'       {"criada" if criado else "já existe"}')

    # * [EXPLICAÇÃO] → Simplificado em 27/07: só tipo_anuncio importa
    #                  pra precificação agora (confirmado com o
    #                  usuário/superior) — logística e catálogo não
    #                  afetam mais comissão/margem. 2 linhas, não 8.
    #                  margem_maxima corrigida de 25 pra 20 — 25 era
    #                  inconsistente com todo o resto já validado nessa
    #                  sessão (sempre 20% em exemplos reais conferidos).
    stdout.write('  [CONFIG ML] Tipos de anúncio...')
    tipos = [
        ('Clássico', TipoAnuncio.CLASSICO, 12),
        ('Premium',  TipoAnuncio.PREMIUM,  17),
    ]

    for nome, tipo_anuncio, comissao in tipos:
        _, criado = ConfiguracaoTipoAnuncioMercadoLivre.objects.get_or_create(
            tipo_anuncio=tipo_anuncio,
            defaults={
                'comissao': Decimal(str(comissao)),
                'margem_padrao': Decimal('15'),
                'margem_minima': Decimal('10'),
                'margem_maxima': Decimal('20'),
                'margem_competicao': Decimal('5'),
            }
        )
        stdout.write(f'       {nome}: {"criado" if criado else "já existe"}')

    stdout.write('  [CONFIG ML] Faixas de armazenagem...')
    faixas = [
        (1, 'Faixa 1 — Até 12×15×25cm',       Decimal('0.0070'), 12,   15,   25),
        (2, 'Faixa 2 — Até 28×36×51cm',       Decimal('0.0150'), 28,   36,   51),
        (3, 'Faixa 3 — Até 60×60×70cm',       Decimal('0.0500'), 60,   60,   70),
        (4, 'Faixa 4 — Maior que 60×60×70cm', Decimal('0.1070'), 9999, 9999, 9999),
    ]

    for ordem, nome, valor_diario, max_altura, max_largura, max_profundidade in faixas:
        _, criado = FaixaArmazenagemMercadoLivre.objects.get_or_create(
            ordem=ordem,
            defaults={
                'nome': nome,
                'valor_diario': valor_diario,
                'max_altura': Decimal(str(max_altura)),
                'max_largura': Decimal(str(max_largura)),
                'max_profundidade': Decimal(str(max_profundidade)),
                'ativo': True,
            }
        )
        stdout.write(f'       {nome}: {"criada" if criado else "já existe"}')