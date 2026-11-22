#if UNITY_EDITOR
using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// Crea y asigna el Universal Render Pipeline del proyecto. Sin un pipeline
/// asset asignado Unity usa el render integrado y los materiales URP (los de
/// los modelos) se dibujan en magenta de error.
///
/// Ajustes pensados para visores autónomos: MSAA 4×, sin HDR, sin sombras
/// (la escena no las usa) y transparencias ordenadas por el renderQueue que
/// asigna el cargador.
/// </summary>
public static class NeuroHubRenderSetup
{
    public const string PipelinePath = "Assets/Settings/NeuroHubURP.asset";
    public const string RendererPath = "Assets/Settings/NeuroHubURP_Renderer.asset";

    [MenuItem("ATLAS/MR/Configurar URP")]
    public static void Ensure()
    {
        UniversalRenderPipelineAsset pipeline = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(PipelinePath);
        if (pipeline == null)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(PipelinePath));
            UniversalRendererData renderer = AssetDatabase.LoadAssetAtPath<UniversalRendererData>(RendererPath);
            if (renderer == null)
            {
                // OnEnable del renderer rellena sus shaders internos en el Editor.
                renderer = ScriptableObject.CreateInstance<UniversalRendererData>();
                AssetDatabase.CreateAsset(renderer, RendererPath);
            }
            pipeline = UniversalRenderPipelineAsset.Create(renderer);
            AssetDatabase.CreateAsset(pipeline, PipelinePath);
        }
        UniversalRendererData data = AssetDatabase.LoadAssetAtPath<UniversalRendererData>(RendererPath);
        if (data != null && data.postProcessData == null)
        {
            data.postProcessData = AssetDatabase.LoadAssetAtPath<PostProcessData>(
                "Packages/com.unity.render-pipelines.universal/Runtime/Data/PostProcessData.asset");
            EditorUtility.SetDirty(data);
        }

        pipeline.msaaSampleCount = 4;
        pipeline.supportsHDR = false;
        pipeline.renderScale = 1f;
        pipeline.shadowDistance = 0f;
        pipeline.supportsCameraDepthTexture = false;
        pipeline.supportsCameraOpaqueTexture = false;
        EditorUtility.SetDirty(pipeline);

        GraphicsSettings.renderPipelineAsset = pipeline;
        int current = QualitySettings.GetQualityLevel();
        for (int i = 0; i < QualitySettings.names.Length; i++)
        {
            QualitySettings.SetQualityLevel(i, false);
            QualitySettings.renderPipeline = pipeline;
        }
        QualitySettings.SetQualityLevel(current, false);
        AssetDatabase.SaveAssets();
        Debug.Log($"ATLAS: URP asignado ({PipelinePath}) en Graphics y en {QualitySettings.names.Length} niveles de calidad.");
    }
}
#endif
