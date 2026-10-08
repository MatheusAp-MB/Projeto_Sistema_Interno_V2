# integracao_mercado_livre/servicos/consultar_full_ml.py
#
# Consulta no Mercado Livre os dados de Full (Planejamento de envios) de 1
# CÓDIGO e grava o que o ML respondeu no banco da empresa
# (ConsultaFullMercadoLivre), para as telas de Full só precisarem LER do banco.
# Uma única entrada pública chama a API — e SÓ ELA:
#
#   consultar_codigo(empresa, codigo, usuario)  -> botão "Consultar no Mercado Livre" (Planejamento / ficha) e os
#                                                  botões "Atualizar" e "Fazer varredura completa" da tela "Estoque no Full"
#
# REGRA DO MATHEUS: NUNCA requisição automática à API. Nada aqui é chamado por
# tela aberta, rotina agendada, importação ou comando de rotina — só por clique
# de botão.
#
# A varredura completa chama consultar_codigo uma vez por Código ML. Para ela não reler o arquivo detalhes_mlbs.json
# (que pode ser grande) a cada Código, ela lê o arquivo UMA vez (ler_detalhes_para_varredura) e passa o resultado em
# "detalhes". Quem não passa nada continua lendo o arquivo na hora, como sempre.
#
# O que a consulta faz, nesta ordem:
#   1) Lê o detalhes_mlbs.json da empresa (sem API) e separa os registros do
#      código: código "OPXW24140" = registros cujo inventory_id é esse; código
#      "#5838589786" = registros do anúncio MLB5838589786. O banco passou a guardar
#      o inventory_id (07/10/2026), mas esta consulta ainda usa o arquivo como
#      ponte código -> produto.
#   2) Faz as chamadas GET, todas de leitura:
#        - 1 de ESTOQUE por inventory_id do código  (/inventories/{id}/stock/fulfillment)
#        - 1 de REPOS   por user_product_id do código (/marketplace/fbm/user-products/{id}/replenishment)
#        - 1 de FLEX    por user_product_id do código (/user-products/{id}/stock) — o estoque por local: o que está no
#                        Full e o que está no depósito do vendedor (acrescentada em 08/10/2026)
#      Quase sempre são 3 chamadas no total (1 + 1 + 1).
#   3) Grava 1 linha em ConsultaFullMercadoLivre com os pacotes CRUS (nada é
#      renomeado nem corrigido) e os registros do arquivo. Cada clique grava uma
#      linha nova: a anterior fica guardada para comparar momentos diferentes.
#
# Se o ML recusar o acesso (401) nada é gravado e o erro sobe para a view. Erro
# de resposta de 1 chamada (404, 403...) NÃO derruba a consulta: fica registrado
# no pacote (campo "erro") e a tela mostra o que aconteceu.

import json
from dataclasses import asdict, dataclass, field

from api_mercado_livre import ApiMercadoLivre
from core.empresa import definir_empresa_ativa
from integracao_mercado_livre.servicos.buscar_detalhes import _caminho_pasta_logs, _caminho_saida_json
from gestao_full.funcoes_auxiliares.full_ml import interpretar_codigo


class ErroConsultaFull(Exception):
    """Problema que o usuário consegue resolver (código inválido, arquivo ausente...).
    A mensagem já vem pronta para aparecer na tela."""


@dataclass
class RelatorioConsultaFull:
    """Resumo de 1 consulta — objeto de processo (nunca salvo direto no banco),
    mesmo padrão de RelatorioLeituraCaracteristicas."""
    codigo: str
    consulta_id: int | None = None
    registros_no_arquivo: int = 0
    chamadas: int = 0
    falhas: list[str] = field(default_factory=list)  # ["REPOS MLBU...: texto do erro"] (começa com ESTOQUE, REPOS ou FLEX)


# Função Objetivo: Lê o detalhes_mlbs.json da empresa e devolve
# (registros, gerado_em). Levanta ErroConsultaFull se o arquivo não existe ou
# está ilegível.
def _ler_detalhes(empresa: str):
    caminho = _caminho_saida_json(empresa)
    if not caminho.exists():
        raise ErroConsultaFull(
            'O arquivo detalhes_mlbs.json desta empresa não existe. '
            'Rode o comando buscar_detalhes para esta empresa e tente de novo.'
        )
    try:
        with open(caminho, encoding='utf-8') as arquivo:
            dados = json.load(arquivo)
    except (OSError, ValueError):
        raise ErroConsultaFull('Não consegui ler o detalhes_mlbs.json desta empresa (arquivo ilegível).')
    return dados.get('registros') or [], str(dados.get('gerado_em') or '')


