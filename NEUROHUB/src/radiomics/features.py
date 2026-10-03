"""
Registro de clases de rasgos y su nomenclatura IBSI.

Define QUE se extrae y con que nombre se escribe cada descriptor, separado del
COMO se calcula (eso vive en `texture.py` y `shape.py`). La idea es que las
columnas del CSV usen exactamente los nombres de PyRadiomics, para que un
informe generado aqui sea intercambiable con el de Raidionics o PyRadiomics.
"""

# =============================================================================
# CLASES
# =============================================================================
NOMBRES_CLASES = {
    "firstOrder": "Primera Orden",
    "shape": "Forma",
    "glcm": "GLCM (Co-Ocurrencia)",
    "glrlm": "GLRLM (Serie de Grises)",
    "glszm": "GLSZM (Zonas de Grises)",
    "ngtdm": "NGTDM (Dependencia de Tono)",
    "lsh": "LSH (Histograma Escalado)",
    "lszm": "LSZM (Histograma Escalado de Zona)",
}

# Prefijos de transformacion de imagen (estandar IBSI). El valor es el sigma
# en unidades de vóxel; None significa que no se filtra.
FILTROS_IMAGEN = {
    "original": None,
    "log_sigma_1_0_1": 1.5,
    "log_sigma_2_0_1": 2.5,
    "log_sigma_3_0_1": 3.5,
    "square": None,
    "exponential": None,
    "gradient": None,
    "wavelet": None,
}

# =============================================================================
# RASGOS DE PRIMERA ORDEN (intensidad)
# =============================================================================
# Solo los que no dependen de histogramas normalizados ni de GLCM.
RASGOS_PRIMERA_ORDEN = [
    "Mean", "Median", "Minimum", "Maximum", "Range", "Variance",
    "StandardDeviation", "Skewness", "Kurtosis", "Energy",
    "InterquartileRange", "Percentile_1", "Percentile_10", "Percentile_90",
    "Percentile_99", "UpperOutlierRange", "LowerOutlierRange",
    "RootMeanSquared", "MeanAbsoluteDeviation",
    "RobustMeanAbsoluteDeviation", "RobustMeanAbsoluteDeviationMedian",
    "EnergyMean", "EnergyMedian", "EnergyMinimum", "EnergyMaximum",
    "EnergyRange", "EnergySkewness", "EnergyKurtosis",
    "MeanLog", "VarianceLog", "RootMeanSquaredLog", "EnergyLog2",
    "ExponentialEnergy", "ExponentialEnergyLog2",
    "Entropy", "EntropyLog2", "Uniformity", "UniformityNormalized",
    "EnergyEntropy", "EnergyEntropyLog2",
]

# =============================================================================
# RASGOS DE FORMA
# =============================================================================
# Solo se calculan en la imagen original: son geometricos, no cambian al
# filtrar la imagen. El prefijo `original_` se mantiene por compatibilidad.
RASGOS_FORMA = [
    "MeshVolume", "MeshVolume_mm3", "VoxelVolume", "VoxelVolume_mm3",
    "SurfaceVolume", "SurfaceVolume_mm2", "SurfaceVolumeRatio",
    "SurfaceToVolumeRatio", "VolumeProportion",
    "SurfaceAreaMesh", "SurfaceAreaVoxel", "SurfaceArea_mm2",
    "Compactness1", "Compactness2", "Sphericity", "SphericalDisproportion",
    "Maximum3DDiameter", "Minimum3DDiameter",
    "Elongation", "Flatness", "PrincipalAxis1Length",
    "PrincipalAxis2Length", "PrincipalAxis3Length",
    "PrincipalAxis1Orientation", "PrincipalAxis2Orientation",
    "PrincipalAxis3Orientation",
    "PrincipalMomentsOrder1", "PrincipalMomentsOrder2",
    "PrincipalMomentsOrder3",
    "Eigenvalues1", "Eigenvalues2", "Eigenvalues3",
    "Perimeter", "Perimeter_mm", "Perimeter2D", "Perimeter2D_mm",
    "Perimeter3D", "Perimeter3D_mm",
    "Circularity", "Sphericity2D", "MaximumDiameter2D",
    "MaximumDiameter3D",
    "Gyration", "FeretDiameter", "FeretDiameter2D", "FeretDiameter3D",
]

