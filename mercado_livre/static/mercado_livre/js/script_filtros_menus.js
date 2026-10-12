// mercado_livre/static/mercado_livre/js/script_filtros_menus.js
//
// Função Objetivo: O comportamento do painel "Filtros" em MENUS (parcial estrutura_parcial_filtros_menus.html; hoje só da Previsão de Ruptura de estoque). Ele NÃO guarda lista de opções nem estado próprio: tudo é lido dos checkboxes que o servidor
// desenhou (cada um é um campo de verdade do formulário, com o mesmo nome e valor de sempre). O que o script faz:
//   1) abre e fecha o painel ("Editar filtros"; ele sempre começa FECHADO) e cada menu (clique fora ou Esc fecham);
//   2) desenha, a partir dos checkboxes, a etiqueta de cada menu fechado (a primeira escolha com ×, "+N" e "N selecionados") e o resumo de cima (chips "Campo: valor" com ×; os 3 primeiros e "+ N outros");
//   3) marca "alterações pendentes" quando algum checkbox difere do que veio do servidor (o atributo `checked`, que o navegador guarda em `defaultChecked`): o filtro só vale ao ENVIAR o formulário ("Aplicar filtros" ou "Recalcular");
//   4) a busca dentro do menu, "Selecionar visíveis" e "Limpar".
// * [EXPLICAÇÃO] → Os chips e as etiquetas copiam o texto (ou o selo do registro único badges.py) da própria opção: a cor e o ícone não são repetidos aqui. Sem este script o <noscript> do parcial abre tudo como lista simples.

