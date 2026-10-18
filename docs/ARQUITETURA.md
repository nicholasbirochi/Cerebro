# Roteamento central e memória compartilhada

O usuário escolhe Claude Code ou Codex para conduzir o pedido. O principal consulta o Cérebro, envia uma tarefa delimitada ao roteador e revisa o resultado. As duas entradas são alternativas.

## Arquitetura de delegação

O roteador concentra três caminhos: Copilot, Ollama e OpenCode/Nemotron. A escolha considera tipo de tarefa, franquia incluída atual, adequação do modelo e memória disponível. A resposta volta pelo roteador ao principal. As condições de custo e segurança prevalecem sobre a preferência por um provedor. Perto do limite semanal do principal (90%), o modo economia amplia a delegação a código médio e análise sem dados sensíveis; o principal passa a revisar mais e escrever menos.

## Três destinos implementados

`tools/auxiliares.py` concentra Ollama, Copilot e Nemotron via OpenCode. A linha do Copilot é contínua, como as demais saídas. A escolha muda conforme a tarefa e a elegibilidade; isso não muda a camada do auxiliar. Copilot requer franquia incluída verificada e overage desativado, usa Auto/Efficiency e executa uma resposta textual sem ferramentas. A integração foi validada em 14/10/2026. O principal decide quando delegar: não existe interceptação automática de toda mensagem do chat.

Nemotron respondeu em inferência real via OpenCode em 13/10/2026 (56 tokens de entrada e 2 de saída, aproximadamente 19 segundos). A configuração privada da máquina o habilita; o exemplo público permanece desativado até o usuário fornecer sua própria configuração elegível.

## Memória e monitoramento

Cérebro guarda regras e conhecimento em Markdown, com navegação pelo Obsidian e consulta e escrita controlada por `cerebro.py`. Graphify apoia a exploração das relações do código. Noah oferece voz e texto e segue em desenvolvimento.

Codenotch é uma camada separada de monitoramento, retirada do mapa de encaminhamento de mensagens. Não se presume cobertura universal de provedores. Os pontos animados são mensagens ilustrativas da arquitetura-alvo, não telemetria de tráfego.

## Mapas e contexto em camadas

Uma consulta começa por projeto e trechos: até duas notas e 2.500 caracteres por padrão. Primeiro use o estado atual e a rota pertinente; consulte o histórico e amplie `--max`/`--orcamento` apenas se faltar informação. As omissões são contadas, sem listar dezenas de notas. O resumo continua informando a quantidade exibida e os caracteres da saída inteira.

O mesmo matching orienta a seleção de notas e de trechos: termos de até três caracteres exigem palavra inteira, os aliases de edição são explícitos e termos maiores continuam aceitando correspondência parcial. A pontuação dá peso maior a seções `Estado atual`, `Resumo atual`, `Situação atual` e `Status atual`, e menor a `Histórico`; subseções herdam o peso até um cabeçalho do mesmo nível ou superior. Trechos atuais aparecem primeiro, seguidos pela quantidade de termos distintos. O histórico permanece disponível quando relevante. O [benchmark sintético](BENCHMARK.md) mede separadamente a quantidade de texto retornado.

Uma seção curta no mapa pode indicar tarefa, arquivo e validação. Exemplo com as próprias ferramentas públicas:

| Tarefa | Consultar | Validação |
|---|---|---|
| Busca, relevância e orçamento | `tools/cerebro.py`: `cmd_buscar`, `trechos`, `_mostrar_trechos` | `python3 -m unittest discover -s tools -p 'test_cerebro.py' -q` |
| Gravação de notas | `tools/cerebro.py`: `resolver`, `cmd_gravar`, `gravar` | Mesma suíte; casos de hash, trava, caminhos e segredos usam cofre sintético |
| Integridade e atualização dos mapas | `tools/cerebro.py`: `cmd_verificar`, `fontes_conferidas`, `hashes_externos` | Mesma suíte e `python3 tools/cerebro.py verificar` no exemplo |

O verificador já aceita `conferido_em`, `fontes_raiz` (caminho absoluto local) e `fontes_conferidas` (lista de caminhos relativos seguidos de `sha256:` e 64 caracteres hexadecimais). Registre apenas fontes pertinentes que você tenha conferido e mantenha esses caminhos no seu cofre privado. Uma mudança de hash pede nova conferência daquela fonte; não prova que o projeto esteja quebrado. A data do monitoramento não atualiza automaticamente a versão histórica do diagrama.

Hashes de referência podem ser obtidos com `python3 -c 'import hashlib,pathlib; print(hashlib.sha256(pathlib.Path("caminho/arquivo.py").read_bytes()).hexdigest())'`. Não use arquivos de dados, credenciais ou conteúdo somente na nuvem como fontes automáticas. A distribuição não inclui mapas ou caminhos do cofre pessoal.

## Skills e esforço por tarefa

Uma skill de mapas pode ter uma entrada curta que encaminha consultas ao grafo existente, atualizações incrementais e construções novas para referências diferentes. Carregue só o procedimento necessário. Uma edição pequena em arquivo conhecido pode usar busca normal; a presença de um grafo não exige reconstruí-lo nem carregar todo o manual.

`medium` é um ponto de partida para tarefas delimitadas. Use esforço menor em tarefas simples e revisadas, e maior quando diagnóstico, riscos ou verificações exigirem. Preserve o modelo escolhido pelo usuário e valide o resultado com os critérios da tarefa; não há seleção automática de esforço neste repositório.

No Codex, o padrão é configurado por `model_reasoning_effort` em `config.toml`. No Claude Code, `effortLevel` define o padrão onde aplicável; escolhas por modelo ou sessão podem prevalecer. Configurações locais e contas não são distribuídas. Confira o esforço ativo no cliente ao iniciar uma sessão e ajuste quando necessário. Fontes: [configuração do Codex](https://learn.chatgpt.com/docs/config-file/config-reference) e [esforço no Claude Code](https://code.claude.com/docs/en/model-config#effort-level).
