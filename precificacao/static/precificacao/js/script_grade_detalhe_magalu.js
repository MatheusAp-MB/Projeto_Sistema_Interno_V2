// * [RESUMO] → Controla o painel "como chegamos nesse preço" da Grade
//              Magalu — mesmo padrão do script_grade_detalhe.js (ML),
//              simplificado (sem tipo, sem variação — Magalu não tem
//              MLB nem Clássico/Premium ainda). Arquivo PRÓPRIO, não
//              compartilhado com o ML — a versão do ML tem a URL do
//              ML cravada dentro dela, não dava pra reaproveitar sem
//              acoplar os 2 marketplaces no mesmo arquivo.

function limparDestaqueMagalu(grid) {
    if (!grid) return;
    grid.querySelectorAll('.grade-margem-card--ativa').forEach(el => el.classList.remove('grade-margem-card--ativa'));
}

function alternarDetalheMargemMagalu(elCard, produtoId, margemChave) {
    const slot = document.getElementById(`detalhe-magalu-${produtoId}`);
    if (!slot) return;

    const grid = elCard.closest('.grade-margens-grid');

    if (slot.dataset.margemAtual === margemChave) {
        slot.innerHTML = '';
        delete slot.dataset.margemAtual;
        limparDestaqueMagalu(grid);
        return;
    }

    limparDestaqueMagalu(grid);
    elCard.classList.add('grade-margem-card--ativa');

    const url = `/precificacao/grade-magalu/detalhe/${produtoId}/${margemChave}/`;
    htmx.ajax('GET', url, { target: slot, swap: 'innerHTML' }).then(() => {
        slot.dataset.margemAtual = margemChave;
    });
}

function fecharDetalheMargemMagalu(produtoId) {
    const slot = document.getElementById(`detalhe-magalu-${produtoId}`);
    if (!slot) return;
    slot.innerHTML = '';
    delete slot.dataset.margemAtual;

    const bloco = slot.previousElementSibling;
    if (bloco) {
        limparDestaqueMagalu(bloco.querySelector('.grade-margens-grid'));
    }
}