# * [RESUMO] → Popula os 16 critérios de qualidade conhecidos do
#              Mercado Livre (DICIO_REGRAS, migrado do projeto paralelo
#              de API). São a nossa tradução/interpretação — critérios
#              novos que a API trouxer e não estiverem aqui são criados
#              automaticamente na importação, marcados como
#              catalogado=False (ver importar_qualidade_anuncio.py).

from mercado_livre.models import CriterioQualidade

CRITERIOS = [
    {
        'rule_key': 'UP_HAS_SHORTS', 'grupo': 'UP_SHORTS',
        'nome': 'TER NO MÍNIMO: 1 CLIPE', 'pergunta': 'Tem 1 clipe?',
        'como_aprovar': 'Adicione no mínimo 1 clipe em cada anúncio.\nOs clipes devem ter até 1 minuto, em formato vertical.\nSerão publicados em todas as variações do anúncio.',
    },
    {
        'rule_key': 'UP_PICTURES_QUANTITY_MIN', 'grupo': 'UP_PICTURES',
        'nome': 'TER NO MÍNIMO: 3 FOTOS', 'pergunta': 'Tem 3 fotos?',
        'como_aprovar': 'Adicione no mínimo 3 fotos ao anúncio.\nMostre o produto em diferentes ângulos.\nUse fundo branco e boa iluminação.',
    },
    {
        'rule_key': 'UP_TITLE_LENGTH_MIN', 'grupo': 'UP_TITLE',
        'nome': 'TÍTULO COM NO MÍNIMO 3 PALAVRAS', 'pergunta': 'Título com 3+ palavras?',
        'como_aprovar': 'O título deve conter no mínimo 3 palavras descritivas.\nInclua marca, modelo e características principais.\nEvite palavras genéricas como "produto" ou "item".',
    },
    {
        'rule_key': 'UP_HAS_GTIN', 'grupo': 'UP_GTIN',
        'nome': 'INFORMAR CÓDIGO UNIVERSAL (EAN/GTIN)', 'pergunta': 'Tem código EAN/GTIN?',
        'como_aprovar': 'Preencha o código EAN ou GTIN do produto.\nO código deve pertencer exatamente a este produto.\nIsso melhora a exposição nos resultados de busca.',
    },
    {
        'rule_key': 'UP_BEST_STOCK_AVAILABILITY_TIME', 'grupo': 'UP_STOCK_AVAILABILITY_TIME',
        'nome': 'DEFINIR COMO SEM PRAZO DE DISPONIBILIDADE', 'pergunta': 'Sem prazo de disponibilidade?',
        'como_aprovar': 'Remova o prazo de disponibilidade do anúncio.\nAnúncios sem prazo são mais competitivos no algoritmo.',
    },
    {
        'rule_key': 'UP_MULTI_ORIGIN_ONE_STORE_STOCK', 'grupo': 'UP_STOCK_DEPOSITO',
        'nome': 'TER NO MÍNIMO: 2 UNIDADES EM ESTOQUE', 'pergunta': 'Tem 2+ unidades em estoque?',
        'como_aprovar': 'Mantenha no mínimo 2 unidades disponíveis no anúncio.\nAnúncios com pouco estoque perdem posicionamento.',
    },
    {
        'rule_key': 'UP_HAS_FREE_SHIPPING', 'grupo': 'UP_FREE_SHIPPING',
        'nome': 'OFERECER FRETE GRÁTIS', 'pergunta': 'Tem frete grátis?',
        'como_aprovar': 'Ative o frete grátis no anúncio.\nVálido para produtos acima de R$ 19,90.\nAnúncios com frete grátis têm mais visibilidade e conversão.',
    },
    {
        'rule_key': 'UP_LISTING_TYPE_PREMIUM', 'grupo': 'UP_FINANCING',
        'nome': 'OFERECER PARCELAMENTO SEM JUROS', 'pergunta': 'Parcelamento sem juros?',
        'como_aprovar': 'Altere o tipo do anúncio para Premium.\nIsso habilita o parcelamento sem juros para o comprador.\nAplicável somente a anúncios do tipo Premium.',
    },
    {
        'rule_key': 'UP_HAS_PROMOTIONS', 'grupo': 'UP_PROMOTIONS',
        'nome': 'PARTICIPAR DE UMA PROMOÇÃO', 'pergunta': 'Tem promoção ativa?',
        'como_aprovar': 'Acesse a lista de promoções disponíveis para este anúncio.\nParticipe de pelo menos uma promoção ativa.\nPromoções aumentam a visibilidade e as visitas.',
    },
    {
        'rule_key': 'UP_TS_MAIN_QUANTITY', 'grupo': 'UP_TECHNICAL_SPECIFICATIONS_MAIN',
        'nome': 'PREENCHER FICHA TÉCNICA COMPLETA', 'pergunta': 'Ficha técnica preenchida?',
        'como_aprovar': 'Preencha todas as características técnicas obrigatórias.\nIsso reduz perguntas e devoluções.\nAcesse a edição do anúncio e complete todos os campos.',
    },
    {
        'rule_key': 'UP_EXPENSIVE_PRICE', 'grupo': 'UP_PRICE',
        'nome': 'PREÇO DENTRO DO LIMITE DE TARIFAS', 'pergunta': 'Preço dentro do limite de tarifas?',
        'como_aprovar': 'Verifique se o preço está dentro do limite aceito pelo ML.\nPreços acima do limite podem reduzir acesso a descontos em tarifas.',
    },
    {
        'rule_key': 'UP_OFFENDER_PRICE', 'grupo': 'UP_PRICE',
        'nome': 'PREÇO DENTRO DO LIMITE DE PROMOÇÕES', 'pergunta': 'Preço dentro do limite de promoções?',
        'como_aprovar': 'Verifique se o preço está dentro do limite para acesso a promoções.\nPreços acima do limite podem bloquear participação em promoções.',
    },
    {
        'rule_key': 'UP_PRICE_PER_QUANTITY', 'grupo': 'UP_PRICE',
        'nome': 'ADICIONAR PREÇOS DE ATACADO', 'pergunta': 'Tem preços de atacado?',
        'como_aprovar': 'Configure preços diferenciados por quantidade.\nOfereça desconto para compras em maior volume.',
    },
    {
        'rule_key': 'UP_ME_FLEX_ITEM_OPTIN', 'grupo': 'UP_ME_FLEX_ITEM_OPTIN',
        'nome': 'HABILITAR ENVIOS FLEX', 'pergunta': 'Habilitado para Flex?',
        'como_aprovar': 'Habilite o Envios Flex para entrega no mesmo dia.\nAnúncios com Flex têm maior destaque no algoritmo e mais conversão.',
    },
    {
        'rule_key': 'UP_HAS_SIZE_CHART_MULTIVARIATION', 'grupo': 'UP_SIZE_CHART',
        'nome': 'ADICIONAR TABELA DE MEDIDAS', 'pergunta': 'Tem tabela de medidas?',
        'como_aprovar': 'Adicione uma tabela de medidas ao anúncio.\nFundamental para produtos de vestuário e calçados.',
    },
    {
        'rule_key': 'UP_CATALOG_OPTIN', 'grupo': 'UP_CATALOG',
        'nome': 'OPTAR PELO CATÁLOGO', 'pergunta': 'Optou pelo catálogo?',
        'como_aprovar': 'Faça o optin do anúncio no catálogo do ML.\nAnúncios no catálogo têm maior visibilidade.',
    },
]


def popular_criterios_qualidade(stdout, style):
    stdout.write('[CRITÉRIOS QUALIDADE] Criando critérios conhecidos...')
    for c in CRITERIOS:
        _, criado = CriterioQualidade.objects.update_or_create(
            rule_key=c['rule_key'],
            defaults={
                'grupo': c['grupo'],
                'nome': c['nome'],
                'pergunta': c['pergunta'],
                'como_aprovar': c['como_aprovar'],
                'catalogado': True,
            }
        )
        stdout.write(f"    {c['rule_key']}: {'criado' if criado else 'atualizado'}")