import { Redirect } from 'expo-router'
import { ActivityIndicator, View } from 'react-native'
import { useSessao } from '@/sessao'
import { useCores } from '@/ui'

// Porta de entrada: sem sessão, o login; validador vai à catraca; os demais, aos ingressos.
export default function Inicio() {
  const { carregando, sessao } = useSessao()
  const cores = useCores()
  if (carregando) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: cores.fundo }}>
        <ActivityIndicator color={cores.destaque} />
      </View>
    )
  }
  if (!sessao) return <Redirect href="/entrar" />
  return <Redirect href={sessao.papel === 'validador' ? '/catraca' : '/ingressos'} />
}
