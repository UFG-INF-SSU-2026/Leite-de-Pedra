# Testes automatizados — Marco 4

A suíte não inclui teste de APK. O pacote não está no repositório, e um teste desse artefato não foi criado.

## Verificação pedida no enunciado

Quatro verificações da seção 4. Onde a demonstração ainda não aconteceu, a coluna do observado diz isso em vez de inventar um resultado.

| Verificação | Passos e entradas | Resultado esperado | Resultado observado em 25/11/2026 | Evidência |
|---|---|---|---|---|
| Fluxo e contexto | `test_fluxo_do_app`: cadastro, compra e leitura na catraca por um validador. `test_fila_recomendada_para_quem_chega`: duas filas, uma bloqueada e outra em atenção; duas livres com esperas diferentes; uma livre e outra sem enlace. `test_horario_antigo_do_esp_nao_bloqueia_estado`: contagem, heartbeat e saída. | Dois produtores chegam ao processador (movimento do sensor e leitura do backend). Quem decide o ingresso e o semáforo é o processador. A fila recomendada muda com o semáforo e a espera, e uma fila sem enlace deixa de ser destino. | Os três testes passaram. A tela do aplicativo, com a fila recomendada mudando no celular, não foi aberta nesta execução. | `evidencias/unittest-2026-11-25.txt`. A parte do aplicativo fica para o vídeo. |
| Persistência | `test_persiste_e_deduplica_movimentos`: grava uma contagem, repete o mesmo `event_id`, fecha a conexão, abre outra no mesmo `filas_teste` e aplica a saída. | A repetição não muda o saldo. Depois de reabrir a conexão, a ocupação continua a que foi gravada. | Passou. Não foi desligado o contêiner do processador no meio de um evento com o banco `filas`. | O mesmo log. |
| Segurança | `test_fluxo_do_app`: senha errada, leitura sem token e cliente autenticado chamando a catraca. `test_dashboard`: anônimo, cliente e admin rebaixado. `test_horario_antigo_do_esp_nao_bloqueia_estado`: leitura com autor que não é validador. `broker/testar-acl.py`: o produtor publica `fila/teste-marco3/heartbeat`; o processador e o produtor assinam esse tópico. | 401 para senha errada e para anônimo; 403 para cliente na catraca e para admin rebaixado; recusa `validador-nao-autorizado`. No broker, o processador recebe e o produtor não lê. A conexão exige a CA do projeto. | Os testes da suíte passaram. O script da ACL imprimiu `ACL de leitura: processador recebeu; produtor não recebeu. OK`. O log do broker, na mesma hora, registrou os dois usuários com TLS 1.3 e cifra `TLS_AES_256_GCM_SHA384`. Não foram executados o firmware intruso (senha MQTT inválida) nem o HTTPS do celular. | `evidencias/unittest-2026-11-25.txt`, `evidencias/acl-2026-11-25.txt` e `evidencias/acl-broker-2026-11-25.txt`. Intruso e celular: vídeo. |
| Falha e recuperação | `test_processador_fora_nao_gasta_o_ingresso` e o trecho de espera esgotada em `test_fluxo_do_app`: a leitura é publicada e o processador não responde a tempo; em seguida uma leitura nova, com o processador no ar. | HTTP 504, ingresso não marcado como usado; na leitura seguinte, aceite. | Os dois testes passaram. `tests/e2e_completo.py`, que para o processo de verdade com o Wokwi no ar, não rodou. | O mesmo log da suíte. |

## Comando

Na raiz do projeto, com o banco `filas_teste` no ar (TimescaleDB em `127.0.0.1:5433`, TLS, senha do papel `processador` em `.local/banco/`, fora do Git):

```
python -m unittest discover -s tests -v
```

Nesta máquina (Windows, Python 3.12.6, ambiente virtual já instalado com `requirements.txt`):

```
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`discover` só recolhe arquivos `test*.py`. Entram `test_admin.py`, `test_apresentacao.py`, `test_backend.py`, `test_contrato.py`, `test_estado_filas.py` e `test_heartbeat.py`. Ficam de fora, de propósito, `tests/e2e_completo.py` e `tests/demo_lotacao.py`: são roteiros com Wokwi e AWS, não a suíte unitária.

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
| `broker/testar-acl.py` | integração com o Mosquitto | Leitura permitida e leitura proibida no canal | `evidencias/acl-2026-11-25.txt` |
| `tests/e2e_completo.py` | ponta a ponta | Fluxo com os dois simuladores | não executado nesta data |
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
