"""Backup datado do Cérebro, com manifesto, hashes e teste de restauração. Só biblioteca padrão; nunca sobrescreve.
Uso: python3 -I backup_cerebro.py <pasta de saída> [<pasta local para a restauração>]
Gera Cerebro-AAAA-MM-DD-HHMM.tar.gz, .tar.gz.sha256, .SHA256SUMS e .MANIFESTO.json; restaura o arquivo gravado
na saída numa pasta temporária (ao lado da saída ou na pasta indicada, útil quando a saída é sincronizada com a
nuvem), confere o sha256 de cada arquivo e roda `verificar` e os testes sobre a cópia.
A pasta de saída só é backup independente se estiver em outro disco físico (ex.: disco externo); o manifesto
registra o que o diskutil identificou. Pasta sincronizada (OneDrive, iCloud) neste disco não conta.
CEREBRO_DIR substitui o cofre (usado nos testes com cofre sintético)."""
import datetime, hashlib, json, os, platform, plistlib, subprocess, sys, tarfile, tempfile
from pathlib import Path

COFRE = Path(os.environ.get("CEREBRO_DIR") or Path(__file__).resolve().parent.parent / "examples" / "cofre")
FORA = {".DS_Store", "__pycache__", ".trava"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def inventario(raiz):
    itens = []
    for d, subs, arqs in os.walk(raiz):
        subs[:] = sorted(s for s in subs if s not in FORA)
        for s in [s for s in subs if os.path.islink(os.path.join(d, s))]:  # link para pasta: idem, nunca percorrido
            subs.remove(s)
            itens.append(((Path(d) / s).relative_to(raiz).as_posix(), "link:" + os.readlink(Path(d) / s), 0))
        for n in sorted(arqs):
            p = Path(d) / n
            if n in FORA:
                continue
            if p.is_symlink():  # guardado como link; conferido pelo alvo, nunca seguido
                itens.append((p.relative_to(raiz).as_posix(), "link:" + os.readlink(p), 0))
                continue
            itens.append((p.relative_to(raiz).as_posix(), sha(p), p.stat().st_size))
    return itens


def mesmo_disco(saida):
    return os.stat(saida).st_dev == os.stat(COFRE).st_dev


def _diskutil(alvo):
    try:
        r = subprocess.run(["diskutil", "info", "-plist", alvo], capture_output=True, timeout=30, check=True)
        return plistlib.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, ValueError):
        return None


def disco_fisico(caminho):
    """(disco físico inteiro, info do volume) que guarda o caminho, ou (None, info) se não der para saber."""
    try:
        r = subprocess.run(["df", "-P", str(caminho)], capture_output=True, text=True, timeout=30, check=True)
        info = _diskutil(r.stdout.strip().splitlines()[-1].split()[0])
    except (OSError, subprocess.SubprocessError, IndexError):
        return None, None
    if not info:
        return None, None
    lojas = [s.get("APFSPhysicalStore") for s in info.get("APFSPhysicalStores") or []]
    if lojas and lojas[0]:  # APFS: o contêiner é sintetizado; o disco real é o da loja física
        loja = _diskutil(lojas[0])
        return (loja or {}).get("ParentWholeDisk"), info
    return info.get("ParentWholeDisk"), info


