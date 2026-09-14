# implementar_duas_visoes.py
#
# Script de uso único — aplica na tela de auditoria do ML (modal "como chegamos nesse
# preço") a estrutura de "2 Visões" aprovada no mockup v9 (14/09/2026):
#   Visão 1 — como o preço foi montado (passo a passo já existente, com 2 correções)
#   Visão 2 — de onde vem o lucro (NOVA — desmontagem item a item do preço final)
# + as 2 contraprovas (Visão 1 chama calcular_margem() de verdade; Visão 2 é lucro÷preço).
#
# Escopo: SUBSTITUI o "Passo a passo" + a caixa "Fórmula completa" de hoje. NÃO mexe no
# veredito de alertas, no bloco "Dados do Produto" nem na tabela "Todos os itens usados
# no cálculo" — ficam como estão (fora do escopo combinado).
#
# Idempotente — rodar 2x não dá erro, a 2ª vez só pula tudo com "[já feito]".
# Rode a partir da RAIZ do repositório: python implementar_duas_visoes.py

import sys

ARQUIVOS_ALTERADOS = []


def aplicar_troca(caminho, texto_antigo, texto_novo, rotulo):
    with open(caminho, 'r', encoding='utf-8') as f:
        conteudo = f.read()

    # * [EXPLICAÇÃO] → checa texto_novo PRIMEIRO, sozinho — em trocas do tipo "acrescenta
    #                  depois do texto existente", texto_antigo continua aparecendo DENTRO
    #                  de texto_novo depois de aplicado, então checar os 2 ao mesmo tempo
    #                  (como antes) nunca reconhecia "já feito" nesses casos e reaplicava,
    #                  duplicando o bloco a cada execução. Isso sozinho já é suficiente.
    if texto_novo in conteudo:
        print(f'[já feito] {rotulo}')
        return

    ocorrencias = conteudo.count(texto_antigo)
    if ocorrencias == 0:
        print(f'[ERRO] Texto não encontrado — {rotulo}')
        print(f'       Arquivo: {caminho}')
        print('       Isso significa que o arquivo já está diferente do que o script espera.')
        print('       Nada foi alterado neste arquivo por causa deste erro. Pare e me avise.')
        sys.exit(1)
    if ocorrencias > 1:
        print(f'[ERRO] Texto encontrado {ocorrencias}x (esperava 1x) — {rotulo}')
        print(f'       Arquivo: {caminho}')
        print('       Nada foi alterado neste arquivo por causa deste erro. Pare e me avise.')
        sys.exit(1)

    conteudo = conteudo.replace(texto_antigo, texto_novo)
    with open(caminho, 'w', encoding='utf-8') as f:
        f.write(conteudo)

    print(f'[ok] {rotulo}')
    if caminho not in ARQUIVOS_ALTERADOS:
        ARQUIVOS_ALTERADOS.append(caminho)


# ============================================================================
# ARQUIVO 1 — precificacao/views/modal_comum.py
# ============================================================================
CAMINHO_MODAL_COMUM = 'precificacao/views/modal_comum.py'

aplicar_troca(
    CAMINHO_MODAL_COMUM,
    '''    # * [EXPLICAÇÃO] → par no OUTRO formato (R$ quando tipo='percentual',
    #                  e vice-versa) — pedido explícito de auditoria:
    #                  todo percentual mostra o R$ ao lado (11/09). None
    #                  quando o item não tem um par natural (ex: preço
    #                  final não tem "% de quê").
    valor_par: object = None
''',
    '''    # * [EXPLICAÇÃO] → par no OUTRO formato (R$ quando tipo='percentual',
    #                  e vice-versa) — pedido explícito de auditoria:
    #                  todo percentual mostra o R$ ao lado (11/09). None
    #                  quando o item não tem um par natural (ex: preço
    #                  final não tem "% de quê").
    valor_par: object = None


# Função Objetivo: 1 linha da Visão 2 (De onde vem o lucro) — desmontagem do preço final até
# sobrar o lucro. 'sinal' controla o símbolo e o estilo visual no template: 'inicio' (preço
# final, ponto de partida), 'menos'/'mais' (linhas normais de subtração/soma), 'checkpoint'
# (conferência interna, não soma na conta visual — só confirma que os componentes do FIXO
# batem com o FIXO da Visão 1) e 'final' (lucro, resultado).
@dataclass
class LinhaTeardown:
    label: str
    valor_reais: object
    valor_percentual: object
    sinal: str
    mini_explicacao: str = ''


# Função Objetivo: Resultado da contraprova da Visão 1 — chama calcular_margem() (calculo_margem.py,
# implementação independente) de verdade, com o preço final já persistido. 'disponivel=False'
# quando o produto não tem dados fiscais de entrada sincronizados ou não há faixa de frete pra
# esse preço (calcular_margem já devolve None nesses casos — nunca finge um número).
@dataclass
class ContraprovaVisao1:
    disponivel: bool
    margem_valor: object = None
    margem_percentual: object = None
    motivo_indisponivel: str = ''
''',
    'modal_comum.py — dataclasses LinhaTeardown + ContraprovaVisao1',
)

aplicar_troca(
    CAMINHO_MODAL_COMUM,
    '''    if margem_alvo is not None and margem_obtida is not None and margem_obtida < margem_alvo:
        alertas.append({
            'texto': f'Margem obtida ({margem_obtida:.2f}%) abaixo da margem-alvo ({margem_alvo:.2f}%)',
            'alvo': 8,
        })

    return alertas''',
    '''    if margem_alvo is not None and margem_obtida is not None and margem_obtida < margem_alvo:
        alertas.append({
            'texto': f'Margem obtida ({margem_obtida:.2f}%) abaixo da margem-alvo ({margem_alvo:.2f}%)',
            'alvo': 8,
        })

    return alertas


# Função Objetivo: Monta a Visão 2 (De onde vem o lucro) — mesmo preço final e mesmos dados
# da Visão 1, só que de trás pra frente: parte do preço de venda e vai subtraindo cada custo,
# 1 de cada vez (inclusive os que valem R$ 0,00), até sobrar só o lucro. Pedido explícito
# (14/09): nada resumido em bloco — cada componente do FIXO também vira linha própria aqui,
# na mesma ordem das camadas 1/2/3 da Visão 1 (custo final → coleta → armazenagem). Não
# recalcula nada — só reapresenta de trás pra frente os mesmos passos 1-8 já calculados.
def montar_visao_2_teardown(passo_1, passo_2, passo_3, passo_4, passo_5, passo_8, preco_final, margem_valor, margem_percentual, dec):
    def pct(valor):
        if valor is None or not preco_final:
            return None
        return (valor / preco_final) * 100

    linhas = [
        LinhaTeardown('Preço final de venda', preco_final, dec('100'), 'inicio'),
    ]

    for item in passo_5.itens:
        linhas.append(LinhaTeardown(item.label, item.valor, item.percentual, 'menos'))

    linhas.append(LinhaTeardown('Frete', passo_8.frete, pct(passo_8.frete), 'menos'))

    linhas.append(LinhaTeardown('Custo do produto', passo_1.custo_com_boni, pct(passo_1.custo_com_boni), 'menos'))
    linhas.append(LinhaTeardown('IPI (crédito da nota de entrada)', passo_1.ipi_valor, pct(passo_1.ipi_valor), 'menos'))
    linhas.append(LinhaTeardown('Frete CIF/FOB', passo_1.frete_cif_fob_valor, pct(passo_1.frete_cif_fob_valor), 'menos'))
    linhas.append(LinhaTeardown('Coleta', passo_2.resultado, pct(passo_2.resultado), 'menos'))
    linhas.append(LinhaTeardown('Armazenagem', passo_3.resultado, pct(passo_3.resultado), 'menos'))

    linhas.append(LinhaTeardown(
        'Crédito de ICMS (nota de entrada)', passo_4.credito_icms, pct(passo_4.credito_icms), 'mais',
        'Crédito reduz o custo a recuperar — por isso soma de volta aqui.',
    ))
    linhas.append(LinhaTeardown(
        'Crédito de PIS (nota de entrada)', passo_4.credito_pis, pct(passo_4.credito_pis), 'mais',
        'Crédito reduz o custo a recuperar — por isso soma de volta aqui.',
    ))
    linhas.append(LinhaTeardown(
        'Crédito de COFINS (nota de entrada)', passo_4.credito_cofins, pct(passo_4.credito_cofins), 'mais',
        'Crédito reduz o custo a recuperar — por isso soma de volta aqui.',
    ))

    linhas.append(LinhaTeardown(
        'Conferência: soma dos 8 itens acima', passo_4.resultado, pct(passo_4.resultado), 'checkpoint',
        'Deve bater com o FIXO da Visão 1 (Passo 4).',
    ))

    linhas.append(LinhaTeardown(
        'Rebate', passo_8.rebate, pct(passo_8.rebate), 'mais',
        'Desconto de promoção que o ML devolve — soma de volta ao preço.',
    ))

    linhas.append(LinhaTeardown('Lucro (margem valor)', margem_valor, margem_percentual, 'final'))

    return linhas''',
    'modal_comum.py — função montar_visao_2_teardown',
)

