# agenda_videos/views.py

from django.shortcuts import render
from agenda_videos.funcoes_auxiliares.contexto_tela_diarios import ContextoTelaDiarios


def view_diarios(request):
    contexto = ContextoTelaDiarios(request).montar()
    return render(request, 'agenda_videos/estrutura_diarios.html', contexto)