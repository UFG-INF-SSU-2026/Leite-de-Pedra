# Balanceamento de filas de entrada com decisão na catraca por reconhecimento facial

Caio Castro Miranda, Jaime da Cruz Silva Júnior, João Pedro de Brito Tomé e João Victor Braga Queiroz

Instituto de Informática, Universidade Federal de Goiás  
INF0483 — Software para Sistemas Ubíquos — Prof. Dr. Otávio Calaça Xavier  
Goiânia, novembro de 2026

## Resumo

Filas de entrada de um evento concentram a espera numa única catraca quando o público não vê, a tempo, qual acesso está mais livre. Este trabalho descreve um sistema ubíquo que trata a ocupação das filas como contexto e o ingresso facial como uma decisão separada. Sensores de entrada e de saída publicam movimentos; um processador estima a espera, classifica cada fila num semáforo e recomenda o desvio só quando outra fila está em estado melhor. Na catraca, o aplicativo móvel lê o código do ingresso e o rosto; o reconhecimento ocorre num serviço de nuvem, mas a autorização do validador e a validade do ingresso são decididas pelo processador, com o resultado gravado no mesmo banco temporal que guarda a telemetria. A comunicação entre os componentes de borda usa MQTT sobre TLS, com uma identidade e uma lista de permissões por papel. A avaliação desta versão combina a suíte automatizada, com 119 testes de contrato, persistência, regras de ingresso, autorização, segurança e falha do processador, e um ensaio ponta a ponta com os dois simuladores e o serviço de nuvem, sem teste de um pacote instalável, sem ensaio de carga e sem medição de energia. O texto registra o que esses ensaios cobrem, o que as execuções registradas observaram e os limites que o time não mediu.

**Palavras-chave:** sistemas ubíquos; contexto; MQTT; banco temporal; reconhecimento facial.

## Abstract

Entrance queues at an event concentrate waiting at a single turnstile when the audience cannot see, in time, which access is moving faster. This paper describes a ubiquitous system that treats queue occupancy as context and facial ticket validation as a separate decision. Entry and exit sensors publish movements; a processor estimates waiting time, classifies each queue on a traffic-light scale and recommends a detour only when another queue is in a strictly better state. At the turnstile, the mobile application reads the ticket code and the face; recognition runs on a cloud service, but validator authorisation and ticket validity are decided by the processor, and the outcome is written to the same time-series database that stores telemetry. Edge components communicate over MQTT with TLS, each with its own identity and a per-role permission list. The evaluation of this version combines the automated suite, with 119 tests covering contract, persistence, ticket rules, authorisation, security and processor failure, and an end-to-end trial with both simulators and the cloud service, with no installable package test, no load trial and no energy measurement. The text records what these trials cover, what the recorded runs observed and the limits the team did not measure.

**Keywords:** ubiquitous systems; context; MQTT; time-series database; facial recognition.

## 1 Introdução

Todo evento com ingresso tem hora para começar, e é a hora marcada que concentra a chegada. Num jogo às 16 h, quem chega às 15 h encontra a entrada vazia e passa por qualquer catraca. A partir das 15h40 o fluxo cresce de uma vez, e é nesse intervalo que as filas se formam. O problema não é a capacidade instalada — um estádio ou uma casa de show costuma ter quatro ou mais catracas, hoje quase sempre com reconhecimento facial —, é a distribuição do público entre elas durante os vinte minutos de pico.

A motivação deste trabalho vem da observação dessa operação. Quem chega escolhe a catraca pelo que vê: o tamanho aparente da fila. O critério é ruim porque as catracas não atendem no mesmo ritmo. A primeira do corredor, por ficar no caminho natural de quem entra, recebe mais gente do que as do fim, e uma fila curta diante de uma catraca lenta pode custar mais tempo do que uma fila longa diante de uma rápida. Se o público enxergasse qual acesso está escoando melhor, o pico se dissolveria mais rápido, e o ganho não seria apenas de tempo médio, mas da experiência de quem comprou o ingresso.

