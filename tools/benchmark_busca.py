"""Compara a saída da busca usando apenas notas sintéticas e Git local.

Execute na distribuição clonada: python3 tools/benchmark_busca.py
Não consulta serviços, modelos, configurações de contas ou um cofre pessoal.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


REFERENCIA = "40569e851506e3cd027004960f4b7d217bd0cb32"
RAIZ = Path(__file__).resolve().parent.parent


def consultar(script, cofre, *opcoes):
    resultado = subprocess.run(
        [sys.executable, str(script), "buscar", "contexto", "--trechos", *opcoes],
        env=dict(os.environ, CEREBRO_DIR=str(cofre)),
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=True,
    )
    return resultado.stdout


def conteudo(saida):
    """Compara nomes e trechos; pontuação e resumo de orçamento podem mudar."""
    nomes, trechos = [], []
    for linha in saida.splitlines():
        cabecalho = re.match(r"\s*\d+\s+\d+ car\.  (.+)  \[", linha)
        if cabecalho:
            nomes.append(cabecalho.group(1))
        elif linha.startswith("      L"):
            trechos.append(linha)
    return nomes, trechos


def medir():
    anterior = subprocess.run(
        ["git", "-C", str(RAIZ), "show", f"{REFERENCIA}:tools/cerebro.py"],
        capture_output=True, timeout=10, check=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="cerebro-benchmark-") as pasta:
        temporario = Path(pasta)
        cofre = temporario / "cofre"
        protocolo = cofre / "00 - Regras para Agentes" / "Protocolo dos Agentes.md"
        protocolo.parent.mkdir(parents=True)
        protocolo.write_text("# Protocolo sintético\nRegras de demonstração.\n", encoding="utf-8")
        notas = cofre / "05 - Padrões e Preferências" / "Aprendizados"
        notas.mkdir(parents=True)
        for i in range(40):
            corpo = "## Estado atual\n" + "".join(
                f"- Contexto da rota {j}: editar exemplo_{i:02d}_{j}.py e validar o cenário sintético. "
                + "Detalhes de demonstração para a mesma consulta. " * 4 + "\n"
                for j in range(4)
            )
            texto = ("---\ntipo: aprendizado\nstatus: ativo\ncriado_em: 2026-10-10\n"
                     "atualizado_em: 2026-10-10\n---\n" + corpo)
            (notas / f"Aprendizado - contexto sintético de demonstração {i:02d}.md").write_text(texto, encoding="utf-8")
        referencia = temporario / "anterior.py"
        referencia.write_bytes(anterior)
        atual = RAIZ / "tools" / "cerebro.py"
        opcoes = ("--max", "5", "--orcamento", "12000")
        antes = consultar(referencia, cofre, *opcoes)
        depois = consultar(atual, cofre, *opcoes)
        padrao = consultar(atual, cofre)
        nomes, linhas = conteudo(antes)
        if len(nomes) != 5 or len(linhas) != 20 or conteudo(depois) != (nomes, linhas):
            raise ValueError("Comparação inválida: as cinco notas e seus vinte trechos precisam ser idênticos.")
        if len(conteudo(padrao)[0]) != 2 or len(padrao) > 2500:
            raise ValueError("O padrão atual precisa mostrar duas notas dentro de 2.500 caracteres.")
        if len(depois) >= len(antes) or len(depois) > 12000 or len(antes) > 12000:
            raise ValueError("O cenário não demonstrou redução dentro do orçamento combinado.")
        return {
            "cenario": "40 notas relevantes inteiramente sintéticas; consulta: contexto",
            "unidade": "caracteres Unicode da saída inteira, incluindo quebras de linha",
            "referencia_git": REFERENCIA,
            "comparacao_controlada": {
                "max_notas": 5, "orcamento": 12000,
                "antes": len(antes), "depois": len(depois),
                "reducao_percentual": round(100 * (1 - len(depois) / len(antes)), 1),
                "mesmas_notas_e_trechos": True,
                "notas_conferidas": len(nomes), "trechos_conferidos": len(linhas),
            },
            "padrao_atual": {"notas": 2, "orcamento": 2500, "caracteres": len(padrao)},
            "limite": "Não mede tokens, custo, latência ou qualidade geral das respostas de uma IA.",
        }


if __name__ == "__main__":
    try:
        print(json.dumps(medir(), ensure_ascii=False, indent=2))
    except (OSError, subprocess.SubprocessError, ValueError) as erro:
        print(f"Benchmark não concluído: {erro}\nUse um clone Git que contenha a revisão {REFERENCIA}.",
              file=sys.stderr)
        raise SystemExit(1)
