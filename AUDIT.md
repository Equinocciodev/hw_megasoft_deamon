# AUDIT — hw_megasoft_deamon

STATUS: OPEN · last-audited: 2026-09-28

Servicio Flask local (`127.0.0.1:8087`) instalado como servicio de Windows con
NSSM en cada caja. Es el puente entre el POS de Odoo y el VPOS de Megasoft
(`javaw` en `C:\vpos`): sirve los archivos `.txt` que el datáfono escribe
—vouchers y cierres de lote— y puede reiniciar el VPOS.

No cobra ni habla con la pasarela. Pero **lee, archiva y destruye los únicos
archivos que prueban un cierre de lote**, y puede matar el proceso que los
escribe. Por ahí van sus dos problemas reales.

---

## El problema de fondo: nada dice cuándo el archivo está completo

El VPOS responde al `accion:cierre` y **después** escribe el archivo. El manual
(MAET-VPOSW-00) describe `archivoCierre` como «path donde se registró el
voucher»: no promete que esté completo, no da tamaño esperado, no hay marca de
fin ni acción de consulta que lo diga. Un archivo existe desde su primer byte.

Agrava el diagnóstico que `_comandos()` añade **siempre** `810Fin del
documento.`: un cierre truncado sale por la impresora con un cierre de documento
perfectamente formado. Mirando el papel no se nota. La comprobación tiene que
pasar antes.

### Lo que hay hoy para decidirlo

| Señal | Dónde | Fuerza |
|---|---|---|
| Contenido idéntico en 2 sondeos (4 s) | POS, `pos_megasoft_payment` 19.0.1.37 | Heurística. Una pausa del VPOS > 4 s la engaña |
| `size` / `mtime` | demonio, `43f9590` | Igual de indirecta |
| `en_escritura` | demonio, **nuevo** | **Señal positiva**: otro proceso tiene el archivo abierto |
| `sha1` | demonio, **nuevo** | Prueba de identidad entre lo validado y lo impreso |
| `last_line` / `line_count` | demonio, **nuevo** | Materia prima para aprender el terminador real |

`en_escritura` se obtiene abriendo el archivo con `dwShareMode=0` (denegar
todo). Si el VPOS lo tiene abierto, Windows rechaza la apertura. Es sólo
lectura y se cierra de inmediato: no escribe, no trunca, no mueve nada.
Devuelve `None` fuera de Windows o sin pywin32 — **«no sé» no es «listo»**.

Caveat honesto: si el VPOS abre y cierra el archivo por cada línea, hay
ventanas en las que nadie lo tiene abierto. Por eso `en_escritura` **descarta**
(si es `True`, seguro que no está listo) pero no **confirma** por sí sola. La
combinación que sí sostiene una conclusión es: `en_escritura` falso **y**
contenido estable **y** `last_line` igual al terminador conocido.

### Lo que falta y por qué (no se puede hacer desde aquí)

**El terminador no se conoce.** Es el único chequeo que convertiría la
heurística en una comprobación. Por eso se devuelve `last_line`: con el log
nuevo, unos días de cierres BUENOS en producción dicen con qué termina siempre
un cierre completo. Entonces se asierta y se acaba el problema. Hasta tener ese
dato, asertar un terminador inventado rechazaría cierres válidos.

---

## Operaciones destructivas

### 1. `restart_service` — la más peligrosa

`taskkill /F /IM javaw.exe` mata **todos** los `javaw` de la máquina, sin gracia
y sin preguntar. Consecuencias directas:

- Si el VPOS estaba escribiendo un cierre → **archivo truncado**. Es una causa
  directa de «cierres incompletos», y encaja con que el POS ofrece reiniciar el
  VPOS justo cuando algo va mal.
- Si estaba en medio de un cobro → cobro sin respuesta, que es el escenario de
  reintento del que salen los cobros dobles.

