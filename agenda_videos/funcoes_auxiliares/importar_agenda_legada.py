# agenda_videos/funcoes_auxiliares/importar_agenda_legada.py

# Função Objetivo: Importa o ESTADO ATUAL da Agenda (fase, ocorrência, status
# manual, vencimento) a partir da planilha legada do Google Sheets ("Agenda de
# Clipes"), exportada como .xlsx (ex: MAGAZINE.xlsx). Lê só a aba "Base de
# Produtos" — "Agenda" é um filtro dela mesma (exclui Pausados), sem dado
# próprio; "Concluídos"/"Adicionar Produtos" ficam fora por decisão do usuário.
#
# Casa por EAN com Produto JÁ EXISTENTE (nunca cria Produto novo — os produtos
# já vêm do import normal do ERP). Reutilizável — update_or_create em tudo,
# seguro rodar de novo se a planilha for atualizada.
#
# Decisões confirmadas com o usuário (26/07):
#   - inicio_fase = "Data de Cadastro" da planilha, direto.
#   - fim_ocorrencia_atual = "Vence em" da planilha, direto (é o dado real que
#     importa de verdade pra Atrasado/Risco/A Fazer Hoje).
#   - Roteiros/Completos/Vídeo Simples/Base de toda fase até a atual =
#     assumidos como já prontos ("Decisão A", mesmo espírito de sempre).
#   - Nenhuma Postagem é criada (fora de escopo, decisão do usuário).
#   - Nenhum timestamp novo (agendado_em, roteiros_marcado_em, etc.) é
#     preenchido — dado legado, nunca inventamos a hora exata.

import pandas as pd
from produtos.models import Produto
from agenda_videos.models import (
    Fase, ConfiguracaoFase, AndamentoAgenda, StatusManualAgenda,
    ProgressoProducaoVideo, StatusVideo, PreparacaoVideoFase,
)
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_fase
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto
from agenda_videos.views import ORDEM_FASES

ABA_ORIGEM = 'Base de Produtos'

MAPA_FASE = {label: valor for valor, label in Fase.choices}
MAPA_STATUS_MANUAL = {label: valor for valor, label in StatusManualAgenda.choices}


# Função Objetivo: Representa e valida 1 linha da planilha — nunca deixa
# passar dado ruim silenciosamente, sempre com erro explícito por linha.
class LinhaAgendaLegada:

    def __init__(self, linha_bruta):
        self.linha_bruta = linha_bruta
        self.ean = None
        self.fase = None
        self.status_manual = None
        self.ocorrencia_atual = None
        self.inicio_fase = None
        self.fim_ocorrencia_atual = None
        self.erro = None

    def validar_e_extrair(self):
        try:
            # * [EXPLICAÇÃO] → dtype=str na leitura só ajuda se a célula do
            #                  Excel já era TEXTO — se era NÚMERO, o zero à
            #                  esquerda já se perdeu dentro do próprio
            #                  arquivo, antes de qualquer código rodar (não
            #                  tem "00" num número, matematicamente). A
            #                  correção é completar até 13 dígitos (padrão
            #                  EAN-13, único formato visto em todo o catálogo
            #                  até agora) — se o EAN já tinha 13 dígitos,
            #                  zfill não muda nada; se perdeu zero à esquerda
            #                  no Excel, recupera.
            ean_bruto = str(self.linha_bruta['Código de barras']).strip()
            ean_bruto = ean_bruto[:-2] if ean_bruto.endswith('.0') else ean_bruto
            self.ean = ean_bruto.zfill(13)

            fase_label = str(self.linha_bruta['Fase Atual']).strip()
            self.fase = MAPA_FASE.get(fase_label)
            if self.fase is None:
                self.erro = f'Fase "{fase_label}" não reconhecida'
                return self

            status_label = str(self.linha_bruta['Status Manual']).strip()
            self.status_manual = MAPA_STATUS_MANUAL.get(status_label)
            if self.status_manual is None:
                self.erro = f'Status Manual "{status_label}" não reconhecido'
                return self

            self.ocorrencia_atual = int(self.linha_bruta['Ocorrência Atual'])
            self.inicio_fase = self.linha_bruta['Data de Cadastro'].date()
            self.fim_ocorrencia_atual = self.linha_bruta['Vence em'].date()
        except (ValueError, TypeError, AttributeError) as erro:
            self.erro = f'Dado inválido/faltando ({erro})'
        return self


