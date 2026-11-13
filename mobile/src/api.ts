import Constants from 'expo-constants'

// Cliente do backend. Por ora sem TLS (backend com BACKEND_SEM_TLS=1): HTTP na
// máquina que serve o app pelo Expo, que é a mesma do backend; assim o celular
// na rede funciona sem configurar nada. EXPO_PUBLIC_API_URL troca o endereço
// (por exemplo, https://<ip>:8444 com o certificado do projeto: mobile/README.md).
const maquinaDoExpo = Constants.expoConfig?.hostUri?.split(':')[0] ?? 'localhost'
export const API_URL = process.env.EXPO_PUBLIC_API_URL ?? `http://${maquinaDoExpo}:8444`

export class ErroApi extends Error {
  status: number
  constructor(status: number, mensagem: string) {
    super(mensagem)
    this.status = status
  }
}

type Opcoes = { metodo?: 'GET' | 'POST'; corpo?: unknown; token?: string | null }

export async function chamar<T>(caminho: string, { metodo = 'GET', corpo, token }: Opcoes = {}): Promise<T> {
  const cabecalhos: Record<string, string> = {}
  if (token) cabecalhos.Authorization = `Bearer ${token}`
  if (corpo !== undefined) cabecalhos['Content-Type'] = 'application/json'
  let resposta: Response
  try {
    resposta = await fetch(API_URL + caminho, {
      method: metodo,
      headers: cabecalhos,
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    })
  } catch {
    throw new ErroApi(0, 'Sem conexão com o servidor. Confira a internet e tente de novo.')
  }
  const dados = await resposta.json().catch(() => ({}))
  if (!resposta.ok) {
    if (typeof dados.detail === 'string') throw new ErroApi(resposta.status, dados.detail)
    if (resposta.status === 422) throw new ErroApi(422, 'Confira os dados informados.')
    throw new ErroApi(resposta.status, `O servidor não respondeu (HTTP ${resposta.status}).`)
  }
  return dados as T
}

export type Papel = 'cliente' | 'validador' | 'admin'
export type Sessao = { token: string; papel: Papel }
export type Conta = { usuarioId: string; login: string; nome: string; papel: Papel }
export type Ingresso = { ingressoId: string; emitidoEm: string; usadoEm: string | null; filaEntrada: string | null }
export type Semaforo = 'livre' | 'atencao' | 'bloqueada'
export type FilaAgora = { filaId: string; semaforo: Semaforo; ocupacao: number; tempoEsperaEstimado: number | null }
export type Filas = { filas: FilaAgora[]; recomendada: string | null }

export const entrar = (login: string, senha: string) =>
  chamar<Sessao>('/sessoes', { metodo: 'POST', corpo: { login, senha } })

export const cadastrar = (dados: { login: string; senha: string; nome: string; foto: string }) =>
  chamar<{ usuarioId: string }>('/usuarios', { metodo: 'POST', corpo: dados })
