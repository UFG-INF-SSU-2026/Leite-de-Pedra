# Contribuições individuais

As contribuições dos demais integrantes ainda não estão neste arquivo.

## Caio Castro Miranda — 202302600

Parte 3 — Gerenciamento inteligente das filas.

Cálculo da ocupação e do tempo de espera, classificação do estado das filas e recomendação automática de direcionamento.

O que mudou no Marco 4:

- Criação do endpoint `GET /filas` no backend.
- Nova lógica para escolher a melhor fila entre aquelas com enlace ativo, priorizando o melhor semáforo e, em caso de empate, o menor tempo de espera.
- Integração com o aplicativo: a tela do ingresso atualiza a recomendação a cada 3 segundos.
- Exibição da ocupação, do semáforo e do tempo estimado de espera de cada fila.
- Criação do teste `demo_lotacao.py` para demonstrar a mudança de recomendação em tempo real.

Principal contribuição: levar o gerenciamento das filas para o usuário, permitindo que ele saiba diretamente pelo celular qual fila deve escolher.
