# Balanceamento de filas de entrada com decisão na catraca por reconhecimento facial

Caio Castro Miranda, João Pedro de Brito Tomé, João Victor Braga e Jaime da Cruz

Universidade Federal de Goiás  
Software para Sistemas Ubíquos  
Novembro de 2026

## Resumo

Filas de entrada de um evento concentram a espera numa única catraca quando o público não vê, a tempo, qual acesso está mais livre. Este trabalho descreve o Leite de Pedra, um sistema ubíquo que trata a ocupação das filas como contexto e o ingresso facial como uma decisão separada. Sensores de entrada e de saída publicam movimentos; um processador estima a espera, classifica cada fila num semáforo e recomenda o desvio só quando outra fila está em estado melhor. Na catraca, o aplicativo móvel lê o código do ingresso e o rosto; o reconhecimento ocorre num serviço de nuvem, mas a autorização do validador e a validade do ingresso são decididas pelo processador, com o resultado gravado no mesmo banco temporal que guarda a telemetria. A comunicação entre os componentes de borda usa MQTT sobre TLS, com uma identidade e uma lista de permissões por papel. A avaliação possível nesta versão é a suíte automatizada dos módulos de contrato, persistência, regras de ingresso, autorização e falha do processador, sem teste de um APK, sem ensaio de carga e sem medição de energia. O texto registra o que essa suíte cobre, o que a execução de 25 de novembro de 2026 observou e os limites que o grupo não mediu.

**Palavras-chave:** sistemas ubíquos; contexto; MQTT; banco temporal; reconhecimento facial.

## 1. Introdução

Numa entrada com duas filas, a pessoa que chega escolhe pelo que vê naquele instante: o comprimento aparente da fila, não o tempo que ainda vai esperar. Se a catraca de uma delas atende mais devagar, o comprimento engana, e o pico seguinte reforça a fila que já está pior. O problema tratado aqui é fazer essa escolha com o estado recente das duas filas e, no momento da passagem, impedir que um ingresso válido seja usado por outra pessoa ou por um validador sem permissão.

O cenário pede mais de um produtor de eventos. O primeiro é o par de sensores de cada fila, que só informa que alguém entrou ou saiu. O segundo é a catraca, que informa uma tentativa de acesso com ingresso e rosto. Quem decide não é quem mediu. Um processador único mantém o saldo, calcula a espera e publica o semáforo; o mesmo processo aplica as regras do ingresso. A resposta volta por dois caminhos: o estado retido para quem sinaliza a fila, e o resultado da leitura para o aplicativo que está na catraca.

A mudança de contexto é a troca de semáforo e, com ela, da fila recomendada. A recomendação não segue a ocupação bruta. Dez pessoas numa fila rápida podem esperar menos do que três numa fila parada. Por isso os limiares estão em segundos de espera estimada: até 15 s a fila fica livre, entre 15 s e 30 s em atenção, acima de 30 s bloqueada. Enquanto não há vazão medida, a espera usa 7 s por pessoa, para que a fila reaja ao crescimento antes da primeira saída. Depois, a espera é a ocupação dividida pela vazão observada nas saídas recentes, no espírito de L = λW, com o cuidado de não misturar o tempo em que a fila estava vazia.

Há três restrições que organizam o desenho. A foto não circula no barramento dos sensores: só uma referência sai do backend, e o banco não guarda biometria. Cada componente entra com identidade própria; publicar estado ou resultado é privilégio do processador. E a decisão precisa sobreviver ao reinício de quem calculou, senão a ocupação volta a zero no meio do evento e o semáforo mente.

O restante do artigo apresenta a fundamentação, a arquitetura, a implementação, a forma de avaliação e o que foi possível observar em 25 de novembro de 2026. Não há, nesta versão, pacote Android instalável nem ensaio com público. Essas ausências estão declaradas na discussão e em `entregas/Marco4/pendencias.md`.

## 2. Fundamentação e trabalhos relacionados

Weiser descreveu a computação ubíqua como tecnologia que se mistura ao ambiente em vez de exigir que a pessoa opere um computador dedicado [1]. No Leite de Pedra, a pessoa que chega não configura nada: olha o sinal da fila, ou a tela do ingresso, e segue. A operação explícita fica com quem já tem papel no evento, o cliente que comprou o ingresso e o validador na catraca.

