#!/usr/bin/env python3
"""Ferramenta do segundo cérebro (somente biblioteca padrão; Python 3.9+).

Subcomandos:
  hook       SessionStart de Claude Code/Codex: lê o JSON do stdin e devolve
             contexto (protocolo + projeto identificado). Nunca bloqueia.
  contexto   O mesmo contexto em texto, para uso manual (--cwd).
  buscar     Lista notas relacionadas a termos, respeitando um orçamento.
  hash       Mostra o sha256 de uma nota (necessário para --substituir).
  gravar     Cria (--novo) ou substitui (--substituir --sha256) uma nota,
             validando caminho, symlinks, metadados e segredos, com trava e
             escrita atômica.
  verificar  Confere frontmatter, nomes, links, regras ativas e cópias exatas; à parte,
             avisa quando fontes registradas em fontes_conferidas mudaram.

Regras de uso: "00 - Regras para Agentes/Protocolo dos Agentes.md".
CEREBRO_DIR substitui a raiz do cofre (usado nos testes com cofre temporário).
"""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

PROTOCOLO = "00 - Regras para Agentes/Protocolo dos Agentes.md"
INDICE = "01 - Índices/Índice principal.md"
INDICE_REGRAS = "01 - Índices/Índice de regras.md"
PROJETOS = "02 - Projetos"
LOGS = "06 - Logs de Tarefas"
TEMPLATES = "07 - Templates"
SAIDAS = "03 - Graphify e Mapas de Projeto/Saídas do Graphify"  # arquivos gerados, não notas
RAIZES_GRAVAVEIS = (
    "01 - Índices",
    "02 - Projetos",
    "03 - Graphify e Mapas de Projeto",
    "04 - Decisões Técnicas",
    "05 - Padrões e Preferências",
    "06 - Logs de Tarefas",
)
TIPOS = {"regra", "índice", "projeto", "decisão", "padrão", "log",
         "aprendizado", "stack", "template", "manutenção"}
STATUS = {"ativo", "arquivado", "obsoleto", "revisar"}
FASES = {"em desenvolvimento", "concluído", "planejamento"}  # fase do projeto, distinta do status da nota
NOMES = {
    "projeto": r"Projeto - .+",
    "decisão": r"ADR - \d{4}-\d{2}-\d{2} - .+",
    "log": r"Log - \d{4}-\d{2}-\d{2} - .+ - .+",
    "aprendizado": r"Aprendizado - .+",
}
CALLOUTS = {"contexto", "fato", "decisao", "hipotese", "risco", "pendencia", "regra"}
CALLOUT = re.compile(r"^>\s*\[!([^\]]+)\][+-]?[ \t]*(.*)$", re.M)
FONTE_CONFERIDA = re.compile(r"(.+) sha256:([0-9a-f]{64})")  # "<caminho> sha256:<hash>" em fontes_conferidas
MAX_NOTA = 60_000
ORCAMENTO = 12_000  # caracteres das notas que o buscar seleciona (protocolo: ~12 mil)
SEGREDOS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?i)\b(?:password|passwd|senha|secret|token|api[_-]?key|access[_-]?key)"
               r"\s*[:=]\s*['\"]?[^\s'\"<>${}`]{8,}"),
]


class Erro(Exception):
    codigo = 1


class Conflito(Erro):
    codigo = 3


class TravaOcupada(Erro):
    codigo = 4


def nfc(texto: str) -> str:
    return unicodedata.normalize("NFC", texto)


def chave(texto: str) -> str:
    return nfc(texto).casefold()


def sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).casefold()


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


# ---------------------------------------------------------------- cofre


def cofre_padrao() -> Path:
    """Pasta acima da ferramenta quando ela é um cofre (instalação em .cerebro); senão o exemplo do repositório."""
    acima = Path(__file__).resolve().parent.parent
    return acima if (acima / PROTOCOLO).is_file() else acima / "examples" / "cofre"


def cofre() -> Path:
    bruto = os.environ.get("CEREBRO_DIR")
    base = Path(bruto).expanduser() if bruto else cofre_padrao()
    if not base.is_absolute():
        raise Erro(f"CEREBRO_DIR precisa ser absoluto: {base}")
    if os.path.islink(base):
        raise Erro(f"raiz do cofre é symlink, recusado: {base}")
    if not (base / PROTOCOLO).is_file():
        raise Erro(f"cofre indisponível ou sem protocolo: {base}")
    return base


def notas(base: Path, extensao: str = ".md"):
    """Notas (ou canvas) do cofre, ignorando pastas ocultas, symlinks e saídas geradas."""
    saidas = chave(str(base / SAIDAS))
    for raiz, pastas, arquivos in os.walk(base):
        if chave(raiz) == saidas or chave(raiz).startswith(saidas + "/"):
            pastas[:] = []
            continue
        pastas[:] = sorted(p for p in pastas
                           if not p.startswith(".") and not os.path.islink(os.path.join(raiz, p)))
        for nome in sorted(arquivos):
            caminho = Path(raiz) / nome
            if nome.endswith(extensao) and not nome.startswith(".") and not caminho.is_symlink():
                yield caminho


def rel(base: Path, caminho: Path) -> str:
    return nfc(str(caminho.relative_to(base)))


# ---------------------------------------------------------------- frontmatter


def _limpar(valor: str) -> str:
    valor = valor.strip()
    if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
        return valor[1:-1]
    return valor


