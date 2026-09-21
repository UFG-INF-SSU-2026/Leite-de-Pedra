# Leite de Pedra — Sistema Inteligente de Gerenciamento de Filas

Projeto da disciplina **INF0483 — Software para Sistemas Ubíquos** (UFG, 2026/2), com o Prof. Dr. Otávio Calaça Xavier.
Repositório: `UFG-INF-SSU-2026/Leite-de-Pedra`

## Sobre o projeto

O Leite de Pedra é um sistema inteligente de gerenciamento de filas para eventos com múltiplas entradas (shows, jogos, eventos com ingresso). Sua ação central é o **balanceamento inteligente de fluxo de fila**: em eventos com múltiplas filas, o público não tem como saber qual fila está com melhor fluxo. Sem essa orientação, a tendência natural é se juntar à fila mais cheia — a mais visível, a mais próxima, a que "parece" a principal —, mesmo quando existe capacidade livre em outro ponto de entrada a poucos metros dali. O resultado é o clássico desbalanceamento: uma baia/catraca congestionada e outra praticamente vazia, sem que ninguém tenha como perceber isso de dentro da fila.

O sistema resolve isso sensoriando cada fila continuamente, estimando em tempo real quanto tempo de espera cada uma representa, e sinalizando visualmente (painel de LED/semáforo) para qual fila o público deve se direcionar — sem exigir nenhuma decisão ou esforço extra de quem está entrando.

O projeto se apoia nas cinco bases de um sistema ubíquo trabalhadas na Aula 1 da disciplina:

- **Distribuição** — não existe um único ponto central de controle: cada fila tem seu próprio ponto de sensoriamento, coordenados por uma névoa local do evento.
- **Contexto** — a recomendação não é uma regra fixa; ela muda de acordo com a situação real de cada fila naquele momento.
- **Adaptação** — o sistema reage sozinho a mudanças de fluxo, recalculando a recomendação sem intervenção manual.
- **Heterogeneidade** — dispositivos diferentes (pontos de validação, painéis de LED, broker MQTT) precisam interoperar através de um contrato de eventos comum.
- **Integração** — sensoriamento, decisão e atuação formam um ciclo fechado e contínuo, sem depender de um operador humano decidindo manualmente.

**Importante:** o sistema é puramente recomendador. Ele nunca aciona catracas ou qualquer mecanismo físico de forma autônoma — a decisão final continua sendo humana/mecânica.

## Equipe — grupo "Leite de Pedra"

João Victor Braga Queiroz (201810114), Caio Castro Miranda (202302600), Jaime da Cruz Silva Júnior (202302611), João Pedro de Brito Tomé (202302612).

## Estado atual

Marco 1 (protótipos individuais) e Marco 2 (integração executável produtor → comunicação → consumidor via MQTT, com uma condição de falha tratada) já foram concluídos e entregues.

As definições técnicas — contrato de eventos, arquitetura de sensoriamento, regra de decisão, como rodar cada demonstração — ficam documentadas dentro da pasta de cada atividade/marco, não neste README. Ao final do projeto, este documento será retrabalhado para refletir a versão consolidada.

## Estrutura do repositório

```
/atividade-01.md
/atividade-02.md
/Marco1/
  CaioCastro/
  JaimeCruz/
  JoaoPedro/
  JoaoVictor/
/Marco2/
  produtor.py
  consumidor.py
  observador.py
  mosquitto.conf
  README.md
  roteiro-demo.html
```
