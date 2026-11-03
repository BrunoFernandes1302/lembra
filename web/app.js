// Lembra — lógica do app (sem frameworks).
// Segurança: todo texto vindo do usuário/API é inserido com textContent (nunca innerHTML),
// para que uma memória contendo código não seja "executada" na tela (ataque XSS).
"use strict";

const API = window.LEMBRA_API || "";
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
let categorias = []; // [{nome, memorias}] — vem do banco, cada usuário tem a sua lista

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

function icone(nome) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "ic");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${nome}`);
  svg.append(use);
  return svg;
}

function botao(texto, classe, aoClicar, nomeIcone) {
  const b = el("button", classe);
  b.type = "button";
  if (nomeIcone) b.append(icone(nomeIcone));
  b.append(document.createTextNode(texto));
  b.addEventListener("click", aoClicar);
  return b;
}

const rotulo = (c) => c[0].toUpperCase() + c.slice(1);

// ---------------- Menu de seleção (substitui o <select> nativo) ----------------
// A lista do <select> nativo é desenhada pelo sistema operacional e o CSS não a alcança.
// Aqui o <select> continua existindo (escondido) e guarda o valor; desenhamos por cima
// uma pílula + lista própria. Toda a lógica que lê select.value continua funcionando.
function aprimorarSelect(select) {
  if (select._menu) return select._menu;
  const caixa = el("div", "menu" + (select.hasAttribute("data-compacto") ? " compacto" : ""));
  const botaoMenu = el("button", "menu-botao");
  botaoMenu.type = "button";
  botaoMenu.setAttribute("aria-haspopup", "listbox");
  botaoMenu.setAttribute("aria-label", select.getAttribute("aria-label") || "Escolher");
  const rotuloMenu = el("span", "menu-rotulo");
  if (select.dataset.icone) botaoMenu.append(icone(select.dataset.icone));
  botaoMenu.append(rotuloMenu, icone("chevron"));
  const lista = el("ul", "menu-lista");
  lista.setAttribute("role", "listbox");
  lista.hidden = true;
  caixa.append(botaoMenu, lista);
  select.after(caixa);
  select.classList.add("select-escondido");
  select.tabIndex = -1;

  const fechar = () => { lista.hidden = true; caixa.classList.remove("aberto"); botaoMenu.setAttribute("aria-expanded", "false"); };
  const desenhar = () => {
    const op = select.options[select.selectedIndex];
    rotuloMenu.textContent = op ? op.text : "";
    lista.replaceChildren();
    [...select.options].forEach((o) => {
      const li = el("li", "menu-item" + (o.selected ? " escolhido" : ""));
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", String(o.selected));
      li.tabIndex = -1;
      li.append(el("span", null, o.text), icone("check"));
      li.addEventListener("click", () => {
        select.value = o.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        desenhar();
        fechar();
        botaoMenu.focus();
      });
      lista.append(li);
    });
  };
  botaoMenu.addEventListener("click", () => {
    if (!lista.hidden) return fechar();
    $$(".menu.aberto").forEach((m) => m._fechar?.());
    desenhar();
    // abre para cima quando está na parte de baixo da tela (ex.: barra de pergunta)
    caixa.classList.toggle("para-cima", botaoMenu.getBoundingClientRect().top > innerHeight * 0.55);
    lista.hidden = false;
    caixa.classList.add("aberto");
    botaoMenu.setAttribute("aria-expanded", "true");
    (lista.querySelector(".escolhido") || lista.firstChild)?.focus();
  });
  lista.addEventListener("keydown", (e) => {
    const itens = [...lista.children];
    const i = itens.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); itens[Math.min(i + 1, itens.length - 1)]?.focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); itens[Math.max(i - 1, 0)]?.focus(); }
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); document.activeElement.click(); }
    if (e.key === "Escape") { fechar(); botaoMenu.focus(); }
  });
  caixa._fechar = fechar;
  // redesenha sozinho quando as opções mudam (ex.: categorias recarregadas)
  new MutationObserver(() => queueMicrotask(desenhar)).observe(select, { childList: true });
  select.addEventListener("change", desenhar);
  select.form?.addEventListener("reset", () => setTimeout(desenhar));
  select._menu = { desenhar, fechar };
  desenhar();
  return select._menu;
}
document.addEventListener("click", (e) => {
  $$(".menu.aberto").forEach((m) => { if (!m.contains(e.target)) m._fechar(); });
});

// ---------------- Resposta da IA: formatação segura + revelação suave ----------------
// O Gemini responde com marcações (**negrito**, listas, [1]). Montamos os elementos
// um a um com textContent — nunca innerHTML —, então nada vindo da IA "executa" na tela.
function trechoFormatado(texto) {
  const frag = document.createDocumentFragment();
  // **negrito** e citações [1], [2]
  texto = texto.replace(/\s*\[\s*\]/g, ""); // citação vazia "[]"
  texto.split(/(\*\*[^*]+\*\*|\[\d+(?:\s*,\s*\d+)*\])/g).forEach((parte) => {
    if (!parte) return;
    if (/^\*\*[^*]+\*\*$/.test(parte)) frag.append(el("strong", null, parte.slice(2, -2)));
    else if (/^\[\d+(?:\s*,\s*\d+)*\]$/.test(parte))
      parte.slice(1, -1).split(",").forEach((n) => frag.append(el("span", "cita", n.trim())));
    else frag.append(document.createTextNode(parte));
  });
  return frag;
}

function renderizarResposta(caixa, texto) {
  const corpo = el("div", "resposta");
  let lista = null;
  texto.trim().split("\n").forEach((linha) => {
    const t = linha.trim();
    const item = t.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (item) {
      if (!lista) { lista = el(/^\d/.test(t) ? "ol" : "ul"); corpo.append(lista); }
      const li = el("li");
      li.append(trechoFormatado(item[1]));
      lista.append(li);
    } else {
      lista = null;
      if (!t) return;
      const p = el("p");
      p.append(trechoFormatado(t));
      corpo.append(p);
    }
  });
  // cada bloco surge em sequência (efeito "digitando"); quem pediu menos movimento vê tudo de uma vez
  [...corpo.querySelectorAll("p, li")].forEach((b, i) => b.style.setProperty("--atraso", `${Math.min(i, 12) * 70}ms`));
  caixa.append(corpo);
}

// ---------------- Login / cadastro ----------------
let modoAuth = "entrar";

function mostrarAuth() {
  $("#app").hidden = true;
  $("#tela-auth").hidden = false;
}

async function mostrarApp() {
  $("#tela-auth").hidden = true;
  $("#app").hidden = false;
  irPara("perguntar");
  await carregarCategorias().catch(() => {});
}

$$(".aba-auth").forEach((b) =>
  b.addEventListener("click", () => {
    modoAuth = b.dataset.modo;
    $$(".aba-auth").forEach((x) => x.classList.toggle("ativa", x === b));
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

  const b = $("#botao-auth");
  b.disabled = true;
  try {
    const s = modoAuth === "cadastro"
      ? await chamar("/auth/cadastro", { metodo: "POST", autenticado: false, corpo: { email, senha } })
      : await chamar("/auth/login", { metodo: "POST", autenticado: false, corpo: { email, senha } });
    sessao.set(s);
    f.reset();
    mostrarApp();
  } catch (err) {
    erro.textContent = err.message;
  } finally {
    b.disabled = false;
  }
});

const DICA_INICIAL = $("#dica-perguntar").cloneNode(true);

$("#sair").addEventListener("click", () => {
  sessao.limpar();
  // Limpa tudo da tela: se outra pessoa entrar neste celular, não vê nada da anterior.
  $("#conversa").replaceChildren(DICA_INICIAL.cloneNode(true));
  $("#lista-memorias").replaceChildren();
  $("#lista-categorias").replaceChildren();
  $("#lab-chunks").replaceChildren();
  $("#lab-resumo").textContent = "";
  categorias = [];
  mostrarAuth();
});

// ---------------- Navegação ----------------
const TELAS = ["perguntar", "registrar", "memorias", "ajustes"];
function irPara(tela) {
  TELAS.forEach((t) => ($(`#tela-${t}`).hidden = t !== tela));
  $$(".aba").forEach((a) => a.classList.toggle("ativa", a.dataset.tela === tela));
  if (tela === "memorias") carregarMemorias();
  if (tela === "ajustes") carregarConfig();
}
$$(".aba").forEach((a) => a.addEventListener("click", () => irPara(a.dataset.tela)));

