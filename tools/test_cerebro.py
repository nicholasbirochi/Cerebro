"""Testes do cerebro.py com cofre sintético temporário (nunca toca o cofre real).

python3 -m unittest discover -s "<cofre>/.cerebro" -p "test_*.py"
"""
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "cerebro.py"
spec = importlib.util.spec_from_file_location("cerebro", SCRIPT)
cerebro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cerebro)


def nota(tipo="aprendizado", status="ativo", extra="", corpo="Corpo sintético.\n"):
    return (f"---\ntipo: {tipo}\nstatus: {status}\ncriado_em: 2026-10-10\n"
            f"atualizado_em: 2026-10-10\n{extra}---\n{corpo}")


class CofreSintetico(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cerebro-teste-"))
        self.base = self.tmp / "Cofre Sintético"
        self.fora = self.tmp / "fora"
        self.fora.mkdir()
        for pasta in (*cerebro.RAIZES_GRAVAVEIS, "00 - Regras para Agentes", "07 - Templates",
                      "05 - Padrões e Preferências/Aprendizados", ".cerebro"):
            (self.base / pasta).mkdir(parents=True, exist_ok=True)
        (self.base / cerebro.PROTOCOLO).write_text(
            nota("regra", extra="autorizacao: teste\n", corpo="# Protocolo\nPROTOCOLO-SINTETICO\n"), encoding="utf-8")
        (self.base / cerebro.INDICE_REGRAS).write_text(
            nota("índice", corpo="[[Protocolo dos Agentes]]\n"), encoding="utf-8")
        self.projeto = self.tmp / "Projetos" / "Ação Sintética"
        self.projeto.mkdir(parents=True)
        (self.base / "02 - Projetos" / "Projeto - Sintetico.md").write_text(
            nota("projeto", extra=f'caminho: "{self.projeto}"\nremoto: "git@github.com:exemplo/Sintetico.git"\n'),
            encoding="utf-8")
        self.env = dict(os.environ, CEREBRO_DIR=str(self.base))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rodar(self, *args, entrada=None, env=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=entrada,
                              capture_output=True, text=True, env=env or self.env, timeout=30)

    def gravar(self, destino, conteudo, *modo):
        return self.rodar("gravar", "--destino", destino, *(modo or ("--novo",)), entrada=conteudo)

    # ------------------------------------------------------------ hook
    def contexto_do_hook(self, cwd, env=None):
        r = self.rodar("hook", entrada=json.dumps({"cwd": cwd, "hook_event_name": "SessionStart"}), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        saida = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(saida["hookEventName"], "SessionStart")
        return saida["additionalContext"]

    def test_hook_identifica_por_caminho_mesmo_em_nfd(self):
        cwd = unicodedata.normalize("NFD", str(self.projeto / "src"))
        texto = self.contexto_do_hook(cwd)
        self.assertIn("Projeto - Sintetico", texto)
        self.assertIn("por caminho", texto)
        self.assertIn("PROTOCOLO-SINTETICO", texto)

    def test_hook_identifica_por_remoto_git(self):
        repo = self.tmp / "clone"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                        "https://github.com/exemplo/sintetico.git"], check=True)
        self.assertIn("por remoto git", self.contexto_do_hook(str(repo)))

    def test_hook_sem_projeto(self):
        texto = self.contexto_do_hook(str(self.fora))
        self.assertIn("Nenhum perfil de projeto", texto)

    def test_hook_cofre_indisponivel_nao_falha(self):
        env = dict(self.env, CEREBRO_DIR=str(self.tmp / "nao-existe"))
        texto = self.contexto_do_hook(str(self.fora), env=env)
        self.assertIn("Cofre indisponível", texto)
        self.assertIn("não afirme consultas", texto)

    def test_hook_stdin_invalido(self):
        r = self.rodar("hook", entrada="{nao é json")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Segundo cérebro", json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])

    # ------------------------------------------------------------ gravar
    def test_gravar_novo_e_repeticao(self):
        destino = "05 - Padrões e Preferências/Aprendizados/Aprendizado - teste.md"
        r = self.gravar(destino, nota())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["sha256"],
                         cerebro.sha256((self.base / destino).read_bytes()))
        repetido = self.gravar(destino, nota(corpo="Outra versão.\n"))
        self.assertEqual(repetido.returncode, 3)
        self.assertIn("Corpo sintético", (self.base / destino).read_text(encoding="utf-8"))
        mesmo_nome = self.gravar("06 - Logs de Tarefas/Aprendizado - teste.md", nota())
        self.assertEqual(mesmo_nome.returncode, 3)

    def test_rejeita_caminhos_fora_das_raizes(self):
        for destino in ("00 - Regras para Agentes/Nova regra.md", "07 - Templates/T.md",
                        "../fora/Aprendizado - x.md", str(self.fora / "Aprendizado - x.md"),
                        ".obsidian/x.md", "05 - Padrões e Preferências/Nova pasta/Aprendizado - x.md",
                        "05 - Padrões e Preferências/Aprendizados/Aprendizado - x.txt", ""):
            with self.subTest(destino=destino):
                r = self.gravar(destino, nota())
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(list(self.fora.iterdir()), [])

    def test_rejeita_symlinks(self):
        pasta = self.base / "05 - Padrões e Preferências" / "Atalho"
        pasta.symlink_to(self.fora, target_is_directory=True)
        r = self.gravar("05 - Padrões e Preferências/Atalho/Aprendizado - x.md", nota())
        self.assertEqual(r.returncode, 1)
        self.assertIn("symlink", r.stderr)
        alvo_externo = self.fora / "alvo.md"
        alvo_externo.write_text("original", encoding="utf-8")
        link = self.base / "06 - Logs de Tarefas" / "Log - 2026-10-10 - x - y.md"
        link.symlink_to(alvo_externo)
        r = self.gravar("06 - Logs de Tarefas/Log - 2026-10-10 - x - y.md", nota("log"), "--substituir",
                        "--sha256", cerebro.sha256(b"original"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(alvo_externo.read_text(encoding="utf-8"), "original")

    def test_rejeita_metadados_invalidos_e_segredos(self):
        pasta = "05 - Padrões e Preferências/Aprendizados/"
        casos = {
            "tipo inválido": (pasta + "Aprendizado - a.md", nota("ideia")),
            "sem frontmatter": (pasta + "Aprendizado - b.md", "só texto\n"),
            "data inválida": (pasta + "Aprendizado - c.md", nota().replace("2026-10-10", "10/10/2026", 1)),
            "nome fora do padrão": (pasta + "Coisa solta.md", nota()),
            "log sem padrão": ("06 - Logs de Tarefas/Log de hoje.md", nota("log")),
            "segredo": (pasta + "Aprendizado - d.md", nota(corpo="api_key = abcdefghijklmnop1234\n")),
            "chave privada": (pasta + "Aprendizado - e.md", nota(corpo="-----BEGIN RSA PRIVATE KEY-----\n")),
        }
        for nome, (destino, conteudo) in casos.items():
            with self.subTest(nome):
                r = self.gravar(destino, conteudo)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertFalse((self.base / destino).exists())

    def test_substituir_exige_hash_atual(self):
        destino = "02 - Projetos/Projeto - Sintetico.md"
        original = (self.base / destino).read_bytes()
        novo = original.decode("utf-8") + "\nAtualizado.\n"
        errado = self.gravar(destino, novo, "--substituir", "--sha256", "0" * 64)
        self.assertEqual(errado.returncode, 3)
        self.assertEqual((self.base / destino).read_bytes(), original)
        certo = self.gravar(destino, novo, "--substituir", "--sha256", cerebro.sha256(original))
        self.assertEqual(certo.returncode, 0, certo.stderr)
        self.assertIn("Atualizado.", (self.base / destino).read_text(encoding="utf-8"))

    def test_concorrencia_um_vence_os_demais_conflitam(self):
        destino = "02 - Projetos/Projeto - Sintetico.md"
        original = (self.base / destino).read_bytes()
        h = cerebro.sha256(original)
        procs = [subprocess.Popen([sys.executable, str(SCRIPT), "gravar", "--destino", destino,
                                   "--substituir", "--sha256", h], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
                 for _ in range(6)]
        for i, p in enumerate(procs):
            p.stdin.write(original.decode("utf-8") + f"\nEscritor {i}\n")
            p.stdin.close()
        codigos = [p.wait(timeout=30) for p in procs]
        for p in procs:
            p.stdout.close()
            p.stderr.close()
        self.assertEqual(codigos.count(0), 1, codigos)
        self.assertEqual(codigos.count(3), 5, codigos)
        vencedor = codigos.index(0)
        self.assertTrue((self.base / destino).read_text(encoding="utf-8").endswith(f"Escritor {vencedor}\n"))
        sobras = [p for p in self.base.rglob(".*.tmp")]
        self.assertEqual(sobras, [])

    def test_trava_ocupada(self):
        fd = os.open(self.base / ".cerebro" / ".trava", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            alvo = self.base / "06 - Logs de Tarefas" / "Log - 2026-10-10 - x - trava.md"
            with self.assertRaises(cerebro.TravaOcupada):
                cerebro.gravar(self.base, alvo, nota("log").encode(), None, espera=0.2)
            self.assertFalse(alvo.exists())
        finally:
            os.close(fd)

    # ------------------------------------------------------------ verificar / buscar
    def test_verificar_aponta_problemas(self):
        self.assertEqual(self.rodar("verificar").returncode, 0, self.rodar("verificar").stdout)
        regras = self.base / "00 - Regras para Agentes"
        (regras / "Regra solta.md").write_text(nota("regra", extra="autorizacao: x\n"), encoding="utf-8")
        (self.base / "06 - Logs de Tarefas" / "Log - 2026-10-10 - a - b.md").write_text(
            nota("log", corpo="[[Nota que não existe]]\n"), encoding="utf-8")
        (self.base / "01 - Índices" / "Projeto - Sintetico.md").write_text(nota("índice"), encoding="utf-8")
        (self.base / "03 - Graphify e Mapas de Projeto" / "Mapa.md").write_text(
            nota("índice", extra="sha256_origem: " + "1" * 64 + "\n"), encoding="utf-8")
        (self.base / "06 - Logs de Tarefas" / "Log - 2026-10-10 - a - c.md").write_text(
            nota("log", corpo="> [!hipotese]\n> sem título\n\n> [!fato] Com título\n> ok\n"), encoding="utf-8")
        saida = self.rodar("verificar")
        self.assertEqual(saida.returncode, 1)
        for trecho in ("fora do Índice de regras", "link quebrado", "nome duplicado", "sha256_origem",
                       "callout [!hipotese] sem título"):
            self.assertIn(trecho, saida.stdout)
        self.assertNotIn("[!fato] sem título", saida.stdout)

    def test_link_com_alias_escapado_em_tabela(self):
        (self.base / "01 - Índices" / "Índice de teste.md").write_text(
            nota("índice", corpo="| a | b |\n|---|---|\n| [[Projeto - Sintetico\\|perfil]] | [[Inexistente\\|x]] |\n"),
            encoding="utf-8")
        saida = self.rodar("verificar")
        self.assertNotIn("link quebrado [[Projeto - Sintetico", saida.stdout)
        self.assertIn("link quebrado [[Inexistente]]", saida.stdout)

    def test_canvas_fase_e_saidas_geradas(self):
        mapas = self.base / "03 - Graphify e Mapas de Projeto"
        bom = {"nodes": [
            {"id": "a1", "type": "text", "x": 0, "y": 0, "width": 200, "height": 100, "text": "[[Projeto - Sintetico]]"},
            {"id": "b2", "type": "file", "x": 300, "y": 0, "width": 200, "height": 100,
             "file": "02 - Projetos/Projeto - Sintetico.md"}],
            "edges": [{"id": "e1", "fromNode": "a1", "toNode": "b2", "fromSide": "right", "toSide": "left"}]}
        (mapas / "Bom.canvas").write_text(json.dumps(bom), encoding="utf-8")
        (self.base / "05 - Padrões e Preferências/Aprendizados/Aprendizado - x.md").write_text(
            nota(corpo="[[Bom.canvas]]\n"), encoding="utf-8")
        saidas = self.base / cerebro.SAIDAS / "Sintetico"
        saidas.mkdir(parents=True)
        (saidas / "GRAPH_REPORT.md").write_text("# relatório gerado, sem frontmatter [[Inexistente]]\n", encoding="utf-8")
        r = self.rodar("verificar")
        self.assertEqual(r.returncode, 0, r.stdout)
        ruim = {"nodes": [
            {"id": "a1", "type": "text", "x": 0, "y": 0, "width": 200, "height": 100, "text": "[[Nota que não existe]]"},
            {"id": "a1", "type": "file", "x": 50, "y": 50, "width": 200, "height": 100, "file": "nao/existe.md"}],
            "edges": [{"id": "e1", "fromNode": "a1", "toNode": "zz", "toEnd": "seta"}]}
        (mapas / "Ruim.canvas").write_text(json.dumps(ruim), encoding="utf-8")
        (mapas / "Quebrado.canvas").write_text("{nao json", encoding="utf-8")
        (self.base / "02 - Projetos" / "Projeto - Fase.md").write_text(
            nota("projeto", extra='fase: pausado\ncaminho: "/tmp/x"\n'), encoding="utf-8")
        r = self.rodar("verificar")
        self.assertEqual(r.returncode, 1)
        for trecho in ("ids ausentes ou duplicados", "arquivo inexistente", "link quebrado [[Nota que não existe]]",
                       "nó inexistente", "lado ou ponta inválidos", "nós sobrepostos", "JSON inválido",
                       "fase inválida: pausado"):
            self.assertIn(trecho, r.stdout)
        self.assertNotIn("GRAPH_REPORT", r.stdout)

    def test_buscar_respeita_orcamento(self):
        for i in range(8):
            (self.base / "05 - Padrões e Preferências/Aprendizados" / f"Aprendizado - hooks {i}.md").write_text(
                nota(corpo="hooks de sessão\n"), encoding="utf-8")
        r = self.rodar("buscar", "hooks", "--max", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len([l for l in r.stdout.splitlines() if l.startswith(" ")]), 3)
        self.assertIn("3 de 8", r.stdout)
        self.assertIn("além do limite de notas", r.stdout)

    def test_buscar_limite_combinado_de_caracteres(self):
        pasta = self.base / "05 - Padrões e Preferências/Aprendizados"
        # relevância decrescente: A (3 citações), B (2), C (1); A e B somam mais que 12 mil
        for nome, citacoes, tamanho in (("A", 3, 7000), ("B", 2, 7000), ("C", 1, 3000)):
            corpo = "orcamento " * citacoes + "x" * tamanho + "\n"
            (pasta / f"Aprendizado - {nome}.md").write_text(nota(corpo=corpo), encoding="utf-8")
        r = self.rodar("buscar", "orcamento")
        self.assertEqual(r.returncode, 0, r.stderr)
        linhas = [l for l in r.stdout.splitlines() if l.startswith(" ")]
        self.assertEqual(len(linhas), 1)  # C, menos relevante, não entra no lugar de B
        self.assertIn("Aprendizado - A.md", linhas[0])
        omitida = [l for l in r.stdout.splitlines() if l.startswith("OMITIDA")]
        self.assertEqual(len(omitida), 2)
        self.assertIn("Aprendizado - B.md", omitida[0])
        self.assertIn("não cabe no orçamento restante", omitida[0])
        self.assertIn("Aprendizado - C.md", omitida[1])
        self.assertIn("orçamento esgotado", omitida[1])
        total = sum(int(l.split()[1]) for l in linhas)
        self.assertLessEqual(total, 12_000)
        self.assertIn(f"conteúdo selecionado: {total} de 12000 car.", r.stdout)
        maior = self.rodar("buscar", "orcamento", "--orcamento", "20000")
        self.assertEqual(len([l for l in maior.stdout.splitlines() if l.startswith(" ")]), 3)
        self.assertEqual(self.rodar("buscar", "x", "--orcamento", "0").returncode, 1)

    def test_buscar_nota_individual_maior_que_orcamento(self):
        pasta = self.base / "05 - Padrões e Preferências/Aprendizados"
        grande = nota(corpo="## Parte um\ngigante " + "y" * 9000 + "\n## Parte dois\n" + "z" * 9000 + "\n")
        (pasta / "Aprendizado - gigante.md").write_text(grande, encoding="utf-8")
        (pasta / "Aprendizado - pequeno.md").write_text(nota(corpo="gigante pequeno\n"), encoding="utf-8")
        r = self.rodar("buscar", "gigante")
        self.assertEqual(r.returncode, 0, r.stderr)
        linhas = [l for l in r.stdout.splitlines() if l.startswith(" ")]
        self.assertEqual(len(linhas), 1)
        self.assertIn("Aprendizado - pequeno.md", linhas[0])
        omitida = next(l for l in r.stdout.splitlines() if l.startswith("OMITIDA"))
        self.assertIn("Aprendizado - gigante.md", omitida)
        self.assertIn(f"{len(grande)} car.", omitida)  # tamanho real, sem truncar
        self.assertIn("maior que o orçamento sozinha", omitida)
        self.assertIn("Parte um (", r.stdout)
        self.assertIn("Parte dois (", r.stdout)

    def test_hook_injeta_so_a_secao_essencial_com_e_sem_projeto(self):
        (self.base / cerebro.PROTOCOLO).write_text(nota("regra", extra="autorizacao: teste\n", corpo=(
            "# Protocolo\n\n## Essencial\nREGRA-DE-CUSTO-ESSENCIAL\n\n## 1. Procedimento\nSO-NO-ARQUIVO\n")),
            encoding="utf-8")
        for cwd in (str(self.projeto), str(self.fora)):  # projeto com perfil e pasta sem perfil
            with self.subTest(cwd=cwd):
                texto = self.contexto_do_hook(cwd)
                self.assertIn("REGRA-DE-CUSTO-ESSENCIAL", texto)
                self.assertNotIn("SO-NO-ARQUIVO", texto)
                self.assertIn("--trechos", texto)
        self.assertIn('--projeto "Sintetico"', self.contexto_do_hook(str(self.projeto)))

    def test_buscar_trechos_mostra_linhas_e_secoes(self):
        pasta = self.base / "05 - Padrões e Preferências/Aprendizados"
        corpo = ("## Contexto\nlinha sem nada\n## Detalhe\n- item sobre agente que\n  continua aqui sem editar\n"
                 "texto irrelevante\n" * 3)
        (pasta / "Aprendizado - agente.md").write_text(nota(extra="fonte: agente sintético\n", corpo=corpo),
                                                       encoding="utf-8")
        r = self.rodar("buscar", "agente", "editar", "--trechos")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[Detalhe] - item sobre agente que continua aqui sem editar", r.stdout)
        self.assertRegex(r.stdout, r"L\d+ \[Detalhe\]")
        self.assertNotIn("fonte: agente", r.stdout)  # frontmatter não aparece
        self.assertIn("car. mostrados", r.stdout)
        normal = self.rodar("buscar", "agente", "editar")
        self.assertNotIn("[Detalhe]", normal.stdout)  # o modo antigo continua igual

    def notas_de_backup(self, quantidade=34):
        """Muitas notas relevantes, como no cofre real em 2026-10-13 (33 OMITIDA com --max 1)."""
        pasta = self.base / "05 - Padrões e Preferências/Aprendizados"
        for i in range(quantidade):
            corpo = "".join(f"- linha {j} sobre backup e restauração " + "x" * 150 + "\n"
                            for j in range(1 + i % 7))
            (pasta / f"Aprendizado - backup caso {i:02d} com um nome comprido.md").write_text(
                nota(corpo="## Seção\n" + "backup " * (i % 5) + "\n" + corpo), encoding="utf-8")

    def test_buscar_trechos_orcamento_conta_a_saida_inteira(self):
        self.notas_de_backup()
        # o caso observado: orçamento de 700 emitia 4 832 caracteres (linhas OMITIDA fora da conta)
        for orcamento, maximo in ((700, "1"), (1500, "1"), (300, "5"), (4000, "5"), (12000, "5")):
            with self.subTest(orcamento=orcamento, maximo=maximo):
                r = self.rodar("buscar", "backup", "--trechos", "--max", maximo, "--orcamento", str(orcamento))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertLessEqual(len(r.stdout), orcamento)
                linhas = r.stdout.splitlines()
                self.assertTrue(linhas[-1].startswith("-- trechos de "))
                self.assertIn(f"{len(r.stdout)} car. mostrados", linhas[-1])  # o total informado é o real
                mostradas = int(linhas[-1].split()[3])
                listadas = [l for l in linhas if l.startswith("OMITIDA ") and not l.startswith("OMITIDA +")]
                resto = [l for l in linhas if l.startswith("OMITIDA +")]
                nao_listadas = int(resto[0].split()[1][1:]) if resto else 0
                self.assertEqual(mostradas + len(listadas) + nao_listadas, 34)  # nenhuma some sem aviso
                # ordem de relevância: blocos e omissões listadas em pontuação não crescente
                pontos = [int(l.split()[0]) for l in linhas if l[:4].strip().isdigit()] + \
                         [int(l.split()[1]) for l in listadas]
                self.assertEqual(pontos, sorted(pontos, reverse=True))

    def test_buscar_trechos_progressivo_sem_listagem_de_omissoes(self):
        self.notas_de_backup()
        for opcoes, limite, quantidade in (((), 2500, 2),
                                           (("--max", "5", "--orcamento", "12000"), 12000, 5)):
            with self.subTest(opcoes=opcoes):
                r = self.rodar("buscar", "backup", "--trechos", *opcoes)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertLessEqual(len(r.stdout), limite)
                resumo = r.stdout.splitlines()[-1]
                self.assertIn(f"trechos de {quantidade} nota(s)", resumo)
                omitidas = [l for l in r.stdout.splitlines() if l.startswith("OMITIDA")]
                self.assertEqual(len(omitidas), 1)
                self.assertTrue(omitidas[0].startswith(f"OMITIDA +{34 - quantidade} "))
                self.assertNotIn(".md", omitidas[0])

    def test_buscar_trechos_orcamento_pequeno_demais(self):
        self.notas_de_backup()
        r = self.rodar("buscar", "backup", "--trechos", "--orcamento", "50")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")  # nada impresso: a saída não passa do limite
        self.assertIn("pequeno demais", r.stderr)
        minimo = int(r.stderr.rsplit("pelo menos ", 1)[1].split()[0])
        exato = self.rodar("buscar", "backup", "--trechos", "--orcamento", str(minimo))
        self.assertEqual(exato.returncode, 0, exato.stderr)
        self.assertLessEqual(len(exato.stdout), minimo)
        self.assertIn("trechos de 0 nota(s)", exato.stdout)  # formato lido pelo Noah
        vazio = self.rodar("buscar", "inexistentezzz", "--trechos", "--orcamento", "200")
        self.assertEqual(vazio.returncode, 0, vazio.stderr)
        self.assertIn("trechos de 0 nota(s)", vazio.stdout)

    def test_buscar_palavras_num_argumento_equivalem_a_separadas(self):
        pasta = self.base / "05 - Padrões e Preferências/Aprendizados"
        (pasta / "Aprendizado - backup do cofre.md").write_text(
            nota(corpo="## Estado\n- backup conferido\n- saúde da ferramenta\n"), encoding="utf-8")
        (pasta / "Aprendizado - outro.md").write_text(nota(corpo="só saude aqui\n"), encoding="utf-8")
        for modo in ((), ("--trechos",)):
            with self.subTest(modo=modo):
                separadas = self.rodar("buscar", "backup", "saúde", *modo)
                self.assertEqual(separadas.returncode, 0, separadas.stderr)
                self.assertIn("Aprendizado - backup do cofre.md", separadas.stdout)
                for consulta in (["backup saúde"], ["BACKUP  saude "], ["backup", " saúde"],
                                 [unicodedata.normalize("NFD", "backup saúde")]):
                    junta = self.rodar("buscar", *consulta, *modo)
                    self.assertEqual(junta.stdout, separadas.stdout, consulta)

    def test_verificar_avisa_fontes_alteradas_sem_erro(self):
        fonte = self.projeto / "src" / "app.py"
        fonte.parent.mkdir()
        fonte.write_text("print('v1')\n", encoding="utf-8")
        mapas = self.base / "03 - Graphify e Mapas de Projeto"
        mapa = mapas / "Mapa - Sintetico.md"
        mapa.write_text(nota("índice", extra=(
            f'conferido_em: 2026-10-13\nfontes_raiz: "{self.projeto}"\nfontes_conferidas:\n'
            f'  - "src/app.py sha256:{cerebro.sha256(fonte.read_bytes())}"\n')), encoding="utf-8")
        (mapas / "Mapa antigo.md").write_text(nota("índice"), encoding="utf-8")  # sem os campos: válido
        r = self.rodar("verificar")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("1 nota(s) com fontes conferidas, 0 a revisar", r.stdout)
        self.assertNotIn("revisar —", r.stdout)
        fonte.write_text("print('v2')\n", encoding="utf-8")
        r = self.rodar("verificar")
        self.assertEqual(r.returncode, 0, r.stdout)  # aviso de revisão, não erro
        self.assertIn("Mapa - Sintetico.md: revisar — fonte mudou desde a conferência de 2026-10-13", r.stdout)
        self.assertIn("1 a revisar", r.stdout)
        self.assertNotIn("ERRO", r.stdout)
        fonte.unlink()
        self.assertIn("fonte ausente ou ilegível", self.rodar("verificar").stdout)
        destino = "03 - Graphify e Mapas de Projeto/Mapa - Ruim.md"
        for extra in ("fontes_conferidas: [\"/x/a.py sha256:123\"]\nconferido_em: 2026-10-13\n",
                      f"fontes_conferidas: [\"/x/a.py sha256:{'a' * 64}\"]\n",
                      f"conferido_em: 2026-10-13\nfontes_conferidas: [\"rel/a.py sha256:{'a' * 64}\"]\n"):
            with self.subTest(extra=extra):
                g = self.gravar(destino, nota("índice", extra=extra))
                self.assertEqual(g.returncode, 1, g.stdout)
                self.assertIn("fontes_conferidas", g.stderr)

    def test_hook_sem_permissao_de_leitura_nao_falha(self):
        protocolo = self.base / cerebro.PROTOCOLO
        protocolo.chmod(0)
        try:
            if os.access(protocolo, os.R_OK):
                self.skipTest("usuário com acesso irrestrito (root); não dá para simular")
            texto = self.contexto_do_hook(str(self.projeto))
            self.assertIn("Cofre indisponível", texto)
            self.assertIn("Permission denied", texto)
        finally:
            protocolo.chmod(0o644)


if __name__ == "__main__":
    unittest.main()
