function limparDestaqueTiktok(grid) {
    if (!grid) return;
    grid.querySelectorAll('.grade-margem-card--ativa').forEach(el => el.classList.remove('grade-margem-card--ativa'));
}

function alternarDetalheMargemTiktok(elCard, produtoId, tipo, margemChave) {
    const slot = document.getElementById(`detalhe-tiktok-${produtoId}`);
    if (!slot) return;

    const chaveAtual = `${tipo}:${margemChave}`;
    const grid = elCard.closest('.grade-margens-grid');

    if (slot.dataset.chaveAtual === chaveAtual) {
        slot.innerHTML = '';
        delete slot.dataset.chaveAtual;
        limparDestaqueTiktok(document.getElementById(`detalhe-tiktok-${produtoId}`).previousElementSibling);
        return;
    }

    const card = elCard.closest('.grade-card');
    card.querySelectorAll('.grade-margem-card--ativa').forEach(el => el.classList.remove('grade-margem-card--ativa'));
    elCard.classList.add('grade-margem-card--ativa');

    const url = `/precificacao/grade-tiktok/detalhe/${produtoId}/${tipo}/${margemChave}/`;
    htmx.ajax('GET', url, { target: slot, swap: 'innerHTML' }).then(() => {
        slot.dataset.chaveAtual = chaveAtual;
    });
}

function fecharDetalheMargemTiktok(produtoId) {
    const slot = document.getElementById(`detalhe-tiktok-${produtoId}`);
    if (!slot) return;
    slot.innerHTML = '';
    delete slot.dataset.chaveAtual;

    const card = slot.closest('.grade-card');
    if (card) {
        card.querySelectorAll('.grade-margem-card--ativa').forEach(el => el.classList.remove('grade-margem-card--ativa'));
    }
}