/* El panel de mcp-correo.
 *
 * Sin framework: son cuatro rutas y una tabla. El JavaScript pide la
 * lista, la pinta y manda los cambios.
 */

const CABECERA = { "X-MCP-Dashboard": "1" };

let dominios = [];

const $ = (sel) => document.querySelector(sel);

async function pedir(ruta, opciones = {}) {
  const respuesta = await fetch(ruta, {
    ...opciones,
    headers: { "Content-Type": "application/json", ...CABECERA, ...(opciones.headers || {}) },
  });
  let cuerpo = {};
  try {
    cuerpo = await respuesta.json();
  } catch (error) {
    cuerpo = { ok: false, error: `El servidor respondió ${respuesta.status}.` };
  }
  return cuerpo;
}

function avisar(texto, clase = "") {
  const aviso = $("#aviso");
  aviso.textContent = texto;
  aviso.className = `aviso ${clase}`;
  aviso.hidden = !texto;
}

function texto(valor, defecto = "") {
  return valor === null || valor === undefined ? defecto : String(valor);
}

function tri(valor) {
  if (valor === true) return "sí";
  if (valor === false) return "no";
  return "hereda";
}

/* --- pintado ---------------------------------------------------------------- */

function pintar() {
  const contenedor = $("#dominios");
  contenedor.innerHTML = "";
  $("#vacio").hidden = dominios.length > 0;

  const porDefecto = dominios.find((d) => d.default);
  $("#destacado").textContent = porDefecto
    ? `La ruta /mcp abre el dominio ${porDefecto.name}.`
    : "No hay dominio por defecto: la ruta /mcp solo muestra la guía.";

  for (const dominio of dominios) {
    const caja = document.createElement("section");
    caja.className = "dominio";

    const cabecera = document.createElement("header");
    const titulo = document.createElement("h3");
    titulo.textContent = dominio.name + (dominio.default ? " (por defecto)" : "");
    const botones = document.createElement("div");
    botones.className = "fila";
    botones.append(
      boton(dominio.default ? "Quitar del todo" : "Marcar por defecto", () => porDefecto(dominio)),
      boton("Token", () => rotar("dominio", dominio.id)),
      boton("Editar", () => editarDominio(dominio)),
      boton("Cuenta", () => editarCuenta(null, dominio.id)),
      boton("Borrar", () => borrar("dominio", dominio.id, `el dominio ${dominio.name}`))
    );
    cabecera.append(titulo, botones);
    caja.append(cabecera);

    for (const cuenta of dominio.accounts) {
      caja.append(pintarCuenta(cuenta));
    }
    contenedor.append(caja);
  }
}

function pintarCuenta(cuenta) {
  const fila = document.createElement("div");
  fila.className = "cuenta";
  if (!cuenta.enabled) fila.classList.add("inactivo");

  const nombre = document.createElement("strong");
  nombre.textContent = cuenta.name;
  const ruta = document.createElement("span");
  ruta.className = "ruta";
  ruta.textContent = cuenta.route;
  const detalle = document.createElement("span");
  detalle.className = "pista";
  detalle.textContent = `envía:${tri(cuenta.allow_send)} marca:${tri(cuenta.allow_mark)} borra:${tri(
    cuenta.allow_delete
  )}`;

  const botones = document.createElement("div");
  botones.className = "fila";
  botones.append(
    boton("Token", () => rotar("cuenta", cuenta.id)),
    boton("Editar", () => editarCuenta(cuenta, cuenta.domain_id)),
    boton(cuenta.enabled ? "Desactivar" : "Activar", () => activar(cuenta)),
    boton("Borrar", () => borrar("cuenta", cuenta.id, `la cuenta ${cuenta.name}`))
  );

  fila.append(nombre, ruta, detalle, botones);
  return fila;
}

function boton(texto, accion) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = texto;
  b.addEventListener("click", accion);
  return b;
}

/* --- acciones ---------------------------------------------------------------- */

async function cargar() {
  const cuerpo = await pedir("/api/domains");
  if (!cuerpo.ok) {
    avisar(cuerpo.error || "No se pudo cargar la lista.", "error");
    return;
  }
  dominios = cuerpo.domains || [];
  pintar();
}

async function porDefecto(dominio) {
  const cuerpo = await pedir(`/api/domains/${dominio.id}/default`, { method: "POST" });
  if (!cuerpo.ok) return avisar(cuerpo.error, "error");
  avisar(`El dominio ${dominio.name} abre ahora la ruta /mcp.`, "ok");
  await cargar();
}

async function rotar(nivel, id) {
  const cuerpo = await pedir(`/api/${nivel}s/${id}/token`, { method: "POST" });
  if (!cuerpo.ok) return avisar(cuerpo.error, "error");
  mostrarToken(cuerpo.token);
}

function mostrarToken(token) {
  const aviso = $("#aviso");
  aviso.textContent = `Token nuevo: ${token} — cópialo, no se vuelve a mostrar.`;
  aviso.className = "aviso ok";
  aviso.hidden = false;
}

