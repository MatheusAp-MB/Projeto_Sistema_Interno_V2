// * [RESUMO] → Script global do sistema.
//              Controla comportamentos compartilhados por todas as páginas:
//              toggle da sidebar e dropdown de navegação.

// + [STATUS: APROVADO]

// ================================================
// TOGGLE DA SIDEBAR
// ================================================

// * [EXPLICAÇÃO] → Ao clicar no botão de menu (hamburguer) na toolbar,
//                  adiciona ou remove a classe 'sidebar-oculta' no body,
//                  e GRAVA a escolha no localStorage — sem isso, a escolha
//                  se perdia a cada recarregamento de página de verdade
//                  (ex: os links de "Ordenar por", que não são AJAX/htmx).
//                  A leitura desse valor já acontece antes, no <script>
//                  inline logo no início do <body> (evita flash visual).
document.getElementById('btn-toggle-sidebar').addEventListener('click', function() {
    document.body.classList.toggle('sidebar-oculta');
    const estaOculta = document.body.classList.contains('sidebar-oculta');
    localStorage.setItem('sidebar_oculta', estaOculta);
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