$$(".segmento[data-sub]").forEach((s) =>
  s.addEventListener("click", () => {
    $$(".segmento[data-sub]").forEach((x) => x.classList.toggle("ativo", x === s));
    ["rag", "lab", "cats"].forEach((n) => ($(`#sub-${n}`).hidden = n !== s.dataset.sub));
    if (s.dataset.sub === "cats") desenharCategorias();
  })
);

// ---------------- Categorias (do banco) ----------------
let categoriaEscolhida = "geral";

async function carregarCategorias() {
  categorias = await chamar("/categorias");
  if (!categorias.some((c) => c.nome === categoriaEscolhida)) categoriaEscolhida = categorias[0]?.nome || "geral";
  desenharChips();
  preencherSelect($("#form-perguntar").categoria, "Todas");
  preencherSelect($("#filtro-memorias"), "Todas");
  const ci = $("#cat-importar");
  const atualCi = ci.value || "conversas";
  ci.replaceChildren(new Option("Conversas", "conversas"));
  categorias.filter((c) => c.nome !== "conversas").forEach((c) => ci.append(new Option(rotulo(c.nome), c.nome)));
  ci.value = [...ci.options].some((o) => o.value === atualCi) ? atualCi : "conversas";
  if (!$("#sub-cats").hidden) desenharCategorias();
}

