function copiar_texto(texto) {
    // * [EXPLICAÇÃO] → navigator.clipboard só existe em contexto seguro
    //                  (HTTPS ou localhost). Acessando via IP da rede
    //                  local por HTTP puro (ex: colegas testando pelo
    //                  Wi-Fi do escritório), essa API nem existe —
    //                  precisa do método antigo (execCommand) como
    //                  plano B, que funciona em qualquer contexto.
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
