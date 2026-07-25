import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from datetime import timedelta
import openpyxl

from produtos.models import Produto
from agenda_videos.models import (
    ConfiguracaoFase, Fase, ProgressoProducaoVideo, StatusVideo,
    AndamentoAgenda, StatusManualAgenda,
)
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_fase, proximo_dia_util

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CAMINHO_PLANILHA = 'MAGAZINE.xlsx'
# ========================================

MAPA_FASE_PLANILHA = {'Diária': Fase.DIARIA, 'Semanal': Fase.SEMANAL, 'Mensal': Fase.MENSAL}
MAPA_STATUS_MANUAL = {'Ativo': StatusManualAgenda.ATIVO, 'Pausado': StatusManualAgenda.PAUSADO}

# * [EXPLICAÇÃO] → get_or_create nunca sobrescreve se você já tiver ajustado
#                  esses números pelo admin — só cria se ainda não existir.
config_diaria, _ = ConfiguracaoFase.objects.get_or_create(
    fase=Fase.DIARIA, defaults={'quantidade_postagens': 1, 'periodo': 10})
config_semanal, _ = ConfiguracaoFase.objects.get_or_create(
    fase=Fase.SEMANAL, defaults={'quantidade_postagens': 1, 'periodo': 4})
config_mensal, _ = ConfiguracaoFase.objects.get_or_create(
    fase=Fase.MENSAL, defaults={'quantidade_postagens': 1, 'periodo': 3})

MAPA_CONFIG = {Fase.DIARIA: config_diaria, Fase.SEMANAL: config_semanal, Fase.MENSAL: config_mensal}

print(f"Config Diária: período={config_diaria.periodo}")
print(f"Config Semanal: período={config_semanal.periodo}")
print(f"Config Mensal: período={config_mensal.periodo}")
print()


# Função Objetivo: Normaliza EAN vindo do Excel (float tipo 7908276662348.0) pra texto puro.
def normalizar_ean(valor):
    if valor is None:
        return None
    if isinstance(valor, float):
        return str(int(valor))
    return str(valor).strip()


# Função Objetivo: Encadeia pra frente, a partir da Data de Cadastro, até a fase atual.
# Explicação em detalhe: não faz matemática reversa nenhuma — só simula, em ordem, as
# transições automáticas já confirmadas (Diária → Semanal → Mensal), usando a mesma
# função de cálculo de janela que já existe e já foi testada (39 casos).
def calcular_janela_fase_atual(fase_destino, data_cadastro):
    inicio_ciclo = proximo_dia_util(data_cadastro + timedelta(days=1))
    janela_diaria = calcular_janela_fase(Fase.DIARIA, inicio_ciclo, config_diaria.periodo)
    if fase_destino == Fase.DIARIA:
        return janela_diaria

    janela_semanal = calcular_janela_fase(Fase.SEMANAL, janela_diaria.fim + timedelta(days=1), config_semanal.periodo)
    if fase_destino == Fase.SEMANAL:
        return janela_semanal

    janela_mensal = calcular_janela_fase(Fase.MENSAL, janela_semanal.fim + timedelta(days=1), config_mensal.periodo)
    return janela_mensal


wb = openpyxl.load_workbook(CAMINHO_PLANILHA, data_only=True)
ws = wb['Base de Produtos']

criados = 0
nao_encontrados = []
fase_invalida = []

for numero_linha in range(2, ws.max_row + 1):
    valores = [ws.cell(row=numero_linha, column=c).value for c in range(1, 13)]
    (empresa, ean_bruto, produto_nome, marca, data_cad, status_manual_bruto,
     fase_bruta, ocorrencia, vence_em, status_exec, id_, prioridade) = valores

    if not produto_nome and not ean_bruto:
        continue

    ean = normalizar_ean(ean_bruto)
    # * [EXPLICAÇÃO] → endswith, não igualdade exata — o Excel guarda EAN como
    #                  número, e número perde zero à esquerda (0070341902806
    #                  vira 70341902806 ao ler). Isso casa certo não importa
    #                  quantos zeros o banco realmente tem, sem eu precisar
    #                  fixar um tamanho de EAN (13 dígitos, etc.).
    candidatos = list(Produto.objects.filter(ean__endswith=ean))
    if len(candidatos) == 0:
        nao_encontrados.append((ean, produto_nome))
        continue
    if len(candidatos) > 1:
        print(f"[AMBÍGUO] EAN {ean} bateu com {len(candidatos)} produtos — pulando, confira manualmente.")
        continue
    produto = candidatos[0]

    fase_destino = MAPA_FASE_PLANILHA.get(fase_bruta)
    if fase_destino is None:
        fase_invalida.append((ean, produto_nome, fase_bruta))
        continue

    # * [EXPLICAÇÃO] → Decisão A (confirmada): produto já em Diária/Semanal/Mensal
    #                  na planilha antiga significa que já tinha vídeo pronto —
    #                  marca os 4 primeiros pontos do roadmap como concluídos.
    progresso, _ = ProgressoProducaoVideo.objects.get_or_create(produto=produto)
    progresso.video_simples_status = StatusVideo.GERADO
    progresso.video_base_status = StatusVideo.GERADO
    progresso.roteiros_gerados = True
    progresso.completos_produzidos = True
    progresso.quantidade_roteiros = config_diaria.periodo
    progresso.save()

    data_cadastro_pura = data_cad.date() if hasattr(data_cad, 'date') else data_cad
    janela = calcular_janela_fase_atual(fase_destino, data_cadastro_pura)

    AndamentoAgenda.objects.update_or_create(
        produto=produto,
        defaults={
            'fase_atual': MAPA_CONFIG[fase_destino],
            'ocorrencia_atual': int(ocorrencia) if ocorrencia else 1,
            'inicio_fase': janela.inicio,
            'fim_fase': janela.fim,
            'status_manual': MAPA_STATUS_MANUAL.get(status_manual_bruto, StatusManualAgenda.ATIVO),
            'urgente': False,
        }
    )
    criados += 1
    print(f"[OK] EAN {ean} — {produto_nome[:45]} | {fase_bruta} | ocorrência {int(ocorrencia)} | {janela.inicio} → {janela.fim}")

print()
print(f"=== RESUMO ===")
print(f"Importados/atualizados: {criados}")
print(f"Não encontrados no banco (EAN sem Produto correspondente): {len(nao_encontrados)}")
for ean, nome in nao_encontrados[:15]:
    print(f"  EAN {ean} — {nome}")
print(f"Fase inválida/vazia: {len(fase_invalida)}")
for ean, nome, fase in fase_invalida[:15]:
    print(f"  EAN {ean} — {nome} — fase='{fase}'")