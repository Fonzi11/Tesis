#if UNITY_EDITOR
using UnityEditor;

/// <summary>
/// Ajustes de importación para los FBX de estudios: escala real (metros),
/// normales suavizadas recalculadas, sin materiales propios (los aplica el
/// cargador desde el manifiesto) y sin compresión que altere la geometría.
/// </summary>
public sealed class NeuroHubModelPostprocessor : AssetPostprocessor
{
    private void OnPreprocessModel()
    {
        if (!assetPath.Replace('\\', '/').Contains("/Resources/Studies/")) return;
        ModelImporter importer = (ModelImporter)assetImporter;
        importer.globalScale = 1f;
        importer.useFileScale = true;
        importer.bakeAxisConversion = true;
        importer.materialImportMode = ModelImporterMaterialImportMode.None;
        importer.importNormals = ModelImporterNormals.Calculate;
        importer.normalCalculationMode = ModelImporterNormalCalculationMode.AreaAndAngleWeighted;
        importer.normalSmoothingAngle = 70f;
        importer.importTangents = ModelImporterTangents.None;
        importer.meshCompression = ModelImporterMeshCompression.Off;
        importer.meshOptimizationFlags = MeshOptimizationFlags.Everything;
        importer.indexFormat = ModelImporterIndexFormat.Auto;
        importer.isReadable = false;
        importer.weldVertices = true;
        importer.importAnimation = false;
        importer.animationType = ModelImporterAnimationType.None;
        importer.importCameras = false;
        importer.importLights = false;
        importer.importBlendShapes = false;
        importer.addCollider = false;
    }
}
#endif
