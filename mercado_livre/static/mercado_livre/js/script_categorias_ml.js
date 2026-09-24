// mercado_livre/static/mercado_livre/js/script_categorias_ml.js
//
// * [RESUMO] → Script da Árvore de Categorias (versão "níveis
// empilhados"). Bem mais simples que a versão anterior: como agora
// cada seleção recalcula e re-renderiza a trilha INTEIRA no servidor
// (view view_categorias_selecionar), não existe mais estado de
// "aberto/fechado" controlado no JS — o HTML sempre reflete
// exatamente a seleção atual. A única coisa que sobra pro JS é
// limpar a caixa de busca e fechar o dropdown de resultados depois
// de escolher um item nela (o próprio HTMX já cuida de trocar
// #categorias-trilha-niveis e, via swap out-of-band, #categorias-
// breadcrumb e #categorias-detalhes).

document.body.addEventListener('click', function (evento) {
    var itemBusca = evento.target.closest('.item-resultado-busca');
    if (!itemBusca) return;

    var campoBusca = document.getElementById('categorias-busca');
    var resultados = document.getElementById('categorias-resultados-busca');
    if (campoBusca) campoBusca.value = '';
    if (resultados) resultados.innerHTML = '';
});