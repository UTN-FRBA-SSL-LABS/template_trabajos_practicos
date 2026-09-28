# Tests locales y entrega del TP

Antes de enviar una versión para revisión, ejecuten la misma suite que usa el
laboratorio. Una constancia válida habilita la compilación y los tests remotos.
La constancia es un control del proceso de trabajo: no reemplaza los tests remotos.

Este circuito se aplica automáticamente al abrir o actualizar un PR de entrega.

## Preparar la entrega

Ejemplo para `TP3`, trabajando en la rama `TP_3`, desde la raíz del repositorio:

```sh
git add TP3
make -C TP3 verificar
git add TP3/.verificacion-local.json
git commit -m "feat: completar entrega TP3 con tests locales"
git push origin TP_3
```

Luego abran o actualicen el PR de `TP_3` hacia `main`. Para los otros trabajos,
reemplacen `TP3` y `TP_3` por el número correspondiente.

Dentro de la carpeta del TP pueden usar directamente `make verificar`.
El comando está disponible en los cuatro trabajos:

| Trabajo | Comando desde la raíz |
| --- | --- |
| TP1 | `make -C TP1 verificar` |
| TP2 | `make -C TP2 verificar` |
| TP3 | `make -C TP3 verificar` |
| TP4 | `make -C TP4 verificar` |

Usen el mismo entorno GNU con el que compilan el TP: Git, GNU Make, el compilador
configurado en el Makefile y Flex/Bison cuando corresponda, junto con las
herramientas de la suite. El comando respeta la configuración de cada TP.
En Windows se usa la terminal de ese entorno (por ejemplo, MSYS2/MinGW o Cygwin).
WSL también es una opción, pero no es obligatorio. PowerShell o CMD sin las
herramientas GNU no reemplazan ese entorno. No necesitan instalar ni ejecutar
Python para esta verificación. Programan la solución del TP en C y usan
Flex/Bison cuando la consigna lo requiere; la constancia se genera automáticamente.

El verificador toma los archivos preparados mediante `git add`, arma una copia
limpia temporal, compila y ejecuta la suite oficial con los criterios del TP.
No utiliza un ejecutable antiguo de `bin/`. Si todo aprueba, genera
`TP3/.verificacion-local.json`. Si falla o supera los dos minutos para compilar
y probar, la constancia local queda invalidada. Revisen el error antes de enviar.

Si los hooks de pre-commit corrigen el código, hagan `git add` y vuelvan a
ejecutar el verificador antes de completar el commit. Conviene resolver los
cambios de formato antes de ejecutar los tests.

## Cuándo repetir los tests

No es necesario correrlos en cada commit de trabajo. Pueden hacer varios
commits y verificar la versión final que van a enviar al PR. Deben repetirlos
si cambia código, entradas, archivos de compilación o la suite oficial. Cambiar
solamente documentación o el mensaje de un commit no invalida la constancia.

GitHub compara la constancia con los contenidos enviados y con la suite de
`main`. Si falta, está desactualizada o la suite difiere, el control inicial
explica el problema y no inicia los jobs de compilación, tests ni LLM. Si los
docentes actualizaron el verificador o la suite, incorporen `origin/main` a la
rama del TP, resuelvan los conflictos y vuelvan a verificar.

Con constancia válida, los tests remotos se ejecutan en cada actualización del
PR. La compilación y los tests de una versión anterior pueden cancelarse cuando
una versión nueva ya está lista para verificarse. El análisis de formato y
calidad es informativo y se publica junto con el resultado.

## Una devolución automática por rama

El LLM se habilita cuando los tests remotos aprueban. Hay una devolución completa
por repositorio y rama de TP, aunque después agreguen commits, cierren/reabran
el PR o abran uno nuevo desde la misma rama. El aviso enlaza la devolución y el
PR original e identifica el commit cuyos tests habían aprobado. Esa aprobación
no se extiende automáticamente a las versiones posteriores.

Si el intento termina por timeout, error o respuesta cortada/vacía, no se
registra una devolución completa. Se puede reintentar. No se hacen reintentos
automáticos del proveedor dentro de la misma ejecución.

Las devoluciones completas se guardan antes de publicarse en el PR, en la rama
`ssl-evaluaciones` del mismo repositorio. Esa rama y los reportes no tienen un
vencimiento automático. No los borren ni los modifiquen. Los archivos temporales
de calidad de Actions tienen una retención de siete días.

Solo los docentes incluidos en `CODEOWNERS` pueden solicitar otra devolución
completa. La decisión final sobre la entrega sigue siendo del docente.
