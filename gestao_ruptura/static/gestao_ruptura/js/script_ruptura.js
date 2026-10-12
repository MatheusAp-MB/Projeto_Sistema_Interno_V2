/* gestao_ruptura/static/gestao_ruptura/js/script_ruptura.js
 *
 * [RESUMO] → Pequenos atalhos da tela "Previsão de Ruptura de estoque". Nenhum deles é obrigatório: sem JavaScript a tela continua funcionando (é só preencher e clicar em
 *            "Calcular" / clicar nos links). Só o item 5 (botão "Consultar no Mercado Livre", só por clique) chama o Mercado Livre; tudo o mais é GET comum que só lê o banco.
 *
 *            1) Os atalhos de dias (7, 15, 30...; valem para o mundo da tela: o campo é sempre #rup-dias, mesmo que no endereço seja "dias_f"), o checkbox "Contar o que está a caminho" (só existe no Full), o seletor "Urgência segundo" (Mercado Livre /
 *               Sistema) e o seletor "Quantidade segundo" (Mercado Livre / Sistema / Minha quantidade) refazem o cálculo na hora. Os campos de número e a busca só valem ao apertar Enter ou "Recalcular": enquanto houver algo digitado e ainda não aplicado, o botão ganha uma bolinha laranja. Digitar uma quantidade marca "Minha quantidade" sozinho; escolher outra
 *               referência de quantidade limpa o campo.
 *            2) Os seletores "Ordenar por" e "Por página" da lista (marcados com data-rup-ir) levam para o endereço que está no value da opção escolhida.
 *            3) Foto que não carrega (anúncio sem foto, link vencido) vira o quadradinho "sem foto", para a linha não ficar com o ícone de imagem quebrada.
 *            4) O gráfico da curva de estoque (detalhe): ligar/desligar a curva de cada ritmo, passar o mouse (estoque projetado de cada ritmo naquele dia), zoom (botões ou scroll do mouse), mover e arrastar.
 *               Tudo é conta local sobre os dados que o servidor deixou na página; sem este script o gráfico continua inteiro, só não responde ao mouse.
 *            5) Os botões "Consultar no Mercado Livre" da tabela de estoque (um Código ML, ou todos em fila): chamam o servidor só por clique e recarregam a tela no fim.
 *            6) Balão de dica no padrão da tela (branco, com setinha) no lugar do balão preto do navegador: o texto continua escrito no atributo title do HTML; ao carregar, este script o troca por
 *               data-rup-dica e mostra o balão ao passar o mouse (ou ao chegar com o Tab). Sem JavaScript, volta o balão nativo do navegador.
 */
