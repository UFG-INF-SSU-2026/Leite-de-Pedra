import { Redirect, router, Stack, useFocusEffect } from 'expo-router'
import { useCallback, useState } from 'react'
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import type { Conta, Ingresso } from '@/api'
import { ROTULO_PAPEL, useSessao } from '@/sessao'
import { Botao, Erro, Paragrafo, Selo, useCores } from '@/ui'

function quando(valor: string) {
  return new Date(valor).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

export default function Ingressos() {
  const { sessao, api, sair } = useSessao()
  const cores = useCores()
  const [conta, setConta] = useState<Conta | null>(null)
  const [ingressos, setIngressos] = useState<Ingresso[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [atualizando, setAtualizando] = useState(false)
  const [comprando, setComprando] = useState(false)

  const carregar = useCallback(async () => {
    if (!sessao) return
    try {
      const [eu, meus] = await Promise.all([api<Conta>('/eu'), api<Ingresso[]>('/ingressos')])
      setConta(eu)
      setIngressos(meus)
      setErro(null)
    } catch (e) {
      setErro((e as Error).message)
    }
  }, [api, sessao])

  // Recarrega ao voltar para a tela: o ingresso pode ter sido usado na catraca.
  useFocusEffect(useCallback(() => { carregar() }, [carregar]))

  if (!sessao) return <Redirect href="/entrar" />

  async function atualizar() {
    setAtualizando(true)
    await carregar()
    setAtualizando(false)
  }

  async function comprar() {
    setComprando(true)
    setErro(null)
    try {
      const { ingressoId } = await api<{ ingressoId: string }>('/ingressos', { metodo: 'POST' })
      await carregar()
      router.push({ pathname: '/ingresso/[id]', params: { id: ingressoId } })
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setComprando(false)
    }
  }

  const disponiveis = ingressos?.filter(i => !i.usadoEm) ?? []
  const usados = ingressos?.filter(i => i.usadoEm) ?? []

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: cores.fundo }} edges={['bottom', 'left', 'right']}>
      <Stack.Screen options={{
        headerRight: () => (
          <Pressable accessibilityRole="button" onPress={sair} hitSlop={12}>
            <Text style={{ color: cores.destaque, fontSize: 16 }}>Sair</Text>
          </Pressable>
        ),
      }} />
      <ScrollView contentContainerStyle={estilos.conteudo}
        refreshControl={<RefreshControl refreshing={atualizando} onRefresh={atualizar} tintColor={cores.destaque} />}>
        {conta && (
          <View style={{ gap: 4 }}>
            <Text style={{ color: cores.texto, fontSize: 22, fontWeight: '700' }}>Olá, {conta.nome.split(' ')[0]}</Text>
            {conta.papel !== 'cliente' && <Selo texto={ROTULO_PAPEL[conta.papel]} ativo />}
          </View>
        )}
        <Erro mensagem={erro} />
        {conta?.papel === 'validador' && <Botao titulo="Abrir a catraca" aoTocar={() => router.replace('/catraca')} />}
        <Botao titulo="Comprar ingresso" aoTocar={comprar} carregando={comprando} />

        <Text style={[estilos.secao, { color: cores.suave }]}>Para usar</Text>
        {ingressos && !disponiveis.length && <Paragrafo>Você não tem ingressos para usar. Compre um para entrar no evento.</Paragrafo>}
        {disponiveis.map(i => <Cartao key={i.ingressoId} ingresso={i} />)}

        {usados.length > 0 && <Text style={[estilos.secao, { color: cores.suave }]}>Já usados</Text>}
        {usados.map(i => <Cartao key={i.ingressoId} ingresso={i} />)}
      </ScrollView>
    </SafeAreaView>
  )
}

function Cartao({ ingresso }: { ingresso: Ingresso }) {
  const cores = useCores()
  const usado = Boolean(ingresso.usadoEm)
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Ingresso ${ingresso.ingressoId}, ${usado ? 'usado' : 'para usar'}`}
      onPress={() => router.push({ pathname: '/ingresso/[id]', params: { id: ingresso.ingressoId } })}
      style={({ pressed }) => [estilos.cartao, { backgroundColor: cores.superficie, borderColor: cores.linha }, pressed && { opacity: 0.7 }]}
    >
      <View style={{ flex: 1, gap: 4 }}>
        <Text style={{ color: cores.texto, fontSize: 18, fontWeight: '600', fontVariant: ['tabular-nums'] }}>{ingresso.ingressoId}</Text>
        <Text style={{ color: cores.suave }}>
          {usado ? `Entrada em ${quando(ingresso.usadoEm!)}${ingresso.filaEntrada ? ` · ${ingresso.filaEntrada}` : ''}` : `Comprado em ${quando(ingresso.emitidoEm)}`}
        </Text>
      </View>
      <Selo texto={usado ? 'Usado' : 'Mostrar QR'} ativo={!usado} />
    </Pressable>
  )
}

const estilos = StyleSheet.create({
  conteudo: { padding: 20, gap: 14 },
  secao: { fontSize: 13, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.8, marginTop: 8 },
  cartao: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 16, borderRadius: 12, borderWidth: 1 },
})