Y **el camino de vuelta estaba roto**: se mataba primero y se arrancaba después
con `schtasks /run /tn RestartVposREST`, pero `CreateTaskRestartVposRest.bat` usa
`%TASK_NAME%` y **nunca define esa variable**, así que crea la tarea con ese
nombre literal. Si en una caja la tarea no existe con el nombre correcto, el
VPOS se queda muerto sin forma de levantarlo salvo cerrar y abrir sesión de
Windows.

Peor: el POS (`RestartVposService`) **no mira el `status` de la respuesta** y
muestra «The VPOS service has been restarted, please try the transaction again»
pase lo que pase. La cajera lee que todo está bien con el VPOS caído.

**Corregido aquí:** se comprueba que la tarea exista **antes** de matar nada, y
se verifica con `tasklist` que `javaw` vuelva antes de decir que sí.
**Pendiente (decisión):** arreglar el `.bat` del nombre de la tarea, y que el
POS deje de mostrar éxito incondicional.

### 2. `clear_txt_file` — archiva y recrea

Corre **después** de imprimir, así que si se imprimió un truncado, archiva el
truncado. Tres fallos corregidos:

- `os.rename` **sin try/except**. En Windows, mover un archivo que otro proceso
  tiene abierto lanza `PermissionError` → 500 sin explicación.
- **Nombre de respaldo con resolución de segundos** y `split('.')[0]`, que parte
  los nombres con puntos. Dos cierres en el mismo segundo chocan, y en Windows
  `os.rename` **falla si el destino existe** (no sobrescribe como en Linux).
  Ahora lleva microsegundos y sufijo si hace falta.
- **Ningún control de QUÉ se archiva.** El POS imprime por una ruta y limpia por
  carpeta: si el VPOS escribió otro cierre en medio, se archivaba el equivocado.
  Ahora acepta `expected_sha1` y se niega si no coincide, y se niega también si
  hay un escritor activo.

