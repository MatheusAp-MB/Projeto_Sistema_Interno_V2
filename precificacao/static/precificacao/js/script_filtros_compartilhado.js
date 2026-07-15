/*
* [RESUMO] → Busca interna dos filtros (Marca, Categoria) — usada em
* qualquer tela com o painel de filtros avançados (.filtro-busca-
* interna dentro de .filtro-subgrupo). Compartilhado entre Grade e
* Resumo por Marketplace, pra não duplicar essa lógica em 2 lugares.
*/

document.addEventListener('input', function (evento) {
    var campo = evento.target.closest('.filtro-busca-interna');
    if (!campo) return;

    var termo = campo.value.trim().toLowerCase();
    var lista = campo.closest('.filtro-subgrupo').querySelector('.filtro-opcoes-lista');

    lista.querySelectorAll('.filtro-opcao').forEach(function (opcao) {
        var texto = opcao.textContent.trim().toLowerCase();
        opcao.style.display = texto.indexOf(termo) !== -1 ? '' : 'none';
    });
});