A forma de mostrar isso precisa ser lida sem esforço, porque ninguém para diante da entrada de um show para interpretar um painel. Por isso a sinalização usa um código que o público já domina, o semáforo: verde é siga, amarelo é atenção, vermelho é procure outro acesso. A pessoa não configura nada, não abre um aplicativo para ser direcionada e não troca de fila por instrução de operador — olha a cor e segue. Com a validação pelo rosto, desaparece também o gesto de apresentar o código: ela chega, encara a catraca e entra. É o sentido da tecnologia que se mistura ao ambiente descrita por Weiser [1], traduzido aqui como o menor esforço mecânico e de atenção exigido de quem entra.

Numa entrada com duas filas, a pessoa que chega escolhe pelo que vê naquele instante: o comprimento aparente da fila, não o tempo que ainda vai esperar. Se a catraca de uma delas atende mais devagar, o comprimento engana, e o pico seguinte reforça a fila que já está pior. O problema tratado aqui é fazer essa escolha com o estado recente das duas filas e, no momento da passagem, impedir que um ingresso válido seja usado por outra pessoa ou por um validador sem permissão.

O cenário pede mais de um produtor de eventos. O primeiro é o par de sensores de cada fila, que só informa que alguém entrou ou saiu. O segundo é a catraca, que informa uma tentativa de acesso com ingresso e rosto. Quem decide não é quem mediu. Um processador único mantém o saldo, calcula a espera e publica o semáforo; o mesmo processo aplica as regras do ingresso. A resposta volta por dois caminhos: o estado retido para quem sinaliza a fila, e o resultado da leitura para o aplicativo que está na catraca.

A mudança de contexto é a troca de semáforo e, com ela, da fila recomendada. A recomendação não segue a ocupação bruta. Dez pessoas numa fila rápida podem esperar menos do que três numa fila parada. Por isso os limiares estão em segundos de espera estimada: até 15 s a fila fica livre, entre 15 s e 30 s em atenção, acima de 30 s bloqueada. Enquanto não há vazão medida, a espera usa 7 s por pessoa, para que a fila reaja ao crescimento antes da primeira saída. Depois, a espera é a ocupação dividida pela vazão observada nas saídas recentes, no espírito de L = λW, com o cuidado de não misturar o tempo em que a fila estava vazia.

Há três restrições que organizam o desenho. A foto não circula no barramento dos sensores: só uma referência sai do backend, e o banco não guarda biometria. Cada componente entra com identidade própria; publicar estado ou resultado é privilégio do processador. E a decisão precisa sobreviver ao reinício de quem calculou, senão a ocupação volta a zero no meio do evento e o semáforo mente.

A demonstração descrita aqui usa duas filas, por limite de montagem, mas a regra de decisão não depende desse número. Cada fila é avaliada contra as demais e o destino recomendado é a de menor espera entre as que estão em estado estritamente melhor, o que vale igualmente para quatro ou seis acessos.

O restante do artigo apresenta a fundamentação, a arquitetura, a implementação, a forma de avaliação e o que foi possível observar nas execuções registradas dos testes. O pacote Android foi gerado pelo EAS a partir da configuração de build do repositório, com o download indicado no README, mas não é exercitado por teste automatizado, e não houve ensaio com público. Essas ausências estão declaradas na discussão.

## 2 Fundamentação e trabalhos relacionados

Weiser descreveu a computação ubíqua como tecnologia que se mistura ao ambiente em vez de exigir que a pessoa opere um computador dedicado [1]. Aqui, a pessoa que chega não configura nada: olha o sinal da fila, ou a tela do ingresso, e segue. A operação explícita fica com quem já tem papel no evento, o cliente que comprou o ingresso e o validador na catraca.

