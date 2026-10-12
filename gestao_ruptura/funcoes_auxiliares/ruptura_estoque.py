# gestao_ruptura/funcoes_auxiliares/ruptura_estoque.py
#
# Função Objetivo: O ESTOQUE que a tela "Previsão de Ruptura de estoque" usa quando não é digitado: o estoque do FULL, lido da última consulta SALVA de cada Código ML (a mesma que a tela
# "Estoque no Full" mostra; ver gestao_full.funcoes_auxiliares.full_estoque_ml.estoque_full_dos_codigos). Aqui mora a regra de QUAL PARTE do estoque do Full conta para a cobertura
# ("estoque considerado") e a soma dos Códigos ML de um produto (SKU) ou de um anúncio (MLB). Só contas sobre os cartões já lidos: NÃO há banco, API nem tela aqui.
#
# REGRA DO MATHEUS que mora aqui (PROVISÓRIA: proposta aceita em 12/10/2026 com "pode gerar"; a regra real é dele e pode mudar aqui, em UM lugar só):
#   ESTOQUE CONSIDERADO = disponível para venda + em transferência + em processo interno.
#   Ficam FORA da conta (aparecem à parte, "fora da conta"): retirada, danificada, perdida, não suportada, sem cobertura fiscal e qualquer motivo novo que o Mercado Livre mandar.
#   O "A CAMINHO" (unidades enviadas e ainda não recebidas, hipótese do Estoque no Full) aparece em coluna própria e, POR PADRÃO, NÃO entra na cobertura. Só entra quando a pessoa marca
#   "Considerar as unidades a caminho" (pedido do Matheus, 12/10/2026): aí ele é SOMADO ao estoque considerado, como se as unidades já estivessem no Full hoje (estoque_para_cobertura).
#
#   O QUE O MERCADO LIVRE RECOMENDA (urgência e sugestão de envio) mora na MESMA consulta salva (reposição) e é somado aqui, por Código, em `resumir_ml` (referência "Mercado Livre" da tela).
#
# * [EXPLICAÇÃO] → O estoque do Full é do CÓDIGO ML, não do anúncio (dois MLBs do mesmo Código mostram o mesmo número). Por isso o estoque de um SKU ou de um MLB é a soma dos
#                  Códigos dele, cada Código uma vez só (quem chama passa os Códigos já sem repetição). Um Código sem consulta salva (ou com a consulta em erro) NÃO entra na soma e o
#                  resultado fica "parcial": a tela avisa, em vez de tratar o que não foi lido como estoque zero ("ausente não é zero").

from gestao_ruptura.funcoes_auxiliares.ruptura_calculo import URGENCIAS_DO_ML

# status do Mercado Livre (not_available_detail do estoque) que CONTAM como estoque, no jeito que a API manda (as duas grafias de "processo interno").
MOTIVOS_EM_TRANSFERENCIA = ('transfer',)
MOTIVOS_EM_PROCESSO_INTERNO = ('internal_process', 'internalProcess')


# Função Objetivo: Quantas unidades de um Código estão em transferência e em processo interno (os dois motivos do indisponível que contam como estoque).
def _quantidades_que_contam(motivos):
    transferencia = sum(m['quantidade'] or 0 for m in motivos if m['status'] in MOTIVOS_EM_TRANSFERENCIA)
    processo = sum(m['quantidade'] or 0 for m in motivos if m['status'] in MOTIVOS_EM_PROCESSO_INTERNO)
    return transferencia, processo


# Função Objetivo: A soma do estoque do Full de um conjunto de Códigos ML (os de um SKU, de um MLB ou um só), a partir dos cartões de estoque_full_dos_codigos.
# Devolve: `estado` ('ok' = todos os Códigos lidos | 'parcial' = alguns sem leitura | 'sem_leitura' = nenhum lido), `considerado` (o número que a tela usa; None se nenhum foi lido),
# as partes (`disponivel`, `transferencia`, `processo`), `nao_conta` (indisponível que fica fora da conta), `total` (o Total no Full), as listas `sem_consulta`, `com_erro` e
# `desatualizados` (Códigos), `mais_antiga` / `idade` (a consulta mais antiga entre as lidas) e `a_caminho` (None até preencher_a_caminho).
def somar_codigos(codigos, cartoes):
    todos = sorted({str(c).upper() for c in codigos if c})
    lidos, sem_consulta, com_erro, desatualizados = [], [], [], []
    for codigo in todos:
        cartao = cartoes.get(codigo)
        if cartao is None or cartao['estado'] == 'sem_consulta':
            sem_consulta.append(codigo)
        elif cartao['estado'] != 'ok':
            com_erro.append(codigo)
        else:
            lidos.append(cartao)
            if cartao['desatualizado']:
                desatualizados.append(codigo)
    soma = {'disponivel': 0, 'transferencia': 0, 'processo': 0, 'nao_conta': 0, 'total': 0}
    for cartao in lidos:
        disponivel = cartao['disponivel'] or 0
        transferencia, processo = _quantidades_que_contam(cartao['motivos'])
        soma['disponivel'] += disponivel
        soma['transferencia'] += transferencia
        soma['processo'] += processo
        soma['nao_conta'] += max((cartao['indisponivel'] or 0) - transferencia - processo, 0)
        soma['total'] += cartao['total'] or 0
    mais_antiga = min(lidos, key=lambda c: c['consultado_em']) if lidos else None
    if not lidos:
        estado = 'sem_leitura'
    else:
        estado = 'ok' if len(lidos) == len(todos) else 'parcial'
    return {'estado': estado, 'n_codigos': len(todos), 'n_lidos': len(lidos), 'considerado': (soma['disponivel'] + soma['transferencia'] + soma['processo']) if lidos else None,
            **soma, 'sem_consulta': sem_consulta, 'com_erro': com_erro, 'desatualizados': desatualizados,
            'mais_antiga': mais_antiga['consultado_em'] if mais_antiga else None, 'idade': mais_antiga['idade'] if mais_antiga else '', 'a_caminho': None, 'a_caminho_parcial': False}


