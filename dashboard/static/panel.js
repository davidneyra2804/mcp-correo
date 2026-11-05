/* El panel de mcp-correo.
 *
 * Sin framework: son cuatro rutas y una tabla. El JavaScript pide la
 * lista, la pinta y manda los cambios.
 *
 * La interfaz se organiza así: cada dominio es un acordeón (el principal
 * viene abierto), las acciones normales están a la vista y las que rompen
 * algo —eliminar, desactivar, renovar la clave— quedan en un menú de
 * "más opciones", con su confirmación delante.
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

/* --- la ayuda ---------------------------------------------------------------- */

/* El signo de interrogación con su explicación. Se usa como botón para
 * que el teclado también lo abra, y con `aria-describedby` para que un
 * lector de pantalla lo lea.
 */
function conAyuda(explicacion, etiqueta = "¿") {
  const ayuda = document.createElement("span");
  ayuda.className = "con-ayuda";
  ayuda.tabIndex = 0;
  ayuda.setAttribute("role", "button");
  ayuda.setAttribute("aria-label", `Ayuda: ${explicacion}`);
  ayuda.dataset.ayuda = explicacion;
  ayuda.textContent = etiqueta;
  return ayuda;
}

/* --- la confirmación ---------------------------------------------------------- */

/* Un diálogo propio en vez de `confirm()`: el `confirm()` del navegador
 * no se puede estilar, no explica bien qué va a pasar y no se puede
 * traducir con el resto de la interfaz.
 */
function confirmar({ titulo, mensaje, confirmar: textoConfirmar, peligro = true }) {
  /* El control que abrió el diálogo. Al cerrarse, el foco vuelve a él:
   * si no, quien está con el teclado se queda perdido en el cuerpo de la
   * página. */
  const abridor = document.activeElement;

  return new Promise((resolver) => {
    const dialogo = document.createElement("dialog");
    dialogo.className = "confirmacion";

    const cabecera = document.createElement("h2");
    cabecera.textContent = titulo;

    const cuerpo = document.createElement("p");
    cuerpo.className = "confirmacion-mensaje";
    cuerpo.textContent = mensaje;

    const botones = document.createElement("menu");
    const cancelar = document.createElement("button");
    cancelar.type = "button";
    cancelar.className = "secundario";
    cancelar.textContent = "Cancelar";
    const aceptar = document.createElement("button");
    aceptar.type = "button";
    aceptar.className = peligro ? "peligro-solido" : "primario";
    aceptar.textContent = textoConfirmar;

    botones.append(cancelar, aceptar);
    dialogo.append(cabecera, cuerpo, botones);
    document.body.append(dialogo);

    const cerrar = (respuesta) => {
      dialogo.close();
      dialogo.remove();
      /* El foco vuelve a donde estaba. Si ese control ya no existe (la
       * lista se ha repintado mientras tanto), no se hace nada. */
      if (abridor && document.contains(abridor)) abridor.focus();
      resolver(respuesta);
    };

    cancelar.addEventListener("click", () => cerrar(false));
    aceptar.addEventListener("click", () => cerrar(true));
    // El Escape también cancela: es la forma de salir sin tocar nada.
    dialogo.addEventListener("cancel", (evento) => {
      evento.preventDefault();
      cerrar(false);
    });
    dialogo.addEventListener("click", (evento) => {
      // Un clic fuera del contenido cancela.
      if (evento.target === dialogo) cerrar(false);
    });

    dialogo.showModal();
    aceptar.focus();
  });
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
    contenedor.append(pintarDominio(dominio));
  }
}

