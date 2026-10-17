const atualizacoes = new EventSource("/atualizacoes");
const indicador = document.getElementById("conexao");

for (const secao of ["ao-vivo", "historico"]) {
  atualizacoes.addEventListener(secao, (evento) => {
    document.getElementById(secao).innerHTML = evento.data;
  });
}

atualizacoes.addEventListener("sessao-expirada", () => location.assign("/login"));
atualizacoes.addEventListener("open", () => {
  indicador.textContent = "ao vivo";
  indicador.className = "conexao ativa";
});
atualizacoes.addEventListener("error", () => {
  indicador.textContent = "reconectando…";
  indicador.className = "conexao caida";
});
