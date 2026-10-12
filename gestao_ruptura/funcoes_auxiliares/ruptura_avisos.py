# gestao_ruptura/funcoes_auxiliares/ruptura_avisos.py
#
# Função Objetivo: O DONO ÚNICO do AVISO da tela "Previsão de Ruptura de estoque": como um aviso nasce (`aviso`, `aviso_de_contagem`), em que ordem eles aparecem e como a caixa "N avisos sobre os dados" os
# organiza (`organizar_avisos`). A lista do Full, a do Fora do Full e o detalhe só CRIAM avisos por aqui; o template (parciais/estrutura_parcial_avisos.html) só DESENHA o que sai daqui. Só texto e organização: nada de
# banco, API ou conta (as contas ficam em ruptura_calculo.py e os números de cada aviso vêm de quem o cria).
#
# * [EXPLICAÇÃO] → A FORMA do aviso (a mesma em toda a tela): `classe` ("erro" | "aviso" | "info"), `titulo` (o que é, curto), `numero` (o número que importa, em destaque; vazio quando não há), `texto` (o que isso
#                  significa e o que fazer) e, se houver ação, `link` + `link_texto`. Com número, o título continua a frase dele ("579" + "Códigos ML com consulta de estoque antiga").
# * [EXPLICAÇÃO] → A ORDEM é a da gravidade: erro, depois "pedem atenção" (aviso), depois "para saber" (info); dentro de cada grupo vale a ordem em que foram criados. Com 2 ou mais avisos e nenhum erro eles vão
#                  AGRUPADOS numa caixa recolhida de uma linha (não empurra os cartões e a tabela para baixo); erro nunca fica escondido (cada aviso vira uma faixa).

from gestao_vendas.funcoes_auxiliares.vendas_ml import numero

CLASSES_NA_ORDEM = ('erro', 'aviso', 'info')
GRUPOS_DA_CAIXA = (('aviso', 'Pedem atenção'), ('info', 'Para saber'))


# Função Objetivo: Um aviso na forma da tela (ver o cabeçalho): classe, título, texto, número em destaque e o link de ação (opcionais).
def aviso(classe, titulo, texto='', numero_texto='', link='', link_texto=''):
    return {'classe': classe, 'titulo': titulo, 'texto': texto, 'numero': numero_texto, 'link': link, 'link_texto': link_texto}


# Função Objetivo: Um aviso que CONTA coisas: o número vai em destaque e o título concorda com ele ("1 Código ML sem consulta" / "17 Códigos ML sem consulta"; inteiros a partir de mil saem com ponto, como no resto da tela).
def aviso_de_contagem(classe, n, singular, plural_, texto='', link='', link_texto=''):
    return aviso(classe, singular if n == 1 else plural_, texto, numero(n), link, link_texto)


# Função Objetivo: Junta os avisos da tela (os da página e os da lista) e diz como mostrar: `avisos` já na ordem da gravidade; `agrupar` (2 ou mais e nenhum erro); `grupos` (Pedem atenção / Para saber, só os que têm aviso);
# `titulo` e `contagens` (a caixa recolhida: "4 avisos sobre os dados" e, só quando algum pede atenção, o selo "1 pede atenção").
# * [EXPLICAÇÃO] → A caixa FECHADA é de propósito mínima (decisão do Matheus, 12/10/2026): só diz que há avisos e se algum pede atenção. O conteúdo de cada aviso só aparece quando a pessoa abre a caixa; nada de resumo dos avisos na linha fechada.
def organizar_avisos(avisos):
    ordenados = sorted(avisos, key=lambda a: CLASSES_NA_ORDEM.index(a['classe']))
    grupos = [{'chave': chave, 'rotulo': rotulo, 'itens': [a for a in ordenados if a['classe'] == chave]} for chave, rotulo in GRUPOS_DA_CAIXA]
    grupos = [g for g in grupos if g['itens']]
    n_atencao = sum(1 for a in ordenados if a['classe'] == 'aviso')
    contagens = [{'classe': 'aviso', 'texto': f'{n_atencao} {"pede" if n_atencao == 1 else "pedem"} atenção'}] if n_atencao else []
    return {
        'avisos': ordenados,
        'agrupar': len(ordenados) > 1 and not any(a['classe'] == 'erro' for a in ordenados),
        'tem_atencao': n_atencao > 0,
        'grupos': grupos,
        'titulo': f'{len(ordenados)} avisos sobre os dados',
        'contagens': contagens,
    }
