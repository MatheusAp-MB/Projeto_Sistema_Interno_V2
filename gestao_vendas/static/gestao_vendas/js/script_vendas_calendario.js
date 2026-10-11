/*
 * [RESUMO] → O calendário da tela "Vendas — Histórico de vendas" como COMPONENTE: ele tem rolagem própria (a página não cresce com ele). A rolagem em
 *            si é só CSS (.vnd-cal-rolagem); sem este arquivo o calendário continua aparecendo e rolando. Aqui ficam só os extras.
 * * [EXPLICAÇÃO] → 1) Sombras "tem mais": avisam, no topo e embaixo da visão Meses, que há mais meses para rolar.
 *                  2) Na visão Meses a rolagem começa no FIM (os meses mais recentes), como as Semanas, que já mostram a mais recente em cima.
 */
(function () {
    'use strict';

    const calendario = document.querySelector('[data-vnd-calendario]');
    const corpo = calendario ? calendario.querySelector('.vnd-cal-corpo') : null;
    const rolagem = calendario ? calendario.querySelector('.vnd-cal-rolagem') : null;
    if (!calendario || !corpo || !rolagem) {
        return;
    }

    // Função Objetivo: Liga ou desliga as sombras "tem mais" conforme a posição da rolagem.
    function atualizarSombras() {
        const resta = rolagem.scrollHeight - rolagem.clientHeight - rolagem.scrollTop;
        corpo.dataset.podeSubir = rolagem.scrollTop > 2 ? '1' : '';
        corpo.dataset.podeDescer = resta > 2 ? '1' : '';
    }

    rolagem.addEventListener('scroll', atualizarSombras, { passive: true });
    window.addEventListener('resize', atualizarSombras);

    if (calendario.dataset.vndVisao === 'meses') {
        rolagem.scrollTop = rolagem.scrollHeight;
    }
    atualizarSombras();
})();
