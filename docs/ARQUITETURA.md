# Papéis e fluxo

O usuário define o objetivo. Claude Code ou Codex permanece como agente principal, reúne contexto, escolhe ferramentas, revisa e entrega. Copilot é um auxiliar para trabalho delimitado e só deve ser acionado após conferir a franquia incluída; não é uma entrada equivalente nem substitui automaticamente o principal.

O Cérebro guarda conhecimento em Markdown. Obsidian é uma interface de navegação; `cerebro.py` oferece consulta por trechos, validação e escrita controlada. Graphify ajuda a explorar relações do código. Noah fornece voz e texto e segue em desenvolvimento.

Ollama executa modelos locais. O roteador seleciona uma alternativa conforme o tipo de tarefa e os recursos disponíveis. OpenCode fornece a ponte opcional para Nemotron; Codenotch acompanha o uso registrado. A disponibilidade gratuita precisa ser confirmada e não implica quota ilimitada.

A resposta retorna ao principal para validação. Somente conhecimento novo, útil e verificável deve ser registrado. Os pontos do vídeo representam mensagens ilustrativas, não medições de tráfego.

## Entradas alternativas e escopo do roteador

Claude Code e Codex podem conduzir o mesmo tipo de tarefa; cada pedido escolhe um principal. Ambos consultam o Cérebro, delegam e revisam. Os caminhos desenhados representam alternativas, não uma exigência de passar por dois principais.

O principal decide se usa Copilot, auxiliares nativos ou o script `auxiliares.py`. O Copilot é chamado diretamente após verificar a franquia. O script trata apenas Ollama e Nemotron. Integrar Copilot ao script seria uma mudança de implementação que este vídeo não afirma existir.

Nemotron respondeu em inferência real via OpenCode em 13/10/2026 (56 tokens de entrada e 2 de saída, aproximadamente 19 segundos). A configuração privada da máquina o habilita; o exemplo público permanece desativado até o usuário fornecer sua própria configuração elegível.