Dey define contexto como qualquer informação que caracteriza a situação de uma entidade [2]. A entidade aqui é a fila. O contexto usado na decisão é a ocupação (entradas menos saídas), a vazão recente das saídas, a idade do último heartbeat e o semáforo anterior, necessário para a histerese. Uma mudança de contexto é uma mudança nessa situação que altera a recomendação publicada. Abowd e Dey separam a aquisição do contexto do seu uso [3]. Este projeto segue essa separação: os sensores e a catraca adquirem; só o processador usa.

A estimativa de espera apoia-se na relação de Little, L = λW, em que a quantidade média no sistema é o produto da taxa de chegada pelo tempo médio de permanência [4]. Na implementação, a taxa usada não é a de chegada e sim a de atendimento inferida pelos sensores de saída, e só nos intervalos em que havia alguém na fila. Sem esse corte, o tempo ocioso entra na média e a espera fica maior do que a fila realmente impõe. Antes de duas passagens na janela de 90 s, não há taxa confiável, e o sistema usa a constante inicial em vez de publicar uma espera indefinida que congelaria o semáforo.

O transporte dos eventos de borda é MQTT 3.1.1, um protocolo de publicação e assinatura pensado para dispositivos com pouca folga de rede [5]. QoS 1 admite reentrega. O contrato trata isso com `event_id`: a mesma mensagem, com o mesmo instante, não altera o saldo. O estado da fila é publicado com retenção, para que o consumidor recupere o último semáforo ao reconectar. A leitura facial não usa retenção: ela é uma operação com prazo (`validoAte`), não um valor que deva sobreviver para um assinante tardio.

O canal exige TLS 1.2 ou superior e validação do certificado do serviço pela CA do projeto [6]. A autenticação dos serviços no broker é por usuário e senha; a autorização é uma ACL por papel, aplicação do menor privilégio [7]. O aplicativo não fala MQTT. Ele fala com o backend por HTTPS, com sessão JWT de 8 h [8] e senha armazenada com scrypt [9]. Credencial administrativa, chave de nuvem e senha de banco não entram no aplicativo.

A biometria segue o princípio de privacidade desde a concepção: coletar o mínimo, limitar o uso e apagar o que não precisa permanecer [10]. A foto do cadastro vira um rosto na coleção do Rekognition. A foto da catraca vai para um bucket privado, só como objeto daquela leitura. Se a entrada é aceita, o backend apaga o objeto na hora. Recusa, falha de reconhecimento ou ausência de resposta ficam até um dia, para o administrador revisar, e o acesso à imagem gera registro de auditoria. O barramento e o banco temporal recebem a decisão, não a imagem.

O histórico é uma série de eventos com instante. Um banco relacional comum guardaria as linhas, mas a consulta por janela de tempo e o agregado por minuto são o uso previsto do painel. O TimescaleDB organiza `movimentos` e `estados` como hypertables particionadas pelo tempo e mantém agregados contínuos por minuto [11]. A publicação do resultado da catraca usa o padrão de caixa de saída transacional: a decisão e a mensagem a publicar entram na mesma transação, e a mensagem só sai da fila pendente quando o broker confirma [12]. Assim um processo que cai depois de gravar não perde a resposta, e um processo que cai antes de gravar não confirma o evento ao broker.

O reconhecimento em si é um serviço externo, `SearchFacesByImage`, com limiar de semelhança de 95% [13]. O artigo não avalia a taxa de erro desse serviço. O processador trata três respostas já classificadas pelo backend: rosto reconhecido, rosto não reconhecido e falha técnica. A decisão de deixar entrar continua local, sobre ingresso, papel e prazo.

## 3. Proposta e arquitetura

O sistema tem dois produtores, um decisor e mais de um atuador. O produtor de presença é o firmware dos sensores, um ESP32 simulado com um HC-SR04 na entrada e outro na saída de cada fila demonstrada (`fila-a` e `fila-b`). Ele publica `contagem`, `saida` e `heartbeat`. O produtor da catraca é o backend, que só publica depois que o aplicativo do validador envia ingresso, fila e foto. O processador assina os dois fluxos. Ele publica `estado` e `recomendacao` para a sinalização, e `resultado` para a catraca. O consumidor de sinalização é outro ESP32, com LCD e LEDs, porque o simulador usado não coloca dois microcontroladores no mesmo circuito. Os dois firmwares se encontram no broker, não por fio.