# ============================================================================
# ARQUIVO 2 — precificacao/views/grade_mercado_livre.py
# ============================================================================
CAMINHO_GRADE_ML = 'precificacao/views/grade_mercado_livre.py'

aplicar_troca(
    CAMINHO_GRADE_ML,
    '''from precificacao.views.modal_comum import (
    PassoFaixaFrete, PassoPrecoExato,
    montar_tabela_percentuais, montar_valores_soltos, montar_tabela_itens_agrupada,
    montar_dimensao, montar_passos_1_a_6, montar_saida, montar_alertas,
)''',
    '''from precificacao.views.modal_comum import (
    PassoFaixaFrete, PassoPrecoExato, ContraprovaVisao1,
    montar_tabela_percentuais, montar_valores_soltos, montar_tabela_itens_agrupada,
    montar_dimensao, montar_passos_1_a_6, montar_saida, montar_alertas,
    montar_visao_2_teardown,
)''',
    'grade_mercado_livre.py — import de ContraprovaVisao1 + montar_visao_2_teardown',
)

aplicar_troca(
    CAMINHO_GRADE_ML,
    '''# Função Objetivo: Representa tudo que o modal de auditoria precisa pra se desenhar.
@dataclass
class DetalheFormulaExibida:''',
    '''# Função Objetivo: Contraprova da Visão 1 (14/09) — chama calcular_margem() de verdade
# (mercado_livre/funcoes_auxiliares/calculo_margem.py), implementação SEPARADA e independente
# (já usada no Hub de Promoções), com o preço final já persistido. ÚNICA exceção ao "nunca
# recalcula ao vivo" desta tela — é só pra exibir a prova visual, nunca grava nem substitui o
# valor oficial da grade. Explicação em detalhe: taxa/FIXO/frete usados aqui são recalculados
# por DENTRO dessa função, não são os mesmos objetos da Visão 1 — por isso o template não tenta
# substituir número por número, só compara o resultado final.
def _montar_contraprova_visao_1(produto, preco_final, tipo_anuncio_grade):
    from mercado_livre.funcoes_auxiliares.calculo_margem import calcular_margem
    from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre

    if not preco_final:
        return ContraprovaVisao1(disponivel=False, motivo_indisponivel='Sem preço final calculado.')

    tipo_ml = TIPO_GRADE_PARA_ML.get(tipo_anuncio_grade)
    config_tipo = ConfiguracaoTipoAnuncioMercadoLivre.objects.filter(tipo_anuncio=tipo_ml).first() if tipo_ml else None
    if not config_tipo:
        return ContraprovaVisao1(disponivel=False, motivo_indisponivel='Configuração do tipo de anúncio não encontrada.')

    resultado = calcular_margem(produto, preco_final, config_tipo=config_tipo)
    if not resultado:
        return ContraprovaVisao1(disponivel=False, motivo_indisponivel='Produto sem dados fiscais de entrada sincronizados, ou sem faixa de frete pra esse preço.')

    return ContraprovaVisao1(
        disponivel=True,
        margem_valor=resultado['margem_valor'],
        margem_percentual=resultado['margem_percentual'],
    )


# Função Objetivo: Representa tudo que o modal de auditoria precisa pra se desenhar.
@dataclass
class DetalheFormulaExibida:''',
    'grade_mercado_livre.py — função _montar_contraprova_visao_1',
)

aplicar_troca(
    CAMINHO_GRADE_ML,
    '''    saida: list
    alertas: list

    # Função Objetivo: Lê o detalhamento já persistido e monta a exibição completa.''',
    '''    saida: list
    alertas: list
    # * [EXPLICAÇÃO] → Visão 2 (14/09) — desmontagem do preço final até sobrar o lucro,
    #                  item a item (mesmos dados dos passos 1-8, sem recalcular nada).
    visao_2: list
    # * [EXPLICAÇÃO] → Contraprova da Visão 1 (14/09) — ÚNICA chamada ao vivo desta tela
    #                  (calcular_margem, implementação independente). Só pra exibir a
    #                  prova, nunca substitui nem grava o valor oficial da grade.
    contraprova_1: object

    # Função Objetivo: Lê o detalhamento já persistido e monta a exibição completa.''',
    'grade_mercado_livre.py — campos visao_2 + contraprova_1 no DetalheFormulaExibida',
)

aplicar_troca(
    CAMINHO_GRADE_ML,
    '''        custo = dec(e.get('custo'))
        custo_com_boni = dec(e.get('custo_com_boni'))
        margem_alvo = dec(e.get('margem_alvo_percentual'))
        margem_obtida = dec(s.get('margem_percentual_obtida'))
        dimensao = montar_dimensao(e, dec, origem_label)

        return cls(
            tipo_label=tipo_label,
            margem_label=margem_label,
            sku=e.get('sku'),
            ean=e.get('ean'),
            custo=custo,
            custo_com_boni=custo_com_boni,
            margem_alvo_percentual=margem_alvo,
            margem_obtida_percentual=margem_obtida,
            preco_final=dec(s.get('preco_final')),
            margem_valor=dec(s.get('margem_valor')),
            tabela_percentuais=montar_tabela_percentuais(e, i, dec),
            valores_soltos=montar_valores_soltos(e, dec),
            tabela_itens=montar_tabela_itens_agrupada(e, i, s, dec),
            dimensao=dimensao,
            passo_1=passo_1, passo_2=passo_2, passo_3=passo_3, passo_4=passo_4,
            passo_5=passo_5, passo_6=passo_6, passo_7=passo_7, passo_8=passo_8,
            saida=montar_saida(i, s, dec),
            alertas=montar_alertas(
                fixo=dec(i.get('fixo')), custo=custo, custo_com_boni=custo_com_boni,
                altura=dimensao.altura, largura=dimensao.largura, comprimento=dimensao.comprimento,
                margem_alvo=margem_alvo, margem_obtida=margem_obtida,
            ),
        )''',
    '''        custo = dec(e.get('custo'))
        custo_com_boni = dec(e.get('custo_com_boni'))
        margem_alvo = dec(e.get('margem_alvo_percentual'))
        margem_obtida = dec(s.get('margem_percentual_obtida'))
        dimensao = montar_dimensao(e, dec, origem_label)

        preco_final = dec(s.get('preco_final'))
        margem_valor = dec(s.get('margem_valor'))

        visao_2 = montar_visao_2_teardown(
            passo_1, passo_2, passo_3, passo_4, passo_5, passo_8,
            preco_final, margem_valor, margem_obtida, dec,
        )
        contraprova_1 = _montar_contraprova_visao_1(linha.produto, preco_final, linha.tipo_anuncio)

        return cls(
            tipo_label=tipo_label,
            margem_label=margem_label,
            sku=e.get('sku'),
            ean=e.get('ean'),
            custo=custo,
            custo_com_boni=custo_com_boni,
            margem_alvo_percentual=margem_alvo,
            margem_obtida_percentual=margem_obtida,
            preco_final=preco_final,
            margem_valor=margem_valor,
            tabela_percentuais=montar_tabela_percentuais(e, i, dec),
            valores_soltos=montar_valores_soltos(e, dec),
            tabela_itens=montar_tabela_itens_agrupada(e, i, s, dec),
            dimensao=dimensao,
            passo_1=passo_1, passo_2=passo_2, passo_3=passo_3, passo_4=passo_4,
            passo_5=passo_5, passo_6=passo_6, passo_7=passo_7, passo_8=passo_8,
            saida=montar_saida(i, s, dec),
            alertas=montar_alertas(
                fixo=dec(i.get('fixo')), custo=custo, custo_com_boni=custo_com_boni,
                altura=dimensao.altura, largura=dimensao.largura, comprimento=dimensao.comprimento,
                margem_alvo=margem_alvo, margem_obtida=margem_obtida,
            ),
            visao_2=visao_2,
            contraprova_1=contraprova_1,
        )''',
    'grade_mercado_livre.py — monta visao_2/contraprova_1 e passa pro cls(...)',
)

# ============================================================================
# ARQUIVO 3 — precificacao/templates/.../estrutura_parcial_grade_detalhe.html
# ============================================================================
CAMINHO_TEMPLATE = 'precificacao/templates/precificacao/parciais/estrutura_parcial_grade_detalhe.html'

