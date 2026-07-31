# -*- coding: utf-8 -*-
"""
Calculadora CSR/RDF v2 - EcoSereno S.A.S. E.S.P.

Version reconstruida para maxima compatibilidad con Streamlit 1.32.2
y Python 3.11.

Extension de la calculadora original de PCI con cinco capas:
  1. PCI base seca (calculo original preservado)
  2. Correccion por humedad (ISO 21645)
  3. Contenido de cloro por catalogo y clasificacion ISO 21640
  4. Desviacion estandar sigma(PCI) como funcion del origen del material
  5. Precio esperado vs paridad con carbon termico Rio Claro

Referencias:
  - ISO 21640:2021 - Solid recovered fuels. Specifications and classes
  - ISO 21645:2021 - Sampling methods
  - Yale Economic Growth Center 2024 - CSR fraccion gruesa (nota tecnica)
  - Rada et al. 2009; Reza et al. 2013 (calibracion sigma por origen)

Autor: H. Vladimir Martinez-T. - EcoSereno S.A.S. E.S.P., 2026
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# =============================================================================
# CONFIGURACION - DEBE SER LA PRIMERA LLAMADA A STREAMLIT
# =============================================================================
st.set_page_config(
    page_title="Calculadora CSR v2 - EcoSereno",
    layout="wide",
)

# =============================================================================
# CATALOGO DE MATERIALES: PCI (base seca) y contenido de cloro Cl%
# Estructura: id -> (nombre, PCI_seco_kcal_kg, Cl_pct)
# =============================================================================
MATERIALES = {
    1:  ("Virutas de madera",                       4000, 0.05),
    2:  ("Serrin",                                  4200, 0.05),
    3:  ("Cascara de arroz",                        3000, 0.08),
    4:  ("Bagazo",                                  3300, 0.10),
    5:  ("Residuos de alimentos",                   1700, 0.60),
    6:  ("Estiercol",                               1300, 0.40),
    7:  ("Residuos solidos urbanos (RSU mezclado)", 2200, 0.80),
    8:  ("Residuos plasticos (mezcla)",            10000, 0.90),
    9:  ("Neumaticos usados",                      10000, 0.15),
    10: ("Residuos de papel",                       3700, 0.15),
    11: ("Escombros",                                  0, 0.05),
    12: ("Arroz quemado",                           3770, 0.10),
    13: ("Aserrin",                                 3900, 0.05),
    14: ("Carton plegadiza",                        3400, 0.15),
    15: ("Cascarilla arroz",                        3700, 0.10),
    16: ("Madera no aprovechable",                  3000, 0.10),
    17: ("Materia vegetal no aprovechable",         1500, 0.30),
    18: ("Trigo no conforme",                       3780, 0.05),
    19: ("Harina no conforme",                      3950, 0.05),
    20: ("Globos de latex",                        10000, 0.30),
    21: ("Latex",                                  10000, 0.30),
    22: ("Solidos contaminados con latex",           3200, 0.40),
    23: ("EPP y dotaciones (mezcla textil)",        4300, 0.35),
    24: ("Bigbags (PP tejido)",                    11000, 0.05),
    25: ("Bolsas Scholle",                          8000, 0.20),
    26: ("Estibas plasticas (PE/PP)",              10000, 0.05),
    27: ("Cinta adhesiva con celulosa",             5000, 0.25),
    28: ("Plastico no aprovechable (con PVC)",      8000, 1.50),
    29: ("ICOPOR (EPS)",                           10030, 0.02),
    30: ("Poliuretano",                             6800, 0.15),
    31: ("Marquilla",                               4300, 0.20),
    32: ("Silicona",                                5570, 0.10),
    33: ("Materiales mixtos (celulosa/plastico)",   6000, 0.40),
    34: ("Toner con tintas no peligrosas",          8000, 0.10),
}

# Lista pre-formateada para selectbox (evita lambda como format_func)
OPCIONES_MATERIALES = [
    "{0} - {1}".format(mid, MATERIALES[mid][0])
    for mid in sorted(MATERIALES.keys())
]

def id_desde_opcion(opcion_str):
    """Extrae el ID entero de la opcion 'ID - Nombre'."""
    return int(opcion_str.split(" - ")[0])

# =============================================================================
# CONSTANTES CIENTIFICAS Y UMBRALES ISO 21640
# =============================================================================
FACTOR_HUMEDAD_KCAL = 583.9

HUMEDAD_OPTIMA_MAX = 15.0
HUMEDAD_ACEPTABLE_MAX = 25.0
HUMEDAD_RECHAZO = 30.0

CLASES_NCV = {
    1: (5975, "NCV 1 (>25 MJ/kg): premium industrial"),
    2: (4780, "NCV 2 (>20 MJ/kg): apto quemador principal"),
    3: (3585, "NCV 3 (>15 MJ/kg): apto calcinador"),
    4: (2390, "NCV 4 (>10 MJ/kg): calcinador con restricciones"),
    5: (717,  "NCV 5 (>3 MJ/kg): valorizacion limitada"),
}

CLASES_CL = {
    1: (0.20, "Cl 1 (<0.2%): apto quemador principal"),
    2: (0.60, "Cl 2 (<0.6%): apto calcinador (corriente)"),
    3: (1.00, "Cl 3 (<1.0%): coprocesamiento con restricciones"),
    4: (1.50, "Cl 4 (<1.5%): dificilmente comercializable"),
    5: (3.00, "Cl 5 (<3.0%): no apto coprocesamiento"),
}

SIGMA_ORIGEN_DEFAULT = {
    "industrial": 200,
    "comercial":  400,
    "rsu":        650,
}

SIGMA_PREMIUM = 250
SIGMA_CORRIENTE = 400

PCI_CARBON_TERMICO = 6500
PRECIO_CARBON_DEFAULT = 350000

FACTOR_PREMIUM = 0.95
FACTOR_CORRIENTE = 0.85
FACTOR_FUERA_ESPEC = 0.65

GRANULOMETRIAS = [
    "Calcinador (50-75 mm)",
    "Quemador principal (25-30 mm)",
    "Molino / precalcinador (<15 mm)",
]

# =============================================================================
# FUNCIONES DE CALCULO
# =============================================================================

def calcular_mezcla_ponderada(inputs):
    """
    Calcula PCI seco ponderado, Cl ponderado y masa total.
    inputs: lista de tuplas [(id_material, cantidad_kg), ...]
    Retorna: (dataframe_detalle, pci_seco, cl_ponderado, masa_total)
    """
    filtrados = [(i, c) for i, c in inputs if c > 0]
    if not filtrados:
        return pd.DataFrame(), 0.0, 0.0, 0.0

    ids = [i for i, c in filtrados]
    cants = [c for i, c in filtrados]

    total_kg = float(sum(cants))
    if total_kg <= 0:
        return pd.DataFrame(), 0.0, 0.0, 0.0

    nombres = [MATERIALES[i][0] for i in ids]
    pcis = [float(MATERIALES[i][1]) for i in ids]
    cls = [float(MATERIALES[i][2]) for i in ids]

    pci_pond = sum(c * p for c, p in zip(cants, pcis)) / total_kg
    cl_pond = sum(c * cl for c, cl in zip(cants, cls)) / total_kg

    df = pd.DataFrame({
        "ID": ids,
        "Material": nombres,
        "PCI seco (kcal/kg)": pcis,
        "Cl (%)": cls,
        "Cantidad (kg)": cants,
        "% en peso": [100.0 * c / total_kg for c in cants],
    })
    return df, float(pci_pond), float(cl_pond), total_kg


def corregir_pci_por_humedad(pci_seco, humedad_pct):
    """PCI real (base humeda) segun ISO 21645."""
    w = humedad_pct / 100.0
    if w >= 1.0:
        return 0.0
    pci_real = pci_seco * (1.0 - w) - FACTOR_HUMEDAD_KCAL * w
    return max(pci_real, 0.0)


def sigma_ponderada_por_origen(p_ind, p_com, p_rsu, s_ind, s_com, s_rsu):
    """sigma resultante por propagacion de varianza (canastas independientes)."""
    pi = p_ind / 100.0
    pc = p_com / 100.0
    pr = p_rsu / 100.0
    varianza = (pi ** 2) * (s_ind ** 2) + (pc ** 2) * (s_com ** 2) + (pr ** 2) * (s_rsu ** 2)
    return float(np.sqrt(varianza))


def clasificar_ncv(pci_kcal):
    """Clase NCV segun ISO 21640."""
    for clase in [1, 2, 3, 4, 5]:
        if pci_kcal >= CLASES_NCV[clase][0]:
            return clase, CLASES_NCV[clase][1]
    return 5, "Fuera de rango (PCI muy bajo)"


def clasificar_cl(cl_pct):
    """Clase Cl segun ISO 21640."""
    for clase in [1, 2, 3, 4, 5]:
        if cl_pct <= CLASES_CL[clase][0]:
            return clase, CLASES_CL[clase][1]
    return 5, "Fuera de rango (Cl muy alto)"


def evaluar_calidad_contractual(sigma_valor):
    """(etiqueta, factor_precio, descripcion) segun sigma."""
    if sigma_valor <= SIGMA_PREMIUM:
        return "premium", FACTOR_PREMIUM, "sigma {:.0f} <= {}: premium".format(sigma_valor, SIGMA_PREMIUM)
    if sigma_valor <= SIGMA_CORRIENTE:
        return "corriente", FACTOR_CORRIENTE, "sigma {:.0f} <= {}: corriente".format(sigma_valor, SIGMA_CORRIENTE)
    return "fuera_espec", FACTOR_FUERA_ESPEC, "sigma {:.0f} > {}: fuera de especificacion".format(sigma_valor, SIGMA_CORRIENTE)


def calcular_precio_esperado(pci_humedo, sigma_val, precio_carbon, pci_carbon,
                              humedad_pct, cl_pct):
    """Precio esperado (COP/t), paridad (COP/t) y diagnostico."""
    if pci_humedo <= 0:
        return 0.0, 0.0, "No comercializable (PCI = 0)"

    paridad = precio_carbon * (pci_humedo / pci_carbon)

    _, factor_sigma, _ = evaluar_calidad_contractual(sigma_val)

    factor_humedad = 1.0
    if humedad_pct > HUMEDAD_ACEPTABLE_MAX:
        factor_humedad = 0.80
    if humedad_pct >= HUMEDAD_RECHAZO:
        return 0.0, paridad, "Rechazo por humedad excesiva"

    factor_cl = 1.0
    if cl_pct > CLASES_CL[2][0]:
        factor_cl = 0.75
    if cl_pct > CLASES_CL[3][0]:
        return 0.0, paridad, "Rechazo por cloro excesivo (> 1.0%)"

    precio_final = paridad * factor_sigma * factor_humedad * factor_cl

    diagnostico = "paridad {:.0f} k * sigma {:.2f} * humedad {:.2f} * Cl {:.2f}".format(
        paridad / 1000.0, factor_sigma, factor_humedad, factor_cl
    )
    return precio_final, paridad, diagnostico


# =============================================================================
# INTERFAZ - CUERPO PRINCIPAL
# =============================================================================

st.title("Calculadora CSR / RDF v2 - EcoSereno")
st.write(
    "Estimacion preliminar de calidad y precio del Combustible Solido "
    "Recuperado (CSR) segun ISO 21640, para orientar decisiones de mezcla "
    "y negociacion con cementera."
)
st.info(
    "Herramienta orientativa. No sustituye caracterizacion de laboratorio "
    "(ISO 21645, calorimetro de bomba)."
)

# -----------------------------------------------------------------------------
# SIDEBAR
# -----------------------------------------------------------------------------
st.sidebar.header("Parametros globales")

n_materiales = st.sidebar.slider(
    "Numero de corrientes",
    min_value=1,
    max_value=len(MATERIALES),
    value=4,
)

st.sidebar.subheader("Humedad (as received)")
humedad = st.sidebar.slider(
    "Humedad de la mezcla (%)",
    min_value=0.0,
    max_value=40.0,
    value=15.0,
    step=0.5,
)

st.sidebar.subheader("Origen del suministro")
st.sidebar.caption("Distribuye 100% entre las tres canastas:")

pct_industrial = st.sidebar.slider("% industrial contratado", 0, 100, 20, 5)
pct_comercial = st.sidebar.slider("% comercial no contratado", 0, 100, 30, 5)
pct_rsu = st.sidebar.slider("% RSU municipal", 0, 100, 50, 5)

total_pct = pct_industrial + pct_comercial + pct_rsu
if total_pct != 100:
    st.sidebar.warning("Suma origenes: {}% (debe ser 100%)".format(total_pct))
else:
    st.sidebar.success("Suma origenes: 100%")

st.sidebar.subheader("Sigma(PCI) por origen (kcal/kg)")
st.sidebar.caption("Supuestos operativos revisables:")
sigma_ind = st.sidebar.number_input(
    "sigma industrial", min_value=100, max_value=400,
    value=SIGMA_ORIGEN_DEFAULT["industrial"], step=25,
)
sigma_com = st.sidebar.number_input(
    "sigma comercial", min_value=200, max_value=600,
    value=SIGMA_ORIGEN_DEFAULT["comercial"], step=25,
)
sigma_rsu = st.sidebar.number_input(
    "sigma RSU", min_value=400, max_value=1000,
    value=SIGMA_ORIGEN_DEFAULT["rsu"], step=25,
)

st.sidebar.subheader("Referencia comercial")
precio_carbon = st.sidebar.number_input(
    "Precio carbon termico Rio Claro (COP/t)",
    min_value=200000, max_value=600000,
    value=PRECIO_CARBON_DEFAULT, step=10000,
)

granulometria_sel = st.sidebar.selectbox(
    "Granulometria objetivo",
    GRANULOMETRIAS,
    index=0,
)

# -----------------------------------------------------------------------------
# TABLA DE REFERENCIA (opcional)
# -----------------------------------------------------------------------------
with st.expander("Tabla de referencia (34 materiales)"):
    df_ref = pd.DataFrame(
        [(k, v[0], v[1], v[2]) for k, v in sorted(MATERIALES.items())],
        columns=["ID", "Material", "PCI seco (kcal/kg)", "Cl (%)"],
    )
    st.dataframe(df_ref)

# -----------------------------------------------------------------------------
# FORMULACION DE LA MEZCLA
# -----------------------------------------------------------------------------
st.subheader("Formulacion de la mezcla")

col_izq, col_der = st.columns(2)
inputs = []

for i in range(n_materiales):
    contenedor = col_izq if (i % 2 == 0) else col_der
    with contenedor:
        st.markdown("**Material {}**".format(i + 1))
        idx_default = min(i, len(OPCIONES_MATERIALES) - 1)
        opcion_sel = st.selectbox(
            "Selecciona material {}".format(i + 1),
            options=OPCIONES_MATERIALES,
            index=idx_default,
            key="sel_{}".format(i),
        )
        mat_id = id_desde_opcion(opcion_sel)
        cant = st.number_input(
            "Cantidad (kg) - material {}".format(i + 1),
            min_value=0.0,
            value=0.0,
            step=1.0,
            key="cant_{}".format(i),
        )
        inputs.append((mat_id, cant))

# -----------------------------------------------------------------------------
# BOTON DE CALCULO
# -----------------------------------------------------------------------------
calcular = st.button("Calcular", type="primary")

if calcular:
    df_mix, pci_seco, cl_pond, total_kg = calcular_mezcla_ponderada(inputs)

    if total_kg <= 0:
        st.error("Introduce cantidades > 0 para al menos un material.")
        st.stop()

    if total_pct != 100:
        st.error(
            "Los porcentajes de origen suman {}%. Ajustalos a 100% antes de calcular.".format(total_pct)
        )
        st.stop()

    pci_humedo = corregir_pci_por_humedad(pci_seco, humedad)
    sigma_val = sigma_ponderada_por_origen(
        pct_industrial, pct_comercial, pct_rsu,
        sigma_ind, sigma_com, sigma_rsu,
    )

    ncv_c, ncv_d = clasificar_ncv(pci_humedo)
    cl_c, cl_d = clasificar_cl(cl_pond)
    calidad_e, factor_cal, calidad_d = evaluar_calidad_contractual(sigma_val)

    precio_final, precio_paridad, precio_diag = calcular_precio_esperado(
        pci_humedo, sigma_val, precio_carbon, PCI_CARBON_TERMICO,
        humedad, cl_pond,
    )

    # =========================================================================
    # RESULTADOS PRINCIPALES
    # =========================================================================
    st.markdown("---")
    st.subheader("Resultados principales")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Masa total", "{:,.0f} kg".format(total_kg))
    m2.metric("PCI base seca", "{:,.0f} kcal/kg".format(pci_seco))
    m3.metric(
        "PCI base humeda",
        "{:,.0f} kcal/kg".format(pci_humedo),
        delta="{:,.0f} por humedad".format(pci_humedo - pci_seco),
        delta_color="inverse",
    )
    m4.metric("sigma(PCI)", "{:,.0f} kcal/kg".format(sigma_val))

    # =========================================================================
    # CLASIFICACION ISO 21640
    # =========================================================================
    st.markdown("---")
    st.subheader("Clasificacion ISO 21640")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Clase NCV (poder calorifico)**")
        st.markdown("### NCV {}".format(ncv_c))
        st.caption(ncv_d)
    with c2:
        st.markdown("**Clase Cl (cloro)**")
        st.markdown("### Cl {}".format(cl_c))
        st.caption("{:.2f}% - {}".format(cl_pond, cl_d))
    with c3:
        st.markdown("**Calidad contractual**")
        st.markdown("### {}".format(calidad_e.upper()))
        st.caption(calidad_d)

    # =========================================================================
    # PRECIO ESPERADO
    # =========================================================================
    st.markdown("---")
    st.subheader("Precio esperado")

    p1, p2, p3 = st.columns(3)
    p1.metric(
        "Techo por paridad carbon",
        "{:,.0f} k COP/t".format(precio_paridad / 1000.0),
    )
    p2.metric(
        "Precio esperado CSR",
        "{:,.0f} k COP/t".format(precio_final / 1000.0),
        delta="-{:,.0f} k vs paridad".format((precio_paridad - precio_final) / 1000.0),
        delta_color="inverse",
    )
    p3.metric("Granulometria objetivo", granulometria_sel.split(" (")[0])

    st.caption("Desglose: " + precio_diag)

    # Validacion de compatibilidad
    st.markdown("**Compatibilidad mercado / especificacion:**")

    if "Quemador principal" in granulometria_sel and cl_c > 1:
        st.error(
            "Producto no apto para quemador principal: requiere Cl 1 (<0.2%). "
            "La mezcla tiene {:.2f}%. Reformular o dirigir a calcinador.".format(cl_pond)
        )
    elif "Calcinador" in granulometria_sel and cl_c > 2:
        st.warning(
            "Cl clase {} podria ser rechazado por cementera; recomendable Cl 2 (<0.6%).".format(cl_c)
        )
    elif ncv_c >= 4:
        st.warning(
            "NCV clase {}: PCI bajo, precio muy penalizado. Aumentar plasticos.".format(ncv_c)
        )
    else:
        st.success(
            "Compatible con {}. Resumen: NCV {} / Cl {} / {}".format(
                granulometria_sel, ncv_c, cl_c, calidad_e
            )
        )

    # =========================================================================
    # DETALLE DE LA MEZCLA
    # =========================================================================
    st.markdown("---")
    st.subheader("Detalle de la mezcla")

    df_mix_disp = df_mix.copy()
    df_mix_disp["% en peso"] = df_mix_disp["% en peso"].round(1)
    df_mix_disp["Cl (%)"] = df_mix_disp["Cl (%)"].round(2)
    st.dataframe(df_mix_disp)

    # Grafico simple de composicion
    if len(df_mix) > 0:
        col_a, col_b = st.columns(2)
        with col_a:
            fig_comp = px.pie(
                df_mix,
                names="Material",
                values="Cantidad (kg)",
                hole=0.4,
                title="Composicion (PCI seco: {:,.0f} kcal/kg)".format(pci_seco),
            )
            st.plotly_chart(fig_comp)

        with col_b:
            df_orig = pd.DataFrame({
                "Origen": ["Industrial", "Comercial", "RSU municipal"],
                "% suministro": [pct_industrial, pct_comercial, pct_rsu],
                "sigma (kcal/kg)": [sigma_ind, sigma_com, sigma_rsu],
            })
            fig_orig = px.bar(
                df_orig,
                x="Origen",
                y="% suministro",
                color="sigma (kcal/kg)",
                color_continuous_scale="RdYlGn_r",
                title="Suministro por origen (sigma total: {:.0f})".format(sigma_val),
                text="% suministro",
            )
            st.plotly_chart(fig_orig)

    # =========================================================================
    # NOTAS METODOLOGICAS
    # =========================================================================
    with st.expander("Notas metodologicas y referencias"):
        st.markdown(
            "**Formulas aplicadas:**\n\n"
            "- PCI ponderado (seco): PCI = sum(m_i * PCI_i) / sum(m_i)\n"
            "- PCI base humeda (ISO 21645): PCI_r = PCI_seco * (1 - w) - 583.9 * w\n"
            "- sigma(PCI) por origen: sigma = sqrt(sum(p_i^2 * sigma_i^2))\n"
            "- Precio esperado: precio_carbon * (PCI_CSR / PCI_carbon) * factores\n\n"
            "**Referencias:**\n"
            "- ISO 21640:2021 Solid recovered fuels. Specifications and classes\n"
            "- ISO 21645:2021 Solid recovered fuels. Methods for sampling\n"
            "- ISO 21654:2021 Determination of calorific value\n"
            "- Rada et al. (2009); Reza et al. (2013)\n"
            "- Yale Economic Growth Center (2024) - CSR fraccion gruesa\n\n"
            "**Supuestos operativos revisables:**\n\n"
            "Los coeficientes de sigma por origen (200/400/650 kcal/kg) provienen "
            "de literatura y no de mediciones especificas del NAP EcoSereno. "
            "Se recomienda calibrar con la primera campana de caracterizacion en planta.\n\n"
            "**Limitaciones:**\n\n"
            "- No modela azufre, metales pesados, ni fraccion biogenica.\n"
            "- Los valores de Cl% del catalogo son referenciales.\n"
            "- Herramienta orientadora previa a caracterizacion de laboratorio."
        )

# -----------------------------------------------------------------------------
# FOOTER
# -----------------------------------------------------------------------------
st.markdown("---")
st.caption("Calculadora CSR v2 - EcoSereno S.A.S. E.S.P. | H. Vladimir Martinez-T. | 2026")
