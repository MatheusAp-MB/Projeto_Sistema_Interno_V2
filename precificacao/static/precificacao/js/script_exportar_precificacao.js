// * [RESUMO] → Controla a exibição condicional do seletor de "Tipo" (só aparece
// se o marketplace escolhido tiver Clássico/Premium, Sem/Com Afiliado, DBA/FBA)
// e sincroniza o destaque visual dos cards de marketplace/tipo/margem.

document.addEventListener('change', function (evento) {
    if (evento.target.classList.contains('exportacao-radio-marketplace')) {
        document.querySelectorAll('.exportacao-marketplace-card').forEach(function (card) {
            card.classList.remove('grade-margem-card--ativa');
        });
        evento.target.closest('.exportacao-marketplace-card').classList.add('grade-margem-card--ativa');

        var marketplaceEscolhido = evento.target.value;
        var temTipo = evento.target.dataset.temTipo === '1';
        var secaoTipo = document.getElementById('secao-tipo');

        // * [EXPLICAÇÃO] → CRÍTICO: desmarca TODOS os rádios de "tipo" de
        //                  TODOS os marketplaces, sempre — não só do grupo
        //                  que vai aparecer. display:none NUNCA desmarca um
        //                  input escondido; se não limpar aqui, o valor
        //                  marcado antes (ex: "premium" do ML) continua
        //                  sendo enviado no formulário mesmo trocando pra
        //                  um marketplace sem tipo nenhum (bug real
        //                  encontrado: "Shopee_premium" no nome do arquivo).
        document.querySelectorAll('input[name="tipo"]').forEach(function (r) { r.checked = false; });
        document.querySelectorAll('.exportacao-tipo-card').forEach(function (c) {
            c.classList.remove('grade-margem-card--ativa');
        });

        document.querySelectorAll('[data-tipos-de]').forEach(function (grupo) {
            grupo.style.display = 'none';
        });

        if (temTipo) {
            secaoTipo.style.display = 'block';
            var grupoCerto = document.querySelector(`[data-tipos-de="${marketplaceEscolhido}"]`);
            if (grupoCerto) {
                grupoCerto.style.display = 'grid';
            }
        } else {
            secaoTipo.style.display = 'none';
        }
        return;
    }

    if (evento.target.name === 'tipo') {
        document.querySelectorAll('.exportacao-tipo-card').forEach(function (card) {
            card.classList.remove('grade-margem-card--ativa');
        });
        evento.target.closest('.exportacao-tipo-card').classList.add('grade-margem-card--ativa');
        return;
    }

    if (evento.target.name === 'margem') {
        document.querySelectorAll('.promocao-margem-card').forEach(function (card) {
            card.classList.remove('grade-margem-card--ativa');
        });
        evento.target.closest('.promocao-margem-card').classList.add('grade-margem-card--ativa');
    }
});