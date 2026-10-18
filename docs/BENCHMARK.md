# Benchmark de contexto: de 1 nota a 1 milhão de notas

Executado em 17/10/2026 em um Apple M5 com 24 GB de RAM, macOS e Python 3.14.7. O teste compara a busca `--trechos` da revisão pública de referência `40569e8` com a versão atual, usando apenas notas sintéticas. Não acessa o cofre pessoal, não chama IA e não usa API paga.

![Benchmark de contexto em sete escalas](../media/one-pager.png)

[Slide editável (PowerPoint)](../media/one-pager.pptx) · [JSON completo da execução](benchmark-ampliado.json)

## Medido, projetado ou não executado

| Escala | Situação |
|---|---|
| 1, 10, 100, 1.000, 10.000 e 100.000 notas | **Medido.** Arquivos reais em disco, 8 consultas pareadas por escala, 48 comparações e 96 execuções no total. |
| 1.000.000 de notas | **Não medido; aparece como projeção.** O acervo foi gerado em disco (2,83 GB), mas a primeira busca da versão anterior foi interrompida após 22,3 min sem terminar. |

Nenhuma simulação ilustrativa foi usada. Em tabelas e gráficos, a projeção aparece em itálico ou com bolinha vazada e linha tracejada, sempre com "≈".

### Por que 1 milhão não foi medido

O custo cresceu mais que o tamanho do acervo. De 10.000 para 100.000 notas, dez vezes mais notas, o tempo das 8 buscas cresceu **×45,2 na versão anterior** e ×15,9 na atual. Repetido até 1 milhão, isso dá cerca de **7,7 h** só para a versão anterior. Uma medição dessas ocuparia o Mac por uma noite inteira, para confirmar um resultado de caracteres que a estrutura do teste já limita.

A interrupção também produziu um dado real. A busca `roteamento` da versão anterior levou 55,9 s em 100.000 notas. Em 1 milhão, ela passou de **22,3 min** (20,3 min de CPU) sem terminar. Isso é um limite inferior medido, compatível com os ~31 min projetados para essa consulta.

### Como a projeção foi feita

- **Caracteres e tokens.** As saídas são limitadas a 5 notas e 12.000 caracteres por consulta. De 10.000 para 100.000 notas, elas mudaram só nos dígitos das contagens de omitidas: +14 caracteres por versão nas 8 consultas. A projeção repete esse acréscimo de 100.000 para 1 milhão: ≈ 83.900 → ≈ 40.607 caracteres, ≈ 51,6%.
- **Tempo.** Lei de potência por versão: o fator observado de 10.000 para 100.000 notas (×45,2 e ×15,9) é aplicado de novo. A projeção é ≈ 7,7 h antes e ≈ 42 min na versão atual, para as 8 buscas.
- **Memória.** Extrapolação linear do pico entre 10.000 e 100.000 notas: ≈ 3,4 GB por busca.
- **Tamanho do acervo.** Não é projeção: o acervo foi gerado, e seu tamanho exato foi recalculado pelo gerador determinístico.

Uma projeção não substitui a medição. Uma escala maior pode trazer efeitos de cache e memória que estes fatores não capturam.

## Reproduzir

Em um clone Git que contenha a revisão de referência:

```bash
python3 tools/benchmark_busca.py --ampliado                          # 1 a 10.000 notas, cerca de 30 s
python3 tools/benchmark_busca.py --escalas 1 10 100 1000 10000 100000 --parcial progresso.json   # esta execução
python3 tools/benchmark_busca.py --completo --parcial progresso.json  # inclui 1 milhão: ~4 GB e cerca de 8 h
python3 tools/benchmark_busca.py --escalas 40 1000 10000              # o ensaio anterior, de três escalas
```

O script usa biblioteca padrão e Git local. Obtém `tools/cerebro.py` da revisão `40569e851506e3cd027004960f4b7d217bd0cb32` com `git show` e executa as duas versões, em processos separados, contra os mesmos arquivos. O temporário é removido ao terminar, inclusive quando uma busca é interrompida. `--tokens` é opcional e requer a biblioteca `tiktoken` instalada à parte.

