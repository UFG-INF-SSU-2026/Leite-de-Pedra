import { Stack } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { ProvedorSessao } from '@/sessao'
import { useCores } from '@/ui'

export default function Layout() {
  const cores = useCores()
  return (
    <ProvedorSessao>
      <StatusBar style="auto" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: cores.superficie },
          headerTintColor: cores.texto,
          contentStyle: { backgroundColor: cores.fundo },
          headerBackTitle: 'Voltar',
        }}
      >
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="entrar" options={{ title: 'Entrar', headerShown: false }} />
        <Stack.Screen name="cadastro" options={{ title: 'Criar conta' }} />
        <Stack.Screen name="ingressos" options={{ title: 'Meus ingressos', headerBackVisible: false }} />
        <Stack.Screen name="ingresso/[id]" options={{ title: 'Ingresso' }} />
        <Stack.Screen name="catraca" options={{ title: 'Catraca', headerBackVisible: false }} />
      </Stack>
    </ProvedorSessao>
  )
}
