// gestao_vendas/static/gestao_vendas/js/script_vendas.js
//
// Tela "Vendas — Histórico de vendas". Buscar, trocar período/nível/MLB e abrir um produto são links e um formulário normais: funcionam sem este arquivo.
// Este arquivo só liga os BOTÕES DE ATUALIZAÇÃO. REGRA DO MATHEUS: a tela nunca consulta o Mercado Livre sozinha; estes são os únicos caminhos até ele,
// e todos começam num CLIQUE:
//   1) "Atualizar" de um MLB (linha da tabela "Por MLB") e 2) "Atualizar produto" (todos os MLBs do SKU) / "Reler tudo": NÃO leem o período inteiro
//      de uma vez. A tela pergunta ao servidor o PLANO (só os dias que faltam: dia já coletado completo é pulado, os últimos 30 dias são sempre
//      relidos; "Reler tudo" lê todos) — pergunta que só lê o banco — e lê o plano em TRECHOS CURTOS, vários ao mesmo tempo. Trecho com
//      pedidos demais volta partido do servidor e os pedaços entram na frente da fila. Um trecho que falha não impede os outros; acesso recusado para tudo.
//      TUDO ISSO (plano, fila, total de chamadas, resumo e guardar no banco) mora em atualizador_de_vendas.js, o MESMO que o botão "Atualizar este item" da tela
//      "Previsão de Ruptura de estoque" usa: este arquivo só cuida do botão, do aviso e do recarregamento.
//   3) o ícone de cada dia do calendário: coleta aquele dia da conta toda (todos os SKUs);
//   4) "Coletar período da conta": abre a janela de confirmação e, se a pessoa confirmar, o servidor coleta o período escolhido (por calendário) da conta toda em segundo plano.
//      A tela só pergunta o andamento a cada 2 s, mostra a barra, deixa Parar e, no fim, mostra o resumo. (Ao abrir, ela também pergunta UMA vez se já
//      existe uma coleta rodando: isso só lê o cache do servidor, não toca o Mercado Livre.)
// Depois de uma atualização que deu certo (1, 2 e 3) a tela recarrega para ler o banco de novo, e o aviso de "deu certo" aparece depois do recarregamento.

