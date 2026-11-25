# App Leite de Pedra

App do usuário (Expo SDK 58, Expo Router, TypeScript): criar conta com a foto
do rosto, entrar, comprar ingressos e mostrar o QR do ingresso na catraca.

| Tela | Rota | O que faz |
|---|---|---|
| Entrar | `/entrar` | login e senha; o token fica no `expo-secure-store` |
| Criar conta | `/cadastro` | nome, login e senha, depois a foto do rosto pela câmera frontal (`POST /usuarios`) |
| Meus ingressos | `/ingressos` | ingressos para usar e já usados; comprar (`POST /ingressos`); puxe para atualizar |
| Ingresso | `/ingresso/[id]` | QR code com o código do ingresso e a fila recomendada, atualizada enquanto a tela está aberta |
| Catraca | `/catraca` | só o papel `validador`: lê o QR, captura o rosto e mostra o resultado da operação |

As rotas ficam em `src/app/`; o resto (API, sessão, componentes, câmera) em `src/`.

## Rodar

Precisa do backend no ar (`docker compose up -d` na raiz) e de Node 22.13 ou
superior. O caminho abaixo é o que atende o canal protegido: HTTPS, com o
celular conferindo a CA do projeto. Não há APK nesta entrega; o app sobe pelo
Expo Go ou por um simulador.

```
npm install
```

1. Apague `BACKEND_SEM_TLS` do `.env` da raiz, se existir, e reinicie o backend.
2. Emita o certificado com o IP da máquina: `backend/configurar-backend.sh <ip>`.
3. No `.env`, use `BACKEND_ENDERECO=0.0.0.0` para o celular na mesma rede.
4. Instale `.local/mqtt/ca.crt` no aparelho e marque a CA como confiável. No iPhone: perfil em Ajustes e confiança total em Ajustes > Geral > Sobre > Ajustes de Confiança de Certificados. No simulador do iOS: `xcrun simctl keychain booted add-root-cert ../.local/mqtt/ca.crt`.
5. Suba o app apontando para esse HTTPS:

```
EXPO_PUBLIC_API_URL=https://<ip-da-máquina>:8444 npx expo start
```

`npx expo start --ios` serve para o simulador na mesma máquina do backend, com a mesma URL HTTPS (ou `https://localhost:8444` se o certificado incluir `localhost`).

O atalho `BACKEND_SEM_TLS=1` sobe o backend em HTTP e faz o app usar `http://<ip>:8444` quando `EXPO_PUBLIC_API_URL` não está definida. Senhas, tokens e fotos seguem sem criptografia. Esse modo não atende a verificação de canal protegido do Marco 4 e deve ficar desligado na demonstração.

Contas de teste: `python3 banco/seed.py` cria `cliente`, `validador` e `admin`,
todos com a senha `123`.

Antes de entregar: `npx tsc --noEmit` e `npx expo lint`.
