# A/B: Codex cru × repositório completo

Mesmo modelo, mesma pasta e mesmas tarefas, em duas condições. Só muda o ambiente em volta do agente.

| Condição | O que o Codex recebe |
|---|---|
| **Cru** | `codex exec --ignore-user-config --ignore-rules -c project_doc_max_bytes=0 --disable hooks`: sem configuração do usuário, regras, AGENTS, hooks, skills ou Cérebro. O prompt pede que use só o próprio conhecimento e os arquivos da pasta. |
| **Repositório completo** | Configuração normal: hook de início do Cérebro, Protocolo dos Agentes, busca com trechos e roteador `auxiliares.py` para Ollama, Copilot e Nemotron. |

Ambiente: 18/10/2026, Codex CLI 0.147.0, `gpt-5.6-sol` com esforço médio, Apple M5 com 24 GB, 6 rodadas por lado (25 perguntas por rodada = 150 respostas por lado). Os tokens do principal (entrada, entrada em cache e saída) vêm dos eventos `turn.completed` do próprio Codex; os tokens locais vêm do registro do roteador.

## Acurácia

[![One pager do A/B: 30/150 → 150/150 respostas certas e 49% menos tokens por resposta certa](../media/ab-acuracia.png)](../media/ab-acuracia.png)

| Tarefa | Cru | Completo |
|---|---:|---:|
| 20 perguntas que dependem do contexto do usuário (6 rodadas) | 0/120 | 120/120 |
| 5 perguntas respondíveis pelos arquivos da pasta (6 rodadas) | 30/30 | 30/30 |
| **Total do questionário** | **30/150 (20%)** | **150/150 (100%)** |
| Tabela Markdown a partir de `dados.txt` | 6/6 | 6/6 |
| 30 descrições curtas (formato conferido; medição anterior, 2 rodadas) | 2/2 | 2/2 |
| Tempo médio do questionário | 19,2 s | 42,4 s |

O cru respondeu "não sei" em todas as perguntas de contexto e não inventou nenhuma resposta. As tarefas que dependem só da pasta não pioraram com o repositório.

## Tokens

| Medida (média de 6 rodadas) | Cru | Completo |
|---|---:|---:|
| Tokens do principal, questionário | 48 mil | 123 mil |
| Tokens do principal, tabela | 66 mil | 103 mil |
| Tokens do principal, 30 descrições (medição anterior, 2 rodadas) | 72 mil | 156 mil |
| Tokens por resposta certa, questionário | 9,6 mil | 4,9 mil |

O repositório completo **lê mais** em cada sessão (+56% a +156%, quase todo em cache) e mesmo assim **gasta 49% menos tokens por resposta certa**: o cru gasta tokens e não acerta o que depende do contexto.

**Delegar ao modelo local ainda não compensa em tarefas pequenas.** Nas 30 descrições, a delegação ao Qwen 2.5 Coder 7B elevou os tokens do principal para 228 mil (dica), 375 mil (comando) e 254 mil (rascunho), contra 156 mil sem delegar. O 7B foi reprovado na validação de formato nas 4 delegações validadas, e o principal reler o contexto a cada passo custa mais do que as 30 linhas economizadas. O fluxo de rascunho, que guarda a resposta reprovada e aponta só as linhas ruins, reduziu o custo de 375 mil para 254 mil.

O que vem a seguir:

1. Delegar só saídas grandes (centenas de linhas) que passem na primeira validação.
2. Texto em português vai para o 14B; o 7B fica com transformações exatas (ordenar, extrair, renomear).
3. Evitar plugins globais em projetos do Cérebro; o principal leu a skill Ponytail em quase toda execução.
4. Corrigir rascunhos em vez de refazer a tarefa.

## Código, até acertar: qual contexto custa menos

[![One pager do A/B de código: hook curto com 23% menos tokens pagos que o atual e 35/36 convenções na 1ª tentativa](../media/ab-codigo.png)](../media/ab-codigo.png)

Três tarefas de código (CNPJ, Agenda e Pontos, descritas no README) × 3 rodadas, cada uma repetida até ser **aceita**: passar nos testes ocultos, nos extras e nas convenções do usuário. A medida é o custo de **tokens pagos** até a aceitação: entrada fora do cache + saída (o cache não entra na cota da mesma forma).

