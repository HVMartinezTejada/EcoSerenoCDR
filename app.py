# -*- coding: utf-8 -*-
"""
Calculadora CSR/RDF v2 - EcoSereno S.A.S. E.S.P.

Extension de la calculadora original de PCI para incorporar:
  Capa 1: PCI base seca (calculo original preservado)
  Capa 2: Correccion por humedad (ISO 21645)
  Capa 3: Contenido de cloro por catalogo y clasificacion ISO 21640
  Capa 4: Desviacion estandar sigma(PCI) como funcion del origen del material
  Capa 5: Precio esperado vs paridad con carbon termico Rio Claro

Referencias:
  - ISO 21640:2021 - Solid recovered fuels. Specifications and classes
  - ISO 21645:2021 - Sampling methods
  - Yale Economic Growth Center 2024 - CSR fraccion gruesa (nota tecnica)
  - Rada et al. 2009; Reza et al. 2013 (calibracion sigma por origen)

Autor: H. Vladimir Martinez-T. (adaptacion sobre app original de RETIRAR SAS ESP)
"""

# =============================================================================
# 1) LIBRERIAS Y CONFIGURACION
# =============================================================================
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(
    page_title="Calculadora CSR v2 (EcoSereno)",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# 2) CATALOGO DE MATERIALES: PCI (base seca) y contenido de cloro Cl%
# =============================================================================
# Estructura: id: (nombre, PCI_seco_kcal/kg, Cl% en peso)
# Los valores de Cl provienen de literatura tecnica (ISO 21640 Anexo B,
# publicaciones de coprocesamiento cementero, y datos de plantas europeas
# de CSR). Se documentan como referenciales para orden de magnitud.
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
    22: ("Solidos contaminados con latex",          3200, 0.40),
    23: ("EPP y dotaciones (mezcla textil)",        4300, 0.35),
    24: ("Bigbags (PP tejido)",                    11000, 0.05),
    25: ("Bolsas Scholle",                          8000, 0.20),
    26: ("Estibas plasticas (PE/PP)",              10000, 0.05),
    27: ("Cinta adhesiva con celulosa",             5000, 0.25),
    28: ("Plastico no aprovechable (mezcla PVC?)",  8000, 1.50),
    29: ("ICOPOR (EPS)",                           10030, 0.02),
    30: ("Poliuretano",                             6800, 0.15),
    31: ("Marquilla",                               4300, 0.20),
    32: ("Silicona",                                5570, 0.10),
    33: ("Materiales mixtos (celulosa/plastico)",   6000, 0.40),
    34: ("Toner con tintas no peligrosas",          8000, 0.10),
}

# =============================================================================
# 3) CONSTANTES CIENTIFICAS Y UMBRALES ISO 21640
# =============================================================================

# --- Correccion por humedad (ISO 21645) ---
# PCI_real = PCI_seco * (1 - w) - CALOR_VAPORIZACION_AGUA * w
CALOR_VAPORIZACION_AGUA = 2442.0  # kJ/kg equivalente en kcal/kg (2.442 MJ/kg)
# Nota: el factor real es ~2442 kJ/kg = 583 kcal/kg; para uso practico en
# kcal/kg se usa 2.442 MJ/kg convertido a kcal/kg = 583.9 kcal/kg
FACTOR_HUMEDAD_KCAL = 583.9

# --- Umbrales de humedad para coprocesamiento ---
HUMEDAD_OPTIMA_MAX = 15.0    # % - premium
HUMEDAD_ACEPTABLE_MAX = 25.0 # % - corriente
HUMEDAD_RECHAZO = 30.0       # % - no comercializable

