# Software para Sistemas Ubíquos — Atividade em Grupo 02
## Processamento e distribuição de responsabilidades

**Integrantes:**
- Caio Castro Miranda
- Jaime da Cruz Silva Junior
- João Pedro de Brito Tomé
- João Victor Braga Queiroz

**Cenário utilizado:** o mesmo da Atividade 01 (v2) — balanceamento de fluxo de fila em entrada única de eventos, com validação de ingresso feita pela câmera de um celular/tablet (modo QR Code ou reconhecimento facial), recomendação de fila calculada por um serviço agregador e exibida em painel de LED.

---

## Parte 1 — Eventos do sistema

### 1 e 2. Tipos de evento e contrato

Escolhemos dois eventos distintos, ambos produzidos pelo mesmo dispositivo (o celular/tablet do ponto de validação), mas representando ocorrências diferentes: uma é o resultado de uma ação do público (validar o ingresso), a outra é um sinal de vida do próprio dispositivo, usado para detectar falhas silenciosas.

#### Evento A — `ValidacaoRealizada`

| Campo | Descrição |
|---|---|
| Nome | `ValidacaoRealizada` |
| Produtor | Software local do celular/tablet no ponto de validação |
| Entidade observada | O ponto de validação (catraca/fila), não a pessoa — nenhum dado pessoal é incluído |
| Tempo do evento | Instante em que a decisão de validação (binária) foi tomada no aparelho |
| Campos | `fila_id` (identificador do ponto de validação), `modo` (`qr` \| `facial`), `resultado` (`validado` \| `nao_validado`), `seq` (número de sequência local do aparelho) |
| Unidade | Não aplicável (evento discreto, sem grandeza física) |
| Identificador/sequência | `seq` — contador monotônico por aparelho, reiniciado a cada sessão do app |

#### Evento B — `DispositivoHeartbeat`

| Campo | Descrição |
|---|---|
| Nome | `DispositivoHeartbeat` |
| Produtor | Software local do celular/tablet no ponto de validação |
| Entidade observada | O próprio dispositivo (estado operacional) |
| Tempo do evento | Instante da emissão do heartbeat, gerado a intervalos fixos |
| Campos | `fila_id`, `bateria_pct` (%), `fila_atual_estimada` (pessoas), `status` (`ok` \| `degradado`) |
| Unidade | `bateria_pct` em porcentagem; `fila_atual_estimada` em número de pessoas |
| Identificador/sequência | `heartbeat_seq` — contador monotônico por aparelho |

### 3. Exemplos em JSON

```json
// Evento A
{
  "evento": "ValidacaoRealizada",
  "fila_id": "portao-2-catraca-3",
  "tempo_evento": "2026-08-28T18:12:07.482Z",
  "modo": "qr",
  "resultado": "validado",
  "seq": 18422
}
```

```json
// Evento B
{
  "evento": "DispositivoHeartbeat",
  "fila_id": "portao-2-catraca-3",
  "tempo_evento": "2026-08-28T18:12:10.000Z",
  "bateria_pct": 74,
  "fila_atual_estimada": 12,
  "status": "ok",
  "heartbeat_seq": 6141
}
```

### 4. Qualidade

**Validação necessária:** todo evento recebido pelo serviço central passa por checagem de (a) esquema — campos obrigatórios presentes e com tipo/faixa esperada (ex.: `resultado` só pode ser um dos dois valores enumerados); e (b) monotonicidade de sequência por `fila_id`.

- **Evento inválido:** falha de esquema (campo ausente, tipo errado, `fila_id` desconhecido) → evento é rejeitado e registrado em log de erros, sem afetar o contador da fila.
- **Evento duplicado:** `seq` (ou `heartbeat_seq`) já processado anteriormente para aquele `fila_id` → evento é descartado silenciosamente (idempotência), pois o MQTT com QoS ≥ 1 pode reentregar mensagens.
- **Evento desatualizado (stale):** `tempo_evento` mais antigo que a janela de processamento corrente (ver item 8, tratamento de atraso) → tratado conforme a política de eventos atrasados, não como erro de validação.

---

## Parte 2 — Processamento temporal

### 5. Operações

