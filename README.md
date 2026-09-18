# Marco 2 — cooperação observável entre produtor e consumidor

Fronteira integrada: o **produtor** publica eventos de contagem, validação e
heartbeat; o **consumidor** deriva ocupação e tempo de espera e publica de volta
uma **recomendação**; o **observador** é um terceiro assinante que acompanha a
travessia sem que produtor e consumidor saibam da sua existência.

## Contrato

Eventos de telemetria (`fila/{id}/contagem`, `fila/{id}/validacao`, `fila/{id}/heartbeat`):

```json
{"filaId": "fila-a", "tipo": "contagem", "sequence": 41, "eventTimeMs": 1758200000000}
```

`validacao` acrescenta `"resultado": "aprovado" | "reprovado"`.
A identidade de um evento é o par `(tipo, sequence)`.

Recomendação (`fila/{id}/recomendacao`), publicada pelo consumidor:

```json
{"filaId": "fila-a", "sentidoRecomendado": "fila-b", "tempoEsperaEstimado": 120}
```

## Preparação (uma vez)

```
sudo apt install mosquitto mosquitto-clients python3-paho-mqtt
sudo systemctl stop mosquitto
sudo systemctl disable mosquitto
```

As duas últimas linhas são necessárias: o pacote sobe o mosquitto como serviço e
ele ocupa a porta 1883, o que faz `mosquitto -c mosquitto.conf` falhar com
"Address already in use". A demonstração precisa do broker em primeiro plano,
sob controle de quem apresenta.

## Executar

Quatro terminais.

```
mosquitto -c mosquitto.conf     # terminal 1
python3 -u consumidor.py        # terminal 2
python3 -u observador.py        # terminal 3
python3 -u produtor.py          # terminal 4
```

O `-u` evita que o Python segure a saída em buffer — sem ele os logs aparecem
em blocos e a demonstração perde o tempo real.

## Roteiro da demonstração

**1. Regime normal.** O observador mostra latência de 1 a 3 ms. Contagens a cada
1s, heartbeats a cada 2s, validações a cada 3s. O consumidor publica recomendações
conforme a ocupação muda.

**2. Queda do enlace.** `Ctrl+C` no terminal do broker. Observe:

- o produtor passa a registrar `Sem enlace: evento acumulado na fila local (N pendentes)`
- o observador silencia
- passados 6 s, o consumidor imprime `sem dados atualizados - mantendo recomendação anterior`

O ponto a destacar: o consumidor **não** decide com informação vencida. Ele
congela e declara o motivo.

**3. Volta do enlace.** Reinicie `mosquitto -c mosquitto.conf`. Observe:

- produtor: `Reenviado da fila local:` — os eventos saem na ordem em que foram gerados
- consumidor e observador: `assinaturas restabelecidas`
- observador: latências de ~15000 ms nos eventos atrasados, e
  `ALERTA: fila X sem heartbeat há mais de 8s`

A latência alta é a evidência visível de que aquele evento não descreve mais o
presente.

## Notas de implementação

As assinaturas são feitas dentro do callback `on_connect`, não uma única vez
antes do laço. Numa sessão limpa o broker descarta as assinaturas quando a
conexão cai; assinar apenas na partida faz o cliente reconectar e ficar surdo.

A fila local do produtor tem limite de 200 eventos (`deque(maxlen=200)`). Numa
queda longa os eventos mais antigos são descartados em favor dos mais recentes.
