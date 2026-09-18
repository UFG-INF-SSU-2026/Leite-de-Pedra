# Marco 2 — balanceamento de filas de entrada

Em um evento com várias filas de entrada, o público tende a se concentrar numa
delas. O sistema conta quem entra e quem sai de cada fila, estima quanto tempo
cada uma está levando e sinaliza num semáforo qual fila procurar — para que um
pico de chegada se distribua em vez de empilhar numa fila só.

## Componentes

| Componente | Papel |
|---|---|
| `produtor.py` | Simula o mundo físico: infravermelho na entrada de cada fila conta quem chega; validador facial no fim conta quem entra no evento. Obedece ao semáforo. |
| `consumidor.py` | Deriva ocupação, vazão e tempo de espera. Classifica o semáforo e publica a recomendação. |
| `observador.py` | Terceiro assinante. Acompanha a travessia e alerta se o enlace cair. |

A fronteira integrada é produtor ↔ consumidor, mediada pelo broker MQTT.

## Como a ocupação é medida

```
ocupação = pessoas contadas pelo infravermelho − pessoas aprovadas no validador
```

Entradas e saídas são **contadores acumulados**. A janela deslizante de 20
eventos serve apenas para a vazão — quantas pessoas por segundo aquela fila
está consumindo agora.

```
vazão        = aprovados na janela ÷ duração da janela
tempo espera = ocupação ÷ vazão
```

## Semáforo

| Estado | Condição | Significado |
|---|---|---|
| verde | ocupação ≤ 5 | fila livre, permaneça |
| amarelo | 6 a 10 | enchendo |
| vermelho | acima de 10 | bloqueada, procure outra fila |

Os limites ficam em `LIMITE_ATENCAO` e `LIMITE_BLOQUEIO`, no topo do
`consumidor.py`.

Para **descer** de estado a ocupação precisa cair `MARGEM_HISTERESE` abaixo do
limite. Sem isso o semáforo piscaria entre dois estados com a ocupação
oscilando de um em um.

## Quando o sistema desvia pessoas

Em regime normal **todas as filas recomendam a si mesmas** — ninguém é desviado.
O desvio só entra quando uma fila sai do verde, e mesmo assim só aponta para
uma fila que esteja **num estado melhor**. Se todas estiverem igualmente cheias,
não há para onde mandar e cada fila continua recomendando a si mesma.

Isso evita o efeito pingue-pongue: comparar números de ocupação diretamente faz
a recomendação alternar a cada evento e as pessoas seriam mandadas de um lado
para o outro sem ganho nenhum.

## Contrato

Telemetria — `fila/{id}/contagem`, `fila/{id}/validacao`, `fila/{id}/heartbeat`:

```json
{"filaId": "fila-a", "tipo": "contagem", "sequence": 41, "eventTimeMs": 1758200000000}
```

`validacao` acrescenta `"resultado": "aprovado" | "reprovado"`.
A identidade de um evento é o par `(tipo, sequence)`.

Recomendação — `fila/{id}/recomendacao`, publicada pelo consumidor:

```json
{"filaId": "fila-a", "semaforo": "bloqueada", "ocupacao": 12,
 "sentidoRecomendado": "fila-b", "tempoEsperaEstimado": 180}
```

O produtor assina esse tópico: quem chega e vê o semáforo fechado entra na fila
indicada. É o que fecha o ciclo — a recomendação muda o comportamento, e não
apenas informa.

## Preparação (uma vez)

```
sudo apt install mosquitto mosquitto-clients python3-paho-mqtt
sudo systemctl stop mosquitto
sudo systemctl mask mosquitto
```

O pacote sobe o mosquitto como serviço e ele ocupa a porta 1883, o que faz
`mosquitto -c mosquitto.conf` falhar com "Address already in use". `disable`
não basta — ele só impede o autostart no boot, e o serviço volta a subir.
`mask` bloqueia de vez. Para reverter: `sudo systemctl unmask mosquitto`.

## Executar

Quatro terminais.

```
mosquitto -c mosquitto.conf     # terminal 1
python3 -u consumidor.py        # terminal 2
python3 -u observador.py        # terminal 3
python3 -u produtor.py          # terminal 4
```

### Quantas filas

O produtor aceita 2, 3 ou 4 filas; sem argumento, usa 2.

```
python3 -u produtor.py 4
```

**Só o produtor recebe esse parâmetro.** O consumidor descobre as filas pelos
tópicos que chegam — ele assina `fila/+/contagem`, então não precisa saber
quantas existem, nem ser reiniciado quando o produtor sobe com outra
quantidade. O observador também não, porque assina `fila/#`.

Cada fila tem o seu próprio validador, então acrescentar filas acrescenta
capacidade na mesma medida. Com mais filas, um pico se dilui melhor: a carga
desviada se reparte entre todas as outras em vez de cair sobre uma só.

O `-u` evita que o Python segure a saída em buffer — sem ele os logs aparecem
em blocos e a demonstração perde o tempo real.

## O que acontece sozinho

O consumidor imprime um painel a cada 2 s com as duas filas lado a lado —
estado, ocupação, vazão, espera estimada e para onde mandar quem chega. As
mudanças de estado saem destacadas entre os painéis.

O produtor dispara **picos periódicos, alternando de fila**: o primeiro aos
12 s na fila-a, e daí em diante a cada 40 s, trocando de fila a cada vez
(`PICO_ATRASO`, `PICO_DURACAO`, `CICLO_PICO`, `INTERVALO_PICO`). Num evento real
os picos se repetem e não se concentram sempre na mesma entrada; repetir também
garante que a demonstração sempre tenha um ciclo à vista, sem depender de quem
apresenta subir o produtor no instante certo.

Cada ciclo, sem intervenção:

1. as duas filas começam verdes e ninguém é desviado
2. a fila em pico passa de 5 e fica amarela; começa a apontar para a outra
3. passa de 10 e fica vermelha
4. a outra fila absorve os desvios e também enche
5. a fila em pico drena, volta a amarelo e depois a verde
6. as duas terminam verdes, até o próximo pico

## Queda do enlace

`Ctrl+C` no terminal do broker.

- o produtor acumula em fila local de até 200 eventos
- o observador silencia
- passados 6 s, o consumidor congela: `sem dados atualizados - mantendo recomendação anterior`

Ao religar, o produtor esvazia a fila local em ordem e o observador mostra
latências de ~15 000 ms nos eventos atrasados.

O consumidor **continua congelado durante todo o reenvio**, mesmo já recebendo
eventos. Isso é proposital: a validade é medida pelo `eventTimeMs`, o instante
em que o evento aconteceu, e não pelo instante em que o pacote chegou. Os
eventos reenviados entram na contabilidade — ocupação é contador acumulado, e
descartá-los perderia o saldo de quem entrou e saiu durante a queda — mas não
valem como sinal de que há dado atual. A recomendação só volta quando chegar
evento recente de fato.

## Notas de implementação

As assinaturas são feitas dentro do callback `on_connect`, não uma única vez
antes do laço. Numa sessão limpa o broker descarta as assinaturas quando a
conexão cai; assinar apenas na partida faz o cliente reconectar e ficar surdo.

Uma validação `reprovado` não remove a pessoa da fila — ela continua lá para
tentar de novo. Só `aprovado` conta como saída.