function preencherSelect(select, rotuloTodas) {
  const atual = select.value;
  select.replaceChildren(new Option(rotuloTodas, ""));
  categorias.forEach((c) => select.append(new Option(rotulo(c.nome), c.nome)));
  if ([...select.options].some((o) => o.value === atual)) select.value = atual;
}

function desenharChips() {
  const box = $("#chips-categoria");
  box.replaceChildren();
  $("#dica-cat").hidden = categorias.some((c) => c.nome === categoriaEscolhida);
  categorias.forEach((c) => {
    const chip = botao(c.nome, "chip" + (c.nome === categoriaEscolhida ? " ativo" : ""), () => {
      categoriaEscolhida = c.nome;
      desenharChips();
    });
    box.append(chip);
  });
  box.append(botao("nova", "chip chip-nova", () => {
    $("#linha-nova-cat").hidden = false;
    $("#nova-cat-registrar").focus();
  }, "plus"));
}

async function criarCategoria(nome) {
  nome = nome.trim().toLowerCase();
  if (!nome) return null;
  await chamar("/categorias", { metodo: "POST", corpo: { nome } });
  await carregarCategorias();
  return nome;
}

$("#criar-cat-registrar").addEventListener("click", async () => {
  try {
    const nome = await criarCategoria($("#nova-cat-registrar").value);
    if (!nome) return;
    categoriaEscolhida = nome;
    desenharChips();
    $("#nova-cat-registrar").value = "";
    $("#linha-nova-cat").hidden = true;
  } catch (err) { avisar(err.message); }
});

$("#form-nova-cat").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const nome = await criarCategoria(e.target.nome.value);
    if (nome) avisar(`Categoria "${nome}" criada`);
    e.target.reset();
  } catch (err) { avisar(err.message); }
});

function desenharCategorias() {
  const lista = $("#lista-categorias");
  lista.replaceChildren();
  categorias.forEach((c) => {
    const li = el("li", "item item-cat");
    const info = el("div", "item-info");
    info.append(el("span", "etiqueta", c.nome), el("span", "suave", `${c.memorias} memória(s)`));
    const acoes = el("div", "acoes");
    acoes.append(
      botao("Renomear", "botao-texto", async () => {
        const novo = prompt(`Novo nome para "${c.nome}":`, c.nome);
        if (!novo || novo.trim().toLowerCase() === c.nome) return;
        try {
          await chamar(`/categorias/${encodeURIComponent(c.nome)}`, { metodo: "PUT", corpo: { novo_nome: novo } });
          await carregarCategorias();
          avisar("Categoria renomeada");
        } catch (err) { avisar(err.message); }
      }, "edit"),
      botao("Apagar", "botao-texto apagar", async () => {
        const outras = categorias.filter((x) => x.nome !== c.nome).map((x) => x.nome);
        if (!outras.length) return avisar("Crie outra categoria antes de apagar esta.");
        let destino = outras.includes("geral") ? "geral" : outras[0];
        if (c.memorias > 0) {
          destino = prompt(`As ${c.memorias} memória(s) de "${c.nome}" serão movidas para qual categoria?\n(${outras.join(", ")})`, destino);
          if (!destino) return;
        } else if (!confirm(`Apagar a categoria "${c.nome}"?`)) return;
        try {
          const r = await chamar(`/categorias/${encodeURIComponent(c.nome)}?mover_para=${encodeURIComponent(destino)}`,
            { metodo: "DELETE" });
          await carregarCategorias();
          avisar(r.memorias_movidas ? `${r.memorias_movidas} memória(s) movida(s) para "${destino.toLowerCase()}"` : "Categoria apagada");
        } catch (err) { avisar(err.message); }
      }, "trash")
    );
    li.append(info, acoes);
    lista.append(li);
  });
}

// ---------------- Áudio: falar em vez de digitar ----------------
// Grava no formato nativo do aparelho (Chrome/Android: WebM/Opus; iPhone: MP4/AAC), manda para a
// API, que transcreve com o Gemini (multimodal). O áudio não é guardado; só o texto volta.
const MAX_GRAVACAO_S = 120;
let gravacao = null; // { rec, botao, inicio, timer, fluxo }

function formatoGravacao() {
  const opcoes = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm", "audio/ogg;codecs=opus"];
  return opcoes.find((t) => window.MediaRecorder?.isTypeSupported?.(t)) || "";
}

