import { Redirect, useFocusEffect, useLocalSearchParams } from 'expo-router'
import { useCallback, useState } from 'react'
import { Text, View } from 'react-native'
import QRCode from 'react-native-qrcode-svg'
import type { Ingresso } from '@/api'
import { useSessao } from '@/sessao'
import { Erro, Paragrafo, Selo, Tela, useCores } from '@/ui'

// O QR leva só o código do ingresso. Sozinho ele não abre a catraca: o
// processador também confere se o rosto lido é o do dono.
export default function TelaIngresso() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const { sessao, api } = useSessao()
  const cores = useCores()
  const [ingresso, setIngresso] = useState<Ingresso | null>(null)
  const [erro, setErro] = useState<string | null>(null)

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

  if (!sessao) return <Redirect href="/entrar" />

  const usado = Boolean(ingresso?.usadoEm)

  return (
    <Tela>
      <Erro mensagem={erro} />
      {ingresso && (
        <View style={{ alignItems: 'center', gap: 16, marginTop: 8 }}>
          <Selo texto={usado ? 'Já usado' : 'Válido para uma entrada'} ativo={!usado} />
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
