"""Componentes reutilizaveis para testes da API Claude.

Este modulo concentra:
- dataclasses do modelo, tarifas e tarefa;
- cliente Anthropic (contagem gratuita e geracao);
- carteira de creditos com historico local.

Nao precisa alterar este arquivo para trocar descricao, modelo ou modo de execucao.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from anthropic import Anthropic
from dotenv import load_dotenv


MILHAO = Decimal("1000000")
Esforco = Literal["low", "medium", "high", "xhigh", "max"]
Raciocinio = Literal["disabled", "adaptive"]


def agora_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class Tarifas:
    """Tarifas em USD por 1 milhao de tokens."""

    entrada: Decimal
    saida: Decimal
    leitura_cache: Decimal
    escrita_cache_5m: Decimal
    escrita_cache_1h: Decimal


@dataclass(frozen=True, slots=True)
class TabelaPrecos:
    """Tarifas vinculadas a um modelo, inclusive para contexto longo."""

    modelo_id: str
    ate_100k: Tarifas
    acima_100k: Tarifas
    limite_entrada: int = 100_000

    def para_entrada(self, total_entrada: int) -> Tarifas:
        return self.ate_100k if total_entrada <= self.limite_entrada else self.acima_100k


# Valores da documentacao oficial em 12/10/2026.
# Atualize esta tabela se a Anthropic mudar as tarifas.
PRECOS_HAIKU_55 = TabelaPrecos(
    modelo_id="claude-haiku-5-5",
    ate_100k=Tarifas(
        entrada=Decimal("0.10"),
        saida=Decimal("0.50"),
        leitura_cache=Decimal("0.01"),
        escrita_cache_5m=Decimal("0.125"),
        escrita_cache_1h=Decimal("0.20"),
    ),
    acima_100k=Tarifas(
        entrada=Decimal("0.50"),
        saida=Decimal("2.50"),
        leitura_cache=Decimal("0.05"),
        escrita_cache_5m=Decimal("0.625"),
        escrita_cache_1h=Decimal("1.00"),
    ),
)


@dataclass(frozen=True, slots=True)
class ModeloClaude:
    """Objeto com identificador, comportamento e tabela de precos."""

    id: str
    precos: TabelaPrecos
    esforco: Esforco = "low"
    raciocinio: Raciocinio | None = "disabled"
    max_tokens: int = 96

    def __post_init__(self) -> None:
        if self.id != self.precos.modelo_id:
            raise ValueError(
                "A tabela de precos nao pertence ao modelo informado. "
                "Atualize as tarifas ao trocar de modelo."
            )
        if self.max_tokens < 1:
            raise ValueError("max_tokens deve ser maior que zero")
        if self.esforco not in ("low", "medium", "high", "xhigh", "max"):
            raise ValueError("Nivel de esforco desconhecido")
        if self.raciocinio not in (None, "disabled", "adaptive"):
            raise ValueError("Modo de raciocinio desconhecido")
        if self.raciocinio == "disabled" and self.esforco in ("xhigh", "max"):
            raise ValueError(
                "Haiku 5.5 nao aceita raciocinio disabled em xhigh/max. "
                "Use raciocinio='adaptive'."
            )

    def parametros(self) -> dict[str, Any]:
        """Parametros usados nas chamadas de contagem e geracao."""
        resultado: dict[str, Any] = {
            "model": self.id,
            "output_config": {"effort": self.esforco},
        }
        if self.raciocinio is not None:
            resultado["thinking"] = {"type": self.raciocinio}
        return resultado

    def custo(self, uso: UsoTokens) -> Decimal:
        """Custo estimado de tokens, com cache e contexto longo."""
        tarifas = self.precos.para_entrada(uso.total_entrada)
        soma = (
            Decimal(uso.entrada) * tarifas.entrada
            + Decimal(uso.saida) * tarifas.saida
            + Decimal(uso.cache_leitura) * tarifas.leitura_cache
            + Decimal(uso.cache_escrita_5m) * tarifas.escrita_cache_5m
            + Decimal(uso.cache_escrita_1h) * tarifas.escrita_cache_1h
        )
        return soma / MILHAO


@dataclass(frozen=True, slots=True)
class TarefaTitulo:
    """Entrada do caso de uso: titulo de anuncio para Mercado Livre."""

    descricao_produto: str
    limite_caracteres: int = 60

    def __post_init__(self) -> None:
        if not self.descricao_produto.strip():
            raise ValueError("A descricao do produto nao pode estar vazia")
        if self.limite_caracteres < 1:
            raise ValueError("O limite de caracteres deve ser positivo")

    def prompt(self) -> str:
        return (
            "Crie exatamente UM titulo de anuncio para o Mercado Livre.\n"
            f"Limite: {self.limite_caracteres} caracteres, contando espacos.\n"
            "Priorize tipo de produto, marca, modelo e atributos relevantes.\n"
            "Nao invente especificacoes ou caracteristicas.\n"
            "Sem emojis, aspas, hashtags, comentarios ou quebras de linha.\n"
            "Retorne somente o titulo.\n\n"
            f"DESCRICAO DO PRODUTO:\n{self.descricao_produto.strip()}"
        )

    def validar(self, texto: str, truncado: bool = False) -> tuple[bool, str]:
        titulo = texto.strip()
        if not titulo:
            return False, "O modelo devolveu um titulo vazio"
        if truncado:
            return False, "A resposta atingiu max_tokens e pode estar incompleta"
        if "\n" in titulo or "\r" in titulo:
            return False, "O titulo possui quebras de linha"
        if len(titulo) > self.limite_caracteres:
            return False, f"Titulo excedeu {self.limite_caracteres} caracteres"
        return True, "Titulo dentro do limite (revisar qualidade e fidelidade)"


@dataclass(frozen=True, slots=True)
class UsoTokens:
    entrada: int
    saida: int
    cache_leitura: int = 0
    cache_escrita_5m: int = 0
    cache_escrita_1h: int = 0

    @property
    def total_entrada(self) -> int:
        return (
            self.entrada
            + self.cache_leitura
            + self.cache_escrita_5m
            + self.cache_escrita_1h
        )

    @classmethod
    def da_resposta(cls, resposta: Any) -> UsoTokens:
        uso = resposta.usage
        detalhe = getattr(uso, "cache_creation", None)
        escrita_5m = int(getattr(detalhe, "ephemeral_5m_input_tokens", 0) or 0)
        escrita_1h = int(getattr(detalhe, "ephemeral_1h_input_tokens", 0) or 0)
        escrita_total = int(getattr(uso, "cache_creation_input_tokens", 0) or 0)
        if escrita_total > 0 and escrita_total != escrita_5m + escrita_1h:
            raise ValueError(
                "A API informou escrita em cache sem detalhamento 5m/1h. "
                "Confira o uso no Console antes de apurar o custo."
            )
        return cls(
            entrada=int(uso.input_tokens),
            saida=int(uso.output_tokens),
            cache_leitura=int(getattr(uso, "cache_read_input_tokens", 0) or 0),
            cache_escrita_5m=escrita_5m,
            cache_escrita_1h=escrita_1h,
        )


@dataclass(frozen=True, slots=True)
class Estimativa:
    tokens_entrada: int
    max_tokens_saida: int
    custo_maximo_estimado: Decimal


@dataclass(frozen=True, slots=True)
class Resultado:
    texto: str
    uso: UsoTokens
    custo_estimado: Decimal
    id_resposta: str
    truncado: bool


class ServicoClaude:
    """Esconde chamadas ao SDK para o restante da aplicacao."""

    def __init__(self, modelo: ModeloClaude, cliente: Any):
        self.modelo = modelo
        self.cliente = cliente

    @classmethod
    def do_ambiente(cls, modelo: ModeloClaude, pasta: Path) -> ServicoClaude:
        load_dotenv(pasta / ".env")
        chave = os.getenv("ANTHROPIC_API_KEY")
        workspace = os.getenv("ANTHROPIC_WORKSPACE_ID")
        if not chave or not workspace:
            raise ValueError(
                "Defina ANTHROPIC_API_KEY e ANTHROPIC_WORKSPACE_ID no .env"
            )
        cliente = Anthropic(
            api_key=chave,
            default_headers={"anthropic-workspace-id": workspace},
            max_retries=0,  # Evita novas tentativas automaticas sem registro financeiro
            timeout=30.0,
        )
        return cls(modelo, cliente)

    def _parametros(self, tarefa: TarefaTitulo) -> dict[str, Any]:
        return {
            **self.modelo.parametros(),
            "messages": [{"role": "user", "content": tarefa.prompt()}],
        }

    def estimar(self, tarefa: TarefaTitulo) -> Estimativa:
        """Usa somente o endpoint gratuito de contagem."""
        contagem = self.cliente.messages.count_tokens(**self._parametros(tarefa))
        entrada = int(contagem.input_tokens)
        custo_maximo = self.modelo.custo(
            UsoTokens(entrada=entrada, saida=self.modelo.max_tokens)
        )
        return Estimativa(
            tokens_entrada=entrada,
            max_tokens_saida=self.modelo.max_tokens,
            custo_maximo_estimado=custo_maximo,
        )

    def executar(self, tarefa: TarefaTitulo) -> Resultado:
        """Executa uma chamada paga e devolve resultado com consumo."""
        resposta = self.cliente.messages.create(
            **self._parametros(tarefa),
            max_tokens=self.modelo.max_tokens,
        )
        uso = UsoTokens.da_resposta(resposta)
        texto = "".join(
            bloco.text for bloco in resposta.content if bloco.type == "text"
        ).strip()
        return Resultado(
            texto=texto,
            uso=uso,
            custo_estimado=self.modelo.custo(uso),
            id_resposta=str(resposta.id),
            truncado=resposta.stop_reason == "max_tokens",
        )


@dataclass(frozen=True, slots=True)
class ConfiguracaoCreditos:
    """O ciclo so deve mudar quando o Console confirmar nova concessao."""

    ciclo: str
    teto: Decimal
    arquivo_estado: Path
    arquivo_legado: Path

    def __post_init__(self) -> None:
        if not self.ciclo.strip():
            raise ValueError("Informe um identificador para o ciclo")
        if self.teto < 0:
            raise ValueError("O teto mensal nao pode ser negativo")


@dataclass(slots=True)
class CarteiraCreditos:
    """Saldo estimado, persistido em JSON e separado das chamadas ao Claude."""

    configuracao: ConfiguracaoCreditos
    saldo: Decimal
    ciclo: str
    historico: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def carregar(cls, config: ConfiguracaoCreditos) -> CarteiraCreditos:
        if config.arquivo_estado.exists():
            dados = json.loads(config.arquivo_estado.read_text(encoding="utf-8"))
            carteira = cls(
                configuracao=config,
                saldo=Decimal(str(dados["saldo"])),
                ciclo=str(dados["ciclo"]),
                historico=list(dados.get("historico", [])),
            )
            if carteira.ciclo != config.ciclo:
                saldo_anterior = carteira.saldo
                carteira.ciclo = config.ciclo
                carteira.saldo = config.teto  # REINICIA, nao soma o saldo anterior
                carteira.historico.append(
                    {
                        "tipo": "renovacao",
                        "data_utc": agora_utc(),
                        "ciclo": config.ciclo,
                        "saldo_anterior": str(saldo_anterior),
                        "saldo_novo": str(config.teto),
                    }
                )
                carteira.salvar()
            return carteira

        # Importa saldo criado pelo script antigo, sem perder os centavos.
        if config.arquivo_legado.exists():
            saldo = Decimal(config.arquivo_legado.read_text(encoding="utf-8").strip())
            origem = "importacao_saldo_claude_txt"
        else:
            saldo = config.teto
            origem = "saldo_inicial"

        carteira = cls(configuracao=config, saldo=saldo, ciclo=config.ciclo)
        carteira.historico.append(
            {
                "tipo": origem,
                "data_utc": agora_utc(),
                "ciclo": config.ciclo,
                "saldo": str(saldo),
            }
        )
        carteira.salvar()
        return carteira

    def salvar(self) -> None:
        """Grava o arquivo inteiro por substituicao atomica."""
        destino = self.configuracao.arquivo_estado
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_name(destino.name + ".tmp")
        dados = {
            "ciclo": self.ciclo,
            "saldo": str(self.saldo),
            "historico": self.historico,
        }
        temporario.write_text(
            json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporario.replace(destino)

    def debitar(self, resultado: Resultado, modelo: ModeloClaude) -> None:
        custo = resultado.custo_estimado
        if custo < 0 or custo > self.saldo:
            raise ValueError("Debito invalido ou maior que o saldo estimado")
        self.saldo -= custo
        self.historico.append(
            {
                "tipo": "chamada",
                "data_utc": agora_utc(),
                "ciclo": self.ciclo,
                "modelo": modelo.id,
                "id_resposta": resultado.id_resposta,
                "tokens_entrada": resultado.uso.total_entrada,
                "tokens_saida": resultado.uso.saida,
                "custo_estimado_usd": str(custo),
                "saldo_estimado_apos_usd": str(self.saldo),
            }
        )
        self.salvar()
