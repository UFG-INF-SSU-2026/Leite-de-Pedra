# Limitações declaradas — Marco 4

Este arquivo cumpre a declaração pedida para o marco. O artigo discute as mesmas fronteiras na seção 6. Nenhuma delas é apresentada como defeito escondido: são limites do que o sistema faz hoje e do que esta versão mediu.

## Simulação

Os sensores de fila e o consumidor de sinalização são firmware de ESP32 no Wokwi, não uma bancada física. A passagem de uma pessoa é o ciclo de distância 400 cm, 40 cm, 400 cm no HC-SR04 simulado. O relógio do simulador pode avançar mais devagar que o da máquina; por isso a atividade do enlace usa o relógio monotônico do processador, com tolerância de 15 s, e não o `timestamp` do ESP32. Pelo mesmo motivo, a vazão marca cada saída pela hora em que o processador a recebe. As duas placas não compartilham um circuito: o Wokwi desta licença não simula os dois microcontroladores no mesmo projeto, e elas se falam pelo broker.

## Dados pessoais

O sistema trata nome, login, senha (só o hash scrypt) e imagem do rosto. A foto de cadastro vai para a coleção do Rekognition. A foto da catraca vai para um bucket S3 privado, no prefixo `leituras/`. Aceite apaga essa foto na hora. Recusa, indeterminado e leitura sem resposta ficam até a regra de ciclo de vida de um dia. O MQTT não transporta a imagem; o TimescaleDB não guarda a foto nem a referência. O painel só abre a imagem por link de cinco minutos, e cada abertura entra na auditoria. Não há base legal nem termo de consentimento redigidos neste repositório: a declaração aqui é técnica, sobre o que é coletado e onde para.

## Segurança

MQTT só em TLS na porta 8883, com a CA do projeto e senha por identidade. O banco só aceita TLS 1.2 ou superior, com `sslmode=verify-full`, e cada serviço tem um papel. Segredos ficam em `.local/` e no `.env`, fora do Git. Credencial de admin não vai no aplicativo: o papel é definido no servidor.

O volume Docker do banco não é cifrado em repouso. As contas de teste `cliente`, `validador` e `admin` usam a senha `123` e só servem para demonstração; `banco/seed.py` não deve rodar num evento real. O reconhecimento depende da conta AWS do backend. Existe o modo `BACKEND_SEM_TLS=1`, que tira a criptografia do HTTPS. Ele não atende a verificação de canal protegido. A demonstração tem de usar o HTTPS descrito em `mobile/README.md`.

Não houve ensaio de invasão além do firmware intruso (senha inválida recusada pelo broker), do script de ACL e das respostas 401 e 403 da API.

## Conectividade

Sem heartbeat recebido em 15 s, a fila deixa de ser atualizada e deixa de ser destino; o consumidor permanece no último estado retido. Se o aplicativo não alcança o backend, a interface mostra falta de conexão e não troca para a tela de sucesso. Se o backend está no broker e o processador não responde em 10 s, a catraca recebe HTTP 504, o ingresso não é marcado como usado e a leitura atrasada expira. Se o próprio backend perde o broker, a resposta é 503 e nada é publicado.

Não foi medido o comportamento numa rede com perda, atraso ou partição controlados. O ensaio `tests/e2e_completo.py`, que percorre esse 504 com os simuladores no ar, não faz parte da execução registrada em `evidencias/`.

## Desempenho

Não há teste de carga, nem medição de latência de ponta a ponta com o broker, o Rekognition e o banco ao mesmo tempo, nem meta de vazão de catraca. Os limiares de 15 s e 30 s são parâmetros de significado para quem espera, não um resultado de capacidade medida.

## Energia

Não há medição de consumo do celular nem de um ESP32 físico. O aplicativo usa a câmera no cadastro e na captura da catraca, não em segundo plano contínuo. O firmware simulado não representa a corrente de um rádio e de quatro sensores ultrassônicos reais. Qualquer afirmação de autonomia ficaria sem evidência.
