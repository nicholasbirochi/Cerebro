# Benchmark da saída de busca

Medição executada em 16/10/2026 com Python 3.14. Compara a quantidade de texto devolvida pela ferramenta, sem chamar uma IA ou acessar um cofre pessoal.

## Reproduzir

Em um clone Git deste repositório que contenha a revisão de referência:

```bash
python3 tools/benchmark_busca.py
```

O script usa somente a biblioteca padrão e o Git local. Obtém `tools/cerebro.py` da revisão pública `40569e851506e3cd027004960f4b7d217bd0cb32` com `git show`, cria um cofre sintético temporário, executa as duas versões e remove o temporário ao terminar. Não faz fetch, inferências ou downloads. Um ZIP ou clone sem a revisão de referência não basta para essa comparação.

## Resultado reproduzível

Consulta `contexto`, com 40 notas relevantes sintéticas e um protocolo mínimo. As notas têm quatro linhas relevantes cada, sem variações históricas. Ambas as versões recebem `--trechos --max 5 --orcamento 12000`.

| Medida | Antes | Agora |
|---|---:|---:|
| Caracteres da saída inteira | 11.696 | 5.862 |
| Notas selecionadas | 5 | 5 |
| Trechos selecionados | 20 | 20 |

**49,9% menos caracteres**, com os mesmos nomes de notas e vinte trechos idênticos, incluindo os números de linha. Pontuações e resumos de orçamento podem mudar. O script falha se essa equivalência deixar de valer, se não houver redução ou se a saída ultrapassar o orçamento.

O padrão atual, medido separadamente, mostra duas notas em **2.495 caracteres**, dentro do limite de 2.500. Essa modalidade seleciona menos notas e não é usada para calcular a redução controlada de 49,9%.

O cenário evidencia o custo de listar individualmente muitas notas omitidas. A versão atual resume essas omissões em uma contagem. A melhoria da precisão da busca é coberta por testes próprios: siglas curtas, aliases de edição, prioridade do estado atual e preservação de resultados históricos.

## Outra observação local

Em uma consulta ao acervo pessoal em 16/10/2026, a comparação com as mesmas cinco notas e trechos passou de **11.961 para 4.677 caracteres: 60,9% menos texto**. Esse acervo não é distribuído; o resultado é uma observação adicional, não o benchmark reproduzível acima. Nenhum conteúdo das notas pessoais acompanha a medição pública.

## Limites

- São caracteres Unicode, incluindo quebras de linha. Não há conversão estimada para tokens.
- Trata-se de uma consulta e um cenário sintético fixo; não é uma média de projetos ou de conversas.
- A igualdade dos trechos verifica a preservação desse contexto selecionado. Não avalia a qualidade geral das respostas de uma IA.
- Não foram medidos tokens de entrada/saída/raciocínio, cache, latência, cota preservada ou economia financeira.
- Os **30% menos tokens** apresentados no one pager continuam sendo uma **simulação distinta**. A mensalidade não muda: **R$ 0 de desconto**.

Para comparar modelos ou níveis de esforço, use tarefas equivalentes com critérios de aceitação e contadores reais do cliente. A redução de texto desta ferramenta não substitui essa avaliação.