function pintarDominio(dominio) {
  /* El acordeón: un `details` con su `summary`. El principal viene abierto
   * porque es el que se usa a diario; los demás, cerrados.
   *
   * El `summary` solo lleva texto: los botones y el menú van fuera, en una
   * fila propia. Meter controles interactivos dentro del disparador del
   * acordeón confunde al teclado y a los lectores de pantalla, porque el
   * `summary` ya es un control.
   *
   * El `details` contiene solo el `summary`. Las acciones y la lista de
   * cuentas son hermanas suyas, dentro del bloque: así las acciones se
   * ven aunque el dominio esté cerrado (dentro del `details` no se verían)
   * y el orden de lectura es cabecera, acciones y cuentas.
   *
   * La lista de cuentas se muestra con `:has()` cuando el `details` está
   * abierto. La alternativa —meter el cuerpo dentro del `details`— es lo
   * que escondía las acciones con el dominio cerrado.
   */
  const contenedor = document.createElement("div");
  contenedor.className = "dominio-bloque";

  const caja = document.createElement("details");
  caja.className = "dominio";
  caja.open = Boolean(dominio.default);

  /* El estado del acordeón, marcado también como atributo: así se puede
   * saber desde el DOM y desde CSS sin depender de `:has()`. */
  contenedor.dataset.abierto = caja.open ? "true" : "false";
  caja.addEventListener("toggle", () => {
    contenedor.dataset.abierto = caja.open ? "true" : "false";
  });

  const cabecera = document.createElement("summary");
  cabecera.className = "dominio-cabecera";
  cabecera.append(pintarCabeceraDominio(dominio));
  caja.append(cabecera);

  /* Las acciones del dominio, fuera del disparador y fuera del `details`. */
  const acciones = document.createElement("div");
  acciones.className = "dominio-acciones";
  acciones.append(pintarAccionesDominio(dominio));

  const cuerpo = document.createElement("div");
  cuerpo.className = "dominio-cuerpo";

  if (!dominio.accounts.length) {
    const vacio = document.createElement("p");
    vacio.className = "dominio-vacio";
    vacio.textContent = "Este dominio todavía no tiene cuentas.";
    cuerpo.append(vacio);
  } else {
    for (const cuenta of dominio.accounts) {
      cuerpo.append(pintarCuenta(cuenta));
    }
  }

  contenedor.append(caja, acciones, cuerpo);
  return contenedor;
}

function pintarCabeceraDominio(dominio) {
  /* Solo texto: esto va dentro del `summary`, que ya es un control. */
  const fragmento = document.createDocumentFragment();

  const chevron = document.createElement("span");
  chevron.className = "chevron";
  chevron.setAttribute("aria-hidden", "true");
  chevron.textContent = "▶";

  const nombre = document.createElement("span");
  nombre.className = "dominio-nombre";
  nombre.textContent = dominio.name;

  const etiqueta = document.createElement("span");
  if (dominio.default) {
    etiqueta.className = "etiqueta";
    etiqueta.textContent = "Principal";
    etiqueta.title = "Es el dominio que abre la ruta /mcp.";
  } else {
    etiqueta.className = "etiqueta neutra";
    etiqueta.textContent = "Secundario";
    etiqueta.title = "Se accede a sus cuentas por su propia ruta.";
  }

  const numero = document.createElement("span");
  numero.className = "numero";
  const cuentas = dominio.accounts.length;
  numero.textContent = cuentas === 1 ? "1 cuenta" : `${cuentas} cuentas`;

  fragmento.append(chevron, nombre, etiqueta, numero);
  return fragmento;
}

/* Las acciones del dominio. Van fuera del `summary`, en su propia fila:
 * dentro, serían controles anidados en el disparador del acordeón. */
function pintarAccionesDominio(dominio) {
  const acciones = document.createElement("div");
  acciones.className = "cuenta-acciones";
  acciones.append(
    boton("Añadir cuenta", () => editarCuenta(null, dominio.id), {
      ayuda: "Crea una cuenta de correo dentro de este dominio.",
    }),
    boton("Editar", () => editarDominio(dominio), {
      ayuda: "Cambia los datos del dominio: sus servidores y sus permisos.",
    }),
    menuMasOpciones([
      {
        texto: "Hacer principal",
        accion: () => porDefecto(dominio),
        ayuda: "Abre la ruta /mcp con las cuentas de este dominio.",
        oculto: dominio.default,
      },
      {
        texto: "Renovar clave de acceso",
        accion: () => rotar("domains", dominio.id),
        ayuda: "Genera una clave nueva. La anterior deja de funcionar.",
        peligro: true,
      },
      {
        texto: "Eliminar dominio",
        accion: () =>
          borrar(
            "domains",
            dominio.id,
            `el dominio ${dominio.name} y todas sus cuentas`,
            "Eliminar el dominio"
          ),
        ayuda: "Borra el dominio y todas sus cuentas. No se puede deshacer.",
        peligro: true,
      },
    ])
  );
  return acciones;
}