# Função Objetivo: Lê o arquivo UMA vez (sem API) para a varredura completa da tela "Estoque no Full" e devolve
# (registros, gerado_em), o mesmo par que consultar_codigo espera em "detalhes". Levanta ErroConsultaFull se o arquivo
# não existe ou está ilegível.
def ler_detalhes_para_varredura(empresa: str):
    return _ler_detalhes(empresa)


# Função Objetivo: Os registros do arquivo que pertencem ao código digitado.
def _registros_do_codigo(registros, tipo, valor_interno):
    campo = 'inventory_id' if tipo == 'inventory_id' else 'mlb'
    return [r for r in registros if str(r.get(campo) or '').strip().upper() == valor_interno]


# Função Objetivo: "Consultar no Mercado Livre" — a única entrada pública. Faz
# as chamadas GET descritas no cabeçalho e grava 1 ConsultaFullMercadoLivre.
# "detalhes" (opcional) = o par (registros, gerado_em) de ler_detalhes_para_varredura; sem ele o arquivo é lido aqui.
def consultar_codigo(empresa: str, codigo: str, usuario: str = '', detalhes=None) -> RelatorioConsultaFull:
    from mercado_livre.models import ConsultaFullMercadoLivre

    definir_empresa_ativa(empresa)

    codigo_normalizado, tipo, valor_interno = interpretar_codigo(codigo)
    if codigo_normalizado is None:
        raise ErroConsultaFull(
            'Esse código não parece válido. Digite o Código ML da tela (ex.: OPXW24140) '
            'ou, quando a linha não tem Código ML, # e o número do anúncio (ex.: #5838589786).'
        )

    registros, gerado_em = detalhes if detalhes is not None else _ler_detalhes(empresa)
    do_codigo = _registros_do_codigo(registros, tipo, valor_interno)

    inventarios = sorted({str(r['inventory_id']) for r in do_codigo if r.get('inventory_id')})
    if tipo == 'inventory_id' and valor_interno not in {i.upper() for i in inventarios}:
        # A tela do ML mostrou esse Código ML mesmo que o arquivo não o conheça: ainda dá para consultar o estoque.
        inventarios.append(valor_interno)
    user_products = sorted({str(r['user_product_id']) for r in do_codigo if r.get('user_product_id')})

    if not inventarios and not user_products:
        raise ErroConsultaFull(
            f'O anúncio {valor_interno} não está no detalhes_mlbs.json ou não tem inventory_id nem '
            f'user_product_id, então não há o que consultar no Full.'
        )

    api_ml = ApiMercadoLivre(pasta_logs=_caminho_pasta_logs(empresa), empresa=empresa)
    relatorio = RelatorioConsultaFull(codigo=codigo_normalizado, registros_no_arquivo=len(do_codigo))

    # Só o 401 interrompe (levanta ErroAutenticacaoAPI e nada é gravado): nenhuma chamada seguinte funcionaria.
    estoque, reposicao, flex = {}, {}, {}
    for inventory_id in inventarios:
        pacote = api_ml.buscar_full_estoque(inventory_id)
        estoque[inventory_id] = asdict(pacote)
        relatorio.chamadas += 1
        if pacote.erro:
            relatorio.falhas.append(f'ESTOQUE {inventory_id}: {pacote.erro}')
    for user_product_id in user_products:
        pacote = api_ml.buscar_full_reposicao(user_product_id)
        reposicao[user_product_id] = asdict(pacote)
        relatorio.chamadas += 1
        if pacote.erro:
            relatorio.falhas.append(f'REPOS {user_product_id}: {pacote.erro}')
    # * [EXPLICAÇÃO] → O Flex é do produto do vendedor (user_product_id), como a reposição: o mesmo produto em dois Códigos ML
    #                  não é somado em dobro na tela (ela soma por user_product_id). O ML limita este endpoint a 100 chamadas por
    #                  minuto; cada Código faz poucas (quase sempre 1), então a varredura completa fica abaixo disso.
    for user_product_id in user_products:
        pacote = api_ml.buscar_full_flex(user_product_id)
        flex[user_product_id] = asdict(pacote)
        relatorio.chamadas += 1
        if pacote.erro:
            relatorio.falhas.append(f'FLEX {user_product_id}: {pacote.erro}')

    consulta = ConsultaFullMercadoLivre.objects.create(
        codigo=codigo_normalizado,
        usuario=usuario,
        arquivo_gerado_em=gerado_em,
        registros_arquivo=do_codigo,
        estoque=estoque,
        reposicao=reposicao,
        flex=flex,
    )
    relatorio.consulta_id = consulta.pk
    return relatorio
