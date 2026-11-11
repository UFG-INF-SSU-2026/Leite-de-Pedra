// Cliente da API de admin do backend. A SPA é servida pelo próprio backend
// (mesma origem), então as rotas são relativas e não há CORS.

const CHAVE_TOKEN = 'painel.token'
const CHAVE_PAPEL = 'painel.papel'

export class ErroApi extends Error {
  status: number
  constructor(status: number, mensagem: string) {
    super(mensagem)
    this.status = status
  }
}

// sessionStorage: o token some quando a aba fecha.
export const token = {
  ler: () => sessionStorage.getItem(CHAVE_TOKEN),
  salvar: (valor: string) => sessionStorage.setItem(CHAVE_TOKEN, valor),
  apagar: () => {
    sessionStorage.removeItem(CHAVE_TOKEN)
    sessionStorage.removeItem(CHAVE_PAPEL)
  },
  // Só escolhe a tela (painel ou catraca); quem confere o papel é o backend.
  papel: () => sessionStorage.getItem(CHAVE_PAPEL),
}

let aoPerderSessao = () => {}
export function quandoPerderSessao(funcao: () => void) {
  aoPerderSessao = funcao
}

export async function chamar<T>(caminho: string, opcoes: { metodo?: string; corpo?: unknown } = {}): Promise<T> {
  const cabecalhos: Record<string, string> = {}
  const atual = token.ler()
  if (atual) cabecalhos.Authorization = `Bearer ${atual}`
  if (opcoes.corpo !== undefined) cabecalhos['Content-Type'] = 'application/json'
  const resposta = await fetch(caminho, {
    method: opcoes.metodo ?? 'GET',
    headers: cabecalhos,
    body: opcoes.corpo === undefined ? undefined : JSON.stringify(opcoes.corpo),
  })
  const dados = await resposta.json().catch(() => ({}))
  if (!resposta.ok) {
    if (resposta.status === 401 || resposta.status === 403) {
      token.apagar()
      aoPerderSessao()
    }
    if (typeof dados.detail === 'string') throw new ErroApi(resposta.status, dados.detail)
    if (Array.isArray(dados.detail)) throw new ErroApi(resposta.status, 'Dados inválidos.')
    // Sem corpo da API: o backend não respondeu (fora do ar, ou o proxy do Vite não o alcançou).
    throw new ErroApi(resposta.status, `O backend não respondeu (HTTP ${resposta.status}). Confira se ele está rodando: python3 -m backend.`)
  }
  return dados as T
}

export async function entrar(login: string, senha: string) {
  const dados = await chamar<{ token: string; papel: string }>('/sessoes', { metodo: 'POST', corpo: { login, senha } })
  if (dados.papel !== 'admin' && dados.papel !== 'validador')
    throw new ErroApi(403, 'Esta conta não é de administrador nem de validador.')
  token.salvar(dados.token)
  sessionStorage.setItem(CHAVE_PAPEL, dados.papel)
}

export function consulta(parametros: Record<string, string | number | undefined>) {
  const pares = Object.entries(parametros).filter(([, valor]) => valor !== undefined && valor !== '')
  return pares.length ? '?' + new URLSearchParams(pares.map(([c, v]) => [c, String(v)])).toString() : ''
}

export type Pagina<T> = { total: number; itens: T[] }
export type Papel = 'cliente' | 'validador' | 'admin'

export type Usuario = { usuarioId: string; login: string; nome: string; papel: Papel; faceId: string; criadoEm: string }
export type Ingresso = {
  ingressoId: string; usuarioId: string; dono: string | null; situacao: 'disponivel' | 'usado' | 'cancelado'
  emitidoEm: string; usadoEm: string | null; filaEntrada: string | null; leituraId: string | null
  validadorId: string | null; canceladoEm: string | null
}
export type Movimento = {
  eventId: string; tipo: string; filaId: string; momento: string; recebidoEm: string
  resultado: string | null; motivo: string | null; ingressoId: string | null; validadorId: string | null
  correlationId: string | null; origem: string | null
}
export type EstadoRegistrado = { momento: string; filaId: string; semaforo: string; ocupacao: number; esperaSegundos: number | null }
export type RegistroAuditoria = { momento: string; admin: string; acao: string; alvo: string; detalhe: string | null }
export type Resumo = {
  saidaPendente: number
  usuarios: Record<Papel, number>
  ingressos: { emitidos: number; usados: number; cancelados: number; disponiveis: number }
  leituras: Record<'aceito' | 'recusado' | 'indeterminado', number>
  filas: { filaId: string; entradas: number; saidas: number; ocupacao: number }[]
}
export type FilaAoVivo = {
  filaId: string
  estado: { semaforo: string; ocupacao: number; sentidoRecomendado: string; tempoEsperaEstimado: number | null } | null
  recomendacao: { motivo?: string } | null
  ultimoResultado: { resultado: string; motivo?: string; ingressoId?: string; recebidoEm: string } | null
  ultimaReacao: { acao: string; resultado: string; recebidoEm: string } | null
  ultimaLeitura: { ingressoId?: string; reconhecimento?: string; recebidoEm: string } | null
  segundosSemHeartbeat: number | null
  enlaceAtivo: boolean
}
export type AoVivo = {
  brokerConectado: boolean
  filas: FilaAoVivo[]
  componentes: { source: string; online: boolean; atualizadoEm: string }[]
  rejeitadas: Record<string, number>
  mensagens: {
    recebidoEm: string; latenciaMs: number | null; filaId: string | null; tipo: string
    eventId: string; correlationId: string; source: string; payload: Record<string, unknown>
  }[]
}
export type MinutoHistorico = {
  minuto: string; filaId: string; entradas: number; saidas: number; aceitos: number; recusados: number
  indeterminados: number; esperaMedia: number | null; esperaMaxima: number | null; ocupacaoMaxima: number | null
}
