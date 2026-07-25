import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from datetime import date, timedelta
from agenda_videos.models import Fase
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import (
    proximo_dia_util, adicionar_dias_uteis, proxima_segunda, proximo_dia_1,
    adicionar_meses, ultimo_dia_do_mes, calcular_janela_fase, calcular_janela_ocorrencia,
)

erros = []


def checar(nome, obtido, esperado):
    ok = obtido == esperado
    print(f"[{'OK' if ok else 'FALHOU'}] {nome}: obtido={obtido} esperado={esperado}")
    if not ok:
        erros.append(nome)


print("=== 1) proximo_dia_util — todos os 7 dias da semana como entrada ===")
base = date(2026, 7, 20)  # segunda
dias_semana = ['seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'dom']
for i in range(7):
    d = base + timedelta(days=i)
    esperado = d if i < 5 else date(2026, 7, 27)
    checar(f"proximo_dia_util({d} = {dias_semana[i]})", proximo_dia_util(d), esperado)

print("\n=== 2) adicionar_dias_uteis — fim de semana e virada de ano ===")
checar("adicionar_dias_uteis(seg 20/07, 0)", adicionar_dias_uteis(date(2026, 7, 20), 0), date(2026, 7, 20))
checar("adicionar_dias_uteis(seg 20/07, 4)", adicionar_dias_uteis(date(2026, 7, 20), 4), date(2026, 7, 24))
checar("adicionar_dias_uteis(seg 20/07, 5) pula fds", adicionar_dias_uteis(date(2026, 7, 20), 5), date(2026, 7, 27))
checar("adicionar_dias_uteis(sex 25/12, 3) vira o ano", adicionar_dias_uteis(date(2026, 12, 25), 3), date(2026, 12, 30))

print("\n=== 3) proxima_segunda — os 7 dias, incluindo já-segunda (não deve pular) ===")
for i in range(7):
    d = base + timedelta(days=i)
    esperado = d if i == 0 else date(2026, 7, 27)
    checar(f"proxima_segunda({d} = {dias_semana[i]})", proxima_segunda(d), esperado)

print("\n=== 4) proximo_dia_1 — meio do mês, último dia, já-dia-1 (não deve pular) ===")
checar("proximo_dia_1(01/09, já é dia 1)", proximo_dia_1(date(2026, 9, 1)), date(2026, 9, 1))
checar("proximo_dia_1(15/09, meio do mês)", proximo_dia_1(date(2026, 9, 15)), date(2026, 10, 1))
checar("proximo_dia_1(30/09, último dia)", proximo_dia_1(date(2026, 9, 30)), date(2026, 10, 1))
checar("proximo_dia_1(31/12, virada de ano)", proximo_dia_1(date(2026, 12, 31)), date(2027, 1, 1))

print("\n=== 5) adicionar_meses — virada de ano, 12 e 18 meses ===")
checar("adicionar_meses(01/10, 0)", adicionar_meses(date(2026, 10, 1), 0), date(2026, 10, 1))
checar("adicionar_meses(01/10, 2)", adicionar_meses(date(2026, 10, 1), 2), date(2026, 12, 1))
checar("adicionar_meses(01/11, 2) cruza ano", adicionar_meses(date(2026, 11, 1), 2), date(2027, 1, 1))
checar("adicionar_meses(01/01, 12)", adicionar_meses(date(2026, 1, 1), 12), date(2027, 1, 1))
checar("adicionar_meses(01/06, 18)", adicionar_meses(date(2026, 6, 1), 18), date(2027, 12, 1))

print("\n=== 6) ultimo_dia_do_mes — fevereiro bissexto/não, mês 30/31 dias ===")
checar("fev/2026 (não bissexto)", ultimo_dia_do_mes(date(2026, 2, 10)), date(2026, 2, 28))
checar("fev/2028 (bissexto)", ultimo_dia_do_mes(date(2028, 2, 10)), date(2028, 2, 29))
checar("dez (virada de ano)", ultimo_dia_do_mes(date(2026, 12, 5)), date(2026, 12, 31))
checar("abr (30 dias)", ultimo_dia_do_mes(date(2026, 4, 15)), date(2026, 4, 30))

print("\n=== 7) calcular_janela_fase — DIÁRIA ===")
j = calcular_janela_fase(Fase.DIARIA, date(2026, 7, 25), 10)
checar("ref=sáb 25/07, período=10 -> início", j.inicio, date(2026, 7, 27))
checar("ref=sáb 25/07, período=10 -> fim", j.fim, date(2026, 8, 7))
j = calcular_janela_fase(Fase.DIARIA, date(2026, 7, 20), 10)
checar("ref=seg 20/07 (já útil) -> não pula", j.inicio, date(2026, 7, 20))
j = calcular_janela_fase(Fase.DIARIA, date(2026, 7, 20), 1)
checar("período=1 -> início==fim", (j.inicio, j.fim), (date(2026, 7, 20), date(2026, 7, 20)))

print("\n=== 8) calcular_janela_fase — SEMANAL ===")
j = calcular_janela_fase(Fase.SEMANAL, date(2026, 7, 30), 4)
checar("ref=qui 30/07, período=4 -> início", j.inicio, date(2026, 8, 3))
checar("ref=qui 30/07, período=4 -> fim", j.fim, date(2026, 8, 28))
j = calcular_janela_fase(Fase.SEMANAL, date(2026, 8, 3), 4)
checar("ref=seg 03/08 (já segunda) -> não pula", j.inicio, date(2026, 8, 3))

print("\n=== 9) calcular_janela_fase — MENSAL ===")
j = calcular_janela_fase(Fase.MENSAL, date(2026, 9, 15), 3)
checar("ref=15/09, período=3 -> início", j.inicio, date(2026, 10, 1))
checar("ref=15/09, período=3 -> fim", j.fim, date(2026, 12, 31))
j = calcular_janela_fase(Fase.MENSAL, date(2026, 10, 1), 3)
checar("ref=01/10 (já dia 1) -> não pula", j.inicio, date(2026, 10, 1))
j = calcular_janela_fase(Fase.MENSAL, date(2026, 11, 20), 3)
checar("ref=20/11, período=3, cruza ano -> início", j.inicio, date(2026, 12, 1))
checar("ref=20/11, período=3, cruza ano -> fim", j.fim, date(2027, 2, 28))

print("\n=== 10) calcular_janela_ocorrencia — ocorrência 1 == início da fase ===")
checar("Diária", calcular_janela_ocorrencia(Fase.DIARIA, date(2026, 7, 27), 1).inicio, date(2026, 7, 27))
checar("Semanal", calcular_janela_ocorrencia(Fase.SEMANAL, date(2026, 8, 3), 1).inicio, date(2026, 8, 3))
checar("Mensal", calcular_janela_ocorrencia(Fase.MENSAL, date(2026, 10, 1), 1).inicio, date(2026, 10, 1))

print("\n=== 11) última ocorrência bate com fim da fase ===")
jd = calcular_janela_fase(Fase.DIARIA, date(2026, 7, 27), 10)
checar("Diária", calcular_janela_ocorrencia(Fase.DIARIA, jd.inicio, 10).fim, jd.fim)
js = calcular_janela_fase(Fase.SEMANAL, date(2026, 8, 3), 4)
checar("Semanal", calcular_janela_ocorrencia(Fase.SEMANAL, js.inicio, 4).fim, js.fim)
jm = calcular_janela_fase(Fase.MENSAL, date(2026, 10, 1), 3)
checar("Mensal", calcular_janela_ocorrencia(Fase.MENSAL, jm.inicio, 3).fim, jm.fim)

print("\n=== 12) Diária — ocorrência cruzando fim de semana ===")
checar("início=qua 22/07, ocorrência 3 (sem pular)", calcular_janela_ocorrencia(Fase.DIARIA, date(2026, 7, 22), 3).inicio, date(2026, 7, 24))
checar("início=qua 22/07, ocorrência 4 (pula fds)", calcular_janela_ocorrencia(Fase.DIARIA, date(2026, 7, 22), 4).inicio, date(2026, 7, 27))

print()
if erros:
    print(f"### {len(erros)} CASO(S) FALHARAM: {erros}")
else:
    print("### TODOS OS CASOS PASSARAM ###")