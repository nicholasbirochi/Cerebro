"""Verificações pequenas da integridade do cenário sintético ampliado."""
import tempfile
import unittest
from pathlib import Path

import benchmark_busca as benchmark


class CorpusSintetico(unittest.TestCase):
    def test_corpus_deterministico_e_contagem_real_de_arquivos(self):
        with tempfile.TemporaryDirectory() as pasta:
            a, b = Path(pasta) / "a", Path(pasta) / "b"
            registros, primeiro = benchmark.gerar_corpus(a, 40)
            _, segundo = benchmark.gerar_corpus(b, 40)
            self.assertEqual(primeiro, segundo)
            self.assertEqual(len(registros), 40)
            arquivos = list(a.rglob("*.md"))
            self.assertEqual(len(arquivos), 41)
            self.assertEqual(primeiro["caracteres"], sum(len(p.read_text()) for p in arquivos))
            self.assertEqual(primeiro["bytes_utf8"], sum(p.stat().st_size for p in arquivos))

    def test_consultas_cobrem_projeto_multiplos_termos_e_zero_resultado(self):
        self.assertEqual(len(benchmark.CONSULTAS), 8)
        self.assertTrue(any(len(c["termos"]) > 1 for c in benchmark.CONSULTAS))
        self.assertTrue(any(c.get("projeto") for c in benchmark.CONSULTAS))
        self.assertIn({"termos": ["inexistentezzz"]}, benchmark.CONSULTAS)


if __name__ == "__main__":
    unittest.main()
