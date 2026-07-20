// * [RESUMO] → JS da tela "Gerar Promoção — TikTok Shop": sincroniza o destaque
// visual dos cards de margem (1 grupo por tipo), o botão "Selecionar/Desmarcar
// tudo" e a lista de chips de marcas selecionadas.

document.addEventListener('change', function (evento) {
    if (evento.target.name !== 'margem_sem_afiliado' && evento.target.name !== 'margem_com_afiliado') return;

    var grupo = evento.target.name;
    document.querySelectorAll(`input[name="${grupo}"]`).forEach(function (radio) {
        radio.closest('.promocao-margem-card').classList.remove('grade-margem-card--ativa');
    });
    evento.target.closest('.promocao-margem-card').classList.add('grade-margem-card--ativa');
});

function marcarTodasMarcas(botao) {
    var caixas = botao.closest('form').querySelectorAll('input[name="marca"]');
    var todasMarcadas = Array.from(caixas).every(function (c) { return c.checked; });
    caixas.forEach(function (c) { c.checked = !todasMarcadas; });
    botao.textContent = todasMarcadas ? 'Selecionar tudo' : 'Desmarcar tudo';
    atualizarChipsMarca();
}

function atualizarChipsMarca() {
    var caixas = document.querySelectorAll('input[name="marca"]:checked');
    var lista = document.getElementById('lista-chips-marcas');
    var contador = document.getElementById('contador-marcas');

    contador.textContent = caixas.length;

    if (caixas.length === 0) {
        lista.innerHTML = '<span class="promocao-chips-vazio">Nenhuma marca selecionada ainda.</span>';
        return;
    }

    lista.innerHTML = '';
    caixas.forEach(function (caixa) {
        var chip = document.createElement('span');
        chip.className = 'promocao-chip';
        chip.textContent = caixa.value;

        var remover = document.createElement('button');
        remover.type = 'button';
        remover.className = 'promocao-chip-remover';
        remover.innerHTML = '&times;';
        remover.onclick = function () {
            caixa.checked = false;
            atualizarChipsMarca();
        };

        chip.appendChild(remover);
        lista.appendChild(chip);
    });
}