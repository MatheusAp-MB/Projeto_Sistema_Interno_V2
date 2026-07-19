function limparDestaqueShopee(grid) {
    if (!grid) return;
    grid.querySelectorAll('.grade-margem-card--ativa').forEach(el => el.classList.remove('grade-margem-card--ativa'));
}

function alternarDetalheMargemShopee(elCard, produtoId, margemChave) {
    const slot = document.getElementById(`detalhe-shopee-${produtoId}`);
    if (!slot) return;

    const grid = elCard.closest('.grade-margens-grid');

    if (slot.dataset.margemAtual === margemChave) {
        slot.innerHTML = '';
        delete slot.dataset.margemAtual;
        limparDestaqueShopee(grid);
        return;
    }

    limparDestaqueShopee(grid);
    elCard.classList.add('grade-margem-card--ativa');

    const url = `/precificacao/grade-shopee/detalhe/${produtoId}/${margemChave}/`;
    htmx.ajax('GET', url, { target: slot, swap: 'innerHTML' }).then(() => {
        slot.dataset.margemAtual = margemChave;
    });
}

function fecharDetalheMargemShopee(produtoId) {
    const slot = document.getElementById(`detalhe-shopee-${produtoId}`);
    if (!slot) return;
    slot.innerHTML = '';
    delete slot.dataset.margemAtual;

    const bloco = slot.previousElementSibling;
    if (bloco) {
        limparDestaqueShopee(bloco.querySelector('.grade-margens-grid'));
    }
}