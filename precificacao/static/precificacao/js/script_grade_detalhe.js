/*
* [RESUMO] → Controla o painel "como chegamos nesse preço" — 1 slot
* por (produto, tipo), carregado sob demanda via HTMX. Comportamento:
* clicar no mesmo card fecha (toggle); clicar em outro card do MESMO
* tipo substitui (o slot é único por tipo, e o destaque visual troca
* junto); Clássico e Premium têm slots independentes, podem ficar
* abertos ao mesmo tempo. HTMX sozinho não tem esse "toggle" nem o
* controle de destaque, por isso essa função pequena.
*/

// ================================================
// COPIAR TEXTO (título, EAN) — mesmo padrão já usado no
// Hub de Anúncios, auto-contido aqui.
// ================================================

function copiar_texto(texto) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(texto);
    }
    return new Promise(function (resolve, reject) {
        var campo = document.createElement('textarea');
        campo.value = texto;
        campo.style.position = 'fixed';
        campo.style.opacity = '0';
        document.body.appendChild(campo);
        campo.focus();
        campo.select();
        try {
            document.execCommand('copy');
            resolve();
        } catch (erro) {
            reject(erro);
        } finally {
            document.body.removeChild(campo);
        }
    });
}

document.addEventListener('click', function (evento) {
    var icone = evento.target.closest('.icone-copiar');
    if (!icone) return;

    // * [EXPLICAÇÃO] → O ícone fica dentro de um <summary> (o
    //                  cabeçalho do card é clicável pra colapsar) —
    //                  sem isso, clicar em "copiar" também
    //                  abriria/fecharia o card sem querer.
    evento.preventDefault();
    evento.stopPropagation();

    var valor = icone.getAttribute('data-copiar');
    if (!valor) return;

    copiar_texto(valor).then(function () {
        icone.classList.remove('fa-copy');
        icone.classList.add('fa-check', 'copiado');
        setTimeout(function () {
            icone.classList.remove('fa-check', 'copiado');
            icone.classList.add('fa-copy');
        }, 1200);
    });
});

function limparDestaque(grid) {
    if (!grid) return;
    grid.querySelectorAll('.grade-margem-card--ativa').forEach(el => el.classList.remove('grade-margem-card--ativa'));
}

function alternarDetalheMargem(elCard, produtoId, tipo, margemChave, variacaoId) {
    // * [EXPLICAÇÃO] → variacaoId vazio = fallback do produto (usa
    //                  '0' como sufixo do slot, nunca é um PK real).
    //                  Com variacaoId real, é 1 MLB específico — cada
    //                  um tem seu PRÓPRIO slot, independente dos outros.
    const sufixoSlot = variacaoId || '0';
    const slot = document.getElementById(`detalhe-${produtoId}-${tipo}-${sufixoSlot}`);
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

    let url = `/precificacao/grade-mercado-livre/detalhe/${produtoId}/${tipo}/${margemChave}/`;
    if (variacaoId) {
        url += `?variacao=${variacaoId}`;
    }
    htmx.ajax('GET', url, { target: slot, swap: 'innerHTML' }).then(() => {
        slot.dataset.margemAtual = margemChave;
    });
}

function fecharDetalheMargem(produtoId, tipo, variacaoId) {
    const sufixoSlot = variacaoId || '0';
    const slot = document.getElementById(`detalhe-${produtoId}-${tipo}-${sufixoSlot}`);
    if (!slot) return;
    slot.innerHTML = '';
    delete slot.dataset.margemAtual;

    // * [EXPLICAÇÃO] → O slot é sempre o irmão logo depois do bloco
    //                  (.grade-tipo-bloco ou .grade-card-mlb) que
    //                  contém o grid de cards — usa isso pra achar e
    //                  limpar o destaque quando fecha pelo botão
    //                  "Fechar" do painel (que não tem referência
    //                  direta ao card).
    const bloco = slot.previousElementSibling;
    if (bloco) {
        limparDestaque(bloco.querySelector('.grade-margens-grid'));
    }
}

// ================================================
// ESPELHO DA NF ("Ver NF") — janela com a nota fiscal inteira
// ================================================