function pintarCuenta(cuenta) {
  const fila = document.createElement("div");
  fila.className = "cuenta";
  if (!cuenta.enabled) fila.classList.add("inactivo");

  const info = document.createElement("div");
  info.className = "cuenta-info";

  const nombre = document.createElement("span");
  nombre.className = "cuenta-nombre";
  nombre.textContent = cuenta.label || cuenta.name;

  const ruta = document.createElement("code");
  ruta.className = "cuenta-ruta";
  ruta.textContent = cuenta.route;
  ruta.title = "La ruta que se le pasa al cliente para usar esta cuenta.";

  const estado = document.createElement("span");
  estado.className = cuenta.enabled ? "estado activo" : "estado inactivo";
  estado.textContent = cuenta.enabled ? "Activa" : "Desactivada";

  info.append(nombre, ruta, estado);

  const acciones = document.createElement("div");
  acciones.className = "cuenta-acciones";
  acciones.append(
    botonCopiar(cuenta, "url", "Copiar URL", {
      ayuda: "Copia la URL completa del MCP de esta cuenta, lista para pegar en un cliente MCP.",
    }),
    botonCopiar(cuenta, "token", "Copiar token", {
      ayuda: "Copia el token de acceso vigente de esta cuenta, sin renovarlo.",
    }),
    boton("Editar", () => editarCuenta(cuenta, cuenta.domain_id), {
      ayuda: "Cambia los datos de la cuenta: su contraseña, su nombre o sus permisos.",
    }),
    menuMasOpciones([
      {
        texto: "Renovar clave de acceso",
        accion: () => rotar("accounts", cuenta.id),
        ayuda: "Genera una clave nueva para esta cuenta. La anterior deja de funcionar.",
        peligro: true,
      },
      {
        texto: cuenta.enabled ? "Desactivar" : "Activar",
        accion: () => activar(cuenta),
        ayuda: cuenta.enabled
          ? "Deja de exponer la cuenta. Sus datos siguen guardados."
          : "Vuelve a exponer la cuenta en su ruta.",
        peligro: cuenta.enabled,
      },
      {
        texto: "Eliminar cuenta",
        accion: () =>
          borrar(
            "accounts",
            cuenta.id,
            `la cuenta ${cuenta.name}`,
            "Eliminar la cuenta"
          ),
        ayuda: "Borra la cuenta. No se puede deshacer.",
        peligro: true,
      },
    ])
  );

  fila.append(info, acciones);
  return fila;
}

/* El botón de copiar: URL del MCP o token de la cuenta.
 *
 * No se pinta el valor en la página. Se pide a la API cuando quien lo
 * copia lo pide, y se pone en el portapapeles. El botón dice qué va a
 * copiar y, cuando lo ha copiado, lo confirma y vuelve a su estado.
 *
 * El token no se renueva: la ruta de credenciales devuelve el vigente.
 */
function botonCopiar(cuenta, que, textoBoton, opciones = {}) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "copiar";
  b.dataset.copiar = que;
  b.dataset.cuenta = cuenta.id;
  b.textContent = textoBoton;
  if (opciones.ayuda) {
    b.title = opciones.ayuda;
    b.setAttribute("aria-label", `${textoBoton}. ${opciones.ayuda}`);
  }
  b.addEventListener("click", () => copiar(cuenta, que, b, textoBoton));
  return b;
}

/* Copia un valor al portapapeles y lo confirma.
 *
 * Hay tres pasos, y el orden importa: primero se copia, después se
 * confirma. Si el portapapeles falla, no se dice «Copiado»: se avisa de
 * que no se pudo y se enseña el valor para copiarlo a mano. Decir
 * «Copiado» cuando no se copió es peor que no decir nada.
 */
