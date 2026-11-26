# Declaração de uso de IA — redação do Marco 4

Registro do que foi feito com assistência de IA nos arquivos deste diretório. O grupo responde por ler, testar e explicar o material. Esta nota não substitui o que cada integrante tenha usado em outros momentos do projeto: isso precisa ser acrescentado por quem usou.

| Campo | Registro |
|---|---|
| Ferramenta | Cursor, modelo Grok 4.7 |
| Data | 25 de novembro de 2026 |
| Finalidade | Rascunhar o artigo a partir do código e da documentação já existentes; organizar o comando, a tabela de rastreio e o resultado dos testes automatizados; apontar o README para o Marco 4; corrigir o README do app para que o caminho documentado seja HTTPS. |
| Orientação seguida | Não inventar métricas, não criar teste de APK, não gerar o pacote Android, não commitar, e deixar por escrito o que ainda falta. |
| O que foi aproveitado | Estrutura do artigo (problema, fundamentação, arquitetura, implementação, avaliação, resultados, conclusão e referências), a tabela módulo–requisito em `testes.md`, `limitacoes.md`, `pendencias.md` e os parágrafos novos do README e de `mobile/README.md`. |
| O que foi modificado em relação a um texto genérico | Limiares, papéis, prazos e nomes de arquivo foram tirados do código (`processador/processador.py`, `banco/esquema.sql`, `tests/`). Referências só entram quando correspondem a obras conhecidas; não há número de acerto do reconhecimento nem tempo de resposta medido. |
| Validação | A saída dos testes em `evidencias/` é a saída do `unittest`, não um resumo escrito pelo modelo. O artigo descreve essa saída. O grupo ainda precisa reler o PDF, confirmar que consegue explicar arquitetura e contribuição, e repetir o comando dos testes antes da entrega. |

Contribuições individuais de implementação não estão nesta declaração. O que já foi registrado está em `contribuicoes.md`.
