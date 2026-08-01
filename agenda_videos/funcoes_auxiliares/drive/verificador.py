# agenda_videos/funcoes_auxiliares/drive/verificador.py

# Função Objetivo: TEMPORARIAMENTE DESATIVADO (30/07) — a verificação
# automática de arquivos no Drive avançava o roadmap ANTIGO (13 pontos,
# Simples/Base/Roteiros/Completos por FASE inteira). Esse conceito não existe
# mais no modelo novo (Base/Roteiro/Completo por OCORRÊNCIA) — precisa de
# redesenho próprio (convenção de nome de arquivo/pasta por ocorrência),
# ainda não discutido. Por enquanto, as 2 funções não fazem nada — import
# seguro, mas não avança nada sozinho.

from dataclasses import dataclass


@dataclass(frozen=True)
class DiagnosticoBloqueio:
    ponto: str
    mensagem: str


def verificar_produto_no_drive(produto_id):
    return [], None, None


def verificar_todos_no_drive():
    return [], []