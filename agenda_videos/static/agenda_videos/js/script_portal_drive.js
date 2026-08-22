// agenda_videos/static/agenda_videos/js/script_portal_drive.js
//
// * [RESUMO] → Portal do Drive: seleção de arquivo por clique OU arraste,
// preview LOCAL do arquivo escolhido antes de qualquer envio (vídeo
// tocável ou texto legível, com nome/duração/tamanho lidos no navegador),
// contagem do lote selecionado, barra de progresso real durante o envio,
// fechamento do modal de confirmação de exclusão, o toggle "mostrar mais"
// da ocorrência extra do Vídeo Trimestral, o accordion exclusivo entre
// produtos da lista (20/08/2026: tela virou lista de TODOS os produtos —
// só 1 fica aberto/carregado por vez, fechar 1 sempre limpa o conteúdo
// dele da DOM, pra nunca ter 2 #portal-drive-card ao mesmo tempo), e a
// barra de progresso real do botão "Sincronizar com o Drive" (21/08/2026:
// antes era um POST comum sem feedback nenhum — agora dispara a
// sincronização via fetch e acompanha o progresso por polling de status).
// Delegação de evento no document, sem onclick inline.

document.addEventListener('click', function (evento) {
    if (evento.target.closest('.portal-drive-remover-selecao')) return;

    var cartao = evento.target.closest('.portal-drive-filecard');
    if (!cartao) return;
    if (cartao.classList.contains('portal-drive-filecard--presente')) return;
    if (cartao.classList.contains('portal-drive-filecard--selecionado')) return;

    var input = cartao.querySelector('.portal-drive-input-arquivo');
    if (input) input.click();
});

document.addEventListener('change', function (evento) {
    if (!evento.target.classList.contains('portal-drive-input-arquivo')) return;

    var cartao = evento.target.closest('.portal-drive-filecard');
    var arquivo = evento.target.files[0];
    if (arquivo) marcarArquivoSelecionado(cartao, arquivo);
});

document.addEventListener('click', function (evento) {
    var botaoRemover = evento.target.closest('.portal-drive-remover-selecao');
    if (!botaoRemover) return;
    evento.stopPropagation();

    limparArquivoSelecionado(botaoRemover.closest('.portal-drive-filecard'));
});

// Função Objetivo: Marca o cartão como "selecionado", garante que o
// arquivo esteja dentro do <input> escondido e dispara o preview local.
function marcarArquivoSelecionado(cartao, arquivo) {
    var input = cartao.querySelector('.portal-drive-input-arquivo');

    if (!input.files.length || input.files[0] !== arquivo) {
        var transferencia = new DataTransfer();
        transferencia.items.add(arquivo);
        input.files = transferencia.files;
    }

    cartao.classList.add('portal-drive-filecard--selecionado');
    cartao.querySelector('.portal-drive-remover-selecao').hidden = false;

    var pill = cartao.querySelector('.portal-drive-pill-estado');
    pill.classList.remove('video-nao-gerado');
    pill.classList.add('portal-drive-pill-estado--selecionado');
    pill.textContent = 'selecionado';

    mostrarPreviewLocal(cartao, arquivo);
    atualizarContadorEnvio();
}

function limparArquivoSelecionado(cartao) {
    var input = cartao.querySelector('.portal-drive-input-arquivo');
    input.value = '';

    limparPreviewLocal(cartao);
    cartao.classList.remove('portal-drive-filecard--selecionado');
    cartao.querySelector('.portal-drive-remover-selecao').hidden = true;

    var dadosUpload = cartao.querySelector('.portal-drive-dados-upload');
    if (dadosUpload) dadosUpload.hidden = true;

    var pill = cartao.querySelector('.portal-drive-pill-estado');
    pill.classList.remove('portal-drive-pill-estado--selecionado');
    pill.classList.add('video-nao-gerado');
    pill.textContent = 'selecione ou arraste';

    atualizarContadorEnvio();
}

