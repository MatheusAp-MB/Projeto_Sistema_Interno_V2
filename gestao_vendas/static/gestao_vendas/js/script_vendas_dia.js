/*
 * [RESUMO] → O card de detalhe de cada dia da tela "Vendas — Histórico de vendas". Clicar num dia do calendário (visão Meses ou Semanas) abre um
 *            card junto dele com o que aconteceu naquele dia: total de unidades, quanto foi Full e quanto foi fora do Full, pedidos, faturamento,
 *            cancelados, hora de pico, anúncios que mais venderam e como o dia se compara com a média. Tem o botão "Atualizar este dia" (é o
 *            mesmo botão [data-vnd-dia] do script_vendas.js, que continua sendo quem faz a consulta ao Mercado Livre).
 * * [EXPLICAÇÃO] → Os números NÃO são calculados aqui: o Python manda um JSON (<script id="vnd-dias-dados">) com os textos já formatados de cada
 *                  dia, e este arquivo só os desenha. Tudo o que vem do banco entra na tela por textContent (nunca por innerHTML).
 * * [EXPLICAÇÃO] → O card é "position: fixed" e segue o dia quando a página rola ou quando o calendário rola por dentro (.vnd-cal-rolagem); se o dia sai
 *                  da área visível do calendário, o card fecha. No celular (até 760px) ele vira uma folha embaixo da tela.
 *                  Fecha com Esc, com o X ou clicando fora; as setas ‹ › (ou as teclas ← →) vão para o dia anterior / seguinte.
 * * [EXPLICAÇÃO] → MODO FIXADO: quando a área do calendário (.vnd-cal-area) tem largura para o calendário continuar legível E o painel (ver --vnd-painel-area-min no CSS),
 *                  o card deixa de flutuar e vira uma coluna ao lado do calendário. Nesse modo ele não segue o dia, não fecha ao clicar fora nem quando o dia rola para fora
 *                  (fecha só com o X, Esc ou clicando de novo no mesmo dia). Sem largura (menu lateral aberto numa tela menor) ou no celular, vale o card flutuante de sempre.
 *                  Ao abrir/fechar a coluna o calendário muda de largura (3 meses por linha viram 2); por isso o dia aberto é trazido de volta para a vista.
 */
