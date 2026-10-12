"""Seu painel de configuracao para testar titulos do Mercado Livre.

Altere apenas os objetos da secao CONFIGURACAO abaixo.
Executar: python -u teste_claude.py
"""

from decimal import Decimal
from pathlib import Path

from anthropic import APIError

from config_claude import (
    PRECOS_HAIKU_55,
    CarteiraCreditos,
    ConfiguracaoCreditos,
    ModeloClaude,
    ServicoClaude,
    TarefaTitulo,
)

PASTA = Path(__file__).resolve().parent

# ==========================================================
# CONFIGURACAO - ALTERE AQUI
# ==========================================================

# Objeto MODELO: qual LLM usar e como deve se comportar.
MODELO = ModeloClaude(
    id="claude-haiku-5-5",
    precos=PRECOS_HAIKU_55,
    esforco="low",           # low | medium | high | xhigh | max
    raciocinio="disabled",  # disabled | adaptive
    max_tokens=96,
)

# Objeto TAREFA: o que voce quer que a IA produza.
TAREFA = TarefaTitulo(
    descricao_produto="""O Pulverizador Costal Brudden SS20-B combina o modo elétrico, para maior praticidade, com o modo manual, para uso quando necessário, mantendo a continuidade do trabalho. Produto Brudden original, acompanhado de nota fiscal e garantia de fábrica de 6 meses.

Principais recursos
Dois modos de uso: alterne entre o modo elétrico e o modo manual conforme a necessidade da tarefa.
Autonomia de bateria: bateria recarregável com autonomia de aproximadamente 10 horas de uso contínuo.
Jogo de bicos intercambiáveis: acompanha um conjunto com 5 bicos diferentes para aplicação de líquidos e soluções agrícolas de uso foliar, permitindo escolher o bico adequado para cada tarefa em jardins, plantas ou limpeza de ambientes.
Lança telescópica ajustável: lança regulável de 42 centímetros a 90 centímetros, facilitando o alcance em locais de difícil acesso.
Gatilho com trava de acionamento: gatilho metálico com trava que facilita a pulverização em períodos mais longos.
Bomba com regulagem de pressão: bomba de diafragma com ajuste de pressão para adequar o fluxo de pulverização a cada tarefa.
Kit de reparo incluso: conjunto com fusível, anel de vedação, arruela e travas para pequenos reparos e manutenção do equipamento.

Especificações técnicas

Características gerais
Capacidade do tanque: 20 litros.
Tipo: pulverizador elétrico e manual costal.
Bomba: diafragma com regulagem de pressão.
Autonomia da bateria: aproximadamente 10 horas.
Bateria: recarregável de 12 volts e 8 amperes.
Voltagem da fonte: bivolt.

Medidas e peso
Peso do produto: 5,8 quilogramas.
Altura: 56 centímetros.
Largura: 21 centímetros.
Comprimento: 42 centímetros.

Performance
Pressão máxima: 4,5 bar (65,3 libras-força por polegada quadrada).

Acessórios inclusos
Lança telescópica de 42 centímetros a 90 centímetros.
Jogo com 5 bicos de pulverização.
Kit de reparo (fusível, anel de vedação, arruela e travas).
Bateria e carregador.

Detalhes sobre os bicos
Bico cone vazio duplo: ideal para aplicação de líquidos agrícolas, com dois orifícios que possibilitam atingir uma área maior de pulverização.
Bico leque: ideal para aplicação de líquidos agrícolas, com formato em leque para maior controle da pulverização.
Bico espelho: ideal para aplicação de líquidos agrícolas que exigem gotas de maior tamanho.
Bico especial de 4 furos: ideal para aplicação em cobertura total ou sobreposta com líquidos agrícolas de uso foliar.
Bico especial de 5 furos: ideal para aplicação em cobertura total ou sobreposta com líquidos agrícolas de uso foliar.

Indicações de uso
Adequado para uso em viveiros de plantas, jardinagem, limpeza de ambientes e cuidados em chácaras ou propriedades rurais.

Modo de uso e cuidados
Este equipamento deve ser operado apenas com produtos líquidos. Não utilize produtos em pó, insolúveis em água, corrosivos, inflamáveis, combustíveis ou solventes. Acompanha manual de instruções para uso adequado e seguro.""",
    limite_caracteres=60,
)

# Objeto CREDITOS: 120 dolares por concessao, sem acumular.
CREDITOS = ConfiguracaoCreditos(
    ciclo="2026-10-12",  # MUDE somente quando confirmar a proxima renovacao
    teto=Decimal("120.00"),
    arquivo_estado=PASTA / "saldo_claude.json",
    arquivo_legado=PASTA / "saldo_claude.txt",
)

# False: so conta tokens (gratis). True: consulta o Claude (pago).
EXECUTAR = True

# ==========================================================
# APLICACAO - NORMALMENTE NAO PRECISA ALTERAR
# ==========================================================


def main() -> None:
    carteira = CarteiraCreditos.carregar(CREDITOS)
    servico = ServicoClaude.do_ambiente(MODELO, PASTA)

    print("\n=== CONFIGURACAO ===")
    print(f"Modelo: {MODELO.id}")
    print(f"Esforco: {MODELO.esforco}")
    print(f"Raciocinio: {MODELO.raciocinio}")
    print(f"Modo: {'EXECUCAO PAGA' if EXECUTAR else 'SIMULACAO GRATUITA'}")
    print(f"Saldo local estimado: US$ {carteira.saldo:.8f}")

    estimativa = servico.estimar(TAREFA)
    print("\n=== ESTIMATIVA GRATUITA ===")
    print(f"Entrada: {estimativa.tokens_entrada} tokens")
    print(f"Limite de saida: {estimativa.max_tokens_saida} tokens")
    print(f"Custo estimado ate o limite: US$ {estimativa.custo_maximo_estimado:.8f}")
    print(f"Saldo projetado: US$ {carteira.saldo - estimativa.custo_maximo_estimado:.8f}")

    if not EXECUTAR:
        print("\nNenhuma chamada paga executada. Saldo mantido.")
        return

    if estimativa.custo_maximo_estimado > carteira.saldo:
        print("\nChamada bloqueada: saldo estimado insuficiente.")
        return

    # A API cobra esta chamada, inclusive se o titulo gerado for invalido.
    resultado = servico.executar(TAREFA)

    # Persiste o custo ANTES de exibir ou avaliar o titulo.
    carteira.debitar(resultado, MODELO)

    titulo = resultado.texto
    aprovado, motivo = TAREFA.validar(titulo, truncado=resultado.truncado)

    print("\n=== TITULO GERADO ===")
    print(titulo or "(vazio)")
    print(f"Caracteres: {len(titulo)}/{TAREFA.limite_caracteres}")
    print(f"Validacao: {'OK' if aprovado else 'REPROVADO'} - {motivo}")
    print("\n=== CONSUMO ===")
    print(f"Entrada efetiva: {resultado.uso.total_entrada} tokens")
    print(f"Saida efetiva: {resultado.uso.saida} tokens")
    print(f"Custo estimado: US$ {resultado.custo_estimado:.8f}")
    print(f"Saldo local atualizado: US$ {carteira.saldo:.8f}")


if __name__ == "__main__":
    try:
        main()
    except APIError as erro:
        print(f"\nErro da API Anthropic: {erro}")
        print("Se a requisicao chegou a ser processada, confira o Console antes de ajustar o saldo.")
        raise SystemExit(1) from erro
