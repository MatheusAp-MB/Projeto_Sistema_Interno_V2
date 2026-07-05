# * [RESUMO] → Views do app core.
#              Contém as views globais do sistema — login, logout e homepage.

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages

# ================================================
# LOGIN
# ================================================

def view_login(request):
    # * [EXPLICAÇÃO] → Se o usuário já está autenticado, redireciona
    #                  direto para a homepage.
    if request.user.is_authenticated:
        return redirect('/')

    if request.method == 'POST':
        usuario = request.POST.get('username')
        senha   = request.POST.get('password')

        user = authenticate(request, username=usuario, password=senha)

        if user is not None:
            login(request, user)
            return redirect('/')
        else:
            # * [EXPLICAÇÃO] → PRG Pattern — após erro, adiciona a mensagem
            #                  e redireciona para GET. Isso evita o aviso do
            #                  navegador ao recarregar a página.
            messages.error(request, 'Usuário ou senha incorretos.')
            return redirect('login')

    return render(request, 'pagina_login/estrutura_login.html')


# ================================================
# LOGOUT
# ================================================

def view_logout(request):
    # * [EXPLICAÇÃO] → O logout() encerra a sessão do usuário —
    #                  remove os dados de autenticação do cookie.
    logout(request)
    return redirect('/login/')

# ================================================
# HOMEPAGE
# ================================================

def view_home(request):
    # * [EXPLICAÇÃO] → View da homepage — página inicial do sistema.
    #                  Por enquanto só renderiza o template.
    #                  Futuramente pode receber dados de resumo/dashboard.
    return render(request, 'pagina_home/estrutura_home.html')