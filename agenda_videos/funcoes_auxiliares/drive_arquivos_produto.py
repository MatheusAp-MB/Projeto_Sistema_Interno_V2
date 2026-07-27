# agenda_videos/funcoes_auxiliares/drive_arquivos_produto.py

# Função Objetivo: Navega a estrutura {marca}/{ean}/Videos/ no Google Drive e
# devolve os arquivos encontrados — só isso, nenhuma escrita no banco, nenhuma
# lógica de avançar roadmap. Isolado de propósito (26/07) — testado sozinho
# antes de integrar em qualquer fluxo real da Agenda, mesmo espírito já usado
# na exploração da API do Mercado Livre.

import re
from django.conf import settings
from agenda_videos.funcoes_auxiliares.google_drive_cliente import obter_servico_drive


class LocalizadorArquivosProduto:

    def __init__(self):
        self.servico = obter_servico_drive()
        # * [EXPLICAÇÃO] → Cache só de pasta de MARCA, em memória, durante 1
        #                  execução — nunca persistido (não é fonte de
        #                  verdade, é só atalho pra não buscar a mesma marca
        #                  2x na mesma rodada).
        self._cache_pasta_marca = {}
        # * [EXPLICAÇÃO] → Contador de chamadas reais à API (26/07) — só pra
        #                  medir custo antes de pensar em rodar isso em lote,
        #                  nunca usado em lógica de negócio nenhuma.
        self.chamadas_realizadas = 0

    def _buscar_subpasta(self, pasta_pai_id, nome_subpasta):
        nome_escapado = nome_subpasta.replace("'", "\\'")
        query = (
            f"'{pasta_pai_id}' in parents and name = '{nome_escapado}' "
            f"and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        resultado = self.servico.files().list(q=query, fields='files(id)').execute()
        self.chamadas_realizadas += 1
        arquivos = resultado.get('files', [])
        return arquivos[0]['id'] if arquivos else None

    def _obter_pasta_marca(self, marca):
        if marca not in self._cache_pasta_marca:
            self._cache_pasta_marca[marca] = self._buscar_subpasta(settings.GOOGLE_DRIVE_PASTA_RAIZ_ID, marca)
        return self._cache_pasta_marca[marca]

    # Função Objetivo: Devolve (encontrado, arquivos, motivo, pasta_videos_id)
    # — "encontrado" distingue "pasta existe mas está vazia" de "pasta não
    # existe em algum nível" (marca/EAN/Videos). "pasta_videos_id" é
    # devolvido pra quem chama poder mover arquivo depois (precisa saber o
    # "pai" atual) ou listar o que já está em usados/.
    def localizar_arquivos(self, marca, ean):
        pasta_marca_id = self._obter_pasta_marca(marca)
        if pasta_marca_id is None:
            return False, [], f'Pasta da marca "{marca}" não encontrada na raiz do Drive.', None

        pasta_ean_id = self._buscar_subpasta(pasta_marca_id, ean)
        if pasta_ean_id is None:
            return False, [], f'Pasta do EAN "{ean}" não encontrada dentro de "{marca}".', None

        pasta_videos_id = self._buscar_subpasta(pasta_ean_id, 'Videos')
        if pasta_videos_id is None:
            return False, [], f'Subpasta "Videos" não encontrada dentro de "{marca}/{ean}".', None

        # * [EXPLICAÇÃO] → Traz "id" junto com "name" — o parser precisa dos
        #                  2, não só do nome (ver parser_arquivos_drive.py,
        #                  ArquivoDrive).
        resultado = self.servico.files().list(
            q=f"'{pasta_videos_id}' in parents and trashed = false",
            fields='files(id, name)',
        ).execute()
        self.chamadas_realizadas += 1
        return True, resultado.get('files', []), None, pasta_videos_id

    # Função Objetivo: Lista o conteúdo bruto de Videos/usados/ ([] se a
    # subpasta ainda não existir) — usado por quem precisa considerar "o que
    # já existiu" (completude do pool), não só "o que sobrou na pasta agora"
    # (que é o que localizar_arquivos mostra, sem misturar os 2 conceitos).
    def listar_arquivos_usados(self, pasta_videos_id):
        pasta_usados_id = self._buscar_subpasta(pasta_videos_id, 'usados')
        if pasta_usados_id is None:
            return []
        resultado = self.servico.files().list(
            q=f"'{pasta_usados_id}' in parents and trashed = false",
            fields='files(id, name)',
        ).execute()
        self.chamadas_realizadas += 1
        return resultado.get('files', [])

    # Função Objetivo: Conta quantos vídeos numerados já existem dentro de
    # Videos/usados/{prefixo}_NN.mp4 — usado pra RECONSTRUIR o estado de
    # consumo (estado_consumo_drive.py) quando ele não existe ainda, ou ficou
    # desatualizado. Só conta sequência contígua a partir de 1, mesmo
    # critério já usado no parser (parser_arquivos_drive.py).
    def contar_ja_usados(self, pasta_videos_id, prefixo):
        padrao = re.compile(rf'^{prefixo}_(\d{{2}})\.mp4$', re.IGNORECASE)
        numeros = sorted(
            int(m.group(1)) for m in (padrao.match(a['name']) for a in self.listar_arquivos_usados(pasta_videos_id)) if m
        )
        contador = 0
        esperado = 1
        for numero in numeros:
            if numero == esperado:
                contador += 1
                esperado += 1
            else:
                break
        return contador