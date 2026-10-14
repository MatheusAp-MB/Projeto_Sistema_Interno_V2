# gestao_apis/funcoes_auxiliares/tempo_legivel.py

# Função Objetivo: Transforma segundos em texto curto pra tela ("37 min",
# "4h 12min", "3 dias").


def descrever_duracao(segundos):
    segundos = max(int(segundos), 0)
    if segundos < 60:
        return 'menos de 1 min'
    minutos = segundos // 60
    if minutos < 60:
        return f'{minutos} min'
    horas, resto = divmod(minutos, 60)
    if horas < 48:
        return f'{horas}h {resto:02d}min' if resto else f'{horas}h'
    return f'{horas // 24} dias'