Dey define contexto como qualquer informação que caracteriza a situação de uma entidade [2]. A entidade aqui é a fila. O contexto usado na decisão é a ocupação (entradas menos saídas), a vazão recente das saídas, a idade do último heartbeat e o semáforo anterior, necessário para a histerese. Uma mudança de contexto é uma mudança nessa situação que altera a recomendação publicada. Abowd e Dey separam a aquisição do contexto do seu uso [3]. Este projeto segue essa separação: os sensores e a catraca adquirem; só o processador usa.

A estimativa de espera apoia-se na relação de Little, L = λW, em que a quantidade média no sistema é o produto da taxa de chegada pelo tempo médio de permanência [4]. Na implementação, a taxa usada não é a de chegada e sim a de atendimento inferida pelos sensores de saída, e só nos intervalos em que havia alguém na fila. Sem esse corte, o tempo ocioso entra na média e a espera fica maior do que a fila realmente impõe. Antes de duas passagens na janela de 90 s, não há taxa confiável, e o sistema usa a constante inicial em vez de publicar uma espera indefinida que congelaria o semáforo.

O transporte dos eventos de borda é MQTT 3.1.1, um protocolo de publicação e assinatura pensado para dispositivos com pouca folga de rede [5]. QoS 1 admite reentrega. O contrato trata isso com event_id: a mesma mensagem, com o mesmo instante, não altera o saldo. O estado da fila é publicado com retenção, para que o consumidor recupere o último semáforo ao reconectar. A leitura facial não usa retenção: ela é uma operação com prazo (validoAte), não um valor que deva sobreviver para um assinante tardio.

O canal exige TLS 1.2 ou superior e validação do certificado do serviço pela autoridade certificadora do projeto [6]. A autenticação dos serviços no broker é por usuário e senha; a autorização é uma lista de controle de acesso por papel, aplicação do menor privilégio [7]. O aplicativo não fala MQTT. Ele fala com o backend por HTTPS, com sessão JWT de 8 h [8] e senha armazenada com scrypt [9]. O login tem limite de tentativas por conta e por endereço, com resposta HTTP 429, e os acessos recusados ficam registrados para auditoria. Credencial administrativa, chave de nuvem e senha de banco não entram no aplicativo.

A biometria segue o princípio de privacidade desde a concepção: coletar o mínimo, limitar o uso e apagar o que não precisa permanecer [10]. A foto do cadastro vira um rosto na coleção do Rekognition. A foto da catraca vai para um bucket privado, só como objeto daquela leitura. Se a entrada é aceita, o backend apaga o objeto na hora. Recusa, falha de reconhecimento ou ausência de resposta ficam até um dia, para o administrador revisar, e o acesso à imagem gera registro de auditoria. O barramento e o banco temporal recebem a decisão, não a imagem.

O histórico é uma série de eventos com instante. Um banco relacional comum guardaria as linhas, mas a consulta por janela de tempo e o agregado por minuto são o uso previsto do painel. O TimescaleDB organiza movimentos e estados como hypertables particionadas pelo tempo e mantém agregados contínuos por minuto [11]. A publicação do resultado da catraca usa o padrão de caixa de saída transacional: a decisão e a mensagem a publicar entram na mesma transação, e a mensagem só sai da fila pendente quando o broker confirma [12]. Assim um processo que cai depois de gravar não perde a resposta, e um processo que cai antes de gravar não confirma o evento ao broker.

O reconhecimento em si é um serviço externo, o Amazon Rekognition, consultado por SearchFacesByImage com limiar de semelhança de 95% [13]. O artigo não avalia a taxa de erro desse serviço. O processador trata três respostas já classificadas pelo backend: rosto reconhecido, rosto não reconhecido e falha técnica. A decisão de deixar entrar continua local, sobre ingresso, papel e prazo.

## 3 Proposta e arquitetura