// Função Objetivo: Mostra uma prévia REAL do arquivo escolhido — vídeo
// tocável (Base/Completo) via URL.createObjectURL, ou texto legível
// (Roteiro) via FileReader — e preenche nome/duração/tamanho, tudo lido
// no navegador, sem gastar nenhuma chamada de rede.
function mostrarPreviewLocal(cartao, arquivo) {
    var thumb = cartao.querySelector('.portal-drive-thumb');
    limparPreviewLocal(cartao);

    var dadosUpload = cartao.querySelector('.portal-drive-dados-upload');
    var linhaNome = cartao.querySelector('.portal-drive-dados-nome');
    var linhaDuracaoTamanho = cartao.querySelector('.portal-drive-dados-duracao-tamanho');
    var tamanhoTexto = formatarTamanhoArquivo(arquivo.size);

    if (dadosUpload) dadosUpload.hidden = false;
    if (linhaNome) linhaNome.textContent = arquivo.name;
    if (linhaDuracaoTamanho) linhaDuracaoTamanho.textContent = tamanhoTexto;

    var ehTexto = arquivo.name.toLowerCase().endsWith('.txt');

    if (ehTexto) {
        var leitor = new FileReader();
        leitor.onload = function () {
            var caixaTexto = document.createElement('div');
            caixaTexto.className = 'portal-drive-preview-texto';
            caixaTexto.textContent = leitor.result;
            thumb.innerHTML = '';
            thumb.appendChild(caixaTexto);
        };
        leitor.readAsText(arquivo);
        return;
    }

    var url = URL.createObjectURL(arquivo);
    var player = criarPlayerLocal(url);
    var video = player.querySelector('.portal-drive-preview-video');
    video.addEventListener('loadedmetadata', function () {
        if (linhaDuracaoTamanho) {
            linhaDuracaoTamanho.textContent = formatarDuracao(video.duration) + ' · ' + tamanhoTexto;
        }
    });
    thumb.innerHTML = '';
    thumb.appendChild(player);
}

// Função Objetivo: Monta o player local (vídeo + barra de controles
// própria) — play/pausar, tempo atual, linha do tempo arrastável, mudo/
// áudio e tela cheia. Visual fixo do sistema, nunca depende dos controles
// nativos do navegador (que variam e escondiam a tela cheia atrás de um
// menu).
function criarPlayerLocal(url) {
    var container = document.createElement('div');
    container.className = 'portal-drive-player';

    var video = document.createElement('video');
    video.className = 'portal-drive-preview-video';
    video.src = url;
    video.playsInline = true;
    video.preload = 'metadata';
    video.dataset.objectUrl = url;

    var controles = document.createElement('div');
    controles.className = 'portal-drive-player-controles';
    controles.innerHTML =
        '<button type="button" class="portal-drive-player-botao" data-acao="play-pause"><i class="fas fa-play"></i></button>' +
        '<span class="portal-drive-player-tempo">0:00</span>' +
        '<input type="range" class="portal-drive-player-progresso" min="0" max="100" value="0" step="0.1">' +
        '<button type="button" class="portal-drive-player-botao" data-acao="volume"><i class="fas fa-volume-high"></i></button>' +
        '<button type="button" class="portal-drive-player-botao" data-acao="tela-cheia"><i class="fas fa-expand"></i></button>';

    container.appendChild(video);
    container.appendChild(controles);
    return container;
}

function alternarReproducao(video) {
    if (video.paused) { video.play(); } else { video.pause(); }
}

document.addEventListener('click', function (evento) {
    var botao = evento.target.closest('[data-acao="play-pause"]');
    if (!botao) return;
    alternarReproducao(botao.closest('.portal-drive-player').querySelector('.portal-drive-preview-video'));
});


// * [EXPLICAÇÃO] → play/pause/timeupdate não sobem (bubble) sozinhos —
// por isso o listener vai no capture (3º argumento true), pego lá em
// cima no document, e filtra pelo próprio vídeo que disparou.
document.addEventListener('play', function (evento) {
    if (!evento.target.classList || !evento.target.classList.contains('portal-drive-preview-video')) return;
    evento.target.closest('.portal-drive-player').querySelector('[data-acao="play-pause"] i').className = 'fas fa-pause';
}, true);

document.addEventListener('pause', function (evento) {
    if (!evento.target.classList || !evento.target.classList.contains('portal-drive-preview-video')) return;
    evento.target.closest('.portal-drive-player').querySelector('[data-acao="play-pause"] i').className = 'fas fa-play';
}, true);

document.addEventListener('timeupdate', function (evento) {
    if (!evento.target.classList || !evento.target.classList.contains('portal-drive-preview-video')) return;
    var video = evento.target;
    if (!video.duration) return;

    var player = video.closest('.portal-drive-player');
    var barra = player.querySelector('.portal-drive-player-progresso');
    var tempo = player.querySelector('.portal-drive-player-tempo');

    if (!barra.matches(':active')) {
        barra.value = (video.currentTime / video.duration) * 100;
    }
    tempo.textContent = formatarDuracao(video.currentTime);
}, true);