**Resuelto sin quitar el vacío (2026-09-28, QA del PR #1624 de gleiros):**
recrear el `.txt` vacío con el mismo nombre era el origen del caso
`varios_archivos`. Pasó en la Caja 11 de staging: tras archivar el residuo del
24-09 quedó `…_20260924.txt` vacío, el cierre de hoy llegó como `…_20260928.txt`
y `check_txt_file` se negó; el POS no encontró el comprobante de un lote YA
cerrado. Ahora `_un_solo_txt` **no cuenta los `.txt` vacíos** (0 bytes o sólo
espacios, la misma definición que `_comandos`):

- uno con contenido y el resto vacíos → ése (`check_txt_file` añade
  `vacios_ignorados`);
- dos o más con contenido → `varios_archivos`, como siempre (nunca se elige);
- un archivo ilegible NO se da por vacío (podría ser un cierre);
- un único `.txt` vacío → como siempre; varios y todos vacíos → `solo_vacios`
  (`clear_txt_file` no archiva ninguno);
- los errores llevan también `vacios`.

El vacío se **sigue recreando y no se borra nada**: sigue sin saberse si el VPOS
necesita que el archivo exista, e ignorarlo no destruye nada. Aditivo: un POS
viejo ve lo mismo salvo que ahora encuentra el comprobante.
Pruebas: `test_carpeta_cierres.py`.

### 3. `get_txt_file` — lee cualquier ruta

Abre la ruta que le manden, sin validar. Con `CORS(app)` sin restricción y sin
autenticación, cualquier página abierta en el navegador de la caja puede leer
archivos del equipo. Sólo escucha en `127.0.0.1`, así que no es exposición de
red — es exposición al navegador de esa máquina, que es exactamente donde corre
el POS.

**Pendiente (decisión):** acotar las rutas a `C:\voucher\**` y restringir CORS a
los orígenes de Odoo. Ambas cosas rompen si un despliegue usa otras rutas u
otro dominio, así que necesitan confirmación antes.

### 4. `debug=True` en producción

`app.run(debug=True)` dejaba el depurador de Werkzeug —consola de ejecución de
código protegida sólo por un PIN— en un equipo de tienda, y activaba el
recargador, que arranca un proceso hijo que NSSM no sigue. **Corregido**:
`debug=False, host='127.0.0.1', threaded=True`.

---

## Sin rastro: no había log

El instalador apunta `AppStdout`/`AppStderr` a `logs\*.log` pero **nunca crea la
carpeta**, así que los `print()` no quedaban en ningún sitio. Cuando una cajera
reportaba «el cierre salió incompleto» no había nada que mirar del lado del
demonio.

**Corregido**: la carpeta se crea al arrancar y hay un log rotado
(`logs/api.log`, 5 × 2 MB) con nombre, tamaño y `sha1` de cada archivo servido y
cada archivado. Es lo que permite, dentro de unos días, responder la pregunta del
terminador.

Complementario y **pendiente**: los cierres no se registran en Odoo.
`megasoft_transaction` tiene ~68.302 filas de tipo `tarjeta` y **0** de cierre.

---

## Otros cambios

- **Codificación explícita.** `open(path, 'r')` usaba la codificación por
  defecto del intérprete, que bajo NSSM no es la de la consola: un byte fuera de
  tabla levantaba `UnicodeDecodeError` → 500 → el POS reintentaba hasta agotar
  los 60 s sin decir por qué. Ahora se lee en binario y se decodifica `cp1252`
  con `errors='replace'`, que no puede fallar. Cubre además el archivo capturado
  a media escritura, que puede terminar en una secuencia multibyte partida.
- **CRLF (2026-09-28).** Al pasar a leer en binario (1ef7e3e), `_comandos`
  sólo quitaba el `\n` y cada comando salía con un `\r` colgando (los `.txt`
  del VPOS son de Windows). El desplegado (19747f4) abría en modo texto y no lo
  tenía. Ahora `rstrip('\r\n')`: los comandos vuelven a ser los de siempre.
  Hallado al escribir `test_carpeta_cierres.py` (`FinDeLineaWindows`).
- **`check_last_txt_file` y `get_lasts_txt`** tenían cero manejo de errores:
  cualquier problema de carpeta era un 500. Ahora devuelven `motivo`.
- **`request.json['x']`** lanzaba `KeyError` → 500 si faltaba el campo. Ahora
  devuelven `motivo: sin_ruta`.

Todo lo añadido es **aditivo**: `exists`, `data` y `status` conservan su
significado, así que un POS viejo contra este demonio se comporta igual que
antes.

---

## Pruebas

`test.py` **no prueba nada útil**: manda `data={...}` (formulario) donde los
endpoints leen `request.json`, y da por bueno un 200 contra rutas que no
existen en la máquina de pruebas. Arreglarlo es trabajo aparte y no se ha hecho.
La verificación de estos cambios es lectura de código; falta la prueba en caja.

`test_carpeta_cierres.py` (2026-09-28) sí prueba: carpeta temporal real y el
cliente de Flask con JSON, como el POS. `python -m unittest test_carpeta_cierres -v`
(hace falta `flask` y `flask-cors`; fuera de Windows, `en_escritura` es `None`).

---

## Decisiones pendientes del dueño

1. Arreglar `%TASK_NAME%` en `CreateTaskRestartVposRest.bat` y desplegar el .bat.
2. Que el POS deje de mostrar «servicio reiniciado» sin mirar la respuesta.
3. ~~¿Se puede dejar de recrear el `.txt` vacío en `clear_txt_file`?~~ Ya no hace
   falta para el caso `varios_archivos`: los vacíos se ignoran (2026-09-28). Sigue
   abierto sólo si se quiere dejar la carpeta limpia.
4. Acotar rutas de `get_txt_file` y restringir CORS.
5. Registrar los cierres en `megasoft_transaction`.
6. Recoger `last_line` de cierres buenos para asertar el terminador.
