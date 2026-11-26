# Contribuições individuais

As contribuições dos demais integrantes ainda não estão neste arquivo.

## Caio Castro Miranda — 202302600

Parte 3 — Gerenciamento inteligente das filas.

Cálculo da ocupação e do tempo de espera, classificação do estado das filas e recomendação automática de direcionamento.

O que mudou no Marco 4:

- Criação do endpoint `GET /filas` no backend.
- Nova lógica para escolher a melhor fila entre aquelas com enlace ativo, priorizando o melhor semáforo e, em caso de empate, o menor tempo de espera.
- Integração com o aplicativo: a tela do ingresso atualiza a recomendação a cada 3 segundos.
- Exibição da ocupação, do semáforo e do tempo estimado de espera de cada fila.
- Criação do teste `demo_lotacao.py` para demonstrar a mudança de recomendação em tempo real.

Principal contribuição: levar o gerenciamento das filas para o usuário, permitindo que ele saiba diretamente pelo celular qual fila deve escolher.

## João Pedro de Brito Tomé — 202302612

Arquitetura do Marco 4 de ponta a ponta: contrato das mensagens, banco, processador, backend, observabilidade, dashboard de administração, aplicativo móvel, firmware, Docker, testes e documentação.

Os commits são de 06/11 a 13/11/2026; o hash de cada item está entre parênteses. Dois deles (`21124c4` e `662f6cd`) entraram pelo PR #3.

### Contrato das mensagens e broker

- Contrato comum de toda mensagem MQTT: `event_id`, `correlation_id`, `event_type`, `source`, `timestamp` e `payload`. `ler_evento` valida o envelope contra o tópico e descarta o que não casa (`b16f12a`).
- Presença de cada componente por Last Will: online e offline, retidos, em `sistema/{usuario}/status` (`b16f12a`).
- ACL separando por papel leitura, resultado, reação e rejeitadas (`b16f12a`).
- Usuário `monitor`, só de leitura, para o MQTTX. É um usuário à parte porque o broker usa o usuário como client id: entrar como `observador` derrubaria a observabilidade. Inclui a opção `--adicionar-monitor` em `broker/configurar-seguranca.sh` (`3a827c3`).

### Banco de dados (TimescaleDB)

- Tabelas de usuários, ingressos e auditoria (`336d16c`).
- Tabela `saida` como caixa de saída transacional (transactional outbox) (`336d16c`).
- Correlação e origem em `movimentos` (`336d16c`).
- Papéis por componente: `processador`, `backend`, `painel` e `observador` (só leitura), com permissões por coluna e scripts para atualizar um banco existente (`336d16c`).
- `SELECT` e `INSERT` em `movimentos` para o papel `backend`, necessários no tratamento do 504 (`cf99f81`).

### Processador

- Decisão da leitura na catraca só pelas regras do ingresso: quem leu é validador; o ingresso é do dono do rosto e não foi usado nem cancelado. O rosto chega já reconhecido pelo backend, e o processador não usa AWS (`bd58f7a`).
- Resultado publicado pela tabela `saida` até o broker confirmar (PUBACK). Numa queda, o pendente sai de novo com o mesmo `event_id` (`bd58f7a`).
- Mensagens descartadas publicadas em `sistema/processador/rejeitado`, com o motivo (`bd58f7a`).

### Backend (API do app e do dashboard)

- API do aplicativo (`2caaa65`):
  - cadastro com o rosto (Rekognition), com um rosto por conta;
  - login com JWT;
  - compra e listagem de ingressos;
  - leitura na catraca: o backend reconhece o rosto, guarda a foto no S3, publica a leitura e espera o resultado pelo `correlation_id`.
- Rotas `/admin`, que conferem no banco, a cada pedido, se a conta é de admin, e fazem a gestão de usuários, ingressos, auditoria e fotos (`2caaa65`).
- Foto da leitura aceita apagada do S3 assim que o resultado chega. Recusadas e indeterminadas ficam até a regra do bucket (1 dia), para o admin revisar (`eecdd5e`).
- Modo `BACKEND_SEM_TLS=1`, só para desenvolvimento, com aviso ao iniciar. O padrão continua HTTPS (`e1927f5`).
- Leitura aceita devolve o nome e o login do dono do ingresso para a catraca (`2b42a6e`).
- Aba Leituras completada com o dono do ingresso e o login do validador, lidos pelo papel `painel`. A observabilidade continua sem ler dados pessoais (`5baf61b`).
- Correção (`cf99f81`): com o processador fora do ar, o 504 gastava o ingresso quando o processador voltava, e a nova tentativa dava `ingresso-ja-usado`. A correção:
  - no 504, o backend grava a leitura como `indeterminado` (`sem-resposta-processador`);
  - se o processador decidiu nesse meio-tempo, o backend devolve a decisão dele;
  - backend e processador decidem sob a mesma trava do banco por `evento_id` (`pg_advisory_xact_lock`), e vale quem gravar primeiro;
  - a leitura leva `validoAte`: vencida, o processador a rejeita como `leitura-expirada` sem tocar no ingresso.

### Observabilidade

- Processo próprio que assina tudo no broker e lê o banco como `observador`, sem gravar nada (`49092dc`).
- API interna que o backend repassa ao dashboard. Substituiu o painel antigo do observador (`49092dc`).

### Dashboard de administração (React)

