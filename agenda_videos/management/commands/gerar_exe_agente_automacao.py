# agenda_videos/management/commands/gerar_exe_agente_automacao.py

# Função Objetivo: Gera o programa do agente de automação (servidor_agente.exe) com o PyInstaller, num único
# comando (`python manage.py gerar_exe_agente_automacao`). É o programa que roda no computador de quem faz as
# postagens, replicações e verificações no Mercado Livre — o servidor do sistema não o inclui sozinho: sempre que
# o código de agente_local/ muda, o .exe precisa ser gerado de novo. Uso do dev (nunca roda no servidor).
# O nome é específico de propósito (decisão de Matheus, 14/10/2026): "gerar_exe" sozinho é aberto demais e
# confunde com o gerar_exe do Sistema de Devoluções, que empacota outro programa.
#
# * [DECISÃO, 14/10/2026] → O agente é SEMPRE gerado sem console (--noconsole): roda escondido, só com o ícone na
#   bandeja do Windows, e não existe opção para gerar com console (decisão de Matheus). As demais opções repetem o
#   último build que existe no PC (30/07/2026), conferido nos arquivos que o PyInstaller deixou em
#   build/servidor_agente: arquivo único (--onefile), nome servidor_agente, resultado em dist/ e arquivos de
#   trabalho em build/. Foram acrescentados só estes itens, todos seguros:
#     --clean       o PyInstaller reaproveita análise antiga e pode ignorar código novo (visto no gerar_exe do
#                   Sistema de Devoluções em 04/09/2026) — aqui o .exe precisa ter SEMPRE o código de agora;
#     --noconfirm   nunca ficar parado esperando um "sim" no terminal;
#     --hidden-import=pystray._win32   o ícone da bandeja escolhe o código do Windows por nome (import dinâmico),
#                   o mesmo ajuste que o Sistema de Devoluções precisou — já vinha incluído, aqui só fica garantido;
#     --specpath build   o arquivo .spec fica em build/ e não suja a raiz do projeto.
# * [EXPLICAÇÃO] → Sem console o Windows entrega sys.stdout/sys.stderr vazios (None): o código do agente já cuida
#   disso (_DuplicadorSaida em servidor_agente.py grava tudo no arquivo agente_log_*.txt, ao lado do .exe) e não usa
#   input() nem abre outros programas. Pelo mesmo motivo, se o agente falhar ao abrir (ex.: sem agente_config.env)
#   NÃO aparece janela nenhuma: o único registro é esse arquivo de log — o comando avisa isso no fim.
# * [EXPLICAÇÃO] → O comando usa o mesmo Python em que ele mesmo está rodando (sys.executable -m PyInstaller): não
#   depende do "pyinstaller" estar no PATH e usa sempre o ambiente do Poetry em que o manage.py foi aberto.
# * [IMPORTANTE] → O comando recusa rodar fora do Windows (o agente usa bibliotecas dele; um binário de Linux/Mac
#   não serviria) e antes de gastar o minuto do build confere 3 coisas que dariam um .exe errado ou um erro tardio:
#   PyInstaller instalado, agente fechado (o Windows não deixa trocar o .exe aberto) e todas as bibliotecas do agente
#   instaladas neste ambiente (senão o .exe sairia sem elas e só quebraria no computador de quem usa).
# * [IMPORTANTE] → Nada é escrito no agente_config.env (ele guarda a chave do agente): o comando só avisa se ele não
#   está ao lado do .exe.

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

NOME_DO_EXE = 'servidor_agente'
SCRIPT_DO_AGENTE = Path('agente_local') / 'servidor_agente.py'
PASTA_DO_RESULTADO = 'dist'
PASTA_DE_TRABALHO = 'build'
ARQUIVO_DE_CONFIGURACAO = 'agente_config.env'
FOLGA_DO_RELOGIO_DO_ARQUIVO_EM_SEGUNDOS = 2
TEMPO_MAXIMO_DA_CONFERENCIA_EM_SEGUNDOS = 60


def _rodando_no_windows():
    return sys.platform == 'win32'


def _pyinstaller_instalado():
    return importlib.util.find_spec('PyInstaller') is not None


def _exe_esta_em_uso(caminho_do_exe):
    """True se o .exe já existe e o Windows não deixa escrever nele (o agente está aberto)."""
    if not caminho_do_exe.exists():
        return False
    try:
        with open(caminho_do_exe, 'ab'):
            return False
    except OSError:
        return True


def _conferir_bibliotecas_do_agente(pasta_do_projeto):
    """Abre o código do agente num processo à parte (só o import — nada roda). Devolve (ok, detalhe)."""
    try:
        resultado = subprocess.run(
            [sys.executable, '-c', 'import agente_local.servidor_agente'],
            cwd=pasta_do_projeto, capture_output=True, text=True, timeout=TEMPO_MAXIMO_DA_CONFERENCIA_EM_SEGUNDOS,
        )
    except subprocess.TimeoutExpired:
        return False, f'travou por mais de {TEMPO_MAXIMO_DA_CONFERENCIA_EM_SEGUNDOS} segundos ao abrir'
    if resultado.returncode == 0:
        return True, ''
    linhas_do_erro = resultado.stderr.strip().splitlines()
    return False, linhas_do_erro[-1] if linhas_do_erro else 'sem detalhe'


