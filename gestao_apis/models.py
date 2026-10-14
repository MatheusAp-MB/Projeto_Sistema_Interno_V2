# gestao_apis/models.py

# Função Objetivo: Guarda o histórico da tela "Gestão de APIs" — cada teste
# feito (e, no futuro, cada falha real registrada pelos pontos de entrada das
# integrações). Serve pra duas coisas: (1) a tabela "Eventos" da tela; (2)
# reconstruir o estado de cada conexão quando a página é aberta, sem precisar
# chamar a API externa de novo.
#
# * [DECISÃO, 14/10/2026] → App COMPARTILHADO entre as 2 empresas (Magazine e
#   Samvale): as integrações (Drive, Mercado Livre MB/SV, Sysemp MB/SV...)
#   são uma coisa só, não faz sentido ter um histórico por empresa. Por isso
#   'gestao_apis' está em APPS_SEMPRE_COMPARTILHADOS (core/database_router.py)
#   — a tabela mora sempre no banco 'default'.
#
# * [IMPORTANTE] → NUNCA gravar aqui token, chave ou senha. Os campos de texto
#   (motivo, impacto, como_resolver, evidencia) são escritos por nós. O campo
#   'resposta' guarda a resposta REAL da API (decisão de 14/10/2026), mas SÓ depois de
#   passar por preparar_resposta_para_exibir() (protecao_de_segredos.py).

from django.db import models


class EventoIntegracao(models.Model):
    # * [EXPLICAÇÃO] → 'conexao' é o id do catálogo (ex.: 'ml_mb',
    #                  'google_drive_envio') — ver funcoes_auxiliares/catalogo_conexoes.py.
    conexao = models.CharField(max_length=40, db_index=True)

    # * [EXPLICAÇÃO] → 'teste' = alguém clicou em Testar. 'erro_interno' = o
    #                  teste quebrou por falha do NOSSO código (não da API).
    #                  'autorizacao' = a autorização do Google Drive foi renovada pelo botão da tela
    #                  (só é gravada quando o login novo foi conferido no Drive).
    acao = models.CharField(max_length=20)

    # * [EXPLICAÇÃO] → Um dos 5 estados de funcionando/atencao/com_problema/
    #                  nao_verificada/nao_configurada (funcoes_auxiliares/estados.py).
    estado = models.CharField(max_length=20)

    motivo = models.CharField(max_length=300, blank=True)
    impacto = models.CharField(max_length=300, blank=True)
    como_resolver = models.CharField(max_length=300, blank=True)
    evidencia = models.CharField(max_length=300, blank=True)

    # * [EXPLICAÇÃO] → Resposta real da API no teste (JSON em várias linhas, sem segredos, cortada
    #                  em ~4000 caracteres). Aparece em "Ver detalhes". Vazio nos testes antigos.
    resposta = models.TextField(blank=True, default='')

    # * [EXPLICAÇÃO] → Quem clicou. Sem login (LOGIN_REQUIRED desligado) fica
    #                  o texto "Sem login (acesso aberto)".
    quem = models.CharField(max_length=80)

    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-criado_em', '-id']

    def __str__(self):
        return f'{self.criado_em:%d/%m/%Y %H:%M:%S} {self.conexao} {self.estado}'