async function iniciarGravacao(botaoMic) {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
    return avisar("Este navegador não permite gravar áudio.");
  let fluxo;
  try {
    fluxo = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch {
    return avisar("Permita o uso do microfone para falar com o Lembra.");
  }
  const tipo = formatoGravacao();
  const rec = new MediaRecorder(fluxo, tipo ? { mimeType: tipo, audioBitsPerSecond: 32000 } : undefined);
  const pedacos = [];
  rec.ondataavailable = (e) => e.data.size && pedacos.push(e.data);
  rec.onstop = () => {
    fluxo.getTracks().forEach((t) => t.stop()); // desliga o microfone (some o indicador do sistema)
    enviarAudio(botaoMic, new Blob(pedacos, { type: rec.mimeType || tipo || "audio/webm" }));
  };
  rec.start();
  const inicio = Date.now();
  const tempo = botaoMic.querySelector(".tempo");
  const timer = setInterval(() => {
    const s = Math.floor((Date.now() - inicio) / 1000);
    tempo.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    if (s >= MAX_GRAVACAO_S) pararGravacao();
  }, 250);
  gravacao = { rec, botaoMic, timer };
  botaoMic.classList.add("gravando");
  botaoMic.querySelector("use").setAttribute("href", "#i-stop");
  botaoMic.setAttribute("aria-label", "Parar gravação");
  tempo.textContent = "0:00";
}

function pararGravacao() {
  if (!gravacao) return;
  clearInterval(gravacao.timer);
  gravacao.rec.stop();
  gravacao = null;
}

function restaurarMic(botaoMic) {
  botaoMic.classList.remove("gravando", "transcrevendo");
  botaoMic.querySelector("use").setAttribute("href", "#i-mic");
  botaoMic.querySelector(".tempo").textContent = botaoMic.classList.contains("com-texto") ? "Falar" : "";
  botaoMic.disabled = false;
}

async function enviarAudio(botaoMic, blob) {
  botaoMic.classList.remove("gravando");
  botaoMic.classList.add("transcrevendo");
  botaoMic.disabled = true;
  botaoMic.querySelector(".tempo").textContent = "Transcrevendo…";
  try {
    if (blob.size < 1500) throw new Error("Gravação curta demais.");
    const b64 = await new Promise((ok, erro) => {
      const fr = new FileReader();
      fr.onload = () => ok(String(fr.result).split(",")[1]);
      fr.onerror = erro;
      fr.readAsDataURL(blob);
    });
    const r = await chamar("/audio/transcrever", { metodo: "POST", corpo: { audio_b64: b64, mime: blob.type } });
    if (!r.texto) throw new Error("Não ouvi nenhuma fala. Tente de novo.");
    if (botaoMic.dataset.gravador === "perguntar") {
      const f = $("#form-perguntar");
      f.pergunta.value = r.texto;
      f.requestSubmit();
    } else {
      const ta = $("#form-registrar").texto;
      ta.value = (ta.value.trim() ? ta.value.trim() + " " : "") + r.texto; // revise antes de salvar
      ta.dispatchEvent(new Event("input", { bubbles: true })); // dispara a sugestão de categoria
      ta.focus();
      avisar("Transcrito ✓ — revise antes de salvar");
    }
  } catch (err) {
    avisar(err.message);
  } finally {
    restaurarMic(botaoMic);
  }
}

$$("[data-gravador]").forEach((b) =>
  b.addEventListener("click", () => (gravacao ? pararGravacao() : iniciarGravacao(b)))
);

// ---------------- Sugestão de categoria pela IA ----------------
// "debounce": só pergunta à IA quando a pessoa PARA de digitar por 1,5 s (e não a cada letra).
let timerSugestao = null;
let pedidoSugestao = 0;
let sugestaoAtual = null;

function esconderSugestao() { $("#sugestao-cat").hidden = true; sugestaoAtual = null; }

$("#form-registrar").texto.addEventListener("input", (e) => {
  clearTimeout(timerSugestao);
  const texto = e.target.value.trim();
  if (texto.length < 25) return esconderSugestao();
  timerSugestao = setTimeout(async () => {
    const meu = ++pedidoSugestao; // descarta respostas de pedidos antigos (a pessoa continuou digitando)
    try {
      const r = await chamar("/categorias/sugerir", { metodo: "POST", corpo: { texto } });
      if (meu !== pedidoSugestao || !r.categoria) return;
      if (r.categoria === categoriaEscolhida) return esconderSugestao();
      sugestaoAtual = r;
      $("#aceitar-sugestao").textContent = r.nova ? `+ ${r.categoria} (nova)` : r.categoria;
      $("#motivo-sugestao").textContent = r.motivo || "";
      $("#sugestao-cat").hidden = false;
    } catch { /* sugestão é opcional */ }
  }, 1500);
});

$("#aceitar-sugestao").addEventListener("click", async () => {
  if (!sugestaoAtual) return;
  try {
    if (sugestaoAtual.nova) await criarCategoria(sugestaoAtual.categoria);
    categoriaEscolhida = sugestaoAtual.categoria;
    desenharChips();
    esconderSugestao();
  } catch (err) { avisar(err.message); }
});

// ---------------- Registrar ----------------
$("#form-registrar").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const erro = $("#erro-registrar");
  erro.textContent = "";
  if (!f.texto.value.trim()) return (erro.textContent = "Escreva a memória.");
  const b = f.querySelector("button[type=submit]");
  b.disabled = true;
  b.querySelector("span").textContent = "Guardando e entendendo…";
  try {
    const r = await chamar("/memorias", { metodo: "POST",
      corpo: { texto: f.texto.value, categoria: categoriaEscolhida, data_evento: f.data_evento.value } });
    f.reset();
    esconderSugestao();
    avisar(`Memória salva ✓ (${r.chunks} chunk${r.chunks > 1 ? "s" : ""})`);
    carregarCategorias().catch(() => {});
  } catch (err) {
    erro.textContent = err.message;
  } finally {
    b.disabled = false;
    b.querySelector("span").textContent = "Salvar memória";
  }
});

