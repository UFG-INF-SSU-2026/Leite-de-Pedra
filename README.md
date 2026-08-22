# UNIVERSIDADE FEDERAL DE GOIÁS
## INSTITUTO DE INFORMÁTICA
### Software para Sistemas Ubíquos — Atividade em Grupo 01
**Prof. Dr. Otávio Calaça Xavier**

# Análise inicial de um sistema ubíquo

## Integrantes
- Caio Castro Miranda
- Jaime da Cruz Silva Júnior
- João Pedro de Brito Tomé
- João Victor Braga Queiroz

## Cenário escolhido
**Biblioteca Inteligente Ubíqua com RFID e recomendação contextual**

A proposta é uma biblioteca capaz de identificar livros e usuários, acompanhar a movimentação do acervo, auxiliar na localização de exemplares e detectar livros fora do lugar. Para isso, o sistema utiliza RFID/NFC, dispositivos conectados, processamento de contexto e uma aplicação web ou móvel.

---

# Parte 1 — Compreensão do problema

## 1. Problema e usuários

Bibliotecas universitárias podem ter dificuldade para localizar livros que aparecem como disponíveis, mas estão em outra estante, além de depender de processos manuais para acompanhar o acervo.

O sistema pretende reduzir esses problemas por meio da identificação automática dos livros e da atualização de sua localização aproximada.

### Usuários
- **Estudantes e professores:** pesquisam e localizam livros.
- **Bibliotecários:** acompanham o acervo e recebem alertas.
- **Administradores:** mantêm a infraestrutura do sistema.

### Situação de uso

O usuário pesquisa um livro e o sistema informa sua disponibilidade e localização. Caso o exemplar seja detectado em uma área diferente da cadastrada, o sistema atualiza a informação ou gera um alerta.

---

## 2. Contexto

O sistema precisa perceber:

### Usuário
- identificação;
- perfil ou curso, quando autorizado;
- livros pesquisados e empréstimos ativos.

### Ambiente
- setor em que o livro foi detectado;
- movimentação de exemplares;
- disponibilidade física dos livros.

### Sistema
- estado dos leitores RFID;
- conectividade;
- última localização registrada;
- situação de empréstimo.

Essas informações permitem que o sistema adapte sua resposta ao contexto.

---

## 3. Dispositivos e comunicação

### Dispositivos
- tags RFID nos livros;
- cartões RFID/NFC dos usuários;
- leitores RFID;
- ESP32 ou Raspberry Pi como gateway;
- servidor e banco de dados;
- aplicação web ou móvel.

### Como o sistema diferencia um livro de uma zona

O livro é identificado pela **tag RFID que ele carrega** (identidade fixa, gravada no cadastro). A zona **não possui tag** — ela é identificada indiretamente, pelo **leitor RFID fixo** instalado naquele setor, que possui um ID próprio associado a uma zona no cadastro do sistema.

Quando um leitor capta uma tag, o evento gerado é:

```text
Evento = { tag_id: "0xA1B2C3", leitor_id: "2", timestamp: ... }
```

O servidor cruza as duas informações:

```text
tag_id    → tabela de livros    → "qual livro é esse?"
leitor_id → tabela de leitores  → "em qual zona esse leitor está?"
```

E monta a informação completa: *"Livro X foi detectado pelo Leitor 2, que está no Setor B."* O sistema nunca "lê a zona" diretamente — ele infere a zona a partir de qual leitor fixo captou aquela tag. Isso também explica por que a granularidade é por **setor**, e não por posição exata.

### Comunicação

Os leitores enviam as identificações ao gateway, que encaminha os eventos ao servidor.

```text
Tag RFID
   ↓
Leitor RFID
   ↓
Gateway
   ↓
Wi-Fi / MQTT
   ↓
Servidor
   ↓
Banco de dados
   ↓
Aplicação
```

---

## 4. Processamento e resposta

O gateway pode filtrar leituras repetidas e armazenar eventos temporariamente em caso de perda de conexão.

O servidor realiza o processamento principal:

- verifica a situação do livro;
- atualiza sua localização;
- identifica inconsistências;
- gera recomendações e alertas.

### Exemplo de decisão

```text
SE localização_detectada != localização_cadastrada
E livro não está emprestado
ENTÃO gerar alerta de livro fora do lugar
```

As respostas podem ser exibidas no aplicativo, em um terminal ou por LEDs nas estantes.

---

## 5. Risco principal

### Confiabilidade da localização por RFID

Uma leitura RFID não representa necessariamente a posição exata do livro. Podem ocorrer falhas, interferências e leituras de tags próximas.

Quanto maior a precisão desejada, maior o número de leitores e o custo.

Por isso, a proposta inicial utiliza **localização por zonas ou setores**, em vez de tentar identificar a posição exata em cada prateleira.

### Mitigação de interferência entre RFIDs

A interferência é o principal fator que compromete a confiabilidade da leitura, e ocorre em três níveis diferentes:

**a) Interferência entre leitores (reader-to-reader)** — dois leitores próximos operam ao mesmo tempo e um atrapalha o sinal do outro.
- distanciamento físico entre leitores de setores diferentes;
- escalonamento no tempo (TDMA), ativando um leitor por vez em ciclos curtos;
- ajuste da potência de transmissão à área real de cada setor.