# Função Objetivo: Preenche `a_caminho` de uma soma (somar_codigos) com o "A caminho" de cada Código lido (cartões já passados por a_caminho_dos_codigos). Se algum Código lido ficou sem
# esse número, a soma só tem os que têm e `a_caminho_parcial` fica verdadeiro; se nenhum tem, continua None ("—").
def preencher_a_caminho(resumo, codigos, cartoes):
    valores, faltando = [], 0
    for codigo in {str(c).upper() for c in codigos if c}:
        cartao = cartoes.get(codigo)
        if not cartao or cartao['estado'] != 'ok':
            continue
        if cartao.get('a_caminho') is None:
            faltando += 1
        else:
            valores.append(cartao['a_caminho'])
    resumo['a_caminho'] = sum(valores) if valores else None
    resumo['a_caminho_parcial'] = bool(valores) and faltando > 0


# Função Objetivo: O estoque que ENTRA na cobertura de uma soma (somar_codigos): o considerado e, só se a opção "Considerar as unidades a caminho" estiver marcada, mais o a caminho. É o ÚNICO
# lugar onde essa escolha vira número (a lista, o detalhe, o gráfico e o diagnóstico usam este valor). Devolve None quando nenhum Código foi lido ("ausente não é zero"). Um Código lido sem o
# número de "a caminho" soma 0 (e a tela avisa que ele ficou de fora). Quem chama precisa ter passado a soma por preencher_a_caminho antes.
# * [EXPLICAÇÃO] → O a caminho é uma HIPÓTESE (as unidades ainda não chegaram): marcar a opção trata essas unidades como se já estivessem no Full HOJE. Por isso a opção vem desmarcada.
def estoque_para_cobertura(resumo, com_a_caminho):
    if resumo['considerado'] is None:
        return None
    return resumo['considerado'] + ((resumo['a_caminho'] or 0) if com_a_caminho else 0)


# Função Objetivo: A conta do estoque considerado escrita em português ("Disponível 120 + em transferência 10 + em processo interno 0 = 130"), para o tooltip e o detalhe. Com a opção "Considerar
# as unidades a caminho" marcada, a conta continua com "+ a caminho N = total". Diz também o que ficou fora da conta e o que não foi lido. Vazio quando nenhum Código foi lido.
def texto_da_conta(resumo, numero, com_a_caminho=False):
    if resumo['considerado'] is None:
        return ''
    texto = (f'Disponível {numero(resumo["disponivel"])} + em transferência {numero(resumo["transferencia"])} + em processo interno {numero(resumo["processo"])} '
             f'= {numero(resumo["considerado"])} un')
    if com_a_caminho and resumo['a_caminho']:
        texto += f' + a caminho {numero(resumo["a_caminho"])}{" (parcial)" if resumo["a_caminho_parcial"] else ""} = {numero(estoque_para_cobertura(resumo, True))} un'
    if resumo['nao_conta']:
        texto += f'. Fora da conta: {numero(resumo["nao_conta"])} un indisponíveis por outro motivo (retirada, danificadas, perdidas...)'
    faltando = resumo['sem_consulta'] + resumo['com_erro']
    if faltando:
        texto += f'. Não lidos (não entram na soma): {", ".join(faltando)}'
    return texto + '.'


# ==================================================== o que o Mercado Livre recomenda ====================================================

