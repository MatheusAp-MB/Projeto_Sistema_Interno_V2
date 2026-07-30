# scripts_dev/reverter_teste_replicacao_automatica.py

# Função Objetivo: Reverte 1 produto específico pro estado "Aguardando Replicar"
# depois de um teste de ponta a ponta bem-sucedido — desfaz exatamente o que
# view_marcar_concluido (api/replicacao_automatica/views.py) fez: volta a
# Postagem de "replicado" pra "aprovado" e volta ocorrencia_atual no
# AndamentoAgenda, sem cruzar fase (produto ficou dentro da mesma fase).

import os
import sys


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, 'manage.py')):
            sys.path.insert(0, caminho_atual)
            return
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError('Não foi possível encontrar manage.py subindo a partir deste script.')


_adicionar_raiz_do_projeto_ao_path()

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from produtos.models import Produto
from agenda_videos.models import Postagem, StatusPostagem, Fase
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_ocorrencia
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EAN_PARA_REVERTER = '7896660874272'
FASE_ESPERADA_ANTES = Fase.DIARIA      # fase_atual ANTES de reverter (checagem de segurança)
OCORRENCIA_ESPERADA_ANTES = 2          # ocorrencia_atual ANTES de reverter (checagem de segurança)
OCORRENCIA_ALVO = 1                    # ocorrencia_atual DEPOIS de reverter
# ========================================

print(f'--- {EAN_PARA_REVERTER} ---')

produto = Produto.objects.filter(ean=EAN_PARA_REVERTER).first()
if produto is None:
    print('  Produto não encontrado no banco. Abortando.')
    sys.exit(1)

andamento = getattr(produto, 'andamento_agenda', None)
if andamento is None:
    print('  Produto sem AndamentoAgenda. Abortando.')
    sys.exit(1)

# * [EXPLICAÇÃO] → Só prossegue se o estado atual bater exatamente com o
#                  confirmado antes de rodar este script — evita reverter em
#                  cima de um estado diferente do esperado.
if andamento.fase_atual.fase != FASE_ESPERADA_ANTES or andamento.ocorrencia_atual != OCORRENCIA_ESPERADA_ANTES:
    print(
        f'  Estado atual (fase={andamento.fase_atual.fase}, '
        f'ocorrencia_atual={andamento.ocorrencia_atual}) não bate com o esperado '
        f'(fase={FASE_ESPERADA_ANTES}, ocorrencia_atual={OCORRENCIA_ESPERADA_ANTES}). '
        f'Abortando sem mexer em nada.'
    )
    sys.exit(1)

postagem = Postagem.objects.filter(
    produto=produto, fase=FASE_ESPERADA_ANTES, numero_ocorrencia=OCORRENCIA_ALVO,
).order_by('-criado_em').first()

if postagem is None:
    print(f'  Nenhuma Postagem encontrada pra fase={FASE_ESPERADA_ANTES}, ocorrência={OCORRENCIA_ALVO}. Abortando.')
    sys.exit(1)

if postagem.status != StatusPostagem.REPLICADO:
    print(f'  Postagem #{postagem.id} está "{postagem.status}", não "replicado" — abortando (não é o cenário esperado).')
    sys.exit(1)

print(f'  Postagem #{postagem.id} — status atual: {postagem.status}')
postagem.status = StatusPostagem.APROVADO
postagem.replicado_em = None
postagem.save(update_fields=['status', 'replicado_em'])
print('  Revertida pra "aprovado" (replicado_em limpo).')

andamento.ocorrencia_atual = OCORRENCIA_ALVO
janela = calcular_janela_ocorrencia(andamento.fase_atual.fase, andamento.inicio_fase, OCORRENCIA_ALVO)
andamento.fim_ocorrencia_atual = janela.fim
andamento.save(update_fields=['ocorrencia_atual', 'fim_ocorrencia_atual'])
print(f'  AndamentoAgenda revertido: ocorrencia_atual={OCORRENCIA_ALVO}, fim_ocorrencia_atual={janela.fim}.')

sincronizar_roadmap_agenda_produto(produto)
print('  Roadmap ressincronizado.')

print()
print('Concluído — produto de volta em Diária Dia 01 de 10, Postagem aprovada, aguardando replicar.')