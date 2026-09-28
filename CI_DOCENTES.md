# Administración del circuito de entregas

## Estado de la implementación

Esta versión se prepara para el template y los repositorios activos de 2026 de
las comisiones 001, 051, 251 y 053. El curso 052 queda expresamente excluido.
Se reutiliza el secreto ANTHROPIC_API_KEY existente. No se deben ejecutar los scripts antiguos
`sync_student_workflows.sh` ni `restore_branch_protection.sh` para este cambio:
no contemplan el nuevo circuito ni la preservación selectiva de configuraciones.

La secuencia para trasladarlo a los repositorios existentes está en
[PLAN_DISTRIBUCION.md](PLAN_DISTRIBUCION.md). El destino es main de cada repositorio;
publicar en el template no actualiza automáticamente esas copias.

Cada TP incluye `make verificar` (desde la raíz, `make -C TPN verificar`). El
comando compila automáticamente una herramienta docente escrita en C y ejecuta
la suite oficial sobre una copia limpia del índice de Git. La verificación
local obligatoria no requiere Python. Los scripts Python de CI se ejecutan en
GitHub Actions; la instalación opcional de pre-commit es independiente.

La constancia usa el esquema 2: nombres, modos e identificadores de objetos Git
para vincular exactamente los contenidos preparados y el verificador oficial.
Es compatible con checkouts CRLF. Una constancia de la versión anterior debe
regenerarse con `make verificar`; no se modifica el registro de devoluciones LLM.

## Circuito y límites

`entregas.yml` reemplaza los diez workflows anteriores. La lógica se toma de
`main` mediante `pull_request_target`. El código del alumno se ejecuta solamente
en el job de tests, en otro runner, con token de lectura, sin secreto del
proveedor ni caché compartida con los jobs privilegiados.

| Job | Trabajo | Límite |
| --- | --- | --- |
| Verificación previa | Rama, archivos protegidos, constancia y registro | 3 min |
| Compilación, tests y calidad | Una compilación del TP, suite oficial, clang-format, cppcheck y cpplint | 3 min |
| Publicar resultado | Estado en el SHA probado y comentario con calidad | 3 min |
| Devolución LLM | Registro, llamada, persistencia y comentario | 5 min |

La llamada tiene un máximo de 180 segundos, sin reintentos internos ni del SDK.
Los tests tienen un máximo conjunto de 120 segundos dentro de su job. El job de
tests puede cancelarse por una entrega más reciente; el de LLM no se cancela por
pushes y se serializa por repositorio y rama. Los jobs de publicación y LLM
pueden correr en paralelo después de los tests.

Estos son límites por job, no un máximo global de cinco u ocho minutos por
workflow. El límite agregado de los cuatro jobs es 14 minutos de runner y la
ruta secuencial más larga suma 11 minutos, más las esperas de GitHub. El consumo
habitual debe medirse después de un piloto autorizado. Con jobs cortos, la
estructura apunta a unos cinco minutos facturables en la primera devolución y
tres en las siguientes actualizaciones; no es una medición ni una garantía.

El job de LLM se omite antes de asignar runner cuando ya existe una devolución.
También vuelve a consultar el registro dentro de la exclusión mutua, para
cubrir dos eventos que hayan pasado el control previo al mismo tiempo.

Se conserva la validación de rama/carpeta, archivos protegidos, suite y calidad.
Como un PR de TP no puede modificar otros TPs, se elimina la compilación
informativa redundante de todos ellos. La calidad se aplica al TP entregado.

## Instalación y configuración

El circuito queda activo por defecto al estar en `main` de un repositorio
incluido en el filtro. No requiere una fecha ni una variable de activación.

1. Conservar **`ANTHROPIC_API_KEY`** donde ya está configurado. No se necesita
   recuperar su valor, crear otra clave ni trasladarla a un environment.
2. Respaldar y publicar el circuito validado en `main`, preservando código de
   alumnos, suites propias, integrantes, CODEOWNERS, colaboradores y ajustes.
   No reemplazar el README personalizado por el README del template.
3. Revisar los checks requeridos: el nuevo contexto es **`SSL / Tests de entrega`**.
   Retirar solamente los nombres reemplazados y preservar las demás protecciones.
   El estado se publica en el SHA probado.
