(function () {
    var modal = document.getElementById('modal-fotos');
    if (!modal) return;

    var elImagem = document.getElementById('modal-fotos-imagem');
    var elTitulo = document.getElementById('modal-fotos-titulo');
    var elMlb = document.getElementById('modal-fotos-mlb');
    var elSku = document.getElementById('modal-fotos-sku');
    var elContador = document.getElementById('modal-fotos-contador');
    var elLegenda = document.getElementById('modal-fotos-legenda');
    var btnFechar = document.getElementById('modal-fotos-fechar');
    var btnAnterior = document.getElementById('modal-fotos-anterior');
    var btnProxima = document.getElementById('modal-fotos-proxima');

    var estado = { fotos: [], indice: 0, titulo: '', mlb: '', sku: '' };
    var precarregadas = {};

    function montarLegenda(foto) {
        var partes = [];
        if (foto.size) partes.push('Tamanho servido: ' + foto.size);
        if (foto.max_size) partes.push('Tamanho máximo: ' + foto.max_size);
        if (foto.quality) partes.push('Qualidade: ' + foto.quality);
        return partes.length ? partes.join(' · ') : 'Sem dados adicionais desta foto.';
    }

    function urlGrande(url) {
        if (!url) return url;
        var partes = url.split('.');
        var ext = partes.pop();
        var base = partes.join('.');
        var semSufixo = base.replace(/-[^-]+$/, '');
        return semSufixo + '-F.' + ext;
    }

    function precarregar(url) {
        if (!url || precarregadas[url]) return;
        precarregadas[url] = true;
        var img = new Image();
        img.src = url;
    }

    function precarregarFotosDoAnuncio() {
        estado.fotos.forEach(function (foto) {
            precarregar(urlGrande(foto.secure_url || foto.url));
        });
    }

    function renderizar() {
        var foto = estado.fotos[estado.indice];
        if (!foto) return;
        elImagem.src = urlGrande(foto.secure_url || foto.url);
        elImagem.alt = 'Foto ' + (estado.indice + 1) + ' de ' + estado.titulo;
        elTitulo.textContent = estado.titulo;
        elMlb.textContent = estado.mlb;
        elSku.textContent = estado.sku;
        elContador.textContent = 'Foto ' + (estado.indice + 1) + ' de ' + estado.fotos.length;
        elLegenda.textContent = montarLegenda(foto);
    }

    function abrir(fotosId, indice, titulo, mlb, sku) {
        var script = document.getElementById(fotosId);
        if (!script) return;
        estado.fotos = JSON.parse(script.textContent);
        estado.indice = indice;
        estado.titulo = titulo;
        estado.mlb = mlb;
        estado.sku = sku;
        renderizar();
        precarregarFotosDoAnuncio();
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
    }

    function fechar() {
        modal.hidden = true;
        document.body.style.overflow = '';
    }

    function anterior() {
        estado.indice = (estado.indice - 1 + estado.fotos.length) % estado.fotos.length;
        renderizar();
    }

    function proxima() {
        estado.indice = (estado.indice + 1) % estado.fotos.length;
        renderizar();
    }

    document.addEventListener('mouseover', function (evento) {
        var item = evento.target.closest('.card-fotos-item');
        if (!item) return;
        var script = document.getElementById(item.getAttribute('data-fotos-id'));
        if (!script) return;
        var fotos = JSON.parse(script.textContent);
        var foto = fotos[parseInt(item.getAttribute('data-index'), 10)];
        if (foto) precarregar(urlGrande(foto.secure_url || foto.url));
    });

    document.addEventListener('click', function (evento) {
        var item = evento.target.closest('.card-fotos-item');
        if (!item) return;
        abrir(
            item.getAttribute('data-fotos-id'),
            parseInt(item.getAttribute('data-index'), 10),
            item.getAttribute('data-titulo'),
            item.getAttribute('data-mlb'),
            item.getAttribute('data-sku')
        );
    });

    btnFechar.addEventListener('click', fechar);
    btnAnterior.addEventListener('click', anterior);
    btnProxima.addEventListener('click', proxima);

    modal.addEventListener('click', function (evento) {
        if (evento.target === modal) fechar();
    });

    document.addEventListener('keydown', function (evento) {
        if (modal.hidden) return;
        if (evento.key === 'Escape') fechar();
        if (evento.key === 'ArrowLeft') anterior();
        if (evento.key === 'ArrowRight') proxima();
    });
})();