# --- Clases ISO 21640 por PCI (NCV, valor mediano en kcal/kg) ---
# ISO 21640 usa MJ/kg; conversion: 1 MJ/kg = 239.0 kcal/kg
CLASES_NCV = {
    1: {"min_kcal": 5975, "descripcion": "NCV 1 (>25 MJ/kg): premium industrial"},
    2: {"min_kcal": 4780, "descripcion": "NCV 2 (>20 MJ/kg): apto quemador principal"},
    3: {"min_kcal": 3585, "descripcion": "NCV 3 (>15 MJ/kg): apto calcinador"},
    4: {"min_kcal": 2390, "descripcion": "NCV 4 (>10 MJ/kg): calcinador con restricciones"},
    5: {"min_kcal":  717, "descripcion": "NCV 5 (>3 MJ/kg): valorizacion limitada"},
}

# --- Clases ISO 21640 por cloro (Cl%) ---
CLASES_CL = {
    1: {"max": 0.20, "descripcion": "Cl 1 (<0.2%): apto quemador principal"},
    2: {"max": 0.60, "descripcion": "Cl 2 (<0.6%): apto calcinador (corriente)"},
    3: {"max": 1.00, "descripcion": "Cl 3 (<1.0%): coprocesamiento con restricciones"},
    4: {"max": 1.50, "descripcion": "Cl 4 (<1.5%): dificilmente comercializable"},
    5: {"max": 3.00, "descripcion": "Cl 5 (<3.0%): no apto coprocesamiento"},
}

# --- Sigma(PCI) por origen del material (kcal/kg) ---
# Coeficientes de literatura, tratados como supuestos operativos revisables.
# Fuentes: Yale Economic Growth Center 2024; Rada et al. 2009; Reza et al. 2013;
# ISO 21640 Anexo A (estadistica de variabilidad).
SIGMA_ORIGEN_DEFAULT = {
    "industrial_contratado": 200,  # rango literatura: 150-250
    "comercial_no_contratado": 400,  # rango: 300-450
    "rsu_municipal": 650,  # rango: 500-800
}

# --- Umbrales de sigma para calidad contractual ---
SIGMA_PREMIUM = 250    # premium: sigma <= 250 kcal/kg
SIGMA_CORRIENTE = 400  # corriente: sigma <= 400 kcal/kg

# --- Referencias de carbon termico Rio Claro (paridad economica) ---
PCI_CARBON_TERMICO = 6500       # kcal/kg (referencia zona Antioquia)
PRECIO_CARBON_DEFAULT = 350000  # COP/t CIF cementera Rio Claro (referencial 2026)

# --- Factores de calidad y sigma sobre el precio ---
FACTOR_PREMIUM = 0.95     # premium comercializable a 95% de paridad carbon
FACTOR_CORRIENTE = 0.85   # corriente a 85%
FACTOR_FUERA_ESPEC = 0.65 # penalizacion si sigma > 400

# --- Granulometria por punto de inyeccion ---
GRANULOMETRIA = {
    "calcinador (50-75 mm)": {"min": 50, "max": 75, "mercado": "calcinador"},
    "quemador principal (25-30 mm)": {"min": 25, "max": 30, "mercado": "quemador"},
    "molino/precalcinador (<15 mm)": {"min": 0, "max": 15, "mercado": "molino"},
}

# =============================================================================
# 4) FUNCIONES DE CALCULO
# =============================================================================

def calcular_mezcla_ponderada(inputs):
    """
    Calcula PCI seco ponderado, Cl ponderado y masa total.
    inputs: lista de tuplas [(id_material, cantidad_kg), ...]
    """
    if not inputs:
        return pd.DataFrame(), 0.0, 0.0, 0.0

    ids = [i for i, c in inputs if c > 0]
    cants = [c for i, c in inputs if c > 0]

    if not ids or sum(cants) <= 0:
        return pd.DataFrame(), 0.0, 0.0, 0.0

    ids_arr = np.array(ids, dtype=int)
    cants_arr = np.array(cants, dtype=float)
    nombres = [MATERIALES[i][0] for i in ids_arr]
    pcis = np.array([MATERIALES[i][1] for i in ids_arr], dtype=float)
    cls = np.array([MATERIALES[i][2] for i in ids_arr], dtype=float)

    total_kg = float(cants_arr.sum())
    pci_pond = float(np.dot(cants_arr, pcis) / total_kg)
    cl_pond = float(np.dot(cants_arr, cls) / total_kg)

    df = pd.DataFrame({
        "ID": ids_arr,
        "Material": nombres,
        "PCI seco (kcal/kg)": pcis,
        "Cl (%)": cls,
        "Cantidad (kg)": cants_arr,
        "% en peso": (cants_arr / total_kg) * 100,
    })
    return df, pci_pond, cl_pond, total_kg