Cuidados com as escalas grandes:

- **Geração incremental.** As notas são determinísticas e cada escala é o prefixo da seguinte. O acervo cresce em um único diretório temporário, sem recriar notas. Cada escala é medida sobre exatamente o seu prefixo, igual a gerá-la do zero. Os testes conferem que os hashes de 1.000 e 10.000 notas reproduzem os do ensaio publicado em 16/10/2026.
- **Recursos.** Antes de cada escala, o script confere o disco e recusa a escala se sobrarem menos de 5 GiB livres. Também projeta o pico de memória a partir das duas escalas anteriores e recusa a escala se a projeção passar da metade da RAM física. O diretório termina em `.noindex`, para o Spotlight não indexá-lo. As buscas rodam uma por vez. Esta execução usou `nice -n 10`.
- **Retomada.** Com `--parcial ARQUIVO`, cada escala concluída é gravada. Uma execução interrompida retoma da escala seguinte, desde que o núcleo, o script, o Python e o tokenizador sejam os mesmos. Caso contrário, o arquivo é ignorado. O JSON publicado foi montado dessa forma, a partir do progresso gravado pela execução que chegou a 1 milhão.

## Volume de cada acervo

| Notas de conteúdo | Arquivos Markdown | Caracteres no acervo | Bytes UTF-8 | Tamanho | Situação |
|---:|---:|---:|---:|---:|---|
| 1 | 2 | 1.668 | 1.752 | 1,8 kB | Medido |
| 10 | 11 | 25.894 | 27.139 | 27,1 kB | Medido |
| 100 | 101 | 268.174 | 281.029 | 281,0 kB | Medido |
| 1.000 | 1.001 | 2.690.974 | 2.819.929 | 2,8 MB | Medido |
| 10.000 | 10.001 | 26.918.974 | 28.208.929 | 28,2 MB | Medido |
| 100.000 | 100.001 | 269.198.974 | 282.098.929 | 282,1 MB | Medido |
| 1.000.000 | 1.000.001 | 2.699.198.974 | 2.828.198.929 | 2,83 GB | Gerado em disco; busca interrompida |

O protocolo mínimo participa das contagens de arquivos e caracteres, mas não das notas de conteúdo. O acervo é contado uma vez, sem multiplicar pelas consultas, e não representa conteúdo enviado a uma IA. Em disco, 1 milhão de notas ocupou cerca de 3,8 GB, porque cada arquivo pequeno usa um bloco inteiro.

## Texto retornado, em caracteres

| Escala | Saída antes, caracteres | Saída atual, caracteres | Caracteres a menos | Redução | Mesmas notas e trechos |
|---|---:|---:|---:|---:|---:|
| 1 nota | 4.667 | 4.667 | 0 | 0,0% | 8/8 |
| 10 notas | 23.587 | 23.509 | 78 | 0,3% | 8/8 |
| 100 notas | 64.082 | 39.371 | 24.711 | 38,6% | 8/8 |
| 1.000 notas | 82.546 | 40.565 | 41.981 | 50,9% | 8/8 |
| 10.000 notas | 83.872 | 40.579 | 43.293 | 51,6% | 8/8 |
| 100.000 notas | 83.886 | 40.593 | 43.293 | 51,6% | 8/8 |
| *1.000.000 notas, projeção* | *≈ 83.900* | *≈ 40.607* | *≈ 43.293* | *≈ 51,6%* | não medido |
| **Total medido, 48 consultas** | **342.640** | **189.284** | **153.356** | **44,8%** | **48/48** |

A redução total medida é `(342.640 − 189.284) ÷ 342.640 × 100`. Ela pondera o volume de saída, sem tirar a média simples dos percentuais, e soma consultas distintas: não é o tamanho de uma única resposta. A projeção fica fora dos totais.

## Tokens: análise separada

Contagem com **tiktoken 0.14.0, codificação `o200k_base`**, a codificação pública usada pelos modelos GPT-4o em diante da OpenAI. Nenhuma API foi chamada.

