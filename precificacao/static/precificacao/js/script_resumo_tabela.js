/*
* [RESUMO] → Cabeçalho fixo em 2 níveis (grupo + subcoluna) — a
* segunda linha precisa "grudar" logo abaixo da primeira durante a
* rolagem, mas a altura real da primeira linha pode variar (texto
* quebrando, fonte diferente por navegador). Em vez de chutar um
* valor fixo em CSS, mede a altura real e ajusta.
*/

function ajustarCabecalhoResumo() {
    var linhaGrupos = document.querySelector('.resumo-linha-grupos');
    var linhaSub = document.querySelector('.resumo-linha-subcolunas');
    if (!linhaGrupos || !linhaSub) return;

    var altura = linhaGrupos.getBoundingClientRect().height;
    linhaSub.querySelectorAll('th').forEach(function (th) {
        th.style.top = altura + 'px';
    });
}

document.addEventListener('DOMContentLoaded', ajustarCabecalhoResumo);
window.addEventListener('resize', ajustarCabecalhoResumo);