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

// ================================================
// BUSCA INTERNA DOS FILTROS (Marca, Categoria) — mesmo
// comportamento já usado em script_produtos.js, auto-contido
// aqui pra não depender de outro app carregar o script dele.
// ================================================

document.addEventListener('input', function (evento) {
    var campo = evento.target.closest('.filtro-busca-interna');
    if (!campo) return;

    var termo = campo.value.trim().toLowerCase();
    var lista = campo.closest('.filtro-subgrupo').querySelector('.filtro-opcoes-lista');

    lista.querySelectorAll('.filtro-opcao').forEach(function (opcao) {
        var texto = opcao.textContent.trim().toLowerCase();
        opcao.style.display = texto.indexOf(termo) !== -1 ? '' : 'none';
    });
});