O aplicativo participa dos dois lados do fluxo humano. Quem chega autentica, compra o ingresso e vê, na tela do código, a fila recomendada e o semáforo de cada acesso, atualizados a cada 3 s. Quem valida autentica com outro papel, lê o código, captura o rosto e recebe aceito, recusado ou indeterminado. Carregamento, falha de rede e texto da operação são estados da interface. O painel web de administração não substitui esse aplicativo: ele consulta histórico e altera papel e cancelamento, sempre com a conta de admin conferida no banco a cada pedido.

A distribuição segue a regra de uma única autoridade. Sensor não escolhe semáforo. Backend não marca ingresso como usado. Observabilidade lê e não grava. O banco separa os papéis por coluna: o processador atualiza saldo e decisão; o backend cria cliente e ingresso, sem poder escolher o papel da conta; o painel muda papel, cancela ingresso disponível e escreve auditoria; o observador só lê. O superusuário do banco não entra pela rede.

A justificativa para não fundir reconhecimento e ocupação é de significado, não de tecnologia. Uma pessoa recusada, ou que desiste, continua na fila até passar pelo sensor de saída. Se a ocupação dependesse da face aceita, a fila aparente diminuiria sem ninguém ter saído, e a recomendação mandaria mais gente para um corredor ainda cheio. O rosto decide quem passa na catraca. O sensor decide quantos estão no corredor.

O diagrama de implantação e o contrato do envelope (`event_id`, `correlation_id`, `event_type`, `source`, `timestamp` e `payload`) estão em `docs/ARQUITETURA.md` e no README. Toda mensagem que não casa tópico, tipo e identificador da fila é descartada e, no processador, contabilizada em `sistema/processador/rejeitado`, sem derrubar o processo.

## 4. Implementação

### 4.1 Contexto e histerese

A ocupação de uma fila é o máximo entre zero e a diferença entre entradas e saídas aceitas. A vazão usa só as saídas dentro de 90 s. Um intervalo entre duas saídas só entra na média se, na saída anterior, ainda havia gente na fila. A espera é zero com ocupação zero; é ocupação vezes 7 s enquanto a vazão não existe; é infinita se já houve saídas no passado e a janela atual não tem nenhuma, o que fecha a fila quando a entrada para. Com vazão positiva, a espera é ocupação dividida pela vazão.

A classificação não usa só o limiar de subida. Para descer de bloqueada a atenção, a espera precisa cair a 23 s; para descer a livre, a 8 s. A margem de 7 s evita que duas filas parecidas troquem de cor a cada evento. O desvio também é conservador: a fila de destino precisa estar num nível estritamente melhor. Entre destinos melhores, escolhe-se a menor espera. Fila sem heartbeat recebido nos últimos 15 s, medidos no relógio monotônico do processador, deixa de ser atualizada e deixa de ser destino. O relógio do simulador não serve para essa validade, porque pode andar mais devagar que o relógio da máquina.

O estado só é republicado quando o tuplo (semáforo, ocupação, destino, espera) muda, com QoS 1 e retenção. A recomendação leva o mesmo `correlation_id` do evento que provocou o recálculo e um texto de motivo, para que a sinalização e o painel expliquem o desvio em vez de mostrar só a cor.

### 4.2 Catraca

O backend recebe a foto, consulta a coleção e publica a leitura com o reconhecimento já rotulado, o identificador do validador, o ingresso, a referência da foto e o prazo `validoAte`. O processador, na mesma transação, confere se o validador tem o papel certo, se o reconhecimento permite seguir, se o usuário reconhecido é o dono e se o ingresso não foi usado nem cancelado. Aceite marca o uso. Recusa informa o motivo: validador não autorizado, rosto que não confere, ingresso inexistente, cancelado ou já usado. Falha de reconhecimento resulta em indeterminado, e o ingresso continua válido. Leitura incompleta não gera resultado de catraca; gera rejeição sem devolver a referência da foto.

