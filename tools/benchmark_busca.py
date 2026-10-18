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
import shutil
import subprocess
import sys
import tempfile
import threading
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
ESCALAS = (1, 10, 100, 1000, 10000, 100000, 1000000)
ESCALAS_RAPIDAS = ESCALAS[:5]  # 100.000 e 1.000.000 só sob pedido explícito
PASTA_NOTAS = Path("05 - Padrões e Preferências") / "Aprendizados"
NOME_NOTA = re.compile(r"/Aprendizado - [a-z]+ sintético (\d+)\.md$")
BLOCO_DISCO = 4096  # cada nota ocupa um bloco APFS; o pré-cálculo de disco usa esse piso
MARGEM_DISCO = 5 * 2**30
FRACAO_MEMORIA = 0.5  # recusa uma escala cujo pico projetado passe da metade da RAM física


def atributos(i):
    return TEMAS[i % len(TEMAS)], f"Demo-{i % 7:02d}"


def nota(i):
    tema, projeto = atributos(i)
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
    return nome, texto


def gerar_corpus(base, quantidade, inicio=0):
    """Notas determinísticas. Cada escala é o prefixo da seguinte: o acervo cresce de `inicio`
    até `quantidade` sem recriar as notas já gravadas, e a descrição cobre o acervo inteiro."""
    pasta = base / PASTA_NOTAS
    if not inicio:
        pasta.mkdir(parents=True)
        protocolo = base / "00 - Regras para Agentes" / "Protocolo dos Agentes.md"
        protocolo.parent.mkdir()
        protocolo.write_text("# Protocolo sintético\nRegras de demonstração.\n", encoding="utf-8")
    for i in range(inicio, quantidade):
        nome, texto = nota(i)
        (pasta / nome).write_text(texto, encoding="utf-8")
    digest = hashlib.sha256()
    caracteres = bytes_total = arquivos = 0
    for arquivo in sorted(base.rglob("*.md")):
        dados = arquivo.read_bytes()
        caracteres += len(dados.decode("utf-8"))
        bytes_total += len(dados)
        arquivos += 1
        digest.update(str(arquivo.relative_to(base)).encode("utf-8") + b"\0" + dados + b"\0")
    return {"notas_de_conteudo": quantidade, "arquivos_markdown": arquivos,
            "caracteres": caracteres, "bytes_utf8": bytes_total, "sha256": digest.hexdigest()}


def confere(i, consulta):
    tema, projeto = atributos(i)
    return tema in consulta["termos"] and (not consulta.get("projeto") or projeto == consulta["projeto"])


def elegiveis(quantidade, consulta):
    return sum(confere(i, consulta) for i in range(quantidade))


def nota_elegivel(caminho_rel, quantidade, consulta):
    """Confere pelo nome se a nota devolvida existe nesta escala e pertence ao tema/projeto pedido."""
    achado = NOME_NOTA.search(caminho_rel)
    if not achado:
        return False
    i = int(achado.group(1))
    return (i < quantidade and caminho_rel == f"{PASTA_NOTAS}/{nota(i)[0]}" and confere(i, consulta))


def executar(script, cofre, *opcoes, termos, espera):
    """Uma busca em processo próprio, com tempo de parede, CPU e pico de memória desse processo (POSIX)."""
    comando = [sys.executable, str(script), "buscar", *termos, "--trechos", *opcoes]
    estourou = []
    with tempfile.TemporaryFile() as erros:
        inicio = time.perf_counter()
        processo = subprocess.Popen(comando, env=dict(os.environ, CEREBRO_DIR=str(cofre)),
                                    stdout=subprocess.PIPE, stderr=erros)
        prazo = threading.Timer(espera, lambda: (estourou.append(True), processo.kill()))
        prazo.start()
        try:
            saida = processo.stdout.read()
            _, estado, uso = os.wait4(processo.pid, 0)
        finally:
            prazo.cancel()
            processo.stdout.close()
        segundos = time.perf_counter() - inicio
        processo.returncode = os.waitstatus_to_exitcode(estado)
        if estourou:
            raise subprocess.TimeoutExpired(comando, espera)
        if processo.returncode:
            erros.seek(0)
            raise subprocess.CalledProcessError(processo.returncode, comando, saida, erros.read())
    rss = uso.ru_maxrss * (1 if sys.platform == "darwin" else 1024)  # bytes no macOS, KiB no Linux
    return saida.decode("utf-8"), {"segundos": round(segundos, 4),
                                   "cpu_segundos": round(uso.ru_utime + uso.ru_stime, 3),
                                   "pico_memoria_mb": round(rss / 2**20, 1)}


