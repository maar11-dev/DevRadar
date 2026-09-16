with

tecnologias_por_mes as (
    select
        tecnologia,
        cast(date_trunc('month', fecha_publicacion) as date) as mes,
        id_oferta
    from {{ ref('int_tecnologias_por_oferta') }}
    where fecha_publicacion is not null
),

ofertas_por_mes as (
    select
        cast(date_trunc('month', fecha_publicacion) as date) as mes,
        count(distinct id_oferta) as total_ofertas_mes
    from {{ ref('stg_ofertas') }}
    where tecnologias is not null
        and fecha_publicacion is not null
    group by 1
)

select
    tecnologias_por_mes.tecnologia || '|' || strftime(tecnologias_por_mes.mes, '%Y-%m') as id_tecnologia_mes,
    tecnologias_por_mes.tecnologia,
    tecnologias_por_mes.mes,
    count(distinct tecnologias_por_mes.id_oferta) as num_ofertas,
    ofertas_por_mes.total_ofertas_mes,
    round(
        100.0 * count(distinct tecnologias_por_mes.id_oferta) / ofertas_por_mes.total_ofertas_mes, 2
    ) as pct_ofertas
from tecnologias_por_mes
inner join ofertas_por_mes
    on tecnologias_por_mes.mes = ofertas_por_mes.mes
group by
    tecnologias_por_mes.tecnologia,
    tecnologias_por_mes.mes,
    ofertas_por_mes.total_ofertas_mes
