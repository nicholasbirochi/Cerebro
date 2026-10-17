"""Verificações pequenas da integridade do cenário sintético ampliado."""
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import benchmark_busca as benchmark

RECURSOS = {"segundos": 0.01, "cpu_segundos": 0.01, "pico_memoria_mb": 10.0}


class CorpusSintetico(unittest.TestCase):
    def test_relatorio_calcula_totais_para_escalas_escolhidas(self):
        with patch.object(benchmark, "CONSULTAS", [{"termos": ["inexistentezzz"]}]), \
                patch.object(benchmark, "executar", return_value=("Nenhuma nota.\n", RECURSOS)):
            resultado = benchmark.medir_ampliado((2, 1))
        self.assertEqual([e["corpus"]["notas_de_conteudo"] for e in resultado["escalas"]], [1, 2])
        self.assertEqual(resultado["total"]["consultas_pareadas"], 2)
        self.assertEqual(resultado["total"]["execucoes"], 4)
        self.assertEqual(resultado["total"]["antes"], 2 * len("Nenhuma nota.\n"))
        self.assertEqual(resultado["escalas"][1]["agregado"]["recursos"]["antes"]["pico_memoria_mb_maximo"], 10.0)
        self.assertEqual(resultado["nao_executadas"], [])

    def test_retoma_escalas_do_arquivo_parcial_da_mesma_implementacao(self):
        with tempfile.TemporaryDirectory() as pasta, \
                patch.object(benchmark, "CONSULTAS", [{"termos": ["inexistentezzz"]}]), \
                patch.object(benchmark, "executar", return_value=("Nenhuma nota.\n", RECURSOS)) as executar:
            parcial = Path(pasta) / "parcial.json"
            primeiro = benchmark.medir_ampliado((1,), parcial)
            self.assertEqual(executar.call_count, 2)
            segundo = benchmark.medir_ampliado((1, 10), parcial)
            self.assertEqual(executar.call_count, 4)  # só a escala 10 foi executada de novo
            self.assertEqual(segundo["escalas"][0], primeiro["escalas"][0])
            dados = json.loads(parcial.read_text(encoding="utf-8"))
            dados["identidade"]["script_sha256"] = "outro"
            parcial.write_text(json.dumps(dados), encoding="utf-8")
            benchmark.medir_ampliado((1,), parcial)
            self.assertEqual(executar.call_count, 6)  # identidade diferente invalida o progresso

    def test_corpus_deterministico_e_contagem_real_de_arquivos(self):
        with tempfile.TemporaryDirectory() as pasta:
            a, b = Path(pasta) / "a", Path(pasta) / "b"
            primeiro = benchmark.gerar_corpus(a, 40)
            benchmark.gerar_corpus(b, 10)
            segundo = benchmark.gerar_corpus(b, 40, inicio=10)  # crescimento incremental
            self.assertEqual(primeiro, segundo)
            arquivos = list(a.rglob("*.md"))
            self.assertEqual(len(arquivos), 41)
            self.assertEqual(primeiro["arquivos_markdown"], 41)
            self.assertEqual(primeiro["caracteres"], sum(len(p.read_text()) for p in arquivos))
            self.assertEqual(primeiro["bytes_utf8"], sum(p.stat().st_size for p in arquivos))

    def test_acervo_incremental_reproduz_hashes_do_ensaio_publicado(self):
        historico = {1000: "d9a3d7b5e4193d72eb69db68908a7d0a0b71be372e8edb59c8c5d068f1802b8d",
                     10000: "676678e62c3ae9b2d9d2cdf4c604551d20af1af034c2d0e1c54ba49a2a57d7da"}
        with tempfile.TemporaryDirectory() as pasta:
            base, gerado = Path(pasta) / "cofre", 0
            for quantidade, esperado in historico.items():
                self.assertEqual(benchmark.gerar_corpus(base, quantidade, gerado)["sha256"], esperado)
                gerado = quantidade

    def test_elegibilidade_por_tema_projeto_e_escala(self):
        consulta = {"termos": ["roteamento"], "projeto": "Demo-00"}
        self.assertEqual(benchmark.elegiveis(100, consulta), len(range(0, 100, 28)))
        caminho = f"{benchmark.PASTA_NOTAS}/{benchmark.nota(28)[0]}"
        self.assertTrue(benchmark.nota_elegivel(caminho, 100, consulta))
        self.assertFalse(benchmark.nota_elegivel(caminho, 28, consulta))  # ainda não existe nesta escala
        self.assertFalse(benchmark.nota_elegivel(f"{benchmark.PASTA_NOTAS}/{benchmark.nota(4)[0]}", 100, consulta))
        self.assertFalse(benchmark.nota_elegivel(f"{benchmark.PASTA_NOTAS}/{benchmark.nota(1)[0]}", 100, consulta))

    def test_recusa_escala_sem_disco_ou_com_memoria_projetada_excessiva(self):
        livre = type("Uso", (), {"free": 6 * 2**30})
        with patch.object(benchmark.shutil, "disk_usage", return_value=livre):
            self.assertIn("disco", benchmark.recursos_insuficientes(".", 1_000_000, 0, []))
            self.assertIsNone(benchmark.recursos_insuficientes(".", 1000, 0, []))
            ram_mb = benchmark.os.sysconf("SC_PAGE_SIZE") * benchmark.os.sysconf("SC_PHYS_PAGES") / 2**20
            medidas = [(1000, 20.0), (10000, 20.0 + ram_mb / 10)]  # cresce ~ram/10 a cada 9.000 notas
            self.assertIn("memória", benchmark.recursos_insuficientes(".", 100_000, 0, medidas))
            self.assertIsNone(benchmark.recursos_insuficientes(".", 100_000, 0, medidas[:1]))

    def test_consultas_cobrem_projeto_multiplos_termos_e_zero_resultado(self):
        self.assertEqual(len(benchmark.CONSULTAS), 8)
        self.assertTrue(any(len(c["termos"]) > 1 for c in benchmark.CONSULTAS))
        self.assertTrue(any(c.get("projeto") for c in benchmark.CONSULTAS))
        self.assertIn({"termos": ["inexistentezzz"]}, benchmark.CONSULTAS)
        self.assertEqual(benchmark.ESCALAS, (1, 10, 100, 1000, 10000, 100000, 1000000))


if __name__ == "__main__":
    unittest.main()
