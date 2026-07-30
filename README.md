# Calculadora CSR / RDF v2 — EcoSereno

Herramienta de estimación preliminar de calidad y precio del **Combustible Sólido Recuperado (CSR)** según ISO 21640:2021, para orientar decisiones de mezcla y negociación con cementera.

Extensión de la calculadora original de PCI ([RETIRAR SAS ESP](https://github.com/HVMartinezTejada)) con cinco capas de análisis integradas.

---

## Qué hace

Esta herramienta convierte una composición de mezcla de residuos en una **estimación de precio comercial esperado** en la cadena CSR → coprocesamiento cementero, incorporando las variables que la industria realmente valora:

1. **Capa 1 — PCI base seca:** cálculo ponderado por masa a partir del catálogo de 34 materiales.
2. **Capa 2 — Corrección por humedad:** aplicación de ISO 21645 (PCI real *as received*).
3. **Capa 3 — Contenido de cloro:** clasificación ISO 21640 (Cl 1 a Cl 5), determinante para acceso al quemador principal vs calcinador.
4. **Capa 4 — σ(PCI) por origen:** modelización de la desviación estándar como función de la proporción industrial contratado / comercial / RSU municipal.
5. **Capa 5 — Precio esperado:** cálculo con paridad térmica de carbón Río Claro como techo económico absoluto, con ajustes por σ, humedad, cloro y granulometría.

---

## Instalación local

```bash
git clone https://github.com/HVMartinezTejada/rdf-energy-calculator.git
cd rdf-energy-calculator
pip install -r requirements.txt
streamlit run app_csr_v2.py
```

Se abre en `http://localhost:8501`.

## Despliegue en Streamlit Community Cloud

1. Subir el repositorio a GitHub (público o privado).
2. Ir a [share.streamlit.io](https://share.streamlit.io) y hacer login con GitHub.
3. "New app" → seleccionar el repositorio → `app_csr_v2.py` como main file.
4. Deploy. Streamlit detecta `requirements.txt` automáticamente.

---

## Cómo interpretar los resultados

### Clases ISO 21640

- **NCV** (Net Calorific Value): 1 (mejor) a 5 (peor). Cementera acepta típicamente NCV 3 o mejor.
- **Cl** (cloro): 1 (mejor) a 5 (peor). Quemador principal requiere Cl 1; calcinador acepta hasta Cl 2.

### Calidad contractual

- **Premium**: σ ≤ 250 kcal/kg → precio 95% de paridad carbón.
- **Corriente**: σ ≤ 400 kcal/kg → precio 85% de paridad carbón.
- **Fuera de especificación**: σ > 400 → precio penalizado 65% de paridad.

### Techo económico absoluto

El CSR nunca debería superar el precio del carbón térmico ponderado por PCI relativo. Este es el **límite superior de negociación**; cualquier precio por encima indica que la cementera está pagando por otro atributo (por ejemplo carbono biogénico) o que el escenario está fuera de mercado.

---

## Supuestos operativos revisables

Los coeficientes de σ por origen son valores de literatura, no mediciones específicas del NAP EcoSereno:

| Origen | σ(PCI) supuesto | Rango literatura |
|---|---|---|
| Industrial contratado | 200 kcal/kg | 150–250 |
| Comercial no contratado | 400 kcal/kg | 300–450 |
| RSU municipal | 650 kcal/kg | 500–800 |

Los valores de Cl% del catálogo son igualmente referenciales. Ambos deben **calibrarse con la primera campaña de caracterización ISO 21645** en planta.

---

## Escenarios de referencia (validados)

| Escenario | PCI (h) | σ | NCV | Cl | Precio esperado |
|---|---|---|---|---|---|
| RSU municipal predominante | 1.900 | 590 | 5 | 3 | ~50 k COP/t |
| Base EcoSereno realista (20/30/50) | 4.500 | 350 | 3 | 2 | ~207 k COP/t |
| Óptimo con contratos (60/30/10) | 7.700 | 180 | 1 | 2 | ~394 k COP/t |
| Rechazo industrial 100% | 7.540 | 180 | 1 | 1 | ~386 k COP/t |

---

## Referencias

- ISO 21640:2021 — Solid recovered fuels. Specifications and classes
- ISO 21645:2021 — Sampling methods
- ISO 21654:2021 — Determination of calorific value
- Rada, E.C. et al. (2009). RDF/SRF variability characterisation
- Reza, B. et al. (2013). Statistical analysis of SRF properties
- Yale Economic Growth Center (2024). CSR fracción gruesa: nota técnica

---

## Limitaciones

- No modela azufre (S), metales pesados ni fracción biogénica.
- No sustituye la caracterización de laboratorio (ISO 21645, calorímetro de bomba).
- Los valores del catálogo son órdenes de magnitud, no datos validados por muestra real.

---

## Licencia

MIT © 2025 H. Vladimir Martínez-T.
