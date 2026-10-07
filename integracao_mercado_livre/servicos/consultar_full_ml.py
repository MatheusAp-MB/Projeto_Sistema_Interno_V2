# integracao_mercado_livre/servicos/consultar_full_ml.py
#
# Consulta no Mercado Livre os dados de Full (Planejamento de envios) de 1
# CÓDIGO e grava o que o ML respondeu no banco da empresa
# (ConsultaFullMercadoLivre), para a tela "Full — ficha do código" só precisar
# LER do banco. Uma única entrada pública — e SÓ ELA chama a API:
#
#   consultar_codigo(empresa, codigo, usuario)  -> botão "Consultar no Mercado Livre"
#
# REGRA DO MATHEUS: NUNCA requisição automática à API. Nada aqui é chamado por
# tela aberta, rotina agendada, importação ou comando de rotina — só por clique
# de botão.
#
# O que a consulta faz, nesta ordem:
#   1) Lê o detalhes_mlbs.json da empresa (sem API) e separa os registros do
#      código: código "OPXW24140" = registros cujo inventory_id é esse; código
#      "#5838589786" = registros do anúncio MLB5838589786. O banco não guarda
#      inventory_id (só o mlbu), por isso a ponte código -> produto é o arquivo.
#   2) Faz as chamadas GET, todas de leitura:
#        - 1 de ESTOQUE por inventory_id do código  (/inventories/{id}/stock/fulfillment)
#        - 1 de REPOS   por user_product_id do código (/marketplace/fbm/user-products/{id}/replenishment)
#      Quase sempre são 2 chamadas no total (1 + 1).
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
    falhas: list[str] = field(default_factory=list)  # ["REPOS MLBU...: texto do erro"]


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


# Função Objetivo: Os registros do arquivo que pertencem ao código digitado.
def _registros_do_codigo(registros, tipo, valor_interno):
    campo = 'inventory_id' if tipo == 'inventory_id' else 'mlb'
    return [r for r in registros if str(r.get(campo) or '').strip().upper() == valor_interno]


# Função Objetivo: "Consultar no Mercado Livre" — a única entrada pública. Faz
# as chamadas GET descritas no cabeçalho e grava 1 ConsultaFullMercadoLivre.
def consultar_codigo(empresa: str, codigo: str, usuario: str = '') -> RelatorioConsultaFull:
    from mercado_livre.models import ConsultaFullMercadoLivre

    definir_empresa_ativa(empresa)

    codigo_normalizado, tipo, valor_interno = interpretar_codigo(codigo)
    if codigo_normalizado is None:
        raise ErroConsultaFull(
            'Esse código não parece válido. Digite o Código ML da tela (ex.: OPXW24140) '
            'ou, quando a linha não tem Código ML, # e o número do anúncio (ex.: #5838589786).'
        )

    registros, gerado_em = _ler_detalhes(empresa)
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
    estoque, reposicao = {}, {}
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

    consulta = ConsultaFullMercadoLivre.objects.create(
        codigo=codigo_normalizado,
        usuario=usuario,
        arquivo_gerado_em=gerado_em,
        registros_arquivo=do_codigo,
        estoque=estoque,
        reposicao=reposicao,
    )
    relatorio.consulta_id = consulta.pk
    return relatorio