```
ValidacaoRealizada / DispositivoHeartbeat
        │
        ▼
   Validação (esquema, seq)
        │
        ▼
   Filtragem (descarta duplicados e status "degradado" fora de janela)
        │
        ▼
   Transformação (evento → incremento de contagem por fila_id)
        │
        ▼
   Agrupamento (por fila_id, dentro da janela deslizante)
        │
        ▼
   Agregação (vazão móvel = contagem na janela / duração da janela)
        │
        ▼
   Detecção (compara vazão entre filas + curva histórica, aplica histerese)
        │
        ▼
   Atuação (comando de recomendação enviado ao painel de LED)
```

### 6. Estado e janela

**Regra:** recomendar a fila com maior vazão relativa (pessoas/minuto) frente à sua ocupação estimada, evitando trocar a recomendação por pequenas oscilações.

- **Tipo de janela:** deslizante (sliding window), não uma janela fixa/tumbling — porque a vazão precisa ser reavaliada continuamente, não apenas ao fim de um bloco fixo de tempo.
- **Duração da janela:** 120 segundos.
- **Frequência de avaliação:** a cada 15 segundos (a janela desliza; o resultado é recalculado nesse intervalo, não a cada evento individual, para suavizar ruído).
- **Estado mantido:** para cada `fila_id`, uma lista (ou contador incremental com decaimento) dos eventos `ValidacaoRealizada` com `resultado = validado` ocorridos nos últimos 120 s, mais o valor da última recomendação emitida (necessário para aplicar a histerese, isto é, exigir uma diferença mínima de vazão antes de trocar a recomendação).

### 7. Semântica temporal

A regra usa **tempo do evento** (`tempo_evento`, gerado no próprio celular), não tempo de processamento.

**Justificativa:** existem múltiplos dispositivos publicando via MQTT, com latência de rede variável entre eles; se a vazão fosse calculada pelo tempo de chegada ao serviço central, um atraso de rede maior em uma fila específica poderia distorcer sua vazão medida (parecendo mais lenta do que realmente é), prejudicando exatamente a fila que já está com problema de conectividade. Usar o tempo do evento mantém a métrica fiel ao que de fato aconteceu em cada ponto de validação.

### 8. Eventos atrasados

Quando um evento `ValidacaoRealizada` chega após o serviço já ter emitido uma recomendação baseada na janela à qual esse evento pertence:

- Se o atraso for pequeno (dentro de uma margem de tolerância de 10 s — compatível com jitter normal de rede local), o evento é **aceito e a contagem é corrigida retroativamente**: a vazão da fila é recalculada e, se a diferença ultrapassar a margem de histerese, uma nova recomendação é emitida.
- Se o atraso for maior que a margem de tolerância, o evento é **separado**: ainda incrementa o contador histórico/absoluto da fila (usado no painel administrativo e nas métricas pós-evento), mas **não** dispara recorreção da recomendação já exibida, evitando instabilidade visível para o público.
- Eventos de heartbeat atrasados além de 2 ciclos são simplesmente descartados (não fazem sentido retroativamente — servem apenas para status corrente).

### 9. Pseudocódigo

```
a cada 15s, para cada fila_id:

    janela = eventos_validados(fila_id, janela=120s, agora=tempo_evento_mais_recente)

    se tamanho(janela) < MINIMO_AMOSTRAS:
        manter recomendação atual (dado insuficiente)
        retorna

    vazao[fila_id] = contagem(janela) / duracao(janela)   # pessoas/min
    ocupacao_estimada[fila_id] = ultimo_heartbeat(fila_id).fila_atual_estimada

    score[fila_id] = vazao[fila_id] / max(ocupacao_estimada[fila_id], 1)

fila_recomendada_nova = argmax(score, sobre todas as filas com status == "ok")

se fila_recomendada_nova != fila_recomendada_atual:
    se |score[fila_recomendada_nova] - score[fila_recomendada_atual]| > MARGEM_HISTERESE:
        fila_recomendada_atual = fila_recomendada_nova
        emitir_comando(painel_led, fila_recomendada_atual)
    # senão: mantém recomendação atual, mesmo que outra fila esteja marginalmente melhor
```

---

## Parte 3 — Distribuição e resiliência

