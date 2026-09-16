-- Los salarios de Adzuna que llegan a staging deben estar en el rango anual
-- aceptado (ADR-010), y ningún rango puede tener el mínimo por encima del máximo.
select id_oferta, fuente_salario, salario_min, salario_max
from {{ ref('stg_ofertas') }}
where (
        fuente_salario = 'adzuna'
        and (salario_min not between 15000 and 300000 or salario_max not between 15000 and 300000)
    )
    or salario_min > salario_max
