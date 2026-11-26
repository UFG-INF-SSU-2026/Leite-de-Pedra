import * as SecureStore from 'expo-secure-store'
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { chamar, entrar as entrarNaApi, ErroApi, type Papel, type Sessao } from './api'

// O token fica no armazenamento seguro do aparelho (Keychain / Keystore).
const CHAVE = 'sessao'

type ContextoSessao = {
  carregando: boolean
  sessao: Sessao | null
  entrar: (login: string, senha: string) => Promise<void>
  sair: () => Promise<void>
  // Chamada autenticada; um token recusado encerra a sessão.
  api: <T>(caminho: string, opcoes?: { metodo?: 'GET' | 'POST'; corpo?: unknown }) => Promise<T>
}

const Contexto = createContext<ContextoSessao | null>(null)

export function ProvedorSessao({ children }: { children: ReactNode }) {
  const [sessao, setSessao] = useState<Sessao | null>(null)
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    SecureStore.getItemAsync(CHAVE)
      .then(salva => salva && setSessao(JSON.parse(salva) as Sessao))
      .catch(() => {})
      .finally(() => setCarregando(false))
  }, [])

  const sair = useCallback(async () => {
    await SecureStore.deleteItemAsync(CHAVE)
    setSessao(null)
  }, [])

  const entrar = useCallback(async (login: string, senha: string) => {
    const nova = await entrarNaApi(login, senha)
    await SecureStore.setItemAsync(CHAVE, JSON.stringify(nova))
    setSessao(nova)
  }, [])

  const api = useCallback(async <T,>(caminho: string, opcoes: { metodo?: 'GET' | 'POST'; corpo?: unknown } = {}) => {
    try {
      return await chamar<T>(caminho, { ...opcoes, token: sessao?.token })
    } catch (erro) {
      if (erro instanceof ErroApi && erro.status === 401) await sair()
      throw erro
    }
  }, [sessao, sair])

  return <Contexto.Provider value={{ carregando, sessao, entrar, sair, api }}>{children}</Contexto.Provider>
}

export function useSessao() {
  const contexto = useContext(Contexto)
  if (!contexto) throw new Error('useSessao fora do ProvedorSessao')
  return contexto
}

export const ROTULO_PAPEL: Record<Papel, string> = { cliente: 'Cliente', validador: 'Validador', admin: 'Admin' }