Se o processador não responde em 10 s, o backend grava indeterminado com motivo `sem-resposta-processador` e devolve HTTP 504. O aplicativo mostra essa falha na tela de captura. Quando o processador volta, a leitura atrasada ou já foi decidida por essa gravação, ou passou de `validoAte` e é descartada como expirada. Nos dois casos o ingresso não é gasto. Uma reentrega com o mesmo `event_id` devolve a decisão já gravada.

### 4.3 Persistência

`movimentos` e `estados` são hypertables pelo instante do evento. A chave `(evento_id, tipo, momento)` absorve a reentrega. Usuários, ingressos, auditoria e a caixa de saída ficam no mesmo servidor, com permissões diferentes. O volume Docker `banco_dados` preserva as linhas depois que o contêiner do banco e o processo do processador sobem de novo. Os testes usam o banco `filas_teste`, com o mesmo esquema, e não apagam o banco `filas` do evento.

### 4.4 Aplicativo

O cliente móvel é um aplicativo Expo em TypeScript. A câmera frontal cadastra o rosto; a câmera traseira, na catraca, lê o código e o rosto de quem entra. O token fica no armazenamento seguro do aparelho. A sessão restaura ao abrir. Pedido sem rede produz a mensagem de falta de conexão; pedido em curso mostra carregamento; a catraca só troca para a tela de resultado quando o backend devolve a decisão. Não há, nesta árvore, o pacote APK. A execução documentada é Expo Go ou simulador, com `EXPO_PUBLIC_API_URL` em HTTPS e a CA do projeto instalada no aparelho. O atalho sem TLS existe no código e está excluído da demonstração do canal protegido.

### 4.5 Identidade inválida

Um terceiro firmware, o intruso, usa a CA pública e uma senha que não é a do produtor. O broker recusa a conexão. Nenhuma contagem desse firmware chega ao processador. O script `broker/testar-acl.py` cobre o outro lado da autorização: o processador recebe um heartbeat de teste; o produtor, que não tem permissão de leitura, não recebe.

## 5. Metodologia de avaliação

A avaliação desta versão é a execução dos testes automatizados já existentes no repositório, mais a inspeção do código e da documentação de implantação. Não foi escrito teste para o APK, porque o pacote não existe. Não foi medido consumo de energia, latência sob carga nem taxa de erro do reconhecimento com um conjunto de rostos reais. O ensaio ponta a ponta `tests/e2e_completo.py` depende das duas simulações Wokwi, da porta serial e da conta AWS; não entrou na execução registrada em 25 de novembro de 2026.

O comando da suíte, a partir da raiz, é:

`python -m unittest discover -s tests`

No Windows, com o ambiente virtual do projeto: `.venv\Scripts\python.exe -m unittest discover -s tests`. O banco `filas_teste` precisa estar acessível em `127.0.0.1:5433`, com TLS e a senha do papel `processador` fora do Git. O Rekognition e o MQTT reais são substituídos por dobras nessa suíte, exceto no ponto em que `test_apresentacao.py` executa o código do processador sobre o banco de teste. A ACL do broker é um comando à parte, `python broker/testar-acl.py`, com o Mosquitto no ar.

Cada módulo abaixo está ligado ao requisito que as asserções exercitam. A saída integral da execução fica em `entregas/Marco4/evidencias/`.

| Módulo | Requisito | O que as asserções cobrem |
|---|---|---|
| `tests/test_contrato.py` | Contrato e validação | Aceita o envelope coerente com o tópico; descarta fila trocada, tipo trocado, raiz desconhecida, status em nome de outro, campo inválido e payload que não é JSON. Não abre o banco. |
| `tests/test_estado_filas.py` | Persistência | Grava a entrada, ignora a reentrega, fecha o motor, abre de novo e ainda lê a ocupação; aplica a saída e o resultado. |
| `tests/test_heartbeat.py` | Contexto, tempo, regra com estado e falha | Heartbeat com relógio antigo do sensor ainda libera o estado; regras de aceite, reuso, rosto, ingresso inexistente, falha de reconhecimento e validador sem papel; caixa de saída até o PUBACK; duplicata; 504 que não gasta o ingresso; leitura expirada e mensagem fora do contrato. |
| `tests/test_backend.py` | Fluxo do app, autenticação, autorização e contexto | Cadastro, senha errada (401), cliente barrado na catraca (403), leitura publicada no contrato, foto apagada só no aceite, 504 sem marcar o ingresso, e a fila recomendada quando uma está bloqueada, quando as duas estão livres e quando uma está sem enlace. |
| `tests/test_admin.py` | Autorização administrativa | Painel recusa anônimo e cliente; admin rebaixado perde o acesso com o token antigo; cancelamento e auditoria seguem o papel `painel`. |
| `tests/test_apresentacao.py` | Falha e recuperação | Com o processador no ar, o dono entra e o ingresso fica usado; com o processador fora, a resposta é 504 e, na volta, uma nova leitura aceita. |
| `broker/testar-acl.py` | Autorização no canal | Leitor autorizado recebe; produtor não lê o tópico de telemetria. Exige o broker. |
| `tests/e2e_completo.py` | Fluxo com os dois simuladores | Roteiro manual automatizado, fora da suíte `discover` e fora desta execução. |