### 10. Distribuição de responsabilidades

Usamos apenas dois níveis do contínuo, considerados suficientes para o cenário: **dispositivo** e **névoa**. Não há necessidade de nuvem para a operação em tempo real (só eventualmente para dashboard histórico/entre eventos, fora do escopo desta atividade).

| Responsabilidade | Local de execução |
|---|---|
| Captura de imagem, leitura de QR ou comparação facial, decisão de validação | Dispositivo (celular/tablet) |
| Estado: contador local de validações do próprio aparelho | Dispositivo |
| Agregação entre filas, cálculo de vazão móvel, janela/histerese, decisão de recomendação | Névoa (servidor local do evento, na mesma rede do venue) |
| Estado: janela deslizante de 120s por fila, última recomendação emitida | Névoa |
| Envio do comando de acionamento ao painel de LED | Névoa → dispositivo atuador (painel) |

### 11. Justificativas

1. **Agregação e decisão na névoa, não na nuvem** — critério de **latência e conectividade**. A recomendação de fila precisa ser recalculada a cada poucos segundos e continuar funcionando mesmo que o link de internet do evento caia (situação comum em locais com grande concentração de pessoas disputando banda de rede móvel). Um servidor de névoa na rede local do venue mantém a decisão operando independentemente da internet externa.

2. **Reconhecimento facial e leitura de QR inteiramente no dispositivo, nunca na névoa** — critério de **privacidade**. Como discutido na Atividade 01, o dado biométrico (rosto) é dado pessoal sensível pela LGPD; processá-lo e descartá-lo localmente, publicando somente o resultado binário da validação, elimina a superfície de risco de vazamento ou uso indevido que existiria se a imagem trafegasse até qualquer serviço central, mesmo que local.

### 12. Comportamento diante de falhas

**Falha escolhida:** conexão indisponível entre o dispositivo e o servidor de névoa (broker MQTT inalcançável).

Comportamento: o dispositivo continua validando ingressos normalmente (a validação em si não depende da rede). Os eventos `ValidacaoRealizada` são enfileirados localmente. O painel de LED daquela fila passa a exibir a **última recomendação recebida antes da queda** (modo degradado, sem atualização), em vez de apagar ou travar. Quando a conexão for restabelecida, o dispositivo reenvia a fila de eventos pendentes (marcados com seus `tempo_evento` originais), e a névoa aplica a regra de eventos atrasados do item 8 para corrigir a janela sem gerar uma recomendação instável. Se a indisponibilidade ultrapassar um limite (ex.: 3 ciclos de heartbeat perdidos), o serviço de névoa marca aquela fila como `status: degradado` e a exclui do cálculo de `argmax` até voltar a responder, evitando recomendar uma fila da qual não há dado confiável.

### 13. Diagrama

```
Pessoa valida ingresso (fenômeno físico)
        │
        ▼
Câmera do celular (sensor) — DISPOSITIVO
        │
        ▼
Validação local (QR ou facial) → ValidacaoRealizada
Heartbeat periódico → DispositivoHeartbeat
        │  publica via MQTT (apenas resultado + contagem)
        ▼
Serviço de névoa (rede local do evento)
        │
        ├─ Validação/filtragem/dedup dos eventos
        ├─ Estado: janela deslizante 120s por fila_id
        ├─ Agregação: vazão móvel + score
        └─ Detecção: comparação entre filas + histerese
        │
        ▼
   Decisão: fila recomendada
        │  comando via MQTT
        ▼
Painel de LED da fila (atuador) — DISPOSITIVO
        │
        ▼
Público observa e segue a fila indicada
```

**Representações mínimas (resumo):**
- Evento: `ValidacaoRealizada` (dispositivo → serviço de névoa, tempo do evento, campos `fila_id/modo/resultado/seq`)
- Regra: janela deslizante 120s / estado = validações recentes por fila / condição = `score` acima da margem de histerese / decisão = troca de recomendação
- Fluxo: validação → validação/filtragem/transformação/agrupamento/agregação/detecção → estado da janela → decisão → comando ao painel
- Distribuição: captura+validação → dispositivo (privacidade); agregação+decisão → névoa (latência/conectividade)
