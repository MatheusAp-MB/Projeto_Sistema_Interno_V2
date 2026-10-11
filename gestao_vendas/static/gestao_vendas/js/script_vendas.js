// gestao_vendas/static/gestao_vendas/js/script_vendas.js
//
// Tela "Vendas — Histórico de vendas". Buscar, trocar período/nível/MLB e abrir um produto são links e um formulário normais: funcionam sem este arquivo.
// Este arquivo só liga os BOTÕES DE ATUALIZAÇÃO. REGRA DO MATHEUS: a tela nunca consulta o Mercado Livre sozinha; estes são os únicos caminhos até ele,
// e todos começam num CLIQUE:
//   1) "Atualizar" de um MLB (linha da tabela "Por MLB") e 2) "Atualizar produto" (todos os MLBs do SKU) / "Reler tudo": NÃO leem o período inteiro
//      de uma vez. A tela pergunta ao servidor o PLANO (só os dias que faltam: dia já coletado completo é pulado, os últimos 30 dias são sempre
//      relidos; "Reler tudo" lê todos) — pergunta que só lê o banco — e lê o plano em TRECHOS CURTOS, vários ao mesmo tempo (CONCORRENCIA). Trecho com
//      pedidos demais volta partido do servidor e os pedaços entram na frente da fila. Um trecho que falha não impede os outros; acesso recusado para tudo.
//   3) o ícone de cada dia do calendário: coleta aquele dia da conta toda (todos os SKUs);
//   4) "Coletar período da conta": abre a janela de confirmação e, se a pessoa confirmar, o servidor coleta N dias da conta toda em segundo plano.
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
        parar: pagina.dataset.urlPeriodoParar
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

    function plural(n, singular, pluralTexto) {
        return n === 1 ? singular : pluralTexto;
    }

    function formatarNumero(n) {
        return Number(n || 0).toLocaleString('pt-BR');
    }

    function csrf() {
        const campo = document.querySelector('#vnd-csrf input[name="csrfmiddlewaretoken"]');
        return campo ? campo.value : '';
    }

    // Função Objetivo: Chama o servidor e devolve {ok, status, dados} (dados = o JSON, ou {} se a resposta não for JSON). Só rejeita se a rede falhar.
    function chamar(url, metodo, corpo) {
        const opcoes = { method: metodo, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'Accept': 'application/json' } };
        if (corpo !== undefined) {
            opcoes.headers['Content-Type'] = 'application/json';
            opcoes.body = JSON.stringify(corpo);
        }
        return fetch(url, opcoes).then(function (resposta) {
            return resposta.json().catch(function () { return {}; }).then(function (dados) {
                return { ok: resposta.ok, status: resposta.status, dados: dados };
            });
        });
    }

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
    // * [EXPLICAÇÃO] → Trechos lidos AO MESMO TEMPO. Nunca medi o limite do Mercado Livre para este endpoint (as respostas não trazem cabeçalho
    //                  de limite): se o resumo mostrar recusas (429), baixe este número para 2 ou 1.
    const CONCORRENCIA = 3;
    const ESPERA_FILA_MS = 150;

    function diasEntre(de, ate) {
        return Math.round((Date.parse(ate + 'T00:00:00Z') - Date.parse(de + 'T00:00:00Z')) / 86400000) + 1;
    }

    // Função Objetivo: Pergunta o PLANO ao servidor (só lê o banco). `mlb` vazio = todos os MLBs do SKU. Devolve (sempre) {ok, plano | mensagem}.
    function pedirPlano(mlb, tudo) {
        let url = enderecos.planejar + '?sku=' + encodeURIComponent(sku) + '&dias=' + dias;
        if (mlb) {
            url += '&mlb=' + encodeURIComponent(mlb);
        }
        if (tudo) {
            url += '&tudo=1';
        }
        return chamar(url, 'GET').then(function (resposta) {
            const dados = resposta.dados || {};
            if (!resposta.ok || !dados.ok) {
                return { ok: false, mensagem: dados.mensagem || 'Não consegui montar o plano de atualização. Tente de novo.' };
            }
            return { ok: true, plano: dados };
        }).catch(function () {
            return { ok: false, mensagem: 'Não consegui falar com o servidor. Confira a conexão e tente de novo.' };
        });
    }

    // Função Objetivo: Lê UM trecho de UM MLB. Devolve (sempre, sem rejeitar) {tipo: 'ok' | 'dividir' | 'erro', ...}. `maxPedidos` 0 = sem limite.
    function coletarTrecho(trecho, maxPedidos) {
        const corpo = { mlb: trecho.mlb, sku: sku, de: trecho.de, ate: trecho.ate };
        if (maxPedidos) {
            corpo.max_pedidos = maxPedidos;
        }
        return chamar(enderecos.mlb, 'POST', corpo).then(function (resposta) {
            const dados = resposta.dados || {};
            if (dados.dividir && dados.partes && dados.partes.length > 1) {
                return { tipo: 'dividir', partes: dados.partes };
            }
            if (!resposta.ok || !dados.ok) {
                return {
                    tipo: 'erro', erros429: dados.erros_429 || 0, interromper: Boolean(dados.interromper),
                    mensagem: dados.mensagem || 'Não consegui consultar o Mercado Livre. Tente de novo.'
                };
            }
            return { tipo: 'ok', pedidos: dados.pedidos || 0, avisos: dados.avisos || 0, erros429: dados.erros_429 || 0 };
        }).catch(function () {
            return { tipo: 'erro', erros429: 0, interromper: true, mensagem: 'Não consegui falar com o servidor. Confira a conexão e tente de novo.' };
        });
    }

    // Função Objetivo: Lê os trechos do plano, CONCORRENCIA por vez. Devolve (sem rejeitar) o balanço: {pedidos, trechos, diasFeitos, erros429, comAviso,
    //                  falhas: [{mlb, de, ate, mensagem}], parou: o MLB onde o acesso foi recusado ou a rede caiu (''), se tudo andou}.
    //                  `aoAndar(balanco)` é chamada a cada trecho que termina (a tela usa para o percentual no botão).
    function executarFila(trechos, maxPedidos, aoAndar) {
        const fila = trechos.slice();
        const balanco = { pedidos: 0, trechos: 0, diasFeitos: 0, erros429: 0, comAviso: 0, falhas: [], parou: '' };
        let ativos = 0;
        let interrompido = false;

        function trabalhador() {
            if (interrompido) {
                return Promise.resolve();
            }
            if (!fila.length) {
                // Fila vazia mas outro trecho ainda lê: ele pode devolver pedaços novos. Espera em vez de sair.
                return ativos === 0 ? Promise.resolve() : new Promise(function (r) { setTimeout(r, ESPERA_FILA_MS); }).then(trabalhador);
            }
            const trecho = fila.shift();
            ativos += 1;
            return coletarTrecho(trecho, trecho.dias > 1 ? maxPedidos : 0).then(function (r) {
                ativos -= 1;
                balanco.erros429 += r.erros429 || 0;
                if (r.tipo === 'dividir') {
                    const pedacos = r.partes.map(function (p) { return { mlb: trecho.mlb, de: p.de, ate: p.ate, dias: diasEntre(p.de, p.ate) }; });
                    Array.prototype.unshift.apply(fila, pedacos);
                } else if (r.tipo === 'ok') {
                    balanco.trechos += 1;
                    balanco.pedidos += r.pedidos;
                    balanco.diasFeitos += trecho.dias;
                    balanco.comAviso += r.avisos ? 1 : 0;
                } else {
                    balanco.falhas.push({ mlb: trecho.mlb, de: trecho.de, ate: trecho.ate, mensagem: r.mensagem });
                    if (r.interromper) {
                        interrompido = true;
                        balanco.parou = trecho.mlb;
                    }
                }
                aoAndar(balanco);
                return trabalhador();
            });
        }

        const trabalhadores = [];
        for (let i = 0; i < CONCORRENCIA; i += 1) {
            trabalhadores.push(trabalhador());
        }
        return Promise.all(trabalhadores).then(function () { return balanco; });
    }

    function dataCurta(iso) {
        return iso.slice(8, 10) + '/' + iso.slice(5, 7);
    }

    // Função Objetivo: Monta a mensagem final e, se pelo menos um trecho foi lido, recarrega a tela para ler o banco de novo.
    function finalizarAtualizacao(mlb, plano, balanco) {
        const nTrechos = balanco.trechos + ' ' + plural(balanco.trechos, 'trecho', 'trechos');
        const pulados = plano.dias_total - plano.dias_a_coletar;
        const pulou = pulados > 0 && plano.dias_total
            ? ' O que já estava coletado foi pulado (' + Math.round(100 * pulados / plano.dias_total) + '%).' : '';
        const recusas = balanco.erros429
            ? ' O Mercado Livre recusou ' + balanco.erros429 + ' ' + plural(balanco.erros429, 'chamada', 'chamadas') +
              ' por excesso (429): se isso se repetir, reduza os trechos simultâneos.' : '';
        let texto;
        let tipo = 'ok';
        if (balanco.parou) {
            const ultima = balanco.falhas[balanco.falhas.length - 1];
            texto = 'Parei no ' + balanco.parou + ' (' + nTrechos + ' lidos antes). ' + ultima.mensagem;
            tipo = 'erro';
        } else if (balanco.falhas.length) {
            const lista = balanco.falhas.slice(0, 2).map(function (f) {
                return f.mlb + ' (' + dataCurta(f.de) + ' a ' + dataCurta(f.ate) + ') — ' + f.mensagem;
            }).join(' | ');
            texto = (mlb || 'Produto') + ' atualizado em parte: ' + nTrechos + ' lidos, ' + balanco.falhas.length + ' ' +
                plural(balanco.falhas.length, 'falhou', 'falharam') + '. ' + lista +
                (balanco.falhas.length > 2 ? ' (e mais ' + (balanco.falhas.length - 2) + ')' : '') + recusas;
            tipo = 'aviso';
        } else {
            texto = (mlb || 'Produto') + ' atualizado: ' + formatarNumero(balanco.pedidos) + ' ' + plural(balanco.pedidos, 'pedido', 'pedidos') +
                ' em ' + nTrechos + '.' + pulou + recusas;
            if (balanco.comAviso || balanco.erros429) {
                tipo = 'aviso';
                if (balanco.comAviso) {
                    texto += ' Em ' + balanco.comAviso + ' ' + plural(balanco.comAviso, 'trecho', 'trechos') + ' o coletor deixou aviso (veja o terminal do servidor).';
                }
            }
        }
        if (balanco.trechos) {
            guardarAvisoERecarregar(texto, tipo);
            return;
        }
        aplicarTrava();
        avisar(texto, tipo);
    }

    // Função Objetivo: O "Atualizar" de um MLB (`mlb` preenchido) ou do produto (`mlb` vazio): plano → fila de trechos → resumo.
    function atualizar(botao, mlb, tudo) {
        operacao = true;
        aplicarTrava(botao, mlb ? '…' : 'Planejando…');
        pedirPlano(mlb, tudo).then(function (resposta) {
            if (!resposta.ok) {
                operacao = false;
                aplicarTrava();
                avisar((mlb ? mlb + ': ' : '') + resposta.mensagem, 'erro');
                return undefined;
            }
            const plano = resposta.plano;
            const trechos = plano.trechos.slice().sort(function (a, b) { return b.dias - a.dias; });
            const texto = function (balanco) {
                const pct = plano.dias_a_coletar ? Math.min(100, Math.round(100 * balanco.diasFeitos / plano.dias_a_coletar)) : 100;
                return mlb ? pct + '%' : 'Atualizando… ' + pct + '%';
            };
            aplicarTrava(botao, texto({ diasFeitos: 0 }));
            return executarFila(trechos, plano.max_pedidos, function (balanco) { aplicarTrava(botao, texto(balanco)); }).then(function (balanco) {
                operacao = false;
                finalizarAtualizacao(mlb, plano, balanco);
            });
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
        mostrar('vnd-modal-total', opcao.value);
        mostrar('vnd-modal-faltam', reler ? opcao.value : d.faltam);
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