O sistema tem dois produtores, um decisor e mais de um atuador. O produtor de presença é o firmware dos sensores, um ESP32 simulado com um HC-SR04 na entrada e outro na saída de cada fila demonstrada (fila-a e fila-b). Ele publica contagem, saída e heartbeat. O produtor da catraca é o backend, que só publica depois que o aplicativo do validador envia ingresso, fila e foto. O processador assina os dois fluxos. Ele publica estado e recomendação para a sinalização, e resultado para a catraca. O consumidor de sinalização é outro ESP32, com LCD e LEDs, porque o simulador usado não coloca dois microcontroladores no mesmo circuito. Os dois firmwares se encontram no broker, não por fio.

A atuação do sistema é apenas de recomendação. O vermelho do semáforo significa fila não recomendada, e não acesso fechado: a catraca continua operando, e quem já está naquela fila não é impedido de seguir nela. O sistema não aciona, não trava e não libera catraca. Quem decide a passagem é a validação do ingresso e do rosto; quem decide a fila continua sendo a pessoa.

O aplicativo participa dos dois lados do fluxo humano. Quem chega autentica, compra o ingresso e vê, na tela do código, a fila recomendada e o semáforo de cada acesso, atualizados a cada 3 s. Quem valida autentica com outro papel, lê o código, captura o rosto e recebe aceito, recusado ou indeterminado. Carregamento, falha de rede e texto da operação são estados da interface. O painel web de administração não substitui esse aplicativo: ele consulta histórico e altera papel e cancelamento, sempre com a conta de administrador conferida no banco a cada pedido.

A distribuição segue a regra de uma única autoridade. Sensor não escolhe semáforo. Backend não marca ingresso como usado. Observabilidade lê e não grava. O banco separa os papéis por coluna: o processador atualiza saldo e decisão; o backend cria cliente e ingresso, sem poder escolher o papel da conta; o painel muda papel, cancela ingresso disponível e escreve auditoria; o observador só lê. O superusuário do banco não entra pela rede.

A justificativa para não fundir reconhecimento e ocupação é de significado, não de tecnologia. Uma pessoa recusada, ou que desiste, continua na fila até passar pelo sensor de saída. Se a ocupação dependesse da face aceita, a fila aparente diminuiria sem ninguém ter saído, e a recomendação mandaria mais gente para um corredor ainda cheio. O rosto decide quem passa na catraca. O sensor decide quantos estão no corredor.

O diagrama de implantação e o contrato do envelope (event_id, correlation_id, event_type, source, timestamp e payload) acompanham a documentação de arquitetura do repositório. Toda mensagem que não casa tópico, tipo e identificador da fila é descartada e, no processador, contabilizada num tópico de rejeição, sem derrubar o processo.

## 4 Implementação

### 4.1 Contexto e histerese

A ocupação de uma fila é o máximo entre zero e a diferença entre entradas e saídas aceitas. A vazão usa só as saídas dentro de 90 s. Um intervalo entre duas saídas só entra na média se, na saída anterior, ainda havia gente na fila. A espera é zero com ocupação zero; é ocupação vezes 7 s enquanto a vazão não existe; é infinita se já houve saídas no passado e a janela atual não tem nenhuma, o que fecha a fila quando a entrada para. Com vazão positiva, a espera é ocupação dividida pela vazão.

A classificação não usa só o limiar de subida. Para descer de bloqueada a atenção, a espera precisa cair a 23 s; para descer a livre, a 8 s. A margem de 7 s evita que duas filas parecidas troquem de cor a cada evento. O desvio também é conservador: a fila de destino precisa estar num nível estritamente melhor. Entre destinos melhores, escolhe-se a menor espera. Fila sem heartbeat recebido nos últimos 15 s, medidos no relógio monotônico do processador, deixa de ser atualizada e deixa de ser destino. O relógio do simulador não serve para essa validade, porque pode andar mais devagar que o relógio da máquina. Pelo mesmo motivo, cada saída entra na vazão com a hora em que o processador a recebe, e saídas que chegam a menos de 1 s uma da outra, acumuladas pelo broker durante uma queda, não contam como atendimento.