(function () {
    'use strict';

    var raiz = document.querySelector('[data-fm]');
    if (!raiz) { return; }

    var corpo = raiz.querySelector('[data-fm-corpo]');
    var botaoEditar = raiz.querySelector('[data-fm-editar]');
    var textoEditar = raiz.querySelector('[data-fm-editar-texto]');
    var rotuloResumo = raiz.querySelector('[data-fm-rotulo]');
    var areaChips = raiz.querySelector('[data-fm-chips]');
    var status = raiz.querySelector('[data-fm-status]');
    var aplicarResumo = raiz.querySelector('[data-fm-aplicar-resumo]');
    var aplicarRodape = raiz.querySelector('[data-fm-aplicar]');
    var notaRodape = raiz.querySelector('[data-fm-nota]');
    var campos = [].slice.call(raiz.querySelectorAll('[data-fm-campo]'));
    var LIMITE_DE_CHIPS = 3;
    var chipsExpandidos = false;
    var campoAberto = null;

    function criar(tag, classe, texto) {
        var peca = document.createElement(tag);
        if (classe) { peca.className = classe; }
        if (texto !== undefined) { peca.textContent = texto; }
        return peca;
    }

    function icone(classe) {
        var i = criar('i', 'fas ' + classe);
        i.setAttribute('aria-hidden', 'true');
        return i;
    }

    function normalizar(texto) {
        return String(texto).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
    }

    function caixasDe(campo) { return [].slice.call(campo.querySelectorAll('input[type="checkbox"]')); }
    function marcadasDe(campo) { return caixasDe(campo).filter(function (caixa) { return caixa.checked; }); }
    function visivel(caixa) { return !caixa.parentNode.hidden; }
    function terminacao(campo) { return campo.getAttribute('data-genero') === 'f' ? 'a' : 'o'; }
    function corpoAberto() { return raiz.classList.contains('fm--aberto'); }

    // Um texto (ou selo) igual ao da opção, para a etiqueta e o chip: copia o que o servidor desenhou.
    function copiaDoTexto(caixa) {
        var origem = caixa.parentNode.querySelector('.fm-opcao-texto');
        var copia = criar('span', 'fm-texto');
        [].forEach.call(origem.childNodes, function (no) { copia.appendChild(no.cloneNode(true)); });
        return copia;
    }

    function botaoRemover(classe, rotulo, aoClicar) {
        var botao = criar('button', classe);
        botao.type = 'button';
        botao.setAttribute('aria-label', rotulo);
        botao.appendChild(icone('fa-xmark'));
        botao.addEventListener('click', function (evento) { evento.stopPropagation(); aoClicar(); });
        return botao;
    }

    function criarEtiqueta(caixa) {
        var etiqueta = criar('span', 'fm-etiqueta');
        etiqueta.appendChild(copiaDoTexto(caixa));
        etiqueta.appendChild(botaoRemover('fm-x', 'Remover ' + caixa.getAttribute('data-label'), function () { caixa.checked = false; desenharTudo(); }));
        return etiqueta;
    }

    function criarChip(caixa) {
        var campo = caixa.closest('[data-fm-campo]');
        var rotulo = campo.getAttribute('data-rotulo');
        var chip = criar('span', 'fm-chip');
        chip.appendChild(criar('span', 'fm-chip-campo', rotulo + ':'));
        chip.appendChild(copiaDoTexto(caixa));
        chip.appendChild(botaoRemover('fm-x', 'Remover ' + caixa.getAttribute('data-label') + ' de ' + rotulo, function () { caixa.checked = false; desenharTudo(); }));
        return chip;
    }

    function desenharCampo(campo) {
        var caixas = caixasDe(campo);
        var marcadas = caixas.filter(function (caixa) { return caixa.checked; });
        var n = marcadas.length;
        var escolhida = campo.querySelector('[data-fm-escolhida]');
        var resto = campo.querySelector('[data-fm-resto]');
        escolhida.textContent = '';
        resto.textContent = '';
        if (n > 0) {
            escolhida.appendChild(criarEtiqueta(marcadas[0]));
            if (n > 1) { resto.appendChild(criar('span', 'fm-mais', '+' + (n - 1))); }
            resto.appendChild(criar('span', 'fm-contagem', n + ' selecionad' + terminacao(campo) + (n === 1 ? '' : 's')));
        } else {
            resto.appendChild(criar('span', 'fm-vazio', campo.getAttribute('data-vazio')));
        }
        campo.querySelector('[data-fm-contagem]').textContent = n + ' de ' + caixas.length + ' selecionad' + terminacao(campo) + (n === 1 ? '' : 's');
        campo.querySelector('[data-fm-limpar]').disabled = n === 0;
        var visiveis = caixas.filter(visivel);
        campo.querySelector('[data-fm-todas]').disabled = visiveis.length === 0 || visiveis.every(function (caixa) { return caixa.checked; });
    }

    function haMudanca() {
        return [].some.call(raiz.querySelectorAll('input[type="checkbox"]'), function (caixa) { return caixa.checked !== caixa.defaultChecked; });
    }

    function desenharEstado() {
        var pendente = haMudanca();
        raiz.classList.toggle('fm--pendente', pendente);
        rotuloResumo.textContent = pendente ? 'Filtros selecionados:' : 'Filtros aplicados:';
        status.textContent = pendente ? 'Alterações pendentes' : 'Seleções aplicadas';
        aplicarRodape.classList.toggle('fm-aplicar--pendente', pendente);
        aplicarResumo.classList.toggle('fm-aplicar--pendente', pendente);
        aplicarResumo.hidden = !(pendente && !corpoAberto());   // com o painel fechado, o botão aparece junto do resumo: tirar um chip não pode deixar a pessoa sem como aplicar
        notaRodape.textContent = pendente ? 'Existem alterações pendentes. Clique em Aplicar filtros (ou em Recalcular).' : 'Marque as opções e clique em Aplicar filtros (ou em Recalcular).';
        return pendente;
    }

    function desenharResumo(pendente) {
        var marcadas = [];
        campos.forEach(function (campo) { marcadas = marcadas.concat(marcadasDe(campo)); });
        if (marcadas.length <= LIMITE_DE_CHIPS) { chipsExpandidos = false; }
        areaChips.textContent = '';
        if (!marcadas.length) {
            areaChips.appendChild(criar('span', 'fm-resumo-vazio', pendente ? 'Nenhum critério selecionado' : 'Nenhum filtro aplicado'));
        }
        (chipsExpandidos ? marcadas : marcadas.slice(0, LIMITE_DE_CHIPS)).forEach(function (caixa) { areaChips.appendChild(criarChip(caixa)); });
        if (marcadas.length > LIMITE_DE_CHIPS) {
            var mais = criar('button', 'fm-mais-chips', chipsExpandidos ? 'Mostrar menos' : '+ ' + (marcadas.length - LIMITE_DE_CHIPS) + ' outros');
            mais.type = 'button';
            mais.setAttribute('aria-expanded', String(chipsExpandidos));
            mais.addEventListener('click', function () { chipsExpandidos = !chipsExpandidos; desenharTudo(); });
            areaChips.appendChild(mais);
        }
        areaChips.classList.toggle('fm-chips--expandido', chipsExpandidos);
    }

    function desenharTudo() {
        campos.forEach(desenharCampo);
        desenharResumo(desenharEstado());
    }

    function alternarCorpo(abrir) {
        raiz.classList.toggle('fm--aberto', abrir);
        botaoEditar.setAttribute('aria-expanded', String(abrir));
        textoEditar.textContent = abrir ? 'Fechar filtros' : 'Editar filtros';
        if (!abrir) { fecharMenu(); }
        desenharEstado();
    }

    // O menu abre para baixo; se não couber na janela e houver espaço em cima, abre para cima.
    function posicionar(campo) {
        var menu = campo.querySelector('.fm-menu');
        menu.classList.remove('fm-menu--acima');
        var caixa = menu.getBoundingClientRect();
        if (caixa.bottom > window.innerHeight - 16 && campo.getBoundingClientRect().top > caixa.height + 20) { menu.classList.add('fm-menu--acima'); }
    }

    function abrirMenu(campo) {
        if (campoAberto && campoAberto !== campo) { fecharMenu(); }
        campoAberto = campo;
        campo.classList.add('fm-campo--aberto');
        campo.closest('.fm-grupo').classList.add('fm-grupo--aberto');
        campo.querySelector('[data-fm-abrir]').setAttribute('aria-expanded', 'true');
        posicionar(campo);
        var busca = campo.querySelector('[data-fm-busca]');
        if (busca) { busca.focus(); }
    }

    function fecharMenu() {
        if (!campoAberto) { return; }
        var campo = campoAberto;
        campoAberto = null;
        campo.classList.remove('fm-campo--aberto');
        campo.closest('.fm-grupo').classList.remove('fm-grupo--aberto');
        campo.querySelector('[data-fm-abrir]').setAttribute('aria-expanded', 'false');
        var busca = campo.querySelector('[data-fm-busca]');
        if (busca && busca.value !== '') { busca.value = ''; filtrarOpcoes(campo, ''); }   // o menu sempre reabre com todas as opções
    }

    function filtrarOpcoes(campo, termo) {
        var procurado = normalizar(termo.trim());
        var achou = 0;
        caixasDe(campo).forEach(function (caixa) {
            var combina = normalizar(caixa.getAttribute('data-label')).indexOf(procurado) !== -1;
            caixa.parentNode.hidden = !combina;
            if (combina) { achou += 1; }
        });
        campo.querySelector('[data-fm-sem-resultado]').hidden = achou !== 0;
        desenharCampo(campo);
    }

    document.addEventListener('click', function (evento) {
        var alvo = evento.target;
        if (!alvo.closest) { return; }
        if (campoAberto && !alvo.closest('.fm-campo--aberto')) { fecharMenu(); }   // clique fora do menu aberto
        if (!alvo.closest('[data-fm]')) { return; }

        if (alvo.closest('[data-fm-editar]')) { alternarCorpo(!corpoAberto()); return; }
        var campo = alvo.closest('[data-fm-campo]');
        if (!campo) { return; }
        if (alvo.closest('[data-fm-todas]')) {
            caixasDe(campo).filter(visivel).forEach(function (caixa) { caixa.checked = true; });
            desenharTudo();
        } else if (alvo.closest('[data-fm-limpar]')) {
            caixasDe(campo).forEach(function (caixa) { caixa.checked = false; });
            desenharTudo();
        } else if (alvo.closest('.fm-controle') && !alvo.closest('.fm-x')) {
            if (campoAberto === campo) { fecharMenu(); } else { abrirMenu(campo); }
        }
    });

    raiz.addEventListener('change', function (evento) {
        if (evento.target.matches && evento.target.matches('input[type="checkbox"]')) { desenharTudo(); }
    });

    raiz.addEventListener('input', function (evento) {
        var busca = evento.target.closest ? evento.target.closest('[data-fm-busca]') : null;
        if (busca) { filtrarOpcoes(busca.closest('[data-fm-campo]'), busca.value); }
    });

    raiz.addEventListener('keydown', function (evento) {
        var alvo = evento.target;
        // Enter dentro do menu não envia o formulário: na busca não faz nada, e numa opção marca/desmarca (como o espaço).
        if (evento.key === 'Enter' && alvo.matches) {
            if (alvo.matches('[data-fm-busca]')) { evento.preventDefault(); }
            if (alvo.matches('.fm-opcao input')) { evento.preventDefault(); alvo.click(); }
        }
        if (evento.key === 'Escape' && campoAberto) {
            var botao = campoAberto.querySelector('[data-fm-abrir]');
            fecharMenu();
            botao.focus();
            evento.stopPropagation();
        }
    });

    window.addEventListener('resize', function () { if (campoAberto) { posicionar(campoAberto); } });
    window.addEventListener('pageshow', desenharTudo);   // voltar pelo navegador restaura os checkboxes: o desenho acompanha

    desenharTudo();
})();
