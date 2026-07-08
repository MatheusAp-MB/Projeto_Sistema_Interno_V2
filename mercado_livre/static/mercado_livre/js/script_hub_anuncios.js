document.addEventListener('click', function (evento) {
    var icone = evento.target.closest('.icone-copiar');
    if (!icone) return;

    evento.preventDefault();
    evento.stopPropagation();

    var valor = icone.getAttribute('data-copiar');
    if (!valor) return;

    navigator.clipboard.writeText(valor).then(function () {
        icone.classList.remove('fa-copy');
        icone.classList.add('fa-check', 'copiado');

        setTimeout(function () {
            icone.classList.remove('fa-check', 'copiado');
            icone.classList.add('fa-copy');
        }, 1200);
    });
});

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