- Visão geral ao vivo: componentes, filas, tentativas, reações e rejeitadas (`83f34a4`).
- Histórico, usuários, ingressos, leituras com foto, movimentos por correlação, estados e auditoria (`83f34a4`).
- Gráficos de espera média e entradas por minuto, uma linha por fila. São SVG desenhado pelo React, sem biblioteca nova e respeitando a CSP do painel (`099a038`).
- Catraca no computador para contas de validador: a webcam lê o QR do ingresso (BarcodeDetector, ou o código digitado) e depois o rosto. Mostra a foto capturada e os dados de quem foi liberado (`2b42a6e`).
- Correção: o enlace do ESP32 aparecia como "Aceito" e passou a aparecer como "no ar" (`a291ae7`).

### Aplicativo móvel (Expo)

- App de clientes e validadores (`04f2d19`):
  - cadastro com a foto do rosto;
  - login;
  - compra de ingressos e QR do ingresso;
  - para validadores, a catraca, com leitura do QR e captura do rosto.

  O app fala só com o backend.
- Endereço padrão `http://<máquina do Expo>:8444`, para o celular na rede funcionar sem instalar a CA. `EXPO_PUBLIC_API_URL` troca o endereço (`d002c88`).

### Firmware (Wokwi / ESP32)

- Produtor publica os movimentos no contrato comum (`2e7d564`).
- Consumidor executa a reação ao resultado da leitura (LED piscando e LCD) e a confirma em `fila/{id}/reacao`, sem decidir nada (`2e7d564`).
- Sensores aceitam `chegada fila-a` e `saida fila-b` pela serial, passando pelo mesmo caminho dos sensores (buffer, TLS e QoS 1). Isso permite automatizar o teste de ponta a ponta (`1bd0a6f`).
- Correção: consumidor com keepalive de 60 s e sessão persistente. O Wokwi lento fazia o broker derrubar a conexão a cada 15 a 40 s e perder a reação da catraca (`4be30c6`).

### Infraestrutura

- `docker-compose.yml` com banco, broker, processador, backend e observabilidade (`c7b0d9c`).
- Modelo do `.env` (`f0e0709`).
- Remoção do console de demonstração `validador/`: a catraca é o app e o dashboard (`a1cdcbd` atualizou o console para o contrato novo; `97b2301` o removeu).

### Testes

- `tests/e2e_completo.py`, teste de ponta a ponta (`1bd0a6f`):
  - cria contas com rostos gerados por IA e compra ingressos;
  - lota a fila-a até fechar e desviar para a fila-b;
  - passa os clientes na catraca das duas filas (Rekognition, processador e reação do consumidor);
  - repete o 504 com o processador parado e esvazia as filas.
- Testes do 504 sem gastar o ingresso no backend e da leitura expirada no processador (`cf99f81`, em `test_backend.py` e `test_heartbeat.py`).

### Documentação

- README e `docs/ARQUITETURA.md` com o contrato, a outbox, a observabilidade e os papéis (`1a1baef`).
- Situação atual da implementação, regras de segurança por componente e o motivo do banco compartilhado (`21124c4`).
- Passo a passo para rodar localmente, com uma tabela de problemas comuns (`662f6cd`):
  - requisitos e configuração da AWS (bucket, regra de 1 dia, coleção e perfil);
  - segredos, Docker e contas de teste;
  - painel e catraca no computador;
  - app no celular, ESP32 e testes.
- `mobile/README.md` com o modo HTTP e como voltar ao HTTPS (`d002c88`).

## João Victor Braga Queiroz — 201810114

Concepção do problema e da solução, requisitos, regras de contexto e tempo,
sensoriamento e qualidade dos dados, e redação do artigo.

### Concepção

- Identificação do problema a partir da operação real de eventos com ingresso: o
  gargalo da entrada é a distribuição do público no pico, não a capacidade
  instalada.
- Proposta da troca de tema do grupo, que abandonou a biblioteca inteligente com
  RFID e passou a tratar balanceamento de fluxo de fila.
- Desenho da solução: contagem de chegada e saída por fila, tempo de espera
  estimado como grandeza apresentada, decisão por janela deslizante com histerese
  e semáforo como linguagem para o público.
- Definição da restrição que atravessa o projeto: o sistema recomenda(induz), nunca
  trava nem aciona a catraca.

### Requisitos

- Levantamento das restrições de operação real usadas como critério de escopo:
  capacidade por segmento de corredor, variação de iluminação ao longo do evento
  e comportamento do público em pico.
- Descarte de sensores e arquiteturas que não se sustentariam em campo.
- Separação entre fidelidade de documentação e de protótipo, com os substitutos
  declarados.

### Sensoriamento e regras de tempo

- Perfil de sensoriamento e qualidade nas atividades individuais.
- Protótipo ESP32/Wokwi usado como demonstração do Marco 1.
- Papel de produtor no Marco 2 e roteiros das demonstrações.
- Definição do que conta como dado válido, de como a vazão é apurada, do ritmo de
  reavaliação do estado e das condições em que a recomendação muda.

### Artigo do Marco 4

- Redação e fechamento do artigo em formato ABNT/UFG, junto à Caio Miranda.

### Atuação no repositório

- Commits de regra de contexto e tempo no Marco 2 (18/09), organização das
  entregas por marco e README inicial do projeto (19 a 21/09).
- Correção da vazão no processador no Marco 4 (`d0d3525`), que fazia as filas
  aparecerem travadas durante a demonstração.

Principal contribuição: a concepção do sistema e as regras que o sustentam — o
problema, a solução, o que conta como dado válido, como a espera é estimada e
quando a recomendação muda — além do artigo que descreve tudo isso.

- Testes unitários sem banco e sem broker, 75 casos, cobrindo as funções de `senhas`, `mqtt_config`, `modelos`, `estado_filas`, backend, observabilidade e processador: `tests/test_unidades.py` e `tests/test_unidades_processador.py`.

### Ainda não commitado
