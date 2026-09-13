// impostos/static/impostos/js/script_tabela_pis_cofins_por_ncm_cst.js
//
// * [RESUMO] → Script da tela de PIS/COFINS por NCM + CST.
//              Destaca a linha correspondente na tabela depois de uma
//              consulta bem-sucedida — mesmo padrão do destacar_celula()
//              da tela de ICMS por NCM, simplificado porque aqui a linha
//              inteira é o alvo (não há coluna fixa lateral pra descontar).

function limpar_destaque_pis_cofins() {
    document.querySelectorAll('.tabela-pc tr.destaque').forEach(function(tr) {
        tr.classList.remove('destaque');
    });
}

// Função Objetivo: Calcula a altura disponível até o fim da tela e limita
// o .grade-container a isso — mesma técnica de ajustar_altura_grade() da
// tela de ICMS por NCM: a tabela vira uma caixa de tamanho fixo, com
// rolagem interna própria, em vez de esticar a página inteira.
function ajustar_altura_grade() {
    var container = document.querySelector('.grade-container');
    if (!container) return;
    var distanciaDoTopo = container.getBoundingClientRect().top;
    var margemInferior = 24;
    container.style.maxHeight = (window.innerHeight - distanciaDoTopo - margemInferior) + 'px';
}

ajustar_altura_grade();
window.addEventListener('resize', ajustar_altura_grade);

// A troca do HTMX (resultado da consulta, ou o <select> de CST) muda a
// altura do que vem antes da tabela — sem isso, o max-height calculado
// no carregamento da página fica desatualizado e sobra scroll externo.
document.body.addEventListener('htmx:afterSwap', ajustar_altura_grade);

function destacar_grupo(ncm, cst) {
    limpar_destaque_pis_cofins();

    var linha = document.querySelector(
        `.tabela-pc tr[data-ncm="${ncm}"][data-cst="${cst}"]`
    );
    if (!linha) return;

    linha.classList.add('destaque');
    linha.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// Função Objetivo: Dropdown customizado do campo NCM — filtra a lista de
// NCMs disponíveis conforme o usuário digita, mostra as opções abaixo do
// campo (com rolagem própria) e preenche o input ao selecionar. Continua
// permitindo digitar um NCM que não está na lista (o input nunca é
// bloqueado) — o dropdown só ajuda a encontrar mais rápido. A lista
// inteira já vem embutida na página (json_script), sem ida ao servidor
// a cada letra digitada.
(function () {
    var elementoDados = document.getElementById('dados-ncms-disponiveis');
    var input = document.getElementById('input-ncm');
    var opcoesContainer = document.getElementById('combo-ncm-opcoes');
    if (!elementoDados || !input || !opcoesContainer) return;

    var TODOS_OS_NCMS = JSON.parse(elementoDados.textContent);
    var MAXIMO_OPCOES_EXIBIDAS = 50;
    var indiceAtivo = -1;

    function filtrarNcms(termo) {
        if (!termo) return [];
        return TODOS_OS_NCMS
            .filter(function (ncm) { return ncm.indexOf(termo) !== -1; })
            .slice(0, MAXIMO_OPCOES_EXIBIDAS);
    }

    function fecharOpcoes() {
        opcoesContainer.innerHTML = '';
        opcoesContainer.classList.remove('aberto');
        indiceAtivo = -1;
    }

    function selecionarNcm(ncm) {
        input.value = ncm;
        fecharOpcoes();
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
    }

    function renderizarOpcoes(ncms) {
        opcoesContainer.innerHTML = '';
        indiceAtivo = -1;

        if (ncms.length === 0) {
            fecharOpcoes();
            return;
        }

        ncms.forEach(function (ncm) {
            var item = document.createElement('div');
            item.className = 'combo-ncm-item';
            item.textContent = ncm;
            item.addEventListener('mousedown', function (evento) {
                evento.preventDefault(); // não deixa o input perder o foco antes do clique
                selecionarNcm(ncm);
            });
            opcoesContainer.appendChild(item);
        });

        opcoesContainer.classList.add('aberto');
    }

    function atualizarItemAtivo() {
        var itens = opcoesContainer.querySelectorAll('.combo-ncm-item');
        itens.forEach(function (item, indice) {
            item.classList.toggle('ativo', indice === indiceAtivo);
        });
        if (itens[indiceAtivo]) {
            itens[indiceAtivo].scrollIntoView({ block: 'nearest' });
        }
    }

    input.addEventListener('input', function () {
        renderizarOpcoes(filtrarNcms(input.value.trim()));
    });

    input.addEventListener('keydown', function (evento) {
        var itens = opcoesContainer.querySelectorAll('.combo-ncm-item');
        if (!itens.length) return;

        if (evento.key === 'ArrowDown') {
            evento.preventDefault();
            indiceAtivo = (indiceAtivo + 1) % itens.length;
            atualizarItemAtivo();
        } else if (evento.key === 'ArrowUp') {
            evento.preventDefault();
            indiceAtivo = (indiceAtivo - 1 + itens.length) % itens.length;
            atualizarItemAtivo();
        } else if (evento.key === 'Enter' && indiceAtivo >= 0) {
            evento.preventDefault();
            selecionarNcm(itens[indiceAtivo].textContent);
        } else if (evento.key === 'Escape') {
            fecharOpcoes();
        }
    });

    input.addEventListener('blur', function () {
        // pequeno atraso pra dar tempo do mousedown do item rodar antes de fechar
        setTimeout(fecharOpcoes, 150);
    });
})();