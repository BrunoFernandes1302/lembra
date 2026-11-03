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

$$(".segmento").forEach((s) =>
  s.addEventListener("click", () => {
    $$(".segmento").forEach((x) => x.classList.toggle("ativo", x === s));
    ["rag", "lab", "cats"].forEach((n) => ($(`#sub-${n}`).hidden = n !== s.dataset.sub));
    if (s.dataset.sub === "cats") desenharCategorias();
  })
);

// ---------------- Categorias (do banco) ----------------
let categoriaEscolhida = "geral";

async function carregarCategorias() {
  categorias = await chamar("/categorias");
  if (!categorias.some((c) => c.nome === categoriaEscolhida)) categoriaEscolhida = "geral";
  desenharChips();
  preencherSelect($("#form-perguntar").categoria, "Procurar em: todas");
  preencherSelect($("#filtro-memorias"), "Todas");
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
    avisar(`Memória salva ✓ (${r.chunks} chunk${r.chunks > 1 ? "s" : ""})`);
    carregarCategorias().catch(() => {});
  } catch (err) {
    erro.textContent = err.message;
  } finally {
    b.disabled = false;
    b.querySelector("span").textContent = "Salvar memória";
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
    pensando.textContent = r.resposta;
    if (r.fontes.length) {
      const det = el("details", "fontes");
      det.open = !r.gerada_por_ia; // sem IA, as memórias SÃO a resposta: já mostra abertas
      det.append(el("summary", null, `${r.fontes.length} memória(s) usada(s)`));
      r.fontes.forEach((fo, i) => {
        const d = el("div", "fonte");
        const meta = [`[${i + 1}]`, fo.categoria, fo.data].filter(Boolean).join(" · ");
        const cab = el("span", "fonte-meta");
        cab.append(document.createTextNode(meta + " "), el("span", "nota", `similaridade ${fo.similaridade.toFixed(2)}`));
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
    f.modelo_llm.value = c.modelo_llm;
    f.instrucoes.value = c.instrucoes;
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
    usar_ia: f.usar_ia.checked, modelo_llm: f.modelo_llm.value, instrucoes: f.instrucoes.value,
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
    const r = await chamar("/lab/chunking", { metodo: "POST", autenticado: false,
      corpo: { texto, chunk_size: Number(f.chunk_size.value), chunk_overlap: Number(f.chunk_overlap.value) } });
    $("#lab-resumo").textContent =
      `${r.total} chunk(s) com tamanho ${f.chunk_size.value} e sobreposição ${f.chunk_overlap.value}`;
    desenharChunks($("#lab-chunks"), r.chunks);
  } catch (err) { avisar(err.message); }
});

// ---------------- Início ----------------
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
sessao.get()?.access_token ? mostrarApp() : mostrarAuth();