Verificações manuais de interface e do APK não fazem parte deste registro. A apresentação gravada está em https://drive.google.com/file/d/1IyoW87-bQh-Tf3qgKNgGXRloHaFUiPyJ/view?usp=sharing.

## 6. Resultados e discussão

Em 25 de novembro de 2026 a suíte rodou no Windows, com Python 3.12.6 e o TimescaleDB 2.17.2 em `127.0.0.1:5433`. Só o serviço de banco estava no ar. O comando foi `.venv\Scripts\python.exe -m unittest discover -s tests -v`, e o `discover` encontrou 8 testes.

A primeira passagem falhou em dois: `test_fluxo_do_app` e `test_processador_fora_nao_gasta_o_ingresso`, ambos com `permission denied for table movimentos` no papel `backend`. O arquivo `banco/ingressos.sql` já concede a esse papel `SELECT` e `INSERT` em `movimentos`, justamente para gravar o indeterminado quando o processador não responde. O volume local era anterior a essa concessão. Foi aplicado `GRANT SELECT, INSERT ON movimentos TO backend` só em `filas_teste`, o banco que a suíte usa. O banco `filas` da demonstração não foi alterado. Não houve alteração de código. Se o volume de `filas` também for anterior a essa linha de `ingressos.sql`, o caminho do HTTP 504 pode falhar do mesmo jeito até o grupo aplicar a concessão.

A segunda passagem está em `entregas/Marco4/evidencias/unittest-2026-11-25.txt`. O rodapé é `Ran 8 tests in 7.420s` e `OK`. Passaram o painel de admin, o processador no ar, o processador fora do ar, o fluxo do aplicativo, a fila recomendada, o contrato, a persistência depois de fechar a conexão e as regras de heartbeat, ingresso e prazo. O log ainda mostra um fio do cliente MQTT com `Invalid host`, porque o broker não estava ligado, e avisos de socket deixado aberto. Nenhum dos dois fez uma asserção falhar. `broker/testar-acl.py` e `tests/e2e_completo.py` não entraram nesta execução.

O contrato, isolado de rede e de banco, aceita só a mensagem cujo tópico, tipo e identificadores combinam. Isso sustenta a regra de desconfiar do que chega: um produtor não escreve status em nome do backend, e um JSON quebrado não derruba o leitor. É um teste unitário do parser, não uma prova de que o broker impõe a mesma regra. A imposição no canal continua sendo a ACL e o TLS, descritos na arquitetura e cobertos pelo script do broker quando o Mosquitto está no ar.

A persistência é o requisito com critério mais direto. O teste grava um movimento, descarta a repetição, destrói o motor de conexão e constrói outro sobre o mesmo `filas_teste`. A ocupação que o segundo motor lê é a que o primeiro gravou. Isso é o análogo, no banco de teste, de reiniciar o processador sem zerar a fila. Não substitui um desligamento físico do contêiner durante um evento com o banco `filas`, mas é a evidência automatizada pedida para gravação, recuperação e preservação.

As regras da catraca, no teste do processador, percorrem a ordem implementada: papel do validador, reconhecimento, posse do ingresso e uso único. A segunda apresentação do mesmo ingresso aceito volta como já usado. O validador que na verdade é o cliente recebe recusa, mesmo com o rosto do dono. A falha de reconhecimento não marca o ingresso. O caso do processador atrasado grava indeterminado e, passado o prazo, não decide mais aquela leitura. O teste de apresentação repete a ideia com o backend e o processador no mesmo processo de teste: a primeira leitura com o decisor “fora” não queima o código; a seguinte, com o decisor no ar, aceita.