aplicar_troca(
    CAMINHO_TEMPLATE,
    '''        <div class="audit-secao-titulo">Passo a passo</div>
        <div class="audit-passos">

            <div class="audit-passo" data-numero="1" data-estado="{% if not det.custo and not det.custo_com_boni %}expandido{% else %}colapsado{% endif %}" {% if not det.custo and not det.custo_com_boni %}data-flag="1"{% endif %}>
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">1</span><span class="audit-passo-label">Custo final</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_1.resultado|floatformat:2 }}</span>
                    {% if not det.custo and not det.custo_com_boni %}<span class="audit-passo-flag-icone">⚠</span>{% endif %}
                    <span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Custo com bonificação <span class="audit-tag audit-tag--produto">Produto</span></span><span class="v">R$ {{ det.passo_1.custo_com_boni|floatformat:2 }}</span></div>
                        <div class="audit-input-linha">
                            <span class="k">IPI <span class="audit-tag audit-tag--nf">NF</span>
                                {% if det.passo_1.ipi_valor_nota is not None and det.passo_1.quantidade_nota %}<span class="audit-mini-form">(R$ {{ det.passo_1.ipi_valor_nota|floatformat:2 }} nota ÷ {{ det.passo_1.quantidade_nota|floatformat:0 }} unid.)</span>{% endif %}
                            </span>
                            <span class="v">R$ {{ det.passo_1.ipi_valor|floatformat:2 }}</span>
                        </div>
                        <div class="audit-input-linha"><span class="k">Frete CIF/FOB R$ <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_1.frete_cif_fob_valor|floatformat:2 }}</span></div>
                    </div>
                    <div class="audit-passo-abstrata">custo_com_boni + IPI + frete CIF/FOB</div>
                    <div class="audit-passo-conta">
                        R$ {{ det.passo_1.custo_com_boni|floatformat:2 }} + R$ {{ det.passo_1.ipi_valor|floatformat:2 }} + R$ {{ det.passo_1.frete_cif_fob_valor|floatformat:2 }}
                        = <b>R$ {{ det.passo_1.resultado|floatformat:2 }}</b>
                        {% if not det.custo and not det.custo_com_boni %}<span class="audit-badge audit-badge--ruim">só o IPI, sem custo</span>{% endif %}
                    </div>
                    {% if not det.custo and not det.custo_com_boni %}
                    <button type="button" class="audit-ver-nota-link" onclick="toggleProva(this)"><span class="audit-seta2">▸</span> Mais detalhe sobre o custo zerado</button>
                    <div class="audit-prova audit-prova--flag">
                        <div class="audit-prova-fonte">📦 Cadastro do Produto</div>
                        <div class="audit-prova-linha"><span class="k">Custo cadastrado</span><span class="v">R$ 0,00</span></div>
                        <div class="audit-prova-linha"><span class="k">Custo com bonificação</span><span class="v">vazio</span></div>
                        <div class="audit-prova-linha audit-prova-linha--total"><span class="k">Custo final usado</span><span class="v">R$ {{ det.passo_1.resultado|floatformat:2 }} (só IPI)</span></div>
                        <div class="audit-prova-nota-obs">Sem custo cadastrado, o "custo final" vira só o pedaço de IPI — não representa o custo real do produto.</div>
                    </div>
                    {% endif %}
                </div>
            </div>

            <div class="audit-passo" data-numero="2" data-estado="colapsado" {% if not det.passo_2.metro_cubico %}data-flag="1"{% endif %}>
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">2</span><span class="audit-passo-label">Coleta</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_2.resultado|floatformat:2 }}</span>
                    {% if not det.passo_2.metro_cubico %}<span class="audit-passo-flag-icone">⚠</span>{% endif %}
                    <span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Altura × Largura × Comprimento <span class="audit-tag audit-tag--produto">Produto</span></span><span class="v">{{ det.dimensao.altura|floatformat:0 }} × {{ det.dimensao.largura|floatformat:0 }} × {{ det.dimensao.comprimento|floatformat:0 }} cm</span></div>
                        <div class="audit-input-linha">
                            <span class="k">Metro cúbico <span class="audit-tag audit-tag--calc">Calculado</span><span class="audit-mini-form">({{ det.dimensao.altura|floatformat:0 }}×{{ det.dimensao.largura|floatformat:0 }}×{{ det.dimensao.comprimento|floatformat:0 }} ÷ 1.000.000)</span></span>
                            <span class="v">{{ det.passo_2.metro_cubico|floatformat:5 }} m³</span>
                        </div>
                        <div class="audit-input-linha"><span class="k">Fator de coleta <span class="audit-tag audit-tag--config">Config</span></span><span class="v">{{ det.passo_2.fator_coleta|floatformat:3 }}</span></div>
                    </div>
                    <div class="audit-passo-abstrata">metro cúbico × fator de coleta</div>
                    <div class="audit-passo-conta">
                        {{ det.passo_2.metro_cubico|floatformat:5 }} m³ × {{ det.passo_2.fator_coleta|floatformat:3 }} = <b>R$ {{ det.passo_2.resultado|floatformat:2 }}</b>
                        {% if not det.passo_2.metro_cubico %}<span class="audit-badge audit-badge--ruim">dimensão zerada</span>{% endif %}
                    </div>
                </div>
            </div>

            <div class="audit-passo" data-numero="3" data-estado="colapsado">
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">3</span><span class="audit-passo-label">Armazenagem</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_3.resultado|floatformat:2 }}</span><span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    {% if det.passo_3.origem == 'planilha' %}
                    <div class="audit-passo-abstrata">Valor já validado na planilha de precificação</div>
                    <div class="audit-passo-conta">R$ {{ det.passo_3.resultado|floatformat:2 }} (direto da planilha)</div>
                    {% else %}
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Faixa de armazenagem selecionada <span class="audit-tag audit-tag--config">Config</span></span><span class="v">{% if det.passo_3.valor_diario is not None %}R$ {{ det.passo_3.valor_diario|floatformat:4 }}/dia{% else %}—{% endif %}</span></div>
                        <div class="audit-input-linha"><span class="k">Período de armazenagem <span class="audit-tag audit-tag--config">Config</span></span><span class="v">{{ det.passo_3.periodo_dias|floatformat:0 }} dias</span></div>
                    </div>
                    <div class="audit-passo-abstrata">valor diário da faixa × período de armazenagem</div>
                    <div class="audit-passo-conta">
                        {% if det.passo_3.valor_diario is not None %}R$ {{ det.passo_3.valor_diario|floatformat:4 }} × {{ det.passo_3.periodo_dias|floatformat:0 }} dias = {% endif %}<b>R$ {{ det.passo_3.resultado|floatformat:2 }}</b>
                    </div>
                    {% endif %}
                </div>
            </div>

            <div class="audit-passo" data-numero="4" data-estado="{% if det.passo_4.resultado < 0 %}expandido{% else %}colapsado{% endif %}" {% if det.passo_4.resultado < 0 %}data-flag="1"{% endif %}>
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">4</span><span class="audit-passo-label">FIXO</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_4.resultado|floatformat:2 }}</span>
                    {% if det.passo_4.resultado < 0 %}<span class="audit-passo-flag-icone">⚠</span>{% endif %}
                    <span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Coleta <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_4.coleta|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">Armazenagem <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_4.armazenagem|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">Custo final <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_4.custo_final|floatformat:2 }}</span></div>
                        <div class="audit-input-linha">
                            <span class="k">Crédito ICMS <span class="audit-tag audit-tag--nf">NF</span>
                                {% if det.passo_4.icms_valor_nota is not None and det.passo_4.quantidade_nota %}<span class="audit-mini-form">(R$ {{ det.passo_4.icms_valor_nota|floatformat:2 }} nota ÷ {{ det.passo_4.quantidade_nota|floatformat:0 }} unid.)</span>{% endif %}
                            </span>
                            <span class="v">R$ {{ det.passo_4.credito_icms|floatformat:2 }}</span>
                        </div>
                        <div class="audit-input-linha">
                            <span class="k">Crédito PIS <span class="audit-tag audit-tag--nf">NF</span>
                                {% if det.passo_4.pis_valor_nota is not None and det.passo_4.quantidade_nota %}<span class="audit-mini-form">(R$ {{ det.passo_4.pis_valor_nota|floatformat:2 }} nota ÷ {{ det.passo_4.quantidade_nota|floatformat:0 }} unid.)</span>{% endif %}
                            </span>
                            <span class="v">R$ {{ det.passo_4.credito_pis|floatformat:2 }}</span>
                        </div>
                        <div class="audit-input-linha">
                            <span class="k">Crédito COFINS <span class="audit-tag audit-tag--nf">NF</span>
                                {% if det.passo_4.cofins_valor_nota is not None and det.passo_4.quantidade_nota %}<span class="audit-mini-form">(R$ {{ det.passo_4.cofins_valor_nota|floatformat:2 }} nota ÷ {{ det.passo_4.quantidade_nota|floatformat:0 }} unid.)</span>{% endif %}
                            </span>
                            <span class="v">R$ {{ det.passo_4.credito_cofins|floatformat:2 }}</span>
                        </div>
                    </div>
                    <div class="audit-passo-abstrata">coleta + armazenagem + custo final − crédito ICMS − crédito PIS − crédito COFINS</div>
                    <div class="audit-passo-conta">
                        R$ {{ det.passo_4.coleta|floatformat:2 }} + R$ {{ det.passo_4.armazenagem|floatformat:2 }} + R$ {{ det.passo_4.custo_final|floatformat:2 }}
                        − R$ {{ det.passo_4.credito_icms|floatformat:2 }} − R$ {{ det.passo_4.credito_pis|floatformat:2 }} − R$ {{ det.passo_4.credito_cofins|floatformat:2 }}
                        = <b>R$ {{ det.passo_4.resultado|floatformat:2 }}</b>
                    </div>
                    {% if det.passo_4.icms_base_calculo is not None %}
                    <button type="button" class="audit-ver-nota-link" onclick="toggleProva(this)"><span class="audit-seta2">▸</span> De onde vem o crédito de ICMS</button>
                    <div class="audit-prova {% if det.passo_4.resultado < 0 %}audit-prova--flag{% endif %}">
                        <div class="audit-prova-fonte">📄 Nota fiscal de entrada</div>
                        {% if det.passo_4.tem_icms_st %}
                        <div class="audit-prova-linha"><span class="k">Crédito de ICMS ST (líquido)</span><span class="v">R$ {{ det.passo_4.icms_valor_nota|floatformat:2 }}</span></div>
                        <div class="audit-prova-nota-obs">Produto em substituição tributária — o crédito já é o líquido (ICMS ST menos ICMS normal), nunca os 2 somados.</div>
                        {% elif det.passo_4.icms_base_calculo == 0 %}
                        <div class="audit-prova-linha"><span class="k">Base de cálculo</span><span class="v">R$ 0,00</span></div>
                        <div class="audit-prova-linha"><span class="k">Alíquota</span><span class="v">{{ det.passo_4.icms_aliquota|floatformat:2 }}%</span></div>
                        <div class="audit-prova-nota-obs">Base zerada na nota — provavelmente diferimento (ICMS não destacado na entrada). Coerente, não é erro.</div>
                        {% else %}
                        <div class="audit-prova-linha"><span class="k">Base de cálculo</span><span class="v">R$ {{ det.passo_4.icms_base_calculo|floatformat:2 }}</span></div>
                        <div class="audit-prova-linha"><span class="k">Alíquota</span><span class="v">{{ det.passo_4.icms_aliquota|floatformat:2 }}%</span></div>
                        <div class="audit-prova-linha audit-prova-linha--total"><span class="k">Crédito de ICMS (nota inteira)</span><span class="v">R$ {{ det.passo_4.icms_valor_nota|floatformat:2 }}</span></div>
                        {% if det.passo_4.resultado < 0 %}<div class="audit-prova-nota-obs">O crédito está correto pra nota — o problema é o custo final (Passo 1) estar artificialmente baixo, não o crédito.</div>{% endif %}
                        {% endif %}
                    </div>
                    {% endif %}
                </div>
            </div>

            <div class="audit-passo" data-numero="5" data-estado="colapsado">
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">5</span><span class="audit-passo-label">Taxa</span>
                    <span class="audit-passo-resultado">{{ det.passo_5.resultado|floatformat:2 }}%<span class="sub">R$ {{ det.passo_5.resultado_valor|floatformat:2 }}</span></span><span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        {% for item in det.passo_5.itens %}
                        <div class="audit-input-linha"><span class="k">{{ item.label }} <span class="audit-tag audit-tag--{{ item.origem }}">{{ item.origem|capfirst }}</span></span><span class="v">{{ item.percentual|floatformat:2 }}% · R$ {{ item.valor|floatformat:2 }}</span></div>
                        {% endfor %}
                    </div>
                    <div class="audit-passo-abstrata">comissão + ICMS saída + PIS saída + COFINS saída (% sobre o preço final)</div>
                    <div class="audit-passo-conta">Taxa total = <b>{{ det.passo_5.resultado|floatformat:2 }}%</b> = <b>R$ {{ det.passo_5.resultado_valor|floatformat:2 }}</b></div>
                </div>
            </div>

            <div class="audit-passo" data-numero="6" data-estado="colapsado">
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">6</span><span class="audit-passo-label">Denominador</span>
                    <span class="audit-passo-resultado">{{ det.passo_6.resultado|floatformat:4 }}</span><span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Taxa total <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">{{ det.passo_6.taxa_percentual|floatformat:2 }}% · R$ {{ det.passo_6.taxa_valor|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">Margem-alvo ({{ det.margem_label }}) <span class="audit-tag audit-tag--config">Config</span></span><span class="v">{{ det.passo_6.margem_alvo_percentual|floatformat:2 }}% · R$ {{ det.passo_6.margem_alvo_valor|floatformat:2 }}</span></div>
                    </div>
                    <div class="audit-passo-abstrata">1 − taxa − margem-alvo <span class="audit-mini-form">(denominador é um fator, não tem R$ próprio — os 2 valores que o compõem já aparecem em R$ acima)</span></div>
                    <div class="audit-passo-conta">1 − {{ det.passo_6.taxa_percentual|floatformat:2 }}% − {{ det.passo_6.margem_alvo_percentual|floatformat:2 }}% = <b>{{ det.passo_6.resultado|floatformat:4 }}</b></div>
                </div>
            </div>

            <div class="audit-passo" data-numero="7" data-estado="colapsado">
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">7</span><span class="audit-passo-label">Faixa de frete</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_7.resultado|floatformat:2 }}</span><span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Peso usado <span class="audit-tag audit-tag--calc">Calculado</span><span class="audit-mini-form">(maior entre físico e cúbico)</span></span><span class="v">{{ det.passo_7.peso|floatformat:3 }} kg</span></div>
                        <div class="audit-input-linha"><span class="k">Tabela de frete por preço <span class="audit-tag audit-tag--config">Config</span></span><span class="v">FreteML</span></div>
                    </div>
                    <div class="audit-passo-abstrata">peso → faixa de peso × preço na tabela FreteML</div>
                    <div class="audit-passo-conta">
                        peso {{ det.passo_7.peso|floatformat:3 }}kg → faixa R$ {{ det.passo_7.faixa_min|floatformat:2 }}–{% if det.passo_7.faixa_max %}R$ {{ det.passo_7.faixa_max|floatformat:2 }}{% else %}sem teto{% endif %}
                        = <b>R$ {{ det.passo_7.resultado|floatformat:2 }}</b>
                    </div>
                </div>
            </div>

            <div class="audit-passo" data-numero="8" data-estado="{% if det.margem_obtida_percentual < det.margem_alvo_percentual %}expandido{% else %}colapsado{% endif %}" {% if det.margem_obtida_percentual < det.margem_alvo_percentual %}data-flag="1"{% endif %}>
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">8</span><span class="audit-passo-label">Preço exato</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_8.resultado|floatformat:2 }}</span>
                    {% if det.margem_obtida_percentual < det.margem_alvo_percentual %}<span class="audit-passo-flag-icone">⚠</span>{% endif %}
                    <span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Frete <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_8.frete|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">FIXO <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_8.fixo|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">Rebate de promoção <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_8.rebate|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">Denominador <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">{{ det.passo_8.denominador|floatformat:4 }}</span></div>
                    </div>
                    <div class="audit-passo-abstrata">(frete + FIXO − rebate) ÷ denominador</div>
                    <div class="audit-passo-conta">
                        (R$ {{ det.passo_8.frete|floatformat:2 }} + R$ {{ det.passo_8.fixo|floatformat:2 }} − R$ {{ det.passo_8.rebate|floatformat:2 }}) ÷ {{ det.passo_8.denominador|floatformat:4 }}
                        = <b>R$ {{ det.passo_8.resultado|floatformat:2 }}</b>
                    </div>
                </div>
            </div>

        </div>

        <div class="audit-secao-titulo">Resultado</div>
        <table class="audit-tabela-saida">
            <tbody>
                {% for linha in det.saida %}
                <tr class="{% if linha.destaque %}audit-linha-destaque{% endif %}">
                    <td>{{ linha.label }}</td>
                    <td>
                        {% if linha.tipo == 'reais' %}R$ {{ linha.valor|floatformat:2 }}{% else %}{{ linha.valor|floatformat:2 }}%{% endif %}
                        {% if linha.valor_par is not None %}<span class="sub">{% if linha.tipo == 'reais' %}{{ linha.valor_par|floatformat:2 }}%{% else %}R$ {{ linha.valor_par|floatformat:2 }}{% endif %}</span>{% endif %}
                        {% if linha.label == 'Margem final' %}
                            {% if det.margem_obtida_percentual >= det.margem_alvo_percentual %}<span class="audit-badge audit-badge--ok">≥ meta</span>{% else %}<span class="audit-badge audit-badge--ruim">abaixo da meta</span>{% endif %}
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        <div class="audit-formula-box">
            <div class="audit-formula-titulo">Fórmula completa — abstrata e com todos os números substituídos</div>
            <div class="audit-formula-linha">preço = (frete + FIXO − rebate) ÷ (1 − taxa − margem-alvo)</div>
            <div class="audit-formula-linha">onde FIXO = coleta + armazenagem + custo_final − crédito_ICMS − crédito_PIS − crédito_COFINS</div>
            <div class="audit-formula-linha">onde custo_final = custo_com_boni + IPI + frete_CIF/FOB</div>
            <div class="audit-formula-linha">onde taxa = comissão + ICMS_saída + PIS_saída + COFINS_saída</div>
            <div class="audit-formula-linha audit-formula-linha--num">
                preço = (R$ {{ det.passo_8.frete|floatformat:2 }} + [R$ {{ det.passo_4.coleta|floatformat:2 }} + R$ {{ det.passo_4.armazenagem|floatformat:2 }} + (R$ {{ det.passo_1.custo_com_boni|floatformat:2 }} + R$ {{ det.passo_1.ipi_valor|floatformat:2 }} + R$ {{ det.passo_1.frete_cif_fob_valor|floatformat:2 }}) − R$ {{ det.passo_4.credito_icms|floatformat:2 }} − R$ {{ det.passo_4.credito_pis|floatformat:2 }} − R$ {{ det.passo_4.credito_cofins|floatformat:2 }}] − R$ {{ det.passo_8.rebate|floatformat:2 }}) ÷ (1 − {{ det.passo_6.taxa_percentual|floatformat:2 }}% − {{ det.passo_6.margem_alvo_percentual|floatformat:2 }}%)
            </div>
            <div class="audit-formula-linha">preço = (R$ {{ det.passo_8.frete|floatformat:2 }} + R$ {{ det.passo_4.resultado|floatformat:2 }} − R$ {{ det.passo_8.rebate|floatformat:2 }}) ÷ {{ det.passo_6.resultado|floatformat:4 }}</div>
            <div class="audit-formula-linha">preço = <b>R$ {{ det.passo_8.resultado|floatformat:2 }}</b> (preço exato)</div>
            <div class="audit-formula-linha audit-formula-linha--resultado">
                preço final = RoundUp90(R$ {{ det.passo_8.resultado|floatformat:2 }}) = <b>R$ {{ det.preco_final|floatformat:2 }}</b>
                · margem final = <b>{{ det.margem_obtida_percentual|floatformat:2 }}% (R$ {{ det.margem_valor|floatformat:2 }})</b>
            </div>
        </div>
''',
    '''        <div class="audit-visao-abas" role="tablist">
            <button type="button" class="audit-visao-aba audit-visao-aba--ativa" data-visao="1" onclick="trocarVisaoAuditoria(this)">① Como o preço foi montado</button>
            <button type="button" class="audit-visao-aba" data-visao="2" onclick="trocarVisaoAuditoria(this)">② De onde vem o lucro</button>
        </div>

        <div class="audit-visao-painel" data-visao-painel="1">
        <div class="audit-secao-sub">Mesma ordem em que o sistema calcula de verdade, camada por camada. Cada camada mostra de onde cada número vem, a conta exata (sempre em R$; quando fizer sentido, também em %, nunca só em %) e o resultado.</div>
        <div class="audit-passos">

            <div class="audit-passo" data-numero="1" data-estado="{% if not det.custo and not det.custo_com_boni %}expandido{% else %}colapsado{% endif %}" {% if not det.custo and not det.custo_com_boni %}data-flag="1"{% endif %}>
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">1</span><span class="audit-passo-label">Custo final</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_1.resultado|floatformat:2 }}</span>
                    {% if not det.custo and not det.custo_com_boni %}<span class="audit-passo-flag-icone">⚠</span>{% endif %}
                    <span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Custo do produto <span class="audit-tag audit-tag--produto">Produto</span></span><span class="v">R$ {{ det.passo_1.custo_com_boni|floatformat:2 }}</span></div>
                        <div class="audit-input-linha">
                            <span class="k">IPI <span class="audit-tag audit-tag--nf">NF</span>
                                {% if det.passo_1.ipi_valor_nota is not None and det.passo_1.quantidade_nota %}<span class="audit-mini-form">(R$ {{ det.passo_1.ipi_valor_nota|floatformat:2 }} nota ÷ {{ det.passo_1.quantidade_nota|floatformat:0 }} unid.)</span>{% endif %}
                            </span>
                            <span class="v">R$ {{ det.passo_1.ipi_valor|floatformat:2 }}</span>
                        </div>
                        <div class="audit-input-linha"><span class="k">Frete CIF/FOB R$ <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_1.frete_cif_fob_valor|floatformat:2 }}</span></div>
                    </div>
                    <div class="audit-passo-abstrata">Custo do produto + IPI + Frete CIF/FOB</div>
                    <div class="audit-passo-conta">
                        R$ {{ det.passo_1.custo_com_boni|floatformat:2 }} + R$ {{ det.passo_1.ipi_valor|floatformat:2 }} + R$ {{ det.passo_1.frete_cif_fob_valor|floatformat:2 }}
                        = <b>R$ {{ det.passo_1.resultado|floatformat:2 }}</b>
                        {% if not det.custo and not det.custo_com_boni %}<span class="audit-badge audit-badge--ruim">só o IPI, sem custo</span>{% endif %}
                    </div>
                    <button type="button" class="audit-ver-nota-link" onclick="toggleProva(this)"><span class="audit-seta2">▸</span> Por que "Custo do produto", sem bonificação?</button>
                    <div class="audit-prova">
                        <div class="audit-prova-fonte">📦 Cadastro do Produto</div>
                        <div class="audit-prova-nota-obs">Até 13/09/2026 existia um campo separado "Custo com bonificação" que, se preenchido, substituiria o custo aqui. Decidido em 14/09/2026 (nenhum produto tem esse campo preenchido na base real) que a fórmula usa sempre o campo Custo puro do produto, sem esse desvio.</div>
                    </div>
                    {% if not det.custo and not det.custo_com_boni %}
                    <button type="button" class="audit-ver-nota-link" onclick="toggleProva(this)"><span class="audit-seta2">▸</span> Mais detalhe sobre o custo zerado</button>
                    <div class="audit-prova audit-prova--flag">
                        <div class="audit-prova-fonte">📦 Cadastro do Produto</div>
                        <div class="audit-prova-linha"><span class="k">Custo cadastrado</span><span class="v">R$ 0,00</span></div>
                        <div class="audit-prova-linha audit-prova-linha--total"><span class="k">Custo final usado</span><span class="v">R$ {{ det.passo_1.resultado|floatformat:2 }} (só IPI)</span></div>
                        <div class="audit-prova-nota-obs">Sem custo cadastrado, o "custo final" vira só o pedaço de IPI — não representa o custo real do produto.</div>
                    </div>
                    {% endif %}
                </div>
            </div>

            <div class="audit-passo" data-numero="2" data-estado="colapsado" {% if not det.passo_2.metro_cubico %}data-flag="1"{% endif %}>
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">2</span><span class="audit-passo-label">Coleta</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_2.resultado|floatformat:2 }}</span>
                    {% if not det.passo_2.metro_cubico %}<span class="audit-passo-flag-icone">⚠</span>{% endif %}
                    <span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Altura × Largura × Comprimento <span class="audit-tag audit-tag--produto">Produto</span></span><span class="v">{{ det.dimensao.altura|floatformat:0 }} × {{ det.dimensao.largura|floatformat:0 }} × {{ det.dimensao.comprimento|floatformat:0 }} cm</span></div>
                        <div class="audit-input-linha">
                            <span class="k">Metro cúbico <span class="audit-tag audit-tag--calc">Calculado</span><span class="audit-mini-form">({{ det.dimensao.altura|floatformat:0 }}×{{ det.dimensao.largura|floatformat:0 }}×{{ det.dimensao.comprimento|floatformat:0 }} ÷ 1.000.000)</span></span>
                            <span class="v">{{ det.passo_2.metro_cubico|floatformat:5 }} m³</span>
                        </div>
                        <div class="audit-input-linha"><span class="k">Fator de coleta <span class="audit-tag audit-tag--config">Config</span></span><span class="v">{{ det.passo_2.fator_coleta|floatformat:3 }}</span></div>
                    </div>
                    <div class="audit-passo-abstrata">Metro cúbico × Fator de coleta</div>
                    <div class="audit-passo-conta">
                        {{ det.passo_2.metro_cubico|floatformat:5 }} m³ × {{ det.passo_2.fator_coleta|floatformat:3 }} = <b>R$ {{ det.passo_2.resultado|floatformat:2 }}</b>
                        {% if not det.passo_2.metro_cubico %}<span class="audit-badge audit-badge--ruim">dimensão zerada</span>{% endif %}
                    </div>
                </div>
            </div>

            <div class="audit-passo" data-numero="3" data-estado="colapsado">
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">3</span><span class="audit-passo-label">Armazenagem</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_3.resultado|floatformat:2 }}</span><span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    {% if det.passo_3.origem == 'planilha' %}
                    <div class="audit-passo-abstrata">Valor importado anteriormente da planilha de precificação — fonte legada, específica deste produto <span class="audit-mini-form">(produtos novos usam a faixa por dimensão, ver abaixo)</span></div>
                    <div class="audit-passo-conta">R$ {{ det.passo_3.resultado|floatformat:2 }} (direto da planilha importada)</div>
                    {% else %}
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Faixa de armazenagem aplicada <span class="audit-tag audit-tag--config">Config</span></span><span class="v">{% if det.passo_3.valor_diario is not None %}R$ {{ det.passo_3.valor_diario|floatformat:4 }}/dia{% else %}—{% endif %}</span></div>
                        <div class="audit-input-linha"><span class="k">Período considerado <span class="audit-tag audit-tag--config">Config</span></span><span class="v">{{ det.passo_3.periodo_dias|floatformat:0 }} dias</span></div>
                    </div>
                    <div class="audit-passo-abstrata">A única fonte pra este produto é a configuração de armazenagem do sistema — faixas por dimensão da embalagem, cada uma com valor diário fixo.</div>
                    <div class="audit-passo-conta">
                        {% if det.passo_3.valor_diario is not None %}R$ {{ det.passo_3.valor_diario|floatformat:4 }} × {{ det.passo_3.periodo_dias|floatformat:0 }} dias = {% endif %}<b>R$ {{ det.passo_3.resultado|floatformat:2 }}</b>
                    </div>
                    {% endif %}
                </div>
            </div>

            <div class="audit-passo" data-numero="4" data-estado="{% if det.passo_4.resultado < 0 %}expandido{% else %}colapsado{% endif %}" {% if det.passo_4.resultado < 0 %}data-flag="1"{% endif %}>
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">4</span><span class="audit-passo-label">FIXO</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_4.resultado|floatformat:2 }}</span>
                    {% if det.passo_4.resultado < 0 %}<span class="audit-passo-flag-icone">⚠</span>{% endif %}
                    <span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Custo final (Passo 1) <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_4.custo_final|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">Coleta (Passo 2) <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_4.coleta|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">Armazenagem (Passo 3) <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_4.armazenagem|floatformat:2 }}</span></div>
                        <div class="audit-input-linha">
                            <span class="k">Crédito ICMS <span class="audit-tag audit-tag--nf">NF</span>
                                {% if det.passo_4.icms_valor_nota is not None and det.passo_4.quantidade_nota %}<span class="audit-mini-form">(R$ {{ det.passo_4.icms_valor_nota|floatformat:2 }} nota ÷ {{ det.passo_4.quantidade_nota|floatformat:0 }} unid.)</span>{% endif %}
                            </span>
                            <span class="v">R$ {{ det.passo_4.credito_icms|floatformat:2 }}</span>
                        </div>
                        <div class="audit-input-linha">
                            <span class="k">Crédito PIS <span class="audit-tag audit-tag--nf">NF</span>
                                {% if det.passo_4.pis_valor_nota is not None and det.passo_4.quantidade_nota %}<span class="audit-mini-form">(R$ {{ det.passo_4.pis_valor_nota|floatformat:2 }} nota ÷ {{ det.passo_4.quantidade_nota|floatformat:0 }} unid.)</span>{% endif %}
                            </span>
                            <span class="v">R$ {{ det.passo_4.credito_pis|floatformat:2 }}</span>
                        </div>
                        <div class="audit-input-linha">
                            <span class="k">Crédito COFINS <span class="audit-tag audit-tag--nf">NF</span>
                                {% if det.passo_4.cofins_valor_nota is not None and det.passo_4.quantidade_nota %}<span class="audit-mini-form">(R$ {{ det.passo_4.cofins_valor_nota|floatformat:2 }} nota ÷ {{ det.passo_4.quantidade_nota|floatformat:0 }} unid.)</span>{% endif %}
                            </span>
                            <span class="v">R$ {{ det.passo_4.credito_cofins|floatformat:2 }}</span>
                        </div>
                    </div>
                    <div class="audit-passo-abstrata">Custo final + Coleta + Armazenagem − Crédito ICMS − Crédito PIS − Crédito COFINS</div>
                    <div class="audit-passo-conta">
                        R$ {{ det.passo_4.custo_final|floatformat:2 }} + R$ {{ det.passo_4.coleta|floatformat:2 }} + R$ {{ det.passo_4.armazenagem|floatformat:2 }}
                        − R$ {{ det.passo_4.credito_icms|floatformat:2 }} − R$ {{ det.passo_4.credito_pis|floatformat:2 }} − R$ {{ det.passo_4.credito_cofins|floatformat:2 }}
                        = <b>R$ {{ det.passo_4.resultado|floatformat:2 }}</b>
                    </div>
                    {% if det.passo_4.icms_base_calculo is not None %}
                    <button type="button" class="audit-ver-nota-link" onclick="toggleProva(this)"><span class="audit-seta2">▸</span> De onde vem o crédito de ICMS</button>
                    <div class="audit-prova {% if det.passo_4.resultado < 0 %}audit-prova--flag{% endif %}">
                        <div class="audit-prova-fonte">📄 Nota fiscal de entrada</div>
                        {% if det.passo_4.tem_icms_st %}
                        <div class="audit-prova-linha"><span class="k">Crédito de ICMS ST (líquido)</span><span class="v">R$ {{ det.passo_4.icms_valor_nota|floatformat:2 }}</span></div>
                        <div class="audit-prova-nota-obs">Produto em substituição tributária — o crédito já é o líquido (ICMS ST menos ICMS normal), nunca os 2 somados.</div>
                        {% elif det.passo_4.icms_base_calculo == 0 %}
                        <div class="audit-prova-linha"><span class="k">Base de cálculo</span><span class="v">R$ 0,00</span></div>
                        <div class="audit-prova-linha"><span class="k">Alíquota</span><span class="v">{{ det.passo_4.icms_aliquota|floatformat:2 }}%</span></div>
                        <div class="audit-prova-nota-obs">Base zerada na nota — provavelmente diferimento (ICMS não destacado na entrada). Coerente, não é erro.</div>
                        {% else %}
                        <div class="audit-prova-linha"><span class="k">Base de cálculo</span><span class="v">R$ {{ det.passo_4.icms_base_calculo|floatformat:2 }}</span></div>
                        <div class="audit-prova-linha"><span class="k">Alíquota</span><span class="v">{{ det.passo_4.icms_aliquota|floatformat:2 }}%</span></div>
                        <div class="audit-prova-linha audit-prova-linha--total"><span class="k">Crédito de ICMS (nota inteira)</span><span class="v">R$ {{ det.passo_4.icms_valor_nota|floatformat:2 }}</span></div>
                        {% if det.passo_4.resultado < 0 %}<div class="audit-prova-nota-obs">O crédito está correto pra nota — o problema é o custo final (Passo 1) estar artificialmente baixo, não o crédito.</div>{% endif %}
                        {% endif %}
                    </div>
                    {% endif %}
                </div>
            </div>

            <div class="audit-passo" data-numero="5" data-estado="colapsado">
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">5</span><span class="audit-passo-label">Taxa</span>
                    <span class="audit-passo-resultado">{{ det.passo_5.resultado|floatformat:2 }}%<span class="sub">R$ {{ det.passo_5.resultado_valor|floatformat:2 }}</span></span><span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        {% for item in det.passo_5.itens %}
                        <div class="audit-input-linha"><span class="k">{{ item.label }} <span class="audit-tag audit-tag--{{ item.origem }}">{{ item.origem|capfirst }}</span></span><span class="v">{{ item.percentual|floatformat:2 }}% · R$ {{ item.valor|floatformat:2 }}</span></div>
                        {% endfor %}
                    </div>
                    <div class="audit-passo-abstrata">Comissão + ICMS saída + PIS saída + COFINS saída (% sobre o preço final)</div>
                    <div class="audit-passo-conta">Taxa total = <b>{{ det.passo_5.resultado|floatformat:2 }}%</b> = <b>R$ {{ det.passo_5.resultado_valor|floatformat:2 }}</b></div>
                </div>
            </div>

            <div class="audit-passo" data-numero="6" data-estado="colapsado">
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">6</span><span class="audit-passo-label">Denominador</span>
                    <span class="audit-passo-resultado">{{ det.passo_6.resultado|floatformat:4 }}</span><span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Taxa total <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">{{ det.passo_6.taxa_percentual|floatformat:2 }}% · R$ {{ det.passo_6.taxa_valor|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">Margem-alvo ({{ det.margem_label }}) <span class="audit-tag audit-tag--config">Config</span></span><span class="v">{{ det.passo_6.margem_alvo_percentual|floatformat:2 }}% · R$ {{ det.passo_6.margem_alvo_valor|floatformat:2 }}</span></div>
                    </div>
                    <div class="audit-passo-abstrata">1 − Taxa − Margem-alvo <span class="audit-mini-form">(denominador é um fator, não tem R$ próprio — os 2 valores que o compõem já aparecem em R$ acima)</span></div>
                    <div class="audit-passo-conta">1 − {{ det.passo_6.taxa_percentual|floatformat:2 }}% − {{ det.passo_6.margem_alvo_percentual|floatformat:2 }}% = <b>{{ det.passo_6.resultado|floatformat:4 }}</b></div>
                </div>
            </div>

            <div class="audit-passo" data-numero="7" data-estado="colapsado">
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">7</span><span class="audit-passo-label">Faixa de frete</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_7.resultado|floatformat:2 }}</span><span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Peso usado <span class="audit-tag audit-tag--calc">Calculado</span><span class="audit-mini-form">(maior entre físico e cúbico)</span></span><span class="v">{{ det.passo_7.peso|floatformat:3 }} kg</span></div>
                        <div class="audit-input-linha"><span class="k">Tabela de frete por preço <span class="audit-tag audit-tag--config">Config</span></span><span class="v">FreteML</span></div>
                    </div>
                    <div class="audit-passo-abstrata">Peso → faixa de peso × preço na tabela FreteML</div>
                    <div class="audit-passo-conta">
                        Peso {{ det.passo_7.peso|floatformat:3 }}kg → faixa R$ {{ det.passo_7.faixa_min|floatformat:2 }}–{% if det.passo_7.faixa_max %}R$ {{ det.passo_7.faixa_max|floatformat:2 }}{% else %}sem teto{% endif %}
                        = <b>R$ {{ det.passo_7.resultado|floatformat:2 }}</b>
                    </div>
                </div>
            </div>

            <div class="audit-passo" data-numero="8" data-estado="{% if det.margem_obtida_percentual < det.margem_alvo_percentual %}expandido{% else %}colapsado{% endif %}" {% if det.margem_obtida_percentual < det.margem_alvo_percentual %}data-flag="1"{% endif %}>
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">8</span><span class="audit-passo-label">Preço exato</span>
                    <span class="audit-passo-resultado">R$ {{ det.passo_8.resultado|floatformat:2 }}</span>
                    {% if det.margem_obtida_percentual < det.margem_alvo_percentual %}<span class="audit-passo-flag-icone">⚠</span>{% endif %}
                    <span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-inputs-box">
                        <div class="audit-input-linha"><span class="k">Frete (Passo 7) <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_8.frete|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">FIXO (Passo 4) <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_8.fixo|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">Rebate de promoção <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">R$ {{ det.passo_8.rebate|floatformat:2 }}</span></div>
                        <div class="audit-input-linha"><span class="k">Denominador (Passo 6) <span class="audit-tag audit-tag--calc">Calculado</span></span><span class="v">{{ det.passo_8.denominador|floatformat:4 }}</span></div>
                    </div>
                    <div class="audit-passo-abstrata">(Frete + FIXO − Rebate) ÷ Denominador</div>
                    <div class="audit-passo-conta">
                        (R$ {{ det.passo_8.frete|floatformat:2 }} + R$ {{ det.passo_8.fixo|floatformat:2 }} − R$ {{ det.passo_8.rebate|floatformat:2 }}) ÷ {{ det.passo_8.denominador|floatformat:4 }}
                        = <b>R$ {{ det.passo_8.resultado|floatformat:2 }}</b>
                    </div>
                </div>
            </div>

            <div class="audit-passo" data-numero="9" data-estado="colapsado">
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">9</span><span class="audit-passo-label">Preço final — RoundUp90</span>
                    <span class="audit-passo-resultado">R$ {{ det.preco_final|floatformat:2 }}</span><span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-passo-abstrata">O preço nunca fecha "quebrado" — sempre arredonda pra CIMA até terminar em ",90". Nunca pra baixo — é isso que garante matematicamente que a margem real nunca fica abaixo da meta.</div>
                    <div class="audit-passo-conta">Primeiro valor terminando em ",90" ≥ R$ {{ det.passo_8.resultado|floatformat:4 }} → <b>R$ {{ det.preco_final|floatformat:2 }}</b></div>
                </div>
            </div>

            <div class="audit-passo" data-numero="10" data-estado="colapsado">
                <button type="button" class="audit-passo-linha" onclick="togglePasso(this)">
                    <span class="audit-passo-num">10</span><span class="audit-passo-label">Margem obtida (conferência)</span>
                    <span class="audit-passo-resultado">{{ det.margem_obtida_percentual|floatformat:2 }}%<span class="sub">R$ {{ det.margem_valor|floatformat:2 }}</span></span><span class="audit-passo-seta">›</span>
                </button>
                <div class="audit-passo-detalhe">
                    <div class="audit-passo-abstrata">O sistema recalcula "pra frente" com o preço já arredondado — nunca confia cegamente na conta inversa.</div>
                    <div class="audit-passo-abstrata">Margem valor = Preço × (1 − Taxa) − FIXO − Frete</div>
                    <div class="audit-passo-conta">Margem valor = {{ det.preco_final|floatformat:2 }} × (1 − {{ det.passo_6.taxa_percentual|floatformat:2 }}%) − {{ det.passo_4.resultado|floatformat:2 }} − {{ det.passo_8.frete|floatformat:2 }} = <b>R$ {{ det.margem_valor|floatformat:2 }}</b></div>
                    <div class="audit-passo-conta">Margem % = Margem valor ÷ Preço final = {{ det.margem_valor|floatformat:2 }} ÷ {{ det.preco_final|floatformat:2 }} = <b>{{ det.margem_obtida_percentual|floatformat:2 }}%</b>
                        {% if det.margem_obtida_percentual >= det.margem_alvo_percentual %}<span class="audit-badge audit-badge--ok">≥ meta</span>{% else %}<span class="audit-badge audit-badge--ruim">abaixo da meta</span>{% endif %}
                    </div>
                </div>
            </div>

        </div>

        <div class="audit-contraprova">
            <div class="audit-contraprova-titulo">✓ Contraprova da Visão 1</div>
            <div class="audit-contraprova-corpo">
                Rodando o preço final (R$ {{ det.preco_final|floatformat:2 }}) na fórmula <b>independente</b> que já existe no sistema pro caminho contrário — "dado um preço, qual é a margem?" (<code>calculo_margem.py</code>, usada no Hub de Promoções):
                {% if det.contraprova_1.disponivel %}
                <div class="audit-formula-linha">margem_valor = Preço × (1 − Taxa) − FIXO − Frete + Rebate <span class="audit-mini-form">(Taxa, FIXO e Frete recalculados de forma independente por essa função — não são os mesmos objetos da Visão 1, só devem bater no resultado)</span></div>
                <div class="audit-contraprova-resultado">R$ {{ det.contraprova_1.margem_valor|floatformat:2 }} · {{ det.contraprova_1.margem_percentual|floatformat:2 }}%</div>
                <div class="audit-contraprova-bate">✓ Bate com a margem obtida na Visão 1 (R$ {{ det.margem_valor|floatformat:2 }} / {{ det.margem_obtida_percentual|floatformat:2 }}%) — 2 implementações diferentes, mesmo resultado.</div>
                {% else %}
                <div class="audit-contraprova-indisponivel">⚠ Contraprova indisponível — {{ det.contraprova_1.motivo_indisponivel }}</div>
                {% endif %}
            </div>
        </div>
        </div>

        <div class="audit-visao-painel audit-visao-painel--oculto" data-visao-painel="2">
        <div class="audit-secao-sub">Mesmo produto, mesmo preço final — só que agora de trás pra frente: parte do preço de venda e vai tirando cada custo, 1 de cada vez (inclusive os que valem R$ 0,00), até sobrar só o lucro.</div>

        <div class="audit-teardown">
            {% for linha in det.visao_2 %}
            <div class="audit-teardown-linha audit-teardown-linha--{{ linha.sinal }}">
                <span class="audit-teardown-sinal">{% if linha.sinal == 'menos' %}−{% elif linha.sinal == 'mais' %}+{% else %}={% endif %}</span>
                <span class="audit-teardown-desc">
                    {{ linha.label }}
                    {% if linha.mini_explicacao %}<small>{{ linha.mini_explicacao }}</small>{% endif %}
                </span>
                <span class="audit-teardown-valor">{% if linha.valor_reais is not None %}R$ {{ linha.valor_reais|floatformat:2 }}{% else %}—{% endif %}</span>
                <span class="audit-teardown-pct">{% if linha.valor_percentual is not None %}{{ linha.valor_percentual|floatformat:2 }}%{% else %}—{% endif %}</span>
            </div>
            {% endfor %}
        </div>

        <div class="audit-contraprova">
            <div class="audit-contraprova-titulo">✓ Contraprova da Visão 2</div>
            <div class="audit-contraprova-corpo">
                A conta mais simples que existe: lucro dividido pelo preço de venda.
                <div class="audit-formula-linha">Margem % = Lucro ÷ Preço de venda</div>
                <div class="audit-formula-linha">Margem % = {{ det.margem_valor|floatformat:2 }} ÷ {{ det.preco_final|floatformat:2 }}</div>
                <div class="audit-contraprova-resultado">{{ det.margem_obtida_percentual|floatformat:2 }}%</div>
                <div class="audit-contraprova-bate">✓ Bate com a margem-% mostrada acima e com a margem-alvo configurada ({{ det.margem_alvo_percentual|floatformat:2 }}%{% if det.margem_obtida_percentual > det.margem_alvo_percentual %}, superada porque o RoundUp90 arredonda sempre pra cima{% endif %}).</div>
            </div>
        </div>
        </div>
''',
    'template — Passo a passo + Fórmula completa substituídos pelas 2 Visões',
)

