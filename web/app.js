// Lembra — lógica do app (sem frameworks).
// Segurança: todo texto vindo do usuário/API é inserido com textContent (nunca innerHTML),
// para que uma memória contendo código não seja "executada" na tela (ataque XSS).
"use strict";

const API = window.LEMBRA_API || "";
const CATEGORIAS = ["geral", "família", "finanças", "compromissos", "trabalho", "saúde", "viagens", "estudos", "gostos"];
const $ = (sel) => document.querySelector(sel);

// ---------------- Sessão (crachá) ----------------
const sessao = {
  get() { try { return JSON.parse(localStorage.getItem("lembra.sessao")); } catch { return null; } },
  set(s) { try { localStorage.setItem("lembra.sessao", JSON.stringify(s)); } catch {} },
  limpar() { try { localStorage.removeItem("lembra.sessao"); } catch {} },
};

class ErroApi extends Error {
  constructor(status, msg) { super(msg); this.status = status; }
}

async function chamar(caminho, { metodo = "GET", corpo, autenticado = true, tentouRenovar = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  const s = sessao.get();
  if (autenticado && s) headers.Authorization = `Bearer ${s.access_token}`;

  let r;
  try {
    r = await fetch(API + caminho, { method: metodo, headers, body: corpo ? JSON.stringify(corpo) : undefined });
  } catch {
    throw new ErroApi(0, "Sem conexão com o servidor. Verifique a internet.");
  }

  // Crachá vencido? Renova uma vez com o refresh token e repete o pedido.
  if (r.status === 401 && autenticado && !tentouRenovar && s?.refresh_token) {
    const renovado = await fetch(API + "/auth/renovar", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: s.refresh_token }),
    }).catch(() => null);
    if (renovado?.ok) {
      sessao.set(await renovado.json());
      return chamar(caminho, { metodo, corpo, autenticado, tentouRenovar: true });
    }
    sessao.limpar();
    mostrarAuth();
    throw new ErroApi(401, "Sua sessão expirou. Entre de novo.");
  }

  if (r.status === 204) return null;
  const dados = await r.json().catch(() => ({}));
  if (!r.ok) {
    let msg = dados.detail;
    if (Array.isArray(msg)) msg = "Confira os dados preenchidos.";
    throw new ErroApi(r.status, msg || "Algo deu errado. Tente de novo.");
  }
  return dados;
}

function avisar(texto) {
  const el = $("#aviso");
  el.textContent = texto;
  el.hidden = false;
  clearTimeout(avisar.t);
  avisar.t = setTimeout(() => (el.hidden = true), 2800);
}

function el(tag, classe, texto) {
  const e = document.createElement(tag);
  if (classe) e.className = classe;
  if (texto != null) e.textContent = texto;
  return e;
}

// ---------------- Login / cadastro ----------------
let modoAuth = "entrar";

function mostrarAuth() {
  $("#app").hidden = true;
  $("#tela-auth").hidden = false;
}

function mostrarApp() {
  $("#tela-auth").hidden = true;
  $("#app").hidden = false;
  irPara("perguntar");
}

document.querySelectorAll(".aba-auth").forEach((b) =>
  b.addEventListener("click", () => {
    modoAuth = b.dataset.modo;
    document.querySelectorAll(".aba-auth").forEach((x) => x.classList.toggle("ativa", x === b));
    const cadastro = modoAuth === "cadastro";
    $("#form-auth").senha.autocomplete = cadastro ? "new-password" : "current-password";
    $("#botao-auth").textContent = cadastro ? "Criar conta" : "Entrar";
    $("#erro-auth").textContent = "";
  })
);

$("#form-auth").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const erro = $("#erro-auth");
  erro.textContent = "";
  const email = f.email.value.trim();
  const senha = f.senha.value;
  if (!email || !senha) return (erro.textContent = "Preencha e-mail e senha.");
  if (modoAuth === "cadastro" && senha.length < 8)
    return (erro.textContent = "A senha precisa ter pelo menos 8 caracteres.");

  const botao = $("#botao-auth");
  botao.disabled = true;
  try {
    const s = modoAuth === "cadastro"
      ? await chamar("/auth/cadastro", { metodo: "POST", autenticado: false,
          corpo: { email, senha } })
      : await chamar("/auth/login", { metodo: "POST", autenticado: false, corpo: { email, senha } });
    sessao.set(s);
    f.reset();
    mostrarApp();
  } catch (err) {
    erro.textContent = err.message;
  } finally {
    botao.disabled = false;
  }
});

const DICA_INICIAL = $("#dica-perguntar").cloneNode(true);

$("#sair").addEventListener("click", () => {
  sessao.limpar();
  // Limpa tudo da tela: se outra pessoa entrar neste celular, não vê nada da anterior.
  $("#conversa").replaceChildren(DICA_INICIAL.cloneNode(true));
  $("#lista-memorias").replaceChildren();
  mostrarAuth();
});

// ---------------- Navegação ----------------
function irPara(tela) {
  ["perguntar", "registrar", "memorias"].forEach((t) => ($(`#tela-${t}`).hidden = t !== tela));
  document.querySelectorAll(".aba").forEach((a) => a.classList.toggle("ativa", a.dataset.tela === tela));
  if (tela === "memorias") carregarMemorias();
}
document.querySelectorAll(".aba").forEach((a) => a.addEventListener("click", () => irPara(a.dataset.tela)));

