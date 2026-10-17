# Arquitetura — balanceamento de filas com reconhecimento facial

Este documento descreve o fluxo completo do sistema: quem publica o quê, quem
decide, como a espera é estimada e como a pessoa é liberada na catraca. Os
detalhes de execução ficam no [README](../README.md).

## Visão geral

O evento tem várias filas de entrada. Em cada fila, **sensores** contam quem
entra e quem sai, e uma **câmera** na catraca identifica a pessoa pelo rosto.
Um **processador** central junta esses dados para:

1. estimar o tempo de espera de cada fila e indicar ao público a fila com
   menor espera;
2. decidir, via AWS Rekognition, se a pessoa diante da câmera pode passar.

Toda a comunicação passa por um broker MQTT (Mosquitto) com TLS, autenticação
por senha e ACL por componente.

> **Todo componente, atual ou futuro, segue as mesmas regras de segurança.**
> Isso inclui o app mobile, o painel web, o banco TimescaleDB e a integração com
> AWS Rekognition e S3. Nenhum componente entra no sistema sem cumprir as
> [regras obrigatórias](#regras-obrigatórias-de-segurança) descritas abaixo.

## Componentes

| Componente | Onde está | Papel |
|---|---|---|
| **Produtor** | `produtor/src/main.cpp` (ESP32 no Wokwi) | Sensores HC-SR04 na entrada e na saída de cada fila. Publica cada movimento e um heartbeat. |
| **Validador** | `validador/` (hoje página local; futuro app mobile) | Lê o rosto na catraca, envia a leitura e mostra se a pessoa foi aceita. |
| **Broker** | `broker/` (Mosquitto) | Entrega as mensagens entre os componentes, com TLS e ACL. |
| **Processador** | `processador/processador.py` | Único que decide: calcula ocupação, vazão e espera e avalia cada leitura facial. |
| **Consumidor** | `produtor/src/consumidor.cpp` (ESP32 no Wokwi) | LCD e LEDs que indicam ao público qual fila procurar. |
| **Observador** | `observador/painel/` (painel web) | Visualiza movimentos, resultados e estados. Nunca recebe biometria. |
| **AWS Rekognition** | serviço externo | Compara o rosto lido com a coleção de rostos cadastrados. |

```mermaid
flowchart LR
    subgraph Fila["Em cada fila"]
        P["<b>Produtor</b><br/>ESP32 + HC-SR04<br/>entrada e saída"]
        V["<b>Validador</b><br/>app mobile<br/>câmera na catraca"]
        S["<b>Consumidor</b><br/>ESP32 + LCD e LEDs"]
    end

    B(("<b>Broker</b><br/>Mosquitto<br/>MQTT/TLS :8883"))

    subgraph Servidor["Lado servidor"]
        C["<b>Processador</b><br/>ocupação, vazão, espera<br/>decisão facial"]
        DB[("TimescaleDB")]
        R[["AWS Rekognition"]]
    end

    O["<b>Observador</b><br/>painel web"]

    P -- "contagem · saida · heartbeat" --> B
    V -- "leitura" --> B
    B -- "contagem · saida · heartbeat · leitura" --> C
    C --- DB
    C <-. "SearchFacesByImage" .-> R
    C -- "resultado · estado · recomendacao" --> B
    B -- "estado" --> S
    B -- "resultado · estado" --> V
    B -. "tudo, menos leitura" .-> O
```

## Tópicos MQTT

O MQTT não tem filas, tem **tópicos**: o broker entrega cada mensagem a quem
assina o tópico, sem guardá-la em fila. Todos os tópicos seguem
`fila/{id}/{tipo}`, com `{id}` igual a `fila-a`, `fila-b` etc.

| Tópico | Publica | Assina | Conteúdo |
|---|---|---|---|
| `fila/{id}/contagem` | produtor | processador, observador | uma pessoa entrou na fila |
| `fila/{id}/saida` | produtor | processador, observador | uma pessoa saiu da fila |
| `fila/{id}/heartbeat` | produtor | processador, observador | o enlace do ESP32 está vivo (a cada 2 s) |
| `fila/{id}/leitura` | validador | **só** processador | referência da foto capturada na catraca |
| `fila/{id}/resultado` | processador | validador, observador | `aceito`, `recusado` ou `indeterminado` |
| `fila/{id}/estado` | processador | consumidor, validador, observador | semáforo, ocupação, espera e fila recomendada (retido) |
| `fila/{id}/recomendacao` | processador | observador | mudança de recomendação, com o motivo |

## Fluxo 1 — contagem de pessoas e estimativa de espera

A ocupação vem **só dos sensores**: entradas − saídas. O reconhecimento
facial não altera a contagem. Assim, quem é recusado ou desiste continua
contado até passar pelo sensor de saída, e a espera reflete o movimento real.

```mermaid
sequenceDiagram
    autonumber
    participant P as Produtor (ESP32)
    participant B as Broker
    participant C as Processador
    participant DB as TimescaleDB
    participant S as Consumidor (LEDs)
    participant O as Observador

    Note over P: pessoa passa pelo sensor de entrada
    P->>B: fila/fila-a/contagem {eventId}
    B->>C: contagem
    B->>O: contagem
    C->>DB: grava movimento (ON CONFLICT DO NOTHING)<br/>entradas + 1
    C->>C: recalcula espera e semáforo
    C->>B: fila/fila-a/estado (retain)
    B->>S: estado
    S->>S: acende LED e mostra fila recomendada

    Note over P: pessoa passa pelo sensor de saída
    P->>B: fila/fila-a/saida {eventId}
    B->>C: saida
    B->>O: saida
    C->>DB: grava movimento (ON CONFLICT DO NOTHING)<br/>saídas + 1
    C->>C: registra a passagem para medir a vazão
    C->>B: fila/fila-a/estado (retain)
    B->>S: estado
```

### Como a espera é calculada

```mermaid
flowchart TD
    E["entradas<br/>(sensor de entrada)"] --> OC["ocupação = entradas − saídas"]
    SA["saídas<br/>(sensor de saída)"] --> OC
    SA --> VZ["vazão = 1 ÷ intervalo médio entre saídas<br/>(últimos 90 s, só enquanto havia fila)"]
    OC --> ES{"já há duas saídas<br/>na janela?"}
    VZ --> ES
    ES -- "sim" --> EV["espera = ocupação ÷ vazão"]
    ES -- "não" --> EI["espera = ocupação × 7 s<br/>(estimativa inicial)"]
    EV --> SEM["semáforo"]
    EI --> SEM
    SEM --> L["🟢 livre: ≤ 15 s"]
    SEM --> A["🟡 atenção: 15–30 s"]
    SEM --> X["🔴 bloqueada: > 30 s"]
```

- **Histerese:** para voltar a um nível melhor, a espera precisa cair 7 s
  abaixo do limite. Isso evita que o semáforo fique piscando entre duas cores.
- **Recomendação:** uma fila amarela ou vermelha indica a fila em estado
  melhor e com menor espera. É o que o consumidor mostra ao público.
- **Heartbeat:** se o processador fica 15 s sem receber heartbeat de uma fila,
  ele para de recomendá-la, porque não tem dados confiáveis.

## Fluxo 2 — reconhecimento facial na catraca

```mermaid
sequenceDiagram
    autonumber
    actor Pessoa
    participant V as Validador (app)
    participant S3 as Bucket (S3)
    participant B as Broker
    participant C as Processador
    participant R as AWS Rekognition
    participant O as Observador

    Pessoa->>V: olha para a câmera
    V->>S3: envia a foto (URL pré-assinada)
    V->>B: fila/fila-a/leitura {eventId, fotoRef}
    B->>C: leitura (só o processador pode ler)
    C->>C: descarta se o eventId já foi visto
    C->>C: coloca na fila de trabalho
    C->>R: SearchFacesByImage(coleção, fotoRef)
    R-->>C: rosto correspondente e similaridade
    C->>B: fila/fila-a/resultado {eventId, resultado}
    B->>V: resultado
    B->>O: resultado
    alt aceito
        V->>Pessoa: libera a catraca
    else recusado
        V->>Pessoa: barra e encaminha ao atendimento
    else indeterminado
        V->>Pessoa: operador decide manualmente
    end
```

Decisões deste fluxo:

- **A foto não passa pelo broker.** Biometria é dado pessoal sensível (LGPD).
  A leitura leva só a referência (`fotoRef`) da imagem no bucket, e a ACL
  impede que qualquer outro componente leia `fila/+/leitura`.
- **Quem decide é o processador.** As credenciais da AWS ficam só no servidor,
  nunca no celular, e o validador não consegue publicar um `resultado`.
- **O `eventId` liga a resposta à pergunta.** O `resultado` repete o
  `eventId` da `leitura`, então cada aparelho reconhece a resposta à sua
  leitura mesmo com vários validadores na mesma fila.
- **O reconhecimento roda fora da thread do MQTT.** O Rekognition leva perto
  de 1 s; uma thread de trabalho evita que contagens e saídas fiquem paradas
  esperando.
- **Falha não trava a fila.** Se o Rekognition não responder, o resultado é
  `indeterminado` e o operador decide.

### Situação atual da implementação

Cada próximo passo da tabela abaixo só é concluído quando cumpre as
[regras obrigatórias de segurança](#regras-obrigatórias-de-segurança).

| Parte | Hoje | Próximo passo |
|---|---|---|
| Reconhecimento | `avaliar_rosto` no processador simula o Rekognition: aceita só `demo/rosto-cadastrado.jpg` | trocar pela chamada `SearchFacesByImage` com a coleção real |
| Foto | o validador envia uma referência fixa de demonstração | o app envia a foto ao S3 e publica a chave |
| Cadastro de rostos | não existe | `IndexFaces` de cada portador de ingresso (por exemplo, na compra) |
| Validador | página local `validador/index.html` | app mobile com credencial MQTT própria (MQTT sobre WebSockets, se for híbrido) |
| Observador | painel web (`observador/painel/`) com login: ao vivo pelo broker com atualização contínua (SSE), histórico por minuto do banco | — |

## Segurança e permissões

### Regras obrigatórias de segurança

Estas regras já valem para o produtor, o consumidor, o validador, o
processador e o observador. **Todo componente novo, e toda nova versão dos
atuais, precisa cumpri-las antes de entrar no sistema.** Nenhuma delas pode ser
desligada para facilitar um teste ou uma demonstração.

| # | Regra | Como já é aplicada hoje |
|---|---|---|
| 1 | **Só TLS.** Toda conexão é cifrada e valida o certificado do servidor pela CA do projeto. Nada de conexão sem criptografia nem de validação de certificado desligada. | O broker só escuta MQTT/TLS na porta 8883; `mqtt_config.py` exige a CA e TLS 1.2 ou superior; os ESP32 usam `WiFiClientSecure` com a CA. |
| 2 | **Uma identidade por componente.** Cada componente tem usuário e senha próprios; acesso anônimo é proibido. | `allow_anonymous false`; senhas geradas por `broker/configurar-seguranca.sh` e guardadas com hash no `mosquitto.passwd`. |
| 3 | **Menor privilégio.** Cada identidade só publica e só lê os tópicos de que precisa. Um papel novo começa sem permissão e ganha só o necessário. | `broker/mosquitto.acl`, testado por `broker/testar-acl.py`. |
| 4 | **Segredo fora do Git.** Senhas, chaves, certificados e credenciais de nuvem nunca são versionados. | `.local/` e `produtor/include/segredos*.h` estão no `.gitignore`; cada firmware recebe só a senha do seu papel. |
| 5 | **Desconfiar do que chega.** Todo dado recebido é validado: tópico e `filaId` coincidem, o tipo é conhecido, o tamanho é limitado e payload malformado é descartado sem derrubar o serviço. | Validações no processador, no observador e no servidor do validador (POST limitado a 1 KB). |
| 6 | **Idempotência.** Todo evento tem `eventId`, e repetições são ignoradas. | `ON CONFLICT DO NOTHING` em `estado_filas.py`. |
| 7 | **Uma única autoridade.** Só o processador publica estado, recomendação e resultado; quem envia dados não decide sobre eles. | ACL: só o `processador` escreve em `estado`, `recomendacao` e `resultado`. |
| 8 | **Biometria mínima.** A foto nunca passa pelo broker nem é gravada fora do bucket; só a referência circula, e só o processador a lê. | ACL: só o `processador` lê `fila/+/leitura`; o observador não recebe leituras. |

### Como as regras se aplicam aos próximos componentes

| Componente | O que ele precisa ter |
|---|---|
| **App mobile (validador)** | Usuário MQTT `validador` com senha própria por aparelho ou por operador; TLS validando a CA (inclusive em MQTT sobre WebSockets, que precisa de `listener` com TLS no Mosquitto); nenhuma credencial AWS no aparelho, só URLs pré-assinadas de upload e de curta duração; nenhuma foto guardada no celular depois do envio. |
| **Painel web (observador)** (implementado) | Usuário MQTT `observador` e papel `observador` do banco, ambos somente leitura e sem acesso a `fila/+/leitura`; recebe os dados ao vivo pelo broker e só o histórico do banco; descarta mensagem malformada ou com `filaId` diferente do tópico; login com senha em hash scrypt e sessão JWT HS256 de 1 h em cookie `HttpOnly`, `Secure` e `SameSite=Strict` (algoritmo fixo, `none` recusado); HTTPS com TLS 1.2 ou superior e certificado da CA do projeto, só em `127.0.0.1:8443`; CSP que só aceita o próprio script e a própria origem e templates Jinja2 com escape automático; credenciais do broker e do banco só no servidor, nunca no navegador. |
| **TimescaleDB** (implementado) | Conexão com TLS obrigatório (`sslmode=verify-full`); um usuário de escrita só para o processador e um usuário somente leitura para o painel; senha fora do Git; banco sem porta exposta à internet. Detalhes em [Persistência com TimescaleDB](#persistência-com-timescaledb). |
| **AWS Rekognition e S3** | Credenciais só no processador, com uma política IAM que permita apenas `SearchFacesByImage` na coleção do evento e leitura e exclusão no bucket das fotos; bucket privado e cifrado; fotos apagadas logo após a avaliação; nenhuma chave da AWS no Git nem no app. |

### Permissões no broker

Cada componente tem usuário e senha próprios, e a ACL do broker
(`broker/mosquitto.acl`) aplica o menor privilégio:

```mermaid
flowchart LR
    subgraph Publicam
        P[produtor]
        V[validador]
        C1[processador]
    end
    subgraph Tópicos
        T1[contagem · saida · heartbeat]
        T2[leitura]
        T3[resultado]
        T4[estado · recomendacao]
    end
    subgraph Leem
        C2[processador]
        V2[validador]
        S[consumidor]
        O[observador]
    end

    P --> T1
    V --> T2
    C1 --> T3
    C1 --> T4

    T1 --> C2
    T1 --> O
    T2 --> C2
    T3 --> V2
    T3 --> O
    T4 --> S
    T4 --> V2
    T4 --> O
```

| Identidade | Pode publicar | Pode ler | Não pode |
|---|---|---|---|
| `produtor` | contagem, saída, heartbeat | nada | ler dados, emitir estado |
| `validador` | leitura | resultado, estado | criar entradas ou saídas, decidir o próprio resultado |
| `processador` | resultado, estado, recomendação | contagem, saída, heartbeat, leitura | — |
| `consumidor` | nada | estado | criar movimentos |
| `observador` | nada | tudo, menos leitura | escrever, ver biometria |

## Persistência com TimescaleDB

O TimescaleDB fica **no processador**: só ele grava. Ele é o único componente
que valida e deduplica os eventos; um serviço separado que assinasse os
tópicos gravaria mensagens repetidas ou forjadas. A configuração está em
`banco/` e o acesso em `estado_filas.py`.

```mermaid
flowchart LR
    B(("Broker")) --> C["Processador<br/>valida e deduplica"]
    C -- "TLS verify-full<br/>papel processador" --> T[("TimescaleDB<br/>127.0.0.1:5433")]
    T --> AG["continuous aggregates<br/>por minuto"]
    AG -- "histórico por minuto<br/>TLS verify-full, papel observador" --> O["Observador<br/>painel web"]
    B -- "ao vivo<br/>MQTT/TLS, usuário observador" --> O
    V["Validador"] -. "sem acesso ao banco<br/>(usa o estado do MQTT)" .-x T
```

### Esquema

```mermaid
erDiagram
    filas {
        TEXT fila_id PK
        INTEGER entradas
        INTEGER saidas
    }
    movimentos {
        TEXT evento_id PK
        TEXT tipo PK "contagem, saida, leitura, resultado"
        TIMESTAMPTZ momento PK "hypertable"
        TEXT fila_id
        TIMESTAMPTZ recebido_em
        TEXT resultado "aceito, recusado, indeterminado"
    }
    estados {
        TIMESTAMPTZ momento "hypertable"
        TEXT fila_id
        TEXT semaforo
        INTEGER ocupacao
        INTEGER espera_segundos
    }
    filas ||--o{ movimentos : "fila_id"
    filas ||--o{ estados : "fila_id"
```

| Objeto | Tipo | Conteúdo |
|---|---|---|
| `filas` | tabela | saldo de entradas e saídas por fila. Fica separado para que uma saída a mais com a fila vazia não deixe a ocupação negativa. |
| `movimentos` | hypertable por `momento` | todo evento aceito. A chave `(evento_id, tipo, momento)` descarta as reentregas do QoS 1. A leitura guarda só o `eventId`, **nunca a referência da foto**. |
| `estados` | hypertable por `momento` | cada estado publicado: semáforo, ocupação e espera estimada. |
| `movimentos_por_minuto` | continuous aggregate | entradas, saídas, aceitos, recusados e indeterminados por fila e minuto (vazão). |
| `espera_por_minuto` | continuous aggregate | espera média e máxima e ocupação máxima por fila e minuto. |

Os agregados são atualizados a cada minuto e incluem os dados ainda não
materializados, então o painel vê também o minuto corrente.

### Entrega garantida até o banco

Todo dado chega ao processador pelos tópicos do broker. Nenhuma mensagem se
perde se o processador ou o banco caírem:

- O processador assina `contagem`, `saida`, `heartbeat` e `leitura` com QoS 1,
  numa sessão persistente (`clean_session=False`). O broker guarda em disco
  (`.local/mosquitto/`) o que chega enquanto o processador está fora do ar.
- A confirmação ao broker (PUBACK) é manual. Ela só é enviada depois que o
  evento foi gravado no banco. Para a leitura facial, só depois que o
  resultado foi gravado e publicado.
- Se o banco falhar, o processador se desconecta sem confirmar e encerra.
  Quando ele é iniciado de novo, o broker reentrega as mensagens pendentes, e
  a chave de `movimentos` descarta as que já tinham sido gravadas.
- O broker usa o usuário como client id (`use_username_as_clientid`). Assim,
  outro papel não consegue assumir a sessão do processador nem ler as leituras
  guardadas para ele.

```mermaid
sequenceDiagram
    participant P as Produtor
    participant B as Broker
    participant C as Processador
    participant T as TimescaleDB
    P->>B: contagem (QoS 1)
    B->>C: contagem
    C->>T: INSERT ... ON CONFLICT DO NOTHING
    T-->>C: ok
    C->>B: PUBACK
    Note over C,T: banco fora do ar
    B->>C: contagem
    C-xT: falha
    C->>B: desconecta sem PUBACK
    Note over B: guarda a mensagem
    C->>B: reconecta (mesma sessão)
    B->>C: reentrega a contagem
```

### Segurança do banco

O banco cumpre as [regras obrigatórias](#regras-obrigatórias-de-segurança):

| Regra | Como o banco cumpre |
|---|---|
| Só TLS | `pg_hba.conf` só tem linhas `hostssl`; TLS 1.2 ou superior; os clientes usam `sslmode=verify-full` com a CA do projeto. |
| Uma identidade por componente | papéis `processador` e `observador`, com senha SCRAM própria; o superusuário `postgres` só entra pelo socket local do contêiner. |
| Menor privilégio | `processador` lê, insere e atualiza, mas não apaga, não faz `TRUNCATE` e não cria tabelas; `observador` só lê. |
| Segredo fora do Git | senhas, certificado e chave em `.local/banco`, gerados por `banco/configurar-banco.sh`. |
| Desconfiar do que chega | o processador valida tópico, tipo e `eventTimeMs` antes de gravar; o esquema tem `CHECK` em `tipo`, `resultado` e `semaforo`. |
| Idempotência | `ON CONFLICT DO NOTHING` na chave de `movimentos`. |
| Biometria mínima | nenhuma tabela guarda foto nem referência de foto. |
| Rede | porta publicada só em `127.0.0.1:5433`; telemetria do TimescaleDB desligada. |

Os testes rodam no banco `filas_teste`, que tem o mesmo esquema; só nele o
`processador` pode fazer `TRUNCATE`.