# Função Objetivo: Marca Simples/Base + Roteiros/Completos de toda fase até a
# atual (inclusive) como já prontos — "Decisão A".
def _marcar_preparo_ja_feito(produto, fase_atual, mapa_config_fase):
    ProgressoProducaoVideo.objects.update_or_create(
        produto=produto,
        defaults={'video_simples_status': StatusVideo.GERADO, 'video_base_status': StatusVideo.GERADO},
    )

    indice_fase_atual = ORDEM_FASES.index(fase_atual)
    for fase in ORDEM_FASES[:indice_fase_atual + 1]:
        periodo_atual = mapa_config_fase[fase].periodo
        PreparacaoVideoFase.objects.update_or_create(
            produto=produto, fase=fase,
            defaults={
                'roteiros_gerados': True, 'roteiros_quantidade_no_clique': periodo_atual,
                'completos_produzidos': True, 'completos_quantidade_no_clique': periodo_atual,
            },
        )


def importar_agenda_legada(caminho_arquivo, stdout, style):
    stdout.write(f'[AGENDA LEGADA] Lendo "{ABA_ORIGEM}" de {caminho_arquivo}...')
    # * [EXPLICAÇÃO] → dtype=str força o pandas a ler EAN como TEXTO desde o
    #                  início — sem isso, ele infere como número por padrão,
    #                  e qualquer EAN com zero à esquerda perde esse zero
    #                  ANTES do resto do código rodar (str()/int() depois já
    #                  não recupera o que foi perdido na leitura).
    df = pd.read_excel(caminho_arquivo, sheet_name=ABA_ORIGEM, dtype={'Código de barras': str})

    mapa_config_fase = {c.fase: c for c in ConfiguracaoFase.objects.all()}
    faltando = [f for f in ORDEM_FASES if f not in mapa_config_fase]
    if faltando:
        stdout.write(style.ERROR(
            f'Configuração de Fase ainda não existe pra: {", ".join(faltando)}. '
            f'Crie em Agenda de Vídeos → Configurações antes de importar.'
        ))
        return

    atualizados = 0
    nao_encontrados = []
    erros_linha = []

    for _, linha_bruta in df.iterrows():
        linha = LinhaAgendaLegada(linha_bruta).validar_e_extrair()
        if linha.erro:
            erros_linha.append(f'EAN {linha_bruta.get("Código de barras")}: {linha.erro}')
            continue

        produto = Produto.objects.filter(ean=linha.ean).first()
        if produto is None:
            nao_encontrados.append(linha.ean)
            continue

        config_fase = mapa_config_fase[linha.fase]
        janela_fase = calcular_janela_fase(linha.fase, linha.inicio_fase, config_fase.periodo)

        AndamentoAgenda.objects.update_or_create(
            produto=produto,
            defaults={
                'fase_atual': config_fase,
                'ocorrencia_atual': linha.ocorrencia_atual,
                'inicio_fase': linha.inicio_fase,
                'fim_fase': janela_fase.fim,
                'fim_ocorrencia_atual': linha.fim_ocorrencia_atual,
                'status_manual': linha.status_manual,
                'concluido': False,
                'concluido_em': None,
                'concluido_marcado_em': None,
                'agendado_em': None,
            },
        )
        _marcar_preparo_ja_feito(produto, linha.fase, mapa_config_fase)
        sincronizar_roadmap_agenda_produto(produto)
        atualizados += 1

    stdout.write('')
    stdout.write(style.SUCCESS(f'[AGENDA LEGADA] Concluído! {atualizados} produto(s) atualizado(s).'))
    if nao_encontrados:
        stdout.write(style.WARNING(
            f'{len(nao_encontrados)} EAN(s) da planilha não encontrados no banco (Produto não existe): '
            + ', '.join(nao_encontrados)
        ))
    if erros_linha:
        stdout.write(style.WARNING(f'{len(erros_linha)} linha(s) com erro de dado:'))
        for erro in erros_linha:
            stdout.write(style.WARNING(f'    {erro}'))