// ---------------- Seletores de categoria ----------------
function preencherSelect(select, rotuloTodas) {
  select.append(new Option(rotuloTodas, ""));
  CATEGORIAS.forEach((c) => select.append(new Option(c[0].toUpperCase() + c.slice(1), c)));
}
preencherSelect($("#form-perguntar").categoria, "Procurar em: todas");
preencherSelect($("#filtro-memorias"), "Todas");

let categoriaEscolhida = "geral";
CATEGORIAS.forEach((c) => {
  const chip = el("button", "chip" + (c === categoriaEscolhida ? " ativo" : ""), c);
  chip.type = "button";
  chip.addEventListener("click", () => {
    categoriaEscolhida = c;
    document.querySelectorAll("#chips-categoria .chip").forEach((x) => x.classList.toggle("ativo", x === chip));
  });
  $("#chips-categoria").append(chip);
});

// ---------------- Registrar ----------------
$("#form-registrar").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const erro = $("#erro-registrar");
  erro.textContent = "";
  if (!f.texto.value.trim()) return (erro.textContent = "Escreva a memória.");
  const botao = f.querySelector("button[type=submit]");
  botao.disabled = true;
  botao.textContent = "Salvando…";
  try {
    await chamar("/memorias", { metodo: "POST",
      corpo: { texto: f.texto.value, categoria: categoriaEscolhida, data_evento: f.data_evento.value } });
    f.reset();
    avisar("Memória salva ✓");
  } catch (err) {
    erro.textContent = err.message;
  } finally {
    botao.disabled = false;
    botao.textContent = "Salvar memória";
  }
});

// ---------------- Perguntar ----------------
function balao(classe, texto) {
  const b = el("div", "balao " + classe, texto);
  $("#conversa").append(b);
  b.scrollIntoView({ behavior: "smooth", block: "end" });
  return b;
}

$("#form-perguntar").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const pergunta = f.pergunta.value.trim();
  if (!pergunta) return;
  $("#dica-perguntar")?.remove();
  balao("usuario", pergunta);
  f.pergunta.value = "";
  const pensando = balao("lembra pensando", "Procurando nas suas memórias…");

  try {
    const r = await chamar("/perguntar", { metodo: "POST",
      corpo: { pergunta, categoria: f.categoria.value || null } });
    pensando.classList.remove("pensando");
    pensando.textContent = r.resposta;
    if (r.fontes.length) {
      const det = el("details", "fontes");
      det.open = !r.gerada_por_ia; // sem IA, as memórias SÃO a resposta: já mostra abertas
      det.append(el("summary", null, `${r.fontes.length} memória(s) usada(s)`));
      r.fontes.forEach((fo, i) => {
        const d = el("div", "fonte");
        const meta = [`[${i + 1}]`, fo.categoria, fo.data].filter(Boolean).join(" · ");
        d.append(el("span", "fonte-meta", meta), document.createTextNode(fo.texto));
        det.append(d);
      });
      pensando.append(det);
    }
  } catch (err) {
    pensando.classList.remove("pensando");
    pensando.textContent = "⚠️ " + err.message;
  }
  pensando.scrollIntoView({ behavior: "smooth", block: "end" });
});

// ---------------- Memórias ----------------
$("#filtro-memorias").addEventListener("change", carregarMemorias);

async function carregarMemorias() {
  const lista = $("#lista-memorias");
  lista.replaceChildren(el("li", "vazio", "Carregando…"));
  const cat = $("#filtro-memorias").value;
  try {
    const memorias = await chamar("/memorias" + (cat ? `?categoria=${encodeURIComponent(cat)}` : ""));
    lista.replaceChildren();
    if (!memorias.length) {
      const v = el("li", "vazio");
      v.append(el("p", "vazio-titulo", "Nenhuma memória ainda"), el("p", null, "Use a aba Registrar para começar."));
      return lista.append(v);
    }
    memorias.forEach((m) => {
      const li = el("li", "item");
      const rodape = el("div", "item-rodape");
      const quando = new Date(m.criado_em).toLocaleDateString("pt-BR");
      const info = el("span", null, m.data_evento ? `${m.data_evento} · salvo em ${quando}` : `salvo em ${quando}`);
      const esquerda = el("span", "item-info");
      esquerda.append(el("span", "etiqueta", m.categoria), info);
      const apagar = el("button", "apagar", "Apagar");
      apagar.type = "button";
      apagar.addEventListener("click", async () => {
        if (!confirm("Apagar esta memória? Não dá para desfazer.")) return;
        try {
          await chamar(`/memorias/${m.id}`, { metodo: "DELETE" });
          li.remove();
          avisar("Memória apagada");
          if (!lista.children.length) carregarMemorias();
        } catch (err) { avisar(err.message); }
      });
      rodape.append(esquerda, apagar);
      li.append(el("p", "item-texto", m.texto), rodape);
      lista.append(li);
    });
  } catch (err) {
    lista.replaceChildren(el("li", "vazio", "⚠️ " + err.message));
  }
}

// ---------------- Início ----------------
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
sessao.get()?.access_token ? mostrarApp() : mostrarAuth();