4. Verificar archivos, Actions habilitado, presencia del secreto y protecciones
   mediante API, sin iniciar Actions ni llamar al proveedor para distribuir.

Por decisión del usuario, las reejecuciones de workflows históricos quedan
fuera de este cambio. La clave actual sigue disponible para ellos. La restricción
CODEOWNERS y el registro único se aplican al circuito nuevo; esto no impide que
alguien con permisos de escritura cree otro workflow que utilice un secreto del
repositorio. Se conserva el modelo de confianza indicado por el usuario.

En un repositorio nuevo creado desde el template, asegurar que Actions esté
habilitado y que ANTHROPIC_API_KEY esté disponible para ese repositorio. La clave
no se copia con los archivos del template. El filtro actual cubre únicamente
2026 y las cuatro comisiones indicadas; excluye 052, los sufijos `-1C` y el propio
template, cuyos PR son de mantenimiento.

## Reevaluación manual

En Actions → **Entregas SSL** → Run workflow, seleccionar **main**, indicar el PR
abierto y activar `force_review` para pedir otra devolución completa. Sin esa
opción se recupera la existente o se reintenta un intento incompleto. En ambos
casos se requiere un CODEOWNER y vuelven a verificarse constancia y tests.

Se comprueba `github.triggering_actor`, también al reejecutar jobs: se valida
quién pulsó Re-run, no solamente el autor del evento original. La configuración
actual de CODEOWNERS usa una regla global `*` con usuarios. Si se añaden equipos
o reglas por ruta, el autorizador bloquea las reevaluaciones hasta implementar
la resolución de esas reglas; nunca presume que ser colaborador alcanza.

Re-run de una reevaluación que ya guardó su reporte recupera ese mismo reporte.
Para pedir otra se necesita un nuevo Run workflow. Un fallo al comentar no
vuelve a llamar al proveedor si el registro ya fue guardado.

## Registro y recuperación

`ssl-evaluaciones` contiene `evaluaciones/TP_N.json` con el historial y reportes
Markdown en `reportes/TP_N/`. Se guardan juntos mediante un commit y un avance
sin force de la referencia. Los conflictos entre TPs se reintentan sin repetir
la llamada al proveedor. Un error al leer el registro detiene la evaluación.

No se crea un repositorio privado adicional. Se acepta expresamente confiar en
que los alumnos no modifiquen ni borren este registro. Conservar un backup de
esa rama junto con los backups de cada repositorio. Su eliminación puede quitar
el límite; la constancia local tampoco demuestra criptográficamente que los
tests se hayan ejecutado en el equipo del alumno.

Publicar el circuito no recorre ni reevalúa PR históricos. No hay una exención
por fecha: un PR ya abierto entra al circuito cuando recibe un evento admitido,
como un nuevo commit o una reapertura, y debe presentar una constancia válida.
El registro se construye con las devoluciones del circuito nuevo; los reportes
de workflows antiguos no se importan automáticamente. Una vez guardado el
reporte, cerrar un PR y crear otro de la misma rama conserva el límite y el
enlace original, sin consultar todos los PR históricos.

Un timeout o caída anterior al guardado duradero no consume la devolución. Si
el proveedor llegó a procesar una llamada que acabó en timeout, puede cobrarla:
permitir reintentos incompletos no garantiza un único cargo del proveedor.

## Validación local, sin gastos de proveedor ni de Actions

```sh
python3 -m unittest discover -s ci_tests -v
```

La suite usa repositorios temporales, compila un programa C de prueba y ejecuta
la suite real del laboratorio. Simula las respuestas del LLM y la persistencia
de GitHub. También prueba los cuatro GNUmakefile con Python bloqueado en PATH,
el verificador C y su timeout. Verifica constancias obsoletas, cambios de documentación, CRLF,
errores de compilación/tests, permisos docentes, reportes incompletos, PR nuevos
y recuperación tras fallos de comentarios. No contiene claves ni invoca APIs
externas.

Referencias de la plataforma:
- [Eventos y seguridad de pull_request_target](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target)
- [Reejecución de workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)
- [Concurrencia de workflows](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