/*
* [RESUMO] → O botão "Ver NF" do bloco "Nota fiscal usada como base" (modal de auditoria da
* grade) abre esta janela com o espelho da nota: todos os itens, com impostos, e o produto
* auditado destacado. O conteúdo vem pronto do servidor (impostos_espelho_nota_entrada) via
* HTMX — aqui só abre/fecha a janela e expande os campos de cada item. A janela é criada na
* 1ª vez que alguém clica e reaproveitada nas seguintes, 1 só pra tela inteira (nunca 1 por
* card, o modal da grade pode ter vários painéis abertos ao mesmo tempo).
*/

var ID_SOBREPOSICAO_ESPELHO_NF = 'nf-espelho-sobreposicao';

function obterSobreposicaoEspelhoNF() {
    let sobreposicao = document.getElementById(ID_SOBREPOSICAO_ESPELHO_NF);
    if (sobreposicao) return sobreposicao;

    sobreposicao = document.createElement('div');
    sobreposicao.id = ID_SOBREPOSICAO_ESPELHO_NF;
    sobreposicao.className = 'nf-espelho-sobreposicao';
    sobreposicao.setAttribute('role', 'dialog');
    sobreposicao.setAttribute('aria-modal', 'true');
    sobreposicao.setAttribute('aria-label', 'Espelho da nota fiscal');
    sobreposicao.innerHTML =
        '<div class="nf-espelho-caixa">' +
            '<div class="nf-espelho-barra">' +
                '<span class="nf-espelho-barra-titulo">🧾 Espelho da nota fiscal</span>' +
                '<button type="button" class="nf-espelho-fechar" onclick="fecharEspelhoNF()">✕ Fechar</button>' +
            '</div>' +
            '<div class="nf-espelho-conteudo"></div>' +
        '</div>';

    // * [EXPLICAÇÃO] → Clique no fundo escuro (fora da caixa branca) também fecha.
    sobreposicao.addEventListener('click', function (evento) {
        if (evento.target === sobreposicao) fecharEspelhoNF();
    });

    document.body.appendChild(sobreposicao);
    return sobreposicao;
}

function abrirEspelhoNF(botao) {
    const url = botao.getAttribute('data-url');
    if (!url) return;

    const sobreposicao = obterSobreposicaoEspelhoNF();
    const conteudo = sobreposicao.querySelector('.nf-espelho-conteudo');
    conteudo.innerHTML = '<div class="nf-espelho-carregando">Carregando a nota fiscal…</div>';
    sobreposicao.classList.add('nf-espelho-sobreposicao--aberta');
    document.body.classList.add('nf-espelho-aberto');

    htmx.ajax('GET', url, { target: conteudo, swap: 'innerHTML' }).then(function () {
        // * [EXPLICAÇÃO] → Nota grande (dezenas de itens): já rola até o item do produto auditado.
        const destaque = conteudo.querySelector('.nf-espelho-linha--destaque');
        if (destaque) destaque.scrollIntoView({ block: 'center' });
    }).catch(function () {
        conteudo.innerHTML = '<div class="nf-espelho-carregando">Não foi possível carregar a nota fiscal. Feche e tente de novo.</div>';
    });
}

function fecharEspelhoNF() {
    const sobreposicao = document.getElementById(ID_SOBREPOSICAO_ESPELHO_NF);
    if (!sobreposicao) return;
    sobreposicao.classList.remove('nf-espelho-sobreposicao--aberta');
    sobreposicao.querySelector('.nf-espelho-conteudo').innerHTML = '';
    document.body.classList.remove('nf-espelho-aberto');
}

document.addEventListener('keydown', function (evento) {
    if (evento.key !== 'Escape') return;
    const sobreposicao = document.getElementById(ID_SOBREPOSICAO_ESPELHO_NF);
    if (sobreposicao && sobreposicao.classList.contains('nf-espelho-sobreposicao--aberta')) {
        fecharEspelhoNF();
    }
});

// * [EXPLICAÇÃO] → O "+" de cada item mostra/esconde a linha logo abaixo, que traz TODOS os
//                  campos do item como a API devolveu (XML e Cadastro). Sem isso a tabela
//                  teria 50+ colunas por item.
function alternarCamposItemNF(botao) {
    const linha = botao.closest('tr');
    const detalhe = linha ? linha.nextElementSibling : null;
    if (!detalhe || !detalhe.classList.contains('nf-espelho-linha-detalhe')) return;

    const vaiAbrir = detalhe.hidden;
    detalhe.hidden = !vaiAbrir;
    botao.setAttribute('aria-expanded', vaiAbrir ? 'true' : 'false');
    botao.textContent = vaiAbrir ? '−' : '+';
}