async function copiar(cuenta, que, boton, textoBoton) {
  const estado = estadoDeCopia(boton);
  try {
    const cuerpo = await pedir(`/api/accounts/${cuenta.id}/credenciales`);
    if (!cuerpo.ok) {
      estado.error(cuerpo.error || "No se pudo leer la credencial de la cuenta.");
      return;
    }
    const valor = que === "url" ? cuerpo.url : cuerpo.token;
    if (!valor) {
      estado.error(
        que === "url"
          ? "Esta cuenta todavía no tiene URL de MCP."
          : "Esta cuenta no tiene token propio: usa el de su dominio."
      );
      return;
    }
    const copiado = await escribirEnElPortapapeles(valor);
    if (copiado) {
      estado.ok();
      return;
    }
    /* El portapapeles no estaba disponible: se enseña el valor para
     * copiarlo a mano, que es la alternativa que pedía el requisito. */
    estado.manual(valor);
  } catch (error) {
    estado.error("No se pudo copiar. Copia el valor a mano.");
  }
}

/* Escribe en el portapapeles y dice si pudo.
 *
 * `navigator.clipboard` necesita un contexto seguro y permiso. Cuando
 * no está, se intenta el camino viejo con un textarea oculto y
 * `execCommand`. Si tampoco, se devuelve false y quien llama avisa.
 */
async function escribirEnElPortapapeles(valor) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(valor);
      return true;
    }
  } catch (error) {
    /* Sigue al camino de abajo: el permiso puede estar denegado. */
  }
  try {
    const area = document.createElement("textarea");
    area.value = valor;
    area.setAttribute("readonly", "");
    area.className = "copiar-area";
    document.body.append(area);
    area.select();
    area.setSelectionRange(0, valor.length);
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  } catch (error) {
    return false;
  }
}

/* El estado del botón de copiar: lo normal, la confirmación y el fallo.
 *
 * El aviso del panel (#aviso) es el que anuncia el resultado a los lectores
 * de pantalla, porque es `role="status"`. El botón cambia su texto para
 * quien ve la pantalla, y el aviso explica lo que pasó.
 */
function estadoDeCopia(boton) {
  const original = boton.textContent;
  const aviso = $("#aviso");
  const ocultar = () => {
    boton.textContent = original;
    boton.classList.remove("copiado", "fallido");
    boton.removeAttribute("aria-live");
  };
  return {
    ok() {
      boton.textContent = "Copiado";
      boton.classList.add("copiado");
      boton.classList.remove("fallido");
      aviso.textContent = `${original}: copiado al portapapeles.`;
      aviso.className = "aviso aviso-ok";
      aviso.hidden = false;
      setTimeout(ocultar, 2200);
    },
    error(mensaje) {
      boton.textContent = "No se pudo";
      boton.classList.add("fallido");
      boton.classList.remove("copiado");
      aviso.textContent = mensaje;
      aviso.className = "aviso aviso-error";
      aviso.hidden = false;
      setTimeout(ocultar, 4200);
    },
    manual(valor) {
      boton.textContent = "Copia a mano";
      boton.classList.add("fallido");
      boton.classList.remove("copiado");
      aviso.textContent = `No se pudo usar el portapapeles. Copia a mano: ${valor}`;
      aviso.className = "aviso aviso-error aviso-valor";
      aviso.hidden = false;
      setTimeout(ocultar, 9000);
    },
  };
}

function boton(textoBoton, accion, opciones = {}) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = textoBoton;
  if (opciones.ayuda) {
    b.title = opciones.ayuda;
    b.setAttribute("aria-label", `${textoBoton}. ${opciones.ayuda}`);
  }
  b.addEventListener("click", accion);
  return b;
}

/* El menú de "más opciones": lo que no es la acción del día a día. Las
 * acciones que rompen algo van al final, separadas por una línea.
 *
 * Sigue el patrón de "menu button" del WAI-ARIA: el disparador es un
 * botón con `aria-haspopup="menu"`, la lista es un `role="menu"` y sus
 * entradas son `role="menuitem"`. Se navega con las flechas, con Inicio
 * y Fin, y Escape cierra y devuelve el foco al disparador.
 *
 * Los listeners de `document` son uno solo, compartidos por todos los
 * menús (ver `menuGlobal`), en vez de uno por menú: si no, se acumulan
 * con cada repintado de la lista.
 */
