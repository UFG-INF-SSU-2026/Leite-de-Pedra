import { useCallback, useEffect, useState } from 'react'
import { chamar, consulta, type Pagina } from './api'

export const POR_PAGINA = 50

export function dataHora(valor: string | null | undefined) {
  if (!valor) return '–'
  return new Date(valor).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'medium' })
}

export function hora(valor: string | null | undefined) {
  return valor ? new Date(valor).toLocaleTimeString('pt-BR') : '–'
}

// Busca dados de uma rota e permite recarregar; `intervalo` em ms para atualizar sozinho.
export function useDados<T>(caminho: string, intervalo?: number) {
  const [dados, setDados] = useState<T | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const recarregar = useCallback(() => {
    chamar<T>(caminho).then(d => { setDados(d); setErro(null) }).catch(e => setErro(e.message))
  }, [caminho])
  useEffect(() => {
    recarregar()
    if (!intervalo) return
    const id = setInterval(recarregar, intervalo)
    return () => clearInterval(id)
  }, [recarregar, intervalo])
  return { dados, erro, recarregar }
}

// Lista paginada de uma rota /admin com filtros.
export function useLista<T>(rota: string, filtros: Record<string, string>) {
  const [deslocamento, setDeslocamento] = useState(0)
  const chave = JSON.stringify(filtros)
  useEffect(() => setDeslocamento(0), [chave])
  const caminho = rota + consulta({ ...filtros, limite: POR_PAGINA, deslocamento })
  return { ...useDados<Pagina<T>>(caminho), deslocamento, setDeslocamento }
}
