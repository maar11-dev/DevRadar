-- El denominador son las ofertas del mes con al menos una tecnología detectada
-- (ADR-007): las que no tienen ninguna se analizan en cobertura_extraccion_mensual.
with

tecnologias_por_mes as (
    select
        tecnologia,
        cast(date_trunc('month', fecha_publicacion) as date) as mes,
        id_oferta
    from {{ ref('int_tecnologias_por_oferta') }}
    where fecha_publicacion is not null
),

ofertas_con_tecnologia_por_mes as (
    select
        mes,
        count(distinct id_oferta) as total_ofertas_con_tecnologia_mes
    from tecnologias_por_mes
    group by mes
)

select
    tecnologias_por_mes.tecnologia || '|' || strftime(tecnologias_por_mes.mes, '%Y-%m') as id_tecnologia_mes,
    tecnologias_por_mes.tecnologia,
    tecnologias_por_mes.mes,
    count(distinct tecnologias_por_mes.id_oferta) as num_ofertas,
    ofertas_con_tecnologia_por_mes.total_ofertas_con_tecnologia_mes,
    round(
        100.0 * count(distinct tecnologias_por_mes.id_oferta)
        / ofertas_con_tecnologia_por_mes.total_ofertas_con_tecnologia_mes,
        2
    ) as pct_ofertas
from tecnologias_por_mes
inner join ofertas_con_tecnologia_por_mes
    on tecnologias_por_mes.mes = ofertas_con_tecnologia_por_mes.mes
group by
    tecnologias_por_mes.tecnologia,
    tecnologias_por_mes.mes,
    ofertas_con_tecnologia_por_mes.total_ofertas_con_tecnologia_mes