// ---------------- Registrar: escrever × importar ----------------
$$("[data-reg]").forEach((b) =>
  b.addEventListener("click", () => {
    $$("[data-reg]").forEach((x) => x.classList.toggle("ativo", x === b));
    $("#reg-escrever").hidden = b.dataset.reg !== "escrever";
    $("#reg-importar").hidden = b.dataset.reg !== "importar";
  })
);

// ---------------- Importar conversa do WhatsApp ----------------
let conteudoImportar = null;

$("#form-importar").arquivo.addEventListener("change", async (e) => {
  const arq = e.target.files[0];
  $("#previa-importar").hidden = true;
  $("#erro-importar").textContent = "";
  if (!arq) return;
  if (arq.size > 3000000) return ($("#erro-importar").textContent = "Arquivo grande demais (máx. 3 MB). Exporte um período menor.");
  conteudoImportar = await arq.text(); // lido no próprio aparelho; só o texto vai para a API
  $("#arquivo-nome").textContent = arq.name;
  e.target.closest(".arquivo").classList.add("escolhido");
  const f = $("#form-importar");
  if (!f.nome.value) f.nome.value = arq.name.replace(/^(Conversa do WhatsApp com|WhatsApp Chat with)\s*/i, "").replace(/\.txt$/i, "");
});

function corpoImportar(confirmar) {
  const f = $("#form-importar");
  return { conteudo: conteudoImportar, nome_conversa: f.nome.value.trim() || "Conversa",
           categoria: f.categoria.value, confirmar };
}

$("#form-importar").addEventListener("submit", async (e) => {
  e.preventDefault();
  const erro = $("#erro-importar");
  erro.textContent = "";
  if (!conteudoImportar) return (erro.textContent = "Escolha o arquivo .txt exportado do WhatsApp.");
  const b = $("#botao-previa");
  b.disabled = true;
  try {
    const r = await chamar("/importar/whatsapp", { metodo: "POST", corpo: corpoImportar(false) });
    const ul = $("#previa-numeros");
    ul.replaceChildren();
    const item = (rot, val, largo) => {
      const li = el("li", largo ? "largo" : null);
      li.append(el("b", null, String(val)), document.createTextNode(rot));
      ul.append(li);
    };
    item("mensagens", r.mensagens);
    item("blocos (viram memórias)", r.blocos);
    item("período", `${r.de} → ${r.ate}`, true);
    item("participantes", r.participantes.join(", "), true);
    $("#previa-exemplo").textContent = r.exemplo + (r.exemplo.length >= 600 ? "…" : "");
    $("#previa-importar").hidden = false;
    $("#previa-importar").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    erro.textContent = err.message;
  } finally {
    b.disabled = false;
  }
});

$("#botao-importar").addEventListener("click", async (e) => {
  const b = e.currentTarget;
  b.disabled = true;
  b.querySelector("span").textContent = "Importando e entendendo…";
  try {
    const r = await chamar("/importar/whatsapp", { metodo: "POST", corpo: corpoImportar(true) });
    avisar(`Conversa importada: ${r.memorias_criadas} memória(s), ${r.chunks} chunk(s)`);
    $("#previa-importar").hidden = true;
    $("#form-importar").reset();
    $("#arquivo-nome").textContent = "Escolher arquivo .txt";
    $(".arquivo").classList.remove("escolhido");
    conteudoImportar = null;
    carregarCategorias().catch(() => {});
  } catch (err) {
    $("#erro-importar").textContent = err.message;
  } finally {
    b.disabled = false;
    b.querySelector("span").textContent = "Importar para o Lembra";
  }
});

// ---------------- Perguntar ----------------
function balao(classe, texto) {
  const b = el("div", "balao " + classe, texto);
  $("#conversa").append(b);
  b.scrollIntoView({ behavior: "smooth", block: "end" });
  return b;
}

