# Roteamento central e memória compartilhada

O usuário escolhe Claude Code ou Codex para conduzir o pedido. O principal consulta o Cérebro, envia uma tarefa delimitada ao roteador e revisa o resultado. As duas entradas são alternativas.

## Arquitetura de delegação

O roteador concentra três caminhos: Copilot, Ollama e OpenCode/Nemotron. A escolha considera tipo de tarefa, franquia incluída atual, adequação do modelo e memória disponível. A resposta volta pelo roteador ao principal. As condições de custo e segurança prevalecem sobre a preferência por um provedor.

## Três destinos implementados

`tools/auxiliares.py` concentra Ollama, Copilot e Nemotron via OpenCode. A linha do Copilot é contínua, como as demais saídas. A escolha muda conforme a tarefa e a elegibilidade; isso não muda a camada do auxiliar. Copilot requer franquia incluída verificada e overage desativado, usa Auto/Efficiency e executa uma resposta textual sem ferramentas. A integração foi validada em 14/10/2026. O principal decide quando delegar: não existe interceptação automática de toda mensagem do chat.

Nemotron respondeu em inferência real via OpenCode em 13/10/2026 (56 tokens de entrada e 2 de saída, aproximadamente 19 segundos). A configuração privada da máquina o habilita; o exemplo público permanece desativado até o usuário fornecer sua própria configuração elegível.

## Memória e monitoramento

Cérebro guarda regras e conhecimento em Markdown, com navegação pelo Obsidian e consulta e escrita controlada por `cerebro.py`. Graphify apoia a exploração das relações do código. Noah oferece voz e texto e segue em desenvolvimento.

Codenotch é uma camada separada de monitoramento, retirada do mapa de encaminhamento de mensagens. Não se presume cobertura universal de provedores. Os pontos animados são mensagens ilustrativas da arquitetura-alvo, não telemetria de tráfego.