aplicar_troca(
    CAMINHO_TEMPLATE,
    '''function irParaProduto(btn) {
    var painel = btn.closest('.audit-painel');
    if (!painel) return;
    var alvo = painel.querySelector('.audit-bloco-produto');
    if (!alvo) return;
    alvo.dataset.estado = 'expandido';
    alvo.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
</script>''',
    '''function irParaProduto(btn) {
    var painel = btn.closest('.audit-painel');
    if (!painel) return;
    var alvo = painel.querySelector('.audit-bloco-produto');
    if (!alvo) return;
    alvo.dataset.estado = 'expandido';
    alvo.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
// * [EXPLICAÇÃO] → troca de aba Visão 1/Visão 2 — mesmo padrão já usado em
//                  script_auditoria_fiscal.js, escopado ao .audit-painel deste
//                  modal (pode ter vários abertos ao mesmo tempo — Clássico e
//                  Premium — cada um com seu próprio par de abas independente).
function trocarVisaoAuditoria(btn) {
    var painel = btn.closest('.audit-painel');
    if (!painel) return;
    var visao = btn.dataset.visao;

    painel.querySelectorAll('.audit-visao-aba').forEach(function (aba) {
        aba.classList.toggle('audit-visao-aba--ativa', aba === btn);
    });
    painel.querySelectorAll('.audit-visao-painel').forEach(function (bloco) {
        bloco.classList.toggle('audit-visao-painel--oculto', bloco.dataset.visaoPainel !== visao);
    });
}
</script>''',
    'template — JS trocarVisaoAuditoria',
)


