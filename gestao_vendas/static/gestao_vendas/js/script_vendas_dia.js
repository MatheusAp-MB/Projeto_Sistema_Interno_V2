/*
 * [RESUMO] → O painel de detalhe de cada dia da tela "Vendas — Histórico de vendas". Clicar num dia do calendário (visão Meses ou Semanas) abre o painel
 *            com o que aconteceu naquele dia, em BLOCOS que respondem uma pergunta cada: cabeçalho (posso confiar nesse número? + botão "Atualizar este dia",
 *            que é o mesmo botão [data-vnd-dia] do script_vendas.js, quem continua fazendo a consulta ao Mercado Livre), resumo (o que aconteceu?),
 *            comparação com o mesmo dia da semana (foi bom ou ruim?), origem Full x fora do Full, anúncios, hora a hora, preço e sinais, e pedidos e
 *            cancelamentos (esse só busca os pedidos no servidor quando o bloco é aberto).
 * * [EXPLICAÇÃO] → Os números NÃO são calculados aqui: o Python manda um JSON (<script id="vnd-dias-dados">) com os textos já formatados de cada
 *                  dia (e <script id="vnd-anuncios-dados"> com título, foto, link e selos de cada MLB), e este arquivo só os desenha. Tudo o que vem do banco entra na tela por
 *                  textContent (nunca por innerHTML). A única chamada ao servidor é a lista de pedidos do dia (GET que só lê o banco), por clique no bloco.
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

    // ---------- os BLOCOS do painel ----------
    // * [EXPLICAÇÃO] → Cada bloco responde uma pergunta de quem clica num dia (desenho combinado em 11/10/2026): Resumo (o que aconteceu?), Comparação (foi bom ou ruim,
    //                  comparado a quê?), Origem (de onde veio?), Anúncios (quais?), Hora a hora (quando?), Preços do dia (a que preço, e por que foi diferente?) e Pedidos e cancelamentos
    //                  (conferência). Os blocos (menos o Resumo) abrem e fecham (<details>); a escolha de cada um fica guardada no navegador (se ele deixar), por isso o painel
    //                  "lembra" quais blocos a pessoa quer ver ao trocar de dia. O de Pedidos começa fechado e só busca os pedidos no servidor quando é aberto.
    const CHAVE_BLOCOS = 'vnd-painel-blocos';
    const BLOCOS_ABERTOS_PADRAO = { comparacao: true, origem: true, anuncios: true, horas: true, precos: true, pedidos: false };
    const ROTULOS_DE_ORIGEM = { full: 'Full', fora: 'Fora do Full', indefinido: 'Sem origem' };
    // [rótulo do selo, o que ele quer dizer] de cada marca da lista de preços do dia
    const ROTULOS_DE_MARCA_DE_PRECO = {
        menor: ['MENOR', 'Menor preço vendido no dia'],
        maior: ['MAIOR', 'Maior preço vendido no dia'],
        top: ['MAIS VENDIDO', 'Preço com mais unidades vendidas no dia'],
    };
    const urlPedidos = area ? (area.dataset.vndUrlPedidos || '') : '';
    let dadosDosAnuncios = {};
    try {
        const fonteAnuncios = document.getElementById('vnd-anuncios-dados');
        dadosDosAnuncios = fonteAnuncios ? (JSON.parse(fonteAnuncios.textContent) || {}) : {};
    } catch (erro) {
        dadosDosAnuncios = {};
    }
    const cachePedidos = {};
    const pedidosEmBusca = {};

    function lerBlocosAbertos() {
        const estado = Object.assign({}, BLOCOS_ABERTOS_PADRAO);
        try {
            const guardado = JSON.parse(window.localStorage.getItem(CHAVE_BLOCOS) || 'null');
            if (guardado && typeof guardado === 'object') {
                Object.keys(BLOCOS_ABERTOS_PADRAO).forEach(function (chave) {
                    if (typeof guardado[chave] === 'boolean') {
                        estado[chave] = guardado[chave];
                    }
                });
            }
        } catch (erro) {
            // sem armazenamento (janela privada etc.): vale o padrão
        }
        return estado;
    }
    const blocosAbertos = lerBlocosAbertos();

    function guardarBlocosAbertos() {
        try {
            window.localStorage.setItem(CHAVE_BLOCOS, JSON.stringify(blocosAbertos));
        } catch (erro) {
            // sem armazenamento: o painel só não lembra da escolha
        }
    }

    function limpar(elemento) {
        while (elemento.firstChild) {
            elemento.removeChild(elemento.firstChild);
        }
    }

    function plural(n, singular, varios) {
        return String(n) === '1' ? singular : varios;
    }

    // Função Objetivo: Uma barra horizontal (0 a 100%) usada na Comparação.
    function barraSimples(porcentagem, classe) {
        const barra = criar('span', 'vnd-card-barra' + (classe ? ' ' + classe : ''));
        const enchimento = criar('span');
        enchimento.style.width = Math.max(0, Math.min(100, Number(porcentagem) || 0)) + '%';
        barra.appendChild(enchimento);
        return barra;
    }

    // Função Objetivo: Uma barra EMPILHADA Full / Fora do Full / Sem origem. `partes` = [{chave, barra}]; é só a forma da divisão, os números ficam em texto ao lado.
    function barraEmpilhada(partes, classe) {
        const pilha = criar('span', 'vnd-pilha' + (classe ? ' ' + classe : ''));
        pilha.setAttribute('aria-hidden', 'true');
        partes.forEach(function (parte) {
            const largura = Math.max(0, Math.min(100, Number(parte.barra) || 0));
            if (largura > 0) {
                const segmento = criar('span', 'vnd-pilha-' + parte.chave);
                segmento.style.width = largura + '%';
                pilha.appendChild(segmento);
            }
        });
        return pilha;
    }

    // Função Objetivo: Monta um bloco do painel (<details> com título, resumo curto ao lado do título e o conteúdo). Guarda se a pessoa abriu ou fechou.
    function bloco(chave, titulo, resumo, conteudo, aoAbrir) {
        const detalhes = criar('details', 'vnd-pn-bloco');
        detalhes.dataset.bloco = chave;
        detalhes.open = blocosAbertos[chave] !== false;
        const cabecalho = criar('summary', 'vnd-pn-bloco-cab');
        cabecalho.appendChild(criar('span', 'vnd-pn-bloco-titulo', titulo));
        if (resumo) {
            cabecalho.appendChild(criar('span', 'vnd-pn-bloco-resumo', resumo));
        }
        detalhes.appendChild(cabecalho);
        const corpo = criar('div', 'vnd-pn-bloco-corpo');
        (Array.isArray(conteudo) ? conteudo : [conteudo]).forEach(function (parte) {
            if (parte) {
                corpo.appendChild(parte);
            }
        });
        detalhes.appendChild(corpo);
        detalhes.addEventListener('toggle', function () {
            if (blocosAbertos[chave] !== detalhes.open) {
                blocosAbertos[chave] = detalhes.open;
                guardarBlocosAbertos();
            }
            if (detalhes.open && aoAbrir) {
                aoAbrir(corpo);
            }
        });
        if (detalhes.open && aoAbrir) {
            aoAbrir(corpo);
        }
        return detalhes;
    }

    // Função Objetivo: A RÉGUA do bloco Comparação: uma escala de 0 até o maior valor, com a barra deste dia, a linha pontilhada na média dos mesmos dias da semana e uma
    // bolinha no melhor e no pior dia deles (o tracejado liga o pior ao melhor: a faixa em que esse dia da semana costuma ficar). `pos` (0 a 100) vem pronto do Python.
    function reguaDeComparacao(linhas) {
        const pontos = {};
        const dicas = {};
        const falado = [];
        linhas.forEach(function (l) {
            if (l.pos !== undefined) {
                pontos[l.chave] = Math.max(0, Math.min(100, Number(l.pos) || 0));
                dicas[l.chave] = l.rotulo + ': ' + l.texto + (l.detalhe ? ' (' + l.detalhe + ')' : '');
                falado.push(dicas[l.chave]);
            }
        });
        const regua = criar('div', 'vnd-reg');
        regua.setAttribute('role', 'img');
        regua.setAttribute('aria-label', 'Régua de comparação. ' + falado.join('; ') + '.');
        regua.appendChild(criar('span', 'vnd-reg-trilho'));
        if (pontos.melhor !== undefined && pontos.pior !== undefined) {
            const faixa = criar('span', 'vnd-reg-faixa');
            faixa.style.left = pontos.pior + '%';
            faixa.style.width = Math.max(0, pontos.melhor - pontos.pior) + '%';
            regua.appendChild(faixa);
        }
        if (pontos.este !== undefined) {
            const este = criar('span', 'vnd-reg-este');
            este.style.width = pontos.este + '%';
            este.title = dicas.este;
            if (pontos.este > 0) {
                este.style.minWidth = '4px';
            }
            regua.appendChild(este);
        }
        ['pior', 'melhor'].forEach(function (chave) {
            if (pontos[chave] !== undefined) {
                const ponta = criar('span', 'vnd-reg-ponta vnd-reg-ponta--' + chave);
                ponta.style.left = pontos[chave] + '%';
                ponta.title = dicas[chave];
                regua.appendChild(ponta);
            }
        });
        if (pontos.media !== undefined) {
            const media = criar('span', 'vnd-reg-media');
            media.style.left = pontos.media + '%';
            media.title = dicas.media;
            regua.appendChild(media);
        }
        return regua;
    }

    function blocoComparacao(c) {
        const partes = [];
        if (c.linhas.some(function (l) { return l.pos !== undefined; })) {
            partes.push(reguaDeComparacao(c.linhas));
        }
        const legenda = criar('div', 'vnd-cmp-lista');
        c.linhas.forEach(function (l) {
            const linha = criar('div', 'vnd-cmp' + (l.chave === 'este' ? ' vnd-cmp--destaque' : ''));
            if (l.dica) {
                linha.title = l.dica;
            }
            linha.appendChild(criar('i', 'vnd-cmp-amostra vnd-cmp-amostra--' + l.chave));
            const rotulo = criar('span', 'vnd-cmp-rot', l.rotulo);
            if (l.detalhe) {
                rotulo.appendChild(criar('span', 'vnd-cmp-det', l.detalhe));
            }
            linha.appendChild(rotulo);
            linha.appendChild(criar('span', 'vnd-cmp-val', l.texto));
            legenda.appendChild(linha);
        });
        partes.push(legenda);
        if (c.posicao) {
            partes.push(criar('p', 'vnd-card-nota vnd-card-nota--forte', c.posicao));
        }
        if (c.sem_base) {
            partes.push(criar('p', 'vnd-card-nota', c.sem_base));
        }
        if (c.nota) {
            partes.push(criar('p', 'vnd-card-nota', c.nota));
        }
        return bloco('comparacao', 'Comparação', '', partes);
    }

    function blocoOrigem(origens) {
        const partes = [barraEmpilhada(origens.map(function (o) { return { chave: o.chave, barra: o.barra }; }), 'vnd-pilha--grande')];
        origens.forEach(function (o) {
            const linha = criar('div', 'vnd-card-origem vnd-card-origem--' + o.chave);
            const rotulo = criar('span', 'vnd-card-origem-rot');
            rotulo.appendChild(criar('i', 'vnd-ponto vnd-ponto--' + o.chave));
            rotulo.appendChild(document.createTextNode(o.rotulo));
            linha.appendChild(rotulo);
            linha.appendChild(criar('span', 'vnd-card-origem-un', o.un + ' un'));
            linha.appendChild(criar('span', 'vnd-card-origem-pct', o.pct));
            linha.appendChild(criar('span', 'vnd-card-origem-det', o.pedidos + ' ' + plural(o.pedidos, 'pedido', 'pedidos') + ' · ' + o.fat));
            partes.push(linha);
        });
        return bloco('origem', 'Origem', '', partes);
    }

    // Função Objetivo: Só deixa passar endereço https. A foto e o link vêm do banco, mas nenhum outro esquema (javascript:, data:, http:) entra na página.
    function urlHttps(texto) {
        return typeof texto === 'string' && /^https:\/\//i.test(texto) ? texto : '';
    }

    // Função Objetivo: Copia um texto. O jeito moderno (navigator.clipboard) só existe em contexto seguro (https ou localhost); no http puro cai no jeito antigo.
    function copiarTexto(texto) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(texto);
        }
        return new Promise(function (resolve, reject) {
            const anterior = document.activeElement;
            const campo = document.createElement('textarea');
            campo.value = texto;
            campo.style.position = 'fixed';
            campo.style.opacity = '0';
            document.body.appendChild(campo);
            campo.focus();
            campo.select();
            try {
                if (document.execCommand('copy')) {
                    resolve();
                } else {
                    reject(new Error('cópia recusada'));
                }
            } catch (erro) {
                reject(erro);
            } finally {
                document.body.removeChild(campo);
                if (anterior && anterior.focus) {
                    anterior.focus();
                }
            }
        });
    }

    // Função Objetivo: A foto do anúncio (52 × 52). Sem endereço, ou se a imagem não carregar, entra um quadrado cinza com o ícone de imagem no lugar.
    function fotoDoAnuncio(dados) {
        const vazia = function () {
            const caixa = criar('span', 'vnd-anu-foto vnd-anu-foto--vazia');
            caixa.setAttribute('aria-hidden', 'true');
            caixa.appendChild(criar('i', 'fas fa-image'));
            return caixa;
        };
        const endereco = urlHttps(dados && dados.imagem);
        if (!endereco) {
            return vazia();
        }
        const foto = criar('img', 'vnd-anu-foto');
        foto.alt = '';
        foto.loading = 'lazy';
        foto.decoding = 'async';
        foto.referrerPolicy = 'no-referrer';
        foto.addEventListener('error', function () {
            if (foto.parentNode) {
                foto.parentNode.replaceChild(vazia(), foto);
            }
        });
        foto.src = endereco;
        return foto;
    }

    // Função Objetivo: Os selos do anúncio (status, tipo, logística, Flex e papel no catálogo), com a classe de cor e o ícone que o Python mandou do registro único de
    // selos do sistema. Anúncio fora do cadastro não tem selos: nesse caso só se mostra o tipo que a própria venda registrou (se tiver).
    function selosDoAnuncio(dados, linha) {
        const selos = criar('div', 'vnd-anu-selos');
        const lista = dados && Array.isArray(dados.selos) ? dados.selos : [];
        lista.forEach(function (selo) {
            if (!selo || !selo.rotulo) {
                return;
            }
            const cor = /^[a-z0-9_-]+$/i.test(selo.classe || '') ? selo.classe : 'badge-papel';
            const chip = criar('span', 'badge-tabela ' + cor);
            if (selo.dica) {
                chip.title = selo.dica;
            }
            if (/^fa-[a-z0-9-]+$/i.test(selo.icone || '')) {
                const icone = criar('i', 'fas ' + selo.icone);
                icone.setAttribute('aria-hidden', 'true');
                chip.appendChild(icone);
            }
            chip.appendChild(document.createTextNode(selo.rotulo));
            selos.appendChild(chip);
        });
        if (!selos.childNodes.length && linha.tipo) {
            const doRegistro = criar('span', 'badge-tabela badge-papel', linha.tipo);
            doRegistro.title = 'Tipo do anúncio registrado na própria venda';
            selos.appendChild(doRegistro);
        }
        return selos.childNodes.length ? selos : null;
    }

    // Função Objetivo: A parte de baixo de um anúncio (igual para anúncio e Código ML): a barra Full / Fora do Full e a linha "Full 7 · Fora 1 · R$ … · R$ …/un".
    function rodapeDoAnuncio(item, l) {
        if (l.barra_full !== undefined || l.barra_fora !== undefined) {
            item.appendChild(barraEmpilhada([
                { chave: 'full', barra: l.barra_full }, { chave: 'fora', barra: l.barra_fora }, { chave: 'indefinido', barra: l.barra_sem }
            ]));
        }
        const detalhe = [];
        if (l.full !== undefined) {
            detalhe.push('Full ' + l.full);
            detalhe.push('Fora ' + l.fora);
            if (l.sem !== undefined) {
                detalhe.push('Sem origem ' + l.sem);
            }
        }
        if (l.fat) {
            detalhe.push(l.fat);
        }
        if (l.preco) {
            detalhe.push(l.preco + '/un');
        }
        if (detalhe.length || l.mudou) {
            const linha = criar('div', 'vnd-anu-det', detalhe.join(' · '));
            if (l.mudou) {
                linha.appendChild(document.createTextNode(detalhe.length ? ' ' : ''));
                linha.appendChild(criar('span', 'vnd-pn-etiqueta vnd-pn-etiqueta--aviso', 'mais de um preço'));
            }
            item.appendChild(linha);
        }
    }

    // Função Objetivo: O cartão de UM anúncio, no jeito do Hub de Anúncios: foto, selos, título e MLB (com copiar e abrir no ML); as unidades vendidas ficam à direita.
    function cartaoDoAnuncio(l) {
        const dados = dadosDosAnuncios[l.chave] || null;
        const item = criar('li', 'vnd-anu');
        const identidade = criar('div', 'vnd-anu-id');
        identidade.appendChild(fotoDoAnuncio(dados));
        const corpo = criar('div', 'vnd-anu-corpo');
        const selos = selosDoAnuncio(dados, l);
        if (selos) {
            corpo.appendChild(selos);
        }
        if (dados && dados.titulo) {
            const nome = criar('div', 'vnd-anu-titulo', dados.titulo);
            nome.title = dados.titulo;
            corpo.appendChild(nome);
        } else if (dados && dados.no_cadastro === false) {
            corpo.appendChild(criar('div', 'vnd-anu-titulo vnd-anu-titulo--aviso', 'Anúncio fora do cadastro deste produto'));
        }
        const linha = criar('div', 'vnd-anu-linha');
        linha.appendChild(criar('code', 'vnd-anu-mlb', l.chave || '—'));
        if (l.chave) {
            const copiar = criar('button', 'vnd-anu-icone');
            copiar.type = 'button';
            copiar.dataset.vndCopiar = l.chave;
            copiar.title = 'Copiar ' + l.chave;
            copiar.setAttribute('aria-label', 'Copiar ' + l.chave);
            copiar.appendChild(criar('i', 'fas fa-copy'));
            linha.appendChild(copiar);
        }
        const endereco = urlHttps(dados && dados.link);
        if (endereco) {
            const abrir = criar('a', 'vnd-anu-icone');
            abrir.href = endereco;
            abrir.target = '_blank';
            abrir.rel = 'noopener noreferrer';
            abrir.title = 'Abrir no Mercado Livre';
            abrir.setAttribute('aria-label', 'Abrir ' + l.chave + ' no Mercado Livre');
            abrir.appendChild(criar('i', 'fas fa-arrow-up-right-from-square'));
            linha.appendChild(abrir);
        }
        const numeros = criar('span', 'vnd-anu-numeros');
        numeros.appendChild(criar('strong', '', l.un + ' un'));
        numeros.appendChild(criar('span', 'vnd-anu-pct', l.pct));
        linha.appendChild(numeros);
        corpo.appendChild(linha);
        identidade.appendChild(corpo);
        item.appendChild(identidade);
        rodapeDoAnuncio(item, l);
        return item;
    }

    // Função Objetivo: O bloco "Anúncios" (ou "Códigos ML", no nível Por MLB): do que mais vendeu para o que menos vendeu. Anúncio ganha cartão com foto e selos; Código ML
    // continua uma linha simples (não tem foto, título nem selos).
    function blocoAnuncios(a) {
        const porCodigo = a.tipo === 'codigo';
        const lista = criar('ul', 'vnd-anu-lista');
        let comSelos = false;
        a.linhas.forEach(function (l) {
            if (!porCodigo) {
                const dados = dadosDosAnuncios[l.chave];
                comSelos = comSelos || !!(dados && Array.isArray(dados.selos) && dados.selos.length);
                lista.appendChild(cartaoDoAnuncio(l));
                return;
            }
            const item = criar('li', 'vnd-anu');
            const topo = criar('div', 'vnd-anu-topo');
            topo.appendChild(criar('code', '', l.chave || 'Sem Código ML único'));
            topo.appendChild(criar('strong', '', l.un + ' un'));
            topo.appendChild(criar('span', 'vnd-anu-pct', l.pct));
            item.appendChild(topo);
            rodapeDoAnuncio(item, l);
            lista.appendChild(item);
        });
        // * [EXPLICAÇÃO] → Os selos são a situação de HOJE do anúncio (última importação do banco), não a do dia da venda: um anúncio que vendeu em março pode estar
        //                  pausado agora. O aviso fica uma vez só, embaixo da lista.
        const nota = comSelos ? criar('p', 'vnd-card-extra', 'Os selos mostram como o anúncio está hoje, não como estava naquele dia.') : null;
        return bloco('anuncios', porCodigo ? 'Códigos ML' : 'Anúncios', String(a.linhas.length), [lista, nota]);
    }

    function blocoHoras(h) {
        const maximo = Math.max.apply(null, [1].concat(h.v, h.ref || []));
        const grade = criar('div', 'vnd-horas');
        grade.setAttribute('role', 'img');
        grade.setAttribute('aria-label', 'Unidades vendidas por hora do dia. Pico: ' + h.pico + '.');
        for (let hora = 0; hora < 24; hora++) {
            const semDado = h.corte !== undefined && hora >= h.corte;
            const coluna = criar('span', 'vnd-hora' + (semDado ? ' vnd-hora--sem-dado' : ''));
            const valor = h.v[hora];
            const barra = criar('i', 'vnd-hora-barra');
            barra.style.height = (!semDado && valor > 0) ? Math.max(valor / maximo * 100, 3) + '%' : '0';
            coluna.appendChild(barra);
            if (h.ref && !semDado && h.ref[hora] > 0) {
                const marca = criar('b', 'vnd-hora-ref');
                marca.style.bottom = (h.ref[hora] / maximo * 100) + '%';
                coluna.appendChild(marca);
            }
            let dica = hora + 'h: ' + (semDado ? 'ainda sem dado' : valor + ' un');
            if (h.ref && !semDado) {
                dica += ' (média ' + h.nome + ': ' + String(h.ref[hora]).replace('.', ',') + ')';
            }
            coluna.title = dica;
            grade.appendChild(coluna);
        }
        const eixo = criar('div', 'vnd-horas-eixo');
        eixo.setAttribute('aria-hidden', 'true');
        [0, 6, 12, 18, 23].forEach(function (hora) {
            const marca = criar('span', '', hora + 'h');
            if (hora === 0) {
                marca.style.left = '0';
                marca.style.transform = 'none';
            } else if (hora === 23) {
                marca.style.right = '0';
                marca.style.transform = 'none';
            } else {
                marca.style.left = ((hora + 0.5) / 24 * 100) + '%';
            }
            eixo.appendChild(marca);
        });
        const partes = [grade, eixo];
        const legenda = criar('p', 'vnd-card-nota');
        legenda.appendChild(criar('strong', '', 'Pico: ' + h.pico));
        if (h.ref) {
            legenda.appendChild(document.createTextNode(' · '));
            legenda.appendChild(criar('i', 'vnd-hora-amostra'));
            legenda.appendChild(document.createTextNode(' média de unidades ' + (h.art || 'dos') + ' ' + h.n_ref + ' ' + h.nome + ' do período'));
        }
        if (h.corte !== undefined) {
            legenda.appendChild(document.createTextNode(' · hachurado: da hora da coleta em diante (sem dado, não é zero)'));
        }
        partes.push(legenda);
        return bloco('horas', 'Hora a hora', '', partes);
    }

    // Função Objetivo: A RÉGUA de preços do dia: do menor ao maior preço, uma bolinha em cada preço (maior = vendeu mais unidades) e uma marca laranja no preço médio.
    // `pos`/`media` (0 a 100) e `rel` (0 a 1, o tamanho da bolinha) vêm prontos do Python.
    function reguaDePrecos(r, medio) {
        const regua = criar('div', 'vnd-pr-regua');
        regua.setAttribute('role', 'img');
        regua.setAttribute('aria-label', 'Régua de preços de ' + r.min + ' a ' + r.max + '. ' + r.pontos.map(function (p) { return p.dica; }).join('; ') + '. Preço médio ' + medio + '.');
        regua.appendChild(criar('span', 'vnd-pr-trilho'));
        const media = criar('span', 'vnd-pr-media');
        media.style.left = Math.max(0, Math.min(100, Number(r.media) || 0)) + '%';
        media.title = 'Preço médio: ' + medio;
        regua.appendChild(media);
        r.pontos.forEach(function (p) {
            const posicao = Math.max(0, Math.min(100, Number(p.pos) || 0));
            const tamanho = 8 + 8 * Math.sqrt(Math.max(0, Math.min(1, Number(p.rel) || 0)));
            const ponto = criar('span', 'vnd-pr-ponto' + (posicao >= 100 ? ' vnd-pr-ponto--maior' : ''));
            ponto.style.left = posicao + '%';
            ponto.style.width = tamanho + 'px';
            ponto.style.height = tamanho + 'px';
            ponto.title = p.dica;
            regua.appendChild(ponto);
        });
        const eixo = criar('div', 'vnd-pr-eixo');
        eixo.appendChild(criar('span', '', r.min));
        eixo.appendChild(criar('span', '', r.max));
        regua.appendChild(eixo);
        return regua;
    }

    // Função Objetivo: Uma linha da lista de preços: o preço, as marcas (MENOR / MAIOR / MAIS VENDIDO), unidades e % do dia, uma barrinha e, embaixo, o anúncio (MLB),
    // de que horas a que horas houve venda com esse preço e o faturamento dele.
    function linhaDePreco(l) {
        const item = criar('li', 'vnd-pr-linha');
        const topo = criar('div', 'vnd-pr-topo');
        topo.appendChild(criar('span', 'vnd-pr-preco', l.preco));
        (l.marcas || []).forEach(function (marca) {
            const selo = criar('span', 'vnd-pr-sel vnd-pr-sel--' + marca, ROTULOS_DE_MARCA_DE_PRECO[marca] ? ROTULOS_DE_MARCA_DE_PRECO[marca][0] : marca);
            if (ROTULOS_DE_MARCA_DE_PRECO[marca]) {
                selo.title = ROTULOS_DE_MARCA_DE_PRECO[marca][1];
            }
            topo.appendChild(selo);
        });
        const numeros = criar('span', 'vnd-pr-num');
        numeros.appendChild(criar('strong', '', l.un + ' un'));
        numeros.appendChild(criar('span', '', l.pct));
        topo.appendChild(numeros);
        item.appendChild(topo);
        const barra = criar('div', 'vnd-pr-barra');
        const enchimento = criar('span');
        enchimento.style.width = Math.max(0, Math.min(100, Number(l.barra) || 0)) + '%';
        barra.appendChild(enchimento);
        item.appendChild(barra);
        const detalhe = criar('div', 'vnd-pr-det');
        if (l.mlb) {
            detalhe.appendChild(criar('code', 'vnd-pr-mlb', l.mlb));
            detalhe.appendChild(document.createTextNode(' · '));
        }
        if (l.var) {
            detalhe.appendChild(document.createTextNode('var. ' + l.var + ' · '));
        }
        if (l.quando) {
            detalhe.appendChild(document.createTextNode(l.quando + ' · '));
        }
        detalhe.appendChild(document.createTextNode(l.fat));
        item.appendChild(detalhe);
        return item;
    }

    // Função Objetivo: Uma linha do resumo (rótulo, valor e, embaixo do rótulo, uma explicação curta em letra pequena).
    function parComDetalhe(rotulo, valor, detalhe, dica) {
        const linha = criar('div');
        const dt = criar('dt', '', rotulo);
        if (detalhe) {
            dt.appendChild(criar('small', '', detalhe));
        }
        if (dica) {
            linha.title = dica;
        }
        linha.appendChild(dt);
        linha.appendChild(criar('dd', '', valor));
        return linha;
    }

    // Função Objetivo: A caixa de aviso de UM anúncio que vendeu por mais de um preço no dia. "preço mudou" só quando os períodos de cada preço não se cruzam (o Python decide, pelo
    // instante exato das vendas); senão é "preços misturados" e a caixa diz que não dá para afirmar que houve troca.
    function caixaDeTroca(t) {
        const caixa = criar('div', 'vnd-troca');
        const titulo = criar('p', 'vnd-troca-titulo');
        titulo.appendChild(criar('code', '', t.mlb + (t.variacao ? ' · var. ' + t.variacao : '')));
        titulo.appendChild(criar('span', 'vnd-pn-etiqueta vnd-pn-etiqueta--aviso', t.em_ordem ? 'preço mudou durante o dia' : 'preços misturados no dia'));
        caixa.appendChild(titulo);
        t.passos.forEach(function (passo) {
            const linha = criar('div', 'vnd-troca-passo');
            linha.appendChild(criar('strong', '', passo.preco));
            linha.appendChild(criar('span', '', passo.un + ' un' + (passo.quando ? ' · ' + passo.quando : '')));
            caixa.appendChild(linha);
        });
        if (t.extra) {
            caixa.appendChild(criar('p', 'vnd-card-extra', '+ ' + t.extra + (t.extra === 1 ? ' outro preço' : ' outros preços')));
        }
        if (t.em_ordem) {
            const mudancas = [];
            t.passos.forEach(function (passo, i) {
                if (passo.troca && i > 0) {
                    mudancas.push({ de: t.passos[i - 1].preco, para: passo.preco, quando: passo.troca });
                }
            });
            // * [EXPLICAÇÃO] → Uma frase por troca, cada uma em sua linha (3 preços = 2 trocas): "A troca aconteceu entre 10:03 e 10:12." ou "R$ 24,90 → R$ 21,90: entre 09:30 e 11:15."
            mudancas.forEach(function (m) {
                const nota = criar('p', 'vnd-card-extra', mudancas.length === 1 ? 'A troca aconteceu ' + m.quando + '.' : m.de + ' → ' + m.para + ': ' + m.quando + '.');
                nota.title = 'Do horário da última venda com o preço antigo ao da primeira venda com o preço novo: o sistema só enxerga as vendas, não o momento exato em que o preço foi trocado.';
                caixa.appendChild(nota);
            });
        } else {
            caixa.appendChild(criar('p', 'vnd-card-extra', 'Os horários dos preços se misturam (o preço voltou ao que era, ou dois preços valeram ao mesmo tempo): não dá para afirmar que houve troca.'));
        }
        return caixa;
    }

    // Função Objetivo: O bloco "Preços do dia": régua, lista do menor ao maior preço, resumo (preço médio e comparação com os mesmos dias da semana), trocas de preço dos anúncios e
    // os sinais do pedido (desconto, catálogo, cancelados). Tudo já vem calculado do Python; aqui só se desenha.
    function blocoPrecos(p, cancelados) {
        const partes = [];
        if (p.linhas && p.linhas.length) {
            if (p.regua) {
                partes.push(reguaDePrecos(p.regua, p.medio));
            }
            const lista = criar('ul', 'vnd-pr-lista');
            p.linhas.forEach(function (l) {
                lista.appendChild(linhaDePreco(l));
            });
            partes.push(lista);
            if (p.sobra) {
                partes.push(criar('p', 'vnd-card-extra', '+ ' + p.sobra.n + (p.sobra.n === 1 ? ' outro preço' : ' outros preços') + ' (' + p.sobra.un + ' un) de menor volume'));
            }
            if (p.linhas.some(function (l) { return l.quando; })) {
                partes.push(criar('p', 'vnd-card-nota', 'Os horários são o da primeira e o da última venda com cada preço. O sistema só enxerga as vendas, não o momento em que o preço foi trocado no anúncio.'));
            }
            const resumo = criar('dl', 'vnd-card-fatos vnd-pr-resumo');
            resumo.appendChild(parComDetalhe('Preço médio', p.medio, p.conta, 'Preço médio = faturamento ÷ unidades vendidas com preço (cancelados ficam de fora).'));
            if (p.amplitude) {
                resumo.appendChild(parComDetalhe('Maior preço acima do menor', p.amplitude));
            }
            if (p.ref && p.ref.valor) {
                resumo.appendChild(parComDetalhe(p.ref.rotulo, p.ref.valor, p.ref.texto, 'Faturamento ÷ unidades (' + p.ref.un + ' un) de todas as vendas com preço desses dias. O próprio dia entra na conta.'));
            }
            partes.push(resumo);
            if (p.ref && p.ref.sem) {
                partes.push(criar('p', 'vnd-card-nota', p.ref.sem));
            }
        }
        (p.trocas || []).forEach(function (t) {
            partes.push(caixaDeTroca(t));
        });
        if (p.trocas_extra) {
            partes.push(criar('p', 'vnd-card-extra', '+ ' + p.trocas_extra + (p.trocas_extra === 1 ? ' outro anúncio com mais de um preço' : ' outros anúncios com mais de um preço')));
        }
        if (p.sem_preco) {
            partes.push(criar('p', 'vnd-card-nota', p.sem_preco));
        }
        const sinais = criar('dl', 'vnd-card-fatos');
        if (p.n_pedidos) {
            sinais.appendChild(par('Pedidos com desconto', p.desconto + ' de ' + p.n_pedidos));
            sinais.appendChild(par('Vendas por catálogo', p.catalogo + ' de ' + p.n_pedidos));
        }
        if (cancelados) {
            sinais.appendChild(par('Cancelados (fora das contas)', cancelados.un + (cancelados.fat ? ' · ' + cancelados.fat : '')));
        }
        if (sinais.children.length) {
            partes.push(sinais);
        }
        const mudou = (p.trocas || []).some(function (t) { return t.em_ordem; });
        const resumoDoTitulo = p.n_precos ? p.n_precos + (p.n_precos === 1 ? ' preço' : ' preços') + (mudou ? ' · mudou' : '') : '';
        return bloco('precos', 'Preços do dia', resumoDoTitulo, partes);
    }

    // ---------- bloco Pedidos e cancelamentos: os pedidos vêm do servidor só quando o bloco é aberto ----------
    function linhaDePedido(p, cancelado) {
        const item = criar('li', 'vnd-ped' + (cancelado ? ' vnd-ped--cancelado' : ''));
        item.appendChild(criar('span', 'vnd-ped-hora', p.hora));
        const numeroDoPedido = criar('code', 'vnd-ped-id', p.pedido);
        numeroDoPedido.title = 'Número do pedido no Mercado Livre (um clique seleciona tudo)';
        item.appendChild(numeroDoPedido);
        item.appendChild(criar('span', 'vnd-ped-origem vnd-ped-origem--' + p.origem, ROTULOS_DE_ORIGEM[p.origem] || p.origem));
        item.appendChild(criar('span', 'vnd-ped-det', p.mlb + ' · ' + p.un + ' × ' + (p.preco || 'sem preço')));
        return item;
    }

    function desenharPedidos(destino, pedidos) {
        limpar(destino);
        if (!pedidos.n_pedidos && !pedidos.n_cancelados) {
            destino.appendChild(criar('p', 'vnd-card-nota', 'Nenhum pedido deste recorte no banco para este dia.'));
            return;
        }
        if (pedidos.n_pedidos) {
            const itens = pedidos.n_itens || pedidos.pedidos.length;
            destino.appendChild(criar('p', 'vnd-card-secao-titulo', pedidos.n_pedidos + ' ' + plural(pedidos.n_pedidos, 'pedido', 'pedidos') + (itens > pedidos.n_pedidos ? ' · ' + itens + ' itens' : '')));
            const lista = criar('ol', 'vnd-ped-lista');
            pedidos.pedidos.forEach(function (p) { lista.appendChild(linhaDePedido(p, false)); });
            destino.appendChild(lista);
            if (pedidos.truncado) {
                destino.appendChild(criar('p', 'vnd-card-nota', 'Mostrando só os primeiros ' + pedidos.pedidos.length + ' de ' + itens + ' itens.'));
            }
        }
        if (pedidos.n_cancelados) {
            const itensCancelados = pedidos.n_itens_cancelados || pedidos.cancelados.length;
            destino.appendChild(criar('p', 'vnd-card-secao-titulo', pedidos.n_cancelados + ' ' + plural(pedidos.n_cancelados, 'cancelado', 'cancelados') + (itensCancelados > pedidos.n_cancelados ? ' · ' + itensCancelados + ' itens' : '') + ' (fora das contas)'));
            const lista = criar('ol', 'vnd-ped-lista vnd-ped-lista--cancelados');
            pedidos.cancelados.forEach(function (p) { lista.appendChild(linhaDePedido(p, true)); });
            destino.appendChild(lista);
        }
    }

    // Função Objetivo: Busca os pedidos de um dia (uma vez só por dia: o resultado fica guardado enquanto a página estiver aberta). Rejeita com o texto do erro.
    function buscarPedidos(iso) {
        if (cachePedidos[iso]) {
            return Promise.resolve(cachePedidos[iso]);
        }
        if (pedidosEmBusca[iso]) {
            return pedidosEmBusca[iso];
        }
        const parametros = new window.URLSearchParams({
            sku: area.dataset.vndSku || '', nivel: area.dataset.vndNivel || '', item: area.dataset.vndItem || '', dia: iso
        });
        const promessa = window.fetch(urlPedidos + '?' + parametros.toString(), { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
            .then(function (resposta) {
                return resposta.json().catch(function () { return {}; }).then(function (corpo) {
                    if (!resposta.ok || !corpo.ok) {
                        throw new Error(corpo.mensagem || 'O servidor não conseguiu listar os pedidos.');
                    }
                    cachePedidos[iso] = corpo;
                    return corpo;
                });
            })
            .then(function (corpo) {
                delete pedidosEmBusca[iso];
                return corpo;
            }, function (erro) {
                delete pedidosEmBusca[iso];
                throw (erro && erro.message && erro.message !== 'Failed to fetch') ? erro : new Error('Não consegui falar com o servidor. Verifique a conexão e tente de novo.');
            });
        pedidosEmBusca[iso] = promessa;
        return promessa;
    }

    function carregarPedidos(iso, destino) {
        if (destino.dataset.estado === 'carregando' || destino.dataset.estado === 'pronto') {
            return;
        }
        if (!urlPedidos || !area) {
            destino.dataset.estado = 'erro';
            limpar(destino);
            destino.appendChild(criar('p', 'vnd-card-aviso', 'Esta página não tem o endereço para buscar os pedidos. Recarregue a página.'));
            return;
        }
        destino.dataset.estado = 'carregando';
        limpar(destino);
        destino.appendChild(criar('p', 'vnd-card-nota', 'Carregando os pedidos…'));
        buscarPedidos(iso).then(function (pedidos) {
            if (!destino.isConnected) {
                return;
            }
            destino.dataset.estado = 'pronto';
            desenharPedidos(destino, pedidos);
        }, function (erro) {
            if (!destino.isConnected) {
                return;
            }
            destino.dataset.estado = 'erro';
            limpar(destino);
            destino.appendChild(criar('p', 'vnd-card-aviso vnd-card-aviso--baixo', erro.message));
            const tentar = criar('button', 'vnd-btn vnd-btn--secundario vnd-btn--mini', 'Tentar de novo');
            tentar.type = 'button';
            tentar.addEventListener('click', function () {
                destino.dataset.estado = '';
                carregarPedidos(iso, destino);
            });
            destino.appendChild(tentar);
        });
    }

    function blocoPedidos(iso, d) {
        const partes = [];
        if (d.pedidos) {
            partes.push(d.pedidos);
        }
        if (d.cancelados) {
            partes.push(d.cancelados.pedidos + ' ' + plural(d.cancelados.pedidos, 'cancelado', 'cancelados'));
        }
        const destino = criar('div', 'vnd-ped-destino');
        return bloco('pedidos', 'Pedidos e cancelamentos', partes.join(' · '), destino, function () { carregarPedidos(iso, destino); });
    }

    function botaoAtualizar(iso) {
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
        return atualizar;
    }

    // Função Objetivo: Monta o conteúdo do painel de um dia (lista de elementos): cabeçalho, resumo e os blocos.
    function montar(iso) {
        const d = dados[iso];
        const posicao = chaves.indexOf(iso);
        const partes = [];

        // ---- cabeçalho: dia, setas, X, o selo do estado do dado, a hora da coleta e o botão de atualizar ----
        const cabecalho = criar('header', 'vnd-card-cab');
        const titulo = criar('div', 'vnd-card-tit');
        const nome = criar('h3', 'vnd-card-titulo', d.titulo);
        nome.id = 'vnd-dia-card-titulo';
        titulo.appendChild(nome);
        const situacao = criar('div', 'vnd-card-situacao');
        situacao.appendChild(criar('span', 'vnd-card-estado vnd-card-estado--' + d.estado, d.estado_txt));
        if (d.coletado) {
            situacao.appendChild(criar('span', 'vnd-card-coleta', d.coletado.charAt(0).toUpperCase() + d.coletado.slice(1)));
        }
        situacao.appendChild(botaoAtualizar(iso));
        titulo.appendChild(situacao);
        const anterior = botaoIcone('fa-chevron-left', 'Dia anterior', '-1', function () { ir(-1); });
        const seguinte = botaoIcone('fa-chevron-right', 'Dia seguinte', '1', function () { ir(1); });
        anterior.disabled = posicao <= 0;
        seguinte.disabled = posicao >= chaves.length - 1;
        cabecalho.appendChild(anterior);
        cabecalho.appendChild(titulo);
        cabecalho.appendChild(seguinte);
        cabecalho.appendChild(botaoIcone('fa-xmark', 'Fechar', '', function () { fechar(true); }));
        partes.push(cabecalho);

        if (d.estado === 'sem_dado') {
            partes.push(criar('p', 'vnd-card-aviso', 'Este dia ainda não foi coletado. Não é zero: é um dia sem informação, por isso fica fora da média e dos totais.'));
            return partes;
        }

        // ---- resumo: o que aconteceu ----
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
        if (d.veredito) {
            partes.push(criar('p', 'vnd-card-veredito vnd-card-veredito--' + d.veredito.tipo, d.veredito.texto));
        }
        if (d.aviso) {
            partes.push(criar('p', 'vnd-card-aviso vnd-card-aviso--' + d.aviso.tipo, d.aviso.texto));
        }

        // ---- os blocos, na ordem das perguntas ----
        if (d.comparacao) {
            partes.push(blocoComparacao(d.comparacao));
        }
        if (d.origens && d.origens.length) {
            partes.push(blocoOrigem(d.origens));
        }
        if (d.anuncios && d.anuncios.linhas && d.anuncios.linhas.length) {
            partes.push(blocoAnuncios(d.anuncios));
        }
        if (d.horas) {
            partes.push(blocoHoras(d.horas));
        }
        if (d.precos && (d.precos.linhas || d.precos.n_pedidos || d.cancelados)) {
            partes.push(blocoPrecos(d.precos, d.cancelados));
        }
        if (d.tem_pedidos) {
            partes.push(blocoPedidos(iso, d));
        }
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
    // * [EXPLICAÇÃO] → O painel é refeito a cada dia, então um único ouvinte no próprio card atende todos os botões "copiar" (o do MLB de cada anúncio).
    card.addEventListener('click', function (evento) {
        const botao = evento.target.closest('[data-vnd-copiar]');
        if (!botao || !card.contains(botao)) {
            return;
        }
        evento.preventDefault();
        const valor = botao.dataset.vndCopiar;
        if (!valor) {
            return;
        }
        copiarTexto(valor).then(function () {
            const icone = botao.querySelector('i');
            if (!icone) {
                return;
            }
            icone.className = 'fas fa-check';
            botao.classList.add('vnd-anu-icone--ok');
            window.setTimeout(function () {
                icone.className = 'fas fa-copy';
                botao.classList.remove('vnd-anu-icone--ok');
            }, 1200);
        }).catch(function () {
            botao.title = 'Não foi possível copiar: selecione o MLB e use Ctrl+C';
        });
    });

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