function menuMasOpciones(opciones) {
  const envoltorio = document.createElement("div");
  envoltorio.className = "menu-envoltorio";

  const disparador = document.createElement("button");
  disparador.type = "button";
  disparador.className = "menu";
  /* La elipsis horizontal es compatible con las fuentes de interfaz comunes;
   * el punto medio matemático (⋯) puede no tener glifo y dejar el botón vacío. */
  disparador.textContent = "…";
  disparador.setAttribute("aria-label", "Más opciones");
  disparador.setAttribute("aria-haspopup", "menu");
  disparador.setAttribute("aria-expanded", "false");
  disparador.title = "Más opciones: renovar la clave, desactivar o eliminar.";

  const lista = document.createElement("ul");
  lista.className = "menu-lista";
  lista.setAttribute("role", "menu");
  lista.setAttribute("aria-label", "Más opciones");
  lista.hidden = true;

  const visibles = opciones.filter((opcion) => !opcion.oculto);
  const normales = visibles.filter((opcion) => !opcion.peligro);
  const peligrosos = visibles.filter((opcion) => opcion.peligro);

  for (const opcion of normales) {
    lista.append(elementoMenu(opcion));
  }

  /* La línea y el aviso solo si hay algo normal encima: si el menú es
   * todo peligroso, la separación no aporta nada y ocupa sitio. */
  if (peligrosos.length) {
    if (normales.length) {
      const separador = document.createElement("li");
      separador.className = "menu-separador";
      separador.setAttribute("role", "separator");
      lista.append(separador);
    }

    const aviso = document.createElement("li");
    aviso.className = "menu-pista";
    aviso.textContent = "Estas acciones no se pueden deshacer.";
    aviso.setAttribute("role", "presentation");
    lista.append(aviso);

    for (const opcion of peligrosos) lista.append(elementoMenu(opcion));
  }

  /* El disparador lleva el `aria-controls` de su lista, para que se
   * pueda relacionar una con otra. */
  const idLista = `menu-${++numerosMenu}`;
  lista.id = idLista;
  disparador.setAttribute("aria-controls", idLista);

  const cerrar = (devolverFoco = false) => {
    lista.hidden = true;
    disparador.setAttribute("aria-expanded", "false");
    if (devolverFoco) disparador.focus();
  };

  const abrir = () => {
    lista.hidden = false;
    disparador.setAttribute("aria-expanded", "true");
    /* Al abrir, el foco va a la primera entrada: el menú se usa con el
     * teclado desde el principio. */
    const primera = lista.querySelector('[role="menuitem"]');
    if (primera) primera.focus();
  };

  const entradas = () =>
    [...lista.querySelectorAll('[role="menuitem"]')].filter((e) => !e.disabled);

  disparador.addEventListener("click", (evento) => {
    evento.stopPropagation();
    if (lista.hidden) {
      abrir();
      return;
    }
    cerrar();
  });

  disparador.addEventListener("keydown", (evento) => {
    /* Con el menú cerrado, las flechas lo abren directamente. */
    if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
      evento.preventDefault();
      abrir();
      const todas = entradas();
      const destino = evento.key === "ArrowDown" ? todas[0] : todas[todas.length - 1];
      if (destino) destino.focus();
    }
  });

  /* La navegación con teclado dentro del menú. */
  lista.addEventListener("keydown", (evento) => {
    const todas = entradas();
    if (!todas.length) return;
    const actual = todas.indexOf(document.activeElement);

    switch (evento.key) {
      case "ArrowDown":
        evento.preventDefault();
        todas[(actual + 1) % todas.length].focus();
        break;
      case "ArrowUp":
        evento.preventDefault();
        todas[(actual - 1 + todas.length) % todas.length].focus();
        break;
      case "Home":
        evento.preventDefault();
        todas[0].focus();
        break;
      case "End":
        evento.preventDefault();
        todas[todas.length - 1].focus();
        break;
      case "Escape":
        evento.preventDefault();
        evento.stopPropagation();
        cerrar(true);
        break;
      case "Tab":
        /* El Tab sale del menú. Como las entradas están fuera del orden
         * secuencial (tabindex="-1"), el navegador no calcula solo a
         * dónde va el foco: hay que carriedlo a mano.
         *
         * El destino se calcula desde el disparador, que es el control
         * que estaba en el orden de Tab antes de abrir el menú. Así el
         * foco sigue su camino natural: el siguiente control con Tab, el
         * anterior con Mayús+Tab. */
        evento.preventDefault();
        cerrar();
        moverFocoDesde(disparador, evento.shiftKey ? -1 : 1);
        break;
      default:
        break;
    }
  });

  envoltorio.append(disparador, lista);
  envoltorio.dataset.menu = "1";
  return envoltorio;
}

