"""Dashboard de DevRadar: demanda de tecnologías en ofertas de empleo tech.

Lee directamente los marts de dbt en DuckDB (solo lectura).
Ejecutar con: streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

if __package__ in (None, ""):
    # `streamlit run dashboard/app.py` solo añade dashboard/ al path.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import get_db_path

MARTS = (
    "demanda_tecnologias_mensual",
    "salarios_por_tecnologia",
    "tendencia_modalidad",
    "cobertura_extraccion_mensual",
)
NOTA_COBERTURA = (
    "La API de Adzuna solo entrega los primeros 500 caracteres de la descripción "
    "de cada oferta, así que en muchas no se llega a mencionar ninguna tecnología. "
    "Esas ofertas se excluyen de los porcentajes de demanda, que se calculan solo "
    "sobre las ofertas con al menos una tecnología detectada (ADR-007)."
)
MODALIDADES = ["remoto", "hibrido", "presencial"]
ETIQUETAS_MODALIDAD = {
    "remoto": "Remoto",
    "hibrido": "Híbrido",
    "presencial": "Presencial",
}

# Paleta categórica validada (orden fijo; cada modalidad conserva siempre su color).
PALETA = {
    "light": {"serie": ["#2a78d6", "#eb6834", "#1baf7a"], "superficie": "#ffffff"},
    "dark": {"serie": ["#3987e5", "#d95926", "#199e70"], "superficie": "#0e1117"},
}


def _theme() -> dict:
    """Devuelve la paleta del tema activo de Streamlit (claro por defecto)."""
    try:
        tipo = st.context.theme.type or "light"
    except AttributeError:
        tipo = "light"
    return PALETA.get(tipo, PALETA["light"])


@st.cache_data(ttl=600, show_spinner=False)
def cargar_marts(db_path: str) -> dict[str, pd.DataFrame]:
    """Carga los marts de DuckDB en DataFrames.

    Args:
        db_path: Ruta del archivo DuckDB (forma parte de la clave de caché).

    Returns:
        Diccionario ``nombre del mart -> DataFrame``.
    """
    with duckdb.connect(db_path, read_only=True) as con:
        datos = {
            nombre: con.execute(f"select * from {nombre}").df() for nombre in MARTS
        }
    for df in datos.values():
        df["mes"] = pd.to_datetime(df["mes"])
    return datos


def ranking_tecnologias(demanda: pd.DataFrame, top: int) -> pd.DataFrame:
    """Agrega la demanda de varios meses en un ranking.

    El porcentaje se calcula sobre el total de ofertas del periodo con al menos
    una tecnología detectada (no como media de porcentajes mensuales).

    Args:
        demanda: Filas de ``demanda_tecnologias_mensual`` del periodo.
        top: Número de tecnologías a devolver.

    Returns:
        DataFrame con ``tecnologia``, ``num_ofertas`` y ``pct_ofertas``.
    """
    total = demanda.drop_duplicates("mes")["total_ofertas_con_tecnologia_mes"].sum()
    ranking = demanda.groupby("tecnologia", as_index=False)["num_ofertas"].sum()
    ranking["pct_ofertas"] = (100 * ranking["num_ofertas"] / total).round(1)
    return ranking.sort_values(
        ["num_ofertas", "tecnologia"], ascending=[False, True]
    ).head(top)


def grafico_ranking(ranking: pd.DataFrame, color: str) -> alt.Chart:
    """Barras horizontales del ranking, con el porcentaje como etiqueta."""
    datos = ranking.assign(etiqueta=ranking["pct_ofertas"].map("{:.1f} %".format))
    base = alt.Chart(datos).encode(
        y=alt.Y("tecnologia:N", sort="-x", title=None),
        x=alt.X(
            "num_ofertas:Q",
            title="Ofertas que la mencionan",
            axis=alt.Axis(format="d", tickMinStep=1, tickCount=8),
        ),
        tooltip=[
            alt.Tooltip("num_ofertas:Q", title="Ofertas"),
            alt.Tooltip("pct_ofertas:Q", title="% de ofertas", format=".1f"),
            alt.Tooltip("tecnologia:N", title="Tecnología"),
        ],
    )
    barras = base.mark_bar(color=color, cornerRadiusEnd=4, height={"band": 0.7})
    etiquetas = base.mark_text(align="left", dx=4).encode(
        text="etiqueta:N",
        color=alt.value("gray"),
    )
    return (barras + etiquetas).properties(height=max(160, 26 * len(ranking)))


def grafico_evolucion(serie: pd.DataFrame, color: str) -> alt.Chart:
    """Línea del % mensual de ofertas de una tecnología, con crosshair y tooltip."""
    cerca = alt.selection_point(
        nearest=True, on="pointerover", fields=["mes"], empty=False
    )
    base = alt.Chart(serie).encode(
        x=alt.X("yearmonth(mes):T", title=None, axis=alt.Axis(format="%b %Y")),
    )
    linea = base.mark_line(color=color, strokeWidth=2).encode(
        y=alt.Y(
            "pct_ofertas:Q", title="% de ofertas del mes", scale=alt.Scale(zero=True)
        ),
    )
    puntos = base.mark_point(color=color, filled=True, size=64).encode(
        y="pct_ofertas:Q"
    )
    objetivo = (
        base.mark_rule(opacity=0)
        .encode(
            tooltip=[
                alt.Tooltip("pct_ofertas:Q", title="% de ofertas", format=".1f"),
                alt.Tooltip("num_ofertas:Q", title="Ofertas"),
                alt.Tooltip(
                    "total_ofertas_con_tecnologia_mes:Q",
                    title="Ofertas del mes con tecnologías",
                ),
                alt.Tooltip("yearmonth(mes):T", title="Mes", format="%B %Y"),
            ],
        )
        .add_params(cerca)
    )
    regla = base.mark_rule(color="gray", strokeWidth=1).transform_filter(cerca)
    return (linea + puntos + regla + objetivo).properties(height=280)


def grafico_modalidad(
    modalidad: pd.DataFrame, colores: list[str], superficie: str
) -> alt.Chart:
    """Barras apiladas al 100 % por mes con el reparto de modalidades."""
    datos = modalidad.assign(
        etiqueta=modalidad["modalidad"].map(ETIQUETAS_MODALIDAD),
        orden=modalidad["modalidad"].map(MODALIDADES.index),
        mes_etiqueta=modalidad["mes"].dt.strftime("%b %Y"),
    )
    orden_meses = datos.sort_values("mes")["mes_etiqueta"].unique().tolist()
    return (
        alt.Chart(datos)
        .mark_bar(stroke=superficie, strokeWidth=2)
        .encode(
            x=alt.X(
                "mes_etiqueta:O",
                title=None,
                sort=orden_meses,
                axis=alt.Axis(labelAngle=0),
                scale=alt.Scale(paddingInner=0.4, paddingOuter=0.2),
            ),
            y=alt.Y(
                "pct_ofertas:Q",
                title="% de ofertas",
                stack="normalize",
                axis=alt.Axis(format="%"),
            ),
            color=alt.Color(
                "etiqueta:N",
                title="Modalidad",
                scale=alt.Scale(
                    domain=[ETIQUETAS_MODALIDAD[m] for m in MODALIDADES], range=colores
                ),
                legend=alt.Legend(orient="top"),
            ),
            order=alt.Order("orden:Q"),
            tooltip=[
                alt.Tooltip("pct_ofertas:Q", title="% de ofertas", format=".1f"),
                alt.Tooltip("num_ofertas:Q", title="Ofertas"),
                alt.Tooltip("etiqueta:N", title="Modalidad"),
                alt.Tooltip("mes_etiqueta:O", title="Mes"),
            ],
        )
        .properties(height=280)
    )


def grafico_sin_tecnologia(cobertura: pd.DataFrame, color: str) -> alt.Chart:
    """Barras por mes con el % de ofertas clasificadas sin ninguna tecnología."""
    datos = cobertura.assign(
        mes_etiqueta=cobertura["mes"].dt.strftime("%b %Y"),
        etiqueta=cobertura["pct_sin_tecnologia"].map("{:.1f} %".format),
    )
    orden_meses = datos.sort_values("mes")["mes_etiqueta"].tolist()
    base = alt.Chart(datos).encode(
        x=alt.X(
            "mes_etiqueta:O",
            title=None,
            sort=orden_meses,
            axis=alt.Axis(labelAngle=0),
            scale=alt.Scale(paddingInner=0.4, paddingOuter=0.2),
        ),
        y=alt.Y(
            "pct_sin_tecnologia:Q",
            title="% de ofertas sin tecnologías",
            scale=alt.Scale(domain=[0, 100]),
        ),
        tooltip=[
            alt.Tooltip(
                "pct_sin_tecnologia:Q", title="% sin tecnologías", format=".1f"
            ),
            alt.Tooltip("ofertas_sin_tecnologia:Q", title="Ofertas sin tecnologías"),
            alt.Tooltip("total_ofertas_clasificadas:Q", title="Ofertas clasificadas"),
            alt.Tooltip("mes_etiqueta:O", title="Mes"),
        ],
    )
    barras = base.mark_bar(color=color, cornerRadiusEnd=4)
    etiquetas = base.mark_text(baseline="bottom", dy=-4).encode(
        text="etiqueta:N", color=alt.value("gray")
    )
    return (barras + etiquetas).properties(height=240)


def _formato_entero(valor: int) -> str:
    """Formatea un entero con separador de miles español."""
    return f"{valor:,}".replace(",", ".")


def main() -> None:
    """Construye la página del dashboard."""
    st.set_page_config(page_title="DevRadar", page_icon="📡", layout="wide")
    load_dotenv()
    st.title("📡 DevRadar")
    st.caption("¿Qué tecnologías se piden realmente en las ofertas de empleo tech?")

    db_path = get_db_path()
    if not db_path.exists():
        st.warning(
            f"No se encuentra la base de datos en `{db_path}`. Ejecuta el pipeline "
            "(`python src/ingest.py` y `dbt build` desde `dbt_project/`) o define "
            "`DBT_DUCKDB_PATH`."
        )
        st.stop()
    try:
        marts = cargar_marts(str(db_path))
    except duckdb.Error as exc:
        st.error(
            "No se pudieron leer los marts. ¿Se ha ejecutado `dbt build`? "
            f"Si el pipeline está escribiendo en la base, espera a que termine.\n\n`{exc}`"
        )
        st.stop()

    demanda = marts["demanda_tecnologias_mensual"]
    cobertura = marts["cobertura_extraccion_mensual"]
    if cobertura.empty:
        st.info(
            "Todavía no hay ofertas clasificadas. Ejecuta el pipeline para cargar datos."
        )
        st.stop()

    paleta = _theme()
    color_principal = paleta["serie"][0]

    # --- Filtros (una sola fila) ---
    meses = sorted(cobertura["mes"].dt.date.unique())
    col_periodo, col_top = st.columns([3, 1])
    with col_periodo:
        if len(meses) > 1:
            desde, hasta = st.select_slider(
                "Periodo",
                options=meses,
                value=(meses[0], meses[-1]),
                format_func=lambda m: m.strftime("%b %Y"),
            )
        else:
            desde = hasta = meses[0]
            st.markdown(f"**Periodo:** {meses[0]:%b %Y} (único mes con datos)")
    with col_top:
        top = st.number_input("Tecnologías en el ranking", 5, 50, 15, step=5)

    demanda_periodo = demanda[demanda["mes"].dt.date.between(desde, hasta)]
    cobertura_periodo = cobertura[cobertura["mes"].dt.date.between(desde, hasta)]
    total_clasificadas = int(cobertura_periodo["total_ofertas_clasificadas"].sum())
    total_sin_tecnologia = int(cobertura_periodo["ofertas_sin_tecnologia"].sum())
    total_con_tecnologia = total_clasificadas - total_sin_tecnologia
    pct_sin_tecnologia = (
        100 * total_sin_tecnologia / total_clasificadas if total_clasificadas else 0
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Ofertas clasificadas", _formato_entero(total_clasificadas))
    k2.metric("Con alguna tecnología", _formato_entero(total_con_tecnologia))
    k3.metric(
        "Sin ninguna tecnología detectada",
        f"{pct_sin_tecnologia:.1f} %",
        help=NOTA_COBERTURA,
    )
    k4.metric("Tecnologías distintas", demanda_periodo["tecnologia"].nunique())
    st.info(
        f"**El {pct_sin_tecnologia:.0f} % de las ofertas del periodo no tiene "
        f"ninguna tecnología detectada.** {NOTA_COBERTURA}",
        icon="ℹ️",
    )

    if demanda_periodo.empty:
        st.warning("Ninguna oferta del periodo tiene tecnologías detectadas.")
        st.stop()

    # --- Ranking ---
    st.subheader("Tecnologías más demandadas")
    ranking = ranking_tecnologias(demanda_periodo, int(top))
    st.altair_chart(grafico_ranking(ranking, color_principal), width="stretch")
    st.caption(
        "Etiqueta: % de las ofertas del periodo con alguna tecnología detectada "
        "que mencionan esta."
    )
    with st.expander("Ver tabla"):
        st.dataframe(
            ranking.rename(
                columns={
                    "tecnologia": "Tecnología",
                    "num_ofertas": "Ofertas",
                    "pct_ofertas": "% ofertas",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    # --- Evolución de una tecnología ---
    st.subheader("Evolución de una tecnología")
    tecnologias = (
        demanda.groupby("tecnologia")["num_ofertas"].sum().sort_values(ascending=False)
    )
    seleccion = st.selectbox("Tecnología", tecnologias.index.tolist())
    serie = demanda[demanda["tecnologia"] == seleccion].sort_values("mes")
    if len(serie) < 2:
        fila = serie.iloc[0]
        st.metric(
            f"{seleccion} · {fila['mes']:%b %Y}",
            f"{fila['pct_ofertas']:.1f} % de las ofertas",
            help="Hace falta más de un mes de datos para mostrar la evolución.",
        )
    else:
        st.altair_chart(grafico_evolucion(serie, color_principal), width="stretch")
    with st.expander("Ver tabla"):
        st.dataframe(
            serie.assign(mes=serie["mes"].dt.strftime("%Y-%m"))[
                [
                    "mes",
                    "num_ofertas",
                    "total_ofertas_con_tecnologia_mes",
                    "pct_ofertas",
                ]
            ].rename(
                columns={
                    "mes": "Mes",
                    "num_ofertas": "Ofertas",
                    "total_ofertas_con_tecnologia_mes": "Ofertas del mes con tecnologías",
                    "pct_ofertas": "% ofertas",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    # --- Modalidad y salarios ---
    col_modalidad, col_salarios = st.columns(2)
    with col_modalidad:
        st.subheader("Modalidad de trabajo")
        modalidad = marts["tendencia_modalidad"]
        modalidad = modalidad[modalidad["mes"].dt.date.between(desde, hasta)]
        if modalidad.empty:
            st.info("No hay ofertas con modalidad conocida en el periodo.")
        else:
            st.altair_chart(
                grafico_modalidad(modalidad, paleta["serie"], paleta["superficie"]),
                width="stretch",
            )
            with st.expander("Ver tabla"):
                st.dataframe(
                    modalidad.assign(
                        mes=modalidad["mes"].dt.strftime("%Y-%m"),
                        modalidad=modalidad["modalidad"].map(ETIQUETAS_MODALIDAD),
                    )[["mes", "modalidad", "num_ofertas", "pct_ofertas"]]
                    .sort_values(["mes", "modalidad"])
                    .rename(
                        columns={
                            "mes": "Mes",
                            "modalidad": "Modalidad",
                            "num_ofertas": "Ofertas",
                            "pct_ofertas": "% ofertas",
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )

    with col_salarios:
        st.subheader("Salarios por tecnología")
        salarios = marts["salarios_por_tecnologia"]
        salarios = salarios[salarios["mes"].dt.date.between(desde, hasta)]
        if salarios.empty:
            st.info("Ninguna oferta del periodo publica salario explícito.")
        else:
            resumen = (
                salarios.groupby("tecnologia", as_index=False)
                .agg(
                    ofertas=("num_ofertas_con_salario", "sum"),
                    salario_mediano=("salario_mediano", "median"),
                )
                .sort_values("ofertas", ascending=False)
            )
            st.dataframe(
                resumen.rename(
                    columns={
                        "tecnologia": "Tecnología",
                        "ofertas": "Ofertas con salario",
                        "salario_mediano": "Salario mediano (€/año)",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "Mediana de las medianas mensuales; solo ofertas con salario explícito."
            )

    # --- Calidad de la extracción ---
    st.subheader("Ofertas sin tecnologías detectadas")
    st.caption(
        "Porcentaje mensual de ofertas clasificadas en las que el LLM no encontró "
        "ninguna tecnología del catálogo."
    )
    st.altair_chart(
        grafico_sin_tecnologia(cobertura_periodo, color_principal), width="stretch"
    )
    with st.expander("Ver tabla"):
        st.dataframe(
            cobertura_periodo.sort_values("mes")
            .assign(mes=lambda df: df["mes"].dt.strftime("%Y-%m"))
            .rename(
                columns={
                    "mes": "Mes",
                    "total_ofertas_clasificadas": "Ofertas clasificadas",
                    "ofertas_sin_tecnologia": "Sin tecnologías",
                    "pct_sin_tecnologia": "% sin tecnologías",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    st.divider()
    st.caption(
        "Datos: [Jobs by Adzuna](https://www.adzuna.es) · The Adzuna API. "
        "Tecnologías, modalidad y salario extraídos automáticamente con un LLM; "
        "pueden contener errores."
    )


if __name__ == "__main__":
    main()
