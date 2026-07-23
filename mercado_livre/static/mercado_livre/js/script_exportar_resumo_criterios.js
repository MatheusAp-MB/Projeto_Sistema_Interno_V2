// * [RESUMO] → Intercepta o clique no botão "Exportar" pra mostrar um aviso
// de carregamento enquanto o Excel é gerado no servidor. Usa fetch() em vez
// de navegação direta, porque um <a href> normal pra um download não dá
// nenhum feedback visual — o navegador só salva o arquivo sem avisar nada.

document.addEventListener('click', function (evento) {
    var botao = evento.target.closest('.btn-exportar-com-aviso');
    if (!botao) return;

    var url = botao.dataset.urlExportar;
    var nomeArquivo = botao.dataset.nomeArquivo || 'Exportacao.xlsx';
    mostrarAvisoCarregandoExportacao();

    fetch(url)
        .then(function (resposta) {
            if (!resposta.ok) throw new Error('Falha ao gerar o arquivo.');
            return resposta.blob();
        })
        .then(function (blob) {
            var linkTemporario = document.createElement('a');
            var urlBlob = window.URL.createObjectURL(blob);
            linkTemporario.href = urlBlob;
            linkTemporario.download = nomeArquivo;
            document.body.appendChild(linkTemporario);
            linkTemporario.click();
            linkTemporario.remove();
            window.URL.revokeObjectURL(urlBlob);
        })
        .catch(function () {
            alert('Não foi possível gerar o arquivo — tenta de novo.');
        })
        .finally(function () {
            esconderAvisoCarregandoExportacao();
        });
});

function mostrarAvisoCarregandoExportacao() {
    var aviso = document.createElement('div');
    aviso.id = 'aviso-exportacao-overlay';
    aviso.innerHTML = `
        <div class="aviso-exportacao-caixa">
            <i class="fas fa-spinner fa-spin"></i>
            <span>Aguarde, estamos gerando o arquivo...</span>
        </div>
    `;
    document.body.appendChild(aviso);
}

function esconderAvisoCarregandoExportacao() {
    var aviso = document.getElementById('aviso-exportacao-overlay');
    if (aviso) aviso.remove();
}