document.addEventListener('input', function (evento) {
    if (!evento.target.classList.contains('portal-drive-player-progresso')) return;
    var barra = evento.target;
    var video = barra.closest('.portal-drive-player').querySelector('.portal-drive-preview-video');
    if (!video.duration) return;
    video.currentTime = (barra.value / 100) * video.duration;
});

function alternarMudo(player) {
    var video = player.querySelector('.portal-drive-preview-video');
    video.muted = !video.muted;
    var icone = player.querySelector('[data-acao="volume"] i');
    if (icone) icone.className = video.muted ? 'fas fa-volume-xmark' : 'fas fa-volume-high';
}

document.addEventListener('click', function (evento) {
    var botao = evento.target.closest('[data-acao="volume"]');
    if (!botao) return;
    alternarMudo(botao.closest('.portal-drive-player'));
});

// * [EXPLICAÇÃO] → Atalhos de teclado (F/M/Espaço) — como pode haver vários
// cartões selecionados ao mesmo tempo na tela, obterPlayerAtivo() decide
// qual vídeo a tecla controla: o que estiver em tela cheia (se houver),
// senão o que o mouse estiver sobrevoando. Ignora teclas enquanto o foco
// está num campo de texto, pra nunca atrapalhar digitação em outro lugar
// da tela.
function obterPlayerAtivo() {
    if (document.fullscreenElement && document.fullscreenElement.classList.contains('portal-drive-player')) {
        return document.fullscreenElement;
    }
    return document.querySelector('.portal-drive-player:hover');
}

document.addEventListener('keydown', function (evento) {
    var elementoAtivo = document.activeElement;
    if (elementoAtivo && (elementoAtivo.tagName === 'INPUT' || elementoAtivo.tagName === 'TEXTAREA' || elementoAtivo.isContentEditable)) return;

    var player = obterPlayerAtivo();
    if (!player) return;

    var lidou = true;
    if (evento.code === 'Space') {
        alternarReproducao(player.querySelector('.portal-drive-preview-video'));
    } else if (evento.key === 'f' || evento.key === 'F') {
        alternarTelaCheia(player);
    } else if (evento.key === 'm' || evento.key === 'M') {
        alternarMudo(player);
    } else {
        lidou = false;
    }

    if (!lidou) return;
    evento.preventDefault();

    if (document.fullscreenElement === player) {
        player.classList.add('portal-drive-player--mostrar-controles');
        agendarOcultarControlesTelaCheia(player);
    }
});

function alternarTelaCheia(player) {
    if (document.fullscreenElement === player) {
        document.exitFullscreen();
    } else {
        player.requestFullscreen();
    }
}

document.addEventListener('click', function (evento) {
    var botao = evento.target.closest('[data-acao="tela-cheia"]');
    if (!botao) return;
    alternarTelaCheia(botao.closest('.portal-drive-player'));
});

var temporizadorControlesTelaCheia = null;

// Função Objetivo: Agenda esconder os controles depois de um tempo parado
// — chamada de novo (reiniciando o relógio) toda vez que o mouse se mexe
// enquanto em tela cheia.
function agendarOcultarControlesTelaCheia(player) {
    clearTimeout(temporizadorControlesTelaCheia);
    temporizadorControlesTelaCheia = setTimeout(function () {
        player.classList.remove('portal-drive-player--mostrar-controles');
    }, 500);
}

document.addEventListener('fullscreenchange', function () {
    document.querySelectorAll('.portal-drive-player [data-acao="tela-cheia"] i').forEach(function (icone) {
        var estaCheia = document.fullscreenElement && document.fullscreenElement.contains(icone);
        icone.className = estaCheia ? 'fas fa-compress' : 'fas fa-expand';
    });

    clearTimeout(temporizadorControlesTelaCheia);
    var playerAnterior = document.querySelector('.portal-drive-player--mostrar-controles');
    if (playerAnterior) playerAnterior.classList.remove('portal-drive-player--mostrar-controles');

    if (document.fullscreenElement && document.fullscreenElement.classList.contains('portal-drive-player')) {
        document.fullscreenElement.classList.add('portal-drive-player--mostrar-controles');
        agendarOcultarControlesTelaCheia(document.fullscreenElement);
    }
});

document.addEventListener('mousemove', function () {
    var player = document.fullscreenElement;
    if (!player || !player.classList.contains('portal-drive-player')) return;
    player.classList.add('portal-drive-player--mostrar-controles');
    agendarOcultarControlesTelaCheia(player);
});

