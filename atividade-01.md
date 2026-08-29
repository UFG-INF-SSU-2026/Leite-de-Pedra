# UNIVERSIDADE FEDERAL DE GOIÁS
## INSTITUTO DE INFORMÁTICA
### Software para Sistemas Ubíquos — Atividade em Grupo 01
**Prof. Dr. Otávio Calaça Xavier**

# Software para Sistemas Ubíquos — Atividade em Grupo 01
## Análise inicial de um sistema ubíquo (v2 — validação por câmera de celular)

**Integrantes:**
- Caio Castro Miranda
- Jaime da Cruz Silva Junior
- João Pedro de Brito Tomé
- João Victor Braga Queiroz

**Cenário escolhido:** Balanceamento de fluxo de fila em entrada única de eventos (shows, jogos, eventos geridos via uma plataforma de ticketeira genérica)

---

## Nota de revisão (v2)

Em relação à primeira versão, simplificamos a camada de sensoriamento: em vez de uma câmera dedicada em ângulo top-down associada a um dispositivo de borda (Raspberry Pi) por catraca, o sensor passa a ser a **câmera de um celular ou tablet já usado no ponto de validação de ingresso**, rodando um software de contagem configurável em dois modos:

- **Modo QR Code** — validação lendo o código do ingresso;
- **Modo Reconhecimento facial** — validação por comparação entre o rosto capturado e a foto associada a um ingresso nominal.

A lógica central (vazão móvel, histerese, recomendação de fila) não muda. O que muda é (a) o sensor+gateway, que passam a ser o mesmo dispositivo, e (b) o perfil de risco de privacidade, que agora depende do modo escolhido — detalhado na seção 5.

---

## Parte 1 — Compreensão do problema

### 1. Problema e usuários

Em eventos com portão/entrada única e múltiplos pontos de validação operando em paralelo, o fluxo de chegada do público não é constante ao longo do tempo — ele forma um pico de concentração próximo ao horário de início da atração principal (ex.: portões abrem às 17h, show às 19h, pico de chegada por volta das 18h). Dentro desse pico, as filas em cada ponto de validação crescem e diminuem de forma desigual, por motivos como diferença de vazão entre modos de validação (QR tende a ser mais rápido que reconhecimento facial) ou composição variável do público (ex.: grupos com idosos ou pessoas com mobilidade reduzida reduzem a vazão de uma fila específica, mesmo com menos pessoas nela).

**Usuários:**
- **Público do evento**, que recebe uma indicação de qual fila seguir para reduzir tempo de espera;
- **Equipe operacional do evento**, que se beneficia indiretamente de um fluxo mais distribuído e de um painel de acompanhamento em tempo real.

**Situação de uso:** período de maior concentração de chegada de público, no trecho físico entre a área externa do evento e o ponto de validação de ingresso.

### 2. Contexto

O sistema precisa perceber:
- **Ocupação instantânea** de cada fila (quantidade de pessoas aguardando em cada ponto de validação);
- **Vazão real recente** de cada ponto de validação (pessoas processadas por minuto, medida empiricamente — varia conforme o modo de validação ativo e a composição do público);
- **Tempo de deslocamento físico** entre os pontos de validação do mesmo portão (usado para calibrar a frequência de atualização da recomendação);
- **Fase temporal do evento** (chegada inicial, pico, estabilização), usada para ponderar o dado em tempo real com um padrão histórico esperado de chegada.

### 3. Dispositivos e comunicação

- Um **celular ou tablet com câmera** por catraca/ponto de validação, cumprindo simultaneamente o papel de sensor e de dispositivo de borda (gateway) — sem necessidade de um Raspberry Pi dedicado por fila, como na v1;
- Um **software de validação e contagem** rodando localmente no aparelho, configurável em dois modos:
  - **QR Code**: decodifica o código do ingresso apresentado pelo público;
  - **Reconhecimento facial**: compara o rosto capturado com a foto associada ao ingresso nominal;

  Em ambos os modos, o aparelho decide localmente "validado / não validado" e, em caso positivo, incrementa um contador. Nenhuma imagem, vetor facial ou dado do ingresso sai do aparelho — apenas o evento de contagem;
- Comunicação entre o aparelho e o serviço central via **protocolo MQTT** (mesma justificativa da v1: modelo publish/subscribe, adequado a mensagens curtas e frequentes), publicando apenas o incremento de contagem;
- Um **painel de LED ou display** por fila, também conectado via MQTT, recebendo o comando de recomendação (sem alteração em relação à v1).

### 4. Processamento e resposta

O processamento continua em duas camadas:

- **Borda (local, no celular):** captura de imagem, execução do modo ativo (leitura de QR ou comparação facial), decisão binária de validação, incremento do contador local. Nenhum dado bruto — imagem, vetor facial ou número do ingresso — é publicado na rede; apenas o evento de contagem.
- **Central (serviço agregador):** inalterado em relação à v1 — recebe as contagens de todas as filas, calcula a vazão móvel recente de cada uma, cruza com o padrão histórico esperado de chegada e aplica uma janela mínima de reavaliação com margem de histerese (para evitar alternância de recomendação por ruído estatístico ou pequenas variações momentâneas).

A resposta produzida continua sendo uma **recomendação de fila**, atualizada periodicamente, exibida de forma simples (ex.: luz verde para a fila recomendada) no ponto de decisão física do público.

### 5. Risco principal

**Privacidade** continua sendo o risco central do projeto, mas agora o perfil de risco **depende do modo de validação escolhido** — e essa é a principal diferença em relação à v1, onde a câmera top-down era escolhida justamente por ser incapaz de captar rosto por construção física, e não por promessa de software.

