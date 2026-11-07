# App Leite de Pedra

App do usuário (Expo SDK 58, Expo Router, TypeScript): criar conta com a foto
do rosto, entrar, comprar ingressos e mostrar o QR do ingresso na catraca.

| Tela | Rota | O que faz |
|---|---|---|
| Entrar | `/entrar` | login e senha; o token fica no `expo-secure-store` |
| Criar conta | `/cadastro` | nome, login e senha, depois a foto do rosto pela câmera frontal (`POST /usuarios`) |
| Meus ingressos | `/ingressos` | ingressos para usar e já usados; comprar (`POST /ingressos`); puxe para atualizar |
| Ingresso | `/ingresso/[id]` | QR code com o código do ingresso, que o validador lê na catraca |

As rotas ficam em `src/app/`; o resto (API, sessão, componentes, câmera) em `src/`.

## Rodar

Precisa do backend no ar (`docker compose up -d` na raiz) e de Node 22.13 ou
superior.

```
npm install
npx expo start --ios        # simulador do iOS na mesma máquina do backend
```

O app fala com o backend por HTTPS em `EXPO_PUBLIC_API_URL` (padrão
`https://localhost:8444`), e o aparelho precisa confiar na CA do projeto:

- **Simulador do iOS:** `xcrun simctl keychain booted add-root-cert ../.local/mqtt/ca.crt`
  (uma vez por simulador).
- **Celular na mesma rede:** emita o certificado do backend com o IP da máquina
  (`backend/configurar-backend.sh <ip>`), publique o backend nesse IP, instale e
  marque como confiável a CA no aparelho e rode com
  `EXPO_PUBLIC_API_URL=https://<ip>:8444 npx expo start`.

Contas de teste: `python3 banco/seed.py` cria `cliente`, `validador` e `admin`,
todos com a senha `123`.

Antes de entregar: `npx tsc --noEmit` e `npx expo lint`.