function elementoMenu(opcion) {
  const item = document.createElement("li");
  item.setAttribute("role", "none");
  const b = document.createElement("button");
  b.type = "button";
  b.className = opcion.peligro ? "peligro" : "";
  b.textContent = opcion.texto;
  b.setAttribute("role", "menuitem");
  /* Las entradas de un menú ARIA quedan fuera del orden secuencial de
   * Tab: se enfocan por código, con las flechas. Si no, el Tab se
   * saltaría entrada por entrada dentro del menú en vez de salir de
   * él. */
  b.tabIndex = -1;
  if (opcion.ayuda) {
    b.title = opcion.ayuda;
    b.setAttribute("aria-label", `${opcion.texto}. ${opcion.ayuda}`);
  }
  b.addEventListener("click", () => {
    /* El menú se cierra antes de la acción: si la acción abre un
     * diálogo, el menú no se queda detrás.
     *
     * Al cerrar se devuelve el foco al disparador. Si no, la entrada del
     * menú pierde el foco al ocultarse y el diálogo que abra la acción
     * no tendría a quién devolverlo. */
    const lista = b.closest(".menu-lista");
    const disparador = lista?.parentElement?.querySelector(".menu");
    if (lista) lista.hidden = true;
    /* `aria-expanded` vuelve a "false": el menú ya no está abierto. */
    if (disparador) {
      disparador.setAttribute("aria-expanded", "false");
      disparador.focus();
    }
    opcion.accion();
  });
  item.append(b);
  return item;
}

/* Un único par de listeners para todos los menús, en vez de uno por
 * menú. Se instalan una vez y atienden a cualquier menú que exista en el
 * documento, así que repintar la lista no deja listeners acumulados.
 */
let numerosMenu = 0;
let menuGlobalInstalado = false;

function menuGlobal() {
  if (menuGlobalInstalado) return;
  menuGlobalInstalado = true;

  /* Un clic fuera de un menú lo cierra. */
  document.addEventListener("click", (evento) => {
    for (const envoltorio of document.querySelectorAll(".menu-envoltorio")) {
      if (envoltorio.contains(evento.target)) continue;
      const lista = envoltorio.querySelector(".menu-lista");
      const disparador = envoltorio.querySelector(".menu");
      if (lista && !lista.hidden) {
        lista.hidden = true;
        if (disparador) disparador.setAttribute("aria-expanded", "false");
      }
    }
  });

  /* Escape cierra el menú abierto y devuelve el foco al disparador. */
  document.addEventListener("keydown", (evento) => {
    if (evento.key !== "Escape") return;
    for (const envoltorio of document.querySelectorAll(".menu-envoltorio")) {
      const lista = envoltorio.querySelector(".menu-lista");
      if (!lista || lista.hidden) continue;
      lista.hidden = true;
      const disparador = envoltorio.querySelector(".menu");
      if (disparador) {
        disparador.setAttribute("aria-expanded", "false");
        disparador.focus();
      }
    }
  });
}

/* --- el foco ------------------------------------------------------------------ */

/* Los controles que pueden recibir foco, en el orden en que los recorre
 * el Tab. Se calculan a mano porque, dentro de un menú ARIA, las entradas
 * están fuera de ese orden (`tabindex="-1"`) y el navegador no sabe a
 * dónde tiene que ir el foco cuando sale del menú.
 *
 * Los `summary` van incluidos: son controles nativos del acordeón y
 * reciben el foco con el Tab. Si no estuvieran, al salir de un menú se
 * saltaría la cabecera del dominio siguiente. */
const SELECTOR_FOCO =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