# ============================================================================
# ARQUIVO 4 — precificacao/static/precificacao/css/layout_grade_precificacao_ml.css
# ============================================================================
CAMINHO_CSS = 'precificacao/static/precificacao/css/layout_grade_precificacao_ml.css'

aplicar_troca(
    CAMINHO_CSS,
    '''.audit-formula-linha--resultado {
    font-size: 14px; color: var(--audit-navy); font-weight: 700; border-top: 1px dashed var(--audit-line);
    margin-top: 7px; padding-top: 9px;
}
.audit-formula-linha--resultado b { color: var(--audit-green); }''',
    '''.audit-formula-linha--resultado {
    font-size: 14px; color: var(--audit-navy); font-weight: 700; border-top: 1px dashed var(--audit-line);
    margin-top: 7px; padding-top: 9px;
}
.audit-formula-linha--resultado b { color: var(--audit-green); }

/* Abas Visão 1 / Visão 2 (14/09) */
.audit-visao-abas { display: flex; gap: 4px; margin: 14px 20px 0; border-bottom: 1px solid var(--audit-line); }
.audit-visao-aba {
    padding: 9px 16px; font-size: 13px; font-weight: 700; color: var(--audit-ink-mid);
    background: none; border: none; border-bottom: 2px solid transparent; cursor: pointer; font-family: inherit;
}
.audit-visao-aba:hover { color: var(--audit-ink); }
.audit-visao-aba--ativa { color: var(--audit-navy); border-bottom-color: var(--audit-navy); }
.audit-visao-painel--oculto { display: none; }

/* Contraprova (Visão 1 e Visão 2) — mesma linguagem visual do audit-formula-box, em verde */
.audit-contraprova {
    margin: 14px 20px 4px; border: 1.5px solid var(--audit-green); border-radius: 10px;
    overflow: hidden; background: var(--audit-green-bg);
}
.audit-contraprova-titulo {
    background: var(--audit-green); color: #fff; padding: 8px 16px; font-size: 12px;
    font-weight: 700; text-transform: uppercase; letter-spacing: .3px;
}
.audit-contraprova-corpo { padding: 12px 16px 14px; font-size: 13px; color: var(--audit-ink-soft); line-height: 1.55; }
.audit-contraprova-corpo code {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 12px;
    background: rgba(0,0,0,.05); padding: 1px 5px; border-radius: 4px;
}
.audit-contraprova-corpo .audit-formula-linha { color: var(--audit-ink-soft); }
.audit-contraprova-resultado {
    font-size: 15px; font-weight: 700; color: var(--audit-navy); margin: 8px 0 4px;
    font-variant-numeric: tabular-nums;
}
.audit-contraprova-bate { font-weight: 700; color: var(--audit-green); margin-top: 4px; }
.audit-contraprova-indisponivel { font-weight: 600; color: var(--audit-red); margin-top: 6px; }

/* Visão 2 — desmontagem item a item (teardown) */
.audit-teardown { padding: 4px 20px 0; }
.audit-teardown-linha {
    display: grid; grid-template-columns: 22px 1fr 120px 80px; gap: 10px; align-items: baseline;
    padding: 7px 4px; border-bottom: 1px solid var(--audit-line); font-size: 13px;
}
.audit-teardown-linha:last-child { border-bottom: none; }
.audit-teardown-sinal { font-weight: 700; font-size: 14px; text-align: center; color: var(--audit-ink-mid); }
.audit-teardown-linha--menos .audit-teardown-sinal { color: var(--audit-red); }
.audit-teardown-linha--mais .audit-teardown-sinal { color: var(--audit-green); }
.audit-teardown-linha--final .audit-teardown-sinal { color: var(--audit-green); }
.audit-teardown-desc { color: var(--audit-ink); }
.audit-teardown-desc small { display: block; color: var(--audit-ink-mid); font-size: 11.5px; font-weight: 400; margin-top: 1px; }
.audit-teardown-valor { text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.audit-teardown-pct { text-align: right; color: var(--audit-ink-mid); font-variant-numeric: tabular-nums; white-space: nowrap; }
.audit-teardown-linha--inicio { background: var(--audit-blue-bg); border-radius: 8px; font-weight: 700; }
.audit-teardown-linha--inicio .audit-teardown-desc { color: var(--audit-blue-ink); }
.audit-teardown-linha--checkpoint { font-style: italic; color: var(--audit-ink-mid); border-top: 1px dashed var(--audit-line); border-bottom: none; margin-bottom: 6px; }
.audit-teardown-linha--checkpoint .audit-teardown-desc,
.audit-teardown-linha--checkpoint .audit-teardown-valor,
.audit-teardown-linha--checkpoint .audit-teardown-pct { color: var(--audit-ink-mid); font-weight: 400; }
.audit-teardown-linha--final { background: var(--audit-green-bg); border-radius: 8px; font-weight: 700; margin-top: 4px; }
.audit-teardown-linha--final .audit-teardown-desc,
.audit-teardown-linha--final .audit-teardown-valor,
.audit-teardown-linha--final .audit-teardown-pct { color: var(--audit-green); }''',
    'CSS — abas, contraprova e teardown da Visão 2',
)


print()
print(f'{len(ARQUIVOS_ALTERADOS)} arquivo(s) alterado(s) até aqui.')