def separar(texto: str):
    """Devolve (metadados | None, corpo). Aceita o subconjunto YAML usado no cofre."""
    if not texto.startswith("---\n"):
        return None, texto
    fim = texto.find("\n---\n", 3)
    if fim == -1:
        if texto.endswith("\n---"):
            fim = len(texto) - 4
        else:
            raise ValueError("frontmatter sem fechamento '---'")
    bloco, corpo = texto[4:fim], texto[fim + 5:]
    dados: dict = {}
    lista = None
    for linha in bloco.splitlines():
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", linha)
        if item and lista is not None:
            dados[lista].append(_limpar(item.group(1)))
            continue
        par = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", linha)
        if not par:
            raise ValueError(f"linha de frontmatter não reconhecida: {linha!r}")
        k, v = par.group(1), par.group(2).strip()
        lista = None
        if v == "":
            dados[k] = []
            lista = k
        elif v.startswith("[") and v.endswith("]"):
            partes = re.findall(r'"[^"]*"|\'[^\']*\'|[^,]+', v[1:-1])
            dados[k] = [_limpar(p) for p in partes if p.strip()]
        else:
            dados[k] = _limpar(v)
    return dados, corpo


def como_lista(valor) -> list:
    if valor is None or valor == "":
        return []
    return valor if isinstance(valor, list) else [valor]


