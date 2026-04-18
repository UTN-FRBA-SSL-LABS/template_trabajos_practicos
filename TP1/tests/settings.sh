#!/bin/sh

input_extension='.txt'

# Porcentaje mínimo de clasificaciones correctas para superar un test individual
min_percentage_matching_per_test=80
# Promedio mínimo de clasificaciones correctas entre todas las pruebas
min_average_percentage_over_all_test=80
# Cantidad mínima de tests individuales superados para habilitar revisión de PR
min_quantity_test=3
# Bandera para determinar si todas las condiciones fueron cumplidas.
pass_tests=1