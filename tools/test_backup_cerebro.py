"""Testes do backup_cerebro.py com cofre sintético temporário (nunca copia o cofre real).

python3 -m unittest discover -s "<cofre>/.cerebro" -p "test_*.py"
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PASTA = Path(__file__).resolve().parent
SCRIPT = PASTA / "backup_cerebro.py"


def nota(tipo, extra="", corpo="Corpo.\n"):
    return (f"---\ntipo: {tipo}\nstatus: ativo\ncriado_em: 2026-10-13\natualizado_em: 2026-10-13\n"
            f"{extra}---\n{corpo}")


class BackupSintetico(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="backup-teste-"))
        self.cofre = self.tmp / "Cérebro"
        for pasta in ("00 - Regras para Agentes", "01 - Índices", ".cerebro"):
            (self.cofre / pasta).mkdir(parents=True)
        (self.cofre / "00 - Regras para Agentes/Protocolo dos Agentes.md").write_text(
            nota("regra", "autorizacao: teste\n"), encoding="utf-8")
        (self.cofre / "01 - Índices/Índice de regras.md").write_text(
            nota("índice", corpo="[[Protocolo dos Agentes]]\n"), encoding="utf-8")
        shutil.copy2(PASTA / "cerebro.py", self.cofre / ".cerebro/cerebro.py")
        (self.cofre / ".cerebro/test_minimo.py").write_text(
            "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n", encoding="utf-8")
        (self.cofre / ".cerebro/.trava").write_text("", encoding="utf-8")  # excluído por nome
        self.saida = self.tmp / "destino"
        self.env = dict(os.environ, CEREBRO_DIR=str(self.cofre), PYTHONDONTWRITEBYTECODE="1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rodar(self, saida, *extra):
        return subprocess.run([sys.executable, "-I", str(SCRIPT), str(saida), *map(str, extra)], capture_output=True,
                              text=True, env=self.env, timeout=120)

    def hashes(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.saida.iterdir()}

    def test_backup_restaura_confere_e_nao_sobrescreve(self):
        r = self.rodar(self.saida)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("RESULTADO: restauração comprovada", r.stdout)
        manifestos = list(self.saida.glob("*.MANIFESTO.json"))
        self.assertEqual(len(manifestos), 1)
        m = json.loads(manifestos[0].read_text(encoding="utf-8"))
        self.assertTrue(m["restauracao"]["comprovada"])
        self.assertEqual(m["restauracao"]["arquivos_identicos"], m["restauracao"]["total"])
        self.assertEqual(m["restauracao"]["total"], 4)  # .trava fica de fora
        # a pasta temporária do mesmo disco nunca é declarada backup independente
        self.assertTrue(m["mesmo_disco_do_cofre"])
        self.assertIs(m["backup_independente"], False)
        self.assertIn("independência: NÃO", r.stdout)
        self.assertEqual([p for p in self.saida.iterdir() if p.is_dir()], [])  # restauração temporária removida
        antes = self.hashes()
        de_novo = self.rodar(self.saida)  # no mesmo minuto recusa; noutro cria um conjunto novo
        if de_novo.returncode != 0:
            self.assertIn("nada sobrescrito", de_novo.stdout + de_novo.stderr)
        depois = self.hashes()
        self.assertEqual({k: depois[k] for k in antes}, antes)  # versões anteriores intactas

    def test_link_para_pasta_guardado_sem_percorrer(self):
        # como os node_modules do arquivo de agentes: link para uma pasta fora do cofre
        alvo = self.tmp / "alvo externo"
        alvo.mkdir()
        (alvo / "conteudo.txt").write_text("não deve ser copiado\n", encoding="utf-8")
        (self.cofre / ".cerebro" / "node_modules").symlink_to(alvo, target_is_directory=True)
        r = self.rodar(self.saida)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = json.loads(next(self.saida.glob("*.MANIFESTO.json")).read_text(encoding="utf-8"))
        self.assertEqual(m["links"], {".cerebro/node_modules": str(alvo)})
        self.assertEqual(m["arquivos"], 4)
        self.assertEqual(m["restauracao"]["total"], 5)  # 4 arquivos + o link, conferido pelo destino
        self.assertEqual(m["restauracao"]["arquivos_identicos"], 5)
        with tarfile.open(next(self.saida.glob("*.tar.gz"))) as t:
            nomes = t.getnames()
            link = [t.getmember(n) for n in nomes if n.endswith("/.cerebro/node_modules")]
            self.assertEqual(len(link), 1)
            self.assertTrue(link[0].issym())
            self.assertEqual(link[0].linkname, str(alvo))
            self.assertFalse([n for n in nomes if "/node_modules/" in n])  # o alvo não foi percorrido
        # a restauração confere o destino: um tar com outro destino para o link reprova
        spec = importlib.util.spec_from_file_location("backup_cerebro", SCRIPT)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        modulo.COFRE = self.cofre
        original = tarfile.TarFile.gettarinfo

        def destino_trocado(tf, name=None, arcname=None, fileobj=None):
            info = original(tf, name, arcname, fileobj)
            if info.issym():
                info.linkname = "/outro/destino"
            return info

        outra = self.tmp / "destino-trocado"
        with mock.patch.object(tarfile.TarFile, "gettarinfo", destino_trocado), \
                mock.patch.object(sys, "argv", ["backup_cerebro.py", str(outra)]), \
                contextlib.redirect_stdout(io.StringIO()) as saida:
            self.assertEqual(modulo.main(), 1)
        self.assertIn("RESULTADO: FALHOU", saida.getvalue())
        m = json.loads(next(outra.glob("*.MANIFESTO.json")).read_text(encoding="utf-8"))
        self.assertFalse(m["restauracao"]["comprovada"])
        self.assertEqual(m["restauracao"]["arquivos_identicos"], 4)

    def test_restauracao_em_pasta_local_indicada(self):
        # saída sincronizada com a nuvem: a extração temporária fica fora dela
        local = self.tmp / "restauracao local"
        local.mkdir()
        r = self.rodar(self.saida, local)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = json.loads(next(self.saida.glob("*.MANIFESTO.json")).read_text(encoding="utf-8"))
        self.assertTrue(m["restauracao"]["comprovada"])
        self.assertEqual(m["restauracao"]["extraido_em"], str(local.resolve()))
        self.assertEqual(Path(m["restauracao"]["lido_de"]).parent, self.saida.resolve())
        self.assertIs(m["backup_independente"], False)
        self.assertEqual(list(local.iterdir()), [])  # temporária removida
        self.assertEqual(sorted(p.suffix for p in self.saida.iterdir()), [".SHA256SUMS", ".gz", ".json", ".sha256"])
        for invalida in (self.tmp / "nao-existe", self.cofre / ".cerebro"):
            with self.subTest(invalida=invalida):
                self.assertIn("pasta da restauração", self.rodar(self.tmp / "outra", invalida).stderr)

    def test_recusa_saida_dentro_do_cofre(self):
        r = self.rodar(self.cofre / ".cerebro" / "backups")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("dentro do cofre", r.stderr)
        self.assertFalse((self.cofre / ".cerebro" / "backups").exists())

    def test_independencia_por_disco_fisico(self):
        spec = importlib.util.spec_from_file_location("backup_cerebro", SCRIPT)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        modulo.COFRE = self.cofre
        self.saida.mkdir()
        self.assertEqual(modulo.independencia(self.saida)[0], False)
        modulo.mesmo_disco = lambda _: False  # simula outro volume: decide pelo disco físico
        casos = [
            ("disk0", "disk0", {}, False),
            ("disk0", "disk6", {"BusProtocol": "USB"}, True),
            ("disk0", "disk4", {"BusProtocol": "Disk Image"}, None),
            ("disk0", None, None, None),
        ]
        for origem, destino, info, esperado in casos:
            with self.subTest(destino=destino, info=info):
                modulo.disco_fisico = lambda c, o=origem, d=destino, i=info: (o, {}) if c == self.cofre else (d, i)
                self.assertIs(modulo.independencia(self.saida)[0], esperado)


if __name__ == "__main__":
    unittest.main()