def tokenizador():
    """tiktoken/o200k_base, só com --tokens; na primeira vez a biblioteca pode baixar a codificação."""
    import tiktoken
    codificacao = tiktoken.get_encoding("o200k_base")
    return ({"biblioteca": f"tiktoken {tiktoken.__version__}", "codificacao": "o200k_base"},
            lambda texto: len(codificacao.encode(texto, disallowed_special=())))


def recursos_insuficientes(pasta, quantidade, gerado, medidas):
    """Motivo para não executar a escala, ou None. O pico de memória é projetado linearmente
    a partir das duas maiores escalas já medidas; sem duas medidas, só o disco é conferido."""
    necessario = (quantidade - gerado) * BLOCO_DISCO
    livre = shutil.disk_usage(pasta).free
    if livre - necessario < MARGEM_DISCO:
        return (f"disco: precisa de ~{necessario / 2**30:.1f} GiB e deixaria menos de "
                f"{MARGEM_DISCO / 2**30:.0f} GiB livres ({livre / 2**30:.1f} GiB disponíveis)")
    if len(medidas) >= 2:
        (n1, p1), (n2, p2) = medidas[-2:]
        projetado = p2 + (p2 - p1) / (n2 - n1) * (quantidade - n2)
        try:
            ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**20
        except (OSError, ValueError):
            return None
        if projetado > FRACAO_MEMORIA * ram:
            return (f"memória: pico projetado de ~{projetado:,.0f} MB por busca passa de "
                    f"{FRACAO_MEMORIA:.0%} da RAM física ({ram:,.0f} MB)")
    return None


def carregar_parcial(parcial, identidade):
    """Escalas já medidas por esta mesma implementação; outra identidade invalida o arquivo."""
    if not parcial or not Path(parcial).is_file():
        return {}
    dados = json.loads(Path(parcial).read_text(encoding="utf-8"))
    if dados.get("identidade") != identidade:
        print("Arquivo parcial de outra implementação ou configuração; recomeçando.", file=sys.stderr)
        return {}
    return {e["corpus"]["notas_de_conteudo"]: e for e in dados["escalas"]}