O estado só é republicado quando o tuplo (semáforo, ocupação, destino, espera) muda, com QoS 1 e retenção. A recomendação leva o mesmo correlation_id do evento que provocou o recálculo e um texto de motivo, para que a sinalização e o painel expliquem o desvio em vez de mostrar só a cor.

### 4.2 Catraca

O backend recebe a foto, consulta a coleção e publica a leitura com o reconhecimento já rotulado, o identificador do validador, o ingresso, a referência da foto e o prazo validoAte. O processador, na mesma transação, confere se o validador tem o papel certo, se o reconhecimento permite seguir, se o usuário reconhecido é o dono e se o ingresso não foi usado nem cancelado. Aceite marca o uso. Recusa informa o motivo: validador não autorizado, rosto que não confere, ingresso inexistente, cancelado ou já usado. Falha de reconhecimento resulta em indeterminado, e o ingresso continua válido. Leitura incompleta não gera resultado de catraca; gera rejeição sem devolver a referência da foto.

Se o processador não responde em 10 s, o backend grava indeterminado com motivo de ausência de resposta e devolve HTTP 504. O aplicativo mostra essa falha na tela de captura. Quando o processador volta, a leitura atrasada ou já foi decidida por essa gravação, ou passou de validoAte e é descartada como expirada. Nos dois casos o ingresso não é gasto. Uma reentrega com o mesmo event_id devolve a decisão já gravada.

### 4.3 Persistência

Movimentos e estados são hypertables pelo instante do evento. A chave (evento, tipo, momento) absorve a reentrega. Usuários, ingressos, auditoria e a caixa de saída ficam no mesmo servidor, com permissões diferentes. O volume de dados do contêiner preserva as linhas depois que o banco e o processo do processador sobem de novo. Os testes usam um banco separado, com o mesmo esquema, e não apagam o banco do evento.

### 4.4 Aplicativo

O cliente móvel é um aplicativo Expo em TypeScript. A câmera frontal cadastra o rosto; a câmera traseira, na catraca, lê o código e o rosto de quem entra. O token fica no armazenamento seguro do aparelho. A sessão restaura ao abrir. Pedido sem rede produz a mensagem de falta de conexão; pedido em curso mostra carregamento; a catraca só troca para a tela de resultado quando o backend devolve a decisão. O pacote Android foi gerado pelo serviço de build do Expo, com o download indicado no README do repositório, num perfil de distribuição interna que fixa a URL da API em HTTPS, hoje o endereço de uma máquina da rede local, e embute a autoridade certificadora do projeto por um plugin de configuração, de modo que o aparelho confia no backend sem instalação manual do certificado. A execução também pode ser feita por Expo Go ou simulador, apontando a mesma URL. O atalho sem TLS existe no código e está excluído da demonstração do canal protegido.

### 4.5 Identidade inválida

Um terceiro firmware, o intruso, conhece o certificado da autoridade certificadora do projeto, que é público, mas usa uma senha que não é a do produtor. O broker recusa a conexão. Nenhuma contagem desse firmware chega ao processador. Um script de teste de lista de controle de acesso cobre o outro lado da autorização: o processador recebe um heartbeat de teste; o produtor, que não tem permissão de leitura, não recebe.

## 5 Metodologia de avaliação

A avaliação desta versão é a execução dos testes automatizados do repositório e do ensaio ponta a ponta, mais a inspeção do código e da documentação de implantação. Não foi escrito teste automatizado para o pacote Android; a suíte cobre apenas os serviços. Não foi medido consumo de energia, latência sob carga nem taxa de erro do reconhecimento com um conjunto de rostos reais. O ensaio ponta a ponta depende das duas simulações Wokwi, da porta serial e da conta AWS, e roda à parte da suíte, com a saída guardada nas evidências do repositório.