(function () {
    'use strict';

    const pagina = document.querySelector('.vnd-pagina');
    const card = document.getElementById('vnd-dia-card');
    const fonte = document.getElementById('vnd-dias-dados');
    const area = document.querySelector('[data-vnd-area]');
    if (!pagina || !card || !fonte) {
        return;
    }

    let dados = {};
    try {
        dados = JSON.parse(fonte.textContent) || {};
    } catch (erro) {
        return;
    }
    const chaves = Object.keys(dados).sort();
    const celular = window.matchMedia('(max-width: 760px)');
    // Depois de "Atualizar este dia" a página recarrega; o card do dia atualizado reabre sozinho (por até 2 minutos).
    const CHAVE_REABRIR = 'vnd-dia-reabrir';
    const MS_PARA_REABRIR = 120000;

    let aberto = '';
    let ancora = null;
    let quadro = 0;

    // ---------- modo "fixado" (coluna ao lado do calendário) x "flutuante" (card junto do dia) ----------
    // * [EXPLICAÇÃO] → Para ENTRAR no modo fixado a área precisa ter o mínimo + FOLGA_DA_BARRA_DE_ROLAGEM px; para continuar nele, só o mínimo. Motivo: abrir o painel pode
    //                  fazer surgir a barra de rolagem da página (a área encolhe ~15px) e, sem essa folga, o modo ficaria trocando sozinho (painel abre, barra aparece, painel sai...).
    //                  Com a folga na entrada, o calendário nunca fica abaixo do tamanho mínimo.
    const FOLGA_DA_BARRA_DE_ROLAGEM = 16;
    let larguraDaArea = 0;

    function fixado() {
        return !!area && area.dataset.vndFixar === '1';
    }

    // Função Objetivo: Decide se o painel cabe fixo ao lado do calendário (largura da área >= --vnd-painel-area-min do CSS) e avisa o CSS por data-vnd-fixar.
    //                  Se o navegador não entender a variável, o mínimo vira 0 e o painel nunca fixa (continua flutuando).
    function atualizarModo() {
        if (!area) {
            return;
        }
        const minima = parseFloat(window.getComputedStyle(area).getPropertyValue('--vnd-painel-area-min')) || 0;
        const folga = fixado() ? 0 : FOLGA_DA_BARRA_DE_ROLAGEM;
        const cabe = !celular.matches && minima > 0 && area.clientWidth >= minima + folga;
        area.dataset.vndFixar = cabe ? '1' : '';
        card.setAttribute('role', cabe ? 'region' : 'dialog');
    }

    // Função Objetivo: Avisa o CSS (data-vnd-aberto) se há um dia aberto: com o modo fixado, é isso que abre a 2ª coluna.
    function marcarAberto(sim) {
        if (!area) {
            return;
        }
        if (sim) {
            area.dataset.vndAberto = '1';
        } else {
            area.removeAttribute('data-vnd-aberto');
        }
    }

    // Função Objetivo: Depois que a coluna abre/fecha o calendário se reorganiza; traz o dia de volta para a vista (o mínimo de rolagem possível).
    function manterDiaAVista(elemento) {
        if (elemento && document.contains(elemento) && elemento.scrollIntoView) {
            elemento.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        }
    }

    function criar(tag, classe, texto) {
        const elemento = document.createElement(tag);
        if (classe) {
            elemento.className = classe;
        }
        if (texto !== undefined && texto !== null) {
            elemento.textContent = texto;
        }
        return elemento;
    }

    function celula(iso) {
        return pagina.querySelector('[data-vnd-detalhe="' + iso + '"]');
    }

    function botaoIcone(icone, rotulo, direcao, aoClicar) {
        const botao = criar('button', 'vnd-card-icone');
        botao.type = 'button';
        botao.title = rotulo;
        botao.setAttribute('aria-label', rotulo);
        if (direcao) {
            botao.dataset.direcao = direcao;
        }
        const i = criar('i', 'fas ' + icone);
        i.setAttribute('aria-hidden', 'true');
        botao.appendChild(i);
        botao.addEventListener('click', aoClicar);
        return botao;
    }

    function par(rotulo, valor) {
        const linha = criar('div');
        linha.appendChild(criar('dt', '', rotulo));
        linha.appendChild(criar('dd', '', valor));
        return linha;
    }

    function guardarParaReabrir(iso) {
        try {
            window.sessionStorage.setItem(CHAVE_REABRIR, JSON.stringify({ iso: iso, quando: Date.now() }));
        } catch (erro) {
            // sem armazenamento (janela privada etc.): o card só não reabre sozinho
        }
    }

    // Função Objetivo: Monta o conteúdo do card de um dia (lista de elementos).
    function montar(iso) {
        const d = dados[iso];
        const posicao = chaves.indexOf(iso);
        const partes = [];

        const cabecalho = criar('header', 'vnd-card-cab');
        const titulo = criar('div', 'vnd-card-tit');
        const nome = criar('h3', 'vnd-card-titulo', d.titulo);
        nome.id = 'vnd-dia-card-titulo';
        titulo.appendChild(nome);
        titulo.appendChild(criar('span', 'vnd-card-estado vnd-card-estado--' + d.estado, d.estado_txt));
        const anterior = botaoIcone('fa-chevron-left', 'Dia anterior', '-1', function () { ir(-1); });
        const seguinte = botaoIcone('fa-chevron-right', 'Dia seguinte', '1', function () { ir(1); });
        anterior.disabled = posicao <= 0;
        seguinte.disabled = posicao >= chaves.length - 1;
        cabecalho.appendChild(anterior);
        cabecalho.appendChild(titulo);
        cabecalho.appendChild(seguinte);
        cabecalho.appendChild(botaoIcone('fa-xmark', 'Fechar', '', function () { fechar(true); }));
        partes.push(cabecalho);

        if (d.coletado) {
            partes.push(criar('p', 'vnd-card-coleta', d.coletado.charAt(0).toUpperCase() + d.coletado.slice(1)));
        }

        if (d.estado === 'sem_dado') {
            partes.push(criar('p', 'vnd-card-aviso', 'Este dia ainda não foi coletado. Não é zero: é um dia sem informação, por isso fica fora da média e dos totais.'));
        } else {
            const total = criar('div', 'vnd-card-total' + (d.zero ? ' vnd-card-total--zero' : ''));
            total.appendChild(criar('strong', '', d.un));
            total.appendChild(criar('span', '', d.un === '1' ? 'unidade vendida' : 'unidades vendidas'));
            partes.push(total);

            if (d.zero) {
                partes.push(criar('p', 'vnd-card-coleta', 'Dia completo sem nenhuma venda neste recorte.'));
            } else {
                const resumo = criar('dl', 'vnd-card-resumo');
                resumo.appendChild(par('Pedidos', d.pedidos));
                resumo.appendChild(par('Faturamento', d.fat));
                if (d.preco_medio) {
                    resumo.appendChild(par('Preço médio', d.preco_medio));
                }
                partes.push(resumo);
            }

            if (d.origens && d.origens.length) {
                const secao = criar('div');
                secao.appendChild(criar('p', 'vnd-card-secao-titulo', 'Por origem'));
                d.origens.forEach(function (o) {
                    const linha = criar('div', 'vnd-card-origem vnd-card-origem--' + o.chave);
                    linha.appendChild(criar('span', 'vnd-card-origem-rot', o.rotulo));
                    linha.appendChild(criar('span', 'vnd-card-origem-un', o.un + ' un'));
                    linha.appendChild(criar('span', 'vnd-card-origem-pct', o.pct));
                    const barra = criar('span', 'vnd-card-barra');
                    const enchimento = criar('span');
                    enchimento.style.width = Math.max(0, Math.min(100, Number(o.barra) || 0)) + '%';
                    barra.appendChild(enchimento);
                    linha.appendChild(barra);
                    linha.appendChild(criar('span', 'vnd-card-origem-det', o.pedidos + (o.pedidos === '1' ? ' pedido' : ' pedidos') + ' · ' + o.fat));
                    secao.appendChild(linha);
                });
                partes.push(secao);
            }

            const fatos = criar('dl', 'vnd-card-fatos');
            if (d.cancelados) {
                fatos.appendChild(par('Cancelados (fora das contas)', d.cancelados));
            }
            if (d.pico) {
                fatos.appendChild(par('Hora de pico', d.pico));
            }
            if (d.media) {
                fatos.appendChild(par('Ritmo', d.media));
            }
            if (fatos.children.length) {
                partes.push(fatos);
            }

            if (d.anuncios && d.anuncios.length) {
                const secao = criar('div');
                secao.appendChild(criar('p', 'vnd-card-secao-titulo', 'Anúncios que mais venderam'));
                const lista = criar('ul', 'vnd-card-anuncios');
                d.anuncios.forEach(function (a) {
                    const item = criar('li');
                    item.appendChild(criar('code', '', a.mlb));
                    item.appendChild(criar('span', 'vnd-card-anuncio-nome', a.titulo));
                    item.appendChild(criar('strong', '', a.un + ' un'));
                    if (a.titulo) {
                        item.title = a.titulo;
                    }
                    lista.appendChild(item);
                });
                secao.appendChild(lista);
                if (d.anuncios_extra) {
                    secao.appendChild(criar('p', 'vnd-card-extra', '+ ' + d.anuncios_extra + (d.anuncios_extra === 1 ? ' outro anúncio' : ' outros anúncios')));
                }
                partes.push(secao);
            }
        }

        if (d.aviso) {
            partes.push(criar('p', 'vnd-card-aviso vnd-card-aviso--' + d.aviso.tipo, d.aviso.texto));
        }

        const rodape = criar('div', 'vnd-card-rodape');
        const atualizar = criar('button', 'vnd-btn vnd-btn--secundario vnd-btn--mini');
        atualizar.type = 'button';
        atualizar.dataset.vndDia = iso;
        atualizar.title = 'Consulta o Mercado Livre e recoleta este dia (conta toda)';
        const icone = criar('i', 'fas fa-rotate');
        icone.setAttribute('aria-hidden', 'true');
        atualizar.appendChild(icone);
        atualizar.appendChild(document.createTextNode(' '));
        atualizar.appendChild(criar('span', 'vnd-btn-texto', 'Atualizar este dia'));
        atualizar.addEventListener('click', function () { guardarParaReabrir(iso); });
        rodape.appendChild(atualizar);
        partes.push(rodape);
        return partes;
    }

    function desmarcar() {
        if (ancora) {
            ancora.classList.remove('vnd-selecionado');
            ancora.removeAttribute('aria-expanded');
        }
    }

    // Função Objetivo: Põe o card ao lado do dia (à direita; se não couber, à esquerda) sem sair da janela. No celular o CSS o prende embaixo; no modo fixado não há o que posicionar.
    function posicionar() {
        if (card.hidden) {
            return;
        }
        if (fixado() || celular.matches || !ancora) {
            card.style.left = '';
            card.style.top = '';
            return;
        }
        const margem = 8;
        const a = ancora.getBoundingClientRect();
        // O dia rolou para fora da área do calendário: o card não tem mais a que se agarrar.
        const area = ancora.closest('.vnd-cal-rolagem');
        if (area) {
            const r = area.getBoundingClientRect();
            if (a.bottom < r.top + 4 || a.top > r.bottom - 4 || a.right < r.left + 4 || a.left > r.right - 4) {
                fechar(false);
                return;
            }
        }
        const largura = card.offsetWidth;
        const altura = card.offsetHeight;
        let esquerda = a.right + margem;
        if (esquerda + largura > window.innerWidth - margem) {
            esquerda = a.left - largura - margem;
        }
        esquerda = Math.max(margem, Math.min(esquerda, window.innerWidth - largura - margem));
        const topo = Math.max(margem, Math.min(a.top - 12, window.innerHeight - altura - margem));
        card.style.left = Math.round(esquerda) + 'px';
        card.style.top = Math.round(topo) + 'px';
    }

    function abrir(iso, elemento, opcoes) {
        if (!dados[iso]) {
            return;
        }
        const o = opcoes || {};
        desmarcar();
        aberto = iso;
        ancora = elemento || celula(iso);
        if (ancora) {
            ancora.classList.add('vnd-selecionado');
            ancora.setAttribute('aria-expanded', 'true');
            if (o.rolar && ancora.scrollIntoView) {
                ancora.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            }
        }
        const partes = montar(iso);
        while (card.firstChild) {
            card.removeChild(card.firstChild);
        }
        partes.forEach(function (parte) { card.appendChild(parte); });
        card.hidden = false;
        marcarAberto(true);
        card.scrollTop = 0;
        posicionar();
        if (fixado()) {
            manterDiaAVista(ancora);
        }
        let foco = card;
        if (o.direcao) {
            const botao = card.querySelector('[data-direcao="' + o.direcao + '"]:not(:disabled)') || card.querySelector('[data-direcao]:not(:disabled)');
            foco = botao || card;
        }
        foco.focus({ preventScroll: true });
    }

    function fechar(devolverFoco) {
        if (card.hidden) {
            return;
        }
        card.hidden = true;
        marcarAberto(false);
        desmarcar();
        const elemento = ancora;
        aberto = '';
        ancora = null;
        if (fixado()) {
            manterDiaAVista(elemento);
        }
        if (devolverFoco && elemento && document.contains(elemento)) {
            elemento.focus({ preventScroll: true });
        }
    }

    function ir(passo) {
        const posicao = chaves.indexOf(aberto) + passo;
        if (posicao < 0 || posicao >= chaves.length) {
            return;
        }
        abrir(chaves[posicao], null, { rolar: true, direcao: String(passo) });
    }

    // ---------- eventos ----------
    pagina.addEventListener('click', function (evento) {
        const alvo = evento.target.closest('[data-vnd-detalhe]');
        if (!alvo || !pagina.contains(alvo) || evento.target.closest('[data-vnd-dia]')) {
            return;
        }
        const iso = alvo.dataset.vndDetalhe;
        if (!card.hidden && aberto === iso) {
            fechar(false);
            return;
        }
        abrir(iso, alvo);
    });

    // * [EXPLICAÇÃO] → Os botões ‹ › refazem o card inteiro: quando o clique chega aqui, o botão clicado já saiu da página. Por isso o teste
    //                  "document.contains": sem ele, esse clique contaria como "clicou fora" e fecharia o card que acabou de abrir.
    document.addEventListener('click', function (evento) {
        if (card.hidden || fixado() || !document.contains(evento.target) || card.contains(evento.target) || evento.target.closest('[data-vnd-detalhe]')) {
            return;
        }
        fechar(false);
    });

    document.addEventListener('keydown', function (evento) {
        if (card.hidden) {
            return;
        }
        if (evento.key === 'Escape') {
            fechar(true);
        } else if ((evento.key === 'ArrowLeft' || evento.key === 'ArrowRight') && card.contains(document.activeElement)) {
            evento.preventDefault();
            ir(evento.key === 'ArrowLeft' ? -1 : 1);
        }
    });

    function reposicionar(evento) {
        if (card.hidden || quadro || (evento && evento.target && evento.target !== document && evento.target instanceof Node && card.contains(evento.target))) {
            return;
        }
        quadro = window.requestAnimationFrame(function () {
            quadro = 0;
            posicionar();
        });
    }
    window.addEventListener('scroll', reposicionar, true);
    window.addEventListener('resize', reposicionar);

    // ---------- modo fixado x flutuante: decide agora e de novo sempre que a largura da área (ou o celular) mudar ----------
    atualizarModo();
    if (area && 'ResizeObserver' in window) {
        new ResizeObserver(function () {
            if (area.clientWidth === larguraDaArea) {
                return;
            }
            larguraDaArea = area.clientWidth;
            atualizarModo();
            reposicionar();
        }).observe(area);
    }
    celular.addEventListener('change', function () {
        atualizarModo();
        reposicionar();
    });

    // ---------- depois de "Atualizar este dia": reabre o mesmo dia ----------
    (function reabrirSeHouver() {
        let guardado = null;
        try {
            guardado = JSON.parse(window.sessionStorage.getItem(CHAVE_REABRIR) || 'null');
            window.sessionStorage.removeItem(CHAVE_REABRIR);
        } catch (erro) {
            return;
        }
        if (!guardado || !dados[guardado.iso] || Date.now() - guardado.quando > MS_PARA_REABRIR) {
            return;
        }
        const elemento = celula(guardado.iso);
        if (elemento) {
            abrir(guardado.iso, elemento, { rolar: true });
        }
    })();
})();
