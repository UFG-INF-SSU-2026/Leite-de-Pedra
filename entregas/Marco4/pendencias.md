# O que ainda falta para o Marco 4

Fecha o que deu para fazer em 25 de novembro de 2026 sem APK e sem commit. O restante desta lista continua obrigatório no enunciado e não está no repositório.

## Feito nesta versão

- Suíte automatizada documentada, sem teste de APK: comando, módulos, as quatro verificações do enunciado e a saída obtida (`testes.md` e `evidencias/`).
- ACL do broker executada em 25/11: `evidencias/acl-2026-11-25.txt`.
- README da raiz deixa de se apresentar só como Marco 3 e aponta artigo, testes, limitações, uso de IA, pendências e APK ausente.
- Apresentação gravada no [Drive](https://drive.google.com/file/d/1IyoW87-bQh-Tf3qgKNgGXRloHaFUiPyJ/view?usp=sharing). O arquivo não entra no Git.
- `mobile/README.md` descreve o HTTPS com validação da CA como o modo que atende o canal protegido, e marca `BACKEND_SEM_TLS=1` como atalho que não atende.
- Artigo em PDF, com as seções pedidas, em `artigo.pdf` (fonte em `artigo.md`).
- Limitações de simulação, dados pessoais, segurança, conectividade, desempenho e energia em `limitacoes.md`.
- Declaração da assistência usada para redigir estes arquivos em `uso-de-ia.md`.

## Ainda falta

| Pendência | Por que não foi fechada agora | O que entregar |
|---|---|---|
| APK Android instalável | Não há `android/`, `eas.json` nem arquivo `.apk`. Expo Go não é o pacote do app. | Gerar o APK (por exemplo `npx expo run:android` ou um build de pré-visualização), colocá-lo no repositório e mostrar instalação em celular ou emulador, integrado ao backend em HTTPS. |
| Teste automatizado do APK | O enunciado desta tarefa pediu para não incluir teste do que não existe. | Se o grupo quiser teste do app depois do APK, isso é trabalho novo. A suíte atual continua válida para o servidor. |
| Contribuições dos outros três integrantes | `contribuicoes.md` tem só a de Caio Castro Miranda. | Cada um escreve a própria parte nesse arquivo. |
| Revisão do artigo pelo grupo | O PDF foi gerado a partir do código e da execução dos testes, com assistência registrada em `uso-de-ia.md`. | Reler, corrigir o que o grupo não assumir e conferir se o PDF ficou entre 10 e 15 páginas depois de qualquer edição. |
| Canal na demonstração | O código do app ainda usa HTTP quando `EXPO_PUBLIC_API_URL` não está definida (`mobile/src/api.ts`). A documentação já não recomenda esse modo. | Na gravação e na apresentação, backend sem `BACKEND_SEM_TLS` e app com `EXPO_PUBLIC_API_URL=https://...`. |
| ~~Evidência do `e2e_completo.py`~~ | Feito em 26/11: a segunda execução passou nos dez passos, com os dois simuladores e a AWS (`evidencias/e2e-2026-11-26-execucao2.txt`); a primeira falhou no passo 7 por mensagens antigas guardadas para o consumidor (`evidencias/e2e-2026-11-26.txt`). Detalhes em `testes.md`. | A assinatura de `estado` passou para QoS 0 no firmware do consumidor; falta validar numa nova execução do ponta a ponta. |
| Ensaio de desempenho e de energia | Não há medição. A declaração está em `limitacoes.md`; o enunciado pede declarar, não apresentar número que não foi medido. | Só incluir número novo se houver medição de verdade. |
| `GRANT` de `movimentos` para o papel `backend` no banco `filas` | `banco/ingressos.sql` já declara `GRANT SELECT, INSERT ON movimentos TO backend`. O volume de teste estava sem essa concessão e os dois testes do 504 falhavam. A concessão foi aplicada só em `filas_teste`. | Confirmar o mesmo `GRANT` no banco `filas` se o volume for antigo; sem ele, o HTTP 504 da catraca quebra em vez de gravar o indeterminado. |

A versão que define a nota do Marco 4 é a de 27/11. A de 11/12 entra no projeto final. O APK e as contribuições dos outros três integrantes são o que separa esta árvore do que o enunciado pede por completo. A apresentação está no [Drive](https://drive.google.com/file/d/1IyoW87-bQh-Tf3qgKNgGXRloHaFUiPyJ/view?usp=sharing).