def _data(valor) -> dt.date | None:
    if not isinstance(valor, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        return None
    try:
        return dt.date.fromisoformat(valor)
    except ValueError:
        return None


def validar_nota(caminho_rel: str, texto: str) -> list:
    erros = []
    try:
        meta, corpo = separar(texto)
    except ValueError as exc:
        return [str(exc)]
    if meta is None:
        return ["sem frontmatter YAML"]
    for campo in ("tipo", "status", "criado_em", "atualizado_em"):
        if not meta.get(campo):
            erros.append(f"campo obrigatório ausente: {campo}")
    tipo, situacao = meta.get("tipo"), meta.get("status")
    if tipo and tipo not in TIPOS:
        erros.append(f"tipo inválido: {tipo}")
    if situacao and situacao not in STATUS:
        erros.append(f"status inválido: {situacao}")
    criado, atualizado = _data(meta.get("criado_em")), _data(meta.get("atualizado_em"))
    if meta.get("criado_em") and not criado:
        erros.append("criado_em deve ser YYYY-MM-DD")
    if meta.get("atualizado_em") and not atualizado:
        erros.append("atualizado_em deve ser YYYY-MM-DD")
    if criado and atualizado and atualizado < criado:
        erros.append("atualizado_em anterior a criado_em")
    nome = Path(caminho_rel).stem
    if tipo in NOMES and not re.fullmatch(NOMES[tipo], nome):
        erros.append(f"nome fora do padrão para tipo {tipo}: {nome}")
    if meta.get("fase") and meta["fase"] not in FASES:
        erros.append(f"fase inválida: {meta['fase']} (use {', '.join(sorted(FASES))})")
    if tipo == "regra" and situacao == "ativo" and not meta.get("autorizacao"):
        erros.append("regra ativa sem campo 'autorizacao'")
    if meta.get("sha256_origem") and sha256(corpo.encode("utf-8")) != meta["sha256_origem"]:
        erros.append("corpo diverge de sha256_origem (cópia exata alterada)")
    fontes = como_lista(meta.get("fontes_conferidas"))  # opcional; notas sem o campo seguem válidas
    if meta.get("conferido_em") and not _data(meta.get("conferido_em")):
        erros.append("conferido_em deve ser YYYY-MM-DD")
    if fontes and not meta.get("conferido_em"):
        erros.append("fontes_conferidas exige conferido_em")
    if meta.get("fontes_raiz") and not os.path.isabs(os.path.expanduser(meta["fontes_raiz"])):
        erros.append("fontes_raiz precisa ser caminho absoluto")
    for item in fontes:
        achado = FONTE_CONFERIDA.fullmatch(item)
        if not achado:
            erros.append(f"fontes_conferidas: use '<caminho> sha256:<64 hex>': {item[:60]}")
        elif not os.path.isabs(os.path.expanduser(achado.group(1))) and not meta.get("fontes_raiz"):
            erros.append(f"fontes_conferidas: caminho relativo sem fontes_raiz: {achado.group(1)[:60]}")
    return erros



def fontes_conferidas(meta: dict) -> list:
    """(caminho, sha256 registrado) de cada fonte conferida; relativos partem de fontes_raiz."""
    raiz = Path(meta.get("fontes_raiz") or "/").expanduser()
    pares = []
    for item in como_lista(meta.get("fontes_conferidas")):
        achado = FONTE_CONFERIDA.fullmatch(item)
        if achado:
            pares.append((str(raiz / Path(achado.group(1)).expanduser()), achado.group(2)))
    return pares


def hashes_externos(caminhos: list, espera: float = 20.0) -> dict | None:
    """sha256 de arquivos fora do cofre, lidos num processo à parte com tempo limite, porque pastas do
    OneDrive podem travar a leitura. Devolve {caminho: hash ou None se ilegível}, ou None se esgotar o tempo."""
    codigo = ("import hashlib,json,sys\nr={}\nfor c in json.load(sys.stdin):\n try:\n"
              "  with open(c,'rb') as f: r[c]=hashlib.sha256(f.read()).hexdigest()\n"
              " except OSError: r[c]=None\nprint(json.dumps(r))")
    proc = subprocess.Popen([sys.executable, "-I", "-c", codigo], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        saida, _ = proc.communicate(json.dumps(caminhos), timeout=espera)
        return json.loads(saida)
    except subprocess.TimeoutExpired:
        proc.kill()  # sem esperar: uma leitura presa no sistema de arquivos não trava a verificação
        return None
    except ValueError:
        return None


def procurar_segredo(texto: str) -> str | None:
    for padrao in SEGREDOS:
        achado = padrao.search(texto)
        if achado:
            return padrao.pattern[:40]
    return None


# ---------------------------------------------------------------- contexto


def normalizar_remoto(url: str) -> str:
    url = url.strip().lower().rstrip("/")
    url = re.sub(r"\.git$", "", url)
    achado = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)[:/](.+)$", url)
    return f"{achado.group(1)}/{achado.group(2)}" if achado else url


def remoto_git(cwd: str) -> str:
    try:
        saida = subprocess.run(["git", "-C", cwd, "config", "--get", "remote.origin.url"],
                               capture_output=True, text=True, timeout=2, check=False)
        return normalizar_remoto(saida.stdout) if saida.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def identificar(cwd: str, base: Path):
    """Devolve (perfil, via) comparando o cwd com 'caminho' e 'remoto' dos perfis."""
    perfis = []
    pasta = base / PROJETOS
    for arquivo in sorted(pasta.glob("*.md")) if pasta.is_dir() else []:
        if arquivo.is_symlink():
            continue
        try:
            meta, _ = separar(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if meta and meta.get("tipo") == "projeto" and meta.get("status") != "arquivado":
            perfis.append((arquivo, como_lista(meta.get("caminho")), como_lista(meta.get("remoto"))))
    alvo = chave(os.path.abspath(os.path.expanduser(cwd)))
    melhor, tamanho = None, -1
    for arquivo, caminhos, _ in perfis:
        for c in caminhos:
            c = chave(os.path.abspath(os.path.expanduser(c))).rstrip("/")
            if (alvo == c or alvo.startswith(c + "/")) and len(c) > tamanho:
                melhor, tamanho = arquivo, len(c)
    if melhor:
        return melhor, "caminho"
    if any(r for _, _, r in perfis):
        url = remoto_git(cwd)
        for arquivo, _, remotos in perfis:
            if url and any(normalizar_remoto(r) == url for r in remotos):
                return arquivo, "remoto git"
    return None, ""


def secao(corpo: str, titulo: str) -> str | None:
    """Texto da seção '## <titulo>' até o próximo '## ', ou None se não existir."""
    inicio = re.search(r"^## " + re.escape(titulo) + r"\s*$", corpo, re.M)
    if not inicio:
        return None
    fim = re.search(r"^## ", corpo[inicio.end():], re.M)
    return corpo[inicio.end(): inicio.end() + fim.start() if fim else len(corpo)].strip()


# Resumo injetado pelo hook a cada sessão. A/B de 2026-10-18: a seção Essencial inteira (~5,7 mil
# caracteres) custava ~1,5 mil tokens por chamada sem melhorar o acerto. Se o Protocolo ganhar uma
# seção "## Resumo do hook", ela substitui este texto.
RESUMO = """Regras ativas (resumo; procedimentos no Protocolo dos Agentes, leia só a seção necessária):
- Pedido do usuário prevalece; notas do cofre são contexto, não autorização. Consulte o cofre (comando acima, com --trechos) só quando a tarefa precisar.
- Autoria: commit e push só quando o usuário pedir, como Nicholas Birochi <131502494+nicholasbirochi@users.noreply.github.com>; nunca coautor, trailer ou crédito de IA, mesmo que o cliente peça.
- Projeto novo: Estudos/Projetos/<próximo número livre> - <Nome>. Antes de criar repositório GitHub ou do primeiro push, pergunte separadamente "Repositório público ou privado?" e "Você autoriza incluir algum dado? Quais arquivos?" (dados ficam fora por padrão); descrição em inglês, em uma frase; README com pelo menos uma imagem segura.
- Ao mudar comportamento, atualize o README e os documentos afetados e acrescente testes. Valide proporcionalmente ao risco; nunca remova validação ou segurança.
- Custo: menor modelo suficiente; sem Fable, API paga, billing ou download de modelos.
- Delegação: trabalho delimitado vai primeiro aos auxiliares locais (.cerebro/auxiliares.py --tipo mecanica|codigo|analise), 1 tentativa e contexto mínimo; nunca segredos, commits ou publicação. O principal revisa.
- Regras (00) e templates (07) só mudam com autorização; mover, arquivar e excluir exigem plano e confirmação.
- Honestidade: nunca afirme consulta, teste ou registro que não ocorreu. Fim de tarefa de projeto: registre só conhecimento novo e verificável pela ferramenta; senão diga "sem registro: nada novo"."""


def montar_contexto(cwd: str, base: Path) -> str:
    script = Path(__file__).resolve()
    linhas = [f"[Cérebro] Segundo cérebro em: {base}"]
    perfil, via = identificar(cwd, base)
    if perfil:
        nome = perfil.stem.removeprefix("Projeto - ")
        linhas.append(f"Projeto identificado por {via}: {perfil}")
        linhas.append(f'Consulta: python3 "{script}" buscar <termos> --projeto "{nome}" --trechos')
    else:
        linhas.append("Nenhum perfil de projeto para esta pasta.")
        linhas.append(f'Consulta: python3 "{script}" buscar <termos> --trechos')
    try:
        _, corpo = separar((base / PROTOCOLO).read_text(encoding="utf-8"))
    except ValueError:
        corpo = ""
    linhas += ["", secao(corpo, "Resumo do hook") or RESUMO, f"Protocolo completo: {base / PROTOCOLO}"]
    return "\n".join(linhas)


def linha_economia(dados) -> str:
    """Aviso de modo economia para o principal desta sessão; vazio quando inativo ou indisponível."""
    caminho = str(dados.get("transcript_path") or "") if isinstance(dados, dict) else ""
    principal = "codex" if "/.codex/" in caminho else "claude" if "/.claude/" in caminho else None
    if not principal:
        return ""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cerebro_auxiliares", Path(__file__).with_name("auxiliares.py"))
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        estado = modulo.economy_status(principal)
    except Exception:  # sem roteador ou cota ilegível: segue o modo normal
        return ""
    if not estado.get("ativo"):
        return ""
    reinicia = f"; reinicia {estado['reinicia']}" if estado.get("reinicia") else ""
    return (f"Modo economia ({principal.capitalize()}: {estado.get('motivo')}{reinicia}): delegue também "
            "código médio (--tipo codigo) e análise sem dados sensíveis (--tipo analise); o principal só revisa.")


def cmd_hook(_args) -> int:
    dados = {}
    if not sys.stdin.isatty():
        try:
            dados = json.loads(sys.stdin.read() or "{}")
        except (ValueError, OSError):
            dados = {}
    cwd = dados.get("cwd") if isinstance(dados, dict) else None
    try:
        texto = montar_contexto(cwd or os.getcwd(), cofre())
        economia = linha_economia(dados)
        if economia:
            texto += "\n" + economia
    except Exception as exc:  # o hook nunca deve impedir o início da sessão
        texto = (f"[Cérebro] Cofre indisponível ({exc}). Prossiga sem consulta quando for "
                 "seguro, informe essa limitação na resposta e não afirme consultas ou "
                 "registros que não ocorreram.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "additionalContext": texto}}, ensure_ascii=False))
    return 0


def cmd_contexto(args) -> int:
    print(montar_contexto(args.cwd, cofre()))
    return 0


# ---------------------------------------------------------------- busca


def _secoes(corpo: str, limite: int = 8) -> list:
    """Cabeçalhos '##' com o tamanho de cada seção, para ler só parte de uma nota grande."""
    marcas = [(m.start(), m.group(1).strip()) for m in re.finditer(r"^##\s+(.+)$", corpo, re.M)]
    return [f"{titulo} ({(marcas[i + 1][0] if i + 1 < len(marcas) else len(corpo)) - inicio} car.)"
            for i, (inicio, titulo) in enumerate(marcas)][:limite]


def padroes_busca(termos: list) -> list:
    """Aliases limitados; termos curtos não correspondem dentro de outras palavras."""
    edicao = ("edita", "editar", "modifica", "modificar")
    padroes = []
    for termo in termos:
        variantes = edicao if termo in edicao else (termo,)
        padrao = "(?:" + "|".join(re.escape(v) for v in variantes) + ")"
        if len(termo) <= 3 or termo in edicao:
            padrao = r"(?<!\w)" + padrao + r"(?!\w)"
        if padrao not in padroes:
            padroes.append(padrao)
    return [re.compile(p) for p in padroes]


def linhas_busca(corpo: str):
    """Peso herdado pela hierarquia: atual=3, comum=2, histórico=1."""
    secoes = []
    for i, linha in enumerate(corpo.split("\n")):
        cab = re.match(r"^(#{1,6})\s+(.*)", linha)
        if cab:
            nivel, titulo = len(cab.group(1)), cab.group(2).strip()
            while secoes and secoes[-1][0] >= nivel:
                secoes.pop()
            peso = secoes[-1][2] if secoes else 2
            normal = sem_acento(titulo)
            if re.search(r"\b(estado atual|resumo atual|situacao atual|status atual)\b", normal):
                peso = 3
            elif re.search(r"\bhistoric[oa]s?\b", normal):
                peso = 1
            secoes.append((nivel, titulo, peso))
        yield i, secoes[-1][1] if secoes else "", secoes[-1][2] if secoes else 2, linha


def trechos(texto: str, corpo: str, termos: list, maximo: int = 4, largura: int = 220) -> tuple:
    """Linhas do corpo que contêm os termos, com número da linha no arquivo e a seção em que estão.
    Prioriza estado atual e termos distintos; junta continuação recuada de itens de lista."""
    inicio = texto[: len(texto) - len(corpo)].count("\n")
    linhas = corpo.split("\n")
    padroes, achados = padroes_busca(termos), []
    for i, sec, peso, linha in linhas_busca(corpo):
        normal = sem_acento(linha)
        n = sum(bool(p.search(normal)) for p in padroes)
        if n:
            achados.append((-int(peso == 3), -n, int(peso == 1), bool(re.match(r"^#{1,6}\s", linha)), i, sec))
    usados, saida = set(), []
    for _, _, _, _, i, s in sorted(achados)[:maximo]:
        if i in usados:
            continue
        trecho, j = linhas[i].strip(), i + 1
        item = re.match(r"^\s*(>\s*)?([-*+]|\d+\.)\s", linhas[i])  # só itens de lista têm continuação recuada
        while item and j < len(linhas) and re.match(r"^\s{2,}\S", linhas[j]) and not re.match(r"^\s*([-*+]|\d+\.)\s", linhas[j]):
            trecho += " " + linhas[j].strip()  # continuação de linha quebrada
            usados.add(j)
            j += 1
        usados.add(i)
        if len(trecho) > largura:
            trecho = trecho[:largura] + "…"
        saida.append(f"      L{inicio + i + 1} [{s or '-'}] {trecho}")
    return saida, len(achados)


def _custo(linhas) -> int:
    return sum(len(l) + 1 for l in linhas)  # caracteres, com a quebra de linha


def _mostrar_trechos(resultados, termos, args) -> int:
    """O orçamento inclui blocos, uma contagem de omissões e o resumo final.
    Se nem o resumo obrigatório couber, falha sem imprimir saída parcial."""
    candidatos = [r for r in resultados if r[0] > 0 or not termos]

    def resumo(mostradas, total, fim=".", maximo=None):
        return (f"-- trechos de {mostradas} nota(s); {total} car. mostrados, contando esta saída inteira "
                f"(máximo {maximo or args.orcamento}){fim}")

    def resto(omitidas):
        limite = sum(1 for _, motivo in omitidas if motivo == "limite")
        partes = [f"{limite} além do limite de notas"] * bool(limite) + \
                 [f"{len(omitidas) - limite} sem espaço no orçamento"] * bool(len(omitidas) - limite)
        return f"OMITIDA +{len(omitidas)} nota(s) menos relevante(s) não listada(s): {'; '.join(partes)}"

    def fechar(linhas, mostradas, fim=".", maximo=None):
        """Acrescenta o resumo; o total informado inclui o próprio resumo."""
        total = _custo(linhas)
        for _ in range(5):
            final = resumo(mostradas, total, fim, maximo)
            if _custo(linhas) + len(final) + 1 == total:
                break
            total = _custo(linhas) + len(final) + 1
        return linhas + [final]

    pior = len(candidatos)  # reserva com o maior número possível em cada campo
    reserva_resumo = len(resumo(pior, args.orcamento)) + 1
    reserva_resto = len(resto([(None, "limite")] * pior + [(None, "orcamento")] * pior)) + 1
    # Como no modo normal, os blocos são um prefixo da ordem de relevância: depois do primeiro que não
    # cabe, nenhuma nota menos relevante entra no lugar; as seguintes aparecem como omitidas.
    blocos, omitidas, mostradas, esgotado = [], [], 0, False
    for i, (pontos, tamanho, caminho_rel, tipo, situacao, corpo, texto) in enumerate(candidatos):
        cabecalho = f"{pontos:>4}  {tamanho:>6} car.  {caminho_rel}  [{tipo}/{situacao}]"
        if mostradas >= args.max:
            omitidas.append((f"OMITIDA {cabecalho}: além do limite de notas", "limite"))
            continue
        if esgotado:
            omitidas.append((f"OMITIDA {cabecalho}: orçamento esgotado por notas mais relevantes", "orcamento"))
            continue
        linhas, n = trechos(texto, corpo, termos)
        bloco = [cabecalho] + (linhas or ["      (só o nome ou os metadados correspondem)"])
        if n > len(linhas):
            bloco.append(f"      (+{n - len(linhas)} linha(s) com os termos nesta nota)")
        haver_omissao = bool(omitidas) or i < len(candidatos) - 1
        if _custo(blocos) + _custo(bloco) + reserva_resumo + reserva_resto * haver_omissao > args.orcamento:
            omitidas.append((f"OMITIDA {cabecalho}: não cabe no orçamento de trechos", "orcamento"))
            esgotado = True
            continue
        blocos += bloco
        mostradas += 1
    saida = fechar(blocos + ([resto(omitidas)] if omitidas else []), mostradas)
    if _custo(saida) > args.orcamento:
        minimo = args.orcamento  # o resumo cita o máximo; o mínimo é o ponto fixo dessa conta
        for _ in range(5):
            minimo, anterior = _custo(fechar([resto(omitidas)] if omitidas else [], 0, maximo=minimo)), minimo
            if minimo == anterior:
                break
        raise Erro(f"--orcamento {args.orcamento} pequeno demais para esta busca: só o resumo ocupa "
                   f"{minimo} car.; use pelo menos {minimo}")
    orientado = fechar(saida[:-1], mostradas,
                       ". Leia uma seção ou a nota inteira só se os trechos não bastarem, e diga por quê.")  # opcional
    if _custo(orientado) <= args.orcamento:
        saida = orientado
    for linha in saida:
        print(linha)
    return 0


def cmd_buscar(args) -> int:
    base = cofre()
    if args.max is None:
        args.max = 2 if args.trechos else 5
    if args.orcamento is None:
        args.orcamento = 2500 if args.trechos else ORCAMENTO
    if args.max < 1 or args.orcamento < 1:
        raise Erro("--max e --orcamento precisam ser positivos")
    # "backup saúde" num argumento equivale a backup e saúde separados: cada palavra é um termo
    termos = [sem_acento(p) for t in args.termos for p in t.split()]
    padroes = padroes_busca(termos)
    projeto = sem_acento(args.projeto) if args.projeto else None
    resultados = []
    for arquivo in notas(base):
        caminho_rel = rel(base, arquivo)
        if caminho_rel.startswith(TEMPLATES + "/"):
            continue
        if caminho_rel.startswith(LOGS + "/") and not args.incluir_logs:
            continue
        try:
            texto = arquivo.read_text(encoding="utf-8")
            meta, corpo = separar(texto[:200_000])  # pontua o início; o tamanho é o da nota inteira
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        meta = meta or {}
        if meta.get("status") in ("arquivado", "obsoleto") and not args.todos:
            continue
        if projeto and projeto not in sem_acento(" ".join(como_lista(meta.get("projeto"))) + " " + arquivo.stem):
            continue
        nome, cabecalho = sem_acento(arquivo.stem), sem_acento(json.dumps(meta, ensure_ascii=False))
        linhas = [(peso, sem_acento(linha)) for _, _, peso, linha in linhas_busca(corpo)]
        pontos = sum(12 * len(p.findall(nome)) + 6 * len(p.findall(cabecalho)) +
                     min(sum(peso * len(p.findall(linha)) for peso, linha in linhas), 10) for p in padroes)
        if pontos or not termos:
            resultados.append((pontos, len(texto), caminho_rel, meta.get("tipo", "?"), meta.get("status", "?"), corpo,
                               texto[:200_000]))
    resultados.sort(key=lambda r: (-r[0], r[1], r[2]))
    if args.trechos:
        return _mostrar_trechos(resultados, termos, args)
    # A seleção é um prefixo da ordem de relevância: nenhuma nota menos relevante entra no lugar de
    # outra mais relevante. Nota maior que o orçamento sozinha fica de lado (com as seções listadas);
    # nada é truncado e toda nota relevante que ficou de fora aparece como OMITIDA.
    escolhidos, omitidas, total, esgotado = [], [], 0, False
    for r in resultados:
        if r[1] > args.orcamento:
            omitidas.append((r, "maior que o orçamento sozinha"))
        elif len(escolhidos) >= args.max:
            omitidas.append((r, "além do limite de notas"))
        elif esgotado:
            omitidas.append((r, "orçamento esgotado por notas mais relevantes"))
        elif total + r[1] > args.orcamento:
            esgotado = True
            omitidas.append((r, "não cabe no orçamento restante"))
        else:
            escolhidos.append(r)
            total += r[1]
    linhas = [f"{p:>4}  {t:>6} car.  {c}  [{ti}/{s}]" for p, t, c, ti, s, *_ in escolhidos]
    for linha in linhas:
        print(linha)
    relevantes = [(r, motivo) for r, motivo in omitidas if r[0] > 0]
    for (p, t, c, ti, s, corpo, _), motivo in relevantes[:5]:
        print(f"OMITIDA {p:>4}  {t:>6} car.  {c}  [{ti}/{s}]: {motivo}")
        if motivo == "maior que o orçamento sozinha":
            secoes = _secoes(corpo)
            print("SEÇÕES  leia só a necessária: " +
                  ("; ".join(secoes) if secoes else "sem seções '##'; leia por trechos"))
    if len(relevantes) > 5:
        print(f"OMITIDA ... e mais {len(relevantes) - 5} nota(s) relevante(s)")
    print(f"-- {len(escolhidos)} de {len(resultados)} nota(s); conteúdo selecionado: {total} de "
          f"{args.orcamento} car. (notas inteiras, com frontmatter); esta listagem: "
          f"{sum(len(l) + 1 for l in linhas)} car. Orçamento: até {args.max} notas e ~{args.orcamento} car.; "
          "amplie só com motivo concreto.")
    return 0


# ---------------------------------------------------------------- escrita


def resolver(base: Path, destino: str, gravacao: bool) -> Path:
    """Valida o destino: relativo ao cofre, sem '..', sem ocultos, sem symlinks."""
    bruto = Path(nfc(destino)).expanduser()
    if bruto.is_absolute():
        try:
            bruto = Path(nfc(str(bruto))).relative_to(nfc(str(base)))
        except ValueError:
            raise Erro(f"destino fora do cofre: {destino}") from None
    partes = bruto.parts
    if not partes or any(p in ("", ".", "..") or p.startswith(".") for p in partes):
        raise Erro(f"destino inválido (vazio, '..' ou oculto): {destino}")
    if bruto.suffix != ".md":
        raise Erro("o destino precisa ser uma nota .md")
    if gravacao and chave(partes[0]) not in {chave(r) for r in RAIZES_GRAVAVEIS}:
        raise Erro(f"'{partes[0]}' não é raiz gravável; regras e templates exigem "
                   "autorização explícita e edição fora desta ferramenta")
    atual = base
    for parte in partes[:-1]:
        atual = atual / parte
        try:
            modo = os.lstat(atual).st_mode
        except FileNotFoundError:
            raise Erro(f"pasta inexistente (não crio categorias novas): {rel(base, atual)}") from None
        if stat.S_ISLNK(modo):
            raise Erro(f"symlink no caminho, recusado: {rel(base, atual)}")
        if not stat.S_ISDIR(modo):
            raise Erro(f"não é pasta: {rel(base, atual)}")
    alvo = atual / partes[-1]
    if os.path.islink(alvo):
        raise Erro("o destino é symlink, recusado")
    real_base, real_pai = os.path.realpath(base), os.path.realpath(alvo.parent)
    if os.path.commonpath([real_base, real_pai]) != real_base:
        raise Erro("destino resolve para fora do cofre")
    return alvo


class Trava:
    def __init__(self, base: Path, espera: float):
        pasta = base / ".cerebro"
        if os.path.islink(pasta) or not pasta.is_dir():
            raise Erro(".cerebro ausente ou symlink")
        self.caminho, self.espera, self.fd = pasta / ".trava", espera, None

    def __enter__(self):
        self.fd = os.open(self.caminho, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        limite = time.monotonic() + self.espera
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= limite:
                    os.close(self.fd)
                    raise TravaOcupada("cofre ocupado por outra escrita; tente de novo") from None
                time.sleep(0.05)

    def __exit__(self, *_):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)


def _fsync_pasta(pasta: Path) -> None:
    fd = os.open(pasta, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def gravar(base: Path, alvo: Path, dados: bytes, esperado: str | None, espera: float = 10.0) -> str:
    with Trava(base, espera):
        if esperado is None:
            if os.path.lexists(alvo):
                raise Conflito(f"já existe: {rel(base, alvo)}; leia, atualize e use --substituir")
            mesmo_nome = [rel(base, n) for n in notas(base) if chave(n.stem) == chave(alvo.stem)]
            if mesmo_nome:
                raise Conflito(f"já existe nota com esse nome: {mesmo_nome[0]}")
        else:
            if not os.path.lexists(alvo):
                raise Conflito(f"não existe para substituir: {rel(base, alvo)}")
            if not stat.S_ISREG(os.lstat(alvo).st_mode):
                raise Erro("o destino não é arquivo regular")
            if sha256(alvo.read_bytes()) != esperado:
                raise Conflito("a nota mudou desde a leitura (sha256 diferente); releia e refaça")
        temporario = alvo.parent / f".{alvo.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        fd = os.open(temporario, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            try:
                os.write(fd, dados)  # nota ≤ 60 kB: uma chamada basta, conferida abaixo
                os.fsync(fd)
            finally:
                os.close(fd)
            if os.path.getsize(temporario) != len(dados):
                raise Erro("escrita incompleta no arquivo temporário; nada foi alterado")
            if esperado is None:
                try:
                    os.link(temporario, alvo)  # cria sem sobrescrever
                except FileExistsError:
                    raise Conflito(f"já existe: {rel(base, alvo)}") from None
                except OSError as exc:
                    if exc.errno not in (errno.EPERM, errno.ENOTSUP, errno.EXDEV, errno.EMLINK):
                        raise
                    os.rename(temporario, alvo)  # sob a trava, já checado acima
            else:
                os.chmod(temporario, stat.S_IMODE(os.stat(alvo).st_mode))
                os.replace(temporario, alvo)
        finally:
            if os.path.lexists(temporario):
                os.unlink(temporario)
        _fsync_pasta(alvo.parent)
    return sha256(dados)


def cmd_gravar(args) -> int:
    base = cofre()
    alvo = resolver(base, args.destino, gravacao=True)
    if args.de:
        bruto = Path(args.de).read_bytes()
    else:
        bruto = sys.stdin.buffer.read()
    if len(bruto) > MAX_NOTA * 4:
        raise Erro("conteúdo grande demais")
    try:
        texto = nfc(bruto.decode("utf-8")).replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise Erro("conteúdo não é UTF-8") from None
    if not texto.endswith("\n"):
        texto += "\n"
    if len(texto) > MAX_NOTA:
        raise Erro(f"nota com {len(texto)} caracteres; limite {MAX_NOTA}. Resuma.")
    erros = validar_nota(rel(base, alvo), texto)
    if erros:
        raise Erro("nota inválida: " + "; ".join(erros))
    padrao = procurar_segredo(texto)
    if padrao:
        raise Erro(f"possível segredo no conteúdo (padrão {padrao!r}); remova antes de gravar")
    if args.substituir and not re.fullmatch(r"[0-9a-f]{64}", args.sha256 or ""):
        raise Erro("--substituir exige --sha256 com o hash lido (use o subcomando hash)")
    novo = gravar(base, alvo, texto.encode("utf-8"), None if args.novo else args.sha256)
    print(json.dumps({"ok": True, "destino": rel(base, alvo), "sha256": novo}, ensure_ascii=False))
    return 0


def cmd_hash(args) -> int:
    base = cofre()
    alvo = resolver(base, args.destino, gravacao=False)
    print(sha256(alvo.read_bytes()))
    return 0


# ---------------------------------------------------------------- verificação


def _sem_codigo(texto: str) -> str:
    texto = re.sub(r"```.*?```", "", texto, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", texto)


# Em tabelas, o alias usa barra escapada: [[Nota\|alias]].
LINK = re.compile(r"\[\[([^\]|#^\\]+)(?:[#^][^\]|\\]*)?(?:\\?\|[^\]]*)?\]\]")


LADOS, PONTAS = {"top", "right", "bottom", "left"}, {"none", "arrow"}
TIPOS_NO = {"text": "text", "file": "file", "link": "url", "group": None}


def verificar_canvas(base: Path, arquivo: Path, nomes: dict):
    """JSON Canvas 1.0: campos, ids únicos, arestas válidas, arquivos e links existentes, sobreposição."""
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return [f"JSON inválido: {exc}"], []
    erros, avisos = [], []
    nos, arestas = dados.get("nodes", []), dados.get("edges", [])
    ids = [n.get("id") for n in nos] + [e.get("id") for e in arestas]
    if len(ids) != len(set(ids)) or None in ids:
        erros.append("ids ausentes ou duplicados")
    por_id = {n.get("id"): n for n in nos}
    for n in nos:
        tipo = n.get("type")
        if tipo not in TIPOS_NO or any(not isinstance(n.get(k), int) for k in ("x", "y", "width", "height")):
            erros.append(f"nó {n.get('id')}: tipo ou geometria inválidos")
            continue
        campo = TIPOS_NO[tipo]
        if campo and not n.get(campo):
            erros.append(f"nó {n['id']}: falta '{campo}'")
        if tipo == "file" and not (base / n["file"]).is_file():
            erros.append(f"nó {n['id']}: arquivo inexistente {n['file']}")
        for alvo in LINK.findall(_sem_codigo(n.get("text", ""))):
            if alvo.strip() and chave(alvo.strip()) not in nomes:
                erros.append(f"nó {n['id']}: link quebrado [[{alvo.strip()}]]")
    for e in arestas:
        if e.get("fromNode") not in por_id or e.get("toNode") not in por_id:
            erros.append(f"aresta {e.get('id')}: nó inexistente")
        if any(e.get(k) not in LADOS for k in ("fromSide", "toSide") if k in e) or \
                any(e.get(k) not in PONTAS for k in ("fromEnd", "toEnd") if k in e):
            erros.append(f"aresta {e.get('id')}: lado ou ponta inválidos")
    folhas = [n for n in nos if n.get("type") != "group" and isinstance(n.get("x"), int)]
    for i, a in enumerate(folhas):
        for b in folhas[i + 1:]:
            if not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"] or
                    a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"]):
                avisos.append(f"nós sobrepostos: {a['id']} e {b['id']}")
    return erros, avisos


def cmd_verificar(_args) -> int:
    base = cofre()
    lista = list(notas(base))
    nomes: dict = {}
    for n in lista:
        nomes.setdefault(chave(n.stem), set()).add(rel(base, n))
        nomes.setdefault(chave(rel(base, n)[:-3]), set()).add(rel(base, n))
    telas = list(notas(base, ".canvas"))
    for n in telas:
        nomes.setdefault(chave(n.name), set()).add(rel(base, n))
        nomes.setdefault(chave(rel(base, n)), set()).add(rel(base, n))
    erros, avisos = [], []
    for nome, caminhos in nomes.items():
        if "/" not in nome and len(caminhos) > 1:
            erros.append(f"nome duplicado: {', '.join(sorted(caminhos))}")
    try:
        indice_regras = (base / INDICE_REGRAS).read_text(encoding="utf-8")
    except OSError:
        indice_regras = ""
        erros.append(f"ausente: {INDICE_REGRAS}")
    links_regras = {chave(l.strip()) for l in LINK.findall(indice_regras)}
    revisar, conferidas = 0, []
    for n in lista:
        caminho_rel = rel(base, n)
        texto = n.read_text(encoding="utf-8")
        if caminho_rel.startswith(TEMPLATES + "/"):
            continue  # templates têm placeholders; só valem como esqueleto
        for e in validar_nota(caminho_rel, texto):
            erros.append(f"{caminho_rel}: {e}")
        if procurar_segredo(texto):
            erros.append(f"{caminho_rel}: possível segredo")
        try:
            meta, _ = separar(texto)
        except ValueError:
            meta = None
        meta = meta or {}
        if meta.get("status") == "revisar":
            revisar += 1
        if fontes_conferidas(meta) and _data(meta.get("conferido_em")):
            conferidas.append((caminho_rel, meta["conferido_em"], fontes_conferidas(meta)))
        if meta.get("tipo") == "regra" and meta.get("status") == "ativo" and chave(n.stem) not in links_regras:
            erros.append(f"{caminho_rel}: regra ativa fora do Índice de regras")
        if meta.get("tipo") == "projeto" and not (meta.get("caminho") or meta.get("remoto")):
            avisos.append(f"{caminho_rel}: perfil sem caminho/remoto para identificação")
        for tipo_callout, titulo in CALLOUT.findall(_sem_codigo(texto)):
            if tipo_callout.strip().lower() in CALLOUTS and not titulo.strip():
                avisos.append(f"{caminho_rel}: callout [!{tipo_callout}] sem título")
        for alvo in LINK.findall(_sem_codigo(texto)):
            if alvo.strip() and chave(alvo.strip()) not in nomes:
                erros.append(f"{caminho_rel}: link quebrado [[{alvo.strip()}]]")
    for n in telas:
        e, a = verificar_canvas(base, n, nomes)
        erros += [f"{rel(base, n)}: {x}" for x in e]
        avisos += [f"{rel(base, n)}: {x}" for x in a]
    if revisar:
        avisos.append(f"{revisar} nota(s) com status revisar")
    # Atualização em relação às fontes (separada da integridade acima): só para notas que registram
    # conferido_em e fontes_conferidas. Fonte alterada pede revisão; não prova que a nota está errada.
    atuais = hashes_externos(sorted({c for *_, pares in conferidas for c, _ in pares})) if conferidas else {}
    a_rever = 0
    for caminho_rel, data, pares in conferidas:
        if atuais is None:
            avisos.append(f"{caminho_rel}: atualização não conferida agora (leitura das fontes indisponível ou "
                          "lenta); tente de novo")
            continue
        mudaram = [c for c, h in pares if atuais.get(c) and atuais[c] != h]
        sumiram = [c for c, h in pares if not atuais.get(c)]
        if mudaram or sumiram:
            a_rever += 1
        for c in mudaram:
            avisos.append(f"{caminho_rel}: revisar — fonte mudou desde a conferência de {data}: {c}")
        for c in sumiram:
            avisos.append(f"{caminho_rel}: revisar — fonte ausente ou ilegível desde a conferência de {data}: {c}")
    for linha in erros:
        print(f"ERRO  {linha}")
    for linha in avisos:
        print(f"AVISO {linha}")
    print(f"-- atualização: {len(conferidas)} nota(s) com fontes conferidas, {a_rever} a revisar"
          f"{' (não conferido agora)' if atuais is None else ''}; nas demais, a verificação é só estrutural.")
    print(f"-- {len(lista)} nota(s) e {len(telas)} canvas verificado(s); {len(erros)} erro(s), {len(avisos)} aviso(s).")
    return 1 if erros else 0


# ---------------------------------------------------------------- CLI


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cerebro.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("hook", help="contexto JSON para SessionStart").set_defaults(f=cmd_hook)
    c = sub.add_parser("contexto", help="contexto em texto")
    c.add_argument("--cwd", default=os.getcwd())
    c.set_defaults(f=cmd_contexto)
    b = sub.add_parser("buscar", help="notas relacionadas a termos")
    b.add_argument("termos", nargs="*")
    b.add_argument("--projeto")
    b.add_argument("--max", type=int, help="máximo de notas (padrão 2 com --trechos; 5 sem)")
    b.add_argument("--orcamento", type=int,
                   help=f"caracteres: saída inteira com --trechos (padrão 2500); notas selecionadas sem (padrão {ORCAMENTO})")
    b.add_argument("--incluir-logs", action="store_true")
    b.add_argument("--todos", action="store_true", help="inclui arquivadas/obsoletas")
    b.add_argument("--trechos", action="store_true",
                   help="mostra só as linhas pertinentes de cada nota (o orçamento limita toda a saída)")
    b.set_defaults(f=cmd_buscar)
    h = sub.add_parser("hash", help="sha256 de uma nota")
    h.add_argument("destino")
    h.set_defaults(f=cmd_hash)
    g = sub.add_parser("gravar", help="cria ou substitui nota com validação")
    g.add_argument("--destino", required=True, help="caminho relativo ao cofre")
    modo = g.add_mutually_exclusive_group(required=True)
    modo.add_argument("--novo", action="store_true")
    modo.add_argument("--substituir", action="store_true")
    g.add_argument("--sha256", help="hash da versão lida (obrigatório com --substituir)")
    g.add_argument("--de", help="arquivo com o conteúdo (padrão: stdin)")
    g.set_defaults(f=cmd_gravar)
    sub.add_parser("verificar", help="confere o cofre").set_defaults(f=cmd_verificar)
    args = p.parse_args(argv)
    try:
        return args.f(args)
    except Erro as exc:
        print(f"cerebro: {exc}", file=sys.stderr)
        return exc.codigo
    except OSError as exc:
        print(f"cerebro: falha de E/S: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