def independencia(saida):
    """True só com outro disco físico identificado; False no mesmo disco; None se não der para confirmar."""
    if mesmo_disco(saida):
        return False, "mesmo volume do cofre"
    origem, _ = disco_fisico(COFRE)
    destino, info = disco_fisico(saida)
    if not origem or not destino:
        return None, "disco do destino não identificado pelo diskutil (ex.: volume de rede); confirme manualmente"
    if info.get("BusProtocol") == "Disk Image":
        return None, "o destino é uma imagem de disco, que pode estar guardada neste mesmo disco"
    if destino == origem:
        return False, f"mesmo disco físico do cofre ({origem})"
    return True, f"outro disco físico ({destino}, {info.get('BusProtocol') or 'barramento desconhecido'})"


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit("uso: python3 -I backup_cerebro.py <pasta de saída> [<pasta local para a restauração>]")
    saida = Path(sys.argv[1]).expanduser().resolve()
    if saida == COFRE.resolve() or COFRE.resolve() in saida.parents:
        sys.exit(f"a saída fica dentro do cofre e se perderia com ele; escolha outra pasta: {saida}")
    local = Path(sys.argv[2]).expanduser().resolve() if len(sys.argv) == 3 else saida
    if local != saida and (not local.is_dir() or local == COFRE.resolve() or COFRE.resolve() in local.parents):
        sys.exit(f"a pasta da restauração precisa existir e ficar fora do cofre: {local}")
    saida.mkdir(parents=True, exist_ok=True)
    nome = "Cerebro-" + datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    arq, soma, lista, manif = (saida / f"{nome}{s}" for s in (".tar.gz", ".tar.gz.sha256", ".SHA256SUMS", ".MANIFESTO.json"))
    independente, motivo = independencia(saida)
    if any(p.exists() for p in (arq, soma, lista, manif)):
        sys.exit(f"já existe um backup com este nome; nada sobrescrito: {arq}")
    antes = inventario(COFRE)
    lista.write_text("".join(f"{h}  Cérebro/{r}\n" for r, h, _ in antes if not h.startswith("link:")), encoding="utf-8")
    links = {r: h[5:] for r, h, _ in antes if h.startswith("link:")}
    with tarfile.open(arq, "x:gz") as t:
        for r, _, _ in antes:
            t.add(COFRE / r, arcname=f"Cérebro/{r}", recursive=False)
        t.add(lista, arcname="SHA256SUMS", recursive=False)
    if inventario(COFRE) != antes:
        sys.exit("o cofre mudou durante a cópia; repita com os agentes e o Obsidian parados")
    sha_arq = sha(arq)
    soma.write_text(f"{sha_arq}  {arq.name}\n", encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="restauracao-", dir=local) as tmp:
        guardados = {}

        def sem_links(membro, destino):  # links não são criados no teste; o alvo guardado é conferido
            if membro.issym() or membro.islnk():
                guardados[membro.name.removeprefix("Cérebro/")] = membro.linkname
                return None
            return tarfile.data_filter(membro, destino)

        with tarfile.open(arq) as t:
            t.extractall(tmp, filter=sem_links)
        rest = Path(tmp) / "Cérebro"
        obtido = {r: h for r, h, _ in inventario(rest)} | {r: "link:" + alvo for r, alvo in guardados.items()}
        iguais = sum(1 for r, h, _ in antes if obtido.get(r) == h)
        amb = dict(os.environ, CEREBRO_DIR=str(rest), PYTHONDONTWRITEBYTECODE="1")
        v = subprocess.run([sys.executable, str(rest / ".cerebro/cerebro.py"), "verificar"], capture_output=True, text=True, env=amb)
        u = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(rest / ".cerebro"), "-p", "test_*.py"],
                           capture_output=True, text=True, env=amb, cwd=tmp)
        v_linha = (v.stdout.strip().splitlines() or ["(sem saída)"])[-1]
        u_linha = " ".join(u.stderr.strip().splitlines()[-3:])
        ok = iguais == len(antes) == len(obtido) and v.returncode == 0 and u.returncode == 0

    manifesto = {
        "criado_em": datetime.datetime.now().isoformat(timespec="seconds"),
        "origem": str(COFRE), "arquivo": arq.name, "sha256_arquivo": sha_arq, "bytes_arquivo": arq.stat().st_size,
        "arquivos": len(antes) - len(links), "links": links, "bytes_originais": sum(s for _, _, s in antes), "excluidos_por_nome": sorted(FORA),
        "lista_de_hashes": lista.name,
        "restauracao": {"arquivos_identicos": iguais, "total": len(antes), "verificar": v_linha, "verificar_rc": v.returncode,
                        "testes": u_linha, "testes_rc": u.returncode, "comprovada": ok,
                        "lido_de": str(arq), "extraido_em": str(local)},
        "destino": str(saida), "mesmo_disco_do_cofre": mesmo_disco(saida),
        "backup_independente": independente, "independencia": motivo,
        "observacao": "Só conta como backup independente com outro disco físico e restauração comprovada a partir dele.",
        "python": platform.python_version(),
    }
    manif.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"backup: {arq} ({arq.stat().st_size / 1e6:.1f} MB, {len(antes)} arquivos)")
    print(f"restauração: {iguais} de {len(antes)} idênticos; verificar: {v_linha}; testes: {u_linha}")
    print(f"independência: {'sim' if independente else 'NÃO' if independente is False else 'não confirmada'} ({motivo})")
    print("RESULTADO:", "restauração comprovada" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