| Condição | O que muda |
|---|---|
| **Cru** | como acima, sem nenhum contexto |
| **Atual** | hook de hoje: Protocolo dos Agentes inteiro + perfil do projeto |
| **Hook curto** | só o resumo das regras que mudam o comportamento + perfil; o resto fica disponível pela busca |
| **Validação proporcional** (só Pontos) | `AGENTS.md` do Pontos pede testes conforme o risco, não a suíte inteira a cada mudança |
| **Hook curto + proporcional** (só Pontos) | as duas mudanças juntas |

| Tokens pagos até aceitar (média de 3) | Cru | Atual | Hook curto | Proporcional | Hook curto + prop. |
|---|---:|---:|---:|---:|---:|
| Agenda | 55,9 mil | 43,9 mil | 49,9 mil | | |
| CNPJ | 42,3 mil | 59,9 mil | 31,0 mil | | |
| Pontos | 39,2 mil | 97,1 mil | 82,8 mil | 40,5 mil | 49,9 mil |
| Convenções seguidas na 1ª tentativa (3 tarefas) | 18/36 | 29/36 | **35/36** | | |
| Tentativas nas 9 execuções | 20 | 18 | **14** | | |

Comparações pareadas (mesma tarefa e rodada), com razão geométrica, IC 95% por bootstrap (20 mil reamostragens) e Wilcoxon exato:

| Comparação | Tokens pagos | IC 95% | p |
|---|---:|---:|---:|
| Atual × cru (9 pares) | ×1,42 | 1,04–1,93 | 0,10 |
| Hook curto × cru (9 pares) | ×1,09 | 0,76–1,56 | 0,73 |
| **Hook curto × atual** (9 pares) | **×0,77** | 0,59–1,02 | 0,16 |
| Hook curto × atual, só CNPJ | ×0,51 | 0,42–0,68 | |
| Pontos: proporcional × atual | ×0,41 | 0,34–0,48 | |
| **Pontos: hook curto + proporcional × atual** | **×0,50** | 0,37–0,64 | |
| Pontos: hook curto + proporcional × cru | ×1,24 | 0,99–1,76 | |

Convenções: o atual segue mais regras que o cru (29 × 18 em 36, p = 0,031), e o hook curto segue ainda mais (35 × 29, p = 0,031), com 8 das 9 execuções aceitas já na 1ª tentativa.

**Melhor cenário: hook curto + validação proporcional.** O hook curto custa perto do cru (×1,09) e segue quase todas as convenções; o protocolo inteiro no início da sessão é o que encarece o atual. No Pontos, o excesso vinha de rodar toda a validação a cada passo: pedir testes proporcionais ao risco corta metade dos tokens pagos sem perder convenções. O Pontos continua mais caro que o cru (×1,24) porque segue regras que o cru ignora. **Aplicado em 18/10/2026:** o hook de início agora injeta só esse resumo (cerca de 1,9 mil caracteres, contra ~5 mil só da seção Essencial). O texto vem da seção `## Resumo do hook` do Protocolo, quando existe, ou do padrão `RESUMO` em [tools/cerebro.py](../tools/cerebro.py).

## Limites

- 6 rodadas por lado (150 respostas cada); as 30 descrições ainda são da medição anterior, com 2 rodadas. Diferenças pequenas de tempo estão dentro da variação.
- Só o Codex foi testado. O Claude Code não entrou nesta rodada.
- A correção é automática: e-mail, pasta e comando por expressão regular, tabela linha a linha e descrições só no formato, não na qualidade do texto.
- As perguntas de contexto foram escritas a partir do cofre pessoal e não são distribuídas; o cru não tinha como acertá-las, e é isso que o teste mostra: o ganho vem do contexto, não do modelo.
- Tokens locais (Ollama) não consomem a cota do Codex nem do Claude; o custo deles é tempo de máquina.
- No A/B de código: n = 3 por tarefa, então os intervalos são largos e só os efeitos grandes (convenções, Pontos com validação proporcional) são firmes. O hook curto e o "hook curto + proporcional" rodaram depois das outras séries e em sequência; o hook curto foi simulado no prompt, e o repositório completo com o hook real ficou em ×1,25 (IC 0,84–1,79) contra o cru.
