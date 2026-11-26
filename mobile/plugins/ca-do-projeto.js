// O Android não confia em CA instalada pelo usuário: o APK leva o certificado
// público da CA do projeto e o confia, além das CAs do sistema, para falar com
// o backend em HTTPS. Sem isso, a conexão com https://<ip>:8444 é recusada.
const fs = require('fs')
const path = require('path')
const { AndroidConfig, withAndroidManifest, withDangerousMod } = require('expo/config-plugins')

const CONFIG_REDE = `<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config>
        <trust-anchors>
            <certificates src="system" />
            <certificates src="@raw/ca_do_projeto" />
        </trust-anchors>
    </base-config>
</network-security-config>
`

module.exports = function comCaDoProjeto(config) {
  config = withDangerousMod(config, ['android', (c) => {
    const res = path.join(c.modRequest.platformProjectRoot, 'app/src/main/res')
    fs.mkdirSync(path.join(res, 'raw'), { recursive: true })
    fs.mkdirSync(path.join(res, 'xml'), { recursive: true })
    fs.copyFileSync(path.join(c.modRequest.projectRoot, 'certificados/ca-do-projeto.crt'),
      path.join(res, 'raw/ca_do_projeto.pem'))
    fs.writeFileSync(path.join(res, 'xml/network_security_config.xml'), CONFIG_REDE)
    return c
  }])
  return withAndroidManifest(config, (c) => {
    AndroidConfig.Manifest.getMainApplicationOrThrow(c.modResults).$['android:networkSecurityConfig'] =
      '@xml/network_security_config'
    return c
  })
}
