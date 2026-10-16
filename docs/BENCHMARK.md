# Benchmark ampliado da saída de busca

Executado em 16/10/2026 com Python 3.14 no macOS. O teste mede a saída da ferramenta usando apenas dados sintéticos. Não acessa cofre pessoal nem chama uma IA.

## Reproduzir

Em um clone Git que contenha a revisão pública de referência:

```bash
python3 tools/benchmark_busca.py --ampliado
```

O script usa biblioteca padrão e Git local. Obtém `tools/cerebro.py` da revisão `40569e851506e3cd027004960f4b7d217bd0cb32` com `git show`, cria corpora temporários determinísticos e executa as duas versões contra os mesmos arquivos. Remove o temporário ao terminar. Não faz fetch, download, inferência ou backup pessoal. Um ZIP ou clone sem a revisão de referência não basta.

[JSON completo da execução](benchmark-ampliado.json), incluindo consultas, hashes dos corpora, contagens e tempos observados. Os hashes do núcleo atual e do script permitem identificar exatamente a implementação avaliada.

## Volume de conteúdo e saída retornada

| Notas de conteúdo | Arquivos Markdown, incluindo protocolo | Caracteres no acervo | Bytes UTF-8 | Consultas |
|---|---:|---:|---:|---:|
| 40 | 41 | 105.046 | 110.089 | 8 |
| 1.000 | 1.001 | 2.690.974 | 2.819.929 | 8 |
| 10.000 | 10.001 | 26.918.974 | 28.208.929 | 8 |

Cada escala reutiliza o prefixo de notas da anterior. Por isso, o maior acervo tem 10.000 notas de conteúdo, não 11.040 notas únicas. Seu tamanho é contado uma vez, sem multiplicar pelas consultas. O protocolo mínimo participa das contagens de caracteres e arquivos, mas não das notas de conteúdo.

| Escala | Saída antes, caracteres | Saída atual, caracteres | Caracteres a menos | Redução |
|---|---:|---:|---:|---:|
| 40 notas, 8 consultas | 44.547 | 37.155 | 7.392 | 16,6% |
| 1.000 notas, 8 consultas | 82.546 | 40.565 | 41.981 | 50,9% |
| 10.000 notas, 8 consultas | 83.872 | 40.579 | 43.293 | 51,6% |
| Total de 24 consultas | 210.965 | 118.299 | 92.666 | 43,9% |

A redução total é `(210.965 − 118.299) ÷ 210.965 × 100`, arredondada. Ela pondera o volume efetivo de saída, sem tirar a média simples dos percentuais. Os totais somam consultas distintas e não são o tamanho de uma única resposta.

## Consultas e equivalência

Cada escala recebe as mesmas oito consultas, nesta ordem:

1. `roteamento`
2. `validacao`
3. `interface`
4. `publicacao`
5. `roteamento validacao`
6. `interface publicacao`
7. `roteamento --projeto Demo-00`
8. `inexistentezzz`, para conferir ausência de resultado

Ambas as versões recebem `--trechos --max 5 --orcamento 12000`. As notas têm um tema explícito, projeto sintético e quatro linhas relevantes, com material complementar de tamanho variável. As seções neutras evitam misturar a redução de omissões com mudanças de relevância por histórico ou aliases. O objetivo desta bateria é medir o volume de texto devolvido preservando a seleção.

**Todas as 24 comparações preservaram a mesma ordem de notas e os mesmos trechos, incluindo números de linha.** O script também confere a quantidade esperada de resultados, se cada nota pertence ao tema/projeto correto e o limite da saída. Falha se alguma dessas verificações divergir. Pontuações e resumos podem mudar e ficam fora da equivalência de conteúdo. As contagens de saída incluem omissões, resumo e quebras de linha.

Os testes do núcleo cobrem separadamente termos curtos, aliases, prioridade do estado atual e resultados históricos. A equivalência deste corpus não comprova a qualidade geral das respostas de uma IA.

## Tempos observados

O JSON registra a duração de cada processo completo, alternando a ordem antes/atual entre consultas. Há uma passagem por caso, sem controle de cache ou repetições estatísticas. Esses tempos ajudam a reproduzir e diagnosticar a execução; não sustentam alegação de aceleração, menor espera do usuário ou latência de uma IA.

## Medições anteriores, com outros cenários

O comando rápido original continua disponível:

```bash
python3 tools/benchmark_busca.py
```

Seu corpus específico de 40 notas relevantes e a consulta `contexto` produziram 11.696 → 5.862 caracteres, redução de 49,9%, com cinco notas e vinte trechos idênticos. O padrão de duas notas produziu 2.495 caracteres. Esse corpus e essa consulta diferem dos oito casos da escala de 40 notas acima.

Uma consulta ao acervo pessoal em 16/10/2026, na versão `663803e09609cc6c47202745564243b05d82f8a4`, produziu 11.961 → 4.677 caracteres, redução de 60,9%, com as mesmas cinco notas e trechos. Seus dados privados não são distribuídos. É uma observação histórica específica, sem extrapolação para a bateria ampliada.

O [one pager](../media/one-pager.png) e o [slide editável](../media/one-pager.pptx) agora mostram a análise ampliada. As antigas projeções hipotéticas de tokens por período, espera e equivalência financeira foram retiradas.

## Limites

- Os corpora ampliados são inteiramente sintéticos, sem dados pessoais ou de projetos privados.
- Caracteres Unicode e bytes UTF-8 são unidades distintas. Nenhum valor foi convertido em tokens.
- O tamanho do corpus consultado não é o volume enviado a um modelo.
- A equivalência compara a seleção de contexto nestes casos; não avalia inferências ou qualidade geral das IAs.
- Tokens de entrada/saída/raciocínio, cache de modelos, produtividade e economia financeira não foram medidos. A mensalidade permanece igual.
- Os percentuais variam conforme cenário e distribuição de notas relevantes. Não há promessa universal de 60%.