| Escala | Tokens antes | Tokens atuais | Tokens a menos | Redução em tokens | Redução em caracteres |
|---|---:|---:|---:|---:|---:|
| 1 nota | 1.227 | 1.227 | 0 | 0,0% | 0,0% |
| 10 notas | 6.064 | 6.036 | 28 | 0,5% | 0,3% |
| 100 notas | 18.384 | 10.085 | 8.299 | 45,1% | 38,6% |
| 1.000 notas | 24.481 | 10.396 | 14.085 | 57,5% | 50,9% |
| 10.000 notas | 24.925 | 10.408 | 14.517 | 58,2% | 51,6% |
| 100.000 notas | 24.927 | 10.410 | 14.517 | 58,2% | 51,6% |
| *1.000.000 notas, projeção* | *≈ 24.929* | *≈ 10.412* | *≈ 14.517* | *≈ 58,2%* | *≈ 51,6%* |
| **Total medido** | **100.008** | **48.562** | **51.446** | **51,4%** | **44,8%** |

A partir de 100 notas, a redução em tokens é maior que a redução em caracteres. As linhas que a versão anterior listava para cada nota omitida, com caminhos, acentos e números, rendem mais tokens por caractere do que os trechos mantidos. Na consulta `roteamento` com 1.000 notas, essas linhas tiveram cerca de 3,0 caracteres por token, contra 4,1 nos trechos.

Como ler esses números:

- **Não é o tokenizador do Claude.** A Anthropic não publica um tokenizador local para os modelos atuais. A contagem para Claude não foi medida, e modelos mais novos da OpenAI podem usar outra codificação.
- **Não é o consumo total da conversa.** Mede só o texto devolvido pela busca. Uma conversa real inclui instruções, histórico, ferramentas, respostas e tokens de raciocínio. A redução no total cobrado é menor que a redução mostrada aqui.
- **Não é economia financeira.** Nenhum custo em dinheiro foi calculado. Em planos por assinatura, a mensalidade não muda.

## Tempo, CPU e memória

| Escala | Gerar e conferir o acervo | 8 buscas antes | 8 buscas atuais | Média por busca atual | CPU antes → atual | Pico de memória por busca |
|---|---:|---:|---:|---:|---:|---:|
| 1 nota | 0,0 s | 0,3 s | 0,3 s | 0,04 s | 0,3 s → 0,3 s | 30 MB |
| 10 notas | 0,0 s | 0,3 s | 0,3 s | 0,04 s | 0,3 s → 0,3 s | 30 MB |
| 100 notas | 0,0 s | 0,5 s | 0,5 s | 0,06 s | 0,4 s → 0,4 s | 30 MB |
| 1.000 notas | 0,1 s | 1,3 s | 1,4 s | 0,17 s | 1,3 s → 1,3 s | 33 MB |
| 10.000 notas | 0,8 s | 13,6 s | 10,1 s | 1,26 s | 13,5 s → 10,0 s | 64 MB |
| 100.000 notas | 15,8 s | 10 min | 3 min | 20,02 s | 9 min → 101,3 s | 374 MB |
| *1.000.000 notas, projeção* | gerado; tempo não registrado | *≈ 7,7 h* | *≈ 42 min* | *≈ 5,3 min* | — | *≈ 3,4 GB* |

- **A redução de contexto não custou tempo.** Somando as escalas medidas, foram 11 min antes e 3 min na versão atual. Em 100.000 notas, a busca atual foi **3,8× mais rápida**: 10 min contra 3 min nas 8 consultas. Até 1.000 notas, as diferenças ficam abaixo de um décimo de segundo por busca e se confundem com a variação entre execuções.
- **O crescimento é diferente nas duas versões.** De 10.000 para 100.000 notas, dez vezes mais notas, a atual cresceu ×15,9 e a anterior ×45,2. As duas leem todas as notas a cada busca, sem índice. A causa do crescimento mais rápido da anterior não foi investigada.
- **O limite prático é o tempo, não o contexto.** O texto devolvido fica estável, mas uma busca atual de 20 s em 100.000 notas, ou de ≈ 5 min projetados em 1 milhão, não serve para uso interativo. Acervos dessa ordem pediriam um índice persistente, que este benchmark não avalia.
- **Leitura do disco.** Em 100.000 notas, o tempo de parede da versão atual (3 min) supera o de CPU (101,3 s). A diferença é a leitura dos 282 MB de arquivos.
- Os tempos incluem a inicialização do Python e vêm de uma passagem por caso, sem controle de cache nem repetições estatísticas. O pico de memória é o RSS máximo de cada processo de busca.

