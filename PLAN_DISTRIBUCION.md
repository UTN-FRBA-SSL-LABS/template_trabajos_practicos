# Distribución del circuito de entregas a los repositorios de estudiantes

## Alcance y destino

Actualizar el template no modifica las copias que ya tienen los estudiantes.
El circuito debe quedar en **main de cada repositorio**: el workflow toma de
esa rama la lógica docente que controla la entrega. La rama local de desarrollo
`codex/validacion-local-llm-unico` no activa por sí sola ningún repositorio.

La distribución a estudiantes está pendiente y requiere una orden posterior.
El alcance verificado el 28 de septiembre de 2026 es:

| Comisión | Repositorios | Cantidad |
| --- | --- | ---: |
| 001 | 26-001-01 a 26-001-20 | 20 |
| 051 | 26-051-01 a 26-051-20 | 20 |
| 251 | 26-251-01 a 26-251-15 | 15 |
| 053 | 26-053-01 a 26-053-17 | 17 |
| **Total de estudiantes** | | **72** |

El curso **052 queda fuera**, porque no utiliza este template de laboratorio.
También quedan fuera los repositorios archivados y los nombres con sufijo -1C.
Confirmar nombre e ID de cada repositorio contra el manifiesto antes de escribir.

## Secuencia propuesta por repositorio

1. Leer la versión actual de main, ramas, PR abiertos, protecciones, reglas,
   workflows, disponibilidad de Actions y presencia de ANTHROPIC_API_KEY. Identificar
   variantes locales y checks requeridos. No leer ni reemplazar valores de claves.
2. Guardar un backup del historial y una copia de las configuraciones que se
   vayan a modificar. Registrar el SHA inicial de main y los IDs de los PR ya
   abiertos. Si ya existe el registro de evaluaciones, conservarlo sin reiniciarlo.
3. Crear una rama de mantenimiento desde **el main de ese repositorio**, por
   ejemplo `codex/actualizar-entregas-2026`. Aplicar allí solo los archivos de
   infraestructura y documentación de esta versión. El resultado debe ser un
   diff individual revisable; no un reemplazo del repositorio ni un merge global
   de la historia del template.
4. Validar localmente el diff, el YAML y los scripts. Comparar las suites oficiales
   y conservar las específicas del repositorio. No iniciar el LLM para validar
   la distribución.
5. Incorporar el cambio a **main** respetando las reglas vigentes. El circuito queda
   activo por defecto, sin configurar una fecha de inicio. Si el repositorio
   exige PR y revisión docente, abrir el PR de mantenimiento y obtener esas
   aprobaciones. Donde esté permitido, una actualización directa que avance el
   historial puede evitar ejecuciones innecesarias de los workflows anteriores.
   Nunca usar force-push ni desactivar la protección completa para acelerar el lote.
6. Adaptar únicamente los checks reemplazados al contexto **SSL / Tests de entrega**,
   preservando CODEOWNERS, revisiones, restricciones de push y otras políticas.
   Verificar por API el SHA final, archivos y configuración efectiva.
7. Registrar éxito o incidencia por repositorio. Ante diferencias imprevistas,
   detener ese repositorio y conservar su backup; no continuar con una copia ciega.

Un PR de mantenimiento puede ser rechazado por los checks antiguos que exigen
rama TP_N o prohíben tocar workflows. Esa situación debe detectarse en el paso 1
y resolverse como una transición de checks con los docentes responsables. No
suponer que se puede fusionar automáticamente ni borrar todas las restricciones.

## Archivos que se distribuyen

- Agregar `.github/workflows/entregas.yml` y retirar los diez workflows que
  reemplaza: `test_tp1.yml` a `test_tp4.yml`, `llm_review.yml`, `check_compilation.yml`,
  `static_analysis.yml`, `check_format.yml`, `check_protected_files.yml` y
  `check_tp_branch.yml`. Conservar workflows ajenos a esta implementación.
- Actualizar `.github/scripts/llm_review.py`; agregar `local_receipt.py`,
  `review_state.py`, `submission_gate.py`, `publish_checks.py` y `quality_report.py`.
  Verificar que esté disponible `apt-install.sh`, con la versión compatible.
- Agregar `.github/scripts/local_verifier.c` y `verificar_local.sh`. Incorporar
  el target `verificar` en el GNUmakefile de **cada TP (TP1 a TP4)**, conservando
  el resto de sus reglas. Eliminar `verificar_tp.py` si proviene de la versión anterior.
- Agregar `ENTREGAS.md` y la guía docente. Las pruebas de
  infraestructura pueden distribuirse junto con estos scripts para reproducibilidad.
- Incorporar las cuatro excepciones de `.gitignore` para las constancias locales,
  sin reemplazar las reglas propias del grupo.
- Incorporar en `.gitattributes` la excepción de indentación para
  `.github/scripts/local_verifier.c`, que sigue el formato docente con espacios.
- Integrar el aviso del template de PR y los enlaces de documentación con los
  textos existentes; conservar cualquier sección particular de cada grupo.

Se conservan soluciones, reglas de compilación existentes, mkframework, pruebas oficiales, rúbricas,
prompts, configuración docente, CODEOWNERS, integrantes y README personalizado.
Una variante incompatible se revisa individualmente; no se la pisa con el template.
No se cambian miembros, equipos, permisos ni secretos como parte de esta copia.

## Qué hacen los alumnos después

No se modifican automáticamente sus ramas de trabajo. Antes de abrir o actualizar
un PR, incorporan main a la rama del TP, por ejemplo:

```sh
git fetch origin
git switch TP_3
git merge origin/main
```

Si hay conflictos, los resuelven conservando su implementación. Después siguen
[ENTREGAS.md](ENTREGAS.md): preparar el código, ejecutar `make -C TP3 verificar`,
agregar la constancia al commit y hacer push. No se requiere repetir tests por
cada commit intermedio si los contenidos verificados no cambiaron.

La instalación no recorre ni reevalúa PR históricos. Sin filtro por fecha, un PR
que ya estaba abierto también entra al circuito cuando recibe un nuevo commit
o se reabre. Por eso el relevamiento previo incluye sus entregas y devoluciones:
los reportes de workflows antiguos no se importan automáticamente al registro.
El registro se construye en `ssl-evaluaciones` dentro de cada repositorio. Una
rama con devolución registrada conserva el límite aunque cierre su PR y abra
otro. Las reejecuciones de workflows históricos quedan fuera de este cambio,
según el alcance acordado.

## Lotes, costo y reversión

Conviene comenzar con un repositorio representativo, verificar su instalación
por API y luego avanzar por comisión. Un ensayo integral con Actions o proveedor
sería un piloto aparte, con su consumo explícito; no es necesario dispararlo para
comprobar la copia de archivos. Crear PR de mantenimiento puede disparar los
workflows existentes y debe contemplarse al elegir la vía de incorporación.

Ante una falla de instalación, revertir los commits de infraestructura mediante
un commit nuevo y restaurar únicamente las configuraciones registradas para ese
cambio. Conservar `ssl-evaluaciones` y su historial: borrarlo habilitaría nuevas
evaluaciones. No reescribir las ramas ni retirar commits de alumnos.

La [guía de administración](CI_DOCENTES.md) describe límites, permisos y reintentos.