**b) Interferência entre tags (tag collision)** — várias tags respondem ao mesmo tempo a um leitor (comum em estantes cheias).
- uso do protocolo anti-colisão já embutido nos chips RFID (ex.: EPC Gen2, via *slotted ALOHA*);
- leitura sequencial/em lote, com pequenos atrasos entre ciclos.

**c) Leituras "vazadas" entre zonas** — um leitor capta a tag de um livro fisicamente localizado no setor vizinho. Esse é o caso mais crítico para a biblioteca.

| Estratégia | Como funciona |
|---|---|
| Antenas direcionais | Foco no padrão de irradiação, reduzindo alcance fora da zona |
| Blindagem física | Estantes metálicas ou barreiras de RF entre setores |
| Filtro por RSSI | Só considera válida a leitura acima de um limiar de intensidade de sinal |
| Debounce (confirmação por repetição) | Só atualiza a localização se a mesma tag for lida N vezes seguidas pelo mesmo leitor |
| Zonas de guarda (dead zones) | Pequeno espaço físico sem cobertura entre setores |

**Regra de decisão no servidor**, combinando as estratégias acima:

```text
SE tag lida por leitor_X
E confiança do sinal (RSSI) >= limiar
E leitura repetida >= 3 vezes em Y segundos
ENTÃO confirmar localização = zona do leitor_X
SENÃO ignorar leitura (ruído/interferência)
```

A escolha por **localização por zonas** já é, em si, uma estratégia de tolerância a esse tipo de ruído: como a granularidade exigida é menor (setor, não posição exata), o sistema é mais robusto a pequenas imprecisões de leitura.

---

# Parte 2 — Modelagem do sistema

## 6. Sensores, atuadores e gateway

### Sensores
- **Leitor RFID:** identifica livros e usuários.
- **Sensor de presença:** pode indicar movimentação em determinados setores.

### Atuadores
- LEDs nas estantes;
- alertas no aplicativo;
- displays ou notificações para bibliotecários.

### Gateway
O ESP32 ou Raspberry Pi recebe as leituras, filtra eventos e envia os dados ao servidor.

---

## 7. Fluxo do sistema

```text
Livro é movimentado
        ↓
Leitor RFID detecta a tag
        ↓
Gateway recebe a identificação
        ↓
Dados são enviados ao servidor
        ↓
Servidor compara a localização
        ↓
Sistema toma uma decisão
        ↓
Atualiza localização ou gera alerta
```

Fluxo geral:

```text
Fenômeno físico
→ Sensor
→ Comunicação/Gateway
→ Processamento
→ Decisão
→ Resposta/Atuador
```

---

## 8. Classificação

O sistema pode ser classificado como:

- **Rede de sensores**, pois utiliza leitores distribuídos no ambiente;
- **IoT**, pois dispositivos físicos enviam informações pela rede;
- **Sistema ciberfísico**, pois eventos físicos alteram o estado digital;
- **Aplicação ubíqua**, classificação principal, porque o sistema está integrado ao ambiente, percebe contexto e reage com pouca intervenção do usuário.

---

## 9. Contexto e adaptação

Um exemplo de adaptação ocorre quando um livro muda de setor.

```text
Local esperado: Setor B
Local detectado: Setor C
```

O sistema pode:

1. atualizar a localização estimada;
2. identificar a inconsistência;
3. avisar o bibliotecário;
4. passar a informar ao usuário a nova localização.

Outra adaptação ocorre em caso de perda de conexão: o gateway pode armazenar os eventos localmente e sincronizá-los quando a rede retornar.

---

# Diagrama resumido

```text
Livro/Cartão RFID
        ↓
   Leitor RFID
        ↓
 ESP32 / Gateway
        ↓
   Wi-Fi / MQTT
        ↓
     Servidor
        ↓
 Banco de dados
        ↓
Motor de contexto
        ↓
Aplicativo / Alertas / LEDs
```

---

# Decisão principal de projeto

A principal decisão é utilizar **localização por zonas da biblioteca**.

Essa escolha busca equilibrar:

- custo;
- precisão;
- confiabilidade;
- complexidade do protótipo.

Por exemplo:

```text
Setor A — Engenharia
Setor B — Computação
Setor C — Ciências Humanas
```

Cada setor pode possuir um leitor RFID responsável por identificar os livros presentes naquela região.

---

# Protótipo inicial

O protótipo pode utilizar:

- 1 a 3 ESP32;
- 2 ou 3 leitores RFID;
- tags e cartões RFID;
- LEDs;
- servidor com MQTT e banco de dados;
- aplicação web simples.

### Demonstração

1. O usuário pesquisa um livro.
2. O sistema informa em qual setor ele está.
3. Um LED indica a região.
4. O livro é movido para outro setor.
5. O sistema detecta a mudança.
6. A localização é atualizada ou um alerta é gerado.

---

# Conclusão

A proposta integra RFID, comunicação em rede e processamento de contexto para tornar a biblioteca capaz de perceber eventos e reagir a eles automaticamente.

A principal característica ubíqua está no fato de que o ambiente acompanha a movimentação dos livros e adapta as informações apresentadas aos usuários sem depender apenas de registros manuais.

O principal compromisso do projeto é equilibrar **precisão de localização, confiabilidade e custo**, razão pela qual a primeira versão utiliza localização por setores. As estratégias de mitigação de interferência (antenas direcionais, blindagem, filtro por RSSI, debounce e zonas de guarda) reforçam essa confiabilidade sem exigir aumento significativo de custo ou complexidade.