**Modo QR Code** mantém o perfil de risco baixo da v1: não há dado biométrico envolvido, o que trafega é a leitura de um identificador do ingresso, e o único dado enviado ao serviço central é um número agregado (contagem por fila), sem qualquer campo que associe o dado a uma pessoa específica.

**Modo Reconhecimento facial** introduz um risco de privacidade estruturalmente maior, pois passa a envolver **dado biométrico** — categoria que a LGPD trata como dado pessoal sensível (Art. 5º, II). Isso muda o que a arquitetura precisa garantir, não apenas o que ela promete:
- A imagem do rosto e a comparação facial devem ocorrer **inteiramente no aparelho**, com descarte imediato do frame e de qualquer vetor facial logo após a decisão de validação — nada disso pode ser transmitido ou persistido, nem localmente nem no serviço central;
- O consentimento para uso de reconhecimento facial deve ser **específico e explícito**, distinto da aceitação genérica dos termos de compra do ingresso (LGPD Art. 11);
- É preciso prever um **modo de validação alternativo** no mesmo ponto (ex.: validação manual por atendente) para os casos de falso negativo, evitando que uma falha de reconhecimento vire barreira de acesso para quem tem ingresso legítimo;
- O log de eventos deve registrar apenas "validado / não validado", nunca a imagem ou o dado biométrico em si.

Na prática, isso sugere adotar **QR Code como modo padrão** para eventos de ingresso geral (menor custo de conformidade e de risco), reservando o modo de reconhecimento facial para eventos com ingresso nominal, onde a verificação de identidade já é parte do processo de validação e a sobrecarga de governança adicional é parcialmente justificada por esse requisito.

Um risco secundário, inalterado em relação à v1, é o **efeito oscilatório de redirecionamento** (grupos de pessoas migrando repetidamente entre filas por recomendações que mudam rápido demais), mitigado pela mesma margem de histerese calibrada a partir do tempo real de deslocamento físico entre filas.

---

## Parte 2 — Modelagem do sistema

### 6. Sensores, atuadores e gateway

- **Sensor:** câmera do celular + software de validação (modo QR ou facial, conforme configuração), responsável por transformar o evento físico (pessoa validando entrada) em uma contagem numérica;
- **Atuador:** painel de LED/display por fila, responsável por transformar a decisão do sistema em um sinal visual compreensível pelo público, sem exigir interação ativa (inalterado);
- **Gateway:** o próprio celular acumula agora o papel de sensor e de gateway — uma simplificação em relação à v1, que separava câmera dedicada e Raspberry Pi. É também, como antes, o ponto onde a decisão de privacidade por design é aplicada: é ali que o frame de vídeo e, no modo facial, o dado biométrico, são processados e descartados antes de qualquer transmissão.

### 7. Fluxo do sistema

```
Pessoa no ponto de validação (fenômeno físico)
        │
        ▼
Câmera do celular (sensor)
        │
        ▼
Software local: modo QR Code           OU      Software local: modo Facial
  decodifica o ingresso                          compara rosto x foto do ingresso
        │                                                │
        └───────────────────┬────────────────────────────┘
                             ▼
              Validado? → incrementa contador local
                    (gateway + processamento local,
                     imagem/dado biométrico descartado aqui)
                             │  publica apenas o número via MQTT
                             ▼
        Serviço central: agrega contagens, calcula vazão móvel,
        aplica histerese e cruza com curva histórica de chegada
                             │
                             ▼
                Recomendação de fila calculada (decisão)
                             │
                             ▼
        Painel de LED indica a fila recomendada (resposta/atuador)
```

### 8. Classificação

O sistema pode ser caracterizado simultaneamente como:

- **Rede de sensores distribuída**, por envolver múltiplos dispositivos de sensoriamento (celulares nos pontos de validação) operando de forma coordenada — agora com arquitetura mais simples, já que sensor e gateway são o mesmo dispositivo;
- **Aplicação ubíqua**, porque a interação do usuário final (o público na fila) é passiva — ele apenas observa uma luz, sem operar nenhum dispositivo, enquanto o sistema sensoria o ambiente e toma decisões de forma autônoma, sem comando humano explícito a cada ciclo.

Não classificamos como **sistema ciber-físico completo**, pois o sistema apenas sinaliza uma recomendação — não atua diretamente sobre o mundo físico (não controla catracas, portas ou qualquer mecanismo automático).

### 9. Contexto e adaptação

Mudanças de contexto que alteram o comportamento do sistema:

- **Variação na taxa de chegada de público ao longo do tempo** (ex.: aproximação do horário do evento principal): o sistema pondera o dado sensoriado em tempo real com uma curva histórica esperada, antecipando o crescimento do fluxo em vez de reagir apenas quando a fila já está grande;
- **Queda de vazão em uma fila específica** (ex.: composição do público com mais pessoas de mobilidade reduzida, ou modo de validação mais lento naquele ponto): como a vazão é medida empiricamente e não assumida como constante, o sistema se adapta automaticamente, mesmo sem saber a causa da lentidão;
- **Tipo de evento e política de ingresso**: determina qual modo de validação está ativo em cada ponto — eventos de ingresso geral tendem a usar QR Code (mais rápido, menor risco), enquanto eventos com ingresso nominal podem usar reconhecimento facial, já que a verificação de identidade já faz parte do processo;
- **Perda de conectividade** entre os celulares e o serviço central: cada aparelho mantém uma lógica mínima de decisão local, garantindo que o painel continue funcionando de forma degradada em vez de parar de responder.

---

*Documento produzido para a Atividade em Grupo 01 — Software para Sistemas Ubíquos (UFG/INF), com base na análise crítica do domínio de operação de eventos com plataforma de ticketeira. Versão 2: sensor simplificado para câmera de celular com validação configurável (QR Code / reconhecimento facial).*