A suíte é executada a partir da raiz do repositório com python -m unittest discover -s tests. O banco de teste precisa estar acessível com TLS, e a senha do papel do processador fica fora do controle de versão. O Rekognition e o MQTT reais são substituídos por dobras nessa suíte, exceto no ponto em que o teste de apresentação executa o código do processador sobre o banco de teste. A lista de controle de acesso do broker é um comando à parte, que exige o Mosquitto no ar.

O Quadro 1 liga cada módulo ao requisito que as suas asserções exercitam.

**Quadro 1 — Módulos de teste e requisitos exercitados**

| Módulo | Requisito | O que as asserções cobrem |
|----|----|----|
| Contrato | Contrato e validação | Aceita o envelope coerente com o tópico; descarta fila trocada, tipo trocado, raiz desconhecida, status em nome de outro, campo inválido e payload que não é JSON. Não abre o banco. |
| Estado das filas | Persistência | Grava a entrada, ignora a reentrega, fecha o motor, abre de novo e ainda lê a ocupação; aplica a saída e o resultado. |
| Heartbeat | Contexto, tempo, regra com estado e falha | Heartbeat com relógio antigo do sensor ainda libera o estado; regras de aceite, reuso, rosto, ingresso inexistente, falha de reconhecimento e validador sem papel; caixa de saída até o PUBACK; duplicata; 504 que não gasta o ingresso; leitura expirada e mensagem fora do contrato. |
| Backend | Fluxo do aplicativo, autenticação, autorização e contexto | Cadastro, senha errada (401), cliente barrado na catraca (403), leitura publicada no contrato, foto apagada só no aceite, 504 sem marcar o ingresso, e a fila recomendada quando uma está bloqueada, quando as duas estão livres e quando uma está sem enlace. |
| Painel administrativo | Autorização administrativa | Painel recusa anônimo e cliente; administrador rebaixado perde o acesso com o token antigo; cancelamento e auditoria seguem o papel do painel. |
| Apresentação | Falha e recuperação | Com o processador no ar, o dono entra e o ingresso fica usado; com o processador fora, a resposta é 504 e, na volta, uma nova leitura é aceita. |
| Unitários e segurança | Funções isoladas, login e auditoria | Funções de senhas, contrato, modelos, estado das filas, backend, observabilidade e processador, sem banco e sem broker, incluindo a rajada de saídas depois de uma queda; limite de tentativas de login, registro de acessos recusados, recusas do broker e métricas. |
| ACL do broker | Autorização no canal | Leitor autorizado recebe; produtor não lê o tópico de telemetria. Exige o broker no ar; executado em 25 e 26/11. |
| Ensaio ponta a ponta | Fluxo com os dois simuladores | Roteiro automatizado, fora da suíte: lota a fila-a até desviar, passa clientes na catraca, repete o 504 e esvazia as filas. Passou nos dez passos em 26/11. |

Fonte: elaborado pelos autores.

Verificações manuais de interface, do vídeo e do APK não fazem parte deste registro.

## 6 Resultados e discussão

Na primeira execução registrada, em 25 de novembro, a suíte rodou com apenas o serviço de banco no ar, e o descobridor encontrou oito testes. A primeira passagem falhou em dois casos, ambos por falta de permissão de escrita do papel do backend sobre a tabela de movimentos — a concessão prevista no esquema não estava aplicada no volume local usado. A correção foi conceder essa permissão no banco de teste, sem alterar código nem o banco da demonstração. Na segunda passagem os oito testes passaram: painel de administração, processador no ar, processador fora do ar, fluxo do aplicativo, fila recomendada, contrato, persistência depois de fechar a conexão e regras de heartbeat, ingresso e prazo. O log ainda mostra um cliente MQTT sem host, porque o broker não estava ligado, e avisos de socket deixado aberto; nenhum dos dois fez uma asserção falhar. Em 26 de novembro, com os testes unitários e os de segurança acrescentados, a suíte chegou a 119 testes, todos aprovados. O script da lista de controle de acesso foi corrigido: o leitor e o publicador usavam o mesmo usuário, o broker derrubava o leitor e o teste passava mesmo com a regra errada; corrigido, ele falha quando a lista é liberada de propósito e passa com a do projeto.