# Função Objetivo: O selo (rótulo, classe CSS e ícone) de uma urgência na língua do Mercado Livre ('URGENT', 'THIS_WEEK'...): o MESMO selo da tela "Full — Planejamento de envios" (registro único em
# mercado_livre/funcoes_auxiliares/badges.py). Valor que o ML mandar e eu não conheço aparece com o texto cru. None quando não há urgência.
def selo_da_urgencia(chave):
    from mercado_livre.funcoes_auxiliares.badges import BADGE_PADRAO, BADGES_URGENCIA_FULL

    if not chave:
        return None
    return BADGES_URGENCIA_FULL.get(chave) or {**BADGE_PADRAO, 'label': str(chave)}


# Função Objetivo: O que o Mercado Livre recomenda para um conjunto de Códigos ML (os de um SKU, de um anúncio ou um só), somando o `ml` de cada cartão (full_estoque_ml.ml_dos_codigos). Devolve:
#   `estado`      'ok' (todos os Códigos têm recomendação) | 'parcial' (só alguns) | 'sem_dados' (nenhum) — `motivo` diz por quê quando falta
#   `urgencia`    a MAIS urgente entre os Códigos (um SKU com um Código urgente é urgente); None se nenhum Código trouxe urgência
#   `sugestao_min` / `sugestao_max`  a soma das sugestões de envio dos Códigos (faixa: o mínimo e o máximo); None se nenhum Código trouxe número (nunca vira zero);
#                 `sugestao_exata` quando todas as sugestões somadas são exatas; "não repor" do ML (NO_REPLENISHMENT...) conta como 0 un: o ML disse que não é para enviar
#   `n_com_sugestao`, `nao_repor` (todos os Códigos com "não repor"), `estrela`, `prazo` (o mais próximo) e `por_codigo` (a linha de cada Código, para o tooltip).
# * [EXPLICAÇÃO] → A sugestão que vale para o gráfico e para a comparação é o MÍNIMO (`sugestao_min`): quando o ML manda uma faixa ("de 100 a 150"), o começo da faixa é a quantidade que ele já considera
#                  necessária; a faixa inteira aparece no cartão. Código sem número NÃO entra na soma (não é zero) e deixa o resultado "parcial".
def resumir_ml(codigos, cartoes):
    todos = sorted({str(c).upper() for c in codigos if c})
    por_codigo, com_dados, motivos = [], 0, set()
    menor, maior, n_sug, todas_exatas, urgencias, prazos, nao_repor, estrela = 0, 0, 0, True, [], [], 0, False
    for codigo in todos:
        ml = (cartoes.get(codigo) or {}).get('ml') or {'estado': 'sem_consulta', 'urgencia': None, 'sugestao': None, 'recomendacao': None, 'prazo': '', 'estrela': False, 'n_produtos': 0, 'erro': ''}
        sug, restricao = ml['sugestao'], bool(ml['recomendacao']) and ml['recomendacao'].startswith('NO_REPLENISHMENT')
        if ml['estado'] == 'ok':
            com_dados += 1
            if ml['urgencia']:
                urgencias.append(ml['urgencia'])
            if ml['prazo']:
                prazos.append(ml['prazo'])
            estrela = estrela or ml['estrela']
            if sug:
                menor, maior, n_sug, todas_exatas = menor + sug['min'], maior + sug['max'], n_sug + 1, todas_exatas and sug['tipo'] == 'exact'
            elif restricao:
                n_sug, nao_repor = n_sug + 1, nao_repor + 1
        else:
            motivos.add('erro' if ml['estado'] == 'erro' else ('sem_reposicao' if ml['estado'] == 'sem_reposicao' else 'sem_consulta'))
        por_codigo.append({'codigo': codigo, 'estado': ml['estado'], 'urgencia': ml['urgencia'], 'sugestao': sug, 'recomendacao': ml['recomendacao'], 'prazo': ml['prazo'], 'n_produtos': ml['n_produtos']})
    if com_dados == 0:
        estado = 'sem_dados'
        motivo = ('a consulta de reposição deu erro' if 'erro' in motivos else
                  ('a consulta salva não trouxe a reposição' if 'sem_reposicao' in motivos else 'ainda não há consulta salva'))
    else:
        estado, motivo = ('ok' if com_dados == len(todos) else 'parcial'), ''
    ordem = {u: i for i, u in enumerate(URGENCIAS_DO_ML)}
    return {'estado': estado, 'motivo': motivo, 'n_codigos': len(todos), 'n_com_dados': com_dados, 'por_codigo': por_codigo,
            'urgencia': min(urgencias, key=lambda u: ordem.get(u, len(ordem))) if urgencias else None,
            'sugestao_min': menor if n_sug else None, 'sugestao_max': maior if n_sug else None, 'sugestao_exata': todas_exatas and n_sug > 0, 'n_com_sugestao': n_sug,
            'nao_repor': n_sug > 0 and nao_repor == n_sug, 'estrela': estrela, 'prazo': min(prazos) if prazos else ''}
