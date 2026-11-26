# O que ainda falta para o Marco 4

O que segue em aberto está na tabela. O APK, o vídeo, o artigo revisado, o ensaio ponta a ponta e as quatro contribuições já estão registrados; o `.apk` e o vídeo ficam fora do Git.

## Feito nesta versão

- Suíte automatizada documentada, sem teste de APK: comando, módulos, as quatro verificações do enunciado e a saída obtida (`testes.md` e `evidencias/`).
- ACL do broker executada em 25/11: `evidencias/acl-2026-11-25.txt`.
- README da raiz deixa de se apresentar só como Marco 3 e aponta artigo, testes, limitações, uso de IA, pendências e o download do APK.
- Apresentação gravada no [Drive](https://drive.google.com/file/d/1IyoW87-bQh-Tf3qgKNgGXRloHaFUiPyJ/view?usp=sharing). O arquivo não entra no Git.
- `mobile/README.md` descreve o HTTPS com validação da CA como o modo que atende o canal protegido, e marca `BACKEND_SEM_TLS=1` como atalho que não atende.
- Artigo em PDF, com as seções pedidas, em `artigo.pdf`, exportado pelo Word a partir de `artigo.docx` (fonte); `artigo.md` traz o mesmo texto. `gerar_pdf.py` gera só uma versão sem capa, em `artigo-sem-capa.pdf`.
- Limitações de simulação, dados pessoais, segurança, conectividade, desempenho e energia em `limitacoes.md`.
- Declaração da assistência usada para redigir estes arquivos em `uso-de-ia.md`.

## Ainda falta

| Pendência | Por que não foi fechada agora | O que entregar |
|---|---|---|
| ~~APK Android instalável~~ | Feito em 26/11: build EAS (perfil `apk` de `mobile/eas.json`), com download e página do build linkados no `README.md` da raiz. Aponta para `https://192.168.3.3:8444` e confia na CA do projeto. O `.apk` (115 MB) não entra no Git por passar do limite do GitHub. | Falta mostrar a instalação em celular ou emulador, com o backend em HTTPS. |
| Teste automatizado do APK | O pacote existe e está linkado no README. A suíte não instala nem exercita esse arquivo. | A suíte atual continua válida para o servidor. Um teste do APK instalado seria trabalho novo. |
| ~~Contribuições dos quatro integrantes~~ | Feito: Caio Castro Miranda, João Pedro de Brito Tomé, João Victor Braga Queiroz e Jaime da Cruz estão em `contribuicoes.md`. | — |
| ~~Revisão do artigo pelo grupo~~ | Feito em 26/11: versão ABNT de 13 páginas, com a suíte de 119 testes, o ponta a ponta de 26/11, o APK e a correção da vazão. | Qualquer nova edição vai em `artigo.docx`, com o PDF exportado de novo e conferido entre 10 e 15 páginas. |
| Canal na demonstração | O código do app ainda usa HTTP quando `EXPO_PUBLIC_API_URL` não está definida (`mobile/src/api.ts`). A documentação já não recomenda esse modo. | Na gravação e na apresentação, backend sem `BACKEND_SEM_TLS` e app com `EXPO_PUBLIC_API_URL=https://...`. |
| ~~Evidência do `e2e_completo.py`~~ | Feito em 26/11: a segunda execução passou nos dez passos, com os dois simuladores e a AWS (`evidencias/e2e-2026-11-26-execucao2.txt`); a primeira falhou no passo 7 por mensagens antigas guardadas para o consumidor (`evidencias/e2e-2026-11-26.txt`). Detalhes em `testes.md`. | A assinatura de `estado` passou para QoS 0 no firmware do consumidor; falta validar numa nova execução do ponta a ponta. |
| Ensaio de desempenho e de energia | Não há medição. A declaração está em `limitacoes.md`; o enunciado pede declarar, não apresentar número que não foi medido. | Só incluir número novo se houver medição de verdade. |
| `GRANT` de `movimentos` para o papel `backend` no banco `filas` | `banco/ingressos.sql` já declara `GRANT SELECT, INSERT ON movimentos TO backend`. O volume de teste estava sem essa concessão e os dois testes do 504 falhavam. A concessão foi aplicada só em `filas_teste`. | Confirmar o mesmo `GRANT` no banco `filas` se o volume for antigo; sem ele, o HTTP 504 da catraca quebra em vez de gravar o indeterminado. |

A versão que define a nota do Marco 4 é a de 27/11. A de 11/12 entra no projeto final. O que ainda separa esta árvore do enunciado completo é mostrar o APK instalado num aparelho, com o backend em HTTPS. A apresentação está no [Drive](https://drive.google.com/file/d/1IyoW87-bQh-Tf3qgKNgGXRloHaFUiPyJ/view?usp=sharing).