A fila recomendada, no backend, prefere o melhor semáforo e, no empate, a menor espera, e ignora fila com enlace inativo. É a mudança de contexto vista por quem chega, sem depender do ESP32 naquela asserção: o teste injeta o estado que a observabilidade devolveria.

O que essa suíte não mostra é tão objetivo quanto o que ela mostra. Ela não instala um APK, não abre a câmera, não mede miliwatts, não satura o broker e não estima falso aceite do Rekognition. Os sensores da demonstração são o simulador Wokwi; o horário deles não é o horário em que a pessoa passou, e a distância do HC-SR04 é um clique, não um corpo. O volume do banco não é cifrado em repouso. Existe um interruptor de desenvolvimento que desliga o TLS do backend; deixá-lo ligado anula a verificação de canal protegido, ainda que o MQTT e o banco continuem em TLS. A conectividade degradada está especificada (sem heartbeat a fila sai do conjunto de destinos; sem resposta em 10 s a catraca não gasta o ingresso), mas não foi ensaiada numa rede com perda controlada. Esses limites estão reunidos em `entregas/Marco4/limitacoes.md`.

## 7. Conclusão

O Leite de Pedra separa contar pessoas de autorizar a passagem. Dois produtores alimentam um processador, que responde com semáforo e com o resultado do ingresso. A espera, e não o comprimento da fila, é o contexto que muda a recomendação, com histerese para não oscilar. O banco temporal guarda o saldo e o histórico depois que o processo que calculou termina. Identidade, permissão e canal cifrado estão no broker, no banco e no HTTPS do aplicativo, desde que a demonstração não use o atalho sem TLS.

A evidência automatizada disponível cobre contrato, persistência, regras com estado e prazo, autorização das APIs e a falha em que o processador não responde. Não cobre o pacote Android, o ensaio completo com os dois simuladores e as grandezas de desempenho e energia. A apresentação gravada está em https://drive.google.com/file/d/1IyoW87-bQh-Tf3qgKNgGXRloHaFUiPyJ/view?usp=sharing. O que a suíte não mede continua listado fora do artigo, para não ser confundido com resultado medido.

## Referências

[1] WEISER, M. The Computer for the 21st Century. Scientific American, v. 265, n. 3, p. 94–104, 1991.

[2] DEY, A. K. Understanding and Using Context. Personal and Ubiquitous Computing, v. 5, n. 1, p. 4–7, 2001.

[3] ABOWD, G. D. et al. Towards a Better Understanding of Context and Context-Awareness. In: International Symposium on Handheld and Ubiquitous Computing, 1999.

[4] LITTLE, J. D. C. A Proof for the Queuing Formula: L = λW. Operations Research, v. 9, n. 3, p. 383–387, 1961.

[5] BANKS, A.; GUPTA, R. (ed.). MQTT Version 3.1.1. OASIS Standard, 29 out. 2014.

[6] DIERKS, T.; RESCORLA, E. The Transport Layer Security (TLS) Protocol Version 1.2. RFC 5246, ago. 2008.

[7] SALTZER, J. H.; SCHROEDER, M. D. The Protection of Information in Computer Systems. Proceedings of the IEEE, v. 63, n. 9, p. 1278–1308, 1975.

[8] JONES, M.; BRADLEY, J.; SAKIMURA, N. JSON Web Token (JWT). RFC 7519, maio 2015.

[9] PERCIVAL, C.; JOSEFSSON, S. The scrypt Password-Based Key Derivation Function. RFC 7914, ago. 2016.

[10] CAVOUKIAN, A. Privacy by Design: The 7 Foundational Principles. Information and Privacy Commissioner of Ontario, 2011.

[11] TIMESCALE. TimescaleDB documentation: hypertables and continuous aggregates. Disponível em: https://docs.timescale.com/. Acesso em: 25 nov. 2026.

[12] RICHARDSON, C. Microservices Patterns. Manning, 2018. Padrão transactional outbox.

[13] AMAZON WEB SERVICES. Amazon Rekognition Developer Guide: searching for faces in a collection. Disponível em: https://docs.aws.amazon.com/rekognition/. Acesso em: 25 nov. 2026.
