import { Redirect, useFocusEffect, useLocalSearchParams } from 'expo-router'
import { useCallback, useState } from 'react'
import { Text, View } from 'react-native'
import QRCode from 'react-native-qrcode-svg'
import type { Filas, Ingresso, Semaforo } from '@/api'
import { useSessao } from '@/sessao'
import { Erro, Paragrafo, Selo, Tela, useCores } from '@/ui'

const SEMAFORO: Record<Semaforo, { texto: string; cor: string }> = {
  livre: { texto: 'Livre', cor: '#1d9a52' },
  atencao: { texto: 'Atenção', cor: '#c98a00' },
  bloqueada: { texto: 'Lotada', cor: '#c4321f' },
}
const INTERVALO_FILAS_MS = 3000

function nomeDaFila(filaId: string) {
  return `Fila ${filaId.replace('fila-', '').toUpperCase()}`
}

// Em qual fila entrar: a recomendada pelo processador para quem está chegando,
// atualizada enquanto a tela está aberta.
function QualFila({ filas }: { filas: Filas }) {
  const cores = useCores()
  if (!filas.recomendada) return <Paragrafo>Sem dados das filas agora. Siga a sinalização do local.</Paragrafo>
  return (
    <View style={{ alignSelf: 'stretch', gap: 10, padding: 16, borderRadius: 16, backgroundColor: cores.superficie }}
      accessible accessibilityLabel={`Entre na ${nomeDaFila(filas.recomendada)}`}>
      <Text style={{ color: cores.suave, fontSize: 14 }}>Entre na</Text>
      <Text style={{ color: cores.texto, fontSize: 32, fontWeight: '800' }}>{nomeDaFila(filas.recomendada)}</Text>
      {filas.filas.map(f => (
        <View key={f.filaId} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <View style={{ width: 12, height: 12, borderRadius: 6, backgroundColor: SEMAFORO[f.semaforo].cor }} />
          <Text style={{ color: cores.texto, fontSize: 15, fontVariant: ['tabular-nums'] }}>
            {nomeDaFila(f.filaId)}: {SEMAFORO[f.semaforo].texto}, {f.ocupacao} pessoa(s)
            {f.tempoEsperaEstimado != null ? `, ~${f.tempoEsperaEstimado} s` : ''}
          </Text>
        </View>
      ))}
    </View>
  )
}

// O QR leva só o código do ingresso. Sozinho ele não abre a catraca: o
// processador também confere se o rosto lido é o do dono.
export default function TelaIngresso() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const { sessao, api } = useSessao()
  const cores = useCores()
  const [ingresso, setIngresso] = useState<Ingresso | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [filas, setFilas] = useState<Filas | null>(null)

  useFocusEffect(useCallback(() => {
    if (!sessao) return
    api<Ingresso[]>('/ingressos')
      .then(meus => {
        const encontrado = meus.find(i => i.ingressoId === id)
        setIngresso(encontrado ?? null)
        setErro(encontrado ? null : 'Este ingresso não está na sua conta.')
      })
      .catch(e => setErro((e as Error).message))
  }, [api, sessao, id]))

  // Enquanto a tela está aberta: as filas e o próprio ingresso, que vira "usado" ao passar na catraca.
  useFocusEffect(useCallback(() => {
    if (!sessao) return
    const atualizar = () => {
      api<Filas>('/filas').then(setFilas).catch(() => setFilas(null))
      api<Ingresso[]>('/ingressos').then(meus => setIngresso(meus.find(i => i.ingressoId === id) ?? null)).catch(() => {})
    }
    atualizar()
    const relogio = setInterval(atualizar, INTERVALO_FILAS_MS)
    return () => clearInterval(relogio)
  }, [api, sessao, id]))

  if (!sessao) return <Redirect href="/entrar" />

  const usado = Boolean(ingresso?.usadoEm)

  return (
    <Tela>
      <Erro mensagem={erro} />
      {ingresso && (
        <View style={{ alignItems: 'center', gap: 16, marginTop: 8 }}>
          <Selo texto={usado ? 'Já usado' : 'Válido para uma entrada'} ativo={!usado} />
          {!usado && filas && <QualFila filas={filas} />}
          <View style={{ padding: 20, borderRadius: 16, backgroundColor: '#ffffff', opacity: usado ? 0.35 : 1 }}
            accessible accessibilityLabel={`QR code do ingresso ${ingresso.ingressoId}`}>
            <QRCode value={ingresso.ingressoId} size={240} color="#000000" backgroundColor="#ffffff" ecl="M" />
          </View>
          <Text selectable style={{ color: cores.texto, fontSize: 24, fontWeight: '700', letterSpacing: 2, fontVariant: ['tabular-nums'] }}>
            {ingresso.ingressoId}
          </Text>
          <Paragrafo>
            {usado
              ? `Usado em ${new Date(ingresso.usadoEm!).toLocaleString('pt-BR')}${ingresso.filaEntrada ? ` na ${ingresso.filaEntrada}` : ''}.`
              : 'Na catraca, mostre este QR ao validador e olhe para a câmera. A entrada é liberada quando o rosto confere com o seu cadastro.'}
          </Paragrafo>
        </View>
      )}
    </Tela>
  )
}
