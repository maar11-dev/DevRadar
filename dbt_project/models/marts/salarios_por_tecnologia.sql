with

salarios_por_oferta as (
    select
        id_oferta,
        case
            when salario_min is not null and salario_max is not null
                then (salario_min + salario_max) / 2
            else coalesce(salario_min, salario_max)
        end as salario
    from {{ ref('stg_ofertas') }}
    where coalesce(salario_min, salario_max) is not null
),

tecnologias_con_salario as (
    select
        tecnologias.tecnologia,
        cast(date_trunc('month', tecnologias.fecha_publicacion) as date) as mes,
        tecnologias.id_oferta,
        salarios_por_oferta.salario
    from {{ ref('int_tecnologias_por_oferta') }} as tecnologias
    inner join salarios_por_oferta
        on tecnologias.id_oferta = salarios_por_oferta.id_oferta
    where tecnologias.fecha_publicacion is not null
)

select
    tecnologia || '|' || strftime(mes, '%Y-%m') as id_tecnologia_mes,
    tecnologia,
    mes,
    count(distinct id_oferta) as num_ofertas_con_salario,
    round(avg(salario), 0) as salario_medio,
    round(median(salario), 0) as salario_mediano
from tecnologias_con_salario
group by tecnologia, mes