(function () {
    'use strict';

    const pagina = document.querySelector('.vnd-pagina');
    if (!pagina) {
        return;
    }

    const enderecos = {
        planejar: pagina.dataset.urlPlanejar,
        mlb: pagina.dataset.urlMlb,
        dia: pagina.dataset.urlDia,
        iniciar: pagina.dataset.urlPeriodoIniciar,
        status: pagina.dataset.urlPeriodoStatus,
        parar: pagina.dataset.urlPeriodoParar,
        execucao: pagina.dataset.urlExecucaoRegistrar
    };
    const sku = pagina.dataset.sku || '';
    const dias = parseInt(pagina.dataset.dias, 10) || 90;
    const INTERVALO_STATUS_MS = 2000;
    const SEGUNDOS_AVISO_OK = 7;
    const SEGUNDOS_AVISO_ATENCAO = 14;
    const CHAVE_AVISO = 'vnd-aviso-pendente';

    // Só UMA coisa por vez: "operacao" = um Atualizar (MLB, produto ou dia) em andamento; "coletando" = a coleta de período rodando.
    let operacao = false;
    let coletando = false;
    let temporizadorStatus = null;
    let temporizadorAviso = null;

    function porId(id) {
        return document.getElementById(id);
    }

    const plural = AtualizadorDeVendas.plural;
    const formatarNumero = AtualizadorDeVendas.formatarNumero;

    function csrf() {
        const campo = document.querySelector('#vnd-csrf input[name="csrfmiddlewaretoken"]');
        return campo ? campo.value : '';
    }

    // Função Objetivo: Chama o servidor e devolve {ok, status, dados}; é a MESMA função do orquestrador de vendas (atualizador_de_vendas.js).
    const chamar = AtualizadorDeVendas.chamador(csrf);

    // O orquestrador do "Atualizar" (plano → trechos → total de chamadas → guardar no banco) é o mesmo da tela "Previsão de Ruptura de estoque": mora em atualizador_de_vendas.js.
    const atualizador = AtualizadorDeVendas.criar({
        enderecos: { planejar: enderecos.planejar, mlb: enderecos.mlb, execucao: enderecos.execucao }, sku: sku, chamar: chamar
    });

    // ---------- aviso flutuante ----------
    const ICONES_AVISO = { ok: 'fa-circle-check', aviso: 'fa-triangle-exclamation', erro: 'fa-circle-xmark', info: 'fa-circle-info' };

    // tipo: 'ok' (some sozinho), 'aviso' (some mais devagar), 'erro' (fica até a pessoa fechar), 'info' (some sozinho)
    function avisar(texto, tipo) {
        const caixa = porId('vnd-aviso');
        if (!caixa) {
            return;
        }
        clearTimeout(temporizadorAviso);
        caixa.className = 'vnd-aviso vnd-aviso--' + tipo;
        porId('vnd-aviso-texto').textContent = texto;
        porId('vnd-aviso-icone').className = 'fas vnd-aviso-icone ' + ICONES_AVISO[tipo];
        caixa.hidden = false;
        if (tipo !== 'erro') {
            temporizadorAviso = setTimeout(function () { caixa.hidden = true; }, (tipo === 'aviso' ? SEGUNDOS_AVISO_ATENCAO : SEGUNDOS_AVISO_OK) * 1000);
        }
    }

    function fecharAviso() {
        clearTimeout(temporizadorAviso);
        const caixa = porId('vnd-aviso');
        if (caixa) {
            caixa.hidden = true;
        }
    }

    // O aviso de "deu certo" precisa sobreviver ao recarregamento da tela: fica guardado na aba (sessionStorage) até aparecer.
    function guardarAvisoERecarregar(texto, tipo) {
        try {
            sessionStorage.setItem(CHAVE_AVISO, JSON.stringify({ texto: texto, tipo: tipo }));
        } catch (erro) { /* sem sessionStorage: recarrega sem o aviso */ }
        window.location.reload();
    }

    function mostrarAvisoGuardado() {
        try {
            const bruto = sessionStorage.getItem(CHAVE_AVISO);
            if (bruto) {
                sessionStorage.removeItem(CHAVE_AVISO);
                const aviso = JSON.parse(bruto);
                avisar(aviso.texto, aviso.tipo);
            }
        } catch (erro) { /* nada guardado, ou ilegível: segue sem aviso */ }
    }

    // ---------- travas e estado dos botões ----------
    const SELETOR_BOTOES = '[data-vnd-mlb], [data-vnd-dia], [data-vnd-produto]';

    // Função Objetivo: Põe o botão em "trabalhando" (ícone girando e texto novo) ou volta ao normal. O texto de antes fica guardado no próprio botão.
    function pintarBotao(botao, trabalhando, texto) {
        const rotulo = botao.querySelector('.vnd-btn-texto');
        const icone = botao.querySelector('i');
        if (rotulo && !botao.dataset.rotulo) {
            botao.dataset.rotulo = rotulo.textContent.trim();
        }
        if (rotulo) {
            rotulo.textContent = trabalhando ? texto : botao.dataset.rotulo;
        }
        if (icone) {
            icone.classList.toggle('fa-spin', trabalhando);
        }
        botao.classList.toggle('vnd-btn--ocupado', trabalhando);
    }

    // Função Objetivo: Acerta TODOS os botões de atualizar (e o do período) conforme o que está rodando. O botão que está trabalhando mantém o texto
    //                  e o ícone girando; os outros só ficam desabilitados.
    function aplicarTrava(ativo, texto) {
        const bloqueado = operacao || coletando;
        pagina.querySelectorAll(SELETOR_BOTOES).forEach(function (botao) {
            const semMlb = botao.hasAttribute('data-vnd-produto') && botao.dataset.semMlb === '1';
            botao.disabled = bloqueado || semMlb;
            pintarBotao(botao, botao === ativo, texto);
        });
        const periodo = porId('vnd-btn-periodo');
        if (periodo) {
            periodo.disabled = bloqueado;
        }
    }

    // ---------- atualizar um MLB / um dia / um produto ----------
    // Função Objetivo: O "Atualizar" de um MLB (`mlb` preenchido) ou do produto (`mlb` vazio): o orquestrador faz plano → fila de trechos → resumo → guarda no banco;
    //                  aqui só se cuida do botão (percentual) e, no fim, do aviso e do recarregamento.
    function atualizar(botao, mlb, tudo) {
        operacao = true;
        aplicarTrava(botao, mlb ? '…' : 'Planejando…');
        atualizador.atualizar({
            mlbs: mlb ? [mlb] : [], dias: dias, tudo: tudo, tipo: mlb ? 'mlb' : 'produto', rotulo: mlb || 'Produto',
            aoAndar: function (pct) { aplicarTrava(botao, mlb ? pct + '%' : 'Atualizando… ' + pct + '%'); }
        }).then(function (r) {
            operacao = false;
            if (!r.ok) {
                aplicarTrava();
                avisar((mlb ? mlb + ': ' : '') + r.mensagem, 'erro');
                return;
            }
            if (r.trechos) {
                guardarAvisoERecarregar(r.texto, r.tipo);
                return;
            }
            aplicarTrava();
            avisar(r.texto, r.tipo);
        });
    }

    function atualizarUmMlb(botao) {
        atualizar(botao, botao.dataset.vndMlb, false);
    }

    function atualizarUmDia(botao) {
        const dia = botao.dataset.vndDia;
        operacao = true;
        aplicarTrava(botao, '');
        chamar(enderecos.dia, 'POST', { dia: dia }).then(function (resposta) {
            const dados = resposta.dados || {};
            operacao = false;
            if (!resposta.ok || !dados.ok) {
                aplicarTrava();
                avisar('Dia ' + dia + ': ' + (dados.mensagem || 'Não consegui consultar o Mercado Livre. Tente de novo.'), 'erro');
                return;
            }
            guardarAvisoERecarregar(dados.mensagem, dados.avisos ? 'aviso' : 'ok');
        }).catch(function () {
            operacao = false;
            aplicarTrava();
            avisar('Não consegui falar com o servidor. Confira a conexão e tente de novo.', 'erro');
        });
    }

    // O produto: todos os MLBs do SKU (o servidor sabe quais). `tudo` = "Reler tudo": ignora o que já está coletado.
    function atualizarUmProduto(botao) {
        atualizar(botao, '', botao.dataset.vndProduto === 'tudo');
    }

    pagina.addEventListener('click', function (evento) {
        const botao = evento.target.closest(SELETOR_BOTOES);
        if (!botao || !pagina.contains(botao) || botao.disabled || operacao || coletando) {
            return;
        }
        fecharAviso();
        if (botao.hasAttribute('data-vnd-produto')) {
            atualizarUmProduto(botao);
        } else if (botao.hasAttribute('data-vnd-dia')) {
            atualizarUmDia(botao);
        } else {
            atualizarUmMlb(botao);
        }
    });

    // ---------- coleta de período da conta ----------
    function esconderPeriodo() {
        porId('vnd-periodo').hidden = true;
    }

    // "faltam cerca de 8 min" — estimado pelo ritmo até agora; só aparece depois de uns dias, para não chutar com pouco dado.
    function textoDeFaltam(estado) {
        const feitos = (estado.atual || 1) - 1;
        const decorrido = estado.decorrido || 0;
        if (feitos < 3 || decorrido < 10 || !estado.total) {
            return '';
        }
        const minutos = Math.ceil(((decorrido / feitos) * (estado.total - feitos)) / 60);
        if (minutos <= 1) {
            return 'falta menos de 1 min';
        }
        if (minutos < 90) {
            return 'faltam cerca de ' + minutos + ' min';
        }
        return 'faltam cerca de ' + Math.floor(minutos / 60) + ' h ' + (minutos % 60) + ' min';
    }

    function mostrarProgresso(estado) {
        const total = estado.total || 0;
        const atual = estado.atual || 0;
        porId('vnd-periodo-rotulo').textContent = estado.rotulo || 'Consultando o Mercado Livre';
        const partes = [];
        if (total) {
            partes.push('dia ' + formatarNumero(atual) + ' de ' + formatarNumero(total));
        }
        if (estado.dia) {
            partes.push(estado.dia);
        }
        partes.push(formatarNumero(estado.pedidos) + ' ' + plural(estado.pedidos, 'pedido', 'pedidos'));
        partes.push(formatarNumero(estado.chamadas) + ' ' + plural(estado.chamadas, 'chamada', 'chamadas'));
        if (estado.erros_429) {
            partes.push(estado.erros_429 + ' recusa' + (estado.erros_429 === 1 ? '' : 's') + ' (429)');
        }
        porId('vnd-periodo-numeros').textContent = partes.join(' · ');
        const barra = porId('vnd-periodo-barra');
        if (total) {
            barra.max = total;
            barra.value = Math.max(atual - 1, 0);
        } else {
            barra.removeAttribute('value');
        }
        const faltam = textoDeFaltam(estado);
        porId('vnd-periodo-dica').textContent = (faltam ? faltam + '. ' : '') +
            'Você pode continuar nesta tela; os botões de atualizar ficam bloqueados até terminar.';
        porId('vnd-periodo-parar').disabled = Boolean(estado.parando);
        porId('vnd-periodo').hidden = false;
        porId('vnd-resultado').hidden = true;
    }

    function mostrarResultado(estado) {
        const caixa = porId('vnd-resultado');
        let tipo = 'ok';
        if (estado.status === 'erro') {
            tipo = 'erro';
        } else if (estado.com_aviso || estado.interrompida || estado.completa === false) {
            tipo = 'atencao';
        }
        caixa.className = 'vnd-resultado vnd-resultado--' + tipo;
        porId('vnd-resultado-icone').className = 'fas vnd-resultado-icone ' + { ok: 'fa-circle-check', atencao: 'fa-triangle-exclamation', erro: 'fa-circle-xmark' }[tipo];
        const aviso = estado.status === 'concluido' && estado.pedidos ? ' A tela abaixo ainda mostra os números de antes: clique em Recarregar a tela.' : '';
        porId('vnd-resultado-texto').textContent = (estado.mensagem || '') + aviso;
        caixa.hidden = false;
    }

    function agendarStatus() {
        clearTimeout(temporizadorStatus);
        temporizadorStatus = setTimeout(perguntarStatus, INTERVALO_STATUS_MS);
    }

    // Função Objetivo: Pergunta ao servidor como está a coleta e acerta a tela: rodando = barra e travas; terminou/erro = resumo; nada = limpa.
    function perguntarStatus() {
        return chamar(enderecos.status, 'GET').then(function (resposta) {
            const estado = resposta.dados || {};
            if (estado.status === 'rodando') {
                coletando = true;
                aplicarTrava();
                mostrarProgresso(estado);
                agendarStatus();
                return;
            }
            const estavaColetando = coletando;
            coletando = false;
            aplicarTrava();
            esconderPeriodo();
            if (estado.status === 'concluido' || estado.status === 'erro') {
                mostrarResultado(estado);
            } else if (estavaColetando) {
                avisar('A coleta terminou, mas não consegui ler o resultado. Recarregue a tela.', 'aviso');
            }
        }).catch(function () {
            // Sem conexão com o servidor: a coleta continua lá; a tela tenta de novo em vez de dá-la por perdida.
            if (coletando) {
                porId('vnd-periodo-dica').textContent = 'Perdi a conexão com o servidor; tentando de novo… (a coleta continua rodando lá).';
                agendarStatus();
            }
        });
    }

    // Função Objetivo: Mostra na janela do período a estimativa da opção escolhida: só o que falta, ou tudo se "Reler também" estiver marcado.
    function atualizarEstimativa() {
        const seletor = porId('vnd-modal-dias');
        if (!seletor || !porId('vnd-modal-chamadas')) {
            return;
        }
        const opcao = seletor.options[seletor.selectedIndex];
        const reler = Boolean(porId('vnd-modal-reler') && porId('vnd-modal-reler').checked);
        const mostrar = function (id, valor) { porId(id).textContent = valor === undefined ? '—' : formatarNumero(valor); };
        if (!opcao) {
            ['vnd-modal-faltam', 'vnd-modal-total', 'vnd-modal-chamadas', 'vnd-modal-minutos'].forEach(function (id) { mostrar(id); });
            return;
        }
        const d = opcao.dataset;
        // value = dias PARA TRÁS de hoje (o que o servidor recebe); data-total = dias de calendário do período (esse mais hoje).
        const total = d.total !== undefined ? d.total : opcao.value;
        mostrar('vnd-modal-total', total);
        mostrar('vnd-modal-faltam', reler ? total : d.faltam);
        mostrar('vnd-modal-chamadas', reler ? d.chamadasTudo : d.chamadas);
        mostrar('vnd-modal-minutos', reler ? d.minutosTudo : d.minutos);
    }

    function fecharJanelaDeConfirmacao() {
        const elemento = porId('vnd-modal-periodo');
        const janela = elemento && window.bootstrap ? window.bootstrap.Modal.getInstance(elemento) : null;
        if (janela) {
            janela.hide();
        }
    }

    function confirmarColeta() {
        const botao = porId('vnd-modal-confirmar');
        const escolhidos = parseInt(porId('vnd-modal-dias').value, 10) || 90;
        botao.disabled = true;
        const reler = Boolean(porId('vnd-modal-reler') && porId('vnd-modal-reler').checked);
        chamar(enderecos.iniciar, 'POST', { dias: escolhidos, reler_tudo: reler }).then(function (resposta) {
            fecharJanelaDeConfirmacao();
            const estado = resposta.dados || {};
            if (!resposta.ok || estado.status !== 'rodando') {
                avisar(estado.mensagem || 'Não consegui começar a coleta. Tente de novo.', 'erro');
                return;
            }
            coletando = true;
            aplicarTrava();
            mostrarProgresso(estado);
            agendarStatus();
        }).catch(function () {
            fecharJanelaDeConfirmacao();
            avisar('Não consegui falar com o servidor. Confira a conexão e tente de novo.', 'erro');
        }).then(function () {
            botao.disabled = false;
        });
    }

    function pararColeta() {
        const botao = porId('vnd-periodo-parar');
        botao.disabled = true;
        chamar(enderecos.parar, 'POST', {}).then(function (resposta) {
            const estado = resposta.dados || {};
            if (estado.status === 'rodando') {
                mostrarProgresso(estado);
            }
            // Se já tinha terminado (status "ocioso"), a próxima pergunta de status mostra o resultado.
            perguntarStatus();
        }).catch(function () {
            botao.disabled = false;
            avisar('Não consegui falar com o servidor para parar a coleta. Tente de novo.', 'erro');
        });
    }

    // ---------- ligações ----------
    const seletorDias = porId('vnd-modal-dias');
    if (seletorDias) {
        seletorDias.addEventListener('change', atualizarEstimativa);
        const marcarReler = porId('vnd-modal-reler');
        if (marcarReler) {
            marcarReler.addEventListener('change', atualizarEstimativa);
        }
        atualizarEstimativa();
    }
    const confirmar = porId('vnd-modal-confirmar');
    if (confirmar) {
        confirmar.addEventListener('click', confirmarColeta);
    }
    const parar = porId('vnd-periodo-parar');
    if (parar) {
        parar.addEventListener('click', pararColeta);
    }
    const recarregar = porId('vnd-resultado-recarregar');
    if (recarregar) {
        recarregar.addEventListener('click', function () { window.location.reload(); });
    }
    const fecharResultado = porId('vnd-resultado-fechar');
    if (fecharResultado) {
        fecharResultado.addEventListener('click', function () { porId('vnd-resultado').hidden = true; });
    }
    const fecharAvisoBotao = porId('vnd-aviso-fechar');
    if (fecharAvisoBotao) {
        fecharAvisoBotao.addEventListener('click', fecharAviso);
    }

    // "Atualizar produto" sem nenhum MLB no banco: o botão já nasce desabilitado (o servidor marca com disabled); a trava mantém assim.
    pagina.querySelectorAll('[data-vnd-produto][disabled]').forEach(function (botao) { botao.dataset.semMlb = '1'; });

    mostrarAvisoGuardado();
    // Ao abrir a tela: já existe uma coleta rodando (começada antes, em outra aba, ou antes de recarregar)? Só pergunta ao servidor (cache).
    if (porId('vnd-periodo')) {
        perguntarStatus();
    }
})();
