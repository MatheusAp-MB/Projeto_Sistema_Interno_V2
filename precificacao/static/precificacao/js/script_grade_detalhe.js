/*
* [RESUMO] → Controla o painel "como chegamos nesse preço" — 1 slot
* por (produto, tipo), carregado sob demanda via HTMX. Comportamento:
* clicar no mesmo card fecha (toggle); clicar em outro card do MESMO
* tipo substitui (o slot é único por tipo, e o destaque visual troca
* junto); Clássico e Premium têm slots independentes, podem ficar
* abertos ao mesmo tempo. HTMX sozinho não tem esse "toggle" nem o
* controle de destaque, por isso essa função pequena.
*/

function limparDestaque(grid) {
    if (!grid) return;
    grid.querySelectorAll('.grade-margem-card--ativa').forEach(el => el.classList.remove('grade-margem-card--ativa'));
}

function alternarDetalheMargem(elCard, produtoId, tipo, margemChave) {
    const slot = document.getElementById(`detalhe-${produtoId}-${tipo}`);
    if (!slot) return;

    const grid = elCard.closest('.grade-margens-grid');

    if (slot.dataset.margemAtual === margemChave) {
        // * já está mostrando ESSA margem — fecha e tira o destaque
        slot.innerHTML = '';
        delete slot.dataset.margemAtual;
        limparDestaque(grid);
        return;
    }

    limparDestaque(grid);
    elCard.classList.add('grade-margem-card--ativa');

    const url = `/precificacao/grade-mercado-livre/detalhe/${produtoId}/${tipo}/${margemChave}/`;
    htmx.ajax('GET', url, { target: slot, swap: 'innerHTML' }).then(() => {
        slot.dataset.margemAtual = margemChave;
    });
}

function fecharDetalheMargem(produtoId, tipo) {
    const slot = document.getElementById(`detalhe-${produtoId}-${tipo}`);
    if (!slot) return;
    slot.innerHTML = '';
    delete slot.dataset.margemAtual;

    // * [EXPLICAÇÃO] → O slot é sempre o irmão logo depois do bloco
    //                  (.grade-tipo-bloco) que contém o grid de
    //                  cards — usa isso pra achar e limpar o destaque
    //                  quando fecha pelo botão "Fechar" do painel
    //                  (que não tem referência direta ao card).
    const bloco = slot.previousElementSibling;
    if (bloco) {
        limparDestaque(bloco.querySelector('.grade-margens-grid'));
    }
}