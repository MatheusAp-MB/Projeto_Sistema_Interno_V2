// impostos/static/impostos/js/script_auditoria_fiscal.js
//
// Função Objetivo: Troca de aba (ICMS / PIS-COFINS) e busca por
// NCM/CST/EAN na tela de Auditoria Fiscal (Camada D, 13/09/2026).
// Vanilla JS, sem dependência nenhuma — mesmo padrão de
// script_tabela_icms_por_ncm.js.

document.addEventListener('DOMContentLoaded', function () {
    const abas = document.querySelectorAll('.auditoria-aba');
    const paineis = {
        icms: document.getElementById('painel-auditoria-icms'),
        pis_cofins: document.getElementById('painel-auditoria-pis_cofins'),
    };

    abas.forEach(function (aba) {
        aba.addEventListener('click', function () {
            abas.forEach(function (outra) {
                outra.classList.remove('auditoria-aba-ativa');
                outra.setAttribute('aria-selected', 'false');
            });
            aba.classList.add('auditoria-aba-ativa');
            aba.setAttribute('aria-selected', 'true');

            Object.keys(paineis).forEach(function (chave) {
                if (!paineis[chave]) return;
                paineis[chave].classList.toggle('auditoria-painel-oculto', chave !== aba.dataset.aba);
            });
        });
    });

    const campoBusca = document.getElementById('auditoria-busca');
    if (campoBusca) {
        campoBusca.addEventListener('input', function () {
            const termo = campoBusca.value.trim().toLowerCase();
            document.querySelectorAll('.auditoria-item').forEach(function (item) {
                const alvo = item.dataset.busca || '';
                const bate = termo === '' || alvo.indexOf(termo) !== -1;
                item.classList.toggle('auditoria-item-oculto-busca', !bate);
                // Item que bate na busca abre sozinho — não faz sentido
                // o usuário digitar um EAN e o resultado ficar fechado.
                if (bate && termo !== '') {
                    item.setAttribute('open', '');
                }
            });
        });
    }
});