# =============================================================================
# RASGOS DE TEXTURA
# =============================================================================
# Los rasgos de textura se calculan por clase y comparten nombre base. Los
# nombres finales los compone `extract` con el prefijo del filtro, p. ej.
# `original_GLCM_Autocorrelation`.
RASGOS_TEXTURA = {
    "GLCM": [
        "Autocorrelation", "ClusterProminence", "ClusterShade",
        "ClusterTendency", "Contrast", "Correlation", "DifferenceAverage",
        "DifferenceEntropy", "DifferenceVariance", "JointEntropy",
        "MaximumProbability", "SumEntropy", "SumSquares",
        "InverseDifferenceMoment", "InverseDifferenceMomentNormalized",
        "InverseVariance", "InverseVarianceNormalized",
        "SmallDependenceEmphasis", "LargeDependenceEmphasis",
        "SmallDependenceHighGrayLevelEmphasis",
        "LargeDependenceHighGrayLevelEmphasis", "DependenceNonUniformity",
        "DependenceNonUniformityNormalized", "DependenceNormalized",
        "DependenceVariance", "DependenceVarianceNormalized",
        "DependenceCorrelation", "DependenceEnergy",
        "GrayLevelNonUniformity", "GrayLevelNonUniformityNormalized",
        "GrayLevelVariance", "GrayLevelVarianceNormalized",
        "GrayLevelStandardDeviation", "GrayLevelEntropy",
        "GrayLevelEntropyLog2", "Entropy", "EntropyLog2", "Energy",
        "Homogeneity", "Uniformity", "UniformityNormalized", "Difference",
    ],
    "GLRLM": [
        "RunLengthNonUniformity", "RunLengthNonUniformityNormalized",
        "RunPercentile", "RunEntropy", "RunEntropyLog2", "RunVariance",
        "RunVarianceNormalized", "RunLength", "GrayLevelNonUniformity",
        "GrayLevelNonUniformityNormalized", "GrayLevelVariance",
        "ShortRunEmphasis", "LongRunEmphasis", "GrayLevelEmphasis",
        "LowGrayLevelEmphasis", "HighGrayLevelEmphasis",
    ],
    "GLSZM": [
        "SmallAreaEmphasis", "LargeAreaEmphasis", "GrayLevelEmphasis",
        "HighGrayLevelEmphasis", "LowGrayLevelEmphasis",
        "GrayLevelNonUniformity", "GrayLevelNonUniformityNormalized",
        "GrayLevelVariance", "ZoneEntropy", "ZoneEntropyLog2", "ZoneVariance",
        "ZoneVarianceNormalized", "ZonePercentile", "ZoneCount",
        "ZoneCountNormalized", "ZonePercentage", "AreaMean", "AreaVariance",
        "AreaEntropy", "AreaEntropyLog2", "GrayLevel",
    ],
    "NGTDM": [
        "Coarseness", "CoarsenessNormalized", "Contrast", "Busyness",
        "BusynessNormalized", "Strength", "StrengthNormalized", "Complexity",
        "ComplexityNormalized",
    ],
    "LSH": [
        "HistogramIntensity", "HistogramIntensityNormalized",
        "HistogramIntensityLog2", "Percentile_1", "Percentile_10",
        "Percentile_90", "Percentile_99", "InterquartileRange", "Median",
        "Variance", "VarianceLog", "Skewness", "Kurtosis", "Range",
        "RootMeanSquared", "RootMeanSquaredLog", "MeanLog", "Energy",
        "EnergyLog2", "Entropy", "EntropyLog2", "Minimum", "Maximum",
    ],
}

# =============================================================================
# DESCRIPCIONES
# =============================================================================
# Texto que aparece como tooltip en la tabla de la interfaz, para que el
# radiólogo sepa qué significa cada descriptor sin salir de la aplicación.
DESCRIPCIONES = {
    "Mean": "Intensidad media de la ROI",
    "Median": "Mediana de intensidades",
    "StandardDeviation": "Desviación típica de intensidades",
    "Variance": "Varianza de intensidades",
    "Skewness": "Asimetría de la distribución",
    "Kurtosis": "Curtosis de la distribución",
    "Entropy": "Entropía de Shannon del histograma",
    "Minimum": "Intensidad mínima",
    "Maximum": "Intensidad máxima",
    "Range": "Rango de intensidades (max - min)",
    "RootMeanSquared": "Cuadrado medio de la raíz",
    "Energy": "Suma de intensidades al cuadrado",
    "MeshVolume": "Volumen de la malla (voxelimetría)",
    "MeshVolume_mm3": "Volumen de la malla en mm3",
    "VoxelVolume": "Volumen en número de vóxeles",
    "SurfaceVolume": "Volumen de la superficie (malla)",
    "SurfaceVolume_mm2": "Área de la superficie en mm2",
    "Sphericity": "Esfericidad: 1 = esfera perfecta",
    "Maximum3DDiameter": "Diámetro máximo 3D en mm",
    "Elongation": "Alongación de los ejes principales",
    "Flatness": "Planitud de los ejes principales",
    "SurfaceToVolumeRatio": "Relación superficie/volumen",
    "GLCM_Autocorrelation": "Autocorrelación: similitud de vecinos",
    "GLCM_Contrast": "Contraste local: diferencia entre pares",
    "GLCM_Energy": "Energía (uniformidad) de la co-ocurrencia",
    "GLCM_Entropy": "Entropía de la co-ocurrencia",
    "GLRLM_ShortRunEmphasis": "Énfasis en series cortas",
    "GLRLM_LongRunEmphasis": "Énfasis en series largas",
    "GLRLM_Entropy": "Entropía de la distribución de series",
    "GLSZM_LargeAreaEmphasis": "Énfasis en zonas grandes",
    "GLSZM_SmallAreaEmphasis": "Énfasis en zonas pequeñas",
    "NGTDM_Busyness": "Textura densa o compleja",
    "NGTDM_Complexity": "Complejidad de la textura",
    "NGTDM_Strength": "Fuerza de la diferencia de tono",
}


def nombre_rasgo(clase, rasgo, filtro="original"):
    """
    Compone el nombre final de un descriptor.

    Ejemplos:
        nombre_rasgo("GLCM", "Autocorrelation")
            -> "original_GLCM_Autocorrelation"
        nombre_rasgo("firstOrder", "Mean")
            -> "original_Mean"
    """
    if clase in ("firstOrder", "shape"):
        return f"{filtro}_{rasgo}"
    return f"{filtro}_{clase}_{rasgo}"


def etiqueta_clase(clase):
    """Nombre legible de la clase, para agrupar en la tabla."""
    return NOMBRES_CLASES.get(clase, clase)
