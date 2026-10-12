// Função Objetivo: A busca que fica DENTRO de cada cartão do painel "Filtros" (Marca, Situação do anúncio...): digitar esconde as opções que não combinam. Compartilhado pelo Hub de Anúncios, pelo Hub de Fotos e pela
// Previsão de Ruptura de estoque (o painel é mercado_livre/parciais/estrutura_parcial_filtros_painel.html). Vivia em script_hub_anuncios.js.

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