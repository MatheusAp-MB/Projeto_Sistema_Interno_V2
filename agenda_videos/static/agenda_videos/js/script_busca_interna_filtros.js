// agenda_videos/static/agenda_videos/js/script_busca_interna_filtros.js

// Função Objetivo: Filtra a lista de opções (Marca, etc.) conforme o usuário
// digita — mesmo padrão já usado em Produtos (script_produtos.js). Compartilhado
// entre a Agenda principal e o Histórico geral (26/07) — nenhuma lógica
// específica de 1 tela só, por isso vive num arquivo próprio, não dentro de
// script_agenda_videos.js (que é só o toggle de A Fazer Hoje/Estágio).
document.addEventListener('input', function (evento) {
    var campo = evento.target.closest('.filtro-busca-interna');
    if (!campo) return;

    var termo = campo.value.trim().toLowerCase();
    var lista = campo.closest('.filtro-subgrupo').querySelector('.filtro-opcoes-lista');
    if (!lista) return;

    lista.querySelectorAll('.filtro-opcao').forEach(function (opcao) {
        var texto = opcao.textContent.trim().toLowerCase();
        opcao.style.display = texto.indexOf(termo) !== -1 ? '' : 'none';
    });
});