function limparPreviewLocal(cartao) {
    var thumb = cartao.querySelector('.portal-drive-thumb');
    var videoAntigo = thumb.querySelector('.portal-drive-preview-video');
    if (videoAntigo && videoAntigo.dataset.objectUrl) {
        URL.revokeObjectURL(videoAntigo.dataset.objectUrl);
    }
    thumb.innerHTML = '<div class="portal-drive-thumb-vazio"><i class="fas fa-plus"></i><span>Selecionar ou arrastar</span></div>';
}

function formatarTamanhoArquivo(bytes) {
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatarDuracao(segundosTotais) {
    var minutos = Math.floor(segundosTotais / 60);
    var segundos = Math.round(segundosTotais % 60);
    return minutos + ':' + (segundos < 10 ? '0' : '') + segundos;
}

function atualizarContadorEnvio() {
    var botao = document.getElementById('portal-drive-btn-enviar');
    if (!botao) return;

    var selecionados = document.querySelectorAll('.portal-drive-filecard--selecionado').length;
    botao.disabled = selecionados === 0;
    botao.querySelector('.portal-drive-contador-selecionados').textContent = selecionados;
}

document.addEventListener('dragover', function (evento) {
    if (!evento.target.closest('#portal-drive-lista-fases')) return;
    evento.preventDefault();

    var cartao = evento.target.closest('.portal-drive-filecard:not(.portal-drive-filecard--presente)');
    if (cartao) cartao.classList.add('portal-drive-filecard--sobre-arraste');
});

document.addEventListener('dragleave', function (evento) {
    var cartao = evento.target.closest('.portal-drive-filecard');
    if (cartao) cartao.classList.remove('portal-drive-filecard--sobre-arraste');
});

document.addEventListener('drop', function (evento) {
    if (!evento.target.closest('#portal-drive-lista-fases')) return;
    evento.preventDefault();

    var cartao = evento.target.closest('.portal-drive-filecard:not(.portal-drive-filecard--presente)');
    if (!cartao) return;

    cartao.classList.remove('portal-drive-filecard--sobre-arraste');
    var arquivo = evento.dataTransfer.files[0];
    if (arquivo) marcarArquivoSelecionado(cartao, arquivo);
});

document.body.addEventListener('htmx:beforeRequest', function (evento) {
    if (!evento.target.closest('.portal-drive-form-envio')) return;

    var progresso = document.querySelector('.portal-drive-progresso');
    if (progresso) {
        progresso.hidden = false;
        progresso.querySelector('.portal-drive-progresso-barra').value = 0;
        progresso.querySelector('.portal-drive-progresso-texto').textContent = 'Enviando arquivos... 0%';
    }
});

document.body.addEventListener('htmx:xhr:progress', function (evento) {
    if (!evento.detail.total) return;

    var progresso = document.querySelector('.portal-drive-progresso');
    if (!progresso) return;

    var percentual = Math.round((evento.detail.loaded / evento.detail.total) * 100);
    progresso.querySelector('.portal-drive-progresso-barra').value = percentual;
    progresso.querySelector('.portal-drive-progresso-texto').textContent = 'Enviando arquivos... ' + percentual + '%';
});

// Função Objetivo: Fecha o modal de confirmação de exclusão ao clicar em
// "Cancelar" ou no fundo escurecido — mesmo padrão do modal real de
// roadmap (script_roadmap_produto.js).
document.body.addEventListener('click', function (evento) {
    if (evento.target.matches('[data-fechar-modal-portal-drive]')) {
        document.getElementById('modal-portal-drive-slot').innerHTML = '';
    }
});

document.addEventListener('click', function (evento) {
    var botao = evento.target.closest('.portal-drive-botao-mostrar-mais');
    if (!botao) return;

    document.querySelectorAll('.portal-drive-linhas-extra').forEach(function (bloco) {
        bloco.hidden = false;
    });
    botao.hidden = true;
});

// Função Objetivo: Accordion exclusivo entre produtos da lista — só 1
// produto fica aberto (e carregado) por vez. Abrir 1 fecha os outros;
// fechar qualquer 1 (por essa ação ou clicando de novo nele mesmo) limpa
// o conteúdo carregado dele da DOM, garantindo que #portal-drive-card,
// #portal-drive-btn-enviar etc. nunca existam em duplicidade na página.
// * [EXPLICAÇÃO] → o evento `toggle` do <details> não borbulha (bubble)
// na maioria dos navegadores — por isso o listener vai direto no
// document com capture (3º argumento true), que pega o evento na
// descida, antes dele "morrer" no próprio elemento.
document.addEventListener('toggle', function (evento) {
    var detalhe = evento.target;
    if (!detalhe.matches || !detalhe.matches('.portal-drive-produto-linha')) return;

    if (!detalhe.open) {
        // * [EXPLICAÇÃO] → Só limpa (e força recarregar depois) quando o
        //                  fechamento foi por causa de OUTRO produto ter
        //                  aberto — continua sendo obrigatório nesse caso,
        //                  senão o card antigo e o novo ficam com IDs
        //                  duplicados (#portal-drive-card) ao mesmo tempo
        //                  na DOM. Fechar manualmente o MESMO produto (sem
        //                  abrir outro) preserva o conteúdo já carregado,
        //                  pra reabrir instantâneo, sem "piscar" o
        //                  placeholder de novo (20/08/2026).
        var outroAberto = document.querySelector('.portal-drive-produto-linha[open]');
        if (outroAberto && outroAberto !== detalhe) {
            var conteudo = detalhe.querySelector('.portal-drive-produto-conteudo');
            if (conteudo) {
                conteudo.innerHTML = '<p class="portal-drive-carregando-texto"><i class="fas fa-spinner fa-spin"></i> Carregando dados do Drive...</p>';
            }
            delete detalhe.dataset.carregado;
        }
        return;
    }

    document.querySelectorAll('.portal-drive-produto-linha[open]').forEach(function (outro) {
        if (outro !== detalhe) outro.open = false;
    });

    // * [EXPLICAÇÃO] → Reabertura do MESMO produto sem fetch novo (conteúdo
    //                  já em cache — ver hx-trigger no template) não passa
    //                  por htmx:afterSwap, então precisa forçar aqui
    //                  também; senão a etapa atual fica travada no estado
    //                  (aberta/fechada) em que a pessoa deixou da última vez.
    if (detalhe.dataset.carregado) forcarAberturaEtapaAtual(detalhe);
}, true);

// * [EXPLICAÇÃO] → Marca o produto como "já carregado" depois do 1º swap
//                  bem-sucedido — o hx-trigger do <details> (ver template)
//                  usa esse marcador pra pular a requisição inteira numa
//                  reabertura do MESMO produto, não só evitar o placeholder.
document.body.addEventListener('htmx:afterSwap', function (evento) {
    var detalhe = evento.target.closest && evento.target.closest('.portal-drive-produto-linha');
    if (!detalhe) return;
    detalhe.dataset.carregado = '1';
    forcarAberturaEtapaAtual(detalhe);
});

// Função Objetivo: Garante que a seção da etapa atual (destacada com borda,
// ver _montar_contexto_card/linha.atual em views.py) sempre venha aberta
// quando o produto é exibido — tanto na 1ª carga real (htmx:afterSwap,
// acima) quanto ao reabrir o MESMO produto sem fetch novo (ver o listener
// de "toggle" do accordion exclusivo, mais acima no arquivo).
function forcarAberturaEtapaAtual(detalheProduto) {
    var linhaAtual = detalheProduto.querySelector('.portal-drive-linha-fase--atual');
    if (linhaAtual) linhaAtual.open = true;
}


// * [EXPLICAÇÃO] → Todo duplo-clique dispara 2 "click" + 1 "dblclick" — o
// navegador não cancela os cliques simples sozinho. Por isso o clique
// simples espera 250ms antes de executar de verdade: se um 2º clique
// chegar antes disso (virou duplo-clique), cancela o pausar/despausar e
// deixa só o dblclick (tela cheia) acontecer — mesmo truque do YouTube.
var temporizadorCliqueVideo = null;

document.addEventListener('click', function (evento) {
    if (!evento.target.classList.contains('portal-drive-preview-video')) return;
    var video = evento.target;

    if (temporizadorCliqueVideo) {
        clearTimeout(temporizadorCliqueVideo);
        temporizadorCliqueVideo = null;
        return;
    }

    temporizadorCliqueVideo = setTimeout(function () {
        temporizadorCliqueVideo = null;
        alternarReproducao(video);
    }, 250);
});

document.addEventListener('dblclick', function (evento) {
    if (!evento.target.classList.contains('portal-drive-preview-video')) return;
    clearTimeout(temporizadorCliqueVideo);
    temporizadorCliqueVideo = null;
    alternarTelaCheia(evento.target.closest('.portal-drive-player'));
});


// Função Objetivo: Intercepta o submit do botão "Sincronizar com o Drive"
// (já depois do confirm() aceito) — em vez de deixar o navegador fazer um
// POST comum (trava a tela até a resposta inteira do servidor voltar, sem
// nenhum feedback visual no meio do caminho), dispara a sincronização via
// fetch e passa a consultar o status por polling. A sincronização real
// roda numa thread em background no servidor (ver
// view_portal_drive_sincronizar/_rodar_sincronizacao_portal_drive_em_thread
// em views.py) — o servidor responde na hora, sem esperar ela terminar.
var formSincronizarDrive = document.getElementById('portal-drive-form-sincronizar');
if (formSincronizarDrive) {
    formSincronizarDrive.addEventListener('submit', function (evento) {
        evento.preventDefault();
        iniciarSincronizacaoDrive(formSincronizarDrive);
    });
}

function iniciarSincronizacaoDrive(form) {
    var botao = form.querySelector('.portal-drive-btn-sincronizar');
    var progresso = document.querySelector('.portal-drive-sincronizar-progresso');

    botao.disabled = true;
    botao.classList.add('portal-drive-sincronizando');
    progresso.hidden = false;
    atualizarBarraSincronizacaoDrive(progresso, 'iniciando', 0, null);

    fetch(form.action, { method: 'POST', body: new FormData(form) })
        .then(function (resposta) {
            if (!resposta.ok) throw new Error('Falha ao iniciar a sincronização.');
            consultarStatusSincronizacaoDrive(form, botao, progresso, 0);
        })
        .catch(function () {
            alert('Não foi possível iniciar a sincronização — tenta de novo.');
            botao.disabled = false;
            botao.classList.remove('portal-drive-sincronizando');
            progresso.hidden = true;
        });
}

// Função Objetivo: Consulta o status a cada 1s — se ainda está rodando,
// atualiza a barra e agenda a próxima consulta; se terminou (concluído ou
// erro), recarrega a tela pra mostrar a mensagem final (montada pelo
// Django messages framework no próximo GET, ver view_portal_drive) e os
// dados atualizados da lista. `falhasConsecutivas` limita a tentativa de
// novo em caso de instabilidade de rede — depois de 10 falhas em sequência
// (~10s), desiste e avisa, em vez de tentar pra sempre em silêncio.
function consultarStatusSincronizacaoDrive(form, botao, progresso, falhasConsecutivas) {
    fetch(form.dataset.urlStatus)
        .then(function (resposta) { return resposta.json(); })
        .then(function (estado) {
            if (estado.status === 'rodando') {
                atualizarBarraSincronizacaoDrive(progresso, estado.etapa, estado.processados, estado.total);
                setTimeout(function () { consultarStatusSincronizacaoDrive(form, botao, progresso, 0); }, 1000);
                return;
            }
            // 'concluido', 'erro' ou 'ocioso' (não deveria vir 'ocioso' aqui,
            // mas trata como fim por segurança) — recarrega a tela.
            window.location.href = form.dataset.urlRetorno;
        })
        .catch(function () {
            if (falhasConsecutivas >= 9) {
                alert('Perdemos a conexão com o servidor durante a sincronização — atualize a página pra ver o estado real.');
                return;
            }
            setTimeout(function () { consultarStatusSincronizacaoDrive(form, botao, progresso, falhasConsecutivas + 1); }, 1000);
        });
}

var ROTULO_ETAPA_SINCRONIZACAO_DRIVE = {
    iniciando: 'Iniciando sincronização...',
    lendo_drive: 'Lendo o Google Drive...',
    atualizando_produtos: 'Atualizando produtos',
    avancando_roadmap: 'Avançando etapas',
};

function atualizarBarraSincronizacaoDrive(progresso, etapa, processados, total) {
    var barra = progresso.querySelector('.portal-drive-sincronizar-progresso-barra');
    var texto = progresso.querySelector('.portal-drive-sincronizar-progresso-texto');
    var rotulo = ROTULO_ETAPA_SINCRONIZACAO_DRIVE[etapa] || 'Sincronizando...';

    if (total) {
        var percentual = Math.round((processados / total) * 100);
        barra.value = percentual;
        texto.textContent = rotulo + ': ' + processados + ' de ' + total + ' (' + percentual + '%)';
    } else {
        barra.removeAttribute('value');
        texto.textContent = rotulo;
    }
}