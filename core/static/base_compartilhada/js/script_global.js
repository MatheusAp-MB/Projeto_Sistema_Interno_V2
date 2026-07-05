// * [RESUMO] → Script global do sistema.
//              Controla comportamentos compartilhados por todas as páginas:
//              toggle da sidebar e dropdown de navegação.

// + [STATUS: APROVADO]

// ================================================
// TOGGLE DA SIDEBAR
// ================================================

// * [EXPLICAÇÃO] → Ao clicar no botão de menu (hamburguer) na toolbar,
//                  adiciona ou remove a classe 'sidebar-oculta' no body.
//                  O CSS usa essa classe para esconder ou mostrar a sidebar.
document.getElementById('btn-toggle-sidebar').addEventListener('click', function() {
    document.body.classList.toggle('sidebar-oculta');
});

// ================================================
// DROPDOWN DA SIDEBAR
// ================================================

// * [EXPLICAÇÃO] → Seleciona todos os itens que têm dropdown na sidebar.
//                  Para cada um, adiciona um listener de clique que
//                  abre ou fecha o submenu correspondente.
document.querySelectorAll('.sidebar-dropdown-toggle').forEach(function(toggle) {
    toggle.addEventListener('click', function(e) {
        e.preventDefault();

        // * [EXPLICAÇÃO] → closest() sobe na árvore do DOM até encontrar
        //                  o elemento pai com a classe 'sidebar-dropdown'.
        const dropdown = this.closest('.sidebar-dropdown');
        dropdown.classList.toggle('aberto');
    });
});