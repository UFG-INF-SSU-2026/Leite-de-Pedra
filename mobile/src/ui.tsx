import { type ReactNode } from 'react'
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput,
  useColorScheme, View, type TextInputProps,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'

const CLARO = {
  fundo: '#f3f5f4', superficie: '#ffffff', texto: '#18211d', suave: '#5a6762', linha: '#d4dbd7',
  destaque: '#1f6f5c', sobreDestaque: '#ffffff', erro: '#b3261e', erroFundo: '#f9dedc',
  verde: '#1d7a46', verdeFundo: '#dcf1e4', neutroFundo: '#e6e9e8',
}
const ESCURO: typeof CLARO = {
  fundo: '#101614', superficie: '#171f1c', texto: '#e3ebe7', suave: '#95a39d', linha: '#2b3833',
  destaque: '#5fc4a8', sobreDestaque: '#0d1512', erro: '#f2938a', erroFundo: '#3d1815',
  verde: '#6fd39a', verdeFundo: '#143524', neutroFundo: '#26302c',
}

export function useCores() {
  return useColorScheme() === 'dark' ? ESCURO : CLARO
}

export function Tela({ children, rolar = true }: { children: ReactNode; rolar?: boolean }) {
  const cores = useCores()
  const conteudo = <View style={estilos.conteudo}>{children}</View>
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: cores.fundo }} edges={['bottom', 'left', 'right']}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        {rolar ? <ScrollView keyboardShouldPersistTaps="handled">{conteudo}</ScrollView> : conteudo}
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

export function Titulo({ children }: { children: ReactNode }) {
  return <Text style={[estilos.titulo, { color: useCores().texto }]}>{children}</Text>
}

export function Paragrafo({ children }: { children: ReactNode }) {
  return <Text style={[estilos.paragrafo, { color: useCores().suave }]}>{children}</Text>
}

export function Campo({ rotulo, ...props }: TextInputProps & { rotulo: string }) {
  const cores = useCores()
  return (
    <View style={{ gap: 6 }}>
      <Text style={{ color: cores.suave, fontSize: 14 }}>{rotulo}</Text>
      <TextInput
        placeholderTextColor={cores.suave}
        autoCapitalize="none"
        autoCorrect={false}
        style={[estilos.campo, { color: cores.texto, backgroundColor: cores.superficie, borderColor: cores.linha }]}
        {...props}
      />
    </View>
  )
}

export function Botao({ titulo, aoTocar, carregando, secundario, desativado }: {
  titulo: string; aoTocar: () => void; carregando?: boolean; secundario?: boolean; desativado?: boolean
}) {
  const cores = useCores()
  const inativo = desativado || carregando
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: inativo, busy: carregando }}
      disabled={inativo}
      onPress={aoTocar}
      style={({ pressed }) => [
        estilos.botao,
        secundario
          ? { backgroundColor: 'transparent', borderColor: cores.linha, borderWidth: 1 }
          : { backgroundColor: cores.destaque },
        (pressed || inativo) && { opacity: 0.6 },
      ]}
    >
      {carregando
        ? <ActivityIndicator color={secundario ? cores.texto : cores.sobreDestaque} />
        : <Text style={[estilos.textoBotao, { color: secundario ? cores.texto : cores.sobreDestaque }]}>{titulo}</Text>}
    </Pressable>
  )
}

export function Erro({ mensagem }: { mensagem: string | null }) {
  const cores = useCores()
  if (!mensagem) return null
  return (
    <Text accessibilityRole="alert" style={[estilos.erro, { color: cores.erro, backgroundColor: cores.erroFundo }]}>
      {mensagem}
    </Text>
  )
}

export function Selo({ texto, ativo }: { texto: string; ativo: boolean }) {
  const cores = useCores()
  return (
    <Text style={[estilos.selo, ativo
      ? { color: cores.verde, backgroundColor: cores.verdeFundo }
      : { color: cores.suave, backgroundColor: cores.neutroFundo }]}>
      {texto}
    </Text>
  )
}

export const estilos = StyleSheet.create({
  conteudo: { padding: 20, gap: 16, flexGrow: 1 },
  titulo: { fontSize: 26, fontWeight: '700' },
  paragrafo: { fontSize: 16, lineHeight: 22 },
  campo: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16 },
  botao: { borderRadius: 10, paddingVertical: 14, alignItems: 'center', justifyContent: 'center', minHeight: 50 },
  textoBotao: { fontSize: 16, fontWeight: '600' },
  erro: { padding: 12, borderRadius: 8, fontSize: 15, overflow: 'hidden' },
  selo: { alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999, fontSize: 13, fontWeight: '600', overflow: 'hidden' },
})
