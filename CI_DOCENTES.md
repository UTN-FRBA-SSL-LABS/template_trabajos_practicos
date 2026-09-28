# Administración del circuito de entregas

## Estado de la implementación

Esta versión se prepara para el template y los repositorios activos de 2026 de
las comisiones 001, 051, 052 y 053. Su publicación requiere configurar el secreto
y el environment indicados más abajo. No se deben ejecutar los scripts antiguos
`sync_student_workflows.sh` ni `restore_branch_protection.sh` para este cambio:
no contemplan el nuevo circuito ni la preservación selectiva de configuraciones.

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

## Configuración necesaria antes de activar

1. Crear el environment `ssl-llm` con política de ramas seleccionadas que permita
   únicamente la rama `main` (tipo branch, no tags). Si ya existe, revisar y
   preservar sus otras restricciones.
2. Cargar allí el secreto **`SSL_ANTHROPIC_API_KEY`**. No debe existir como secreto
   general del repositorio o de la organización accesible desde otras ramas.
3. Al hacer el corte, retirar el secreto anterior **`ANTHROPIC_API_KEY`** del
   repositorio y de cualquier otro origen accesible a los workflows viejos.
   GitHub no permite leer su valor actual: un administrador debe volver a
   suministrarlo mediante la interfaz de Secrets o la entrada segura de `gh`.
4. Publicar el circuito validado en `main`, preservando el código de alumnos,
   suites oficiales propias del repo, integrantes, CODEOWNERS, colaboradores y
   configuraciones particulares. No reemplazar el README personalizado por el
   README del template.
5. Revisar los checks requeridos en la protección de `main`: el nuevo contexto
   que resume compilación/tests es **`SSL / Tests de entrega`**. Retirar solamente
   los nombres retirados por este cambio; preservar aprobaciones de CODEOWNERS,
   restricciones de push y demás políticas. El estado se publica sobre el SHA
   probado, porque el workflow de control se ejecuta sobre `main`.
6. Verificar por API la versión de los archivos, el environment, los nombres de
   secretos (nunca sus valores) y las protecciones. No iniciar Actions ni llamar
   al proveedor como parte de esta verificación de distribución.

El cambio de ubicación/nombre de la clave es necesario para que **Re-run** de
una ejecución histórica no siga accediendo al proveedor con el script anterior.
Tampoco se debe dejar la nueva clave disponible para un workflow editado en una
rama de estudiante. `CODEOWNERS` por sí solo no limita quién puede pulsar Run.

Los repositorios creados desde el template no heredan sus secretos ni sus
environments; deben configurarse al crear cada repositorio de curso.

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

## Registro, recuperación y migración

`ssl-evaluaciones` contiene `evaluaciones/TP_N.json` con el historial y reportes
Markdown en `reportes/TP_N/`. Se guardan juntos mediante un commit y un avance
sin force de la referencia. Los conflictos entre TPs se reintentan sin repetir
la llamada al proveedor. Un error al leer el registro detiene la evaluación.

No se crea un repositorio privado adicional. Se acepta expresamente confiar en
que los alumnos no modifiquen ni borren este registro. Conservar un backup de
esa rama junto con los backups de cada repositorio. Su eliminación puede quitar
el límite; la constancia local tampoco demuestra criptográficamente que los
tests se hayan ejecutado en el equipo del alumno.

Si todavía no hay registro, el control busca devoluciones completas del bot en
PR abiertos y cerrados de esa misma rama y las incorpora. Solo reconoce reportes
con las secciones y cierre del formato anterior. Errores y textos cortados no
cuentan. Si un reporte anterior fue borrado, reemplazado por un error o usa otro
formato, se requiere revisión docente para reconstruirlo; no se puede inferir
una devolución completa solo de un check verde. Los reportes históricos sin SHA
lo indican explícitamente y nunca atribuyen su aprobación al HEAD actual.

Un timeout o caída anterior al guardado duradero no consume la devolución. Si
el proveedor llegó a procesar una llamada que acabó en timeout, puede cobrarla:
permitir reintentos incompletos no garantiza un único cargo del proveedor.

## Validación local, sin gastos de proveedor ni de Actions

```sh
python3 -m unittest discover -s ci_tests -v
```

La suite usa repositorios temporales, compila un programa C de prueba y ejecuta
la suite real del laboratorio. Simula las respuestas del LLM y la persistencia
de GitHub. Verifica constancias obsoletas, cambios de documentación, CRLF,
errores de compilación/tests, permisos docentes, reportes incompletos, PR nuevos
y recuperación tras fallos de comentarios. No contiene claves ni invoca APIs
externas.

Referencias de la plataforma:
- [Eventos y seguridad de pull_request_target](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target)
- [Environments y políticas de ramas](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
- [Reejecución de workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)
- [Concurrencia de workflows](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