def salvar_parcial(parcial, identidade, escalas):
    if parcial:
        temporario = Path(f"{parcial}.tmp")
        temporario.write_text(json.dumps({"identidade": identidade, "escalas": escalas},
                                         ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporario, parcial)


def somar(consultas, campo, versao, juntar=sum):
    return juntar(c[campo][versao] for c in consultas)


def agregar(consultas, tokens):
    antes, depois = sum(c["antes"] for c in consultas), sum(c["depois"] for c in consultas)
    agregado = {"antes": antes, "depois": depois, "caracteres_a_menos": antes - depois,
                "reducao_percentual": round(100 * (1 - depois / antes), 1)}
    if tokens:
        t_antes, t_depois = somar(consultas, "tokens", "antes"), somar(consultas, "tokens", "depois")
        agregado["tokens"] = {"antes": t_antes, "depois": t_depois, "tokens_a_menos": t_antes - t_depois,
                              "reducao_percentual": round(100 * (1 - t_depois / t_antes), 1)}
    if all("cpu_segundos" in c for c in consultas):
        agregado["recursos"] = {versao: {
            "segundos_total": round(somar(consultas, "segundos_observados", versao), 3),
            "cpu_segundos_total": round(somar(consultas, "cpu_segundos", versao), 3),
            "pico_memoria_mb_maximo": somar(consultas, "pico_memoria_mb", versao, max),
        } for versao in ("antes", "depois")}
    return agregado


def medir_ampliado(quantidades=ESCALAS_RAPIDAS, parcial=None, contar_tokens=False, espera=3600):
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    anterior = subprocess.run(
        ["git", "-C", str(RAIZ), "show", f"{REFERENCIA}:tools/cerebro.py"],
        capture_output=True, timeout=10, check=True,
    ).stdout
    descricao, contar = tokenizador() if contar_tokens else (None, None)
    escalas, nao_executadas = [], []
    # ".noindex" evita que o Spotlight indexe o acervo temporário.
    with tempfile.TemporaryDirectory(prefix="cerebro-escala-", suffix=".noindex") as pasta:
        raiz = Path(pasta)
        referencia = raiz / "anterior.py"
        referencia.write_bytes(anterior)
        # Uma edição de outra tarefa durante o ensaio não pode trocar o núcleo entre consultas.
        atual = raiz / "atual.py"
        atual.write_bytes((RAIZ / "tools/cerebro.py").read_bytes())
        nucleo_hash = hashlib.sha256(atual.read_bytes()).hexdigest()
        identidade = {"referencia_git": REFERENCIA, "nucleo_atual_sha256": nucleo_hash,
                      "script_sha256": script_hash, "python": sys.version.split()[0], "tokenizador": descricao}
        concluidas = carregar_parcial(parcial, identidade)
        base, gerado, medidas = raiz / "cofre", 0, []
        for quantidade in sorted(quantidades):
            if quantidade in concluidas:
                escala = concluidas[quantidade]
                print(f"Retomado: {quantidade:,} notas já medidas no arquivo parcial.", file=sys.stderr, flush=True)
            else:
                motivo = recursos_insuficientes(raiz, quantidade, gerado, medidas)
                if motivo:
                    nao_executadas += [{"notas_de_conteudo": q, "motivo": motivo if q == quantidade else
                                        "escala anterior não executada"} for q in sorted(quantidades) if q >= quantidade]
                    print(f"Interrompido antes de {quantidade:,} notas: {motivo}.", file=sys.stderr, flush=True)
                    break
                print(f"Gerando {quantidade:,} notas sintéticas ({gerado:,} já gravadas).", file=sys.stderr, flush=True)
                inicio = time.perf_counter()
                corpus = gerar_corpus(base, quantidade, gerado)
                corpus["segundos_para_gerar_e_conferir"] = round(time.perf_counter() - inicio, 1)
                gerado = quantidade
                escala = {"corpus": corpus,
                          "consultas": medir_escala(referencia, atual, base, quantidade, contar, espera)}
                escala["agregado"] = agregar(escala["consultas"], contar)
                salvar_parcial(parcial, identidade, [*escalas, escala])
                print(f"Conferido: {quantidade:,} notas, {len(CONSULTAS)} consultas pareadas.", file=sys.stderr, flush=True)
            escalas.append(escala)
            if "recursos" in escala["agregado"]:
                medidas.append((quantidade, max(escala["agregado"]["recursos"][v]["pico_memoria_mb_maximo"]
                                                for v in ("antes", "depois"))))
    antes = sum(e["agregado"]["antes"] for e in escalas)
    depois = sum(e["agregado"]["depois"] for e in escalas)
    total = {"consultas_pareadas": len(escalas) * len(CONSULTAS), "execucoes": len(escalas) * len(CONSULTAS) * 2,
             "antes": antes, "depois": depois, "caracteres_a_menos": antes - depois,
             "reducao_percentual": round(100 * (1 - depois / antes), 1) if antes else None,
             "mesmas_notas_e_trechos_em_todas": True}
    if contar and escalas:
        t_antes = sum(e["agregado"]["tokens"]["antes"] for e in escalas)
        t_depois = sum(e["agregado"]["tokens"]["depois"] for e in escalas)
        total["tokens"] = {"antes": t_antes, "depois": t_depois, "tokens_a_menos": t_antes - t_depois,
                           "reducao_percentual": round(100 * (1 - t_depois / t_antes), 1)}
    return {"cenario": f"{len(escalas)} escalas sintéticas determinísticas, {len(CONSULTAS)} consultas por escala",
            "referencia_git": REFERENCIA, "nucleo_atual_sha256": nucleo_hash,
            "script_sha256": script_hash,
            "ambiente": {"python": sys.version.split()[0], "plataforma": sys.platform},
            "opcoes_por_consulta": {"max_notas": 5, "orcamento_caracteres": 12000},
            "tokenizador": descricao,
            "escalas": escalas, "nao_executadas": nao_executadas, "total": total,
            "limites": ["Corpora inteiramente sintéticos; cada escala é o prefixo da seguinte.",
                        "O acervo cresce num único diretório temporário; cada escala é medida sobre exatamente "
                        "o seu prefixo, igual a gerar a escala do zero.",
                        "O tamanho do maior corpus é contado uma vez, sem multiplicar pelas consultas.",
                        "As saídas incluem omissões, resumo e quebras de linha.",
                        "Tokens, quando presentes, usam o200k_base (tiktoken), não o tokenizador do Claude, "
                        "e medem só a saída da busca, não a conversa inteira.",
                        "Tempo, CPU e memória: uma passagem por caso, sem controle de cache nem repetições "
                        "estatísticas; incluem a inicialização do Python.",
                        "Não mede inferências, produtividade, qualidade geral das IAs ou economia financeira."]}


def medir_escala(referencia, atual, base, quantidade, contar, espera=3600):
    resultados = []
    for indice, consulta in enumerate(CONSULTAS):
        opcoes = ["--max", "5", "--orcamento", "12000"]
        if consulta.get("projeto"):
            opcoes += ["--projeto", consulta["projeto"]]
        # Alterna a ordem para reduzir o favorecimento sistemático pelo cache do disco.
        ordem = [("antes", referencia), ("depois", atual)]
        if indice % 2:
            ordem.reverse()
        saidas, recursos = {}, {}
        for versao, script in ordem:
            saidas[versao], recursos[versao] = executar(script, base, *opcoes, termos=consulta["termos"],
                                                        espera=espera)
            print(f"{quantidade:,} notas, consulta {indice + 1}/{len(CONSULTAS)}, {versao}: "
                  f"{recursos[versao]['segundos']}s, {recursos[versao]['pico_memoria_mb']} MB.",
                  file=sys.stderr, flush=True)
        nomes, linhas = conteudo(saidas["antes"])
        total_elegiveis = elegiveis(quantidade, consulta)
        if (conteudo(saidas["depois"]) != (nomes, linhas) or
                len(nomes) != min(5, total_elegiveis) or
                not all(nota_elegivel(nome, quantidade, consulta) for nome in nomes) or
                len(linhas) != 4 * len(nomes)):
            raise ValueError(f"Seleção divergente ou incorreta: {quantidade} notas, {consulta}")
        if any(len(saida) > 12000 for saida in saidas.values()):
            raise ValueError("Saída ultrapassou o orçamento combinado.")
        antes, depois = len(saidas["antes"]), len(saidas["depois"])
        resultado = {**consulta, "notas_elegiveis": total_elegiveis,
                     "notas_selecionadas": len(nomes), "trechos": len(linhas),
                     "mesmas_notas_e_trechos": True, "antes": antes, "depois": depois,
                     "reducao_percentual": round(100 * (1 - depois / antes), 1)}
        if contar:
            resultado["tokens"] = {versao: contar(saidas[versao]) for versao in ("antes", "depois")}
        resultado["segundos_observados"] = {v: recursos[v]["segundos"] for v in recursos}
        resultado["cpu_segundos"] = {v: recursos[v]["cpu_segundos"] for v in recursos}
        resultado["pico_memoria_mb"] = {v: recursos[v]["pico_memoria_mb"] for v in recursos}
        resultados.append(resultado)
    return resultados


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ampliado", action="store_true",
                        help="1, 10, 100, 1.000 e 10.000 notas; 40 consultas pareadas em cerca de um minuto")
    parser.add_argument("--completo", action="store_true",
                        help="as sete escalas, até 1.000.000 de notas: ~4 GB temporários e horas de execução")
    parser.add_argument("--escalas", nargs="+", type=int,
                        help="escalas explícitas, de 1 a 1.000.000 (ex.: 40 1000 10000 reproduz o ensaio anterior)")
    parser.add_argument("--parcial", help="arquivo de progresso: grava cada escala concluída e retoma dele")
    parser.add_argument("--tokens", action="store_true",
                        help="conta tokens o200k_base com tiktoken instalado à parte (não é o tokenizador do Claude)")
    parser.add_argument("--espera", type=int, default=3600,
                        help="limite por busca, em segundos (padrão 3600); 1.000.000 de notas pede várias horas")
    args = parser.parse_args()
    if args.escalas and (len(set(args.escalas)) != len(args.escalas) or
                         not all(1 <= q <= ESCALAS[-1] for q in args.escalas)):
        parser.error("cada escala deve aparecer uma única vez, entre 1 e 1.000.000")
    escolhidas = tuple(args.escalas or (ESCALAS if args.completo else ESCALAS_RAPIDAS))
    try:
        print(json.dumps(medir_ampliado(escolhidas, args.parcial, args.tokens, args.espera)
                         if args.ampliado or args.completo or args.escalas else medir(),
                         ensure_ascii=False, indent=2))
    except ImportError:
        print("--tokens requer a biblioteca tiktoken; o benchmark em caracteres não precisa dela.", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, subprocess.SubprocessError, ValueError) as erro:
        print(f"Benchmark não concluído: {erro}\nUse um clone Git que contenha a revisão {REFERENCIA}.",
              file=sys.stderr)
        raise SystemExit(1)
