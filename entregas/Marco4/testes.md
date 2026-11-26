# Testes automatizados — Marco 4

A suíte não inclui teste de APK. O pacote existe: é o build EAS linkado no README da raiz, e não entra no Git por causa do tamanho. Nenhum teste automatizado instala esse arquivo.

## Verificação pedida no enunciado

Quatro verificações da seção 4. Onde a demonstração ainda não aconteceu, a coluna do observado diz isso em vez de inventar um resultado. A tabela guarda o que foi observado em 25/11; a execução de 26/11, com a suíte de 119 testes e o ponta a ponta com os dois simuladores, está em [Resultado observado em 26 de novembro de 2026](#resultado-observado-em-26-de-novembro-de-2026).

| Verificação | Passos e entradas | Resultado esperado | Resultado observado em 25/11/2026 | Evidência |
|---|---|---|---|---|
| Fluxo e contexto | `test_fluxo_do_app`: cadastro, compra e leitura na catraca por um validador. `test_fila_recomendada_para_quem_chega`: duas filas, uma bloqueada e outra em atenção; duas livres com esperas diferentes; uma livre e outra sem enlace. `test_horario_antigo_do_esp_nao_bloqueia_estado`: contagem, heartbeat e saída. | Dois produtores chegam ao processador (movimento do sensor e leitura do backend). Quem decide o ingresso e o semáforo é o processador. A fila recomendada muda com o semáforo e a espera, e uma fila sem enlace deixa de ser destino. | Os três testes passaram. A tela do aplicativo, com a fila recomendada mudando no celular, não foi aberta nesta execução. | `evidencias/unittest-2026-11-25.txt`. A demonstração gravada do aplicativo está no [Drive](https://drive.google.com/file/d/1IyoW87-bQh-Tf3qgKNgGXRloHaFUiPyJ/view?usp=sharing). |
| Persistência | `test_persiste_e_deduplica_movimentos`: grava uma contagem, repete o mesmo `event_id`, fecha a conexão, abre outra no mesmo `filas_teste` e aplica a saída. | A repetição não muda o saldo. Depois de reabrir a conexão, a ocupação continua a que foi gravada. | Passou. Não foi desligado o contêiner do processador no meio de um evento com o banco `filas`. | O mesmo log. |
| Segurança | `test_fluxo_do_app`: senha errada, leitura sem token e cliente autenticado chamando a catraca. `test_dashboard`: anônimo, cliente e admin rebaixado. `test_horario_antigo_do_esp_nao_bloqueia_estado`: leitura com autor que não é validador. `broker/testar-acl.py`: o produtor publica `fila/teste-marco3/heartbeat`; o processador e o produtor assinam esse tópico. | 401 para senha errada e para anônimo; 403 para cliente na catraca e para admin rebaixado; recusa `validador-nao-autorizado`. No broker, o processador recebe e o produtor não lê. A conexão exige a CA do projeto. | Os testes da suíte passaram. O script da ACL imprimiu `ACL de leitura: processador recebeu; produtor não recebeu. OK`. O log do broker, na mesma hora, registrou os dois usuários com TLS 1.3 e cifra `TLS_AES_256_GCM_SHA384`. Não foram executados o firmware intruso (senha MQTT inválida) nem o HTTPS do celular. | `evidencias/unittest-2026-11-25.txt`, `evidencias/acl-2026-11-25.txt` e `evidencias/acl-broker-2026-11-25.txt`. Intruso e celular: [Drive](https://drive.google.com/file/d/1IyoW87-bQh-Tf3qgKNgGXRloHaFUiPyJ/view?usp=sharing). |
| Falha e recuperação | `test_processador_fora_nao_gasta_o_ingresso` e o trecho de espera esgotada em `test_fluxo_do_app`: a leitura é publicada e o processador não responde a tempo; em seguida uma leitura nova, com o processador no ar. | HTTP 504, ingresso não marcado como usado; na leitura seguinte, aceite. | Os dois testes passaram. `tests/e2e_completo.py`, que para o processo de verdade com o Wokwi no ar, não rodou em 25/11. Em 26/11 rodou completo: com o contêiner do processador parado, a catraca recebeu 504; ao voltar, o processador descartou a leitura vencida e a nova leitura foi aceita. | O mesmo log da suíte; em 26/11, `evidencias/e2e-2026-11-26-execucao2.txt`. |

## Comando

Na raiz do projeto, com o banco `filas_teste` no ar (TimescaleDB em `127.0.0.1:5433`, TLS, senha do papel `processador` em `.local/banco/`, fora do Git):

```
python -m unittest discover -s tests -v
```

Nesta máquina (Windows, Python 3.12.6, ambiente virtual já instalado com `requirements.txt`):

```
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`discover` só recolhe arquivos `test*.py`. Entram `test_admin.py`, `test_apresentacao.py`, `test_backend.py`, `test_contrato.py`, `test_estado_filas.py`, `test_heartbeat.py`, `test_seguranca.py`, `test_unidades.py`, `test_unidades_processador.py` e `test_unidades_seguranca.py`. Ficam de fora, de propósito, `tests/e2e_completo.py` e `tests/demo_lotacao.py`: são roteiros com Wokwi e AWS, não a suíte unitária.

Comando separado, com o broker do projeto no ar:

```
python broker/testar-acl.py
```

A saída de 25/11/2026 está em `evidencias/acl-2026-11-25.txt`. O broker registrou TLS 1.3 nessa conexão (`evidencias/acl-broker-2026-11-25.txt`).

## Módulos e requisitos

| Módulo | Tipo | Requisito do marco | Evidência |
|---|---|---|---|
| `tests/test_contrato.py` | unitário | Contrato e validação da mensagem | `evidencias/unittest-2026-11-25.txt` |
| `tests/test_estado_filas.py` | integração com `filas_teste` | Persistência: gravar, reler e preservar depois de fechar a conexão | o mesmo arquivo |
| `tests/test_heartbeat.py` | integração com o processador e `filas_teste` | Contexto, tempo, regra com estado, validade, duplicata e falha sem gastar o ingresso | o mesmo arquivo |
| `tests/test_backend.py` | integração da API, AWS e MQTT dobrados | Fluxo do app, 401, 403, 504 e fila recomendada | o mesmo arquivo |
| `tests/test_admin.py` | integração da API de admin | Autorização: anônimo, cliente e admin rebaixado | o mesmo arquivo |
| `tests/test_apresentacao.py` | integração backend + processador | Falha do processador e recuperação numa leitura nova | o mesmo arquivo |
| `tests/test_unidades.py` e `tests/test_unidades_processador.py` | unitário, sem banco e sem broker | Funções de senhas, contrato, modelos, estado, backend, observabilidade e processador, incluindo a rajada de saídas depois de uma queda | `evidencias/unittest-2026-11-26.txt` |
| `tests/test_unidades_seguranca.py` | unitário, sem banco e sem broker | Limite de tentativas de login, registro de logins recusados e acessos negados, recusas do broker e métricas | o mesmo arquivo |
| `tests/test_seguranca.py` | integração com `filas_teste` | Limite de login com o banco, tentativas em paralelo, registro na auditoria e métricas calculadas no banco | o mesmo arquivo |
| `broker/testar-acl.py` | integração com o Mosquitto | Leitura permitida e leitura proibida no canal | `evidencias/acl-2026-11-25.txt` e `evidencias/acl-2026-11-26.txt` |
| `tests/e2e_completo.py` | ponta a ponta | Fluxo com os dois simuladores, o Rekognition e o 504 com o processador parado | `evidencias/e2e-2026-11-26.txt` (falhou) e `evidencias/e2e-2026-11-26-execucao2.txt` (passou) |
| APK / Expo | — | Aplicativo instalável | fora da suíte |

O detalhe do que cada asserção confere está na seção 5 de `artigo.md`.

## Resultado observado em 25 de novembro de 2026

Ambiente da execução que ficou registrada: Windows, Python 3.12.6, dependências de `requirements.txt` no `.venv`, TimescaleDB 2.17.2 (`timescale/timescaledb:2.17.2-pg17`) em `127.0.0.1:5433`. O broker não estava no ar.

Antes de o motor do Docker responder, a porta 5433 estava fechada e a suíte que abre o banco não concluía. Com o banco no ar, a primeira passagem completa achou 8 testes e falhou em 2 (`test_fluxo_do_app` e `test_processador_fora_nao_gasta_o_ingresso`): `permission denied for table movimentos` para o papel `backend`. `banco/ingressos.sql` já contém `GRANT SELECT, INSERT ON movimentos TO backend`. O volume local não tinha essa concessão. Ela foi aplicada só em `filas_teste`, sem mudança de código:

```
docker exec -u postgres leite-de-pedra-banco psql -d filas_teste -c "GRANT SELECT, INSERT ON movimentos TO backend;"
```

O banco `filas` não foi modificado. Se esse volume também for anterior ao `GRANT` de `banco/ingressos.sql`, o 504 da demonstração pode esbarrar na mesma permissão.

A passagem seguinte está em `evidencias/unittest-2026-11-25.txt`.

| Teste | Resultado |
|---|---|
| `test_admin.AdminTest.test_dashboard` | ok |
| `test_apresentacao.ApresentacaoTest.test_processador_fora_nao_gasta_o_ingresso` | ok |
| `test_apresentacao.ApresentacaoTest.test_processador_no_ar_libera_o_dono` | ok |
| `test_backend.BackendTest.test_fila_recomendada_para_quem_chega` | ok |
| `test_backend.BackendTest.test_fluxo_do_app` | ok |
| `test_contrato.ContratoTest.test_aceita_so_mensagem_do_contrato_que_combina_com_o_topico` | ok |
| `test_estado_filas.EstadoFilasTest.test_persiste_e_deduplica_movimentos` | ok |
| `test_heartbeat.HeartbeatTest.test_horario_antigo_do_esp_nao_bloqueia_estado` | ok |

Rodapé do arquivo: `Ran 8 tests in 7.420s` e `OK`. O log também guarda um `ValueError: Invalid host` numa thread do Paho, porque o broker estava desligado nessa passagem, e `ResourceWarning` de socket. Isso não reprovou teste. O broker foi ligado depois, só para `broker/testar-acl.py`. `tests/e2e_completo.py` não foi executado.

## Resultado observado em 26 de novembro de 2026

Ambiente: Linux (Debian 13), Python 3.13.5 no `.venv`, os cinco serviços do `docker compose` no ar (TimescaleDB 2.17.2, Mosquitto 2.1.2, processador, observabilidade e backend em HTTPS), AWS em `us-east-2` e as duas simulações do Wokwi no VS Code, rodando a 22–23% da velocidade real.

### Suíte

```
PYTHONWARNINGS=ignore .venv/bin/python -m unittest discover -s tests -v
```

`Ran 119 tests in 10.676s` e `OK` (`evidencias/unittest-2026-11-26.txt`). Os 8 testes de 25/11 continuam e passam; os demais vieram com os testes unitários e com o limite de login, o registro de acessos recusados, as recusas do broker e as métricas. As mensagens de leituras recusadas no log são casos provocados pelos próprios testes.

### ACL do broker

`broker/testar-acl.py` foi corrigido: antes, o produtor leitor e o produtor que publica eram dois clientes com o mesmo usuário, e o broker (que usa o usuário como client id) derrubava o leitor, de modo que "produtor não recebeu" passava mesmo com a ACL errada. Agora um único cliente `produtor` assina e publica, e o leitor permitido é o `observador`. Com a ACL liberando a leitura de propósito, o script falha; com a ACL do projeto, imprime `ACL de leitura: observador recebeu; produtor não recebeu. OK` (`evidencias/acl-2026-11-26.txt`). O log do broker da mesma execução, sem nenhuma desconexão por `session taken over` entre os clientes do teste, está em `evidencias/acl-broker-2026-11-26.txt`.

### Ponta a ponta

```
E2E_BACKEND=https://localhost:8444 SSL_CERT_FILE=.local/mqtt/ca.crt .venv/bin/python tests/e2e_completo.py
```

O script usa `http://127.0.0.1:8444` por padrão; o backend só responde em HTTPS, então o endereço e a CA do projeto foram passados pelo ambiente, sem mudar o código.

**Primeira execução (00:51–00:53), falhou no passo 7** (`evidencias/e2e-2026-11-26.txt`). Os passos 1 a 6 passaram: sete contas criadas com rostos gerados por IA cadastrados no Rekognition, componentes e heartbeat no ar, ingressos comprados, fila-a lotada e bloqueada recomendando a fila-b, e duas pessoas na fila-b. No passo 7, a leitura de `e2e-cliente-1` foi aceita (o processador publicou o resultado cerca de 37 ms depois da leitura), mas o consumidor não reagiu em 15 s.

A causa: o consumidor usa sessão persistente e assinava `fila/+/estado` com QoS 1. Enquanto esteve desligado, o broker guardou cada mudança de estado para entregar depois; ao reconectar, o consumidor recebia estados de quatro horas antes (11 a 13 pessoas na fila-a, gravados no banco às 21h04 do dia anterior), fechava a conexão uns 8 s depois (`connection closed by client` no broker; na serial, `SSL - The connection indicated an EOF` e `Falha MQTT: -3`) e voltava 20 s depois. O resultado do teste ficou atrás dessa fila. A sessão guardada foi descartada com uma conexão de sessão limpa no usuário `consumidor`; o ESP32 reconectou sozinho e ficou estável.

**Segunda execução (01:00–01:03), passou nos dez passos** (`evidencias/e2e-2026-11-26-execucao2.txt`):

| Passo | Resultado |
|---|---|
| 1. Contas e2e (reaproveitadas) | ok |
| 2. Produtor, consumidor, processador e backend online; heartbeat das duas filas | ok |
| 3. Compra de 5 ingressos | ok |
| 4. Filas zeradas | ok |
| 5. Fila-a com 5 pessoas, bloqueada e recomendando a fila-b | ok |
| 6. Fila-b com 2 pessoas | ok |
| 7. Catraca da fila-a: aceito, `ingresso-ja-usado`, `rosto-nao-confere` e mais dois aceitos, cada um com a reação do consumidor (liberar ou barrar) | ok |
| 8. Catraca da fila-b: aceito, consumidor liberou | ok |
| 9. Processador parado: 504; de volta, descartou a leitura vencida (`leitura-expirada`) e a nova leitura foi aceita | ok |
| 10. Filas vazias e livres; cada ingresso usado na fila em que a pessoa entrou | ok |

Rodapé: `Tudo certo. Leituras: {'aceito': 6, 'recusado': 2, 'indeterminado': 1}`. Esses números somam o banco `filas` inteiro, não só esta execução.

O teste age sobre o sistema real: as contas `e2e-*` ficam no banco `filas`, os rostos na coleção do Rekognition e as fotos no bucket até a regra de um dia.

### O que continua em aberto

- Depois dessas execuções, o firmware do consumidor passou a assinar `estado` com QoS 0 (é retido, então chega na reconexão) e a manter QoS 1 só em `resultado`, para o broker não acumular estados antigos enquanto ele está desligado. A mudança compila, mas ainda não foi validada numa nova execução do ponta a ponta.
- A queda do consumidor a cada ~8 s só foi observada com a fila guardada. O firmware passou a imprimir na serial `Conexão MQTT caiu: erro N` quando a biblioteca fecha a conexão no meio do laço; a causa exata ainda não foi registrada.
- O ponta a ponta depende do Wokwi rodando com as duas janelas visíveis no VS Code; não roda em integração contínua.

