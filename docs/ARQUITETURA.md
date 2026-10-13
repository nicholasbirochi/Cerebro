# Roteamento central e memória compartilhada

O usuário escolhe Claude Code ou Codex para conduzir o pedido. O principal consulta o Cérebro, envia uma tarefa delimitada ao roteador e revisa o resultado. As duas entradas são alternativas.

## Arquitetura-alvo

O roteador concentra três caminhos: Copilot, Ollama e OpenCode/Nemotron. A escolha considera tipo de tarefa, franquia incluída atual, adequação do modelo e memória disponível. A resposta volta pelo roteador ao principal. As condições de custo e segurança prevalecem sobre a preferência por um provedor.

## Implementado e pendente

`tools/auxiliares.py` trata Ollama e Nemotron via OpenCode. Integrar Copilot nesse ponto único ainda é uma tarefa de implementação. O vídeo e o diagrama sinalizam essa ligação como pendente, sem afirmar automação que ainda não existe. Enquanto isso, a chamada direta existente ao Copilot não é o fluxo-alvo desenhado.

Nemotron respondeu em inferência real via OpenCode em 13/10/2026 (56 tokens de entrada e 2 de saída, aproximadamente 19 segundos). A configuração privada da máquina o habilita; o exemplo público permanece desativado até o usuário fornecer sua própria configuração elegível.

## Memória e monitoramento

Cérebro guarda regras e conhecimento em Markdown, com navegação pelo Obsidian e consulta e escrita controlada por `cerebro.py`. Graphify apoia a exploração das relações do código. Noah oferece voz e texto e segue em desenvolvimento.

Codenotch é uma camada separada de monitoramento, retirada do mapa de encaminhamento de mensagens. Não se presume cobertura universal de provedores. Os pontos animados são mensagens ilustrativas da arquitetura-alvo, não telemetria de tráfego.
