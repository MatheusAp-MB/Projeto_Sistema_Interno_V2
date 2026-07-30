import pystray
from PIL import Image, ImageDraw


def _criar_imagem_icone():
    # * [EXPLICAÇÃO] → Ícone simples (bolinha verde) só pra este teste —
    #                  depois trocamos por um ícone de verdade, com o
    #                  logo do sistema ou algo parecido.
    imagem = Image.new('RGB', (64, 64), 'white')
    desenho = ImageDraw.Draw(imagem)
    desenho.ellipse((8, 8, 56, 56), fill='green')
    return imagem


def _sair(icone, item):
    icone.stop()


icone = pystray.Icon(
    'agente_teste',
    _criar_imagem_icone(),
    'Agente rodando — tudo OK, use o navegador normalmente',
    menu=pystray.Menu(
        pystray.MenuItem('Sair', _sair),
    ),
)
icone.run()