def _montar_comando(pasta_do_projeto):
    return [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--noconsole',
        '--clean',
        '--noconfirm',
        '--name', NOME_DO_EXE,
        '--paths', str(pasta_do_projeto),
        '--distpath', str(pasta_do_projeto / PASTA_DO_RESULTADO),
        '--workpath', str(pasta_do_projeto / PASTA_DE_TRABALHO),
        '--specpath', str(pasta_do_projeto / PASTA_DE_TRABALHO),
        '--hidden-import=pystray._win32',
        str(pasta_do_projeto / SCRIPT_DO_AGENTE),
    ]


class Command(BaseCommand):
    help = (
        'Gera o programa do agente de automação (dist/servidor_agente.exe) com o PyInstaller. '
        'Rodar no Windows, com o agente fechado, sempre que o código de agente_local/ mudar.'
    )

    # * [EXPLICAÇÃO] → Não mexe em banco nenhum: a checagem do Django é desnecessária aqui.
    requires_system_checks = []

    def handle(self, *args, **options):
        pasta_do_projeto = Path(settings.BASE_DIR)
        script = pasta_do_projeto / SCRIPT_DO_AGENTE
        pasta_do_resultado = pasta_do_projeto / PASTA_DO_RESULTADO
        exe = pasta_do_resultado / f'{NOME_DO_EXE}.exe'

        if not _rodando_no_windows():
            raise CommandError(
                'O agente só funciona no Windows, então o .exe precisa ser gerado no Windows. '
                'Rode este comando no computador onde o agente vai ser usado (ou no seu PC de trabalho).'
            )
        if not _pyinstaller_instalado():
            raise CommandError('O PyInstaller não está instalado neste ambiente. Rode: poetry install')
        if not script.exists():
            raise CommandError(f'Não achei o código do agente em {script}. Rode o comando na raiz do projeto.')
        if _exe_esta_em_uso(exe):
            raise CommandError(
                f'O arquivo {exe} está em uso: o agente deve estar aberto (ou o antivírus está lendo o arquivo). '
                'Feche o agente (ícone da bandeja → Sair) e rode o comando de novo.'
            )

        bibliotecas_ok, detalhe = _conferir_bibliotecas_do_agente(pasta_do_projeto)
        if not bibliotecas_ok:
            raise CommandError(
                f'O código do agente não abre neste ambiente ({detalhe}). Rode: poetry install — '
                'sem isso o .exe sairia sem essa biblioteca e só quebraria no computador de quem usa.'
            )

        self.stdout.write(self.style.NOTICE(f'Gerando {NOME_DO_EXE}.exe (arquivo único, sem console). Leva cerca de 1 a 2 minutos...'))
        inicio = time.time()
        resultado = subprocess.run(_montar_comando(pasta_do_projeto), cwd=pasta_do_projeto)

        if resultado.returncode != 0:
            raise CommandError(f'O PyInstaller terminou com erro (código {resultado.returncode}) — veja o log acima.')
        if not exe.exists() or exe.stat().st_mtime < inicio - FOLGA_DO_RELOGIO_DO_ARQUIVO_EM_SEGUNDOS:
            raise CommandError(
                f'O PyInstaller terminou sem erro, mas {exe} não foi atualizado. Rode o comando de novo e, '
                'se repetir, apague a pasta build/ e tente mais uma vez.'
            )

        megabytes = exe.stat().st_size / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(f'Pronto: {exe} ({megabytes:.1f} MB), gerado em {time.time() - inicio:.0f} s.'))

        if not (pasta_do_resultado / ARQUIVO_DE_CONFIGURACAO).exists():
            self.stdout.write(self.style.WARNING(
                f'Atenção: não achei {ARQUIVO_DE_CONFIGURACAO} ao lado do .exe. O agente precisa dele, com 2 linhas: '
                'SERVIDOR=<endereço do sistema> e TOKEN=<o mesmo AGENTE_TOKEN do .env do sistema>.'
            ))
        self.stdout.write(
            'Para usar: abra o novo .exe. Nos outros computadores que usam o agente, '
            f'copie o {NOME_DO_EXE}.exe novo (o {ARQUIVO_DE_CONFIGURACAO} de lá continua valendo).'
        )
        self.stdout.write(
            'O agente roda sem janela: o sinal de que abriu é o ícone na bandeja do Windows. Se o ícone não aparecer, '
            'o motivo está no arquivo agente_log_*.txt (o mais recente), na mesma pasta do .exe.'
        )