def corregir_pci_por_humedad(pci_seco, humedad_pct):
    """
    Aplica correccion ISO 21645 para PCI en base humeda (as received).
    pci_seco: PCI en base seca (kcal/kg)
    humedad_pct: contenido de humedad como porcentaje (0-100)
    Retorna: PCI real (base humeda) en kcal/kg
    """
    w = humedad_pct / 100.0
    if w >= 1.0:
        return 0.0
    pci_real = pci_seco * (1 - w) - FACTOR_HUMEDAD_KCAL * w
    return max(pci_real, 0.0)


def sigma_ponderada_por_origen(pct_industrial, pct_comercial, pct_rsu,
                                sigma_ind, sigma_com, sigma_rsu):
    """
    Calcula sigma(PCI) resultante como propagacion de varianza de canastas.
    Asume independencia entre origenes (simplificacion conservadora).

    Formula: sigma_total = sqrt(sum(p_i^2 * sigma_i^2))
    """
    p_ind = pct_industrial / 100.0
    p_com = pct_comercial / 100.0
    p_rsu = pct_rsu / 100.0

    varianza = (p_ind**2 * sigma_ind**2 +
                p_com**2 * sigma_com**2 +
                p_rsu**2 * sigma_rsu**2)
    return float(np.sqrt(varianza))


def clasificar_ncv(pci_kcal):
    """Clasifica PCI segun ISO 21640 clase NCV (1 mejor, 5 peor)."""
    for clase in [1, 2, 3, 4, 5]:
        if pci_kcal >= CLASES_NCV[clase]["min_kcal"]:
            return clase, CLASES_NCV[clase]["descripcion"]
    return 5, "Fuera de rango (PCI muy bajo)"


def clasificar_cl(cl_pct):
    """Clasifica cloro segun ISO 21640 clase Cl."""
    for clase in [1, 2, 3, 4, 5]:
        if cl_pct <= CLASES_CL[clase]["max"]:
            return clase, CLASES_CL[clase]["descripcion"]
    return 5, "Fuera de rango (Cl muy alto, no apto)"


def evaluar_calidad_contractual(sigma_valor):
    """
    Determina la calidad comercial segun sigma.
    Retorna: (etiqueta, factor_precio, descripcion)
    """
    if sigma_valor <= SIGMA_PREMIUM:
        return "premium", FACTOR_PREMIUM, f"sigma = {sigma_valor:.0f} <= {SIGMA_PREMIUM}: premium"
    elif sigma_valor <= SIGMA_CORRIENTE:
        return "corriente", FACTOR_CORRIENTE, f"sigma = {sigma_valor:.0f} <= {SIGMA_CORRIENTE}: corriente"
    else:
        return "fuera_espec", FACTOR_FUERA_ESPEC, f"sigma = {sigma_valor:.0f} > {SIGMA_CORRIENTE}: fuera de especificacion"


