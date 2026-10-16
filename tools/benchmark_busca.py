"""Compara a saída da busca usando apenas notas sintéticas e Git local.

Execute na distribuição clonada: python3 tools/benchmark_busca.py
Não consulta serviços, modelos, configurações de contas ou um cofre pessoal.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


REFERENCIA = "40569e851506e3cd027004960f4b7d217bd0cb32"
RAIZ = Path(__file__).resolve().parent.parent


def consultar(script, cofre, *opcoes, termos=("contexto",), espera=30):
    resultado = subprocess.run(
        [sys.executable, str(script), "buscar", *termos, "--trechos", *opcoes],
        env=dict(os.environ, CEREBRO_DIR=str(cofre)),
        capture_output=True, text=True, encoding="utf-8", timeout=espera, check=True,
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


TEMAS = ("roteamento", "validacao", "interface", "publicacao")
CONSULTAS = [
    {"termos": [tema]} for tema in TEMAS
] + [
    {"termos": ["roteamento", "validacao"]},
    {"termos": ["interface", "publicacao"]},
    {"termos": ["roteamento"], "projeto": "Demo-00"},
    {"termos": ["inexistentezzz"]},
]


def gerar_corpus(base, quantidade):
    """Notas determinísticas; cada escala reutiliza o prefixo da anterior."""
    pasta = base / "05 - Padrões e Preferências" / "Aprendizados"
    pasta.mkdir(parents=True)
    protocolo = base / "00 - Regras para Agentes" / "Protocolo dos Agentes.md"
    protocolo.parent.mkdir()
    protocolo.write_text("# Protocolo sintético\nRegras de demonstração.\n", encoding="utf-8")
    registros = {}
    for i in range(quantidade):
        tema, projeto = TEMAS[i % len(TEMAS)], f"Demo-{i % 7:02d}"
        nome = f"Aprendizado - {tema} sintético {i:05d}.md"
        texto = ("---\ntipo: aprendizado\nstatus: ativo\ncriado_em: 2026-10-10\n"
                 f"atualizado_em: 2026-10-10\nprojeto: {projeto}\n---\n## Referência\n")
        texto += "".join(
            f"- {tema}: cenário {i:05d}, rota {j}, arquivo exemplo_{i:05d}_{j}.py. "
            + "Informações sintéticas sobre o componente e suas decisões. " * 4 + "\n"
            for j in range(4)
        )
        texto += "\n## Material complementar\n" + (
            "Documentação descritiva do cenário demonstrativo, sem dados reais. " * ((i % 9 + 1) * 4)
        ) + "\n"
        (pasta / nome).write_text(texto, encoding="utf-8")
        registros[str((pasta / nome).relative_to(base))] = (tema, projeto)
    digest = hashlib.sha256()
    caracteres = bytes_total = 0
    for arquivo in sorted(base.rglob("*.md")):
        dados = arquivo.read_bytes()
        caracteres += len(dados.decode("utf-8"))
        bytes_total += len(dados)
        digest.update(str(arquivo.relative_to(base)).encode("utf-8") + b"\0" + dados + b"\0")
    return registros, {"notas_de_conteudo": quantidade, "arquivos_markdown": quantidade + 1,
                       "caracteres": caracteres, "bytes_utf8": bytes_total, "sha256": digest.hexdigest()}


def medir_ampliado():
    anterior = subprocess.run(
        ["git", "-C", str(RAIZ), "show", f"{REFERENCIA}:tools/cerebro.py"],
        capture_output=True, timeout=10, check=True,
    ).stdout
    escalas = []
    with tempfile.TemporaryDirectory(prefix="cerebro-escala-") as pasta:
        raiz = Path(pasta)
        referencia = raiz / "anterior.py"
        referencia.write_bytes(anterior)
        atual = RAIZ / "tools/cerebro.py"
        for quantidade in (40, 1000, 10000):
            base = raiz / str(quantidade)
            registros, corpus = gerar_corpus(base, quantidade)
            resultados = []
            for indice, consulta in enumerate(CONSULTAS):
                opcoes = ["--max", "5", "--orcamento", "12000"]
                if consulta.get("projeto"):
                    opcoes += ["--projeto", consulta["projeto"]]
                # Alterna a ordem para reduzir o favorecimento sistemático pelo cache do disco.
                ordem = [("antes", referencia), ("depois", atual)]
                if indice % 2:
                    ordem.reverse()
                saidas, tempos = {}, {}
                for versao, script in ordem:
                    inicio = time.perf_counter()
                    saidas[versao] = consultar(script, base, *opcoes, termos=consulta["termos"], espera=120)
                    tempos[versao] = round(time.perf_counter() - inicio, 4)
                nomes, linhas = conteudo(saidas["antes"])
                elegiveis = {nome for nome, (tema, projeto) in registros.items()
                             if tema in consulta["termos"] and
                             (not consulta.get("projeto") or projeto == consulta["projeto"])}
                if (conteudo(saidas["depois"]) != (nomes, linhas) or
                        len(nomes) != min(5, len(elegiveis)) or
                        not set(nomes).issubset(elegiveis) or len(linhas) != 4 * len(nomes)):
                    raise ValueError(f"Seleção divergente ou incorreta: {quantidade} notas, {consulta}")
                if any(len(saida) > 12000 for saida in saidas.values()):
                    raise ValueError("Saída ultrapassou o orçamento combinado.")
                antes, depois = len(saidas["antes"]), len(saidas["depois"])
                resultados.append({**consulta, "notas_elegiveis": len(elegiveis),
                                   "notas_selecionadas": len(nomes), "trechos": len(linhas),
                                   "mesmas_notas_e_trechos": True, "antes": antes, "depois": depois,
                                   "reducao_percentual": round(100 * (1 - depois / antes), 1),
                                   "segundos_observados": tempos})
            antes = sum(r["antes"] for r in resultados)
            depois = sum(r["depois"] for r in resultados)
            escalas.append({"corpus": corpus, "consultas": resultados,
                            "agregado": {"antes": antes, "depois": depois,
                                         "reducao_percentual": round(100 * (1 - depois / antes), 1)}})
            print(f"Conferido: {quantidade:,} notas, oito consultas pareadas.", file=sys.stderr, flush=True)
    antes = sum(e["agregado"]["antes"] for e in escalas)
    depois = sum(e["agregado"]["depois"] for e in escalas)
    return {"cenario": "Três escalas sintéticas determinísticas, oito consultas por escala",
            "referencia_git": REFERENCIA, "nucleo_atual_sha256": hashlib.sha256(atual.read_bytes()).hexdigest(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "ambiente": {"python": sys.version.split()[0], "plataforma": sys.platform},
            "opcoes_por_consulta": {"max_notas": 5, "orcamento_caracteres": 12000},
            "escalas": escalas, "total": {"consultas_pareadas": 24, "execucoes": 48,
            "antes": antes, "depois": depois, "caracteres_a_menos": antes - depois,
            "reducao_percentual": round(100 * (1 - depois / antes), 1),
            "mesmas_notas_e_trechos_em_todas": True},
            "limites": ["Corpora inteiramente sintéticos; os prefixos se repetem entre escalas.",
                        "O tamanho do maior corpus é contado uma vez, sem multiplicar pelas consultas.",
                        "As saídas incluem omissões, resumo e quebras de linha; não são tokens de IA.",
                        "Tempos são uma passagem por caso, sem controle de cache nem repetições estatísticas.",
                        "Não mede inferências, produtividade, qualidade geral das IAs ou economia financeira."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ampliado", action="store_true", help="40, 1.000 e 10.000 notas; 24 consultas pareadas")
    args = parser.parse_args()
    try:
        print(json.dumps(medir_ampliado() if args.ampliado else medir(), ensure_ascii=False, indent=2))
    except (OSError, subprocess.SubprocessError, ValueError) as erro:
        print(f"Benchmark não concluído: {erro}\nUse um clone Git que contenha a revisão {REFERENCIA}.",
              file=sys.stderr)
        raise SystemExit(1)
