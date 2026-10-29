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

/* --- pintado ---------------------------------------------------------------- */

function pintar() {
  const contenedor = $("#dominios");
  contenedor.innerHTML = "";
  $("#vacio").hidden = dominios.length > 0;

  const dominioPrincipal = dominios.find((d) => d.default);
  $("#destacado").textContent = dominioPrincipal
    ? `Dominio principal: ${dominioPrincipal.name}. Sus cuentas están disponibles en la ruta principal.`
    : "Elige un dominio principal para acceder a sus cuentas desde la ruta principal.";

  for (const dominio of dominios) {
    const caja = document.createElement("section");
    caja.className = "dominio";

    const cabecera = document.createElement("header");
    const titulo = document.createElement("h3");
    titulo.textContent = dominio.name + (dominio.default ? " (por defecto)" : "");
    const botones = document.createElement("div");
    botones.className = "fila";
    botones.append(
      ...(dominio.default ? [] : [boton("Hacer principal", () => porDefecto(dominio))]),
      boton("Añadir cuenta", () => editarCuenta(null, dominio.id)),
      boton("Editar dominio", () => editarDominio(dominio)),
      boton("Renovar clave de acceso", () => rotar("domains", dominio.id)),
      boton("Eliminar dominio", () => borrar("domains", dominio.id, `el dominio ${dominio.name} y todas sus cuentas`))
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
  detalle.textContent = cuenta.enabled ? "Cuenta activa" : "Cuenta desactivada";

  const botones = document.createElement("div");
  botones.className = "fila";
  botones.append(
    boton("Renovar clave de acceso", () => rotar("accounts", cuenta.id)),
    boton("Editar", () => editarCuenta(cuenta, cuenta.domain_id)),
    boton(cuenta.enabled ? "Desactivar" : "Activar", () => activar(cuenta)),
    boton("Eliminar", () => borrar("accounts", cuenta.id, `la cuenta ${cuenta.name}`))
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

async function rotar(recurso, id) {
  if (!confirm("Al renovar la clave, la anterior dejará de funcionar. ¿Continuar?")) return;
  const cuerpo = await pedir(`/api/${recurso}/${id}/token`, { method: "POST" });
  if (!cuerpo.ok) return avisar(cuerpo.error, "error");
  mostrarToken(cuerpo.token);
}

function mostrarToken(token) {
  const aviso = $("#aviso");
  aviso.textContent = `Tu nueva clave de acceso: ${token} — cópiala y guárdala en un lugar seguro. No volverá a mostrarse.`;
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

async function borrar(recurso, id, que) {
  if (!confirm(`¿Borrar ${que}?`)) return;
  const cuerpo = await pedir(`/api/${recurso}/${id}`, { method: "DELETE" });
  if (!cuerpo.ok) return avisar(cuerpo.error, "error");
  avisar(`Se ha borrado ${que}.`, "ok");
  await cargar();
}

/* --- el editor --------------------------------------------------------------- */

let guardando = null;
let numeroCampo = 0;

function campo(etiqueta, control) {
  const caja = document.createElement("div");
  caja.className = "campo";
  const label = document.createElement("label");
  label.textContent = etiqueta;
  const id = `campo-${++numeroCampo}`;
  control.id = id;
  label.htmlFor = id;
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

/* Los permisos de escritura son un tri-estado: heredar (sin definir),
 * permitir (true) o prohibir (false). Heredar es lo que deja que el
 * dominio y el global manden, como el resto de la configuración.
 */
function permisosEscritos(valores) {
  const caja = document.createElement("div");
  caja.className = "campo inline";
  const select = document.createElement("select");
  for (const texto of ["Heredar", "Permitir", "Prohibir"]) {
    const opcion = document.createElement("option");
    opcion.value = texto;
    opcion.textContent = texto;
    select.append(opcion);
  }
  if (valores === true) select.value = "Permitir";
  else if (valores === false) select.value = "Prohibir";
  else select.value = "Heredar";
  const label = document.createElement("label");
  label.textContent = "Permisos de escritura";
  caja.append(label, select);
  return { caja, select };
}

function leerPermisos(select) {
  if (select.value === "Permitir") return true;
  if (select.value === "Prohibir") return false;
  return null;
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
  const nombre = entrada("text", dominio?.name || "");
  const etiqueta = entrada("text", dominio?.label || "");
  const imap = entrada("text", dominio?.imap_host || "");
  const smtp = entrada("text", dominio?.smtp_host || "");
  const permisos = permisosEscritos(dominio?.allow_send);
  const directos = permisosEscritos(dominio?.allow_direct_send);
  editor(
    "Dominio",
    [
      campo("Dominio de correo (por ejemplo, example.com)", nombre),
      campo("Nombre para identificarlo (opcional)", etiqueta),
      campo("Servidor de correo entrante (IMAP)", imap),
      campo("Servidor de correo saliente (SMTP)", smtp),
      permisos.caja,
      directos.caja,
    ],
    async () => {
      const cuerpo = {
        name: nombre.value,
        label: etiqueta.value,
        imap_host: imap.value,
        smtp_host: smtp.value,
        allow_send: leerPermisos(permisos.select),
        allow_direct_send: leerPermisos(directos.select),
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
  const permisos = permisosEscritos(cuenta ? cuenta.allow_send : null);
  const directos = permisosEscritos(cuenta ? cuenta.allow_direct_send : null);

  const correo = entrada("email", cuenta ? cuenta.user : "");
  correo.placeholder = "ada@example.com";
  correo.required = true;
  correo.autocomplete = "email";
  contrasena.autocomplete = "new-password";
  contrasena.required = !cuenta;
  contrasena.placeholder = cuenta ? "Déjala vacía para conservar la actual" : "Contraseña de tu buzón";
  // Al crear, el alias de ruta y el usuario se toman del correo. Al
  // editar, el alias se conserva: es su identificador en /mcp, y no tiene
  // por qué cambiar porque se edite el usuario de conexión.
  if (!cuenta) {
    nombre.value = "";
    usuario.value = "";
  }
  nombre.placeholder = "Se usa tu correo automáticamente";
  usuario.placeholder = "Solo si es distinto de tu correo";
  correo.addEventListener("input", () => {
    if (cuenta) return;
    const dominio = dominios.find((d) => d.name.toLowerCase() === correo.value.split("@")[1]?.toLowerCase());
    if (dominio) selector.value = String(dominio.id);
  });
  const avanzadas = document.createElement("details");
  avanzadas.className = "opciones-avanzadas";
  const resumen = document.createElement("summary");
  resumen.textContent = "Opciones avanzadas";
  const ayuda = document.createElement("p");
  ayuda.className = "pista";
  ayuda.textContent = "Normalmente no necesitas cambiarlas. Los servidores se toman del dominio seleccionado.";
  const ayudaPermisos = document.createElement("p");
  ayudaPermisos.className = "pista";
  ayudaPermisos.textContent =
    "Envío: exige una confirmación por mensaje. Envío directo: envía en una sola llamada, sin confirmación por mensaje, y solo para rutinas automáticas.";
  avanzadas.append(resumen, ayuda, ayudaPermisos,
    campo("Alias de la ruta (opcional)", nombre),
    campo("Nombre de la cuenta en el panel (opcional)", etiqueta),
    campo("Usuario de conexión diferente (opcional)", usuario),
    campo("Servidor entrante IMAP (opcional)", imap),
    campo("Servidor saliente SMTP (opcional)", smtp),
    permisos.caja,
    directos.caja);

  const recoger = () => ({
    domain_id: Number(selector.value),
    name: nombre.value.trim() || (cuenta ? cuenta.name : correo.value.trim()),
    label: etiqueta.value,
    username: usuario.value.trim() || correo.value.trim(),
    sender: remitente.value,
    imap_host: imap.value,
    smtp_host: smtp.value,
    password: contrasena.value,
    allow_send: leerPermisos(permisos.select),
    allow_direct_send: leerPermisos(directos.select),
  });

  editor(
    cuenta ? "Editar cuenta de correo" : "Añadir cuenta de correo",
    [
      campo("Dominio", selector),
      campo("Dirección de correo", correo),
      campo("Contraseña del correo", contrasena),
      campo("Tu nombre al enviar correos (opcional)", remitente),
      avanzadas,
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
      if (respuesta.token) mostrarToken(respuesta.token);
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

$(".salir").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  await fetch("/logout", { method: "POST", headers: CABECERA });
  window.location.assign("/login");
});

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