def calcular_precio_esperado(pci_humedo, sigma_val, precio_carbon, pci_carbon,
                              humedad_pct, cl_pct, granulometria_apta):
    """
    Precio esperado del CSR en COP/t.
    precio = precio_carbon * (PCI_CSR / PCI_carbon) * factor_calidad * factor_penalizaciones
    """
    if pci_humedo <= 0:
        return 0.0, 0.0, "No comercializable (PCI = 0)"

    # Techo por paridad de carbon termico
    precio_paridad = precio_carbon * (pci_humedo / pci_carbon)

    # Factor por sigma (calidad contractual)
    _, factor_sigma, _ = evaluar_calidad_contractual(sigma_val)

    # Penalizacion por humedad excesiva
    factor_humedad = 1.0
    if humedad_pct > HUMEDAD_ACEPTABLE_MAX:
        factor_humedad = 0.80
    if humedad_pct >= HUMEDAD_RECHAZO:
        return 0.0, precio_paridad, "Rechazo por humedad excesiva"

    # Penalizacion por cloro (impide mercado quemador principal si Cl > 0.2)
    factor_cl = 1.0
    if cl_pct > CLASES_CL[2]["max"]:  # > 0.6%
        factor_cl = 0.75
    if cl_pct > CLASES_CL[3]["max"]:  # > 1.0%
        return 0.0, precio_paridad, "Rechazo por cloro excesivo (> 1.0%)"

    # Penalizacion si granulometria no es apta
    factor_granulometria = 1.0 if granulometria_apta else 0.85

    precio_final = precio_paridad * factor_sigma * factor_humedad * factor_cl * factor_granulometria

    diagnostico = (f"paridad {precio_paridad/1000:.0f} k COP/t * "
                   f"sigma {factor_sigma:.2f} * humedad {factor_humedad:.2f} * "
                   f"Cl {factor_cl:.2f} * gran {factor_granulometria:.2f}")

    return precio_final, precio_paridad, diagnostico


# =============================================================================
# 5) INTERFAZ STREAMLIT
# =============================================================================

st.title("Calculadora CSR / RDF v2 - EcoSereno")
st.markdown(
    "Estimacion preliminar de calidad y precio del combustible solido "
    "recuperado (CSR) segun ISO 21640, para orientar decisiones de mezcla "
    "y negociacion con cementera. **No sustituye caracterizacion de "
    "laboratorio (ISO 21645, calorimetro de bomba).**"
)

# -----------------------------------------------------------------------------
# Sidebar: parametros globales de la mezcla
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("Parametros globales")

    n_materiales = st.slider(
        "Numero de corrientes",
        min_value=1,
        max_value=len(MATERIALES),
        value=4,
        help="Cantidad de materiales distintos en la mezcla",
    )

    st.markdown("---")
    st.subheader("Humedad (as received)")
    humedad = st.slider(
        "Humedad de la mezcla (%)",
        min_value=0.0,
        max_value=40.0,
        value=15.0,
        step=0.5,
        help="ISO 21645: la cementera acepta hasta 25%; >30% se rechaza",
    )

    st.markdown("---")
    st.subheader("Origen del suministro")
    st.caption("Distribuye 100% entre las tres canastas:")

    pct_industrial = st.slider("% industrial contratado",
                                0, 100, 20, 5,
                                help="Rechazos contratados de composicion estable")
    pct_comercial = st.slider("% comercial no contratado",
                               0, 100, 30, 5,
                               help="Centros comerciales, oficinas")
    pct_rsu = st.slider("% RSU municipal",
                        0, 100, 50, 5,
                        help="Domiciliario mezclado")

    total_pct = pct_industrial + pct_comercial + pct_rsu
    if total_pct != 100:
        st.warning(f"Suma origenes: {total_pct}% (debe ser 100%)")
    else:
        st.success(f"Suma origenes: 100%")

    st.markdown("---")
    st.subheader("Sigma(PCI) por origen (kcal/kg)")
    st.caption("Supuestos operativos revisables - literatura:")
    sigma_ind = st.number_input("sigma industrial",
                                  min_value=100, max_value=400,
                                  value=SIGMA_ORIGEN_DEFAULT["industrial_contratado"],
                                  step=25)
    sigma_com = st.number_input("sigma comercial",
                                  min_value=200, max_value=600,
                                  value=SIGMA_ORIGEN_DEFAULT["comercial_no_contratado"],
                                  step=25)
    sigma_rsu = st.number_input("sigma RSU",
                                  min_value=400, max_value=1000,
                                  value=SIGMA_ORIGEN_DEFAULT["rsu_municipal"],
                                  step=25)

    st.markdown("---")
    st.subheader("Referencia comercial")
    precio_carbon = st.number_input(
        "Precio carbon termico Rio Claro (COP/t)",
        min_value=200000, max_value=600000,
        value=PRECIO_CARBON_DEFAULT,
        step=10000,
        help="Techo economico absoluto: el CSR no supera este precio por paridad termica",
    )

    granulometria_seleccion = st.selectbox(
        "Granulometria objetivo",
        list(GRANULOMETRIA.keys()),
        index=0,
    )