O ensaio ponta a ponta rodou no mesmo dia, com os dois simuladores e o Rekognition. A primeira execução falhou no passo da reação da catraca: o consumidor tinha sessão persistente e assinava o estado com QoS 1, e o broker guardou, enquanto ele estava desligado, mudanças de estado de horas antes, que atrasaram o resultado. Descartada a sessão guardada, a segunda execução passou nos dez passos: lotou a fila-a até desviar para a fila-b, passou clientes na catraca das duas filas, conferiu a reação do consumidor, repetiu o 504 com o processador parado e esvaziou as filas. Para o problema não voltar, a assinatura do estado passou a QoS 0, já que o estado é retido e só o último importa, e o ESP32 dos sensores ganhou o mesmo keepalive de 60 s do consumidor; essas duas mudanças ainda não passaram por uma nova execução do ensaio.

O contrato, isolado de rede e de banco, aceita só a mensagem cujo tópico, tipo e identificadores combinam. Isso sustenta a regra de desconfiar do que chega: um produtor não escreve status em nome do backend, e um JSON quebrado não derruba o leitor. É um teste unitário do analisador sintático, não uma prova de que o broker impõe a mesma regra. A imposição no canal continua sendo a lista de controle de acesso e o TLS, descritos na arquitetura e cobertos pelo script do broker quando o Mosquitto está no ar.

A persistência é o requisito com critério mais direto. O teste grava um movimento, descarta a repetição, destrói o motor de conexão e constrói outro sobre o mesmo banco. A ocupação que o segundo motor lê é a que o primeiro gravou. Isso é o análogo, no banco de teste, de reiniciar o processador sem zerar a fila. Não substitui um desligamento físico do contêiner durante um evento, mas é a evidência automatizada pedida para gravação, recuperação e preservação.

As regras da catraca, no teste do processador, percorrem a ordem implementada: papel do validador, reconhecimento, posse do ingresso e uso único. A segunda apresentação do mesmo ingresso aceito volta como já usado. O validador que na verdade é o cliente recebe recusa, mesmo com o rosto do dono. A falha de reconhecimento não marca o ingresso. O caso do processador atrasado grava indeterminado e, passado o prazo, não decide mais aquela leitura. O teste de apresentação repete a ideia com o backend e o processador no mesmo processo de teste: a primeira leitura com o decisor fora não queima o código; a seguinte, com o decisor no ar, aceita.

A fila recomendada, no backend, prefere o melhor semáforo e, no empate, a menor espera, e ignora fila com enlace inativo. É a mudança de contexto vista por quem chega, sem depender do ESP32 naquela asserção: o teste injeta o estado que a observabilidade devolveria.

O que essa suíte não mostra é tão objetivo quanto o que ela mostra. Ela não instala um APK, não abre a câmera, não mede miliwatts, não satura o broker e não estima falso aceite do Rekognition. Os sensores da demonstração são o simulador; o horário deles não é o horário em que a pessoa passou, e a distância do HC-SR04 é um clique, não um corpo. O volume do banco não é cifrado em repouso. Existe um interruptor de desenvolvimento que desliga o TLS do backend; deixá-lo ligado anula a verificação de canal protegido, ainda que o MQTT e o banco continuem em TLS. A conectividade degradada está especificada (sem heartbeat a fila sai do conjunto de destinos; sem resposta em 10 s a catraca não gasta o ingresso), mas não foi ensaiada numa rede com perda controlada.

## 7 Conclusão

