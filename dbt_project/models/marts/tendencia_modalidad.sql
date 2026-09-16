with

ofertas_con_modalidad as (
    select
        id_oferta,
        modalidad,
        cast(date_trunc('month', fecha_publicacion) as date) as mes
    from {{ ref('stg_ofertas') }}
    where modalidad is not null
        and fecha_publicacion is not null
),

conteos as (
    select
        modalidad,
        mes,
        count(distinct id_oferta) as num_ofertas
    from ofertas_con_modalidad
    group by modalidad, mes
)

select
    modalidad || '|' || strftime(mes, '%Y-%m') as id_modalidad_mes,
    modalidad,
    mes,
    num_ofertas,
    round(100.0 * num_ofertas / sum(num_ofertas) over (partition by mes), 2) as pct_ofertas
from conteos
