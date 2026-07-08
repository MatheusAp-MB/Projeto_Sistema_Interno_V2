// * [RESUMO] → Busca interna dos filtros da tela de Resumo de Critérios.
//              Mesmo comportamento já usado no Hub de Anúncios.

// * [EXPLICAÇÃO] → Essa tela usa muito espaço horizontal (tabela larga),
//                  então o menu lateral começa oculto por padrão aqui —
//                  reaproveita a mesma classe que o botão de recolher já
//                  usa em script_global.js, o usuário pode reabrir
//                  normalmente clicando no botão de sempre.
document.body.classList.add('sidebar-oculta');

document.addEventListener('input', function (evento) {
    var campo = evento.target.closest('.filtro-busca-interna');
    if (!campo) return;

    var termo = campo.value.trim().toLowerCase();
    var lista = campo.closest('.filtro-grupo').querySelector('.filtro-opcoes-lista');

    lista.querySelectorAll('.filtro-opcao').forEach(function (opcao) {
        var texto = opcao.textContent.trim().toLowerCase();
        opcao.style.display = texto.indexOf(termo) !== -1 ? '' : 'none';
    });
});