// Sugestões da tela inicial (delegação: funcionam mesmo depois que a tela é recriada ao sair)
$("#conversa").addEventListener("click", (e) => {
  const s = e.target.closest(".sugestao");
  if (!s) return;
  const f = $("#form-perguntar");
  f.pergunta.value = s.dataset.pergunta;
  f.requestSubmit();
});

$("#form-perguntar").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const pergunta = f.pergunta.value.trim();
  if (!pergunta) return;
  $("#dica-perguntar")?.remove();
  balao("usuario", pergunta);
  f.pergunta.value = "";
  const pensando = balao("lembra pensando", null);
  const pontinhos = el("span", "pontinhos");
  pontinhos.append(el("i"), el("i"), el("i"));
  pensando.append(el("span", "texto-pensando", "Procurando nas suas memórias"), pontinhos);

  try {
    const r = await chamar("/perguntar", { metodo: "POST",
      corpo: { pergunta, categoria: f.categoria.value || null } });
    pensando.classList.remove("pensando");
    pensando.replaceChildren();
    renderizarResposta(pensando, r.resposta);
    if (!r.gerada_por_ia) pensando.classList.add("sem-ia");
    if (r.passos?.length) pensando.append(blocoPassos(r.passos));
    if (r.gerada_por_ia) pensando.append(blocoAvaliacao(pergunta, r.resposta));
    if (r.fontes.length) {
      const det = el("details", "fontes");
      det.open = !r.gerada_por_ia; // sem IA, as memórias SÃO a resposta: já mostra abertas
      const resumo = el("summary");
      resumo.append(icone("layers"), document.createTextNode(`${r.fontes.length} ${r.fontes.length > 1 ? "memórias usadas" : "memória usada"}`));
      det.append(resumo);
      r.fontes.forEach((fo, i) => {
        const d = el("div", "fonte");
        const cab = el("span", "fonte-meta");
        cab.append(el("span", "cita", String(i + 1)),
                   document.createTextNode([fo.categoria, fo.data].filter(Boolean).join(" · ")),
                   el("span", "nota", `similaridade ${fo.similaridade.toFixed(2)}`));
        d.append(cab, document.createTextNode(fo.texto));
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

// 👍/👎: dados para personalizar agora (perfil) e para fine-tuning no futuro
function blocoAvaliacao(pergunta, resposta) {
  const caixa = el("div", "avaliacao");
  const enviar = async (util, comentario) => {
    caixa.replaceChildren(el("span", "obrigado", "Obrigado! Isso me ajuda a te entender melhor."));
    try {
      const r = await chamar("/feedback", { metodo: "POST", corpo: { pergunta, resposta, util, comentario } });
      if (r.perfil_atualizado) avisar("Aprendi um pouco mais sobre você ✨ (veja em Ajustes)");
    } catch (err) { avisar(err.message); }
  };
  const sim = botao("", "botao-voto", () => enviar(true), "up");
  sim.setAttribute("aria-label", "Resposta útil");
  const nao = botao("", "botao-voto", () => {
    caixa.replaceChildren();
    const campo = el("input");
    campo.placeholder = "O que faltou? (opcional)";
    campo.maxLength = 500;
    const ok = botao("Enviar", "botao-texto", () => enviar(false, campo.value.trim() || null));
    campo.addEventListener("keydown", (e) => e.key === "Enter" && ok.click());
    caixa.append(campo, ok);
    campo.focus();
  }, "down");
  nao.setAttribute("aria-label", "Resposta não ajudou");
  caixa.append(el("span", "pergunta-voto", "Ajudou?"), sim, nao);
  return caixa;
}

// "Como cheguei aqui": as ferramentas que o agente usou, em ordem
const ICONE_FERRAMENTA = { buscar_memorias: "search", listar_memorias: "list", listar_categorias: "tag",
                           calcular: "calc", data_de_hoje: "calendar", dias_ate: "calendar" };
const NOME_FERRAMENTA = { buscar_memorias: "Buscou", listar_memorias: "Listou memórias", listar_categorias: "Viu as categorias",
                          calcular: "Calculou", data_de_hoje: "Consultou a data", dias_ate: "Contou os dias" };

function blocoPassos(passos) {
  const det = el("details", "passos-agente");
  const resumo = el("summary");
  resumo.append(icone("bot"), document.createTextNode(`Como cheguei aqui · ${passos.length} passo${passos.length > 1 ? "s" : ""}`));
  det.append(resumo);
  const ol = el("ol");
  passos.forEach((p) => {
    const li = el("li");
    const arg = p.argumentos.consulta || p.argumentos.expressao || p.argumentos.categoria || p.argumentos.texto_contem || "";
    const texto = el("span");
    texto.append(el("b", null, NOME_FERRAMENTA[p.ferramenta] || p.ferramenta));
    if (arg) texto.append(document.createTextNode(` “${arg}”`));
    li.append(icone(ICONE_FERRAMENTA[p.ferramenta] || "sparkles"), texto, el("span", "passo-resumo", p.resumo));
    ol.append(li);
  });
  det.append(ol);
  return det;
}

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
      const v = el("li", "vazio estado-vazio");
      const orbe = el("div", "orbe pequeno");
      orbe.append(icone(cat ? "tag" : "inbox"));
      v.append(orbe,
        el("p", "vazio-titulo", cat ? `Nada em "${cat}" ainda` : "Nenhuma memória ainda"),
        el("p", null, cat ? "Escolha outra categoria ou registre algo novo." : "Comece na aba Registrar: escreva algo ou importe uma conversa."));
      return lista.append(v);
    }
    memorias.forEach((m) => lista.append(itemMemoria(m)));
  } catch (err) {
    lista.replaceChildren(el("li", "vazio", "⚠️ " + err.message));
  }
}

function itemMemoria(m) {
  const li = el("li", "item");
  const quando = new Date(m.criado_em).toLocaleDateString("pt-BR");
  const info = el("span", "item-info");
  info.append(el("span", "etiqueta", m.categoria),
              el("span", null, m.data_evento ? `${m.data_evento} · salvo em ${quando}` : `salvo em ${quando}`));
  const acoes = el("div", "acoes");
  const caixaChunks = el("ol", "lista-chunks");
  caixaChunks.hidden = true;

  acoes.append(
    botao("Chunks", "botao-texto", async () => {
      if (!caixaChunks.hidden) return (caixaChunks.hidden = true);
      try {
        const ch = await chamar(`/memorias/${m.id}/chunks`);
        desenharChunks(caixaChunks, ch.map((c) => c.texto));
        caixaChunks.hidden = false;
      } catch (err) { avisar(err.message); }
    }, "layers"),
    botao("Editar", "botao-texto", () => li.replaceWith(formEdicao(m)), "edit"),
    botao("Apagar", "botao-texto apagar", async () => {
      if (!confirm("Apagar esta memória? Não dá para desfazer.")) return;
      try {
        await chamar(`/memorias/${m.id}`, { metodo: "DELETE" });
        li.remove();
        avisar("Memória apagada");
        carregarCategorias().catch(() => {});
        if (!$("#lista-memorias").children.length) carregarMemorias();
      } catch (err) { avisar(err.message); }
    }, "trash")
  );
  const rodape = el("div", "item-rodape");
  rodape.append(info, acoes);
  li.append(el("p", "item-texto", m.texto), rodape, caixaChunks);
  return li;
}

function formEdicao(m) {
  const li = el("li", "item editando");
  const texto = el("textarea");
  texto.rows = 5;
  texto.value = m.texto;
  const cat = el("select");
  categorias.forEach((c) => cat.append(new Option(rotulo(c.nome), c.nome)));
  cat.value = m.categoria;
  const data = el("input");
  data.placeholder = "Quando aconteceu? (opcional)";
  data.value = m.data_evento || "";
  const erro = el("p", "erro");
  const acoes = el("div", "acoes");
  acoes.append(
    botao("Cancelar", "botao-texto", () => li.replaceWith(itemMemoria(m))),
    botao("Salvar", "botao primario pequeno", async (ev) => {
      ev.target.disabled = true;
      try {
        const r = await chamar(`/memorias/${m.id}`, { metodo: "PUT",
          corpo: { texto: texto.value, categoria: cat.value, data_evento: data.value } });
        avisar(r.recalculou ? "Salvo ✓ (texto mudou: chunks e vetores refeitos)" : "Salvo ✓ (só rótulos; vetores mantidos)");
        Object.assign(m, { texto: texto.value, categoria: cat.value, data_evento: data.value });
        li.replaceWith(itemMemoria(m));
        carregarCategorias().catch(() => {});
      } catch (err) {
        erro.textContent = err.message;
        ev.target.disabled = false;
      }
    })
  );
  li.append(texto, cat, data, erro, acoes);
  queueMicrotask(() => aprimorarSelect(cat));
  return li;
}

function desenharChunks(caixa, textos) {
  caixa.replaceChildren();
  textos.forEach((t, i) => {
    const item = el("li", "chunk");
    item.append(el("span", "fonte-meta", `chunk ${i + 1} · ${t.length} caracteres`), document.createTextNode(t));
    caixa.append(item);
  });
}

// ---------------- Ajustes: configuração do RAG ----------------
const FAIXAS = ["chunk_size", "chunk_overlap", "top_k", "margem_relevancia"];
let configCarregada = null;

function atualizarSaidas() {
  const f = $("#form-config");
  FAIXAS.forEach((n) => {
    const v = Number(f[n].value);
    $(`#out-${n}`).textContent = n === "margem_relevancia" ? v.toFixed(2) : n.startsWith("chunk") ? `${v} caracteres` : v;
  });
  // a sobreposição precisa ser menor que metade do chunk
  f.chunk_overlap.max = Math.floor((Number(f.chunk_size.value) - 1) / 2);
}
FAIXAS.forEach((n) => $(`#cfg-${n}`).addEventListener("input", atualizarSaidas));

async function carregarConfig() {
  try {
    const c = await chamar("/config");
    configCarregada = c;
    const f = $("#form-config");
    const sel = $("#cfg-modelo_llm");
    sel.replaceChildren();
    Object.entries(c.modelos_llm).forEach(([id, desc]) => sel.append(new Option(desc, id)));
    FAIXAS.forEach((n) => (f[n].value = c[n]));
    atualizarSaidas();
    f.chunk_overlap.value = c.chunk_overlap;
    atualizarSaidas();
    f.usar_ia.checked = c.usar_ia;
    f.modo_agente.checked = c.modo_agente;
    f.modelo_llm.value = c.modelo_llm;
    f.instrucoes.value = c.instrucoes;
    $("#perfil-estilo").value = c.perfil_estilo || "";
    const ro = c.somente_leitura;
    $("#info-embedding").textContent =
      `Modelo de embeddings: ${ro.modelo_embedding} (${ro.dimensao_embedding} dimensões). ` +
      "Não muda pelo app: trocar de modelo exige refazer os vetores de todos os usuários.";
  } catch (err) { avisar(err.message); }
}

$("#form-config").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  $("#erro-config").textContent = "";
  const corpo = {
    chunk_size: Number(f.chunk_size.value), chunk_overlap: Number(f.chunk_overlap.value),
    top_k: Number(f.top_k.value), margem_relevancia: Number(f.margem_relevancia.value),
    usar_ia: f.usar_ia.checked, modo_agente: f.modo_agente.checked, modelo_llm: f.modelo_llm.value, instrucoes: f.instrucoes.value,
    perfil_estilo: $("#perfil-estilo").value,
  };
  try {
    await chamar("/config", { metodo: "PUT", corpo });
    const mudouChunk = configCarregada &&
      (corpo.chunk_size !== configCarregada.chunk_size || corpo.chunk_overlap !== configCarregada.chunk_overlap);
    configCarregada = { ...configCarregada, ...corpo };
    avisar(mudouChunk ? "Salvo ✓ — reprocesse as memórias para aplicar o novo chunk" : "Configurações salvas ✓");
  } catch (err) {
    $("#erro-config").textContent = err.message;
  }
});