O sistema separa contar pessoas de autorizar a passagem. Dois produtores alimentam um processador, que responde com semáforo e com o resultado do ingresso. A espera, e não o comprimento da fila, é o contexto que muda a recomendação, com histerese para não oscilar. O banco temporal guarda o saldo e o histórico depois que o processo que calculou termina. Identidade, permissão e canal cifrado estão no broker, no banco e no HTTPS do aplicativo, desde que a demonstração não use o atalho sem TLS.

A evidência registrada cobre contrato, persistência, regras com estado e prazo, autorização das interfaces de programação, limite de tentativas de login e a falha em que o processador não responde, na suíte e no ensaio ponta a ponta com os dois simuladores. Não exercita o APK nem o vídeo de demonstração, que existem mas não são verificados por teste automatizado, e não mede as grandezas de desempenho e energia. Esses limites ficam registrados no repositório, nas limitações e pendências do marco, para não serem confundidos com resultado medido.

## Áreas de atuação no projeto

O trabalho foi conduzido pelos quatro autores, distribuído em quatro frentes ao longo do projeto: problema e arquitetura; funcionamento do sistema; aplicativo e persistência; testes, segurança e recuperação de falha. A concepção do problema, as decisões de projeto e a redação final foram discutidas e aprovadas em conjunto.

## Declaração de uso de ferramentas de inteligência artificial

Ferramentas de inteligência artificial foram usadas como apoio de redação e revisão do texto e na geração de trechos de código, posteriormente revisados e testados pelos autores. A concepção do problema, as decisões de arquitetura, a implementação, a execução dos testes e a interpretação dos resultados são de responsabilidade dos autores.

## Referências

[1] WEISER, M. The computer for the 21st century. Scientific American, New York, v. 265, n. 3, p. 94-104, 1991.

[2] DEY, A. K. Understanding and using context. Personal and Ubiquitous Computing, London, v. 5, n. 1, p. 4-7, 2001.

[3] ABOWD, G. D. et al. Towards a better understanding of context and context-awareness. In: INTERNATIONAL SYMPOSIUM ON HANDHELD AND UBIQUITOUS COMPUTING, 1., 1999, Karlsruhe. Proceedings [...]. Berlin: Springer, 1999. p. 304-307.

[4] LITTLE, J. D. C. A proof for the queuing formula: L = λW. Operations Research, Catonsville, v. 9, n. 3, p. 383-387, 1961.

[5] BANKS, A.; GUPTA, R. (ed.). MQTT version 3.1.1. Burlington: OASIS, 2014. OASIS Standard.

[6] DIERKS, T.; RESCORLA, E. The transport layer security (TLS) protocol version 1.2. [S. l.]: IETF, 2008. RFC 5246.

[7] SALTZER, J. H.; SCHROEDER, M. D. The protection of information in computer systems. Proceedings of the IEEE, New York, v. 63, n. 9, p. 1278-1308, 1975.

[8] JONES, M.; BRADLEY, J.; SAKIMURA, N. JSON web token (JWT). [S. l.]: IETF, 2015. RFC 7519.

[9] PERCIVAL, C.; JOSEFSSON, S. The scrypt password-based key derivation function. [S. l.]: IETF, 2016. RFC 7914.

[10] CAVOUKIAN, A. Privacy by design: the 7 foundational principles. Toronto: Information and Privacy Commissioner of Ontario, 2011.

[11] TIMESCALE. TimescaleDB documentation: hypertables and continuous aggregates. [S. l.], 2026. Disponível em: https://docs.timescale.com/. Acesso em: 25 nov. 2026.

[12] RICHARDSON, C. Microservices patterns. Shelter Island: Manning, 2018.

[13] AMAZON WEB SERVICES. Amazon Rekognition developer guide: searching for faces in a collection. [S. l.], 2026. Disponível em: https://docs.aws.amazon.com/rekognition/. Acesso em: 25 nov. 2026.
