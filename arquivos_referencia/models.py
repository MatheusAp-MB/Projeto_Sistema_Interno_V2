# arquivos_referencia/models.py

# Função Objetivo: Guardar, POR EMPRESA, a última vez que o sistema foi atualizado com cada arquivo de referência do Drive
# (botão "Atualizar o sistema com o Drive"). Serve para a tela mostrar "Data da última atualização do sistema com este arquivo"
# e dizer se o sistema está em dia com o que está no Drive.
#
# * [DECISÃO, 15/10/2026] → Fica no banco de CADA empresa (o app não é compartilhado): a importação grava nas duas empresas de forma
#   independente, então o histórico também é independente — uma empresa pode estar em dia e a outra não.
# * [EXPLICAÇÃO] → Só existe 1 linha por arquivo (arquivo_id é único): cada atualização bem-sucedida troca a linha. O "md5" é a
#   impressão digital do arquivo que foi lido do Drive; a tela compara com a impressão digital do arquivo que está no Drive AGORA:
#   iguais = o sistema está em dia; diferentes = o Drive tem uma versão que o sistema ainda não leu.
# * [IMPORTANTE] → A linha é gravada DENTRO da mesma transação da importação (ver atualizacao_do_sistema.py): se a importação for
#   desfeita, o histórico não muda — nunca existe "atualizado em" de uma atualização que não aconteceu.

from django.db import models


class AtualizacaoDoSistema(models.Model):
    arquivo_id = models.SlugField(
        max_length=60, unique=True,
        help_text='Id do cartão em catalogo_arquivos.py (ex.: frete-mercado-livre).',
    )
    atualizado_em = models.DateTimeField(help_text='Quando o sistema foi atualizado com este arquivo pela última vez.')
    arquivo_md5 = models.CharField(max_length=32, help_text='Impressão digital (MD5) do arquivo lido do Drive nessa atualização.')
    arquivo_enviado_em = models.DateTimeField(
        null=True, blank=True, help_text='Data do arquivo no Drive (data do último envio) no momento da leitura.',
    )
    linhas_novas = models.PositiveIntegerField(default=0)
    linhas_mudaram = models.PositiveIntegerField(default=0)
    linhas_iguais = models.PositiveIntegerField(default=0)
    linhas_removidas = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Atualização do sistema com arquivo de referência'
        verbose_name_plural = 'Atualizações do sistema com arquivos de referência'

    def __str__(self):
        return f'{self.arquivo_id} — {self.atualizado_em:%d/%m/%Y %H:%M}'


# Função Objetivo: Guardar, POR EMPRESA, as configurações de como a tela "Arquivos de referência" importa os arquivos. Hoje existe 1: o MODO da planilha
# Busca Legal (Expandir ou Substituir), escolhido no card de configuração no topo da tela.
#
# * [DECISÃO, 16/10/2026] → O modo é uma CONFIGURAÇÃO da empresa (não uma propriedade de um arquivo do Drive) e vale para os dois passos: ao ENVIAR ao
#   Drive (Expandir junta a planilha ao arquivo do Drive; Substituir troca o arquivo inteiro) e ao ATUALIZAR o sistema (Expandir atualiza o que existe e cria o
#   que falta; Substituir deixa o sistema igual à planilha). Fica no banco de CADA empresa: cada uma tem a sua planilha Busca Legal e o seu modo. As tabelas
#   de frete não têm modo (sempre espelham o arquivo). Sem linha gravada, o modo é Expandir (o padrão seguro: nunca apaga).
# * [EXPLICAÇÃO] → 1 linha por configuração (`chave` é única); `valor` é o texto escolhido.

class ConfiguracaoDaImportacao(models.Model):
    chave = models.SlugField(max_length=60, unique=True, help_text='Qual configuração é (ex.: modo-da-busca-legal).')
    valor = models.CharField(max_length=30, help_text='O valor escolhido (ex.: expandir ou substituir).')
    alterado_em = models.DateTimeField(auto_now=True, help_text='Quando a configuração foi alterada pela última vez.')

    class Meta:
        verbose_name = 'Configuração da importação'
        verbose_name_plural = 'Configurações da importação'

    def __str__(self):
        return f'{self.chave} = {self.valor}'