# -----------------------------------------------------------------------------
# Cuerpo principal: tabla de referencia
# -----------------------------------------------------------------------------
with st.expander("Tabla de referencia (34 materiales)", expanded=False):
    df_ref = pd.DataFrame(
        [(k, v[0], v[1], v[2]) for k, v in MATERIALES.items()],
        columns=["ID", "Material", "PCI seco (kcal/kg)", "Cl (%)"],
    )
    st.dataframe(df_ref, hide_index=True, use_container_width=True)

# -----------------------------------------------------------------------------
# Formulacion de la mezcla
# -----------------------------------------------------------------------------
st.subheader("Formulacion de la mezcla")
cols = st.columns(2)
inputs = []
for i in range(n_materiales):
    with cols[i % 2]:
        st.markdown(f"**Material {i+1}**")
        mat_id = st.selectbox(
            f"ID material {i+1}",
            options=list(MATERIALES.keys()),
            index=i if i < len(MATERIALES) else 0,
            format_func=lambda x: f"{x} - {MATERIALES[x][0]}",
            key=f"id_{i}",
        )
        cant = st.number_input(
            f"Cantidad (kg) {i+1}",
            min_value=0.0, value=0.0, step=1.0,
            key=f"cant_{i}",
        )
        inputs.append((mat_id, cant))

