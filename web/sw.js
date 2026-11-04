// Service worker do Lembra.
// Guarda só a "casca" do app (telas, estilos, ícones) para abrir rápido.
// NUNCA guarda dados da API (memórias, respostas): privacidade.
const VERSAO = "lembra-v12";
const CASCA = ["./", "index.html", "styles.css", "app.js", "config.js", "manifest.webmanifest",
               "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSAO).then((c) => c.addAll(CASCA)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(nomes.filter((n) => n !== VERSAO).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  const ehCasca = e.request.method === "GET" && url.origin === location.origin &&
                  CASCA.some((p) => url.pathname.endsWith(p.replace("./", "/")));
  if (!ehCasca) return; // API e qualquer outra coisa: sempre direto da rede, sem cache

  // Rede primeiro (pega atualizações); se estiver offline, usa a cópia guardada.
  e.respondWith(
    fetch(e.request)
      .then((r) => { const copia = r.clone(); caches.open(VERSAO).then((c) => c.put(e.request, copia)); return r; })
      .catch(() => caches.match(e.request))
  );
});