## Como a redução evolui

- **Com 1 nota não há o que economizar.** As duas versões devolvem exatamente o mesmo texto: 0,0%.
- **Com 10 notas a diferença é mínima (0,3%).** Quase todas as notas elegíveis cabem no limite de cinco, e sobram poucas omissões para listar.
- **A partir de 100 notas a redução aparece (38,6%)** e fica entre 50,9% a 51,6% de 1.000 a 100.000 notas.
- **Depois disso ela estabiliza; não cresce sem limite.** As duas versões respeitam o mesmo teto de cinco notas e 12.000 caracteres por consulta. A anterior gasta o espaço restante listando nota omitida por nota omitida até encher o orçamento; a atual resume as omissões em uma linha. Quando o acervo passa de algumas centenas de notas relevantes, as duas saídas atingem seus tetos e a diferença deixa de mudar. Em tokens, a faixa é 57,5% a 58,2%.

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

Ambas as versões recebem `--trechos --max 5 --orcamento 12000`. As notas têm tema explícito, projeto sintético e quatro linhas relevantes, com material complementar de tamanho variável.

**Todas as 48 comparações medidas preservaram a mesma ordem de notas e os mesmos trechos, incluindo números de linha.** O script também confere a quantidade esperada de resultados, se cada nota devolvida existe naquela escala e pertence ao tema e ao projeto pedidos, e o limite da saída. Ele falha se alguma verificação divergir. Pontuações e resumos podem mudar e ficam fora da equivalência de conteúdo. A equivalência em 1 milhão de notas não foi verificada.

## Histórico preservado

**Ensaio de três escalas, 16/10/2026.** 40, 1.000 e 10.000 notas, 24 consultas pareadas: 210.965 → 118.299 caracteres, redução de 43,9%. Por escala: 16,6% em 40 notas, 50,9% em 1.000 e 51,6% em 10.000. O JSON original está em [benchmark-tres-escalas-2026-10-16.json](benchmark-tres-escalas-2026-10-16.json) e pode ser refeito com `--escalas 40 1000 10000`. Nesta execução, 1.000 e 10.000 notas reproduziram os mesmos acervos, com hashes idênticos, e as mesmas saídas: 82.546 → 40.565 e 83.872 → 40.579 caracteres.

**Comando rápido original.** `python3 tools/benchmark_busca.py`, sem opções, usa um corpus próprio de 40 notas e a consulta `contexto`: 11.696 → 5.862 caracteres, redução de 49,9%, com cinco notas e vinte trechos idênticos. O padrão de duas notas produziu 2.495 caracteres.

**Medição no acervo pessoal.** Uma consulta em 16/10/2026, na versão `663803e`, produziu 11.961 → 4.677 caracteres, redução de 60,9%, com as mesmas cinco notas e trechos. Os dados privados não são distribuídos, e o resultado não é extrapolado para esta bateria.

## Limites

- Os acervos são inteiramente sintéticos e regulares. Acervos reais têm notas e distribuições de relevância diferentes.
- 1 milhão de notas é projeção. Só o tamanho do acervo e o limite inferior de tempo da primeira busca foram observados.
- Caracteres Unicode, bytes UTF-8 e tokens são unidades distintas. A contagem de tokens usa `o200k_base`, não o tokenizador do Claude.
- O tamanho do acervo consultado não é o volume enviado a um modelo.
- A equivalência compara a seleção de contexto nestes casos e não avalia inferências nem a qualidade geral das IAs.
- Esta bateria não mede tokens de uma conversa completa. O A/B com o Codex cru e o repositório completo, com tokens do modelo e acurácia, está em [AB-CODEX.md](AB-CODEX.md). Produtividade e economia financeira não foram medidas.
- Os percentuais dependem do cenário. Não há promessa universal de 50% ou 60%.