# -----------------------------------------------------------------------------
# Boton de calculo y resultados
# -----------------------------------------------------------------------------
if st.button("Calcular", type="primary", use_container_width=True):

    df_mix, pci_seco, cl_pond, total_kg = calcular_mezcla_ponderada(inputs)

    if total_kg <= 0:
        st.error("Introduce cantidades > 0 para al menos un material.")
        st.stop()

    if total_pct != 100:
        st.error(f"Los porcentajes de origen suman {total_pct}%. Ajustalos a 100% antes de calcular.")
        st.stop()

    # === CAPA 2: correccion por humedad ===
    pci_humedo = corregir_pci_por_humedad(pci_seco, humedad)

    # === CAPA 4: sigma ponderada por origen ===
    sigma_val = sigma_ponderada_por_origen(
        pct_industrial, pct_comercial, pct_rsu,
        sigma_ind, sigma_com, sigma_rsu,
    )

    # === CAPA 3: clasificaciones ISO 21640 ===
    ncv_clase, ncv_desc = clasificar_ncv(pci_humedo)
    cl_clase, cl_desc = clasificar_cl(cl_pond)
    calidad_etiq, factor_calidad, calidad_desc = evaluar_calidad_contractual(sigma_val)

    # === CAPA 5: precio esperado ===
    granulometria_info = GRANULOMETRIA[granulometria_seleccion]
    granulometria_apta = True  # asumimos que la planta produce en la granulometria seleccionada
    precio_final, precio_paridad, precio_diag = calcular_precio_esperado(
        pci_humedo, sigma_val, precio_carbon, PCI_CARBON_TERMICO,
        humedad, cl_pond, granulometria_apta,
    )

    # =========================================================================
    # RESULTADOS - Metricas principales
    # =========================================================================
    st.markdown("---")
    st.subheader("Resultados principales")

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Masa total", f"{total_kg:,.0f} kg")
    with m2:
        st.metric("PCI base seca", f"{pci_seco:,.0f} kcal/kg")
    with m3:
        delta_h = pci_humedo - pci_seco
        st.metric("PCI base humeda",
                  f"{pci_humedo:,.0f} kcal/kg",
                  delta=f"{delta_h:,.0f} por humedad",
                  delta_color="inverse")
    with m4:
        st.metric("sigma(PCI)",
                  f"{sigma_val:,.0f} kcal/kg",
                  help=f"Umbrales: <={SIGMA_PREMIUM} premium, <={SIGMA_CORRIENTE} corriente")

    # =========================================================================
    # Clasificacion ISO 21640
    # =========================================================================
    st.markdown("---")
    st.subheader("Clasificacion ISO 21640")

    c1, c2, c3 = st.columns(3)
    with c1:
        color_ncv = "green" if ncv_clase <= 3 else "orange" if ncv_clase == 4 else "red"
        st.markdown(f"**Clase NCV (poder calorifico)**")
        st.markdown(f"<h2 style='color:{color_ncv}'>NCV {ncv_clase}</h2>",
                    unsafe_allow_html=True)
        st.caption(ncv_desc)

    with c2:
        color_cl = "green" if cl_clase <= 2 else "orange" if cl_clase == 3 else "red"
        st.markdown(f"**Clase Cl (cloro)**")
        st.markdown(f"<h2 style='color:{color_cl}'>Cl {cl_clase}</h2>",
                    unsafe_allow_html=True)
        st.caption(f"{cl_pond:.2f}% -- {cl_desc}")

    with c3:
        color_cal = ("green" if calidad_etiq == "premium"
                     else "orange" if calidad_etiq == "corriente"
                     else "red")
        st.markdown(f"**Calidad contractual**")
        st.markdown(f"<h2 style='color:{color_cal}'>{calidad_etiq.upper()}</h2>",
                    unsafe_allow_html=True)
        st.caption(calidad_desc)

    # =========================================================================
    # Precio esperado y paridad
    # =========================================================================
    st.markdown("---")
    st.subheader("Precio esperado")

    p1, p2, p3 = st.columns(3)
    with p1:
        st.metric("Techo por paridad carbon",
                  f"{precio_paridad/1000:,.0f} k COP/t",
                  help=f"Paridad termica: precio_carbon * (PCI_CSR / {PCI_CARBON_TERMICO})")
    with p2:
        st.metric("Precio esperado CSR",
                  f"{precio_final/1000:,.0f} k COP/t",
                  delta=f"-{(precio_paridad-precio_final)/1000:,.0f}k vs paridad",
                  delta_color="inverse")
    with p3:
        st.metric("Punto de inyeccion",
                  granulometria_info["mercado"],
                  help=granulometria_seleccion)

    st.caption(f"Desglose: {precio_diag}")

    # === Validacion de compatibilidad mercado / clase ===
    st.markdown("**Compatibilidad mercado / especificacion:**")
    if granulometria_info["mercado"] == "quemador" and cl_clase > 1:
        st.error(
            f"[!] Producto no apto para quemador principal: requiere Cl 1 (<0.2%), "
            f"la mezcla tiene {cl_pond:.2f}%. Reformular o dirigir a calcinador."
        )
    elif granulometria_info["mercado"] == "calcinador" and cl_clase > 2:
        st.warning(
            f"[!] Cl {cl_clase} podria ser rechazado por cementera; recomendable Cl 2 (<0.6%)."
        )
    elif ncv_clase >= 4:
        st.warning(
            f"[!] NCV {ncv_clase}: PCI bajo, precio muy penalizado. Aumentar plasticos/mixtos."
        )
    else:
        st.success(
            f"[OK] Compatible con {granulometria_seleccion}. "
            f"Clase resumen: NCV {ncv_clase} / Cl {cl_clase} / {calidad_etiq}"
        )

    # =========================================================================
    # Detalle de la mezcla
    # =========================================================================
    st.markdown("---")
    st.subheader("Detalle de la mezcla")

    df_mix_disp = df_mix.copy()
    df_mix_disp["% en peso"] = df_mix_disp["% en peso"].map(lambda x: f"{x:.1f}%")
    df_mix_disp["Cl (%)"] = df_mix_disp["Cl (%)"].map(lambda x: f"{x:.2f}%")
    st.dataframe(df_mix_disp, hide_index=True, use_container_width=True)

    # Grafico de composicion
    if len(df_mix) > 0:
        cA, cB = st.columns(2)
        with cA:
            fig_comp = px.pie(
                df_mix, names="Material", values="Cantidad (kg)",
                hole=0.4,
                title=f"Composicion (PCI seco: {pci_seco:,.0f} kcal/kg)",
            )
            fig_comp.update_layout(margin=dict(t=40, b=10), height=350)
            st.plotly_chart(fig_comp, use_container_width=True)

        with cB:
            # Grafico de barras: origen del suministro
            df_orig = pd.DataFrame({
                "Origen": ["Industrial", "Comercial", "RSU municipal"],
                "% suministro": [pct_industrial, pct_comercial, pct_rsu],
                "sigma (kcal/kg)": [sigma_ind, sigma_com, sigma_rsu],
            })
            fig_orig = px.bar(
                df_orig, x="Origen", y="% suministro",
                color="sigma (kcal/kg)",
                color_continuous_scale="RdYlGn_r",
                title=f"Suministro por origen (sigma total: {sigma_val:.0f})",
                text="% suministro",
            )
            fig_orig.update_traces(texttemplate='%{text}%', textposition='outside')
            fig_orig.update_layout(margin=dict(t=40, b=10), height=350)
            st.plotly_chart(fig_orig, use_container_width=True)

    # =========================================================================
    # Notas metodologicas
    # =========================================================================
    with st.expander("Notas metodologicas y referencias", expanded=False):
        st.markdown("""
        **Formulas aplicadas:**

        - **PCI ponderado (seco):** `PCI = sum(m_i * PCI_i) / sum(m_i)` (norma industrial)
        - **PCI base humeda (ISO 21645):** `PCI_r = PCI_seco * (1-w) - 583.9 * w` con w = fraccion humedad
        - **sigma(PCI) por origen:** `sigma = sqrt(sum(p_i^2 * sigma_i^2))` -- propagacion de varianza
        - **Precio esperado:** `precio = precio_carbon * (PCI_CSR/PCI_carbon) * factor_sigma * factor_humedad * factor_Cl * factor_granulometria`

        **Referencias:**
        - ISO 21640:2021 Solid recovered fuels. Specifications and classes
        - ISO 21645:2021 Solid recovered fuels. Methods for sampling
        - ISO 21654:2021 Determination of calorific value
        - Rada, E.C. et al. (2009). RDF/SRF variability characterisation
        - Reza, B. et al. (2013). Statistical analysis of SRF properties
        - Yale Economic Growth Center (2024). CSR fraccion gruesa: nota tecnica

        **Supuestos operativos revisables:**

        Los coeficientes de sigma por origen (200/400/650 kcal/kg) provienen de literatura
        y no de mediciones especificas del NAP EcoSereno. Se recomienda calibrar con la
        primera campana de caracterizacion ISO 21645 en planta.

        **Limitaciones:**

        - No modela azufre (S), metales pesados, ni fraccion biogenica.
        - Los valores de Cl% del catalogo son referenciales; el valor real depende
          del tipo especifico de plastico o textil (por ejemplo, PVC vs PE).
        - Esta herramienta es orientadora previa a caracterizacion de laboratorio.
        """)

# -----------------------------------------------------------------------------
# Footer
# -----------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: #7F8C8D; font-size: 12px;">
        <p><strong>Calculadora CSR v2</strong> - EcoSereno S.A.S. E.S.P.</p>
        <p>Adaptacion sobre la calculadora original de RETIRAR SAS ESP - Unidad I+D+i</p>
        <p>H. Vladimir Martinez-T. -- 2026</p>
    </div>
    """,
    unsafe_allow_html=True,
)
