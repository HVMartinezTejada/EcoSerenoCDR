# -*- coding: utf-8 -*-
"""
Canary test: version minima para verificar que Streamlit Cloud funciona.
Si esta app arranca, el entorno esta bien y el problema esta en app_csr_v2.py
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.set_page_config(
    page_title="Canary CSR",
    layout="wide",
)

st.title("Canary test - EcoSereno")
st.success("Si ves esto, Streamlit Cloud funciona correctamente.")

st.write(f"streamlit: {st.__version__}")
st.write(f"pandas: {pd.__version__}")
st.write(f"numpy: {np.__version__}")

df = pd.DataFrame({
    "material": ["Plastico", "Madera", "Papel", "Textil"],
    "PCI": [10000, 4000, 3700, 4300],
})
st.dataframe(df)

fig = px.bar(df, x="material", y="PCI", title="PCI de referencia")
st.plotly_chart(fig, use_container_width=True)

st.metric("Total materiales", len(df))