$("#aprender-perfil").addEventListener("click", async (e) => {
  const b = e.currentTarget;
  b.disabled = true;
  b.querySelector("span").textContent = "Aprendendo…";
  try {
    const r = await chamar("/perfil/aprender", { metodo: "POST" });
    $("#perfil-estilo").value = r.perfil_estilo;
    avisar("Perfil atualizado ✨");
  } catch (err) { avisar(err.message); }
  b.disabled = false;
  b.querySelector("span").textContent = "Aprender agora";
});

$("#salvar-perfil").addEventListener("click", () => $("#form-config").requestSubmit());

$("#reprocessar").addEventListener("click", async (e) => {
  if (!confirm("Refazer os chunks e vetores de todas as suas memórias com a configuração atual?")) return;
  e.target.disabled = true;
  e.target.textContent = "Reprocessando…";
  try {
    const r = await chamar("/memorias/reprocessar", { metodo: "POST" });
    avisar(`${r.memorias} memória(s) reprocessada(s) em ${r.chunks} chunk(s)`);
  } catch (err) { avisar(err.message); }
  e.target.disabled = false;
  e.target.textContent = "Reprocessar todas as memórias";
});

// ---------------- Ajustes: laboratório ----------------
$("#lab-testar").addEventListener("click", async () => {
  const f = $("#form-config");
  const texto = $("#lab-texto").value;
  if (!texto.trim()) return avisar("Cole um texto primeiro.");
  try {
    const r = await chamar("/lab/chunking", { metodo: "POST",
      corpo: { texto, chunk_size: Number(f.chunk_size.value), chunk_overlap: Number(f.chunk_overlap.value) } });
    $("#lab-resumo").textContent =
      `${r.total} chunk(s) com tamanho ${f.chunk_size.value} e sobreposição ${f.chunk_overlap.value}`;
    desenharChunks($("#lab-chunks"), r.chunks);
  } catch (err) { avisar(err.message); }
});

// ---------------- Início ----------------
$$("select").forEach(aprimorarSelect);
// caixas de texto crescem conforme se escreve (para navegadores sem "field-sizing")
document.addEventListener("input", (e) => {
  if (e.target.tagName !== "TEXTAREA" || CSS.supports("field-sizing", "content")) return;
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight + 2, innerHeight * 0.45) + "px";
});
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
sessao.get()?.access_token ? mostrarApp() : mostrarAuth();