(function () {
    'use strict';

    // [1] Atalhos do formulário (existem na lista e no detalhe).
    var form = document.getElementById('rup-form');
    var campoDias = document.getElementById('rup-dias');

    function enviar() {
        if (!form) { return; }
        if (typeof form.requestSubmit === 'function') { form.requestSubmit(); } else { form.submit(); }
    }

    if (form && campoDias) {
        form.querySelectorAll('[data-dias]').forEach(function (botao) {
            botao.addEventListener('click', function () {
                campoDias.value = botao.getAttribute('data-dias');
                enviar();
            });
        });
    }

    if (form) {
        // Campo de número e busca NÃO valem na hora (só ao apertar Enter ou "Recalcular"): enquanto houver algo digitado e ainda não aplicado, o formulário ganha a marca "pendente" e o botão "Recalcular" ganha uma bolinha laranja (CSS).
        form.querySelectorAll('input[type="number"], input[type="search"]').forEach(function (campo) {
            campo.addEventListener('input', function () { form.classList.add('rup-controles--pendente'); });
        });
        // O checkbox "Contar o que está a caminho" e o seletor "Urgência segundo" também refazem o cálculo na hora.
        form.querySelectorAll('input[name="caminho"], input[name="ref_urg"]').forEach(function (caixa) {
            caixa.addEventListener('change', enviar);
        });
        // "Quantidade segundo" (a opção "Minha quantidade" só existe no detalhe): trocar a referência refaz o cálculo; "Minha quantidade" sem número ainda só leva o cursor ao campo (não há o que calcular); digitar marca "Minha quantidade".
        var campoQtd = document.getElementById('rup-qtd');
        var opcoesQtd = form.querySelectorAll('input[name="ref_qtd"]');
        function marcarReferencia(valor) {
            opcoesQtd.forEach(function (opcao) {
                opcao.checked = opcao.value === valor;
                var chip = opcao.closest ? opcao.closest('.lista-chip') : null;
                if (chip) { chip.classList.toggle('lista-chip--ativo', opcao.checked); }
            });
        }
        opcoesQtd.forEach(function (opcao) {
            opcao.addEventListener('change', function () {
                if (!campoQtd) { enviar(); return; }
                if (opcao.value === 'manual') {
                    marcarReferencia('manual');
                    if (campoQtd.value === '') { campoQtd.focus(); return; }
                } else {
                    campoQtd.value = '';
                }
                enviar();
            });
        });
        if (campoQtd) {
            campoQtd.addEventListener('input', function () { if (campoQtd.value !== '') { marcarReferencia('manual'); } });
        }
    }

    // [2] Seletores que trocam de página: o value da opção já é o endereço pronto (montado no servidor, mantendo busca, filtro, ritmo, prazo, chegar antes e folga).
    document.querySelectorAll('select[data-rup-ir]').forEach(function (seletor) {
        seletor.addEventListener('change', function () {
            var destino = seletor.value;
            if (destino) { window.location.href = destino; }
        });
    });

    // [3] Foto quebrada → placeholder do mesmo tamanho (o CSS dá o tamanho pela classe, então a linha não muda de altura).
    function trocarPorPlaceholder(img) {
        if (!img || img.getAttribute('data-rup-sem-foto') === '1') { return; }
        var ehLista = img.classList.contains('cartao-anuncio-imagem');
        var ehDetalhe = img.classList.contains('rup-produto-imagem');
        if (!ehLista && !ehDetalhe) { return; }
        var vazio = document.createElement(ehLista ? 'div' : 'span');
        vazio.className = ehLista
            ? 'cartao-anuncio-imagem cartao-anuncio-imagem--vazia'
            : 'rup-produto-imagem rup-produto-imagem--vazia';
        vazio.setAttribute('data-rup-sem-foto', '1');
        if (ehLista) {
            vazio.setAttribute('role', 'img');
            vazio.setAttribute('aria-label', 'Sem foto');
        } else {
            vazio.setAttribute('aria-hidden', 'true');
        }
        vazio.innerHTML = ehLista ? '<i class="fas fa-image" aria-hidden="true"></i>' : '<i class="fas fa-box"></i>';
        if (img.parentNode) { img.parentNode.replaceChild(vazio, img); }
    }

    // O evento "error" de <img> não sobe na árvore; só dá para pegar na fase de captura.
    document.addEventListener('error', function (evento) {
        var alvo = evento.target;
        if (alvo && alvo.tagName === 'IMG') { trocarPorPlaceholder(alvo); }
    }, true);

    // Foto que já falhou antes deste script rodar.
    document.querySelectorAll('img.cartao-anuncio-imagem, img.rup-produto-imagem').forEach(function (img) {
        if (img.complete && img.naturalWidth === 0 && img.getAttribute('src')) { trocarPorPlaceholder(img); }
    });

    // [4] Gráfico da curva de estoque (só no detalhe): ligar/desligar curvas, passar o mouse, zoom (botões ou scroll do mouse sobre o gráfico) e arrastar. TUDO local: o script lê os dados que o servidor
    //     deixou no próprio HTML (estoque, ritmos, data de hoje) e refaz só as contas simples (estoque − ritmo × dias). Não chama o servidor, o Mercado Livre nem o ERP.
    //     CADA DATA É UMA COLUNA (da meia-noite dela até a seguinte): a linha do estoque é contínua e cruza o zero dentro da coluna do dia da ruptura (hoje + parte inteira dos dias de estoque);
    //     o nome da data fica no meio da coluna, o "Enviar até" e a "Ruptura" são faixas da coluna e o mouse destaca o dia inteiro (estoque no COMEÇO do dia; em hoje é o estoque lido).
    //     O ZOOM mexe nos DOIS eixos: o horizontal mostra datas cada vez mais próximas (até dia a dia) e o vertical se ajusta ao trecho visível das curvas (mais números, de 1 em 1 unidade nos
    //     limites). As linhas (SVG) são medidas em DIAS no eixo horizontal; o que é texto em HTML (datas, números, "Enviar até", "Ruptura", pontinhos) é reposicionado em %.
    //     Sem este script o gráfico continua inteiro (só não tem zoom, mouse nem caixinhas).
    function iniciarGrafico() {
        var area = document.querySelector('[data-rup-area]');
        var fonte = document.getElementById('rup-grafico-dados');
        if (!area || !fonte) { return; }
        var dados;
        try { dados = JSON.parse(fonte.textContent); } catch (erro) { return; }
        var svg = area.querySelector('svg');
        var barra = document.querySelector('[data-rup-zoom]');
        var NS = 'http://www.w3.org/2000/svg';
        var HORIZONTE = dados.horizonte;
        var MINIMO = Math.min(dados.zoomMinimo || 4, HORIZONTE);
        var PASSOS = [1, 2, 3, 5, 7, 10, 14, 15, 20, 30, 45, 60, 90, 120, 180, 365];   // de quantos em quantos dias o eixo pode contar
        var PX_POR_DATA = 70;    // espaço mínimo de cada data no eixo horizontal (quanto mais largo o gráfico, mais datas cabem)
        var PX_POR_NUMERO = 28;  // espaço mínimo de cada número no eixo vertical
        var FAIXA_MINIMA = 5;    // o menor trecho (em unidades) que o eixo vertical mostra quando há zoom
        var FOLGA = 1e-6;
        var janela = { a: 0, b: HORIZONTE };   // o trecho visível, em dias a partir de hoje
        var escala = { min: 0, max: dados.yMax };   // o trecho visível, em unidades de estoque
        var visiveis = {};
        dados.series.forEach(function (s) { visiveis[s.id] = true; });
        // A COBERTURA DA REMESSA (linha verde, só havendo quantidade para enviar): antes da chegada ela é igual à curva do ritmo em destaque; no dia da chegada (`chega`) o estoque SOBE para `depois` e volta a
        // cair no mesmo ritmo até zerar em `tZero` (a nova ruptura). Medida em dias, como as outras linhas.
        var sug = dados.sug || null;
        if (sug) { visiveis[sug.id] = true; }

        function arredondar(n) { return Math.round(n * 10000) / 10000; }
        function tamanho() { return janela.b - janela.a; }
        function comZoom() { return tamanho() < HORIZONTE - FOLGA; }
        function porcento(t) { return (t - janela.a) / tamanho() * 100; }
        function dentro(t) { return t >= janela.a - FOLGA && t <= janela.b + FOLGA; }
        function yPct(valor) { return 100 - (valor - escala.min) / (escala.max - escala.min) * 100; }
        function valorEm(s, t) { return Math.max(0, dados.estoque - s.media * t); }
        function valorSug(t) { return Math.max(0, sug.depois - sug.media * (t - sug.chega)); }   // o estoque COM a remessa (vale a partir do dia da chegada)
        function ocultar(elemento, sim) {   // serve para SVG também (o atributo hidden é escondido pelo CSS da tela)
            if (sim) { elemento.setAttribute('hidden', ''); } else { elemento.removeAttribute('hidden'); }
        }
        function numeroBR(n) { var inteiro = Math.round(n); return (inteiro === 0 ? 0 : inteiro).toLocaleString('pt-BR'); }   // (evita o "-0")

        // ---- datas: o mesmo formato do servidor (dd/mm; com o ano só quando não é o ano de hoje) ----
        var hoje = dados.hoje.split('-');
        var anoDeHoje = Number(hoje[0]);
        var diaZero = Date.UTC(anoDeHoje, Number(hoje[1]) - 1, Number(hoje[2]));
        function doisDigitos(n) { return (n < 10 ? '0' : '') + n; }
        var SEMANA = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
        function diaDaSemana(n) { return SEMANA[new Date(diaZero + Math.floor(n + FOLGA) * 86400000).getUTCDay()]; }
        function dataDoDia(n) {
            var dia = new Date(diaZero + Math.floor(n + FOLGA) * 86400000);
            var texto = doisDigitos(dia.getUTCDate()) + '/' + doisDigitos(dia.getUTCMonth() + 1);
            return dia.getUTCFullYear() === anoDeHoje ? texto : texto + '/' + dia.getUTCFullYear();
        }

        // ---- a escala vertical: sem zoom é a do servidor (0 até o maior valor); com zoom acompanha o trecho visível das curvas LIGADAS (desligar as outras deixa o eixo ainda mais detalhado) ----
        function calcularEscala() {
            if (!comZoom()) { return { min: 0, max: dados.yMax }; }
            var alto = 0;
            var baixo = Infinity;
            dados.series.forEach(function (s) {
                if (!visiveis[s.id]) { return; }
                alto = Math.max(alto, valorEm(s, janela.a));
                baixo = Math.min(baixo, valorEm(s, janela.b));
            });
            if (sug && visiveis[sug.id] && janela.b > sug.chega + FOLGA) {   // a remessa também conta: o topo é o estoque logo depois da chegada
                var inicioSug = Math.max(janela.a, sug.chega);
                alto = Math.max(alto, valorSug(inicioSug));
                baixo = Math.min(baixo, valorSug(janela.b));
                if (sug.chega >= janela.a) { baixo = Math.min(baixo, sug.antes); }
            }
            if (baixo === Infinity) { baixo = 0; }
            var faixa = Math.max(alto - baixo, FAIXA_MINIMA);
            var folga = faixa * 0.1;
            var minimo = baixo - folga;
            if (minimo < faixa * 0.15) { minimo = 0; }   // perto do zero, mostra o zero
            return { min: minimo, max: Math.max(alto, baixo + FAIXA_MINIMA) + folga };
        }
        // O passo "redondo" do eixo vertical (1, 2, 5, 10, 20, 25, 50...), só em números inteiros (estoque é em unidades), com no máximo `alvo` linhas.
        function passoVertical(faixa, alvo) {
            var bruto = faixa / alvo;
            var base = Math.pow(10, Math.floor(Math.log10(bruto)));
            var multiplos = [1, 2, 2.5, 5, 10];
            for (var i = 0; i < multiplos.length; i++) {
                var passo = multiplos[i] * base;
                if (passo >= bruto && passo >= 1 && Math.round(passo) === passo) { return passo; }
            }
            return Math.max(1, 10 * base);
        }

        // ---- os eixos e as linhas de grade: refeitos a cada mudança de zoom ----
        function linhaSvg(x1, y1, x2, y2, classe) {
            var linha = document.createElementNS(NS, 'line');
            linha.setAttribute('class', classe);
            linha.setAttribute('x1', arredondar(x1));
            linha.setAttribute('x2', arredondar(x2));
            linha.setAttribute('y1', arredondar(y1));
            linha.setAttribute('y2', arredondar(y2));
            return linha;
        }
        function desenharEixos() {
            area.querySelectorAll('.rup-grade, .rup-rotulo-x, .rup-rotulo-y').forEach(function (peca) { peca.parentNode.removeChild(peca); });
            var ancora = svg.querySelector(':scope > :not(.rup-zona)');   // a grade fica atrás de tudo, só na frente das zonas coloridas
            // horizontal: de quantos em quantos dias? O menor passo em que as datas ainda cabem (sem zoom ~7 dias; com zoom, até dia a dia)
            var maximoDeDatas = Math.max(4, Math.floor(area.clientWidth / PX_POR_DATA));
            var passo = PASSOS[PASSOS.length - 1];
            for (var i = 0; i < PASSOS.length; i++) {
                if (tamanho() / PASSOS[i] <= maximoDeDatas) { passo = PASSOS[i]; break; }
            }
            for (var t = Math.floor((janela.a - 1) / passo) * passo; t <= janela.b + FOLGA; t += passo) {
                if (t >= janela.a - FOLGA) { svg.insertBefore(linhaSvg(t, 0, t, 100, 'rup-grade rup-grade--x'), ancora); }   // a divisa entre os dias (meia-noite)
                var meio = t + 0.5;   // o nome da data fica no MEIO da coluna do dia
                if (meio < janela.a - FOLGA || meio > janela.b + FOLGA) { continue; }
                var rotuloX = document.createElement('span');
                rotuloX.className = 'rup-rotulo-x' + (t === 0 ? ' rup-rotulo-x--hoje' : '');
                rotuloX.style.left = porcento(meio) + '%';
                rotuloX.textContent = t === 0 ? 'HOJE' : dataDoDia(t);
                area.appendChild(rotuloX);
            }
            // vertical: de quantas em quantas unidades? Sem zoom ~4 linhas; com zoom, quantas couberem na altura (uma a cada ~28px), chegando a 1 em 1 unidade nos trechos curtos
            var linhasPossiveis = Math.max(4, Math.floor(area.clientHeight / PX_POR_NUMERO));
            var passoY = passoVertical(escala.max - escala.min, comZoom() ? linhasPossiveis : 4);
            for (var v = Math.ceil(escala.min / passoY - FOLGA) * passoY; v <= escala.max + FOLGA; v += passoY) {
                var y = yPct(v);
                svg.insertBefore(linhaSvg(janela.a, y, janela.b, y, 'rup-grade rup-grade--y'), ancora);
                var rotuloY = document.createElement('span');
                rotuloY.className = 'rup-rotulo-y';
                rotuloY.style.top = y + '%';
                rotuloY.textContent = numeroBR(v);
                area.appendChild(rotuloY);
            }
        }

        // ---- as curvas: cada uma é refeita para o trecho visível (reta de estoque caindo até zerar) ----
        function redesenharCurvas() {
            dados.series.forEach(function (s) {
                var curva = svg.querySelector('polyline[data-serie="' + s.id + '"]');
                if (!curva) { return; }
                var pontos = [[janela.a, valorEm(s, janela.a)]];
                if (s.media > 0 && dados.estoque > 0) {
                    var t0 = dados.estoque / s.media;
                    if (t0 > janela.a + FOLGA && t0 < janela.b - FOLGA) { pontos.push([t0, 0]); }
                }
                pontos.push([janela.b, valorEm(s, janela.b)]);
                curva.setAttribute('points', pontos.map(function (p) { return arredondar(p[0]) + ',' + arredondar(yPct(p[1])); }).join(' '));
            });
            var curvaSug = sug ? svg.querySelector('polyline[data-serie="' + sug.id + '"]') : null;
            if (curvaSug) {
                var aindaNaoChegou = sug.chega > janela.b + FOLGA;   // a janela termina antes da chegada: não há o que desenhar
                ocultar(curvaSug, aindaNaoChegou);
                if (!aindaNaoChegou) {
                    var inicio = Math.max(sug.chega, janela.a);
                    var trecho = [];
                    if (sug.chega >= janela.a - FOLGA) { trecho.push([sug.chega, sug.antes]); }   // o salto da chegada (a linha sobe na vertical)
                    trecho.push([inicio, valorSug(inicio)]);
                    if (sug.tZero > inicio + FOLGA && sug.tZero < janela.b - FOLGA) { trecho.push([sug.tZero, 0]); }
                    trecho.push([janela.b, valorSug(janela.b)]);
                    curvaSug.setAttribute('points', trecho.map(function (p) { return arredondar(p[0]) + ',' + arredondar(yPct(p[1])); }).join(' '));
                }
            }
        }

        // ---- textos, pontinhos e a linha do ponto de pedido: acompanham o zoom dos dois eixos e somem quando saem do trecho visível ----
        function posicionarPecas() {
            area.querySelectorAll('[data-rup-t]').forEach(function (peca) {
                var t = parseFloat(peca.getAttribute('data-rup-t'));
                var visivel = dentro(t);
                var ehPontinho = peca.classList.contains('rup-ponto-ruptura');   // onde a linha do ritmo encosta no zero
                if (ehPontinho) {
                    var zero = yPct(0);
                    visivel = visivel && zero <= 100.5;
                    peca.style.top = zero + '%';
                }
                ocultar(peca, !visivel);
                if (!visivel) { return; }
                var p = porcento(t);
                peca.style.left = p + '%';
                if (peca.hasAttribute('data-rup-lado')) {   // o texto do marcador fica do lado onde há espaço
                    peca.classList.toggle('rup-etiqueta--esq', p > 55);
                    peca.classList.toggle('rup-etiqueta--dir', p <= 55);
                }
            });
            area.querySelectorAll('[data-rup-dia]').forEach(function (peca) {   // "Enviar até" e "Ruptura": o texto fica ao lado da faixa do dia, do lado onde há espaço
                var dia = parseFloat(peca.getAttribute('data-rup-dia'));
                var esquerda = porcento(dia) > 55;
                var ancora = esquerda ? dia : dia + 1;
                var visivel = dentro(ancora);
                ocultar(peca, !visivel);
                if (!visivel) { return; }
                peca.style.left = porcento(ancora) + '%';
                peca.classList.toggle('rup-etiqueta--esq', esquerda);
                peca.classList.toggle('rup-etiqueta--dir', !esquerda);
            });
            var linhaPedido = svg.querySelector('.rup-pedido-linha');
            var rotuloPedido = area.querySelector('.rup-etiqueta--pedido');
            if (linhaPedido && rotuloPedido && dados.pedido) {
                var yp = yPct(dados.pedido);
                var cabe = yp >= 0 && yp <= 100;
                ocultar(linhaPedido, !cabe);
                ocultar(rotuloPedido, !cabe);
                if (cabe) {
                    linhaPedido.setAttribute('x1', arredondar(janela.a));
                    linhaPedido.setAttribute('x2', arredondar(janela.b));
                    linhaPedido.setAttribute('y1', arredondar(yp));
                    linhaPedido.setAttribute('y2', arredondar(yp));
                    rotuloPedido.style.top = yp + '%';
                    rotuloPedido.classList.toggle('rup-etiqueta--abaixo', yp < 30);   // linha no topo: o rótulo vai embaixo dela
                }
            }
        }

        // ---- zoom e movimento ----
        function acao(nome, desligado) {
            var botao = barra ? barra.querySelector('[data-rup-zoom-acao="' + nome + '"]') : null;
            if (botao) { botao.disabled = desligado; }
        }
        function atualizarBotoes() {
            var inteiro = !comZoom();
            acao('menos', inteiro);
            acao('tudo', inteiro);
            acao('mais', tamanho() <= MINIMO + FOLGA);
            acao('esq', janela.a <= FOLGA);
            acao('dir', janela.b >= HORIZONTE - FOLGA);
            acao('ruptura', dados.rupturaDia === null || dados.rupturaDia === undefined);
        }
        function aplicarJanela() {
            escala = calcularEscala();
            svg.setAttribute('viewBox', arredondar(janela.a) + ' 0 ' + arredondar(tamanho()) + ' 100');
            desenharEixos();
            redesenharCurvas();
            posicionarPecas();
            atualizarBotoes();
            esconderDica();
            area.classList.toggle('rup-grafico-area--zoom', comZoom());
        }
        function ajustar(inicio, fim) {   // nunca sai de [0, horizonte] e nunca fica menor que o mínimo
            var tam = Math.max(MINIMO, Math.min(HORIZONTE, fim - inicio));
            janela.a = Math.max(0, Math.min(inicio, HORIZONTE - tam));
            janela.b = janela.a + tam;
            aplicarJanela();
        }
        function zoom(fator) {
            var centro = (janela.a + janela.b) / 2;
            var tam = tamanho() * fator;
            ajustar(centro - tam / 2, centro + tam / 2);
        }
        function mover(fracao) {
            var passo = tamanho() * fracao;
            ajustar(janela.a + passo, janela.b + passo);
        }
        function verRuptura() {   // aproxima da região que importa: do dia do "Enviar até" (ou de hoje, se o prazo já passou) até o dia da ruptura (inteiro), com uma folga
            if (dados.rupturaDia === null || dados.rupturaDia === undefined) { return; }
            var folga = Math.max(3, Math.ceil((dados.lead || 0) * 0.6));
            var inicio = (dados.enviarDia !== null && dados.enviarDia !== undefined ? dados.enviarDia : dados.rupturaDia - (dados.lead || 0)) - folga;
            ajustar(inicio, dados.rupturaDia + 1 + folga);
        }
        if (barra) {
            barra.hidden = false;
            barra.addEventListener('click', function (evento) {
                var botao = evento.target.closest ? evento.target.closest('[data-rup-zoom-acao]') : null;
                if (!botao || botao.disabled) { return; }
                var nome = botao.getAttribute('data-rup-zoom-acao');
                if (nome === 'mais') { zoom(0.6); }
                else if (nome === 'menos') { zoom(1 / 0.6); }
                else if (nome === 'esq') { mover(-0.25); }
                else if (nome === 'dir') { mover(0.25); }
                else if (nome === 'ruptura') { verRuptura(); }
                else if (nome === 'tudo') { ajustar(0, HORIZONTE); }
            });
        }

        // ---- ligar e desligar curvas (a do ritmo em destaque não desliga; lembra a escolha enquanto a aba estiver aberta) ----
        var CHAVE = 'rup-curvas-ocultas';
        function lerOcultas() {
            try { return JSON.parse(window.sessionStorage.getItem(CHAVE) || '[]'); } catch (erro) { return []; }
        }
        function gravarOcultas() {
            try {
                window.sessionStorage.setItem(CHAVE, JSON.stringify(Object.keys(visiveis).filter(function (id) { return !visiveis[id]; })));
            } catch (erro) { /* sem armazenamento: a escolha só vale até recarregar */ }
        }
        function mostrarCurva(id, mostrar) {
            visiveis[id] = mostrar;
            area.querySelectorAll('[data-serie="' + id + '"]').forEach(function (peca) { peca.classList.toggle('rup-oculto', !mostrar); });
        }
        var ocultas = lerOcultas();
        document.querySelectorAll('[data-rup-curva]').forEach(function (caixa) {
            var id = caixa.getAttribute('data-rup-curva');
            if (!caixa.disabled && ocultas.indexOf(id) !== -1) { caixa.checked = false; mostrarCurva(id, false); }
            caixa.addEventListener('change', function () { mostrarCurva(id, caixa.checked); gravarOcultas(); aplicarJanela(); });
        });

        // ---- passar o mouse: linha vertical + o estoque projetado de cada curva visível naquele dia ----
        var guia = document.createElement('div');
        guia.className = 'rup-guia';
        guia.hidden = true;
        var dica = document.createElement('div');
        dica.className = 'rup-dica-grafico';
        dica.hidden = true;
        var pontos = {};
        dados.series.concat(sug ? [sug] : []).forEach(function (s) {
            var ponto = document.createElement('span');
            ponto.className = 'rup-ponto-hover rup-cor--' + s.cor;
            ponto.hidden = true;
            area.appendChild(ponto);
            pontos[s.id] = ponto;
        });
        area.appendChild(guia);
        area.appendChild(dica);

        function esconderDica() {
            guia.hidden = true;
            dica.hidden = true;
            Object.keys(pontos).forEach(function (id) { pontos[id].hidden = true; });
        }
        function unidades(n) { return numeroBR(n) + ' un'; }
        function textoUnidades(valor) { return valor > 0 && Math.round(valor) < 1 ? 'menos de 1 un' : unidades(valor); }
        // O mouse destaca o DIA inteiro (a coluna) e mostra o estoque projetado no COMEÇO dele (em hoje é o estoque lido). Na coluna em que uma curva cruza o zero aparece "acaba neste dia";
        // depois dela, "zerado". É a mesma conta da ruptura: o dia da ruptura é hoje + parte inteira dos dias de estoque.
        function mostrarDica(t, fx, py) {
            var dia = Math.max(0, Math.min(HORIZONTE - 1, Math.floor(t + FOLGA)));
            var pEsq = porcento(dia);
            var pDir = porcento(dia + 1);
            var esquerda = pEsq > 55;
            guia.hidden = false;
            guia.style.left = Math.max(0, pEsq) + '%';
            guia.style.width = Math.max(0, Math.min(100, pDir) - Math.max(0, pEsq)) + '%';
            dica.textContent = '';
            var titulo = document.createElement('div');
            titulo.className = 'rup-dica-titulo';
            titulo.textContent = diaDaSemana(dia) + ', ' + dataDoDia(dia) + ' · ' + (dia === 0 ? 'hoje' : 'em ' + dia + (dia === 1 ? ' dia' : ' dias'));
            var subtitulo = document.createElement('div');
            subtitulo.className = 'rup-dica-sub';
            subtitulo.textContent = dia === 0 ? 'Estoque atual (o lido)' : 'Estoque no início do dia';
            dica.appendChild(titulo);
            dica.appendChild(subtitulo);
            dados.series.forEach(function (s) {
                var ponto = pontos[s.id];
                if (!visiveis[s.id]) { ponto.hidden = true; return; }
                var valor = valorEm(s, dia);
                var diaZero = s.diaRuptura;   // null = a curva não zera (sem vendas ou estoque zerado)
                var acaba = diaZero !== null && diaZero !== undefined && diaZero === dia;
                var zerado = !acaba && (diaZero !== null && diaZero !== undefined ? dia > diaZero : valor <= 0);
                var linha = document.createElement('div');
                linha.className = 'rup-dica-linha rup-cor--' + s.cor + (s.id === dados.foco ? ' rup-dica-linha--foco' : '') + (zerado || acaba ? ' rup-dica-linha--zerado' : '');
                var cor = document.createElement('i');
                cor.className = 'rup-dica-cor';
                var nome = document.createElement('span');
                nome.textContent = s.rotulo;
                var numero = document.createElement('strong');
                numero.textContent = acaba ? 'acaba neste dia' : (zerado ? 'zerado' : textoUnidades(valor));
                linha.appendChild(cor);
                linha.appendChild(nome);
                linha.appendChild(numero);
                dica.appendChild(linha);
                var y = yPct(valor);
                ponto.hidden = pEsq < -0.01 || y < -1 || y > 101;   // o pontinho fica na divisa do começo do dia (que é onde está o valor); some se essa divisa saiu da janela
                ponto.style.left = pEsq + '%';
                ponto.style.top = y + '%';
            });
            if (sug) {   // a linha da remessa: só a partir do dia da chegada (antes dele ela é igual à curva do ritmo em destaque)
                var pontoSug = pontos[sug.id];
                if (!visiveis[sug.id] || dia < sug.chega) {
                    pontoSug.hidden = true;
                } else {
                    var valorS = valorSug(dia);
                    var acabaS = dia === sug.diaZero;
                    var zeradoS = !acabaS && dia > sug.diaZero;
                    var linhaS = document.createElement('div');
                    linhaS.className = 'rup-dica-linha rup-cor--' + sug.cor + (zeradoS || acabaS ? ' rup-dica-linha--zerado' : '');
                    var corS = document.createElement('i');
                    corS.className = 'rup-dica-cor';
                    var nomeS = document.createElement('span');
                    nomeS.textContent = sug.rotulo + (dia === sug.chega ? ' (chega)' : '');
                    var numeroS = document.createElement('strong');
                    numeroS.textContent = acabaS ? 'acaba neste dia' : (zeradoS ? 'zerado' : textoUnidades(valorS));
                    linhaS.appendChild(corS);
                    linhaS.appendChild(nomeS);
                    linhaS.appendChild(numeroS);
                    dica.appendChild(linhaS);
                    var yS = yPct(valorS);
                    pontoSug.hidden = pEsq < -0.01 || yS < -1 || yS > 101;
                    pontoSug.style.left = pEsq + '%';
                    pontoSug.style.top = yS + '%';
                }
            }
            dica.hidden = false;
            dica.classList.toggle('rup-dica-grafico--esq', esquerda);
            dica.style.left = Math.max(0, Math.min(100, esquerda ? pEsq : pDir)) + '%';
            dica.style.top = Math.max(4, Math.min(py - dica.offsetHeight / 2, area.clientHeight - dica.offsetHeight - 4)) + 'px';
        }

        var arrasto = null;
        area.addEventListener('mousemove', function (evento) {
            if (arrasto) { return; }
            var caixa = area.getBoundingClientRect();
            var fx = (evento.clientX - caixa.left) / caixa.width;
            if (fx < 0 || fx > 1) { esconderDica(); return; }
            mostrarDica(janela.a + fx * tamanho(), fx, evento.clientY - caixa.top);
        });
        area.addEventListener('mouseleave', esconderDica);

        // ---- arrastar (só quando há zoom; sem zoom o gráfico já está inteiro) ----
        area.addEventListener('pointerdown', function (evento) {
            if (evento.button !== 0 || !comZoom()) { return; }
            arrasto = { x: evento.clientX, a: janela.a, b: janela.b };
            area.classList.add('rup-grafico-area--arrastando');
            try { area.setPointerCapture(evento.pointerId); } catch (erro) { /* sem captura: o arrasto segue só dentro da área */ }
            esconderDica();
        });
        area.addEventListener('pointermove', function (evento) {
            if (!arrasto) { return; }
            var caixa = area.getBoundingClientRect();
            var deslocamento = (evento.clientX - arrasto.x) / caixa.width * (arrasto.b - arrasto.a);
            ajustar(arrasto.a - deslocamento, arrasto.b - deslocamento);
        });
        function soltar() {
            arrasto = null;
            area.classList.remove('rup-grafico-area--arrastando');
        }
        area.addEventListener('pointerup', soltar);
        area.addEventListener('pointercancel', soltar);

        // ---- scroll do mouse em cima do gráfico = SÓ zoom (regra do Matheus): ANCORADO no mouse (o dia que está sob o mouse continua sob o mouse). Rolar para cima aproxima; para baixo afasta.
        //      Mesmo no limite do zoom (já inteiro, ou no máximo de aproximação) a página NÃO rola enquanto o mouse estiver sobre o gráfico: para rolar a página, é só tirar o mouse de cima dele.
        //      Ctrl + scroll continua sendo o zoom do próprio navegador (não é interceptado). ----
        area.addEventListener('wheel', function (evento) {
            if (evento.ctrlKey || evento.deltaY === 0) { return; }
            evento.preventDefault();
            if (arrasto) { return; }
            var passo = evento.deltaY * (evento.deltaMode === 1 ? 16 : (evento.deltaMode === 2 ? 400 : 1));
            var fator = Math.exp(Math.max(-300, Math.min(300, passo)) * 0.002);   // uma "volta" da roda (100) = ~22% a mais ou a menos de dias na janela
            var caixa = area.getBoundingClientRect();
            var fx = Math.max(0, Math.min(1, (evento.clientX - caixa.left) / caixa.width));
            var novoTamanho = Math.max(MINIMO, Math.min(HORIZONTE, tamanho() * fator));
            if (Math.abs(novoTamanho - tamanho()) < FOLGA) { return; }   // já está no limite: não muda nada, mas o scroll também não vai para a página
            var inicio = (janela.a + fx * tamanho()) - fx * novoTamanho;
            ajustar(inicio, inicio + novoTamanho);
            mostrarDica(janela.a + fx * tamanho(), fx, evento.clientY - caixa.top);
        }, { passive: false });

        // a largura do gráfico muda (barra lateral abre ou fecha, janela redimensionada): as datas do eixo se refazem para caber
        if (window.ResizeObserver) {
            new window.ResizeObserver(function () { aplicarJanela(); }).observe(area);
        }
        aplicarJanela();
    }
    iniciarGrafico();

    // [5] Botões "Consultar no Mercado Livre" da tabela de estoque (detalhe): o ÚNICO lugar desta tela que chama o Mercado Livre, e só por clique. Um Código ML por chamada ao servidor (data-rup-url);
    //     "Consultar todos" faz os Códigos da tabela UM POR VEZ (em fila). Acesso recusado ou varredura rodando (o servidor responde "interromper") para a fila. Ao terminar, se algum Código foi atualizado,
    //     a tela recarrega (o endereço guarda o ritmo, o prazo, o chegar antes, a folga e as referências dos dois mundos) e volta a ler só do banco; o resultado fica numa linha de apoio que sobrevive ao recarregamento.
    var secaoConsulta = document.querySelector('[data-rup-consulta]');
    if (secaoConsulta) {
        var urlConsulta = secaoConsulta.getAttribute('data-rup-url');
        var statusConsulta = secaoConsulta.querySelector('[data-rup-status]');
        var botoesConsulta = secaoConsulta.querySelectorAll('[data-rup-consultar]');
        var CHAVE_RESULTADO = 'rup_resultado_da_consulta';
        var ocupado = false;

        function csrfConsulta() {
            var campo = document.querySelector('#rup-csrf input[name="csrfmiddlewaretoken"]');
            return campo ? campo.value : '';
        }

        function dizer(texto, tom) {
            if (!statusConsulta) { return; }
            statusConsulta.textContent = texto;
            statusConsulta.setAttribute('data-rup-dica', texto);
            statusConsulta.classList.remove('rup-consulta-status--erro', 'rup-consulta-status--ok');
            if (tom) { statusConsulta.classList.add('rup-consulta-status--' + tom); }
        }

        function travar(travado, botaoClicado) {
            ocupado = travado;
            botoesConsulta.forEach(function (botao) {
                botao.disabled = travado;
                botao.classList.toggle('rup-consulta-btn--girando', travado && botao === botaoClicado);
            });
        }

        // O resultado da consulta anterior (a tela recarregou depois dela): aparece na linha de apoio e vale só para esta visita.
        try {
            var guardado = window.sessionStorage.getItem(CHAVE_RESULTADO);
            if (guardado) {
                window.sessionStorage.removeItem(CHAVE_RESULTADO);
                var resultado = JSON.parse(guardado);
                dizer(resultado.texto, resultado.tom);
            }
        } catch (erro) { /* sem sessionStorage a tela funciona igual: só não repete o resultado */ }

        function consultar(codigos, botaoClicado) {
            if (ocupado || !codigos.length) { return; }
            travar(true, botaoClicado);
            var posicao = 0, atualizados = 0, problemas = [], parar = false;

            function terminar() {
                var texto, tom;
                if (!problemas.length) {
                    texto = atualizados === 1 ? 'Código atualizado no Mercado Livre.' : atualizados + ' Códigos atualizados no Mercado Livre.';
                    tom = 'ok';
                } else {
                    texto = (atualizados ? atualizados + ' de ' + codigos.length + ' atualizados. ' : 'Nada foi atualizado. ') + problemas[0] + (problemas.length > 1 ? ' (+' + (problemas.length - 1) + ' erro' + (problemas.length > 2 ? 's' : '') + ')' : '');
                    tom = 'erro';
                }
                if (atualizados > 0) {
                    try { window.sessionStorage.setItem(CHAVE_RESULTADO, JSON.stringify({ texto: texto, tom: tom })); } catch (erro) { /* tudo bem */ }
                    dizer('Atualizado. Recarregando…', 'ok');
                    window.location.reload();
                    return;
                }
                dizer(texto, tom);
                travar(false, null);
            }

            function proximo() {
                if (parar || posicao >= codigos.length) { terminar(); return; }
                var codigo = codigos[posicao];
                posicao += 1;
                dizer('Consultando ' + codigo + ' (' + posicao + ' de ' + codigos.length + ')… pode levar alguns segundos.');
                fetch(urlConsulta, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'X-CSRFToken': csrfConsulta(), 'Accept': 'application/json', 'Content-Type': 'application/json' },
                    body: JSON.stringify({ codigo: codigo })
                }).then(function (resposta) {
                    return resposta.json().catch(function () { return { ok: false, mensagem: 'Resposta inesperada do servidor.' }; });
                }).then(function (dados) {
                    if (dados && dados.ok) { atualizados += 1; } else {
                        problemas.push(codigo + ': ' + ((dados && dados.mensagem) || 'a consulta falhou.'));
                        if (dados && dados.interromper) { parar = true; }
                    }
                    proximo();
                }).catch(function () {
                    problemas.push(codigo + ': não consegui falar com o servidor.');
                    parar = true;
                    proximo();
                });
            }
            proximo();
        }

        botoesConsulta.forEach(function (botao) {
            botao.addEventListener('click', function () {
                var alvo = botao.getAttribute('data-rup-consultar');
                if (alvo === 'todos') {
                    var codigos = [];
                    botoesConsulta.forEach(function (outro) {
                        var codigo = outro.getAttribute('data-rup-consultar');
                        if (codigo !== 'todos') { codigos.push(codigo); }
                    });
                    consultar(codigos, botao);
                } else {
                    consultar([alvo], botao);
                }
            });
        });
    }

    // [6] Balão de dica no padrão da tela. Vale só dentro da tela (.rup-pagina) e do atalho da barra de cima.
    var ESCOPO_DICA = '.rup-pagina, .rup-toolbar-link';
    var balaoDica = null;
    var alvoDica = null;
    var esperaDica = null;
    var mouseDicaX = 0;
    var mouseDicaY = 0;

    // Troca title por data-rup-dica (some o balão preto do navegador). Botão só com ícone não tem texto: o title vira o aria-label para o leitor de tela não perder o nome.
    function prepararDicas() {
        document.querySelectorAll(ESCOPO_DICA).forEach(function (area) {
            var itens = Array.prototype.slice.call(area.querySelectorAll('[title]'));
            if (area.hasAttribute('title')) { itens.push(area); }
            itens.forEach(function (el) {
                var texto = (el.getAttribute('title') || '').trim();
                el.removeAttribute('title');
                if (!texto) { return; }
                el.setAttribute('data-rup-dica', texto);
                if (!el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') && !(el.textContent || '').trim()) {
                    el.setAttribute('aria-label', texto);
                }
            });
        });
    }

    function acharDica(elemento) {
        if (!elemento || !elemento.closest) { return null; }
        var alvo = elemento.closest('[data-rup-dica]');
        return alvo && alvo.closest(ESCOPO_DICA) ? alvo : null;
    }

    function criarBalaoDica() {
        if (!balaoDica) {
            balaoDica = document.createElement('div');
            balaoDica.id = 'rup-dica';
            balaoDica.className = 'rup-dica';
            balaoDica.setAttribute('role', 'tooltip');
            document.body.appendChild(balaoDica);
        }
        return balaoDica;
    }

    // Põe o balão perto do alvo, sempre dentro da janela: embaixo se couber (senão em cima), centralizado no alvo e empurrado para dentro nas bordas; a setinha continua apontando para o alvo.
    // Alvo alto (cartão, bloco) usa o ponto do mouse como referência, para o balão não aparecer longe do cursor.
    function posicionarDica(alvo, pelaTeclado) {
        var balao = criarBalaoDica();
        var margem = 8;
        var folga = 10;
        var larguraJanela = document.documentElement.clientWidth;
        var alturaJanela = document.documentElement.clientHeight;
        var caixa = alvo.getBoundingClientRect();
        var ref = { esq: caixa.left, dir: caixa.right, topo: caixa.top, base: caixa.bottom };
        if (!pelaTeclado && caixa.height > 56) {
            ref = { esq: mouseDicaX, dir: mouseDicaX, topo: mouseDicaY - 4, base: mouseDicaY + 14 };
        }
        var largura = balao.offsetWidth;
        var altura = balao.offsetHeight;
        var centro = (Math.max(ref.esq, 0) + Math.min(ref.dir, larguraJanela)) / 2;
        var esq = Math.max(margem, Math.min(centro - largura / 2, larguraJanela - largura - margem));
        var embaixo = ref.base + folga;
        var emCima = ref.topo - folga - altura;
        var usaCima = embaixo + altura > alturaJanela - margem && emCima >= margem;
        var topo = usaCima ? emCima : embaixo;
        var topoFinal = Math.max(margem, Math.min(topo, alturaJanela - altura - margem));
        balao.style.left = Math.round(esq) + 'px';
        balao.style.top = Math.round(topoFinal) + 'px';
        balao.style.setProperty('--rup-dica-seta', Math.round(Math.max(14, Math.min(centro - esq, largura - 14))) + 'px');
        balao.classList.toggle('rup-dica--acima', usaCima);
        balao.classList.toggle('rup-dica--sem-seta', topoFinal !== topo);
    }

    function abrirDica(alvo, pelaTeclado) {
        var texto = alvo.getAttribute('data-rup-dica');
        if (!texto) { return; }
        var balao = criarBalaoDica();
        balao.textContent = texto;
        balao.classList.add('rup-dica--visivel');
        alvo.setAttribute('aria-describedby', 'rup-dica');
        posicionarDica(alvo, pelaTeclado);
    }

    function fecharDica() {
        clearTimeout(esperaDica);
        esperaDica = null;
        if (alvoDica) { alvoDica.removeAttribute('aria-describedby'); }
        alvoDica = null;
        if (balaoDica) { balaoDica.classList.remove('rup-dica--visivel'); }
    }

    function aprontarDicas() {
        prepararDicas();
        // Mouse: o balão abre depois de uma pausa curta (não pisca quando o mouse só passa por cima) e fecha ao sair do alvo.
        document.addEventListener('mouseover', function (evento) {
            var alvo = acharDica(evento.target);
            if (alvo === alvoDica) { return; }
            fecharDica();
            if (!alvo) { return; }
            alvoDica = alvo;
            mouseDicaX = evento.clientX;
            mouseDicaY = evento.clientY;
            esperaDica = setTimeout(function () { esperaDica = null; if (alvoDica === alvo) { abrirDica(alvo, false); } }, 250);
        });
        document.addEventListener('mouseout', function (evento) {
            if (alvoDica && !(evento.relatedTarget && alvoDica.contains(evento.relatedTarget))) { fecharDica(); }
        });
        // Teclado (Tab): abre na hora, só quando o foco veio do teclado.
        document.addEventListener('focusin', function (evento) {
            var alvo = acharDica(evento.target);
            var doTeclado = false;
            try { doTeclado = evento.target.matches(':focus-visible'); } catch (erro) { doTeclado = false; }
            if (!alvo || !doTeclado) { return; }
            fecharDica();
            alvoDica = alvo;
            abrirDica(alvo, true);
        });
        document.addEventListener('focusout', fecharDica);
        document.addEventListener('keydown', function (evento) { if (evento.key === 'Escape') { fecharDica(); } });
        document.addEventListener('mousedown', fecharDica);
        window.addEventListener('scroll', fecharDica, true);
        window.addEventListener('resize', fecharDica);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', aprontarDicas);
    } else {
        aprontarDicas();
    }
})();