function controlesEnFoco() {
  return [...document.querySelectorAll(SELECTOR_FOCO)].filter((el) => {
    /* Lo que no se ve, no recibe el foco. */
    if (el.hidden) return false;
    if (el.closest("[hidden]")) return false;
    if (!el.getClientRects().length) return false;
    return el.getAttribute("aria-hidden") !== "true";
  });
}

/* Lleva el foco al control siguiente (o al anterior) al que `origen`,
 * como si el usuario hubiera pulsado Tab.
 *
 * Si no hay ningún control en esa dirección, el foco se queda en el
 * propio `origen`: es el control que estaba en el orden de Tab, así que
 * es donde pertenece. Dejarlo en la entrada del menú que se acaba de
 * ocultar lo dejaría en un elemento invisible. */
function moverFocoDesde(origen, sentido) {
  const controles = controlesEnFoco();
  const indice = controles.indexOf(origen);
  if (indice === -1) {
    /* El origen no está en la lista (puede que se haya repintado): el
     * foco se queda donde está, que es lo menos raro. */
    return;
  }
  const destino = controles[indice + sentido];
  if (destino) {
    destino.focus();
    return;
  }
  /* No hay a dónde ir: el foco vuelve al disparador, que es el control
   * que estaba en el orden de tabulación. */
  if (document.contains(origen)) origen.focus();
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
  const confirmado = await confirmar({
    titulo: "Renovar la clave de acceso",
    mensaje:
      "Se generará una clave nueva. La clave actual dejará de funcionar en el acto, " +
      "y quien la use tendrá que actualizarla.",
    confirmar: "Renovar la clave",
    peligro: true,
  });
  if (!confirmado) return;

  const cuerpo = await pedir(`/api/${recurso}/${id}/token`, { method: "POST" });
  if (!cuerpo.ok) return avisar(cuerpo.error, "error");
  mostrarToken(cuerpo.token);
}

function mostrarToken(token) {
  const aviso = $("#aviso");
  aviso.textContent = `Tu nueva clave de acceso: ${token} — cópiala y guárdala en un lugar seguro. No volverá a mostrarse.`;
  aviso.className = "aviso aviso-clave";
  aviso.hidden = false;
}

async function activar(cuenta) {
  if (cuenta.enabled) {
    const confirmado = await confirmar({
      titulo: "Desactivar la cuenta",
      mensaje:
        `La cuenta ${cuenta.name} dejará de estar disponible en su ruta /mcp. ` +
        "Sus datos y su contraseña siguen guardados, y puedes volver a activarla.",
      confirmar: "Desactivar",
      peligro: true,
    });
    if (!confirmado) return;
  }

  const cuerpo = await pedir(`/api/accounts/${cuenta.id}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled: !cuenta.enabled }),
  });
  if (!cuerpo.ok) return avisar(cuerpo.error, "error");
  avisar(
    cuenta.enabled
      ? `La cuenta ${cuenta.name} está desactivada.`
      : `La cuenta ${cuenta.name} vuelve a estar activa.`,
    "ok"
  );
  await cargar();
}

async function borrar(recurso, id, que, titulo) {
  const confirmado = await confirmar({
    titulo,
    mensaje: `Vas a borrar ${que}. Esto no se puede deshacer y sus claves dejan de funcionar.`,
    confirmar: "Eliminar",
    peligro: true,
  });
  if (!confirmado) return;

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
  for (const textoOpcion of ["Heredar", "Permitir", "Prohibir"]) {
    const opcion = document.createElement("option");
    opcion.value = textoOpcion;
    opcion.textContent = textoOpcion;
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
  nombre.placeholder = "ejemplo.com";
  const etiqueta = entrada("text", dominio?.label || "");
  etiqueta.placeholder = "Nombre que lo identifique en el panel";
  const imap = entrada("text", dominio?.imap_host || "");
  imap.placeholder = "imap.example.com";
  const smtp = entrada("text", dominio?.smtp_host || "");
  smtp.placeholder = "smtp.example.com";
  const permisos = permisosEscritos(dominio?.allow_send);
  const directos = permisosEscritos(dominio?.allow_direct_send);
  editor(
    dominio ? "Editar dominio" : "Añadir dominio",
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

/* Los listeners globales de los menús se instalan una sola vez. */
menuGlobal();

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