async function activar(cuenta) {
  const cuerpo = await pedir(`/api/accounts/${cuenta.id}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled: !cuenta.enabled }),
  });
  if (!cuerpo.ok) return avisar(cuerpo.error, "error");
  await cargar();
}

async function borrar(nivel, id, que) {
  if (!confirm(`¿Borrar ${que}?`)) return;
  const cuerpo = await pedir(`/api/${nivel}s/${id}`, { method: "DELETE" });
  if (!cuerpo.ok) return avisar(cuerpo.error, "error");
  avisar(`Se ha borrado ${que}.`, "ok");
  await cargar();
}

/* --- el editor --------------------------------------------------------------- */

let guardando = null;

function campo(etiqueta, control) {
  const caja = document.createElement("div");
  caja.className = "campo";
  const label = document.createElement("label");
  label.textContent = etiqueta;
  caja.append(label, control);
  return caja;
}

function entrada(tipo, valor = "", nombre = "") {
  const input = document.createElement("input");
  input.type = tipo;
  input.value = valor ?? "";
  if (nombre) input.name = nombre;
  return input;
}

function editor(titulo, campos, alGuardar, alProbar) {
  const dialogo = $("#editor");
  $("#titulo").textContent = titulo;
  const contenedor = $("#campos");
  contenedor.innerHTML = "";
  for (const c of campos) contenedor.append(c);
  $("#resultado").textContent = "";
  guardando = alGuardar;
  $("#probar").onclick = alProbar || null;
  $("#probar").hidden = !alProbar;
  dialogo.showModal();
  return dialogo;
}

function editarDominio(dominio) {
  const nombre = entrada("text", dominio.name);
  const etiqueta = entrada("text", dominio.label);
  const imap = entrada("text", dominio.imap_host);
  const smtp = entrada("text", dominio.smtp_host);
  editor(
    "Dominio",
    [
      campo("Nombre (corp.example.com)", nombre),
      campo("Etiqueta", etiqueta),
      campo("Servidor IMAP por defecto", imap),
      campo("Servidor SMTP por defecto", smtp),
    ],
    async () => {
      const cuerpo = {
        name: nombre.value,
        label: etiqueta.value,
        imap_host: imap.value,
        smtp_host: smtp.value,
      };
      const respuesta = dominio
        ? await pedir(`/api/domains/${dominio.id}`, { method: "PATCH", body: JSON.stringify(cuerpo) })
        : await pedir("/api/domains", { method: "POST", body: JSON.stringify(cuerpo) });
      if (!respuesta.ok) {
        $("#resultado").textContent = respuesta.error;
        return false;
      }
      avisar("Dominio guardado.", "ok");
      await cargar();
      return true;
    }
  );
}

function editarCuenta(cuenta, dominioId) {
  const dominios_ = dominios;
  const selector = document.createElement("select");
  for (const d of dominios_) {
    const opcion = document.createElement("option");
    opcion.value = String(d.id);
    opcion.textContent = d.name;
    if (d.id === (cuenta ? cuenta.domain_id : dominioId)) opcion.selected = true;
    selector.append(opcion);
  }
  const nombre = entrada("text", cuenta ? cuenta.name : "");
  const etiqueta = entrada("text", cuenta ? cuenta.label : "");
  const usuario = entrada("text", cuenta ? cuenta.user : "");
  const contrasena = entrada("password", "");
  const remitente = entrada("text", cuenta ? cuenta.sender : "");
  const imap = entrada("text", cuenta ? cuenta.imap_host : "");
  const smtp = entrada("text", cuenta ? cuenta.smtp_host : "");

  const recoger = () => ({
    domain_id: Number(selector.value),
    name: nombre.value,
    label: etiqueta.value,
    username: usuario.value,
    sender: remitente.value,
    imap_host: imap.value,
    smtp_host: smtp.value,
    password: contrasena.value,
  });

  editor(
    "Cuenta",
    [
      campo("Dominio", selector),
      campo("Nombre de la ruta (ada@corp.example.com)", nombre),
      campo("Etiqueta", etiqueta),
      campo("Usuario", usuario),
      campo("Contraseña del correo", contrasena),
      campo("Nombre visible del remitente", remitente),
      campo("Servidor IMAP (vacío = el del dominio)", imap),
      campo("Servidor SMTP (vacío = el del dominio)", smtp),
    ],
    async () => {
      const cuerpo = recoger();
      const respuesta = cuenta
        ? await pedir(`/api/accounts/${cuenta.id}`, { method: "PATCH", body: JSON.stringify(cuerpo) })
        : await pedir("/api/accounts", { method: "POST", body: JSON.stringify(cuerpo) });
      if (!respuesta.ok) {
        $("#resultado").textContent = respuesta.error;
        return false;
      }
      avisar("Cuenta guardada.", "ok");
      await cargar();
      return true;
    },
    async () => {
      const cuerpo = recoger();
      const imap_ = await pedir("/api/test/imap", { method: "POST", body: JSON.stringify(cuerpo) });
      $("#resultado").textContent = imap_.ok
        ? `IMAP: ${imap_.detail}`
        : `IMAP: ${imap_.error}`;
    }
  );
}

/* --- arranque ---------------------------------------------------------------- */

$("#formulario").addEventListener("submit", async (evento) => {
  if (evento.submitter && evento.submitter.value === "cancelar") return;
  evento.preventDefault();
  if (guardando) {
    const ok = await guardando();
    if (ok) $("#editor").close();
  }
});

$("#nuevo-dominio").addEventListener("click", () => editarDominio(null));
$("#nueva-cuenta").addEventListener("click", () => {
  if (!dominios.length) {
    avisar("Primero crea un dominio.", "error");
    return;
  }
  editarCuenta(null, dominios[0].id);
});

cargar();
